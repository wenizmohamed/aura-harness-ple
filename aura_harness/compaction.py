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

"""Context-window estimation, compaction, and 400 error parameter recovery."""

from __future__ import annotations

import json
import re
from typing import Any

from aura_harness.stream import PROMPT_RE, RESPONSES_ONLY, UNSUPPORTED, WINDOW_RE, clip


def learn_context_from_error(
    error: str,
    current_window: int | None,
    current_prompt: int,
) -> tuple[bool, int | None, int]:
  """Extracts context window and prompt token counts from an overflow error string."""
  window, prompt = WINDOW_RE.search(error), PROMPT_RE.search(error)
  new_window = int(next(g for g in window.groups() if g)) if window else current_window
  new_prompt = int(next(g for g in prompt.groups() if g)) if prompt else current_prompt
  return bool(prompt and new_window), new_window, new_prompt


def room_tokens(
    context_window: int | None,
    prompt_tokens: int,
    context_margin: int = 1024,
) -> int | None:
  """Returns remaining output token room in a known context window, or None."""
  if not context_window:
    return None
  return context_window - prompt_tokens - context_margin


def compute_output_limit(
    output_ceiling: int,
    min_output: int,
    context_window: int | None,
    prompt_tokens: int,
    context_margin: int = 1024,
) -> int:
  """Clamps `output_ceiling` to available room while staying at least `min_output`."""
  avail = room_tokens(context_window, prompt_tokens, context_margin)
  return (
      output_ceiling
      if avail is None
      else max(min_output, min(output_ceiling, avail))
  )


def compute_compact_at(
    compact_at_tokens: int,
    output_ceiling: int,
    context_window: int | None,
    context_margin: int = 1024,
) -> int:
  """Returns the prompt token compaction threshold adapted to `context_window`."""
  if not context_window:
    return compact_at_tokens
  reserve = min(output_ceiling, context_window // 2)
  return max(
      context_window // 4,
      min(compact_at_tokens, context_window - reserve - context_margin),
  )


def estimate_prompt_tokens(messages: list[dict[str, Any]]) -> int:
  """Estimates token count at four serialized JSON chars per token."""
  return (
      sum(
          len(json.dumps({k: v for k, v in m.items() if k != "output_items"}))
          for m in messages
      )
      // 4
  )


def unread_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Returns trailing tool-result messages appended after the final assistant turn."""
  last = max(
      (n for n, m in enumerate(messages) if m.get("role") == "assistant"),
      default=0,
  )
  return [m for m in messages[last:] if m.get("role") == "tool"]


def trim_old_tool_results(
    messages: list[dict[str, Any]],
    *,
    force: bool,
    keep_recent_results: int,
    compact_threshold: int,
    prompt_tokens: int,
    context_window: int | None,
) -> list[int]:
  """Shortens historical tool outputs while protecting unread and recent tool results."""
  unread = {id(m) for m in unread_messages(messages)}
  results = [(n, m) for n, m in enumerate(messages) if m.get("role") == "tool"]
  candidates = results if force else (
      results[:-keep_recent_results] if keep_recent_results > 0 else results
  )
  size = max(estimate_prompt_tokens(messages), prompt_tokens if force else 0)
  cuts: list[int] = []
  for n, m in candidates:
    if force and context_window and size <= compact_threshold:
      break
    content = m.get("content") or ""
    if len(content) > 600 and id(m) not in unread:
      size -= (len(content) - 400) // 4
      m["content"] = (
          content[:400]
          + "\n[... removed to save context; run the tool again if needed ...]"
      )
      cuts.append(n)
  return cuts


def find_summary_cut_index(messages: list[dict[str, Any]]) -> int | None:
  """Finds a safe boundary to splice old turns into summary notes."""
  cut = len(messages) - 6
  while cut > 3 and messages[cut].get("role") == "tool":
    cut -= 1
  return None if cut < 10 else cut


def shrink_unread_messages(
    messages: list[dict[str, Any]],
    *,
    unread_keep: int,
    compact_threshold: int,
    context_window: int | None,
) -> bool:
  """Truncates unread tool results as a last resort when context overflows."""
  unread = [
      m for m in unread_messages(messages) if len(m.get("content") or "") > 2 * unread_keep
  ]
  if not unread:
    return False
  share = None
  if context_window:
    rest = (
        estimate_prompt_tokens(messages)
        - sum(len(m.get("content") or "") for m in unread) // 4
    )
    share = (compact_threshold - rest) * 4 // len(unread)
  for m in unread:
    content = m.get("content") or ""
    size = len(content)
    keep = size // 2 if share is None or share >= size - 100 else share
    m["content"] = clip(content, max(unread_keep, keep))
  return True


def parse_smaller_output_limit(
    error: str, current_max_output: int, min_output: int
) -> int | None:
  """Parses a reduced `max_tokens` ceiling from a 400 error message."""
  if UNSUPPORTED.search(error):
    return None
  limit = re.search(r"(\d+)\s*\(exclusive\)", error)
  stated = re.search(
      r"at most (\d+)|(\d+), which is the maximum|maximum (?:allowed"
      r" )?(?:number of )?(?:output|completion) tokens (?:is |of )?(\d+)",
      error,
      re.I,
  )
  if limit:
    new = int(limit.group(1)) - 1
  elif stated:
    new = int(next(g for g in stated.groups() if g))
  elif re.search(
      r"max_?(completion_)?tokens|maxOutputTokens|output tokens", error, re.I
  ):
    new = current_max_output // 2
  else:
    return None
  if new >= current_max_output or new < min_output:
    return None
  return new


def should_use_responses(error: str, already_responses: bool) -> bool:
  return not already_responses and bool(RESPONSES_ONLY.search(error))


def should_use_max_tokens(error: str, current_token_limit: str) -> bool:
  return (
      current_token_limit == "max_completion_tokens"
      and "max_completion_tokens" in error
      and bool(UNSUPPORTED.search(error))
  )


def should_drop_effort(error: str, current_effort: dict[str, Any]) -> bool:
  return bool(current_effort) and bool(re.search(r"reasoning[._]effort", error))
