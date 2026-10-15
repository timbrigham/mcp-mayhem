"""Every MCP tool call writes one row to tool_calls.jsonl, reads included (core/calls.py).

Added 2026-10-15 for the guard-coverage unit change (session -> agent instance). The row must
carry the client's own per-call id from the request's `_meta`, because one MCP session can hold
hundreds of subagents and only that id can be traced back to the agent that made the call.
"""

import asyncio
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp.server.lowlevel.server import request_ctx  # noqa: E402
from mcp.shared.context import RequestContext  # noqa: E402
from mcp.types import CallToolRequestParams  # noqa: E402

from core import calls  # noqa: E402
from gitrobot_server import server  # noqa: E402

ROW_KEYS = {"ts", "tool", "surface", "session", "client_call_id", "client_call_id_state",
            "outcome", "error_type", "exception", "refusal_id", "versions", "pid"}


def _rows(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.fixture
def served(repo, tmp_path, monkeypatch):
    """The registered tool functions, pointed at the fixture repo and a temp data dir."""
    monkeypatch.setattr(server, "REPO", repo)
    monkeypatch.setattr(server, "DATA", tmp_path / "data" / "git_ops.jsonl")
    tools = server.mcp._tool_manager._tools
    return type("Served", (), {
        "tool": staticmethod(lambda name: tools[name].fn),
        "calls": tmp_path / "data" / calls.FILENAME,
        "audit": tmp_path / "data" / "git_ops.jsonl",
    })


def _in_request(coro_fn, meta_json):
    """Run a tool inside a request context whose `_meta` is parsed from wire JSON, the way the
    low-level server builds it, so the test covers the real model's extra-key handling."""
    params = {"name": "x", "arguments": {}}
    if meta_json is not None:
        params["_meta"] = meta_json
    meta = CallToolRequestParams.model_validate(params).meta

    async def run():
        token = request_ctx.set(RequestContext(request_id=1, meta=meta, session=None,
                                               lifespan_context=None))
        try:
            return await coro_fn()
        finally:
            request_ctx.reset(token)
    return asyncio.run(run())


def test_a_read_writes_a_row_with_the_client_call_id(served):
    """A Tier 3 read is not audited, but it is logged here, with the id from `_meta`."""
    out = _in_request(lambda: served.tool("read")(op="log", args=["-1", "--oneline"]),
                      {"claudecode/toolUseId": "toolu_READ1", "progressToken": 7})
    assert out["ok"] is True, out
    rows = _rows(served.calls)
    assert len(rows) == 1, rows
    row = rows[0]
    assert set(row) == ROW_KEYS, row
    assert (row["tool"], row["client_call_id"], row["outcome"]) == ("read", "toolu_READ1",
                                                                     "returned")
    assert row["error_type"] is None and row["refusal_id"] is None
    assert row["surface"] == "mcp"
    assert row["ts"].endswith("+00:00")
    assert not _rows(served.audit), "a read must still write no audit row"


def test_a_refusal_is_joined_to_its_audit_row_by_client_call_id(served):
    """The audit row carries the same client_call_id, so the join needs neither time nor the
    refusal_id (which repeats on a retry: the second identical refusal must still join to its
    own call)."""
    for cid in ("toolu_REF1", "toolu_REF2"):
        out = _in_request(lambda: served.tool("push")(branch="+illustrated", reason="probe"),
                          {"claudecode/toolUseId": cid})
        assert out["ok"] is False and out["error_type"] == "refusal", out
    rows = _rows(served.calls)
    assert [(r["outcome"], r["error_type"], r["client_call_id"]) for r in rows] == [
        ("refused", "refusal", "toolu_REF1"), ("refused", "refusal", "toolu_REF2")], rows
    assert rows[0]["refusal_id"] and rows[0]["refusal_id"] == rows[1]["refusal_id"], \
        "refusal_id is not unique per call, which is why the join uses client_call_id"
    audit = [r for r in _rows(served.audit) if r["decision"] == "refused"]
    assert [r["client_call_id"] for r in audit] == ["toolu_REF1", "toolu_REF2"], audit
    assert audit[0]["detail"].startswith(f"[{rows[0]['refusal_id']}]")


def test_a_gate_refusal_has_no_refusal_id_but_still_joins(served, repo, fake_gate):
    """The commit gate raises without a refusal_id; its audit rows still name the call."""
    fake_gate(1)
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    assert _in_request(lambda: served.tool("stage")(paths=["tracked.txt"]),
                       {"claudecode/toolUseId": "toolu_STG"})["ok"] is True
    msg = repo.parent / "msg.txt"
    msg.write_text("a message\n", encoding="utf-8")
    out = _in_request(lambda: served.tool("commit")(message_file=str(msg), reason="probe"),
                      {"claudecode/toolUseId": "toolu_GATE"})
    assert out["ok"] is False, out
    row = _rows(served.calls)[-1]
    assert (row["tool"], row["client_call_id"]) == ("commit", "toolu_GATE"), row
    assert (row["outcome"], row["error_type"], row["refusal_id"]) == ("refused", "refusal",
                                                                       None), row
    audit = [r for r in _rows(served.audit) if r["op"] == "commit"]
    assert audit and all(r["client_call_id"] == "toolu_GATE" for r in audit), audit


def test_a_non_refusal_error_is_failed_with_its_type(served):
    out = _in_request(lambda: served.tool("read")(op="log", repo_mode="nope"),
                      {"claudecode/toolUseId": "toolu_BAD"})
    assert out["ok"] is False and out["error_type"] == "usage", out
    row = _rows(served.calls)[-1]
    assert (row["outcome"], row["error_type"], row["refusal_id"]) == ("error", "usage", None)


def test_no_meta_and_an_unknown_key_both_record_null(served):
    _in_request(lambda: served.tool("read")(op="log", args=["-1"]), None)
    _in_request(lambda: served.tool("read")(op="log", args=["-1"]), {"other/id": "zzz"})
    rows = _rows(served.calls)
    assert len(rows) == 2
    for row in rows:
        assert "client_call_id" in row and row["client_call_id"] is None, row


def test_outside_a_request_the_call_is_still_logged(served):
    """No request context at all (a direct call): the row is written with a null id."""
    out = asyncio.run(served.tool("read")(op="log", args=["-1"]))
    assert out["ok"] is True
    row = _rows(served.calls)[-1]
    assert row["client_call_id"] is None and row["outcome"] == "returned"
    assert row["client_call_id_state"] == "absent"


def test_an_unexpected_exception_is_logged_and_still_raised(served, monkeypatch):
    def boom(self, *a, **k):
        raise RuntimeError("unexpected")
    # server.GitRobot, not core.engine's: another test reloads that module, after which the two
    # names are different classes and patching the fresh one leaves the server's untouched.
    monkeypatch.setattr(server.GitRobot, "status", boom)
    with pytest.raises(RuntimeError):
        _in_request(lambda: served.tool("status")(), {"claudecode/toolUseId": "toolu_BOOM"})
    row = _rows(served.calls)[-1]
    assert (row["tool"], row["outcome"], row["client_call_id"]) == ("status", "raised",
                                                                     "toolu_BOOM")
    assert row["exception"] == "RuntimeError" and row["error_type"] is None


@pytest.mark.parametrize("call", [
    lambda t: t("read")(op="log", args=["-1"]),                         # allowed
    lambda t: t("push")(branch="+illustrated", reason="probe"),         # refused
    lambda t: t("read")(op="log", repo_mode="nope"),                    # failed
    lambda t: t("vocabulary")(),
])
def test_a_log_write_failure_never_changes_the_result(served, monkeypatch, call):
    expected = asyncio.run(call(served.tool))

    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(calls, "append", broken)

    class _DeadStderr:
        def write(self, *_):
            raise OSError("broken pipe")
        flush = write
    monkeypatch.setattr(server.sys, "stderr", _DeadStderr())
    out = asyncio.run(call(served.tool))
    assert out["ok"] == expected["ok"] and out.get("error_type") == expected.get("error_type")


def test_a_robot_that_cannot_be_built_is_logged_and_still_raises(served, monkeypatch):
    """Building the robot raised out of the tool before this log existed; it still must, and
    the call still gets its row."""
    from core.errors import RepoError

    def no_repo():
        raise RepoError("not a git repository")
    monkeypatch.setattr(server, "_robot", no_repo)
    with pytest.raises(RepoError):
        _in_request(lambda: served.tool("status")(), {"claudecode/toolUseId": "toolu_NOREPO"})
    row = _rows(served.calls)[-1]
    assert (row["tool"], row["outcome"], row["client_call_id"]) == ("status", "raised",
                                                                     "toolu_NOREPO")
    assert (row["error_type"], row["exception"]) == ("repo", "RepoError"), row


def test_an_overlong_call_id_is_recorded_as_null(served):
    _in_request(lambda: served.tool("read")(op="log", args=["-1"]),
                {"claudecode/toolUseId": "x" * (calls.MAX_CALL_ID + 1)})
    _in_request(lambda: served.tool("read")(op="log", args=["-1"]),
                {"claudecode/toolUseId": "y" * calls.MAX_CALL_ID})
    assert [(r["client_call_id"], r["client_call_id_state"]) for r in _rows(served.calls)] == [
        (None, "unusable"), ("y" * calls.MAX_CALL_ID, "present")]


def test_every_tool_is_logged_under_its_own_name():
    """`_guard`'s first argument is both the row's `tool` and the GitRobot method it runs, so it
    must be the registered tool's own name. The one tool not routed through `_guard` must log
    for itself, under its own name."""
    import ast
    from core.engine import GitRobot
    tree = ast.parse(Path(server.__file__).read_text(encoding="utf-8"))
    guarded, self_logged = {}, set()
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef) or node.name.startswith("_"):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and getattr(sub.func, "id", None) == "_guard":
                assert isinstance(sub.args[0], ast.Constant), node.name
                guarded[node.name] = sub.args[0].value
            if isinstance(sub, ast.Call) and getattr(sub.func, "id", None) == "_log_call":
                assert isinstance(sub.args[0], ast.Constant), node.name
                assert sub.args[0].value == node.name, (node.name, sub.args[0].value)
                self_logged.add(node.name)
    registered = set(server.mcp._tool_manager._tools)
    assert len(guarded) >= 20, guarded
    assert set(guarded) | self_logged == registered, registered ^ (set(guarded) | self_logged)
    assert all(tool == name for tool, name in guarded.items()), guarded
    assert all(callable(getattr(GitRobot, name, None)) for name in guarded.values())


