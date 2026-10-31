"""The MCP surface: every tool titled, annotated and declaring an outputSchema, and `approve`
exposing every payload field, because its arguments ARE what the approving human reads."""

from __future__ import annotations

import inspect

import anyio

from publish_core.engine import PAYLOAD_FIELDS
from publishrobot_server import server as srv

EXPECTED = {"queue", "approve", "withdraw", "pending", "history"}


def _tools():
    return {t.name: t for t in anyio.run(srv.mcp.list_tools)}


def test_tool_roster_is_exactly_these():
    assert set(_tools()) == EXPECTED


def test_every_tool_is_titled_annotated_and_typed():
    for name, t in _tools().items():
        assert t.title, name
        a = t.annotations
        assert a is not None and None not in (a.readOnlyHint, a.destructiveHint,
                                              a.idempotentHint, a.openWorldHint), name
        assert t.outputSchema and "ok" in t.outputSchema.get("required", []), name


def test_only_approve_reaches_the_outside_world():
    tools = _tools()
    assert [n for n, t in tools.items() if t.annotations.openWorldHint] == ["approve"]
    for n in ("pending", "history"):
        assert tools[n].annotations.readOnlyHint is True


def test_approve_shows_every_payload_field():
    """⛔ If a field drops off `approve`'s signature, the permission prompt stops showing it and
    the human approves bytes they cannot see."""
    params = set(inspect.signature(srv.approve).parameters)
    assert {"id", *PAYLOAD_FIELDS} <= params
    schema = _tools()["approve"].inputSchema["properties"]
    assert {"id", *PAYLOAD_FIELDS} <= set(schema)
