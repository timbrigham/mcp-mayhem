"""Operations for the ``blind_readings`` collection (/reconstruct, 2026-11-15).

ONE write verb, ``ingest_reconstruct``: read the consumer's append-only JSONL and
index it. The JSONL stays the source of truth; this collection is the queryable
copy, keyed so a ledger verdict can bind ``(path, git_blob_id)``.

⛔ THE FILE IS APPEND-ONLY, SO A RE-INGEST MAY ONLY EXTEND WHAT WAS RECORDED.
Every stored row carries the sha256 of the canonical JSON of the line it came from.
Re-ingesting identical bytes is a no-op; a line whose bytes CHANGED under an id that
is already stored is refused, because in an append-only file a changed line is a
rewrite of history, not an update. Dispositions are the one thing that moves, and
they move by NEW lines (``type: "disposition"``) appended per item: the stored
history must be a prefix of the file's history for that item, or the ingest refuses.

⚠ ALL OR NOTHING. A malformed line refuses the whole file, naming the line. A
partial ingest would index some of a run and present it as the run.

⚠ FAIL TOWARD NOTICING. An unknown line ``type`` refuses rather than being skipped
(a new kind of line the consumer starts writing must be priced here, not silently
dropped), and a ``registry_id`` KEY that is absent refuses even where ``null`` would
be accepted: absent and null are different statements, and only one was made.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Optional

from core.errors import OperationError

LINE_TYPES = ("run", "decl", "diff1", "skipped", "disposition")
DISPOSITIONS = ("open", "carried", "applied", "rejected")

# Deterministic ids for readings, so a re-ingest of the same bytes is byte-identical.
_READING_NS = uuid.UUID("b1d0a7e5-0000-4000-8000-0000000b11d0")


def _line_sha(obj: dict) -> str:
    canon = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _refuse(lineno: int, what: str, satisfied_when: str):
    raise OperationError(f"line {lineno}: {what}", satisfied_when=satisfied_when)


def _need(row: dict, lineno: int, *keys: str) -> None:
    missing = [k for k in keys if k not in row]
    if missing:
        _refuse(lineno, f"{row.get('type')!r} line is missing {missing}",
                f"every {row.get('type')!r} line carries {list(keys)} (null is allowed "
                f"where the schema allows it; an absent key is not)")


def _read_jsonl(path: str) -> list[tuple[int, dict]]:
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read().splitlines()
    except FileNotFoundError as exc:
        raise OperationError(f"reconstruct JSONL not found: {path}",
                             satisfied_when="path names an existing JSONL file") from exc
    rows: list[tuple[int, dict]] = []
    for n, text in enumerate(raw, start=1):
        if not text.strip():
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            _refuse(n, f"not valid JSON ({exc})", "every non-blank line is one JSON object")
        if not isinstance(obj, dict):
            _refuse(n, "is not a JSON object", "every non-blank line is one JSON object")
        rows.append((n, obj))
    if not rows:
        raise OperationError(f"reconstruct JSONL is empty: {path}",
                             satisfied_when="the file holds at least one RUN line")
    return rows


def _event(row: dict, sha: str) -> dict:
    return {"disposition": row.get("disposition"), "reason": row.get("reason"),
            "decided_by": row.get("decided_by"), "utc": row.get("utc"),
            "line_sha256": sha}


def _run_entry(row: dict, n: int, sha: str, skipped: list) -> dict:
    _need(row, n, "run_id", "commit", "brief_path", "brief_blob", "reader_prompt_blob",
          "reader_model", "started_utc", "finished_utc", "diff1_count", "examined")
    prompt_path = row.get("reader_prompt_store") or row.get("reader_prompt_path")
    if not prompt_path:
        _refuse(n, "RUN names no reader prompt path",
                "RUN carries reader_prompt_store (preferred) or reader_prompt_path beside "
                "reader_prompt_blob")
    return {
        "run_id": row["run_id"], "commit": row["commit"],
        "brief": {"path": row["brief_path"], "git_blob_id": row["brief_blob"]},
        "reader_prompt": {"path": prompt_path, "git_blob_id": row["reader_prompt_blob"]},
        "reader_model": row["reader_model"],
        "started_utc": row["started_utc"], "finished_utc": row["finished_utc"],
        "diff1_count": row["diff1_count"],
        "examined": [{"path": e.get("path"), "git_blob_id": e.get("git_blob_id")}
                     if isinstance(e, dict) else e for e in (row["examined"] or [])],
        "skipped": skipped,
        "line_sha256": sha,
    }


def _common(row: dict, n: int) -> dict:
    _need(row, n, "run_id", "path", "git_blob_id", "decl", "key_kind", "registry_id")
    return {"run_id": row["run_id"], "path": row["path"], "git_blob_id": row["git_blob_id"],
            "line": row.get("line"), "key_kind": row["key_kind"],
            "registry_id": row["registry_id"],
            "registry_id_reason": row.get("registry_id_reason"),
            "decl": row["decl"]}


def _reading_entry(row: dict, n: int, sha: str) -> dict:
    e = _common(row, n)
    _need(row, n, "is_example", "elaborated_type", "blind_reading")
    rid = uuid.uuid5(_READING_NS, "\x1f".join(
        str(x) for x in (e["run_id"], e["path"], e["git_blob_id"], e["decl"], e["line"])))
    return {"id": str(rid), "kind": "reading", **e,
            "is_example": row["is_example"], "elaborated_type": row["elaborated_type"],
            "blind_reading": row["blind_reading"], "line_sha256": sha}


def _diff1_entry(row: dict, n: int, sha: str) -> dict:
    e = _common(row, n)
    _need(row, n, "item_id", "prose", "signature", "kind", "disposition")
    return {"id": row["item_id"], "kind": "diff1", **e,
            "prose": row["prose"], "signature": row["signature"],
            "diff_kind": row["kind"], "kind_detail": row.get("kind_detail"),
            "line_sha256": sha,
            "dispositions": [_event(row, sha)]}


def ingest_reconstruct(document: Optional[dict], *, path: str) -> tuple[dict, list[str], dict]:
    """Index one reconstruct JSONL file. Returns ``(doc, touched, counts)``."""
    doc = document if document is not None else {"schema_version": "1", "runs": [], "entries": []}
    doc.setdefault("runs", [])
    doc.setdefault("entries", [])
    rows = _read_jsonl(path)

    counts = {t: 0 for t in LINE_TYPES}
    run_rows: dict[str, tuple[int, dict, str]] = {}
    skipped: dict[str, list] = {}
    readings: list[dict] = []
    items: list[dict] = []
    events: dict[str, list[tuple[int, dict]]] = {}

    for n, row in rows:
        t = row.get("type")
        if t not in LINE_TYPES:
            _refuse(n, f"unknown line type {t!r}",
                    f"type is one of {list(LINE_TYPES)}; a new kind of line is priced in "
                    f"sjv before it is written, never skipped")
        if not row.get("run_id"):
            _refuse(n, "carries no run_id", "every line carries the run_id of its RUN")
        counts[t] += 1
        sha = _line_sha(row)
        if t == "run":
            if row["run_id"] in run_rows:
                _refuse(n, f"second RUN line for {row['run_id']!r}",
                        "each run_id has exactly one RUN line")
            run_rows[row["run_id"]] = (n, row, sha)
        elif t == "skipped":
            _need(row, n, "module", "names", "reason")
            skipped.setdefault(row["run_id"], []).append(
                {"module": row["module"], "names": list(row["names"]), "reason": row["reason"]})
        elif t == "decl":
            readings.append(_reading_entry(row, n, sha))
        elif t == "diff1":
            items.append(_diff1_entry(row, n, sha))
        else:
            _need(row, n, "item_id", "disposition", "reason", "decided_by", "utc")
            events.setdefault(row["item_id"], []).append((n, _event(row, sha)))

    for rid in {e["run_id"] for e in readings + items} | set(skipped):
        if rid not in run_rows:
            raise OperationError(
                f"rows reference run_id {rid!r} but the file has no RUN line for it",
                satisfied_when="every run_id used in the file has its RUN line in the file")
    item_ids = {i["id"] for i in items}
    for iid, evs in events.items():
        if iid not in item_ids:
            _refuse(evs[0][0], f"disposition for unknown item_id {iid!r}",
                    "a disposition line names an item_id whose diff1 line is in the same file")
    for i in items:
        i["dispositions"].extend(ev for _, ev in events.get(i["id"], []))

    new_runs = [_run_entry(r, n, sha, skipped.get(rid, []))
                for rid, (n, r, sha) in run_rows.items()]

    # -- merge into the stored document: extend only, never rewrite ----------------
    touched: list[str] = []
    stored_runs = {r["run_id"]: r for r in doc["runs"]}
    for r in new_runs:
        old = stored_runs.get(r["run_id"])
        if old is None:
            doc["runs"].append(r)
            touched.append(r["run_id"])
        elif old != r:
            raise OperationError(
                f"run {r['run_id']!r} is already indexed with different content",
                satisfied_when="the RUN line (and its skipped lines) are byte-identical to "
                               "the ones first ingested; the file is append-only, so a "
                               "changed run is a new run_id")
    stored = {e["id"]: e for e in doc["entries"]}
    for e in readings + items:
        old = stored.get(e["id"])
        if old is None:
            doc["entries"].append(e)
            touched.append(e["id"])
            continue
        if old["line_sha256"] != e["line_sha256"]:
            raise OperationError(
                f"{e['kind']} {e['id']!r} is already indexed from a different line",
                satisfied_when="lines already ingested are unchanged; append a new line "
                               "(a disposition, or a new run) instead of editing one")
        if e["kind"] == "diff1":
            have, want = old["dispositions"], e["dispositions"]
            if want[:len(have)] != have:
                raise OperationError(
                    f"item {e['id']!r}: the file's disposition history does not extend "
                    f"the {len(have)} event(s) already recorded",
                    satisfied_when="disposition lines are only ever appended; the recorded "
                                   "history is a prefix of the file's")
            if len(want) > len(have):
                old["dispositions"] = want
                touched.append(e["id"])

    return doc, touched, {"lines": counts}


OPERATIONS = {
    "ingest_reconstruct": ingest_reconstruct,
}
