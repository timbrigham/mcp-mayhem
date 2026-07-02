"""Append-only audit + hash-drift log (spec §10).

One JSONL record per successful write, never mutated:
    { ts, actor, op, params, entries_touched, resulting_sha256 }

The log doubles as (a) a complete, transparent mutation history and (b) the
integrity anchor: the current file must hash to the last record's
``resulting_sha256`` before any new operation, else the file was edited out of
band (spec §6). Detection, not prevention — also run as a pre-commit/CI gate.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.errors import IntegrityError
from core.store import hash_file


def default_audit_path(data_path: str | os.PathLike) -> Path:
    """Sidecar next to the data file: ``<data>.audit.jsonl`` (spec §15 choice)."""
    p = Path(data_path)
    return p.with_name(p.name + ".audit.jsonl")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_records(audit_path: str | os.PathLike) -> list[dict]:
    path = Path(audit_path)
    if not path.exists():
        return []
    records: list[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def last_record(audit_path: str | os.PathLike) -> Optional[dict]:
    records = read_records(audit_path)
    return records[-1] if records else None


def append_record(
    audit_path: str | os.PathLike,
    *,
    actor: str,
    op: str,
    params: Any,
    entries_touched: list[str],
    resulting_sha256: str,
) -> dict:
    """Append one immutable record. Returns the record written."""
    record = {
        "ts": _now_iso(),
        "actor": actor,
        "op": op,
        "params": params,
        "entries_touched": list(entries_touched),
        "resulting_sha256": resulting_sha256,
    }
    path = Path(audit_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n")
    return record


def verify_integrity(data_path: str | os.PathLike, audit_path: str | os.PathLike) -> str:
    """Compare the on-disk file hash to the last audit hash.

    Returns the confirmed hash on success. Raises :class:`IntegrityError` on
    drift. If there is no audit log yet, the file is *unmanaged* — that is not
    drift, but callers that require a sealed baseline should check separately.
    """
    last = last_record(audit_path)
    if last is None:
        raise IntegrityError(
            f"No audit log at {audit_path}: file is unmanaged. Seal a baseline first."
        )
    current = hash_file(data_path)
    expected = last["resulting_sha256"]
    if current != expected:
        raise IntegrityError(
            "Hash drift detected — the data file was edited out of band "
            f"(bypassing the handler).\n  expected {expected}\n  found    {current}\n"
            f"  file     {data_path}"
        )
    return current
