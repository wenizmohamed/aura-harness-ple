"""AURA harness: config-driven plan, work, verify, repair orchestrator."""

from __future__ import annotations

import sys
import time
from typing import Any

import engine
import taskbridge
from aura_harness.config import HarnessConfig, load_config, validate_runtime_env
from aura_harness.stream import merge_or_append_user, visible
from aura_harness.telemetry import TelemetryLogger


DEFAULT_CONFIG = load_config()
PLAN_PATH = "/tmp/aura_plan.md"
VERIFY_SHARE = DEFAULT_CONFIG.phase_budgets.verify_share
MAX_REPAIR_ROUNDS = DEFAULT_CONFIG.phase_budgets.max_repair_rounds
MIN_REPAIR_SEC = DEFAULT_CONFIG.phase_budgets.min_repair_sec
WRAP_SEC = DEFAULT_CONFIG.phase_budgets.wrap_sec
REVIEW_TOOLS = ("bash", "read_file", "mcp_find", "mcp_call")


def log(msg: str) -> None:
  """Writes one harness log line to stderr."""
  print(f"aura: {msg}", file=sys.stderr, flush=True)


PLANNER = """You are the planning engineer on this task. Do NOT create or modify any deliverable yet.

Steps:
1. Read the whole task and every file you were given (bash + read_file).
2. Identify every deliverable: its exact path, file format, and what the task says it must contain.
3. For each deliverable, write how a reviewer would check it (constraints, units, format, required sections).
4. Note any hard constraints (safety, feasibility, code requirements) that must not be broken.

Write the plan to {plan} with write_file, then answer with a one-paragraph summary of the plan."""

WORKER = """You are the working engineer on this task. A plan was prepared and is at {plan}. Read it first with read_file.

Then execute the task:
- Write each deliverable exactly where, under the name and in the format the plan says. Write it early, then improve it.
- Compute every number with code, check units, and keep every hard constraint from the plan.
- Produce office and binary formats with code so they are real files.
- Before you answer, reopen every deliverable and confirm it is complete and readable.

When done, answer without calling a tool: a short summary of what you delivered (path of each file) and the key results."""

VERIFIER = """You are an independent reviewing engineer. You did not do this work. Do NOT create or modify any deliverable.

The plan is at {plan}. The worker's summary of what they delivered is below.

Open every deliverable the plan names (bash + read_file). For each one check:
- it exists at the exact path and opens as the stated format
- every required section, value and unit the task asks for is present
- numbers are plausible and hard constraints are not broken
- nothing the task asked for is missing

Reply with exactly PASS if everything is correct. Otherwise list each specific gap as one line: the path, what is wrong, what would fix it. Do not list style preferences, only real gaps.

Worker summary:
{summary}"""

REPAIR = """An independent reviewer opened your deliverables and found these gaps:

{gaps}

Fix each one, reopen the files to confirm, then answer with your updated summary of the deliverables."""


class PhaseAgent(engine.Agent):
  """The engine's agent with per-phase budgets and safe user-turn merging."""

  def __init__(
      self,
      session: taskbridge.Session,
      *,
      config: HarnessConfig | None = None,
      telemetry: TelemetryLogger | None = None,
  ):
    super().__init__(session, config=config, telemetry=telemetry)
    self.phase_end: float | None = None

  def phase_left(self) -> float | None:
    """Seconds left in the current phase, or None if unbounded."""
    task = self.session.time_left()
    phase = None if self.phase_end is None else self.phase_end - time.monotonic()
    if task is None:
      return phase
    return task if phase is None else min(task, phase)

  async def run_phase(self, prompt: str, budget: float | None) -> str:
    """Runs one budgeted phase without creating consecutive user-role stalls."""
    self.phase_end = None if budget is None else time.monotonic() + budget
    merge_or_append_user(self.messages, prompt)
    nudges, head = 0, ""
    while True:
      left = self.phase_left()
      if left is not None and left < self.finish_margin:
        return await self.finish("Time for this step is almost up.")
      try:
        reply = await self.complete(head=head)
      except engine.OutOfTime:
        return await self.finish(
            "Time is almost up, and the model is not answering."
        )
      except engine.CutOff:
        return await self.finish("Time for this step is almost up.")
      arguments = [engine.parse_arguments(c) for c in reply.calls.values()]
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
                "Continue this step; when it is done, answer with "
                "your summary."
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
              f" Your reply hit the {self.max_output}-token output"
              " limit; write large files in parts."
          )
        self.messages.append(
            {"role": "tool", "tool_call_id": call["id"], "content": result}
        )
      left = self.phase_left()
      if left is not None:
        self.messages[-1]["content"] += f"\n[{int(left // 60)} minutes left for this step]"
      if self.prompt_tokens > self.compact_at():
        await self.compact()


def is_pass(verdict: str) -> bool:
  """Returns True if the independent reviewer reported PASS or empty verdict."""
  return verdict.strip("*_. \r\n\t").upper() in ("", "PASS")


