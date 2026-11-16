# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Streaming response parsing, argument validation, and API format conversion."""

from __future__ import annotations

import asyncio
import json
import re
import types
from typing import Any

import openai


MAX_EFFORT_MODELS = ("claude", "glm", "gpt-6", "deepseek-v4")
RESPONSES_MODELS = ("gpt-6",)
RESPONSES_ONLY = re.compile(
    r"/v1/responses|not supported.{0,80} in /v1/chat/completions"
)
CONTEXT_FULL = re.compile(
    r"context.?(length|window|size|limit)|maximum context|too many"
    r" tokens|prompt is too long|maximum prompt length"
    r"|(input|prompt|request|messages?)\b[^.]{0,40}(too long|exceed)"
    r"|exceed[^.]{0,40}(token|context)",
    re.I,
)
WINDOW_RE = re.compile(
    r"maximum context length (?:is |of )?(\d+)"
    r"|context (?:window|length|size)(?: limit)?(?: is| of)? (\d+)"
    r"|tokens? > (\d+) maximum|maximum number of tokens allowed \((\d+)\)"
    r"|maximum prompt length is (\d+)",
    re.I,
)
PROMPT_RE = re.compile(
    r"(\d+) input tokens|(\d+) in the messages|prompt is too long: (\d+)"
    r"|input token count \((\d+)\)|request contains (\d+) tokens",
    re.I,
)
UNSUPPORTED = re.compile(
    r"unsupported|unrecogni[sz]ed|unknown|not supported|does not support|not"
    r" (allowed|permitted)"
    r"|extra (inputs|fields)|unexpected",
    re.I,
)
CALL_FIELDS = {"index", "id", "type", "function"}
FUNCTION_FIELDS = {"name", "arguments"}
DELTA_FIELDS = {
    "role",
    "content",
    "tool_calls",
    "function_call",
    "refusal",
    "audio",
    "annotations",
    "reasoning_content",
    "reasoning",
}
BAD_REQUEST = frozenset({
    "invalid_request_error",
    "context_length_exceeded",
    "invalid_value",
    "invalid_prompt",
})


def default_effort(model: str, explicit: str | None = None) -> str:
  """Selects reasoning effort (`max` for frontier Claude/GLM/GPT-6/DeepSeek, else `high`)."""
  if explicit and explicit.strip():
    return explicit.strip()
  return "max" if any(m in model.lower() for m in MAX_EFFORT_MODELS) else "high"


def clip(text: str, limit: int = 30_000) -> str:
  """Truncates `text` in the middle if it exceeds `limit` characters."""
  if len(text) <= limit:
    return text
  head = limit * 2 // 3
  return (
      f"{text[:head]}\n[... {len(text) - limit} characters cut"
      f" ...]\n{text[-(limit - head):]}"
  )


def parse_arguments(call: dict[str, Any]) -> dict[str, Any] | str:
  """Parses a tool call's arguments into a dict or returns a recoverable error string."""

  def reject(constant: str) -> None:
    raise ValueError(f"{constant} is not valid JSON")

  try:
    args = json.loads(call.get("arguments") or "{}", parse_constant=reject)
    if not isinstance(args, dict):
      raise ValueError("the arguments must be a JSON object")
    call["arguments"] = (
        json.dumps(args, ensure_ascii=False)
        .encode("utf-8", "replace")
        .decode("utf-8")
    )
    return args
  except ValueError as exc:
    call["arguments"] = "{}"
    return (
        f"error: the arguments are not a valid JSON object ({exc}); send the"
        " call again"
    )


def unique_name(name: str, taken: Any) -> str:
  """Truncates `name` to 64 chars and appends `_2`, `_3`, ... if already taken."""
  candidate, n = name[:64], 1
  while candidate in taken:
    n += 1
    candidate = f"{name[:63 - len(str(n))]}_{n}"
  return candidate


def visible(text: str) -> str:
  """Strips inline `<think>...</think>` blocks from `text`."""
  return re.sub(r"<think>.*?(</think>|$)", "", text or "", flags=re.S).strip()


def extra_fields(part: Any, known: set[str]) -> dict[str, Any]:
  """Extracts non-null provider-specific extra fields beyond `known`."""
  fields = getattr(part, "model_extra", None) or {}
  return {k: v for k, v in fields.items() if k not in known and v is not None}


