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

"""Modular tool-calling engine for OpenAI-compatible and Vertex proxy models.

Imports configuration, streaming helpers, MCP tooling, compaction utilities, and
sanitized telemetry from `aura_harness`, while re-exporting public symbols at the
module root for backwards compatibility.
"""

from __future__ import annotations

import asyncio
import json
import os
import posixpath
import re
import sys
import time
from typing import Any

import openai
import taskbridge

from aura_harness.compaction import (
    compute_compact_at,
    compute_output_limit,
    find_summary_cut_index,
    learn_context_from_error,
    parse_smaller_output_limit,
    room_tokens,
    should_drop_effort,
    should_use_max_tokens,
    should_use_responses,
    shrink_unread_messages,
    trim_old_tool_results,
    unread_messages,
    estimate_prompt_tokens as _estimate_prompt_tokens,
)
from aura_harness.config import (
    HarnessConfig,
    load_config,
    resolve_model_credentials,
    validate_runtime_env,
)
from aura_harness.mcp_tools import (
    MCP_CATALOG,
    MCP_DIRECT,
    MCP_TOOLS,
    MCPServer,
    SUMMARY_PROMPT,
    SYSTEM,
    TOOLS,
    find_mcp_tools,
    tool,
)
from aura_harness.stream import (
    BAD_REQUEST,
    CALL_FIELDS,
    CONTEXT_FULL,
    DELTA_FIELDS,
    FUNCTION_FIELDS,
    MAX_EFFORT_MODELS,
    PROMPT_RE,
    RESPONSES_MODELS,
    RESPONSES_ONLY,
    UNSUPPORTED,
    WINDOW_RE,
    CutOff,
    OutOfTime,
    Reply,
    StreamBadRequest,
    StreamCut,
    chat_usage,
    clip,
    default_effort,
    drop_thinking,
    extra_fields,
    marked as _marked,
    merge_or_append_user,
    merged,
    parse_arguments,
    response_input,
    signed,
    stream_error,
    thinking_blocks,
    unique_name,
    visible,
)
from aura_harness.telemetry import TelemetryLogger


DEFAULT_CONFIG = load_config()
MODEL, _BASE_URL, _API_KEY = resolve_model_credentials()
EFFORT = default_effort(MODEL, os.environ.get("REASONING_EFFORT"))
CACHE_MARK = "claude" in MODEL.lower()

COMPACT_AT_TOKENS = DEFAULT_CONFIG.model_limits.compact_at_tokens
TOOL_RESULT_CHARS = DEFAULT_CONFIG.model_limits.tool_result_chars
DIRECT_MCP_CHARS = DEFAULT_CONFIG.model_limits.direct_mcp_chars
MAX_TOOLS = DEFAULT_CONFIG.model_limits.max_tools
KEEP_RECENT_RESULTS = DEFAULT_CONFIG.model_limits.keep_recent_results
FINISH_MARGIN_SEC = DEFAULT_CONFIG.model_limits.finish_margin_sec
RETRY_WAITS = DEFAULT_CONFIG.model_limits.retry_waits
MIN_OUTPUT = DEFAULT_CONFIG.model_limits.min_output_tokens
UNREAD_KEEP = DEFAULT_CONFIG.model_limits.unread_keep
CONTEXT_MARGIN = DEFAULT_CONFIG.model_limits.context_margin


def create_client(config: HarnessConfig | None = None) -> openai.AsyncOpenAI:
  """Builds an AsyncOpenAI client from runtime environment and timeout config."""
  cfg = config or DEFAULT_CONFIG
  _, base_url, api_key = resolve_model_credentials()
  return openai.AsyncOpenAI(
      base_url=base_url,
      api_key=api_key or "none",
      max_retries=0,
      timeout=cfg.model_limits.request_timeout_sec,
  )


client = create_client(DEFAULT_CONFIG)


