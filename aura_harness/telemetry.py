"""Structured JSONL event telemetry and per-session summary writer.

Writes strictly sanitized metadata (timings, phases, token counts, tool names,
exit statuses, compaction and retry events) without raw prompts, task files, or
API keys. Paths default to writable sandbox storage (/tmp) so read-only
/opt/harness deployments never fail.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any


class TelemetryLogger:
  """Records structured execution events and writes a per-session JSON summary."""

  def __init__(
      self,
      *,
      enabled: bool = True,
      path: str | Path = "/tmp/aura_telemetry.jsonl",
      summary_path: str | Path | None = "/tmp/aura_summary.json",
      session_id: str | None = None,
  ):
    self.enabled = bool(enabled)
    self.path = Path(path)
    self.summary_path = Path(summary_path) if summary_path else None
    self.session_id = session_id or f"aura-{int(time.time() * 1000)}"
    self._t0 = time.monotonic()
    self._warned = False
    self.counters: dict[str, int] = {
        "model_calls": 0,
        "retries": 0,
        "compactions": 0,
        "tool_calls": 0,
        "tool_errors": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
    }
    self.phases: list[dict[str, Any]] = []
    self.outcome: dict[str, Any] = {}

  def _warn_once(self, exc: Exception) -> None:
    if not self._warned:
      self._warned = True
      print(f"telemetry disabled ({exc})", file=sys.stderr, flush=True)

  def emit(self, event: str, **fields: Any) -> None:
    """Appends one sanitized JSONL event record if telemetry is enabled."""
    if not self.enabled:
      return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_s": round(time.monotonic() - self._t0, 3),
        "session_id": self.session_id,
        "event": event,
        **fields,
    }
    try:
      self.path.parent.mkdir(parents=True, exist_ok=True)
      with self.path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
      self._warn_once(exc)

  def record_model_call(
      self,
      *,
      model: str,
      prompt_tokens: int,
      completion_tokens: int,
      cached_tokens: int,
      finish: str | None,
      latency_s: float,
      tool_call_count: int,
  ) -> None:
    self.counters["model_calls"] += 1
    self.counters["prompt_tokens"] += max(0, int(prompt_tokens))
    self.counters["completion_tokens"] += max(0, int(completion_tokens))
    self.counters["cached_tokens"] += max(0, int(cached_tokens))
    self.emit(
        "model_call",
        model=model,
        prompt_tokens=int(prompt_tokens),
        completion_tokens=int(completion_tokens),
        cached_tokens=int(cached_tokens),
        finish=finish,
        latency_s=round(latency_s, 3),
        tool_call_count=int(tool_call_count),
    )

  def record_retry(self, reason: str, wait_s: float | None = None) -> None:
    self.counters["retries"] += 1
    self.emit("retry", reason=reason[:200], wait_s=wait_s)

  def record_tool(self, name: str, duration_s: float, ok: bool) -> None:
    self.counters["tool_calls"] += 1
    if not ok:
      self.counters["tool_errors"] += 1
    self.emit("tool_call", tool=name, duration_s=round(duration_s, 3), ok=ok)

  def record_compaction(self, mode: str, cut_results: int = 0, dropped_msgs: int = 0) -> None:
    self.counters["compactions"] += 1
    self.emit(
        "compaction",
        mode=mode,
        cut_results=int(cut_results),
        dropped_msgs=int(dropped_msgs),
    )

  def record_phase(self, phase: str, status: str, budget_s: float | None, duration_s: float) -> None:
    entry = {
        "phase": phase,
        "status": status,
        "budget_s": round(budget_s, 2) if budget_s is not None else None,
        "duration_s": round(duration_s, 3),
    }
    self.phases.append(entry)
    self.emit("phase", **entry)

  def write_summary(self, *, model: str, status: str = "completed") -> dict[str, Any]:
    """Writes and returns a compact session summary JSON document."""
    summary = {
        "session_id": self.session_id,
        "model": model,
        "status": status,
        "elapsed_s": round(time.monotonic() - self._t0, 3),
        "counters": dict(self.counters),
        "phases": list(self.phases),
        "outcome": dict(self.outcome),
    }
    if self.enabled and self.summary_path is not None:
      try:
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        self.summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
      except OSError as exc:
        self._warn_once(exc)
    return summary
