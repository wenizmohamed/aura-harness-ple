"""Unit tests for streaming deltas, argument parsing, cache marking, and user merging."""

from __future__ import annotations

import types

from aura_harness.stream import (
    Reply,
    StreamBadRequest,
    StreamCut,
    chat_usage,
    clip,
    default_effort,
    marked,
    merge_or_append_user,
    parse_arguments,
    response_input,
    stream_error,
    unique_name,
    visible,
)


def test_parse_arguments_valid_and_normalizes() -> None:
  call = {"arguments": '{"path": "out.txt", "count": 2}'}
  parsed = parse_arguments(call)
  assert parsed == {"path": "out.txt", "count": 2}
  assert call["arguments"] == '{"path": "out.txt", "count": 2}'


def test_parse_arguments_empty_defaults_to_dict() -> None:
  call = {"arguments": ""}
  assert parse_arguments(call) == {}
  assert call["arguments"] == "{}"


def test_parse_arguments_rejects_non_object_and_nan() -> None:
  bad_array = {"arguments": "[1, 2, 3]"}
  res = parse_arguments(bad_array)
  assert isinstance(res, str) and "JSON object" in res
  assert bad_array["arguments"] == "{}"

  bad_nan = {"arguments": '{"x": NaN}'}
  res2 = parse_arguments(bad_nan)
  assert isinstance(res2, str) and "NaN is not valid JSON" in res2
  assert bad_nan["arguments"] == "{}"

  malformed = {"arguments": '{"path": "unclosed'}
  res3 = parse_arguments(malformed)
  assert isinstance(res3, str) and res3.startswith("error:")
  assert malformed["arguments"] == "{}"


def test_reply_accumulates_indexed_and_nameless_tool_calls_and_filters_thinking() -> None:
  reply = Reply()
  fn1_a = types.SimpleNamespace(name="bash", arguments='{"command":', model_extra={})
  fn1_b = types.SimpleNamespace(name=None, arguments='"ls"}', model_extra={})
  p1 = types.SimpleNamespace(
      index=0,
      id="call_1",
      function=fn1_a,
      model_extra={"extra_content": {"thought_signatures": ["sig_abc"]}},
  )
  p2 = types.SimpleNamespace(index=0, id=None, function=fn1_b, model_extra={})
  fn2 = types.SimpleNamespace(name="read_file", arguments='{"path":"a"}', model_extra={})
  p3 = types.SimpleNamespace(index=None, id=None, function=fn2, model_extra={})
  reply.add_call(p1)
  reply.add_call(p2)
  reply.add_call(p3)
  reply.text = "Running checks."
  reply.extra = {
      "thinking_blocks": [
          {"type": "thinking", "thinking": "unsigned"},
          {"type": "thinking", "thinking": "signed", "signature": "ok_sig"},
      ]
  }
  msg = reply.message()
  assert len(msg["tool_calls"]) == 2
  assert msg["tool_calls"][0]["function"]["name"] == "bash"
  assert msg["tool_calls"][0]["function"]["arguments"] == '{"command":"ls"}'
  assert msg["tool_calls"][0]["extra_content"] == {"thought_signatures": ["sig_abc"]}
  assert msg["tool_calls"][1]["function"]["name"] == "read_file"
  assert msg["thinking_blocks"] == [{"type": "thinking", "thinking": "signed", "signature": "ok_sig"}]


def test_merge_or_append_user_prevents_consecutive_user_turns() -> None:
  msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "instr"}]
  merge_or_append_user(msgs, "PLAN")
  assert len(msgs) == 2
  assert msgs[1]["role"] == "user"
  assert msgs[1]["content"] == "instr\n\nPLAN"

  msgs.append({"role": "assistant", "content": "planned"})
  merge_or_append_user(msgs, "WORK")
  assert len(msgs) == 4
  assert msgs[3] == {"role": "user", "content": "WORK"}


def test_merge_or_append_user_handles_list_content() -> None:
  msgs = [{"role": "user", "content": [{"type": "text", "text": "part1"}]}]
  merge_or_append_user(msgs, "part2")
  assert len(msgs) == 1
  assert msgs[0]["content"] == [
      {"type": "text", "text": "part1"},
      {"type": "text", "text": "part2"},
  ]


def test_stream_error_classification_and_text_helpers() -> None:
  assert isinstance(stream_error({"type": "context_length_exceeded", "message": "full"}), StreamBadRequest)
  assert isinstance(stream_error({"message": "This prompt is too long: 210000 input tokens"}), StreamBadRequest)
  assert isinstance(stream_error({"type": "server_error", "message": "temporary reset"}), StreamCut)

  assert visible("<think>hidden</think>final answer") == "final answer"
  assert visible("<think>unclosed") == ""
  assert clip("0123456789", 6) != "0123456789"
  assert unique_name("same_tool", {"same_tool"}) == "same_tool_2"
  assert default_effort("google-cloud/gemini-4-argon") == "high"
  assert default_effort("claude-opus-5-5") == "max"


def test_marked_and_response_input_and_chat_usage() -> None:
  base = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
  assert marked(base, cache_mark=False) is base
  mk = marked(base, cache_mark=True)
  assert mk[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
  assert mk[1]["content"][0]["cache_control"] == {"type": "ephemeral"}

  items = response_input([
      {"role": "system", "content": "s"},
      {"role": "assistant", "content": "thinking", "tool_calls": [{"id": "c1", "function": {"name": "bash", "arguments": "{}"}}]},
      {"role": "tool", "tool_call_id": "c1", "content": "done"},
  ])
  assert items[1]["role"] == "assistant"
  assert items[2]["type"] == "function_call"
  assert items[3] == {"type": "function_call_output", "call_id": "c1", "output": "done"}

  cu = chat_usage(types.SimpleNamespace(
      input_tokens=100,
      output_tokens=20,
      input_tokens_details=types.SimpleNamespace(cached_tokens=80),
  ))
  assert cu.prompt_tokens == 100 and cu.completion_tokens == 20
  assert cu.prompt_tokens_details.cached_tokens == 80