def merged(old: Any, new: Any, key: str = "") -> Any:
  """Merges streamed delta extra field `new` into `old`."""
  if key == "thinking_blocks" and isinstance(new, list):
    return thinking_blocks(old if isinstance(old, list) else [], new)
  if isinstance(old, dict) and isinstance(new, dict):
    return {**old, **{k: merged(old.get(k), v, k) for k, v in new.items()}}
  if isinstance(old, list) and isinstance(new, list):
    return old + new
  return new


def thinking_blocks(
    blocks: list[dict[str, Any]], new: list[Any]
) -> list[dict[str, Any]]:
  """Accumulates streamed Claude `thinking_blocks` deltas until closed by `signature`."""
  out = [dict(b) for b in blocks]
  for b in new:
    if not isinstance(b, dict):
      continue
    last = out[-1] if out else None
    if (
        last is None
        or last.get("signature")
        or last.get("data")
        or b.get("data")
        or last.get("type") != b.get("type")
    ):
      out.append(dict(b))
      continue
    last["thinking"] = (last.get("thinking") or "") + (b.get("thinking") or "")
    if b.get("signature"):
      last["signature"] = b["signature"]
  return out


def signed(block: Any) -> bool:
  """Returns True when a thinking block carries a valid `signature` or redacted `data`."""
  return isinstance(block, dict) and bool(
      block.get("signature") or block.get("data")
  )


def drop_thinking(
    message: dict[str, Any], unless: Any = lambda block: False
) -> dict[str, Any]:
  """Filters `thinking_blocks` on an assistant message using predicate `unless`."""
  if isinstance(message.get("thinking_blocks"), list):
    message["thinking_blocks"] = [
        b for b in message["thinking_blocks"] if unless(b)
    ]
  fields = message.get("provider_specific_fields")
  if isinstance(fields, dict) and isinstance(
      fields.get("thinking_blocks"), list
  ):
    message["provider_specific_fields"] = {
        **fields,
        "thinking_blocks": [b for b in fields["thinking_blocks"] if unless(b)],
    }
  return message


def marked(messages: list[dict[str, Any]], cache_mark: bool = False) -> list[dict[str, Any]]:
  """Marks first and last messages with Anthropic prompt cache breakpoints when enabled."""
  if not cache_mark or not messages:
    return messages
  out = list(messages)
  for i in {0, len(out) - 1}:
    m, content = out[i], out[i].get("content")
    if isinstance(content, str) and content:
      out[i] = {
          **m,
          "content": [{
              "type": "text",
              "text": content,
              "cache_control": {"type": "ephemeral"},
          }],
      }
    else:
      out[i] = {**m, "cache_control": {"type": "ephemeral"}}
  return out


def merge_or_append_user(messages: list[dict[str, Any]], prompt: str) -> None:
  """Appends `prompt` as a user turn, merging if the trailing message is already `user`.

  Consecutive `role="user"` messages stall Gemini 4 Argon Vertex streams by up to ~600s
  on initial planning; merging avoids back-to-back user turns while keeping exact text.
  """
  if messages and messages[-1].get("role") == "user":
    prev = messages[-1].get("content")
    if isinstance(prev, list):
      messages[-1]["content"] = prev + [{"type": "text", "text": prompt}]
    elif isinstance(prev, str) and prev:
      messages[-1]["content"] = f"{prev}\n\n{prompt}"
    else:
      messages[-1]["content"] = prompt
  else:
    messages.append({"role": "user", "content": prompt})


