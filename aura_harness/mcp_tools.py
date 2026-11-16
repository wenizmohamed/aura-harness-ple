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

"""Built-in tool specs, system prompts, and task MCP client utilities."""

from __future__ import annotations

import json
import re
from typing import Any

import taskbridge


SYSTEM = """You are an expert engineer working on a task in a Linux container. Your tools act inside it: bash (it \
starts in {workdir}), read_file, write_file and edit_file. The container has no internet access.{mcp}

How to work:
- Read the whole task, then look at the files you were given before choosing an approach.
- Work in small, verified steps. Compute numbers with code rather than by hand, and check units.
- When the task says how the result is checked (a time limit, a format, a test), check it that way yourself.
- Write each deliverable exactly where, under the name and in the format the task asks for. Write it early, then \
improve it.
- Produce office and binary formats (docx, xlsx, pdf, ...) with code, such as python3 and the libraries in the \
container, so they are real files of that format.
- Before you finish, open every deliverable again and check that it is complete and readable.
- You have about {minutes} minutes in total; the time left is shown after the results of your tools.

When the work is done, answer without calling a tool: a short summary of what you delivered (the path of each file) \
and the key results. That answer is graded together with your files."""

MCP_DIRECT = """

The task also offers its own tools (the functions named <server>__<tool>)."""

MCP_CATALOG = """

The task also offers its own tools, listed below by server. Call mcp_find to see a tool's parameters, then mcp_call \
to run it.
{catalog}"""

SUMMARY_PROMPT = """The conversation is getting long, so the earlier turns will be removed. Write notes that let you \
continue without them: what the task requires, what you found in the files, every file you created or changed (with \
its path and state), the numbers and decisions so far, and what remains to do. Be specific."""


def tool(
    name: str, description: str, required: list[str], **properties: Any
) -> dict[str, Any]:
  """Builds an OpenAI function-tool definition dictionary."""
  return {
      "type": "function",
      "function": {
          "name": name,
          "description": description,
          "parameters": {
              "type": "object",
              "properties": properties,
              "required": required,
          },
      },
  }


TOOLS = [
    tool(
        "bash",
        "Run a bash command in the task container and return its exit code and"
        " output. Each call starts a new shell in the working directory: only"
        " files persist between calls.",
        ["command"],
        command={"type": "string"},
        timeout_sec={
            "type": "integer",
            "description": (
                "Stop the command after this many seconds (default 120)."
            ),
        },
    ),
    tool(
        "read_file",
        "Read a text file from the task container.",
        ["path"],
        path={"type": "string"},
    ),
    tool(
        "write_file",
        "Create or overwrite a file in the task container; parent directories"
        " are created.",
        ["path", "content"],
        path={"type": "string"},
        content={"type": "string"},
        append={
            "type": "boolean",
            "description": (
                "Add to the end of the file instead (write a large file in"
                " parts)."
            ),
        },
    ),
    tool(
        "edit_file",
        "Replace exact text in a file. old_text must occur exactly once unless"
        " replace_all is true.",
        ["path", "old_text", "new_text"],
        path={"type": "string"},
        old_text={"type": "string"},
        new_text={"type": "string"},
        replace_all={"type": "boolean"},
    ),
]

MCP_TOOLS = [
    tool(
        "mcp_find",
        "Show the description and parameters of the task's own tools that match"
        " a query.",
        ["query"],
        query={
            "type": "string",
            "description": "A tool name, or words describing what you need.",
        },
    ),
    tool(
        "mcp_call",
        "Run one of the task's own tools.",
        ["tool", "arguments"],
        tool={"type": "string", "description": "The tool's name as listed."},
        arguments={"type": "object"},
    ),
]


class MCPServer(taskbridge.MCPClient):
  """Client wrapper for a single task MCP server and its discovered tools."""

  def __init__(self, session: taskbridge.Session, spec: dict[str, Any]):
    super().__init__(session, spec["url"], client="custom-harness")
    self.name = spec["name"]
    self.tools: list[dict[str, Any]] = []

  async def start(self) -> None:
    """Initializes the MCP session and fetches the server's tool list."""
    await self.initialize()
    self.tools = await self.list_tools()

  async def call(
      self,
      name: str,
      arguments: dict[str, Any],
      result_limit: int = 30_000,
  ) -> str:
    """Calls tool `name` on the MCP server and formats the result as text."""
    result = await self.call_tool(name, arguments)
    parts = []
    content = (
        result.get("content") if isinstance(result.get("content"), list) else []
    )
    for item in content:
      kind = item.get("type") if isinstance(item, dict) else None
      if kind == "text":
        parts.append(str(item.get("text", "")))
      elif kind == "resource":
        parts.append(json.dumps(item.get("resource"))[:result_limit])
      elif kind == "resource_link":
        parts.append(json.dumps(item)[:result_limit])
      else:
        parts.append(f"[{kind or 'unknown'} content not shown]")
    if not parts and result.get("structuredContent") is not None:
      parts.append(json.dumps(result["structuredContent"]))
    text = "\n".join(parts) or "(no content)"
    return f"error: {text}" if result.get("isError") else text


def find_mcp_tools(
    mcp_map: dict[str, tuple[Any, dict[str, Any]]],
    query: str,
    result_limit: int = 30_000,
) -> str:
  """Finds MCP tools matching `query` and formats their descriptions and schemas."""
  words = [w for w in re.split(r"[^a-z0-9]+", query.lower()) if w]

  def score(item: tuple[str, tuple[Any, dict[str, Any]]]) -> int:
    name, (_, t) = item
    text = f"{name} {t.get('description') or ''}".lower()
    return (
        (query == name) * 100
        + sum(w in name.lower() for w in words) * 3
        + sum(w in text for w in words)
    )

  best = [
      item
      for item in sorted(mcp_map.items(), key=score, reverse=True)[:8]
      if score(item) > 0
  ]
  if not best:
    return (
        f"no tool matches {query!r}; the names are listed in the system prompt"
    )
  found = [
      f"{name}: {(t.get('description') or '')[:400]}\nparameters:"
      f" {json.dumps(t.get('inputSchema') or {})}"
      for name, (_, t) in best
  ]
  while len(found) > 1 and len("\n\n".join(found)) > result_limit:
    found.pop()
  return "\n\n".join(found)
