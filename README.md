# AURA Harness

Modular, config-driven plan, work, verify, and repair agent harness built on the Physical-Engineering's Last Exam (PLE) protocol (`taskbridge.py`) and deployed with `submission.yaml`.

## Architecture and Module Layout

```text
aura-harness-pub/
|-- submission.yaml              # PLE runtime entry (`model_api`, uv venv install, `serve.py`)
|-- harness_config.json          # Validated phase budgets, model limits, and telemetry defaults
|-- .env.example                 # Required and optional runtime environment variables
|-- serve.py                     # Multi-phase orchestrator (Plan -> Work -> Verify <-> Repair)
|-- engine.py                    # Core tool-calling Agent (backwards-compatible root exports)
|-- taskbridge.py                # WebSocket protocol Session, HTTP Relay, and MCPClient
|-- aura_harness/
|   |-- __init__.py              # Package exports
|   |-- config.py                # HarnessConfig schema, JSON/env loader, validate_runtime_env()
|   |-- telemetry.py             # TelemetryLogger -> sanitized JSONL events + summary JSON
|   |-- stream.py                # SSE/Responses stream parsing, argument validation, turn merging
|   |-- mcp_tools.py             # Built-in tool schemas (bash, read/write/edit_file) & MCPServer
|   `-- compaction.py            # Context-window estimator, truncation/compaction, 400 recovery
|-- scripts/
|   `-- validate.py              # Validates config schema, required files, syntax, and secrets
|-- tests/
|   |-- conftest.py
|   |-- test_stream_and_parsing.py
|   |-- test_retry_and_compaction.py
|   |-- test_serve_phases.py
|   |-- test_taskbridge.py
|   `-- test_config_and_telemetry.py
`-- SECURITY.md                  # Threat model, sandboxing assumptions, and relay protections
```

### Execution Phases (`serve.py`)

Given an active `taskbridge.Session` time budget:

1. **Plan** - Inspects the workspace and requirements without editing deliverables, writes a concrete specification and verification plan to `/tmp/aura_plan.md`. Allocated `plan_share` (`0.10`, 10% of remaining time), capped at `plan_max_sec` (`1200` s / 20 min).
2. **Work** - Reads `/tmp/aura_plan.md` and produces/validates every requested deliverable in code, checking formats, units, and constraints. Uses remaining time minus `verify_share` (`0.30`).
3. **Verify** - Spawns a fresh read-only `PhaseAgent` (`REVIEW_TOOLS = ("bash", "read_file", "mcp_find", "mcp_call")`) that inspects deliverables against the plan and returns `PASS` or one line per concrete gap. Runs when remaining time is at least `min_repair_sec + wrap_sec`, bounded by `verify_round_share` (`0.35`) and `verify_max_sec` (`900` s).
4. **Repair** - When Verify reports concrete gaps and sufficient time remains (`min_repair_sec + wrap_sec`), returns gaps to the Worker `PhaseAgent` up to `max_repair_rounds` (`3`) rounds, looping back to Verify.

Before each phase prompt is sent, `merge_or_append_user()` ensures consecutive `user` messages are merged cleanly rather than creating back-to-back `user` turns that stall streaming endpoints (notably Vertex/LiteLLM Gemini 4 Argon).

---

## Configuration (`harness_config.json`)

All phase time splits, model token ceilings, retry backoffs, and telemetry paths live in `harness_config.json` and are validated at load time by `aura_harness/config.py`:

```json
{
  "phase_budgets": {
    "plan_share": 0.10,
    "plan_max_sec": 1200,
    "verify_share": 0.30,
    "verify_round_share": 0.35,
    "verify_max_sec": 900,
    "max_repair_rounds": 3,
    "min_repair_sec": 600,
    "wrap_sec": 300
  },
  "model_limits": {
    "max_output_tokens": 32000,
    "min_output_tokens": 1024,
    "compact_at_tokens": 150000,
    "tool_result_chars": 30000,
    "direct_mcp_chars": 40000,
    "max_tools": 128,
    "keep_recent_results": 12,
    "unread_keep": 600,
    "context_margin": 1024,
    "finish_margin_sec": 180,
    "request_timeout_sec": 900,
    "retry_waits": [5, 15, 30, 60, 120]
  },
  "telemetry": {
    "enabled": true,
    "path": "/tmp/aura_telemetry.jsonl",
    "summary_path": "/tmp/aura_summary.json"
  }
}
```

