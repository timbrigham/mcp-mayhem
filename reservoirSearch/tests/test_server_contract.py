"""The MCP surface: every tool titled, annotated read-only, declaring an outputSchema with `ok`."""

from __future__ import annotations

import anyio

from reservoir_server import server as srv


def _tools():
    return {t.name: t for t in anyio.run(srv.mcp.list_tools)}


def test_the_tool_set():
    assert set(_tools()) == {"search", "get_package", "dependents", "builds_on", "toolchains",
                             "status", "reload"}


def test_every_tool_is_titled_annotated_read_only_and_typed():
    for name, t in _tools().items():
        assert t.title, name
        a = t.annotations
        assert a is not None and None not in (a.readOnlyHint, a.destructiveHint,
                                              a.idempotentHint, a.openWorldHint), name
        assert a.readOnlyHint is True and a.destructiveHint is False, name
        assert a.openWorldHint is False, name
        assert t.outputSchema and "ok" in t.outputSchema.get("required", []), name


def test_a_refusal_is_ok_false_with_its_success_condition(tmp_path, monkeypatch):
    from reservoir_core.index import Store
    monkeypatch.setattr(srv, "STORE", Store(tmp_path / "missing"))
    out = anyio.run(lambda: srv._guard("status"))
    assert out["ok"] is False and out["error_type"] == "config" and out["satisfied_when"]


def test_distinct_module_path_and_port():
    assert srv.mcp.settings.port == 8014
    assert srv.__name__ == "reservoir_server.server"
