"""Flat-file store: canonical serialization, atomic writes, content hashing.

The flat JSON file is the source of truth and the published artifact (spec §2).
Nothing binary is ever persisted. All writes go through :func:`atomic_write_json`
so a crash mid-write cannot corrupt the source (spec §7 / principle 7).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def canonical_bytes(document: Any) -> bytes:
    """Serialize a document to the exact bytes we write to disk.

    Deterministic (stable key order as given, 2-space indent, trailing newline,
    UTF-8, non-ASCII preserved for readability). The content hash in the audit
    log is computed over *these* bytes, so read-back hashing must reproduce them
    exactly — hence a single canonical serializer used by both write and verify.
    """
    text = json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False)
    return (text + "\n").encode("utf-8")


def canonical_export_bytes(document: Any) -> bytes:
    """Serialize a document for *publication* — deterministic by content alone.

    Distinct from :func:`canonical_bytes`, which preserves the source's
    human-authored key order. Here every object's keys are sorted recursively
    (``sort_keys=True``) so the exported bytes depend only on the data, not on
    how the source happened to be constructed. Combined with the caller sorting
    array entries into a stable order, this makes the published artifact's git
    diffs meaningful and reviewable.
    """
    text = json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True)
    return (text + "\n").encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_document(document: Any) -> str:
    """SHA-256 of a document as it *would* be serialized on disk."""
    return sha256_hex(canonical_bytes(document))


def read_json(path: str | os.PathLike) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def hash_file(path: str | os.PathLike) -> str:
    """SHA-256 of the raw bytes currently on disk (out-of-band edits included)."""
    with open(path, "rb") as fh:
        return sha256_hex(fh.read())


def atomic_write_bytes(path: str | os.PathLike, payload: bytes) -> str:
    """Write raw ``payload`` atomically (temp-then-rename). Returns its SHA-256.

    The temp file is created in the same directory so ``os.replace`` is a true
    atomic rename on the same filesystem (works on Windows and POSIX).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)  # atomic on same filesystem
    except BaseException:
        # Best-effort cleanup of the temp file if the rename never happened.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return sha256_hex(payload)


def atomic_write_json(path: str | os.PathLike, document: Any) -> str:
    """Write ``document`` to disk atomically in canonical (source) form."""
    return atomic_write_bytes(path, canonical_bytes(document))
