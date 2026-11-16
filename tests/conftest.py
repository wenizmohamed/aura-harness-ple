"""Shared test fixtures and fake session/stream helpers."""

from __future__ import annotations

import pathlib
import sys
import time
import types
from typing import Any

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from aura_harness.config import (  # noqa: E402
    HarnessConfig,
    ModelLimits,
    PhaseBudgets,
    TelemetryConfig,
)
from aura_harness.telemetry import TelemetryLogger  # noqa: E402


class FakeSession:
  """In-memory replacement for `taskbridge.Session` supporting async agent tests."""

  def __init__(
      self,
      instruction: str = "Complete the engineering deliverables.",
      *,
      workdir: str = "/app/work",
      time_budget_sec: float | None = 3600.0,
      mcp_servers: list[dict[str, Any]] | None = None,
      limits: dict[str, Any] | None = None,
  ):
    self.instruction = instruction
    self.workdir = workdir
    self.deadline = (
        None if time_budget_sec is None else time.monotonic() + time_budget_sec
    )
    self.mcp_servers = list(mcp_servers or [])
    self.limits = dict(limits or {"exec_timeout_sec": 600})
    self.final_message = ""
    self.logs: list[str] = []
    self.usage_events: list[tuple[str, int, int, int]] = []
    self.files: dict[str, bytes] = {}
    self.exec_calls: list[tuple[str, int]] = []
    self.http_calls: list[dict[str, Any]] = []

  def time_left(self) -> float | None:
    return None if self.deadline is None else self.deadline - time.monotonic()

  async def log(self, text: str) -> None:
    self.logs.append(text)

  async def usage(
      self,
      model: str,
      input_tokens: int = 0,
      output_tokens: int = 0,
      cache_read_tokens: int = 0,
  ) -> None:
    self.usage_events.append((model, input_tokens, output_tokens, cache_read_tokens))

  async def exec(self, command: str, timeout_sec: int = 120) -> dict[str, Any]:
    self.exec_calls.append((command, timeout_sec))
    return {"ok": True, "exit_code": 0, "output": "ok", "timed_out": False}

  async def read_file(self, path: str) -> bytes:
    if path not in self.files:
      import taskbridge

      raise taskbridge.TaskError(f"missing file: {path}")
    return self.files[path]

  async def read_result(self, path: str) -> dict[str, Any]:
    import base64

    if path not in self.files:
      return {"ok": False, "error": f"missing file: {path}"}
    raw = self.files[path]
    return {"ok": True, "content_b64": base64.b64encode(raw).decode(), "size": len(raw)}

  async def write_file(
      self, path: str, data: bytes | str, append: bool = False
  ) -> int:
    raw = data.encode() if isinstance(data, str) else bytes(data)
    if append and path in self.files:
      self.files[path] = self.files[path] + raw
    else:
      self.files[path] = raw
    return len(self.files[path])

  async def http(
      self,
      url: str,
      method: str = "POST",
      headers: dict[str, str] | None = None,
      body: bytes = b"",
      timeout_sec: int = 120,
  ) -> dict[str, Any]:
    self.http_calls.append({
        "url": url,
        "method": method,
        "headers": dict(headers or {}),
        "body": body,
        "timeout_sec": timeout_sec,
    })
    return {"status": 200, "headers": {"Content-Type": "application/json"}, "body": b"{}", "truncated": False}


def make_test_config(tmp_path: pathlib.Path, **model_overrides: Any) -> HarnessConfig:
  """Builds a fast-retry config writing telemetry strictly into pytest `tmp_path`."""
  kwargs: dict[str, Any] = {"retry_waits": (0, 0), "finish_margin_sec": 10}
  kwargs.update(model_overrides)
  limits = ModelLimits(**kwargs)
  tel = TelemetryConfig(
      enabled=True,
      path=str(tmp_path / "telemetry.jsonl"),
      summary_path=str(tmp_path / "summary.json"),
  )
  return HarnessConfig(phase_budgets=PhaseBudgets(), model_limits=limits, telemetry=tel)


@pytest.fixture
def fake_session() -> FakeSession:
  return FakeSession()


@pytest.fixture
def temp_telemetry(tmp_path: pathlib.Path) -> TelemetryLogger:
  return TelemetryLogger(
      enabled=True,
      path=tmp_path / "telemetry.jsonl",
      summary_path=tmp_path / "summary.json",
      session_id="test-session",
  )


def make_stream_chunk(
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    tool_calls: list[Any] | None = None,
    usage: Any = None,
    delta_extra: dict[str, Any] | None = None,
) -> Any:
  """Builds a minimal ChatCompletionChunk-compatible object for stream tests."""
  delta = types.SimpleNamespace(
      content=content,
      tool_calls=tool_calls,
      reasoning_content=None,
      reasoning=None,
      model_extra=delta_extra or {},
  )
  choice = types.SimpleNamespace(delta=delta, finish_reason=finish_reason)
  return types.SimpleNamespace(choices=[choice], usage=usage)
