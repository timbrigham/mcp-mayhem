"""The ``claims`` collection (interop issue #12): the framework's named claim
graph and its honest epistemic status, living INSIDE sjv as a second collection
alongside ``declarations``. A node and an edge share ONE shape (an edge is a claim
with ``from``/``to`` populated). The killer cross-collection invariant — a
``proved``/``deep`` claim needs a live declaration witness — is enforced at the
store level (see :func:`consumers.store.witness_invariant`)."""

from __future__ import annotations

from pathlib import Path

from consumers.claims import operations, rules, views

SCHEMA_PATH = Path(__file__).with_name("claim.schema.json")


def empty_doc() -> dict:
    """The pre-founding claims sub-document (no anchor/counts — claims are not
    scanned from source, they are authored)."""
    return {"schema_version": "1", "entries": []}
