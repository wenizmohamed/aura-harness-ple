"""Unit tests for config schema loading, env validation, and JSONL telemetry."""

from __future__ import annotations

import json

import pytest

from aura_harness.config import ConfigError, load_config, validate_runtime_env
from aura_harness.telemetry import TelemetryLogger


def test_load_config_defaults_and_env_overrides(tmp_path) -> None:
  cfg_file = tmp_path / "cfg.json"
  cfg_file.write_text(
      json.dumps({
          "phase_budgets": {"plan_share": 0.15, "max_repair_rounds": 2},
          "model_limits": {"max_output_tokens": 16000, "compact_at_tokens": 100000},
      }),
      encoding="utf-8",
  )
  cfg = load_config(
      cfg_file,
      env={
          "AURA_VERIFY_SHARE": "0.25",
          "AURA_MAX_REPAIR_ROUNDS": "4",
          "MAX_OUTPUT_TOKENS": "24000",
          "COMPACT_AT_TOKENS": "120000",
          "AURA_TELEMETRY_ENABLED": "false",
      },
  )
  assert cfg.phase_budgets.plan_share == 0.15
  assert cfg.phase_budgets.verify_share == 0.25
  assert cfg.phase_budgets.max_repair_rounds == 4
  assert cfg.model_limits.max_output_tokens == 24000
  assert cfg.model_limits.compact_at_tokens == 120000
  assert cfg.telemetry.enabled is False


def test_load_config_rejects_invalid_bounds(tmp_path) -> None:
  bad = tmp_path / "bad.json"
  bad.write_text(json.dumps({"phase_budgets": {"verify_share": 1.2}}), encoding="utf-8")
  with pytest.raises(ConfigError):
    load_config(bad, env={})

  with pytest.raises(ConfigError):
    load_config(tmp_path / "missing.json", env={})


def test_validate_runtime_env() -> None:
  missing = validate_runtime_env({})
  assert missing.valid is False
  assert "MODEL_NAME" in missing.missing

  ready = validate_runtime_env({
      "MODEL_NAME": "gemini-4-argon",
      "MODEL_BASE_URL": "http://localhost:4000/v1",
      "MODEL_API_KEY": "secret",
  })
  assert ready.valid is True
  assert ready.has_api_key is True
  assert ready.warnings == ()


def test_telemetry_logger_writes_jsonl_and_summary(tmp_path) -> None:
  tel_path = tmp_path / "events.jsonl"
  sum_path = tmp_path / "summary.json"
  tel = TelemetryLogger(path=tel_path, summary_path=sum_path, session_id="s-1")
  tel.record_model_call(
      model="gemini-4-argon",
      prompt_tokens=1000,
      completion_tokens=200,
      cached_tokens=600,
      finish="stop",
      latency_s=1.25,
      tool_call_count=1,
  )
  tel.record_tool("bash", duration_s=0.4, ok=True)
  tel.record_compaction("trim_tool_results", cut_results=3)
  summary = tel.write_summary(model="gemini-4-argon")

  lines = [json.loads(ln) for ln in tel_path.read_text(encoding="utf-8").splitlines()]
  assert [ln["event"] for ln in lines] == ["model_call", "tool_call", "compaction"]
  assert summary["counters"]["model_calls"] == 1
  assert summary["counters"]["prompt_tokens"] == 1000
  assert summary["counters"]["cached_tokens"] == 600
  assert json.loads(sum_path.read_text(encoding="utf-8"))["session_id"] == "s-1"