Invalid values (for example `plan_share <= 0`, `max_output_tokens < min_output_tokens`, `compact_at_tokens < 1024`, negative retry delays, or malformed JSON) fail fast with `ConfigError`.

---

## Environment Variables (`.env.example`)

Copy `.env.example` to `.env` for local runs (never commit `.env`, `.proxy_key`, or `.vertex_sa_key.json`):

| Variable | Required | Purpose / Default |
|---|---|---|
| `MODEL_NAME` | Yes | Model identifier (for example `gemini-4-argon`). |
| `MODEL_BASE_URL` | Recommended | OpenAI-compatible proxy/endpoint URL; falls back to `OPENAI_BASE_URL` then `GOOGLE_GEMINI_BASE_URL`. |
| `MODEL_API_KEY` | Recommended | API key; falls back to `OPENAI_API_KEY`, `GEMINI_API_KEY`, or `"none"`. |
| `PORT` | No | WebSocket listen port for `taskbridge.run` (default `8765`). |
| `REASONING_EFFORT` | No | Overrides automatic effort selection (`max` for Claude/GLM/GPT-6/DeepSeek-v4, else `high`). |
| `AURA_CONFIG_PATH` | No | Path to custom config JSON overriding `harness_config.json`. |
| `AURA_VERIFY_SHARE` | No | Overrides `phase_budgets.verify_share` (default `0.30`). |
| `AURA_MAX_REPAIR_ROUNDS` | No | Overrides `phase_budgets.max_repair_rounds` (default `3`). |
| `MAX_OUTPUT_TOKENS` | No | Overrides `model_limits.max_output_tokens` (default `32000`). |
| `COMPACT_AT_TOKENS` | No | Overrides `model_limits.compact_at_tokens` (default `150000`). |
| `AURA_TELEMETRY_ENABLED` | No | Enables/disables JSONL telemetry (`true` / `false`, default `true`). |
| `AURA_TELEMETRY_PATH` | No | Output JSONL path (default `/tmp/aura_telemetry.jsonl`). Must be writable when `/opt/harness` is read-only. |
| `AURA_SUMMARY_PATH` | No | Per-session JSON summary path (default `/tmp/aura_summary.json`). |
| `JUDGE_BASE_URL` / `JUDGE_API_KEY` / `JUDGE_MODEL` | Local eval | Used by external PLE `checks-judge` / `rubric` evaluator containers (on WSL2 Docker Desktop, point containers at `http://host.docker.internal:4000/v1` rather than `172.17.0.1:4000`). |

---

## Local Setup, Validation, and Tests

### 1. Run validation and unit tests locally

Using `uv` with Python 3.12:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python scripts/validate.py
.venv/bin/python -m pytest -v tests
```

`scripts/validate.py` verifies:
- `harness_config.json` parses and passes schema validation (`load_config(..., env={})`).
- `.env.example` and `submission.yaml` exist.
- All `.py` files compile cleanly via `py_compile`.
- No API key or private key patterns exist inside the repository.

### 2. Validate inside the PLE kit / Docker harness

From the PLE benchmark workspace:

```bash
uv run python -m kit check /path/to/aura-harness
```

On WSL2 with Docker Desktop, run your local LiteLLM/Vertex proxy bound on `0.0.0.0:4000` and pass `JUDGE_BASE_URL=http://host.docker.internal:4000/v1` for judge containers (`172.17.0.1` is unreachable from inside the Docker Desktop VM).

### 3. Run the server directly (smoke test)

```bash
MODEL_NAME=gemini-4-argon MODEL_BASE_URL=http://localhost:4000/v1 MODEL_API_KEY=your-key \
  python serve.py
```

`taskbridge` prints `listening on 8765` (or `$PORT`) when ready for evaluator WebSocket connections.

---

## Structured Telemetry and Artifacts

