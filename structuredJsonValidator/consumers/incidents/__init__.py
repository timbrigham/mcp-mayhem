"""The ``incidents`` collection: actions a tool allowed that were later found harmful.

It lives in its OWN store file, not in the Lean registry the MCP server serves: the incidents are
about the tooling fleet, not about any one project's content. ``build_incident_store`` wires the
generic engine with this one collection, so it gets the same schema validation, verb-only writes
and hash-chained audit as every other consumer.
"""

from __future__ import annotations

from pathlib import Path

from consumers.incidents import operations, rules, views

SCHEMA_PATH = Path(__file__).with_name("incident.schema.json")


def empty_doc() -> dict:
    return {"schema_version": "1", "pattern_rule": rules.PATTERN_RULE, "entries": []}


def build_incident_store(data_path, *, audit_path=None, actor: str = "cli"):
    from core.engine import CollectionSpec, Store
    from core.schema import load_schema

    spec = CollectionSpec(
        schema=load_schema(SCHEMA_PATH),
        business_validator=rules.validate,
        operations=operations.OPERATIONS,
        views=views.VIEWS,
        empty_doc=empty_doc,
        entries_key="entries",
        id_key="id",
    )
    return Store(data_path=data_path, collections={"incidents": spec},
                 audit_path=audit_path, actor=actor)
