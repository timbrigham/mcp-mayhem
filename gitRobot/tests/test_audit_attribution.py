"""Every audit row names its surface and session, always as keys, null when unknown.

Added 2026-10-09 (core/callctx.py). The values are set once at the entry point and must reach
rows written later on a background thread (preflight and push completions), which a plain
`threading.Thread` would not carry.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core import callctx

ROOT = Path(__file__).resolve().parents[1]


def _rows(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.fixture(autouse=True)
def _fresh_context():
    """Each test starts with no caller set, as a library caller would."""
    callctx.SURFACE.set(None)
    callctx.SESSION.set(None)


def test_every_record_type_carries_both_keys(robot, dirty, fake_gate):
    """allowed, refused, started and passed/failed rows, including ones written on the preflight
    thread, all carry the caller set at the entry point."""
    callctx.set_caller("mcp", "sess-abc")
    robot.stage(["tracked.txt"])                       # allowed
    with pytest.raises(Exception):
        robot.read("reset", ["--hard"])                # refused
    fake_gate(1)
    # NOT wait=True: that runs inline and never touches the background thread, which is the hop
    # this test exists for (a mutant dropping the thread's context survived the wait=True form).
    robot.preflight(wait=False)                        # started now, completion on the thread
    import time
    deadline = time.monotonic() + 60
    while robot.preflight_status()["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.2)
    assert robot.preflight_status()["state"] in ("passed", "failed")
    rows = _rows(robot.audit.path)
    assert "failed" in {r["decision"] for r in rows}, "the thread-written completion row is missing"
    decisions = {r["decision"] for r in rows}
    assert {"allowed", "refused", "started"} <= decisions, decisions
    assert len(rows) >= 4
    for r in rows:
        assert r["surface"] == "mcp" and r["session"] == "sess-abc", r


def test_a_library_caller_records_explicit_nulls(robot, dirty):
    robot.stage(["tracked.txt"])
    row = _rows(robot.audit.path)[-1]
    assert "surface" in row and "session" in row
    assert row["surface"] is None and row["session"] is None


def test_the_cli_records_surface_cli_and_a_null_session(repo, dirty, tmp_path):
    data = tmp_path / "cli_ops.jsonl"
    r = subprocess.run([sys.executable, "-m", "core.cli", "--repo", str(repo), "--data", str(data),
                        "stage", "tracked.txt"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    row = _rows(data)[-1]
    assert row["surface"] == "cli" and "session" in row and row["session"] is None, row


def test_the_mcp_tool_records_the_request_session(repo, dirty, tmp_path, monkeypatch):
    """Through the registered tool function: the session id read from the request reaches the
    row, across the worker-thread hop."""
    pytest.importorskip("mcp")
    from gitrobot_server import server
    monkeypatch.setattr(server, "REPO", repo)
    monkeypatch.setattr(server, "DATA", tmp_path / "mcp_ops.jsonl")
    monkeypatch.setattr(server, "_session_id", lambda: "sess-from-request")
    stage = server.mcp._tool_manager._tools["stage"].fn
    out = asyncio.run(stage(paths=["tracked.txt"]))
    assert out["ok"] is True, out
    row = _rows(tmp_path / "mcp_ops.jsonl")[-1]
    assert row["surface"] == "mcp" and row["session"] == "sess-from-request", row


def test_the_session_id_is_read_from_the_request_header(monkeypatch):
    pytest.importorskip("mcp")
    from gitrobot_server import server

    class _Req:
        headers = {"mcp-session-id": "abc123"}

    class _Ctx:
        class request_context:
            request = _Req()

    monkeypatch.setattr(server.mcp, "get_context", lambda: _Ctx())
    assert server._session_id() == "abc123"

    def _outside():
        raise ValueError("no request")

    class _NoCtx:
        @property
        def request_context(self):
            _outside()

    monkeypatch.setattr(server.mcp, "get_context", lambda: _NoCtx())
    assert server._session_id() is None


def test_an_unknown_surface_is_refused():
    with pytest.raises(ValueError):
        callctx.set_caller("web")


def test_the_session_header_is_read_from_a_real_starlette_request(monkeypatch):
    """The real Headers object, not a dict: lookup is case-insensitive, which the server relies on."""
    pytest.importorskip("mcp")
    from starlette.requests import Request
    from gitrobot_server import server
    scope = {"type": "http", "method": "POST", "path": "/mcp", "query_string": b"",
             "headers": [(b"mcp-session-id", b"real-123"), (b"content-type", b"application/json")]}

    class _Ctx:
        class request_context:
            request = Request(scope)

    monkeypatch.setattr(server.mcp, "get_context", lambda: _Ctx())
    assert server._session_id() == "real-123"


def test_concurrent_calls_keep_their_own_sessions(repo, tmp_path, monkeypatch):
    """Two calls in flight at once, each with its own session, write rows naming their own."""
    pytest.importorskip("mcp")
    import contextvars
    from gitrobot_server import server
    which = contextvars.ContextVar("which_session")
    monkeypatch.setattr(server, "REPO", repo)
    monkeypatch.setattr(server, "DATA", tmp_path / "mcp_ops.jsonl")
    monkeypatch.setattr(server, "_session_id", lambda: which.get())
    for name in ("a.txt", "b.txt"):
        (repo / name).write_text(name, encoding="utf-8")
    stage = server.mcp._tool_manager._tools["stage"].fn

    async def one(session, path):
        which.set(session)
        return await stage(paths=[path])

    async def both():
        return await asyncio.gather(one("sess-A", "a.txt"), one("sess-B", "b.txt"))

    assert all(o["ok"] for o in asyncio.run(both()))
    by_path = {r["args"]["paths"][0]: r["session"] for r in _rows(tmp_path / "mcp_ops.jsonl")
               if r["op"] == "stage"}
    assert by_path == {"a.txt": "sess-A", "b.txt": "sess-B"}, by_path


def test_the_reaper_records_surface_internal(repo, tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    import threading
    from gitrobot_server import server
    monkeypatch.setattr(server, "REPO", repo)
    monkeypatch.setattr(server, "DATA", tmp_path / "reaper_ops.jsonl")
    started = []
    monkeypatch.setattr(threading, "Thread",
                        lambda target, **kw: type("T", (), {"start": lambda self: started.append(target)})())

    class _Stop(BaseException):
        pass

    def _stop(_seconds):
        raise _Stop

    monkeypatch.setattr(server.time, "sleep", _stop)
    # A sweep with nothing to reap writes no row, so record the attribution in force at the
    # moment the reap runs; any row it writes reads the same values (core/callctx.current).
    seen = []
    from core.engine import GitRobot
    monkeypatch.setattr(GitRobot, "worktree", lambda self, action, **kw: seen.append(callctx.current()))
    server._start_worktree_reaper()
    with pytest.raises(_Stop):
        started[0]()                        # one sweep, then the sleep ends the loop
    assert seen == [{"surface": "internal", "session": None}], seen