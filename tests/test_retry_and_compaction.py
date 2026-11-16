"""Unit tests for Agent retries, 400 error remedies, and context compaction."""

from __future__ import annotations

import asyncio
import json
import types

import httpx
import openai
import pytest

import engine
from aura_harness.stream import OutOfTime, Reply
from conftest import FakeSession, make_stream_chunk, make_test_config


def _api_status_error(status: int, message: str) -> openai.APIStatusError:
  req = httpx.Request("POST", "http://localhost:4000/v1/chat/completions")
  resp = httpx.Response(status_code=status, request=req, json={"error": {"message": message}})
  return openai.APIStatusError(message=message, response=resp, body={"error": {"message": message}})


def test_learn_context_and_output_limits(tmp_path) -> None:
  cfg = make_test_config(tmp_path, max_output_tokens=32000, compact_at_tokens=150000)
  agent = engine.Agent(FakeSession(), config=cfg)

  err = "maximum context length is 200000 tokens, however you requested 180000 in the messages"
  assert agent.learn_context(err) is True
  assert agent.context_window == 200000
  assert agent.prompt_tokens == 180000
  assert agent.room() == 200000 - 180000 - 1024
  assert agent.output_limit() == 200000 - 180000 - 1024
  assert agent.compact_at() == 150000


def test_shrink_output_and_parameter_remedies(tmp_path) -> None:
  cfg = make_test_config(tmp_path)
  agent = engine.Agent(FakeSession(), config=cfg)
  agent.max_output = 32000

  assert asyncio.run(agent.remedy("Unsupported parameter: max_completion_tokens is unknown")) is True
  assert agent.token_limit == "max_tokens"

  assert asyncio.run(agent.remedy("Extra inputs: reasoning_effort is unsupported")) is True
  assert agent.effort == {}

  assert asyncio.run(agent.remedy("max_tokens must be at most 16384")) is True
  assert agent.output_ceiling == 16384

  assert asyncio.run(agent.remedy("Only supported on /v1/responses")) is True
  assert agent.responses is True


def test_compact_preserves_recent_and_unread_and_summarizes_when_forced(tmp_path, monkeypatch) -> None:
  cfg = make_test_config(tmp_path, keep_recent_results=2, compact_at_tokens=5000)
  sess = FakeSession()
  agent = engine.Agent(sess, config=cfg)
  agent.context_window = 10000
  agent.messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "goal"}]
  for i in range(10):
    agent.messages.append({
        "role": "assistant",
        "content": "step",
        "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": "bash", "arguments": "{}"}}],
    })
    agent.messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": ("X" * 2000)})
  # Trailing unread tool result after final assistant turn
  agent.messages.append({"role": "assistant", "content": "last"})
  agent.messages.append({"role": "tool", "tool_call_id": "unread", "content": "U" * 2000})

  changed = asyncio.run(agent.compact(force=False))
  assert changed is True
  # Last 2 read tool results + unread tool result must remain untouched
  assert agent.messages[-1]["content"] == "U" * 2000
  assert agent.messages[-3]["content"] == "X" * 2000
  assert "removed to save context" in agent.messages[3]["content"]

  # Forced compaction summarizes via stream() when still over window
  async def fake_stream(messages, tool_choice, reserve, head=None):
    r = Reply()
    r.text = "Summary of engineering calculations so far."
    r.finish = "stop"
    return r

  monkeypatch.setattr(agent, "stream", fake_stream)
  agent.context_window = 2000
  agent.prompt_tokens = 9000
  before_len = len(agent.messages)
  assert asyncio.run(agent.compact(force=True)) is True
  assert len(agent.messages) < before_len
  assert "Summary of engineering calculations" in agent.messages[2]["content"]


def test_cut_unread_truncates_oversized_trailing_outputs(tmp_path) -> None:
  cfg = make_test_config(tmp_path, unread_keep=600)
  agent = engine.Agent(FakeSession(), config=cfg)
  agent.messages = [
      {"role": "system", "content": "s"},
      {"role": "assistant", "content": "a"},
      {"role": "tool", "tool_call_id": "u1", "content": "Y" * 5000},
  ]
  assert agent.cut_unread() is True
  assert len(agent.messages[-1]["content"]) < 5000


def test_complete_retries_on_400_remedy_and_429_and_raises_out_of_time(tmp_path, monkeypatch) -> None:
  cfg = make_test_config(tmp_path, finish_margin_sec=5)
  sess = FakeSession(time_budget_sec=60.0)
  agent = engine.Agent(sess, config=cfg)

  calls = {"n": 0}

  class FakeAsyncCompletions:
    async def create(self, **kwargs):
      calls["n"] += 1
      if calls["n"] == 1:
        raise _api_status_error(400, "Unsupported parameter: max_completion_tokens")
      if calls["n"] == 2:
        raise _api_status_error(429, "rate limit")

      async def gen():
        yield make_stream_chunk(content="DONE_OK")
        yield make_stream_chunk(
            finish_reason="stop",
            usage=types.SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=2,
                prompt_tokens_details=types.SimpleNamespace(cached_tokens=4),
            ),
        )

      return gen()

  monkeypatch.setattr(
      engine,
      "client",
      types.SimpleNamespace(chat=types.SimpleNamespace(completions=FakeAsyncCompletions())),
  )

  reply = asyncio.run(agent.complete())
  assert calls["n"] == 3
  assert agent.token_limit == "max_tokens"
  assert reply.text == "DONE_OK"
  assert sess.usage_events and sess.usage_events[-1][1:] == (10, 2, 4)

  # Verify OutOfTime triggers when remaining budget cannot fit retry wait
  cfg_wait = make_test_config(tmp_path)
  cfg_wait = cfg_wait.__class__(
      phase_budgets=cfg_wait.phase_budgets,
      model_limits=cfg_wait.model_limits.__class__(retry_waits=(30,), finish_margin_sec=5),
      telemetry=cfg_wait.telemetry,
  )
  sess_short = FakeSession(time_budget_sec=10.0)
  agent_short = engine.Agent(sess_short, config=cfg_wait)

  class Always429:
    async def create(self, **kwargs):
      raise _api_status_error(429, "rate limit")

  monkeypatch.setattr(
      engine,
      "client",
      types.SimpleNamespace(chat=types.SimpleNamespace(completions=Always429())),
  )
  with pytest.raises(OutOfTime):
    asyncio.run(agent_short.complete())


def test_find_mcp_tools_ranks_exact_and_keyword_matches(tmp_path) -> None:
  cfg = make_test_config(tmp_path)
  agent = engine.Agent(FakeSession(), config=cfg)
  mcp_map = {
      "cad__draw_line": (None, {"description": "Draw CAD line", "inputSchema": {"type": "object"}}),
      "sheet__read_cell": (None, {"description": "Read Excel cell value", "inputSchema": {"type": "object"}}),
  }
  agent.mcp = mcp_map
  out = agent.find_mcp("read cell")
  assert "sheet__read_cell" in out
  miss = agent.find_mcp("zzzznonexistent")
  assert "no tool matches" in miss