def marked(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Backwards-compatible cache-control marker honoring `engine.CACHE_MARK`."""
  return _marked(messages, cache_mark=CACHE_MARK)


class Agent:
  """Manages conversation state, tool execution, retries, and context compaction."""

  def __init__(
      self,
      session: taskbridge.Session,
      *,
      config: HarnessConfig | None = None,
      telemetry: TelemetryLogger | None = None,
  ):
    self.session = session
    self.config = config or load_config()
    limits = self.config.model_limits
    self.telemetry = telemetry or TelemetryLogger(
        enabled=self.config.telemetry.enabled,
        path=self.config.telemetry.path,
        summary_path=self.config.telemetry.summary_path,
    )
    self.tools = list(TOOLS)
    self.mcp: dict[str, tuple[MCPServer, dict[str, Any]]] = {}
    self.messages: list[dict[str, Any]] = []
    self.prompt_tokens = 0
    self.output_ceiling = limits.max_output_tokens
    self.context_window: int | None = None
    self.max_output = self.output_ceiling
    self.token_limit = "max_completion_tokens"
    self.effort = {"reasoning_effort": default_effort(MODEL, os.environ.get("REASONING_EFFORT"))}
    self.responses = MODEL.lower().startswith(RESPONSES_MODELS)
    self.finish_margin = float(limits.finish_margin_sec)

  async def run(self) -> str:
    """Runs the single-loop agent until completion or time expiry."""
    mcp = await self.connect_mcp()
    left = self.session.time_left()
    base_margin = float(self.config.model_limits.finish_margin_sec)
    self.finish_margin = (
        base_margin
        if left is None
        else min(base_margin, max(left, 0.0) / 4.0)
    )
    self.messages = [
        {
            "role": "system",
            "content": SYSTEM.format(
                workdir=self.session.workdir,
                mcp=mcp,
                minutes=int(left / 60) if left else "unlimited",
            ),
        },
        {"role": "user", "content": self.session.instruction},
    ]
    nudges, head = 0, ""
    while True:
      left = self.session.time_left()
      if left is not None and left < self.finish_margin:
        return await self.finish("Time is almost up.")
      try:
        reply = await self.complete(head=head)
      except OutOfTime:
        return await self.finish(
            "Time is almost up, and the model is not answering."
        )
      except CutOff:
        return await self.finish("Time is almost up.")
      arguments = [parse_arguments(call) for call in reply.calls.values()]
      if reply.text or reply.calls:
        self.messages.append(reply.message())
      text = visible(head + reply.text)
      if text:
        self.session.final_message = text
      if not reply.calls:
        if visible(reply.text) and reply.finish == "length":
          nudges, head = 0, head + reply.text
          self.messages.append({
              "role": "user",
              "content": (
                  f"Your reply was cut off at the {self.max_output}-token"
                  " output limit. Continue where it stopped, and put long"
                  " content in files with write_file rather than in a reply."
              ),
          })
          continue
        if visible(reply.text) or nudges >= 2:
          return text or self.session.final_message
        nudges += 1
        self.messages.append({
            "role": "user",
            "content": (
                "Continue the task; when it is done, answer with "
                "your summary of the deliverables."
            ),
        })
        continue
      nudges, head = 0, ""
      for call, args in zip(reply.calls.values(), arguments):
        result = (
            await self.run_tool(call["name"], args)
            if isinstance(args, dict)
            else args
        )
        if reply.finish == "length" and isinstance(args, str):
          result += (
              f" Your reply hit the {self.max_output}-token output limit; write"
              " large files in parts."
          )
        self.messages.append(
            {"role": "tool", "tool_call_id": call["id"], "content": result}
        )
      left = self.session.time_left()
      if left is not None:
        self.messages[-1]["content"] += f"\n[{int(left // 60)} minutes left]"
      if self.prompt_tokens > self.compact_at():
        await self.compact()

  async def finish(self, why: str) -> str:
    """Prompts the model for a final no-tools summary when time expires."""
    merge_or_append_user(
        self.messages,
        f"{why} Stop working now and answer with your final "
        "summary: what you delivered, where, and the key results.",
    )
    left = self.session.time_left()
    reserve = (
        0 if left is None else left - max(5, taskbridge.time_share(left, 30))
    )
    try:
      text = visible(
          (await self.complete(tool_choice="none", reserve=reserve, head="")).text
      )
    except (CutOff, openai.OpenAIError, OutOfTime):
      text = ""
    return text or self.session.final_message

  async def connect_mcp(self) -> str:
    """Connects to task MCP servers and registers direct or catalogued tools."""
    limits = self.config.model_limits
    for spec in self.session.mcp_servers:
      server = MCPServer(self.session, spec)
      try:
        await server.start()
      except (taskbridge.TaskError, RuntimeError, ValueError) as exc:
        await self.session.log(f"MCP server {server.name} unavailable: {exc}")
        self.telemetry.emit("mcp_unavailable", server=server.name, error=str(exc)[:200])
        continue
      for t in server.tools:
        name = re.sub(r"[^A-Za-z0-9_-]", "_", f"{server.name}__{t['name']}")
        self.mcp[unique_name(name, self.mcp)] = (server, t)
      await self.session.log(
          f"MCP server {server.name}: {len(server.tools)} tools"
      )
    if not self.mcp:
      return ""
    functions = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": (t.get("description") or t["name"])[:1024],
                "parameters": (
                    {
                        k: v
                        for k, v in (t.get("inputSchema") or {}).items()
                        if k != "$schema"
                    }
                    or {"type": "object", "properties": {}}
                ),
            },
        }
        for name, (_, t) in self.mcp.items()
    ]
    if (
        len(json.dumps(functions)) <= limits.direct_mcp_chars
        and len(self.tools) + len(functions) <= limits.max_tools
    ):
      self.tools += functions
      return MCP_DIRECT
    self.tools += MCP_TOOLS
    servers: dict[str, list[str]] = {}
    for name, (server, _) in self.mcp.items():
      servers.setdefault(server.name, []).append(name)
    return MCP_CATALOG.format(
        catalog="\n".join(
            f"{s}: {', '.join(names)}" for s, names in servers.items()
        )
    )

  def find_mcp(self, query: str) -> str:
    """Finds MCP tools matching `query` within configured result character limit."""
    return find_mcp_tools(
        self.mcp, query, result_limit=self.config.model_limits.tool_result_chars
    )

  async def complete(
      self,
      tool_choice: str = "auto",
      reserve: float | None = None,
      head: str | None = None,
  ) -> Reply:
    """Streams one completion with retries, parameter recovery, and telemetry."""
    reserve = self.finish_margin if reserve is None else reserve
    waits = iter(self.config.model_limits.retry_waits)
    while True:
      t0 = time.monotonic()
      try:
        reply = await self.stream(self.messages, tool_choice, reserve, head)
        if reply.finish is None:
          raise StreamCut("the stream ended without a finish reason")
        await self.record(reply, latency_s=time.monotonic() - t0)
        return reply
      except openai.APIStatusError as exc:
        if exc.status_code == 400 and await self.remedy(str(exc)):
          self.telemetry.record_retry(f"http_400_remedy", wait_s=0)
          continue
        if not (exc.status_code in (408, 409, 429) or exc.status_code >= 500):
          self.telemetry.emit("model_fatal", status_code=exc.status_code)
          raise
        failure = exc
      except StreamBadRequest as exc:
        if await self.remedy(str(exc)):
          self.telemetry.record_retry("stream_400_remedy", wait_s=0)
          continue
        self.telemetry.emit("model_fatal", kind="stream_bad_request")
        raise
      except (openai.APIError, StreamCut) as exc:
        failure = exc
      wait = next(waits, None)
      if wait is None:
        self.telemetry.emit("retries_exhausted", kind=type(failure).__name__)
        raise failure
      left = self.session.time_left()
      if left is not None and left - wait < reserve:
        await self.session.log(
            f"model call failed ({str(failure)[:300]}); no time left to wait"
            f" {wait}s"
        )
        raise OutOfTime(str(failure)[:300]) from failure
      await self.session.log(
          f"model call failed ({str(failure)[:300]}); again in {wait}s"
      )
      self.telemetry.record_retry(type(failure).__name__, wait_s=wait)
      await asyncio.sleep(wait)

  async def remedy(self, error: str) -> bool:
    """Adjusts parameters or compacts context after a 400 error."""
    limits = self.config.model_limits
    if CONTEXT_FULL.search(error):
      sent, measured = self.max_output, self.learn_context(error)
      if (
          measured
          and (self.room() or 0) >= limits.min_output_tokens
          and self.output_limit() < sent
      ):
        return True
      return bool(
          await self.compact(force=True)
          or (not measured and self.output_limit() < sent)
          or self.cut_unread()
      )
    return (
        self.use_responses(error)
        or self.use_max_tokens(error)
        or self.drop_effort(error)
        or self.shrink_output(error)
    )

  def use_responses(self, error: str) -> bool:
    if should_use_responses(error, self.responses):
      self.responses = True
      return True
    return False

  def use_max_tokens(self, error: str) -> bool:
    if should_use_max_tokens(error, self.token_limit):
      self.token_limit = "max_tokens"
      return True
    return False

  def drop_effort(self, error: str) -> bool:
    if should_drop_effort(error, self.effort):
      self.effort = {}
      return True
    return False

  def shrink_output(self, error: str) -> bool:
    new = parse_smaller_output_limit(
        error, self.max_output, self.config.model_limits.min_output_tokens
    )
    if new is None:
      return False
    self.output_ceiling = new
    return True

  def learn_context(self, error: str) -> bool:
    ok, self.context_window, self.prompt_tokens = learn_context_from_error(
        error, self.context_window, self.prompt_tokens
    )
    return ok

  def room(self) -> int | None:
    return room_tokens(
        self.context_window,
        self.prompt_tokens,
        self.config.model_limits.context_margin,
    )

  def output_limit(self) -> int:
    return compute_output_limit(
        self.output_ceiling,
        self.config.model_limits.min_output_tokens,
        self.context_window,
        self.prompt_tokens,
        self.config.model_limits.context_margin,
    )

  def compact_at(self) -> int:
    return compute_compact_at(
        self.config.model_limits.compact_at_tokens,
        self.output_ceiling,
        self.context_window,
        self.config.model_limits.context_margin,
    )

  def estimate_prompt_tokens(self) -> int:
    return _estimate_prompt_tokens(self.messages)

  async def stream(
      self,
      messages: list[dict[str, Any]],
      tool_choice: str,
      reserve: float,
      head: str | None = None,
  ) -> Reply:
    """Streams one Chat Completions or Responses API reply up to `reserve`."""
    left = self.session.time_left()
    self.max_output = self.output_limit()
    reply = Reply()

    async def read() -> None:
      if self.responses:
        await self.respond(reply, messages, tool_choice)
        return
      stream = await client.chat.completions.create(
          model=MODEL,
          messages=marked(messages),
          tools=self.tools,
          tool_choice=tool_choice,
          stream=True,
          stream_options={"include_usage": True},
          **self.effort,
          **{self.token_limit: self.max_output},
      )
      async for chunk in stream:
        reply.usage = chunk.usage or reply.usage
        if not chunk.choices:
          continue
        delta = chunk.choices[0].delta
        reply.finish = chunk.choices[0].finish_reason or reply.finish
        reply.text += delta.content or ""
        reply.reasoning += (
            getattr(delta, "reasoning_content", None)
            or getattr(delta, "reasoning", None)
            or ""
        )
        reply.extra = merged(reply.extra, extra_fields(delta, DELTA_FIELDS))
        for part in delta.tool_calls or []:
          reply.add_call(part)

    try:
      await asyncio.wait_for(read(), None if left is None else left - reserve)
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
      if head is not None:
        self.session.final_message = (
            visible(head + reply.text) or self.session.final_message
        )
      if isinstance(exc, asyncio.CancelledError):
        raise
      raise CutOff() from None
    except openai.APIError as exc:
      said = {
          "message": getattr(exc, "message", None) or str(exc),
          "type": getattr(exc, "type", None),
          "code": getattr(exc, "code", None),
      }
      if isinstance(exc, openai.APIStatusError) or isinstance(
          stream_error(said), StreamCut
      ):
        raise
      raise StreamBadRequest(said["message"]) from exc
    for n, call in reply.calls.items():
      call["id"] = call["id"] or f"call_{n}_{len(self.messages)}"
      call["name"] = call["name"].split("<|")[0].strip()
    return reply

  async def respond(
      self, reply: Reply, messages: list[dict[str, Any]], tool_choice: str
  ) -> None:
    """Streams a single Responses API call into `reply`."""
    effort = self.effort.get("reasoning_effort")
    stream = await client.responses.create(
        model=MODEL,
        input=response_input(messages),
        tools=[
            {"type": "function", **t["function"], "strict": False}
            for t in self.tools
        ],
        tool_choice=tool_choice,
        stream=True,
        store=False,
        include=["reasoning.encrypted_content"],
        max_output_tokens=self.max_output,
        **({"reasoning": {"effort": effort}} if effort else {}),
    )
    async for event in stream:
      kind = getattr(event, "type", "")
      if kind == "response.output_text.delta":
        reply.text += event.delta or ""
      elif kind in ("error", "response.failed"):
        raise stream_error(
            getattr(getattr(event, "response", None), "error", None) or event
        )
      elif kind in ("response.completed", "response.incomplete"):
        done = event.response
        items = [i.model_dump(exclude_none=True) for i in done.output or []]
        reply.extra = {"output_items": items}
        reply.text = "".join(
            part.get("text", "")
            for item in items
            if item.get("type") == "message"
            for part in item.get("content") or []
            if part.get("type") == "output_text"
        )
        for item in items:
          if item.get("type") == "function_call":
            reply.calls[len(reply.calls)] = {
                "id": item.get("call_id") or "",
                "name": item.get("name") or "",
                "arguments": item.get("arguments") or "",
                "extra": {},
                "function_extra": {},
            }
        reply.usage = chat_usage(done.usage)
        reason = getattr(done.incomplete_details, "reason", None)
        if kind == "response.completed":
          reply.finish = "tool_calls" if reply.calls else "stop"
        else:
          reply.finish = reason if reason == "content_filter" else "length"

  async def record(self, reply: Reply, latency_s: float = 0.0) -> None:
    """Updates `prompt_tokens`, reports evaluator usage, and logs telemetry."""
    if reply.usage is None:
      self.prompt_tokens = self.estimate_prompt_tokens()
      self.telemetry.record_model_call(
          model=MODEL,
          prompt_tokens=self.prompt_tokens,
          completion_tokens=0,
          cached_tokens=0,
          finish=reply.finish,
          latency_s=latency_s,
          tool_call_count=len(reply.calls),
      )
      return
    self.prompt_tokens = reply.usage.prompt_tokens or 0
    cached = (
        getattr(
            getattr(reply.usage, "prompt_tokens_details", None), "cached_tokens", 0
        )
        or 0
    )
    self.telemetry.record_model_call(
        model=MODEL,
        prompt_tokens=self.prompt_tokens,
        completion_tokens=reply.usage.completion_tokens or 0,
        cached_tokens=cached,
        finish=reply.finish,
        latency_s=latency_s,
        tool_call_count=len(reply.calls),
    )
    await self.report(reply)

  async def report(self, reply: Reply) -> None:
    """Reports token usage from `reply` to the evaluator session."""
    usage = reply.usage
    if usage is None:
      return
    cached = (
        getattr(
            getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0
        )
        or 0
    )
    await self.session.usage(
        MODEL, usage.prompt_tokens or 0, usage.completion_tokens or 0, cached
    )

  async def run_tool(self, name: str, args: dict[str, Any]) -> str:
    """Dispatches a built-in or MCP tool call and returns clipped output."""
    limit = self.config.model_limits.tool_result_chars
    await self.session.log(f"{name} {json.dumps(args)[:400]}")
    t0 = time.monotonic()
    ok = True
    try:
      if name == "mcp_call":
        name, args = str(args.get("tool", "")), args.get("arguments") or {}
        args = json.loads(args) if isinstance(args, str) else args
        if name not in self.mcp:
          ok = False
          return f"error: no tool named {name!r}; use mcp_find"
      if name in self.mcp:
        server, t = self.mcp[name]
        return clip(await server.call(t["name"], args, result_limit=limit), limit)
      if name == "mcp_find":
        return self.find_mcp(str(args.get("query", "")))
      handler = {
          "bash": self.bash,
          "read_file": self.read_file,
          "write_file": self.write_file,
          "edit_file": self.edit_file,
      }.get(name)
      if not handler:
        ok = False
        return f"error: there is no tool named {name}"
      return clip(await handler(**args), limit)
    except taskbridge.TaskError as exc:
      ok = False
      return f"error: {exc}"
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
    ) as exc:
      ok = False
      return f"error: {type(exc).__name__}: {exc}"
    finally:
      self.telemetry.record_tool(name, duration_s=time.monotonic() - t0, ok=ok)

  def path(self, path: str) -> str:
    """Resolves `path` relative to `self.session.workdir`."""
    return (
        path
        if path.startswith("/")
        else posixpath.join(self.session.workdir, path)
    )

  async def bash(self, command: str, timeout_sec: int = 120) -> str:
    cap = int(self.session.limits.get("exec_timeout_sec") or 600)
    left = self.session.time_left()
    if left is not None:
      cap = min(cap, max(1, int(left - self.finish_margin)))
    result = await self.session.exec(
        command, taskbridge.positive_int(timeout_sec, 120, cap)
    )
    note = " (timed out)" if result.get("timed_out") else ""
    return (
        "exit code"
        f" {result['exit_code']}{note}\n{result['output'] or '(no output)'}"
    )

  async def read_file(self, path: str) -> str:
    data = await self.session.read_file(self.path(path))
    if b"\0" in data[:8192]:
      return (
          f"{path} is a binary file ({len(data)} bytes); inspect it with bash"
          " (python3, unzip -l, ...)"
      )
    return data.decode("utf-8", "replace") or "(empty file)"

  async def write_file(
      self, path: str, content: str, append: bool = False
  ) -> str:
    size = await self.session.write_file(
        self.path(path), content, append=bool(append)
    )
    return f"{path} now holds {size} bytes"

  async def edit_file(
      self, path: str, old_text: str, new_text: str, replace_all: bool = False
  ) -> str:
    text = (await self.session.read_file(self.path(path))).decode("utf-8")
    count = text.count(old_text) if old_text else 0
    if count == 0:
      return f"error: old_text was not found in {path}"
    if count > 1 and not replace_all:
      return (
          f"error: old_text occurs {count} times in {path}; add context to make"
          " it unique, or set replace_all"
      )
    await self.session.write_file(
        self.path(path),
        text.replace(old_text, new_text, -1 if replace_all else 1),
    )
    return f"replaced {count if replace_all else 1} occurrence(s) in {path}"

  def unread(self) -> list[dict[str, Any]]:
    return unread_messages(self.messages)

  async def compact(self, force: bool = False) -> bool:
    """Trims historical tool results and summarizes older turns when needed."""
    cuts = trim_old_tool_results(
        self.messages,
        force=force,
        keep_recent_results=self.config.model_limits.keep_recent_results,
        compact_threshold=self.compact_at(),
        prompt_tokens=self.prompt_tokens,
        context_window=self.context_window,
    )
    if cuts:
      await self.session.log(f"context: cut {len(cuts)} old tool results")
      self.prompt_tokens = self.estimate_prompt_tokens()
      self.telemetry.record_compaction("trim_tool_results", cut_results=len(cuts))
      if (
          not force
          or not self.context_window
          or self.prompt_tokens <= self.compact_at()
      ):
        return True
    cut = find_summary_cut_index(self.messages)
    if cut is None:
      return bool(cuts)
    try:
      notes = await self.stream(
          self.messages[:cut] + [{"role": "user", "content": SUMMARY_PROMPT}],
          "none",
          self.finish_margin,
      )
    except (openai.APIError, StreamCut, asyncio.TimeoutError) as exc:
      await self.session.log(
          f"context: notes failed ({str(exc)[:200] or 'out of time'})"
      )
      return bool(cuts)
    await self.report(notes)
    if notes.finish is None:
      await self.session.log(
          "context: the notes were cut short, so the turns are kept"
      )
      return bool(cuts)
    text = visible(notes.text)
    if not text:
      await self.session.log(
          "context: the notes came back empty, so the turns are kept"
      )
      return bool(cuts)
    if notes.finish == "length":
      text += "\n[the notes were cut off at the output limit]"
    self.messages = (
        self.messages[:2]
        + [{
            "role": "user",
            "content": (
                "Your notes on the work so far (earlier "
                "turns were removed to save context):\n"
                + text
            ),
        }]
        + self.messages[cut:]
    )
    await self.session.log(f"context: replaced {cut - 2} messages with notes")
    self.prompt_tokens = self.estimate_prompt_tokens()
    self.telemetry.record_compaction(
        "summarize_turns", cut_results=len(cuts), dropped_msgs=cut - 2
    )
    return True

  def cut_unread(self) -> bool:
    """Truncates unread tool outputs as a last resort when context overflows."""
    changed = shrink_unread_messages(
        self.messages,
        unread_keep=self.config.model_limits.unread_keep,
        compact_threshold=self.compact_at(),
        context_window=self.context_window,
    )
    if changed:
      self.prompt_tokens = self.estimate_prompt_tokens()
      self.telemetry.record_compaction("cut_unread")
    return changed


async def solve(session: taskbridge.Session) -> str:
  """Runs `Agent` on `session` and returns the final summary answer."""
  cfg = load_config()
  env_report = validate_runtime_env()
  for warning in env_report.warnings:
    print(f"env notice: {warning}", file=sys.stderr, flush=True)
  tel = TelemetryLogger(
      enabled=cfg.telemetry.enabled,
      path=cfg.telemetry.path,
      summary_path=cfg.telemetry.summary_path,
  )
  print(
      f"task: workdir {session.workdir}, model {MODEL},"
      f" {len(session.mcp_servers)} MCP server(s)",
      file=sys.stderr,
  )
  status = "completed"
  try:
    return await Agent(session, config=cfg, telemetry=tel).run()
  except Exception as exc:
    status = f"error:{type(exc).__name__}"
    raise
  finally:
    tel.write_summary(model=MODEL, status=status)


if __name__ == "__main__":
  taskbridge.run(solve)
