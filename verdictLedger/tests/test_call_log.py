"""Controls for the shared HTTP call log (`mcpcommon/calllog.py`).

⚠ THE MODULE UNDER TEST IS SHARED AND LIVES AT THE REPO ROOT, but the test lives here
because this is where a suite already runs (`cd verdictLedger && python -m pytest -q`),
and verdictLedger is the first server wired to it. A test in a directory nobody runs is
not a control. Move it to a shared suite when a second server adopts the module AND that
suite is in CLAUDE.md's test commands — not before.

⚠⚠ BOTH OF THE FIRST TWO TESTS PIN A BUG THAT WAS REAL, not a hypothetical. Each was
found on 2026-09-05 by running the thing rather than reading it, which is the entire
reason they are tests and not comments.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcpcommon.calllog import CallLogMiddleware, build_logger  # noqa: E402


def _drive(middleware, body: bytes, scope=None):
    """Run one request through the middleware and return the ASGI messages it forwarded."""
    sent = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    scope = scope or {"type": "http", "path": "/mcp", "method": "POST",
                      "client": ("127.0.0.1", 5555)}
    asyncio.run(middleware(scope, receive, send))
    return sent


def _rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


async def _echo_app(scope, receive, send):
    """Answers in TWO body chunks, the way a streamed response arrives."""
    while True:
        message = await receive()
        if not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b'{"ok":true,', "more_body": True})
    await send({"type": "http.response.body", "body": b'"pad":"' + b"z" * 900 + b'"}'})


def test_tool_name_survives_a_truncated_body(tmp_path, monkeypatch):
    """⭐⭐ THE FIELD THAT ANSWERS THE QUESTION MUST NOT BE READ OFF THE TRUNCATED COPY.

    `tool` exists to answer "which of our tools does the consumer actually call". It was
    first parsed from the CLIPPED request text, so it resolved only when the body
    happened to fit under the cap — every call large enough to be interesting logged
    `tool: null`. Measured 2026-09-05 with a 64-byte cap: a well-formed `tools/call` for
    `append` recorded no tool at all.

    That is this repo's defect class exactly — a true value read against the wrong
    object, here the truncated copy rather than the bytes that arrived. The fix parses
    from the raw request; this test fails if anyone re-points it at `req_text`.
    """
    monkeypatch.setenv("ZPLOG_DIR", str(tmp_path))
    logger, path = build_logger("t")
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "append",
                                  "arguments": {"record": {"pad": "y" * 400}}}}).encode()

    _drive(CallLogMiddleware(_echo_app, logger, max_body=64, server_name="t"), body)
    for handler in logger.handlers:
        handler.flush()

    row = _rows(path)[-1]
    assert row["tool"] == "append", "tool name lost to truncation"
    assert row["rpc_method"] == "tools/call"
    assert row["req_truncated"] is True, "cap of 64 should have truncated a 400-byte body"
    # ⚠ The byte count prices THE WIRE, never the stored excerpt. Two fields, two claims.
    assert row["req_bytes"] == len(body)
    assert len(row["req"]) <= 64


def test_zplog_dir_is_a_root_and_never_the_final_path(tmp_path, monkeypatch):
    """⭐⭐ ONE EXPORTED ZPLOG_DIR MUST NOT AIM FOUR SERVERS AT ONE FILE.

    `ZPLOG_DIR` used to BE the log directory, so a single exported value gave every
    server the same `http_calls.jsonl`. Four processes sharing one RotatingFileHandler
    do not merely interleave lines: rollover RENAMES the open file, which fails on
    Windows while another process holds it, so the log stops rotating and grows without
    bound — an observability feature becoming a disk outage.

    Appending `server_name` makes the collision unrepresentable. This test is what keeps
    it that way.
    """
    monkeypatch.setenv("ZPLOG_DIR", str(tmp_path))
    _, path_a = build_logger("alpha")
    _, path_b = build_logger("beta")

    assert path_a != path_b, "two servers must never share one call log"
    assert path_a.parent.name == "alpha"
    assert path_b.parent.name == "beta"


def test_response_is_forwarded_unchanged_and_streaming_is_preserved(tmp_path, monkeypatch):
    """The middleware OBSERVES; it must not buffer or rewrite the transport.

    ⚠ This is why it is raw ASGI rather than Starlette's `BaseHTTPMiddleware`, which
    materialises a response and would collapse streamable-HTTP into a buffered reply.
    Two body messages in, two body messages out, byte-identical.
    """
    monkeypatch.setenv("ZPLOG_DIR", str(tmp_path))
    logger, path = build_logger("t")

    sent = _drive(CallLogMiddleware(_echo_app, logger, max_body=100_000, server_name="t"),
                  b'{"jsonrpc":"2.0","id":1,"method":"initialize"}')
    for handler in logger.handlers:
        handler.flush()

    kinds = [m["type"] for m in sent]
    assert kinds == ["http.response.start", "http.response.body", "http.response.body"]
    forwarded = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert json.loads(forwarded)["ok"] is True

    row = _rows(path)[-1]
    assert row["resp_bytes"] == len(forwarded)
    assert row["status"] == 200


def test_an_exception_is_logged_and_re_raised(tmp_path, monkeypatch):
    """⚠ The most interesting row must not be the one that goes unwritten.

    A handler that blew up used to leave no trace; the log now records it and re-raises
    unchanged, so the middleware never swallows a server error it merely observed.
    """
    monkeypatch.setenv("ZPLOG_DIR", str(tmp_path))
    logger, path = build_logger("t")

    async def boom(scope, receive, send):
        await receive()
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError, match="kaboom"):
        _drive(CallLogMiddleware(boom, logger, max_body=100, server_name="t"), b"{}")
    for handler in logger.handlers:
        handler.flush()

    row = _rows(path)[-1]
    assert "kaboom" in (row["error"] or ""), "the failing call left no row"


def test_logging_never_breaks_serving(tmp_path, monkeypatch):
    """⚠⚠ THIS SERVER IS A MANDATORY DEPENDENCY OF EVERY COMMIT AND PUSH.

    A full disk, a revoked permission, an unserialisable field — none of them may turn
    into a failed push. The write is best-effort and the request still completes. The
    cost of that swallow is that a broken log is SILENT, which is exactly why
    `selftest()` runs at startup where a failure is loud; verified here by breaking the
    writer outright and asserting the response still lands.
    """
    monkeypatch.setenv("ZPLOG_DIR", str(tmp_path))
    logger, _ = build_logger("t")

    middleware = CallLogMiddleware(_echo_app, logger, max_body=100, server_name="t")
    monkeypatch.setattr(middleware, "_write",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))

    sent = _drive(middleware, b'{"jsonrpc":"2.0","id":1}')
    assert [m["type"] for m in sent][0] == "http.response.start"
    assert any(m["type"] == "http.response.body" for m in sent), \
        "a failed log write must not cost the caller its response"


def test_the_join_key_is_captured(tmp_path, monkeypatch):
    """⭐⭐ THE TWO-SIDED COMPARISON NEEDS A ROW-TO-ROW JOIN, NOT TWO PILES.

    Logging on both sides is the disagreement check applied to the transport: our record
    of what ARRIVED against the consumer's of what they SENT. That only works if the rows
    line up. `(tool, timestamp, byte count)` is not enough — same host means one clock,
    but a retry loop emits identical tool and size inside one second, which is precisely
    the traffic worth inspecting.

    ⚠ `rpc_id` needs no new protocol surface: JSON-RPC already requires an `id` the caller
    chooses. It is logged whatever they send, because a REPEATED id is itself a finding
    about the caller — the stock client sends a constant 1 and 2.
    """
    monkeypatch.setenv("ZPLOG_DIR", str(tmp_path))
    logger, path = build_logger("t")
    body = json.dumps({"jsonrpc": "2.0", "id": "7f3c1e2a-uuid", "method": "tools/call",
                       "params": {"name": "append"}}).encode()
    # ⚠ Header name deliberately mixed-case: ASGI does not normalise, so the lookup must.
    scope = {"type": "http", "path": "/mcp", "method": "POST", "client": ("127.0.0.1", 1),
             "headers": [(b"Mcp-Session-Id", b"sess-abc123")]}
    _drive(CallLogMiddleware(_echo_app, logger, max_body=9999, server_name="t"), body, scope)
    for handler in logger.handlers:
        handler.flush()

    row = _rows(path)[-1]
    assert row["rpc_id"] == "7f3c1e2a-uuid", "caller's JSON-RPC id is the join key"
    assert row["session"] == "sess-abc123", "session header lookup must be case-insensitive"
    assert row["tool"] == "append"
