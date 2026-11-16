"""Unit tests for phase orchestration, user-turn merging, and budget guardrails in serve.py."""

from __future__ import annotations

import asyncio
import json

import serve
from aura_harness.config import HarnessConfig, ModelLimits, PhaseBudgets, TelemetryConfig
from aura_harness.stream import Reply
from aura_harness.telemetry import TelemetryLogger
from conftest import FakeSession


def test_is_pass_recognition() -> None:
  assert serve.is_pass("PASS") is True
  assert serve.is_pass("  **PASS**.  \n") is True
  assert serve.is_pass("") is True
  assert serve.is_pass("/app/out.ifc: missing site setback") is False


def test_run_phase_merges_initial_user_message_and_handles_length_cut(tmp_path, monkeypatch) -> None:
  cfg = HarnessConfig(
      phase_budgets=PhaseBudgets(),
      model_limits=ModelLimits(retry_waits=(0,), finish_margin_sec=5),
      telemetry=TelemetryConfig(enabled=False),
  )
  sess = FakeSession(instruction="Design model.ifc")
  agent = serve.PhaseAgent(sess, config=cfg)
  agent.messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": sess.instruction}]

  seen_turns: list[list[dict]] = []
  calls = {"n": 0}

  async def fake_complete(tool_choice="auto", reserve=None, head=None):
    calls["n"] += 1
    seen_turns.append([dict(m) for m in agent.messages])
    r = Reply()
    if calls["n"] == 1:
      r.text = "Part 1 "
      r.finish = "length"
    else:
      r.text = "Part 2"
      r.finish = "stop"
    return r

  monkeypatch.setattr(agent, "complete", fake_complete)
  out = asyncio.run(agent.run_phase("Write plan.", budget=120.0))
  assert out == "Part 1 Part 2"
  # First complete() call MUST have exactly [system, merged_user] with zero consecutive user turns
  assert [m["role"] for m in seen_turns[0]] == ["system", "user"]
  assert "Design model.ifc" in seen_turns[0][1]["content"]
  assert "Write plan." in seen_turns[0][1]["content"]


def test_solve_runs_plan_work_verify_repair_and_writes_telemetry(tmp_path, monkeypatch) -> None:
  cfg = HarnessConfig(
      phase_budgets=PhaseBudgets(
          plan_share=0.10,
          plan_max_sec=600,
          verify_share=0.30,
          verify_round_share=0.35,
          verify_max_sec=900,
          max_repair_rounds=3,
          min_repair_sec=10,
          wrap_sec=5,
      ),
      model_limits=ModelLimits(retry_waits=(0,), finish_margin_sec=2),
      telemetry=TelemetryConfig(
          enabled=True,
          path=str(tmp_path / "tel.jsonl"),
          summary_path=str(tmp_path / "sum.json"),
      ),
  )
  sess = FakeSession(time_budget_sec=3600.0)
  tel = TelemetryLogger(
      enabled=True,
      path=tmp_path / "tel.jsonl",
      summary_path=tmp_path / "sum.json",
      session_id="phase-test",
  )

  phase_calls: list[tuple[str, float | None]] = []

  async def fake_run_phase(self, prompt: str, budget: float | None) -> str:
    if "planning engineer" in prompt:
      phase_calls.append(("plan", budget))
      return "Plan saved."
    if "working engineer" in prompt:
      phase_calls.append(("work", budget))
      return "Delivered /app/work/out.pdf."
    if "independent reviewing engineer" in prompt:
      verifies = sum(1 for k, _ in phase_calls if k == "verify")
      phase_calls.append(("verify", budget))
      return "/app/work/out.pdf: missing section 2" if verifies == 0 else "PASS"
    if "found these gaps" in prompt:
      phase_calls.append(("repair", budget))
      return "Delivered /app/work/out.pdf with section 2."
    raise AssertionError(f"Unexpected prompt: {prompt}")

  monkeypatch.setattr(serve.PhaseAgent, "run_phase", fake_run_phase)
  ans = asyncio.run(serve.solve(sess, config=cfg, telemetry=tel))
  assert "section 2" in ans
  assert [p for p, _ in phase_calls] == ["plan", "work", "verify", "repair", "verify"]

  summary = json.loads((tmp_path / "sum.json").read_text(encoding="utf-8"))
  assert summary["status"] == "completed"
  assert [p["status"] for p in summary["phases"]] == ["done", "done", "gaps", "done", "pass"]


def test_solve_skips_verify_when_remaining_time_below_guard(tmp_path, monkeypatch) -> None:
  cfg = HarnessConfig(
      phase_budgets=PhaseBudgets(min_repair_sec=600, wrap_sec=300),
      model_limits=ModelLimits(retry_waits=(0,), finish_margin_sec=5),
      telemetry=TelemetryConfig(enabled=False),
  )
  # Only 100s budget (< min_repair_sec + wrap_sec = 900s) -> verify must skip cleanly
  sess = FakeSession(time_budget_sec=100.0)
  seen: list[str] = []

  async def fake_run_phase(self, prompt: str, budget: float | None) -> str:
    if "planning engineer" in prompt:
      seen.append("plan")
      return "plan"
    if "working engineer" in prompt:
      seen.append("work")
      return "early-work"
    seen.append("verify")
    return "PASS"

  monkeypatch.setattr(serve.PhaseAgent, "run_phase", fake_run_phase)
  out = asyncio.run(serve.solve(sess, config=cfg))
  assert out == "early-work"
  assert seen == ["plan", "work"]