During each session, `TelemetryLogger` appends sanitized JSONL records to `telemetry.path` (`/tmp/aura_telemetry.jsonl`) and writes a session rollup to `telemetry.summary_path` (`/tmp/aura_summary.json`).

Logged events include:
- `session_start` (`model`, `mcp_count`, `time_budget_s`)
- `model_call` (`model`, `prompt_tokens`, `completion_tokens`, `cached_tokens`, `finish`, `latency_s`, `tool_call_count`)
- `tool_call` (`tool`, `duration_s`, `ok`)
- `compaction` (`mode`, `cut_results`, `dropped_msgs`)
- `retry` (`reason`, `wait_s`)
- `phase` (`phase`, `status`, `budget_s`, `duration_s`)

Telemetry never writes raw prompts, task instructions, tool payloads, or API credentials. If the telemetry path is unwritable, it warns once on stderr and continues without interrupting the agent.

---

## Failure Modes and Debugging Playbooks

### Model exceeds context window or output ceiling

- **What happens:** If `prompt_tokens` exceeds the adaptive threshold (`compute_compact_at()`), or the provider returns a 400/stream context-overflow error matching `CONTEXT_FULL`, `Agent.compact()` trims old tool results (`trim_old_tool_results()`) keeping the latest `keep_recent_results` (`12`) outputs, and if needed summarizes older turns via `SUMMARY_PROMPT` while keeping at most `keep_recent` recent messages.
- **400 output-limit errors:** `parse_smaller_output_limit()` extracts the allowed token ceiling from provider errors and clamps `max_output` down cleanly rather than crashing.
- **Cut-off replies (`finish == "length"`):** Incomplete text replies nudge continuation; malformed partial tool arguments return a recoverable tool-error string prompting smaller `write_file(..., append=true)` chunks.
- **Where to look:** `compaction` events in `/tmp/aura_telemetry.jsonl` and stderr lines from `engine.py`.

### Request timeouts, transient errors, and phase time exhaustion

- **What happens:** Transient network, rate-limit, server, or `StreamCut` failures retry using `model_limits.retry_waits` (`[5, 15, 30, 60, 120]` seconds). Each call deadline respects remaining task/phase time minus `finish_margin_sec` (`180` s). If waiting or completing would overrun the deadline, `OutOfTime` or `CutOff` is raised and the agent calls `finish()` cleanly so verified deliverables and the final summary are returned before the evaluator kills the container.
- **Model compatibility fallbacks:** Unsupported `reasoning_effort`, `max_completion_tokens`, or Responses-only models (`gpt-6`) are automatically detected (`should_drop_effort()`, `should_use_max_tokens()`, `should_use_responses()`) and retried with compatible parameters.

### MCP server connection or tool-call failures

- **What happens:** `Agent.connect_mcp()` initializes every server in `session.mcp_servers`. If fewer than `max_tools` (`128`) tools exist and schemas fit within `direct_mcp_chars` (`40000`), tools are exposed directly as `<server>__<tool>`; otherwise tools are discovered on demand via `mcp_find` and invoked via `mcp_call`.
- **How to debug:**
  1. Confirm the server URL passes `taskbridge.mcp_allows()` (exact server URL, `?query` on queryless base URL, or `/subpath`; no `.` / `..`, backslashes, `%2f`, `%5c`, or `;`).
  2. Check `mcp_target()` constraints: if the evaluator gave a server URL that already contains a `?query`, no extra subpath or query string can be appended.
  3. Inspect `tool_call` events with `"ok": false` in `/tmp/aura_telemetry.jsonl` and container stderr logs prefixed `aura:` or `engine:`.

### Missing or misconfigured environment variables

- **What happens:** `validate_runtime_env()` runs at startup in `serve.py`. Missing `MODEL_NAME` is flagged explicitly; unset `MODEL_BASE_URL` or `MODEL_API_KEY` emits non-secret warnings (`env notice:` on stderr) while leaving behavior intact.
- **Quick fix:** Verify `MODEL_NAME`, `MODEL_BASE_URL`, and `MODEL_API_KEY` against `.env.example`, and test endpoint connectivity with `scripts/validate.py` followed by a smoke check (`kit check`).
