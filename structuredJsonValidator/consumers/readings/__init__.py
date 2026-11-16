"""The ``blind_readings`` collection (2026-11-15): the consumer's /reconstruct
runs — a blind reader's restatement of each declaration from its signature alone,
and the DIFF-1 items where the file's prose claims more than the signature says.

Indexed from the consumer's append-only JSONL by ``ingest_reconstruct``. Keyed on
the Lean registry's minted id where one exists, else on (path, blob, line). The
ledger's ``reconstruct`` step reads its record body from
:func:`consumers.readings.views.verdict_for`."""

from __future__ import annotations

from pathlib import Path

from consumers.readings import operations, rules, views

SCHEMA_PATH = Path(__file__).with_name("reading.schema.json")


def empty_doc() -> dict:
    return {"schema_version": "1", "runs": [], "entries": []}
