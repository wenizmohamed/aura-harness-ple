# AURA Harness

Entry for Google's Agent Harness on Physical-Engineering's Last Exam (PLE).

A small, auditable control layer on top of the reference custom-openai engine. The engine (streaming, tool execution, context compaction, retries, MCP) is imported unchanged as `engine`; this harness decides what to ask the model, when, and for how long.

## How it works

Four time-budgeted phases run inside each task container:

1. **Plan** - enumerate every deliverable (exact path, format, required contents) and how a reviewer would check it. About 10 percent of the budget, capped at 20 minutes.
2. **Work** - execute the plan, writing each deliverable early and then improving it, computing every number in code. Remaining time minus the verify share.
3. **Verify** - a fresh reviewer with read-only tools opens every deliverable and replies PASS or lists concrete gaps.
4. **Repair** - gaps go back to the worker; verify and repair loop while time remains (up to three rounds).

Each phase carries its own deadline with a finish margin that scales with time left, and no repair round opens with under ten minutes left.

## Files

- `serve.py` - the harness entry (plan, work, verify, repair).
- `engine.py` - the reference engine, imported unchanged.
- `taskbridge.py` - task container bridge and tool plumbing.
- `submission.yaml` - model pin (`google-cloud/gemini-4-argon`) plus install and serve commands.
- `requirements.txt` - runtime dependencies.

## Model access

The model is reached through a local Vertex AI service-account proxy (kept out of this repo) that exposes the OpenAI-compatible endpoint the engine already speaks, so runs are reproducible and stay off the interactive quota.

## Run

See `submission.yaml`: the kit installs with `uv` into an isolated Python 3.12 virtualenv and serves `serve.py`.
