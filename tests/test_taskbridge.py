"""Unit tests for MCP URL allowlisting, request routing, HTTP framing, and Relay."""

from __future__ import annotations

import asyncio
import base64
import json
import urllib.request

import pytest

import taskbridge
from conftest import FakeSession


def test_mcp_allows_exact_subpath_query_and_blocks_traversal() -> None:
  servers = [{"name": "cad", "url": "http://127.0.0.1:9001/mcp"}]

  assert taskbridge.mcp_allows("http://127.0.0.1:9001/mcp", servers) is True
  assert taskbridge.mcp_allows("http://127.0.0.1:9001/mcp?token=1", servers) is True
  assert taskbridge.mcp_allows("http://127.0.0.1:9001/mcp/tools/list", servers) is True

  # Prefix spoofing and traversal must be rejected
  assert taskbridge.mcp_allows("http://127.0.0.1:9001/mcp2", servers) is False
  assert taskbridge.mcp_allows("http://127.0.0.1:9001/mcp/../secret", servers) is False
  assert taskbridge.mcp_allows("http://127.0.0.1:9001/mcp/%2e%2e/x", servers) is False
  assert taskbridge.mcp_allows("http://127.0.0.1:9001/mcp/a%2fb", servers) is False
  assert taskbridge.mcp_allows("http://127.0.0.1:9001/mcp/a\\b", servers) is False
  assert taskbridge.mcp_allows("http://127.0.0.1:9001/mcp/a;b", servers) is False
  assert taskbridge.mcp_allows("https://evil.example.com/mcp", servers) is False


def test_mcp_target_appends_path_and_rejects_modifying_query_base() -> None:
  assert taskbridge.mcp_target("http://127.0.0.1:9001/mcp", "", "") == "http://127.0.0.1:9001/mcp"
  assert (
      taskbridge.mcp_target("http://127.0.0.1:9001/mcp/", "tools", "x=1")
      == "http://127.0.0.1:9001/mcp/tools?x=1"
  )
  with pytest.raises(taskbridge.TaskError):
    taskbridge.mcp_target("http://127.0.0.1:9001/mcp?k=1", "sub", "")


def test_positive_int_seconds_text_and_time_share() -> None:
  assert taskbridge.positive_int(5, 10) == 5
  assert taskbridge.positive_int(0, 10) == 10
  assert taskbridge.positive_int(True, 10) == 10
  assert taskbridge.positive_int(12.2, 10, cap=15) == 13
  assert taskbridge.positive_int(9999, 10, cap=600) == 600

  assert taskbridge._seconds(None) == 120
  assert taskbridge._seconds(9999) == taskbridge.MAX_TIMEOUT_SEC
  with pytest.raises(taskbridge.TaskError):
    taskbridge._seconds(float("nan"))

  with pytest.raises(taskbridge.TaskError):
    taskbridge._text("cmd", "")
  with pytest.raises(taskbridge.TaskError):
    taskbridge._text("cmd", "bad\x00nul")

  assert taskbridge.time_share(100.0, 30.0, fraction=0.25) == 75.0
  assert taskbridge.time_share(1000.0, 30.0, fraction=0.25) == 970.0


def test_relay_routes_exec_files_and_mcp_and_enforces_token() -> None:
  sess = FakeSession(mcp_servers=[{"name": "cad", "url": "http://127.0.0.1:9001/mcp"}])

  async def scenario() -> None:
    async with taskbridge.Relay(sess) as relay:
      env = relay.env({"NO_PROXY": "example.local"})
      assert env["TASK_RELAY_URL"] == relay.url
      assert env["NO_PROXY"].startswith("127.0.0.1,localhost,")

      def post(subpath: str, payload: dict | bytes, method: str = "POST"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{relay.url}/{subpath}",
            data=body if method != "GET" else None,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
          with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
          return e.code, e.read().decode()

      st, res = await asyncio.to_thread(post, "exec", {"command": "echo hi", "timeout_sec": 30})
      assert st == 200 and res["ok"] is True

      b64 = base64.b64encode(b"hello ple").decode()
      st_w, res_w = await asyncio.to_thread(post, "write_file", {"path": "/app/out.txt", "content_b64": b64})
      assert st_w == 200 and res_w == {"ok": True, "size": 9}

      st_r, res_r = await asyncio.to_thread(post, "read_file", {"path": "/app/out.txt"})
      assert st_r == 200 and base64.b64decode(res_r["content_b64"]) == b"hello ple"

      st_m, _ = await asyncio.to_thread(post, "mcp/cad/", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
      assert st_m == 200
      assert sess.http_calls[-1]["url"] == "http://127.0.0.1:9001/mcp"

      st_get, _ = await asyncio.to_thread(post, "mcp/cad/", b"", "GET")
      assert st_get == 405

      st_unk, _ = await asyncio.to_thread(post, "mcp/unknown/", {"x": 1})
      assert st_unk == 404

  asyncio.run(scenario())


def test_mcp_client_parses_sse_and_tracks_session_header() -> None:
  sess = FakeSession(mcp_servers=[{"name": "docs", "url": "http://127.0.0.1:9002/mcp"}])

  async def fake_http(url, method="POST", headers=None, body=b"", timeout_sec=120):
    sse = (
        'event: message\n'
        'data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18"}}\n\n'
    ).encode()
    return {
        "status": 200,
        "headers": {"Mcp-Session-Id": "sess-42"},
        "body": sse,
        "truncated": False,
    }

  sess.http = fake_http
  client = taskbridge.MCPClient(sess, "http://127.0.0.1:9002/mcp")
  res = asyncio.run(client.initialize())
  assert res["protocolVersion"] == "2025-06-18"
  assert client.headers["Mcp-Session-Id"] == "sess-42"
