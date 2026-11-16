"""AURA harness: plan, work, verify, repair, on the reference engine.

Four phases run inside the task container, each with its own share of the time
budget:

1. PLAN:   inspect the task files, write a deliverable-by-deliverable plan
           (path, format, how to verify) to a plan file.
2. WORK:   execute the plan, writing each deliverable early and improving it.
3. VERIFY: a fresh reviewer conversation opens every deliverable, checks it
           against the plan and the task, replies PASS or lists concrete gaps.
4. REPAIR: gaps go back to the worker. Loop while time remains.

The engine (streaming, tool execution, context compaction, retries, MCP) is the
reference custom-openai harness, imported unchanged as `engine`. This file only
decides what to ask it, when, and for how long: `PhaseAgent.run_phase` is the
engine's own loop with a per-phase deadline added.
"""

import asyncio
import os
import sys
import time
from typing import Any

import engine
import taskbridge

PLAN_PATH = "/tmp/aura_plan.md"
VERIFY_SHARE = float(os.environ.get("AURA_VERIFY_SHARE", "0.30"))
MAX_REPAIR_ROUNDS = int(os.environ.get("AURA_MAX_REPAIR_ROUNDS", "3"))
MIN_REPAIR_SEC = 600  # no repair round with less than 10 min left
WRAP_SEC = 300  # kept for the final summary
REVIEW_TOOLS = ("bash", "read_file", "mcp_find", "mcp_call")


def log(msg: str) -> None:
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
  """The engine's agent with a per-phase deadline on top of the task deadline."""

  def __init__(self, session: taskbridge.Session):
    super().__init__(session)
    self.phase_end: float | None = None

  def phase_left(self) -> float | None:
    """Seconds left in the current phase, or None if unbounded."""
    task = self.session.time_left()
    phase = None if self.phase_end is None else self.phase_end - time.monotonic()
    if task is None:
      return phase
    return task if phase is None else min(task, phase)

  async def run_phase(self, prompt: str, budget: float | None) -> str:
    """Appends `prompt` and runs the tool loop until the model answers or the
    phase budget runs out. The engine's compaction, retries and tool handling
    are reused as-is."""
    self.phase_end = None if budget is None else time.monotonic() + budget
    self.messages.append({"role": "user", "content": prompt})
    nudges, head = 0, ""
    while True:
      left = self.phase_left()
      if left is not None and left < self.finish_margin:
        return await self.finish("Time for this step is almost up.")
      try:
        reply = await self.complete(head=head)
      except engine.OutOfTime:
        return await self.finish(
            "Time is almost up, and the model is not answering.")
      except engine.CutOff:
        return await self.finish("Time for this step is almost up.")
      arguments = [engine.parse_arguments(c) for c in reply.calls.values()]
      if reply.text or reply.calls:
        self.messages.append(reply.message())
      text = engine.visible(head + reply.text)
      if text:
        self.session.final_message = text
      if not reply.calls:
        if engine.visible(reply.text) and reply.finish == "length":
          nudges, head = 0, head + reply.text
          self.messages.append({
              "role": "user",
              "content": (
                  f"Your reply was cut off at the {self.max_output}-token"
                  " output limit. Continue where it stopped, and put long"
                  " content in files with write_file rather than in a reply."),
          })
          continue
        if engine.visible(reply.text) or nudges >= 2:
          return text or self.session.final_message
        nudges += 1
        self.messages.append({
            "role": "user",
            "content": ("Continue this step; when it is done, answer with "
                        "your summary."),
        })
        continue
      nudges, head = 0, ""
      for call, args in zip(reply.calls.values(), arguments):
        result = (await self.run_tool(call["name"], args)
                  if isinstance(args, dict) else args)
        if reply.finish == "length" and isinstance(args, str):
          result += (f" Your reply hit the {self.max_output}-token output"
                     " limit; write large files in parts.")
        self.messages.append(
            {"role": "tool", "tool_call_id": call["id"], "content": result})
      left = self.phase_left()
      if left is not None:
        self.messages[-1]["content"] += f"\n[{int(left // 60)} minutes left for this step]"
      if self.prompt_tokens > self.compact_at():
        await self.compact()


def is_pass(verdict: str) -> bool:
  return verdict.strip("*_. \r\n\t").upper() in ("", "PASS")


async def solve(session: taskbridge.Session) -> str:
  left = session.time_left()
  log(f"task: workdir {session.workdir}, model {engine.MODEL}, "
      f"{len(session.mcp_servers)} MCP server(s), {left} s")

  worker = PhaseAgent(session)
  mcp = await worker.connect_mcp()
  worker.finish_margin = (engine.FINISH_MARGIN_SEC if left is None
                          else min(engine.FINISH_MARGIN_SEC, max(left, 0) / 4))
  system = {
      "role": "system",
      "content": engine.SYSTEM.format(
          workdir=session.workdir, mcp=mcp,
          minutes=int(left / 60) if left else "unlimited"),
  }
  worker.messages = [system, {"role": "user", "content": session.instruction}]

  # PLAN: 10% of the time, at most 20 minutes
  plan_budget = None if left is None else min(0.10 * left, 1200)
  log(f"plan: budget {plan_budget}")
  await worker.run_phase(PLANNER.format(plan=PLAN_PATH), plan_budget)

  # WORK: all remaining time except the verify share
  left = session.time_left()
  work_budget = None if left is None else left * (1 - VERIFY_SHARE)
  log(f"work: budget {work_budget}")
  summary = await worker.run_phase(WORKER.format(plan=PLAN_PATH), work_budget)
  session.final_message = summary or session.final_message

  # VERIFY / REPAIR
  for round_no in range(1, MAX_REPAIR_ROUNDS + 1):
    left = session.time_left()
    if left is not None and left < MIN_REPAIR_SEC + WRAP_SEC:
      log(f"verify: skipped, {int(left)} s left")
      break
    v_budget = None if left is None else min(0.35 * (left - WRAP_SEC), 900)
    log(f"verify round {round_no}: budget {v_budget}")
    reviewer = PhaseAgent(session)
    await reviewer.connect_mcp()
    reviewer.finish_margin = worker.finish_margin
    reviewer.tools = [t for t in reviewer.tools
                      if t["function"]["name"] in REVIEW_TOOLS]
    reviewer.messages = [system, {"role": "user", "content": session.instruction}]
    verdict = (await reviewer.run_phase(
        VERIFIER.format(plan=PLAN_PATH, summary=summary or ""), v_budget) or "").strip()
    log(f"verify round {round_no}: {verdict[:400]!r}")
    session.final_message = summary or session.final_message  # not the verdict
    if is_pass(verdict):
      break
    left = session.time_left()
    if left is not None and left < MIN_REPAIR_SEC + WRAP_SEC:
      break
    r_budget = None if left is None else left - WRAP_SEC
    log(f"repair round {round_no}: budget {r_budget}")
    summary = (await worker.run_phase(REPAIR.format(gaps=verdict), r_budget)
               or summary)
    session.final_message = summary or session.final_message

  return summary or session.final_message


if __name__ == "__main__":
  taskbridge.run(solve)