def test_the_vocabulary_tool_logs_both_outcomes(served):
    _in_request(lambda: served.tool("vocabulary")(), {"claudecode/toolUseId": "toolu_V1"})
    _in_request(lambda: served.tool("vocabulary")(name="nope"), {"claudecode/toolUseId": "toolu_V2"})
    rows = [(r["tool"], r["client_call_id"], r["outcome"], r["error_type"])
            for r in _rows(served.calls)]
    assert rows == [("vocabulary", "toolu_V1", "returned", None),
                    ("vocabulary", "toolu_V2", "error", "usage")], rows


def test_the_vocabulary_tool_logs_an_unexpected_exception(served, monkeypatch):
    import mcpcommon.vocabulary as v

    def boom(_name):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(v, "as_payload", boom)
    with pytest.raises(RuntimeError):
        _in_request(lambda: served.tool("vocabulary")(), {"claudecode/toolUseId": "toolu_V3"})
    row = _rows(served.calls)[-1]
    assert (row["tool"], row["outcome"], row["exception"]) == ("vocabulary", "raised",
                                                                "RuntimeError")


def test_client_call_id_takes_a_dict_or_a_model_and_never_raises():
    """'sent nothing' (absent) and 'sent something unusable' are kept apart."""
    assert calls.client_call_id({"claudecode/toolUseId": "t1"}) == ("t1", "present")
    assert calls.client_call_id({"claudecode/toolUseId": ""}) == (None, "unusable")
    assert calls.client_call_id({"claudecode/toolUseId": 5}) == (None, "unusable")
    assert calls.client_call_id({"other/id": "t1"}) == (None, "absent")
    assert calls.client_call_id(None) == (None, "absent")
    assert calls.client_call_id(object()) == (None, "absent")


def test_the_writer_refuses_an_unpublished_outcome_or_an_inconsistent_state(tmp_path):
    with pytest.raises(AssertionError):
        calls.append(tmp_path / "c.jsonl", tool="read", call_id=None, call_id_state="absent",
                     outcome="allowed")
    with pytest.raises(AssertionError):
        calls.append(tmp_path / "c.jsonl", tool="read", call_id=None, call_id_state="present",
                     outcome="returned")
    with pytest.raises(AssertionError):
        calls.append(tmp_path / "c.jsonl", tool="read", call_id="t", call_id_state="absent",
                     outcome="returned")
    assert not (tmp_path / "c.jsonl").exists()