def response_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Converts Chat Completions history into Responses API input items."""
  items: list[dict[str, Any]] = []
  for m in messages:
    if m["role"] == "tool":
      items.append({
          "type": "function_call_output",
          "call_id": m["tool_call_id"],
          "output": m["content"],
      })
    elif m["role"] != "assistant":
      items.append({"role": m["role"], "content": m["content"]})
    elif "output_items" in m:
      calls = iter(m.get("tool_calls") or [])
      for item in m["output_items"]:
        call = next(calls, None) if item.get("type") == "function_call" else None
        if call:
          item = {
              **item,
              "call_id": call["id"],
              "name": call["function"]["name"],
              "arguments": call["function"]["arguments"],
          }
        items.append(item)
    else:
      if m.get("content"):
        items.append({"role": "assistant", "content": m["content"]})
      items += [
          {
              "type": "function_call",
              "call_id": c["id"],
              "name": c["function"]["name"],
              "arguments": c["function"]["arguments"],
          }
          for c in m.get("tool_calls") or []
      ]
  return items


def chat_usage(usage: Any) -> Any:
  """Normalizes Responses API usage fields into Chat Completions shape."""
  if usage is None:
    return None
  details = getattr(usage, "input_tokens_details", None)
  return types.SimpleNamespace(
      prompt_tokens=usage.input_tokens or 0,
      completion_tokens=usage.output_tokens or 0,
      prompt_tokens_details=types.SimpleNamespace(
          cached_tokens=getattr(details, "cached_tokens", 0) or 0
      ),
  )


class Reply:
  """Accumulates streamed completion text, reasoning, tool calls, and usage."""

  def __init__(self) -> None:
    self.text = ""
    self.reasoning = ""
    self.calls: dict[int, dict[str, Any]] = {}
    self.usage: Any = None
    self.finish: str | None = None
    self.extra: dict[str, Any] = {}
    self._by_index: dict[Any, int] = {}
    self._by_id: dict[str, int] = {}
    self._last: int | None = None

  def add_call(self, part: Any) -> None:
    """Adds one streamed tool-call delta to the accumulated call map."""
    index = getattr(part, "index", None)
    call_id = getattr(part, "id", None) or ""
    function = getattr(part, "function", None)
    name = (getattr(function, "name", None) or "") if function else ""
    key = self._by_index.get(index) if index is not None else None
    if (
        key is not None
        and call_id
        and self.calls[key]["id"] not in ("", call_id)
    ):
      key = None
    if (
        key is not None
        and not call_id
        and name
        and self._another_call(self.calls[key], name)
    ):
      key = None
    if key is None and call_id:
      key = self._by_id.get(call_id)
    if (
        key is None
        and index is None
        and not call_id
        and self._last is not None
        and not (name and self._another_call(self.calls[self._last], name))
    ):
      key = self._last
    if key is None:
      key = len(self.calls)
      self.calls[key] = {
          "id": "",
          "name": "",
          "arguments": "",
          "extra": {},
          "function_extra": {},
      }
    if index is not None:
      self._by_index[index] = key
    if call_id:
      self._by_id[call_id] = key
    call = self.calls[key]
    call["id"] = call["id"] or call_id
    call["name"] = call["name"] or name
    call["arguments"] += (
        (getattr(function, "arguments", None) or "") if function else ""
    )
    call["extra"] = merged(call["extra"], extra_fields(part, CALL_FIELDS))
    if function:
      call["function_extra"] = merged(
          call["function_extra"], extra_fields(function, FUNCTION_FIELDS)
      )
    self._last = key

  @staticmethod
  def _another_call(call: dict[str, Any], name: str) -> bool:
    if not call["name"]:
      return False
    if name != call["name"]:
      return True
    try:
      return isinstance(json.loads(call["arguments"]), dict)
    except ValueError:
      return False

  def message(self) -> dict[str, Any]:
    """Builds the stored assistant message dict while stripping unsigned thinking blocks."""
    message: dict[str, Any] = {
        **self.extra,
        "role": "assistant",
        "content": self.text or None,
    }
    if self.calls:
      message["tool_calls"] = [
          {
              **c["extra"],
              "id": c["id"],
              "type": "function",
              "function": {
                  **c["function_extra"],
                  "name": c["name"],
                  "arguments": c["arguments"],
              },
          }
          for c in self.calls.values()
      ]
    if self.reasoning:
      message["reasoning_content"] = self.reasoning
    return drop_thinking(message, unless=signed)


class OutOfTime(Exception):  # pylint: disable=g-bad-exception-name
  """Raised when retrying a failed model call would exceed the time budget."""


class CutOff(asyncio.TimeoutError):  # pylint: disable=g-bad-exception-name
  """Raised when a streamed reply is cut off by its per-call deadline."""


class StreamBadRequest(openai.OpenAIError):  # pylint: disable=g-bad-exception-name
  """Raised when an SSE stream reports a non-retryable bad request error."""


class StreamCut(openai.OpenAIError):  # pylint: disable=g-bad-exception-name
  """Raised when an SSE stream ends prematurely or reports a transient error."""


def stream_error(error: Any) -> openai.OpenAIError:
  """Classifies an in-stream error payload as bad-request vs retryable cut."""

  def field(name: str) -> Any:
    return error.get(name) if isinstance(error, dict) else getattr(error, name, None)

  message = str(field("message") or "")
  named = {field("type"), field("code")} & BAD_REQUEST
  if named or CONTEXT_FULL.search(message):
    return StreamBadRequest(message)
  return StreamCut(f"the stream reported an error: {message}")
