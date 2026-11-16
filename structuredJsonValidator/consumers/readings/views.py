"""Projections over ``blind_readings``, and the verdict body for the ledger's
``reconstruct`` step.

⛔ THE GATE IS ON DISPOSITIONING, NOT ON THE READER'S OPINION (the consumer's
R-NOCONV). Whether a DIFF-1 item is right is a judgement this code never makes; what
it reads is whether somebody DECIDED it. An open item blocks; a decided one does not.

How each current disposition lands on the verdict for its own (path, blob):

    open      blocks   FAIL, `failing` names the path
    applied   blocks   the fix landed in a NEW blob, so THIS blob still carries the
                       defect. ⚠ Deliberately not a pass: nobody needs a superseded
                       blob to pass, and a PASS here would be a true statement ("it was
                       dealt with") read against the wrong object (these bytes). The
                       new blob owes its own run.
    carried   passes   rides the PASS as `outstanding`, severity ordinary (V18)
    rejected  passes   named in `reason` only

⚠ NEVER-RUN IS ITS OWN STATE. A (path, blob) no run examined returns
``state: "never_run"`` and no record, never an empty PASS: absence is not success.
"""

from __future__ import annotations

from typing import Optional

STEP = "reconstruct"
BLOCKING = ("open", "applied")


def _current(item: dict) -> Optional[str]:
    evs = item.get("dispositions") or []
    return evs[-1].get("disposition") if evs else None


def verdict_for(document: dict, path: str, git_blob_id: str,
                current_briefs: Optional[dict] = None) -> dict:
    """The record body for one (path, blob).

    ``current_briefs`` maps a brief path to its blob at the ref being judged. When it
    is given, ONLY runs made under the current brief decide, and only they appear in
    `evidence`. ⛔ Measured 2026-11-16 by the consumer, before this parameter existed:
    GapDecoder dc77bfe0 had run w8r1 (brief d8d36a3b) and run w10 (brief d3642ae3),
    and the served record cited BOTH briefs. The ledger stales a delegated record when
    ANY evidence blob it names is not current, so the old brief would have staled a
    record the current run had earned. The coverage view already excluded old-brief
    runs; the verdict did not, so the two answered differently about the same bytes.
    ⚠ Runs exist but none is current -> ``brief_moved`` with no record: a run under the
    current brief is owed, which is not a pass and not ``never_run`` either.
    ``current_briefs=None`` keeps every run (internal callers only; the MCP tool
    always supplies it)."""
    runs = [r for r in document.get("runs", [])
            if any(x.get("path") == path and x.get("git_blob_id") == git_blob_id
                   for x in r.get("examined", []))]
    if not runs:
        return {"state": "never_run", "path": path, "git_blob_id": git_blob_id,
                "record": None,
                "means": "no indexed run examined these bytes; a run is owed. This is "
                         "not a pass."}
    if current_briefs is not None:
        old = sorted(r["run_id"] for r in runs
                     if current_briefs.get(r["brief"]["path"]) != r["brief"]["git_blob_id"])
        runs = [r for r in runs if r["run_id"] not in old]
        if not runs:
            return {"state": "brief_moved", "path": path, "git_blob_id": git_blob_id,
                    "record": None, "superseded_runs": old,
                    "means": "every run on these bytes used a brief that is not the brief at "
                             "the judged ref; the ledger would stale such a record on "
                             "arrival. A run under the current brief is owed."}
    run_ids = sorted(r["run_id"] for r in runs)
    items = sorted((e for e in document.get("entries", [])
                    if e.get("kind") == "diff1" and e.get("path") == path
                    and e.get("git_blob_id") == git_blob_id and e.get("run_id") in run_ids),
                   key=lambda e: (e.get("run_id"), e.get("line") or 0, e.get("id")))
    by_state: dict = {d: [] for d in ("open", "applied", "carried", "rejected")}
    for e in items:
        by_state.setdefault(_current(e), []).append(e)

    evidence: list = []
    for r in sorted(runs, key=lambda r: r["run_id"]):
        for ref in (r["brief"], r["reader_prompt"]):
            if ref not in evidence:
                evidence.append(dict(ref))

    tally = ", ".join(f"{len(by_state[d])} {d}" for d in ("open", "applied", "carried", "rejected"))
    blocking = by_state["open"] + by_state["applied"]
    record = {
        "step": STEP,
        "tier": "A",
        "subjects": [{"path": path, "git_blob_id": git_blob_id}],
        "evidence": evidence,
        "decided": {"how": "delegated", "who": STEP, "passes": 1, "agreed": 1},
    }
    if blocking:
        record["verdict"] = "FAIL"
        record["failing"] = [path]
        record["reason"] = (f"{len(blocking)} undispositioned or superseded DIFF-1 item(s) "
                            f"on this blob ({tally}; runs {run_ids}): "
                            + "; ".join(f"{e['id']} {_current(e)}" for e in blocking))
    else:
        record["verdict"] = "PASS"
        record["reason"] = (f"every DIFF-1 item on this blob is decided ({tally}; runs "
                            f"{run_ids})"
                            + ("; rejected: " + "; ".join(
                                f"{e['id']}: {e['dispositions'][-1].get('reason')}"
                                for e in by_state["rejected"]) if by_state["rejected"] else ""))
        if by_state["carried"]:
            record["outstanding"] = [
                {"severity": "ordinary",
                 "note": f"{e['id']} (line {e.get('line')}, {e.get('diff_kind')}): "
                         f"{e['dispositions'][-1].get('reason')}"}
                for e in by_state["carried"]]
    return {"state": "recorded", "path": path, "git_blob_id": git_blob_id,
            "runs": run_ids, "items": len(items),
            "dispositions": {d: len(v) for d, v in by_state.items()},
            "record": record}


def status(document: dict, **_params) -> str:
    runs = document.get("runs", [])
    entries = document.get("entries", [])
    lines = [f"blind readings: {len(runs)} run(s), "
             f"{sum(e.get('kind') == 'reading' for e in entries)} reading(s), "
             f"{sum(e.get('kind') == 'diff1' for e in entries)} DIFF-1 item(s)"]
    for r in sorted(runs, key=lambda r: r["run_id"]):
        lines.append(f"- {r['run_id']} @ {r['commit'][:12]}")
        for x in r.get("examined", []):
            v = verdict_for(document, x["path"], x["git_blob_id"])
            d = v["dispositions"]
            lines.append(f"    {x['path']} {x['git_blob_id'][:8]}: {v['record']['verdict']} "
                         f"(open {d['open']}, applied {d['applied']}, carried {d['carried']}, "
                         f"rejected {d['rejected']})")
    return "\n".join(lines)


def open_items(document: dict, **_params) -> str:
    rows = [e for e in document.get("entries", [])
            if e.get("kind") == "diff1" and _current(e) in BLOCKING]
    rows.sort(key=lambda e: (e["path"], e["git_blob_id"], e.get("line") or 0, e["id"]))
    lines = [f"blocking DIFF-1 items: {len(rows)}"]
    for e in rows:
        lines.append(f"- {e['id']} [{_current(e)}] {e['path']}:{e.get('line')} "
                     f"{e['git_blob_id'][:8]} {e.get('diff_kind')}: {e['decl']}")
    return "\n".join(lines)


VIEWS = {
    "status": status,
    "open_items": open_items,
}