async def solve(
    session: taskbridge.Session,
    *,
    config: HarnessConfig | None = None,
    telemetry: TelemetryLogger | None = None,
) -> str:
  """Executes Plan -> Work -> Verify <-> Repair phases under configured budgets."""
  cfg = config or load_config()
  pb = cfg.phase_budgets
  env_report = validate_runtime_env()
  for warning in env_report.warnings:
    log(f"env notice: {warning}")
  tel = telemetry or TelemetryLogger(
      enabled=cfg.telemetry.enabled,
      path=cfg.telemetry.path,
      summary_path=cfg.telemetry.summary_path,
  )

  left = session.time_left()
  log(
      f"task: workdir {session.workdir}, model {engine.MODEL}, "
      f"{len(session.mcp_servers)} MCP server(s), {left} s"
  )
  tel.emit(
      "session_start",
      model=engine.MODEL,
      mcp_count=len(session.mcp_servers),
      time_budget_s=round(left, 2) if left is not None else None,
  )

  status = "completed"
  summary = ""
  try:
    worker = PhaseAgent(session, config=cfg, telemetry=tel)
    mcp = await worker.connect_mcp()
    base_margin = float(cfg.model_limits.finish_margin_sec)
    worker.finish_margin = (
        base_margin
        if left is None
        else min(base_margin, max(left, 0.0) / 4.0)
    )
    system = {
        "role": "system",
        "content": engine.SYSTEM.format(
            workdir=session.workdir,
            mcp=mcp,
            minutes=int(left / 60) if left else "unlimited",
        ),
    }
    worker.messages = [system, {"role": "user", "content": session.instruction}]

    # PLAN
    plan_budget = (
        None if left is None else min(pb.plan_share * left, float(pb.plan_max_sec))
    )
    log(f"plan: budget {plan_budget}")
    t_phase = time.monotonic()
    await worker.run_phase(PLANNER.format(plan=PLAN_PATH), plan_budget)
    tel.record_phase("plan", "done", plan_budget, time.monotonic() - t_phase)

    # WORK
    left = session.time_left()
    work_budget = None if left is None else left * (1.0 - pb.verify_share)
    log(f"work: budget {work_budget}")
    t_phase = time.monotonic()
    summary = await worker.run_phase(WORKER.format(plan=PLAN_PATH), work_budget)
    tel.record_phase("work", "done", work_budget, time.monotonic() - t_phase)
    session.final_message = summary or session.final_message

    # VERIFY / REPAIR
    for round_no in range(1, pb.max_repair_rounds + 1):
      left = session.time_left()
      if left is not None and left < pb.min_repair_sec + pb.wrap_sec:
        log(f"verify: skipped, {int(left)} s left")
        tel.record_phase(f"verify_{round_no}", "skipped_low_time", 0.0, 0.0)
        break
      v_budget = (
          None
          if left is None
          else min(pb.verify_round_share * (left - pb.wrap_sec), float(pb.verify_max_sec))
      )
      log(f"verify round {round_no}: budget {v_budget}")
      t_phase = time.monotonic()
      reviewer = PhaseAgent(session, config=cfg, telemetry=tel)
      await reviewer.connect_mcp()
      reviewer.finish_margin = worker.finish_margin
      reviewer.tools = [
          t for t in reviewer.tools if t["function"]["name"] in REVIEW_TOOLS
      ]
      reviewer.messages = [system, {"role": "user", "content": session.instruction}]
      verdict = (
          await reviewer.run_phase(
              VERIFIER.format(plan=PLAN_PATH, summary=summary or ""), v_budget
          )
          or ""
      ).strip()
      passed = is_pass(verdict)
      tel.record_phase(
          f"verify_{round_no}",
          "pass" if passed else "gaps",
          v_budget,
          time.monotonic() - t_phase,
      )
      log(f"verify round {round_no}: {verdict[:400]!r}")
      session.final_message = summary or session.final_message
      if passed:
        break
      left = session.time_left()
      if left is not None and left < pb.min_repair_sec + pb.wrap_sec:
        tel.record_phase(f"repair_{round_no}", "skipped_low_time", 0.0, 0.0)
        break
      r_budget = None if left is None else left - pb.wrap_sec
      log(f"repair round {round_no}: budget {r_budget}")
      t_phase = time.monotonic()
      summary = (
          await worker.run_phase(REPAIR.format(gaps=verdict), r_budget)
          or summary
      )
      tel.record_phase(f"repair_{round_no}", "done", r_budget, time.monotonic() - t_phase)
      session.final_message = summary or session.final_message

    return summary or session.final_message
  except Exception as exc:
    status = f"error:{type(exc).__name__}"
    raise
  finally:
    tel.outcome = {"summary_chars": len(summary or session.final_message or "")}
    tel.write_summary(model=engine.MODEL, status=status)


if __name__ == "__main__":
  taskbridge.run(solve)
