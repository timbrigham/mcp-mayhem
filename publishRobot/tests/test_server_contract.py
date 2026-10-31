"""The MCP surface of both servers: every tool titled, annotated and declaring an outputSchema;
approve ONLY on publishApprove; and approve exposing every payload field, because its arguments
ARE what the approving human reads."""

from __future__ import annotations

import inspect

import anyio

from publish_core.engine import PAYLOAD_FIELDS
from publishapprove_server import server as approve_srv
from publishrobot_server import server as draft_srv


def _tools(srv):
    return {t.name: t for t in anyio.run(srv.mcp.list_tools)}


def test_drafting_server_has_no_approve():
    """⛔ The drafting server is registered device-wide. If approve ever lands on it, every
    session can approve its own queue, and only a deny rule somewhere else would stop it."""
    assert set(_tools(draft_srv)) == {"queue", "withdraw", "pending", "history"}
    assert not hasattr(draft_srv, "approve")


def test_approval_server_has_only_approve():
    assert set(_tools(approve_srv)) == {"approve"}


def test_every_tool_is_titled_annotated_and_typed():
    for srv in (draft_srv, approve_srv):
        for name, t in _tools(srv).items():
            assert t.title, name
            a = t.annotations
            assert a is not None and None not in (a.readOnlyHint, a.destructiveHint,
                                                  a.idempotentHint, a.openWorldHint), name
            assert t.outputSchema and "ok" in t.outputSchema.get("required", []), name


def test_only_approve_reaches_the_outside_world():
    draft = _tools(draft_srv)
    assert not any(t.annotations.openWorldHint for t in draft.values())
    assert _tools(approve_srv)["approve"].annotations.openWorldHint is True
    for n in ("pending", "history"):
        assert draft[n].annotations.readOnlyHint is True


def test_approve_shows_every_payload_field():
    """⛔ If a field drops off `approve`'s signature, the permission prompt stops showing it and
    the human approves bytes they cannot see."""
    params = set(inspect.signature(approve_srv.approve).parameters)
    assert {"id", *PAYLOAD_FIELDS} <= params
    schema = _tools(approve_srv)["approve"].inputSchema["properties"]
    assert {"id", *PAYLOAD_FIELDS} <= set(schema)


def test_servers_use_distinct_names_and_ports():
    assert draft_srv.mcp.name != approve_srv.mcp.name
    assert draft_srv.mcp.settings.port != approve_srv.mcp.settings.port
