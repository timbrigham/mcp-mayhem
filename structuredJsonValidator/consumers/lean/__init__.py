"""Consumer #1: the Lean-declaration registry (the dogfood dataset, spec §13).

Everything Lean-specific lives here — the schema file, the per-disposition
business rules, the operation verbs, and the projections. The generic core in
``core/`` imports none of it; a second consumer would add a sibling package.
"""

from __future__ import annotations

from pathlib import Path

from core.engine import Registry
from core.schema import load_schema
from consumers.lean import operations, rules, views

SCHEMA_PATH = Path(__file__).with_name("declaration.schema.json")


def build_registry(data_path, *, audit_path=None, actor: str = "cli") -> Registry:
    """Wire the generic :class:`Registry` with the Lean consumer's pieces."""
    return Registry(
        data_path=data_path,
        schema=load_schema(SCHEMA_PATH),
        business_validator=rules.validate,
        operations=operations.OPERATIONS,
        views=views.VIEWS,
        entries_key="entries",
        id_key="id",
        audit_path=audit_path,
        actor=actor,
    )
