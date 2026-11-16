"""Configuration schema, file loader, and environment validation for AURA Harness."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "harness_config.json"


class ConfigError(ValueError):
  """Raised when configuration values fail schema validation."""


@dataclass(frozen=True)
class PhaseBudgets:
  """Time-allocation ratios and safety guards across Plan/Work/Verify/Repair."""

  plan_share: float = 0.10
  plan_max_sec: int = 1200
  verify_share: float = 0.30
  verify_round_share: float = 0.35
  verify_max_sec: int = 900
  max_repair_rounds: int = 3
  min_repair_sec: int = 600
  wrap_sec: int = 300


@dataclass(frozen=True)
class ModelLimits:
  """Token ceilings, compaction triggers, tool caps, and retry schedules."""

  max_output_tokens: int = 32000
  min_output_tokens: int = 1024
  compact_at_tokens: int = 150000
  tool_result_chars: int = 30000
  direct_mcp_chars: int = 40000
  max_tools: int = 128
  keep_recent_results: int = 12
  unread_keep: int = 600
  context_margin: int = 1024
  finish_margin_sec: int = 180
  request_timeout_sec: int = 900
  retry_waits: tuple[int, ...] = (5, 15, 30, 60, 120)


@dataclass(frozen=True)
class TelemetryConfig:
  """Structured telemetry destinations (must live on writable storage like /tmp)."""

  enabled: bool = True
  path: str = "/tmp/aura_telemetry.jsonl"
  summary_path: str = "/tmp/aura_summary.json"


@dataclass(frozen=True)
class HarnessConfig:
  """Complete validated configuration for engine and multi-phase orchestrator."""

  phase_budgets: PhaseBudgets = field(default_factory=PhaseBudgets)
  model_limits: ModelLimits = field(default_factory=ModelLimits)
  telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)


@dataclass(frozen=True)
class EnvReport:
  """Validation result summarizing model endpoint and key environment readiness."""

  model: str
  base_url: str | None
  has_api_key: bool
  missing: tuple[str, ...]
  warnings: tuple[str, ...]

  @property
  def valid(self) -> bool:
    """Returns True when all required model runtime fields are present."""
    return not self.missing


def _as_bool(raw: Any, fallback: bool) -> bool:
  if isinstance(raw, bool):
    return raw
  if isinstance(raw, str):
    norm = raw.strip().lower()
    if norm in ("1", "true", "yes", "on"):
      return True
    if norm in ("0", "false", "no", "off"):
      return False
  return fallback


def _as_int(raw: Any, name: str) -> int:
  if isinstance(raw, bool):
    raise ConfigError(f"{name} must be an integer, got bool")
  try:
    return int(raw)
  except (TypeError, ValueError) as exc:
    raise ConfigError(f"{name} must be an integer: {raw!r}") from exc


def _as_float(raw: Any, name: str) -> float:
  if isinstance(raw, bool):
    raise ConfigError(f"{name} must be a number, got bool")
  try:
    return float(raw)
  except (TypeError, ValueError) as exc:
    raise ConfigError(f"{name} must be a number: {raw!r}") from exc


def _validate(cfg: HarnessConfig) -> HarnessConfig:
  pb = cfg.phase_budgets
  ml = cfg.model_limits
  if not (0.0 < pb.plan_share < 1.0):
    raise ConfigError(f"phase_budgets.plan_share must be in (0, 1), got {pb.plan_share}")
  if not (0.0 < pb.verify_share < 1.0):
    raise ConfigError(f"phase_budgets.verify_share must be in (0, 1), got {pb.verify_share}")
  if not (0.0 < pb.verify_round_share <= 1.0):
    raise ConfigError(
        f"phase_budgets.verify_round_share must be in (0, 1], got {pb.verify_round_share}"
    )
  if pb.plan_max_sec <= 0 or pb.verify_max_sec <= 0:
    raise ConfigError("phase_budgets plan_max_sec and verify_max_sec must be positive")
  if pb.max_repair_rounds < 0 or pb.min_repair_sec < 0 or pb.wrap_sec < 0:
    raise ConfigError("phase_budgets repair/wrap bounds cannot be negative")
  if ml.min_output_tokens <= 0 or ml.max_output_tokens < ml.min_output_tokens:
    raise ConfigError(
        "model_limits.max_output_tokens must be >= min_output_tokens (> 0)"
    )
  if ml.compact_at_tokens < 1024 or ml.context_margin < 0:
    raise ConfigError("model_limits.compact_at_tokens must be >= 1024")
  if ml.tool_result_chars <= 0 or ml.direct_mcp_chars <= 0 or ml.max_tools <= 0:
    raise ConfigError("model_limits tool bounds must be positive")
  if ml.keep_recent_results < 0 or ml.unread_keep <= 0 or ml.finish_margin_sec < 0:
    raise ConfigError("model_limits keep/margin bounds are invalid")
  if ml.request_timeout_sec <= 0 or not ml.retry_waits or any(w < 0 for w in ml.retry_waits):
    raise ConfigError("model_limits request_timeout_sec and retry_waits must be valid")
  return cfg


def load_config(
    config_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> HarnessConfig:
  """Loads configuration from JSON file and applies validated environment overrides.

  Args:
    config_path: Explicit path to JSON config file; falls back to
      `AURA_CONFIG_PATH` env var or repository `harness_config.json`.
    env: Optional environment mapping (defaults to `os.environ`).

  Returns:
    Validated `HarnessConfig` object.

  Raises:
    ConfigError: If JSON parsing fails or any field fails validation.
  """
  environ = os.environ if env is None else env
  raw_path = config_path or environ.get("AURA_CONFIG_PATH") or DEFAULT_CONFIG_PATH
  path = Path(raw_path)
  data: dict[str, Any] = {}
  if path.exists():
    try:
      loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
      raise ConfigError(f"failed to read config {path}: {exc}") from exc
    if not isinstance(loaded, dict):
      raise ConfigError(f"config root in {path} must be a JSON object")
    data = loaded
  elif config_path or environ.get("AURA_CONFIG_PATH"):
    raise ConfigError(f"explicit config path not found: {path}")

  pb_raw = data.get("phase_budgets") or {}
  ml_raw = data.get("model_limits") or {}
  tc_raw = data.get("telemetry") or {}
  if not all(isinstance(x, dict) for x in (pb_raw, ml_raw, tc_raw)):
    raise ConfigError("phase_budgets, model_limits, and telemetry must be JSON objects")

  verify_share = (
      _as_float(environ["AURA_VERIFY_SHARE"], "AURA_VERIFY_SHARE")
      if "AURA_VERIFY_SHARE" in environ
      else _as_float(pb_raw.get("verify_share", 0.30), "phase_budgets.verify_share")
  )
  max_repair = (
      _as_int(environ["AURA_MAX_REPAIR_ROUNDS"], "AURA_MAX_REPAIR_ROUNDS")
      if "AURA_MAX_REPAIR_ROUNDS" in environ
      else _as_int(
          pb_raw.get("max_repair_rounds", 3), "phase_budgets.max_repair_rounds"
      )
  )
  pb = PhaseBudgets(
      plan_share=_as_float(pb_raw.get("plan_share", 0.10), "phase_budgets.plan_share"),
      plan_max_sec=_as_int(pb_raw.get("plan_max_sec", 1200), "phase_budgets.plan_max_sec"),
      verify_share=verify_share,
      verify_round_share=_as_float(
          pb_raw.get("verify_round_share", 0.35), "phase_budgets.verify_round_share"
      ),
      verify_max_sec=_as_int(
          pb_raw.get("verify_max_sec", 900), "phase_budgets.verify_max_sec"
      ),
      max_repair_rounds=max_repair,
      min_repair_sec=_as_int(
          pb_raw.get("min_repair_sec", 600), "phase_budgets.min_repair_sec"
      ),
      wrap_sec=_as_int(pb_raw.get("wrap_sec", 300), "phase_budgets.wrap_sec"),
  )

  max_output = (
      _as_int(environ["MAX_OUTPUT_TOKENS"], "MAX_OUTPUT_TOKENS")
      if "MAX_OUTPUT_TOKENS" in environ
      else _as_int(
          ml_raw.get("max_output_tokens", 32000), "model_limits.max_output_tokens"
      )
  )
  compact_at = (
      _as_int(environ["COMPACT_AT_TOKENS"], "COMPACT_AT_TOKENS")
      if "COMPACT_AT_TOKENS" in environ
      else _as_int(
          ml_raw.get("compact_at_tokens", 150000), "model_limits.compact_at_tokens"
      )
  )
  waits_raw = ml_raw.get("retry_waits", [5, 15, 30, 60, 120])
  if not isinstance(waits_raw, list):
    raise ConfigError("model_limits.retry_waits must be a list of integers")
  waits = tuple(_as_int(w, "model_limits.retry_waits[]") for w in waits_raw)
  ml = ModelLimits(
      max_output_tokens=max_output,
      min_output_tokens=_as_int(
          ml_raw.get("min_output_tokens", 1024), "model_limits.min_output_tokens"
      ),
      compact_at_tokens=compact_at,
      tool_result_chars=_as_int(
          ml_raw.get("tool_result_chars", 30000), "model_limits.tool_result_chars"
      ),
      direct_mcp_chars=_as_int(
          ml_raw.get("direct_mcp_chars", 40000), "model_limits.direct_mcp_chars"
      ),
      max_tools=_as_int(ml_raw.get("max_tools", 128), "model_limits.max_tools"),
      keep_recent_results=_as_int(
          ml_raw.get("keep_recent_results", 12), "model_limits.keep_recent_results"
      ),
      unread_keep=_as_int(ml_raw.get("unread_keep", 600), "model_limits.unread_keep"),
      context_margin=_as_int(
          ml_raw.get("context_margin", 1024), "model_limits.context_margin"
      ),
      finish_margin_sec=_as_int(
          ml_raw.get("finish_margin_sec", 180), "model_limits.finish_margin_sec"
      ),
      request_timeout_sec=_as_int(
          ml_raw.get("request_timeout_sec", 900), "model_limits.request_timeout_sec"
      ),
      retry_waits=waits,
  )

  tc = TelemetryConfig(
      enabled=_as_bool(
          environ.get("AURA_TELEMETRY_ENABLED", tc_raw.get("enabled", True)), True
      ),
      path=str(
          environ.get("AURA_TELEMETRY_PATH")
          or tc_raw.get("path")
          or "/tmp/aura_telemetry.jsonl"
      ),
      summary_path=str(
          environ.get("AURA_SUMMARY_PATH")
          or tc_raw.get("summary_path")
          or "/tmp/aura_summary.json"
      ),
  )
  return _validate(HarnessConfig(phase_budgets=pb, model_limits=ml, telemetry=tc))


def resolve_model_credentials(
    env: Mapping[str, str] | None = None,
) -> tuple[str, str | None, str]:
  """Resolves `(model_name, base_url, api_key)` from supported runtime variables."""
  environ = os.environ if env is None else env
  model = (environ.get("MODEL_NAME") or "").strip()
  base_url = (
      environ.get("MODEL_BASE_URL")
      or environ.get("OPENAI_BASE_URL")
      or environ.get("GOOGLE_GEMINI_BASE_URL")
      or ""
  ).strip() or None
  api_key = (
      environ.get("MODEL_API_KEY")
      or environ.get("OPENAI_API_KEY")
      or environ.get("GEMINI_API_KEY")
      or ""
  ).strip()
  return model, base_url, api_key


def validate_runtime_env(env: Mapping[str, str] | None = None) -> EnvReport:
  """Checks required model runtime environment variables without leaking secret values."""
  environ = os.environ if env is None else env
  model, base_url, api_key = resolve_model_credentials(environ)
  missing: list[str] = []
  warnings: list[str] = []
  if not model:
    missing.append("MODEL_NAME")
  if not base_url:
    warnings.append("MODEL_BASE_URL unset; defaulting to OpenAI SDK base URL")
  if not api_key:
    warnings.append("MODEL_API_KEY unset; using placeholder 'none' unless proxy rejects")
  return EnvReport(
      model=model,
      base_url=base_url,
      has_api_key=bool(api_key),
      missing=tuple(missing),
      warnings=tuple(warnings),
  )
