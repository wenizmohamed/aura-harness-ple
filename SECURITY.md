# Security Model and Sandboxing Assumptions

This document describes the trust boundaries, tool capabilities, network protections, and secret-hygiene guarantees of AURA Harness (`aura-harness-pub`).

## 1. Execution Trust Boundaries

The harness operates across two isolated execution contexts mediated by the PLE WebSocket protocol (`taskbridge.py`):

1. **Harness Container (Agent Orchestrator)**
   - Runs `serve.py`, `engine.py`, `aura_harness/*`, and `taskbridge.py` under an isolated Python 3.12 virtualenv (`/opt/harness/venv`).
   - Stage-2 evaluation containers mount `/opt/harness` read-only with capped CPU/RAM (for example 2 CPUs, 4 GB RAM, 6-hour task limit) and writable temporary paths (`/tmp`, `$HOME`).
   - Holds only the model endpoint configuration (`MODEL_NAME`, `MODEL_BASE_URL`, `MODEL_API_KEY`). Does not execute task commands directly on its own filesystem unless explicitly instructed for scratch work like `/tmp/aura_plan.md` or telemetry in `/tmp/`.

2. **Task Container (Evaluator Sandbox)**
   - Runs inside an isolated Harbor/Docker environment with no general internet access (egress controlled by evaluator sidecars).
   - All model-initiated shell commands (`bash`) and file operations (`read_file`, `write_file`, `edit_file`) execute inside the task container over authenticated WebSocket protocol frames (`taskbridge.Session`), never directly on the host machine.

## 2. Tool-Layer Capabilities and Guards

The agent intentionally receives broad command and filesystem access inside the **task container** (`bash`, `read_file`, `write_file`, `edit_file`) because engineering benchmark tasks require compiling models, running solvers, inspecting fixtures, and writing binary/office deliverables.

Guardrails enforced by the harness and protocol bridge:

- **Phase-scoped tool restriction (`serve.py`):** During the **Verify** phase, the independent reviewer `PhaseAgent` is restricted to read-only inspection tools (`REVIEW_TOOLS = ("bash", "read_file", "mcp_find", "mcp_call")`), preventing the verifier from rewriting worker deliverables.
- **Message and size bounds (`taskbridge.py`):**
  - `MAX_FRAME = 16 MiB` WebSocket message limit in either direction.
  - `MAX_WRITE_BYTES = 10 MB` per write chunk (`WRITE_CHUNK = 4 MiB` auto-chunking for larger payloads).
  - `MAX_HTTP_BYTES = 10 MB` HTTP relay request body cap and `MAX_BODY = 64 MiB` relay payload limit.
  - `MAX_TIMEOUT_SEC = 600` hard clamp on `exec` and `http` request timeouts.
  - `MAX_FINAL_CHARS = 1,000,000` ceiling on final summary payload.
- **Process cleanup:** Subprocesses launched via `taskbridge.run_process()` run in their own process group (`start_new_session=True`) and are terminated across the entire group (`SIGTERM` then `SIGKILL`) upon completion, cancellation, or deadline expiry.

## 3. Local HTTP Relay and MCP SSRF / Traversal Protections

When delegating to subprocess tools via `taskbridge.Relay`:

- **Loopback-only binding:** Binds strictly to `127.0.0.1` on an ephemeral port and embeds a 128-bit random per-session bearer path token (`secrets.token_hex(16)`).
- **Strict HTTP request framing (`_read_request` / `_chunked`):** Handles one request per connection and rejects ambiguous framing (multiple `Content-Length` headers, mismatched lengths, combined `Transfer-Encoding` and `Content-Length`, invalid chunked encoding, oversized headers > `MAX_HEAD`).
- **MCP allowlist and path normalization (`mcp_allows`, `mcp_target`):**
  - Only URLs matching an evaluator-supplied `session.mcp_servers` base URL (exact match, `?query` on queryless base URL, or `/subpath`) are permitted.
  - Explicitly rejects path traversal segments (`.`, `..`), percent-encoded slashes/backslashes (`%2f`, `%5c`), literal backslashes (`\`), and semicolon path parameters (`;`).
  - Rejects appending paths or queries onto MCP base URLs that already carry their own query string.

## 4. Credential and Telemetry Hygiene

- **No secrets in repository files:** `.gitignore` excludes `.env`, `*.env` (except `.env.example`), `.proxy_key`, `.vertex_sa_key.json`, `*.pem`, `*.key`, and local `runs/`.
- **Automated secret scanning:** `scripts/validate.py` scans all tracked/workspace files on every CI run (`.github/workflows/ci.yml`) for common token prefixes (`hf_`, `sk-`, `ghp_`, `AIza`) and private key headers (`-----BEGIN ... PRIVATE KEY-----`).
- **Non-leaky runtime validation & telemetry:**
  - `validate_runtime_env()` reports missing/unset env variable names without printing key contents.
  - `TelemetryLogger` records only operational metadata (timestamps, model name, phase durations, token counters, tool names, pass/fail flags) and never logs system prompts, task instructions, command outputs, file contents, or credentials.
