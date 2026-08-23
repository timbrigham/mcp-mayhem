"""The signal families, all computed from the record fields — no extra instrumentation.

Implemented in the order §6 gives, because the first four pay for themselves and
the rest need history to mean anything.

⚠⚠ AN EMPTY STREAM REPORTS "NOTHING RECORDED", NEVER A CLEAN BILL OF HEALTH. Day
one is exactly when the stream is empty, and a signal layer that says "0 problems"
over no data is the failure this whole server exists to end. Every family carries
its own `basis_count` so a zero is readable as "nothing to judge" rather than
"judged fine".

⚠ `signals()` prints its counts on every call, clean or not. A signal nobody reads
manufactures the appearance of coverage — that is `RLY25-1`.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional


def compute(*, records: list, config, family: Optional[str] = None,
            step: Optional[str] = None) -> dict:
    rows = [r for r in records if r.get("step") != "genesis"]
    if step:
        rows = [r for r in rows if r.get("step") == step]

    thresholds = config.signals if config else {}
    families = {
        "coverage_gap": _coverage_gap(rows, config),
        "never_fired": _never_fired(rows, thresholds.get("never_fired_runs", 50)),
        "repeat_subject": _repeat_subject(rows, thresholds.get("repeat_subject_rounds", 3)),
        "basis_drift": _basis_drift(rows),
        "edge_condition": _edge_condition(rows),
        "overturn": _overturn(rows),
    }
    if family:
        if family not in families:
            return {"error": f"unknown family {family!r}; known: {sorted(families)}"}
        families = {family: families[family]}

    empty = not rows
    return {
        "records_considered": len(rows),
        "note": ("NOTHING RECORDED — every count below is zero because there is no "
                 "data, which is not the same as no problems") if empty else None,
        "families": families,
    }


def _coverage_gap(rows, config) -> dict:
    """Which registered types have never recorded anything at all.

    The question an enumeration gate can never answer about itself.
    """
    seen = {r.get("step") for r in rows}
    registered = set(config.types) if config else set()
    missing = sorted(registered - seen)
    return {"basis_count": len(registered), "count": len(missing),
            "never_recorded": missing,
            "why": "a registered type with no record has never run, or ran and did not report"}


def _never_fired(rows, threshold: int) -> dict:
    """A step with no FAIL across many runs — either the corpus is clean or the
    step is decorative, and the two are indistinguishable without asking."""
    runs = defaultdict(set)
    fails = defaultdict(int)
    for r in rows:
        runs[r.get("step")].add((r.get("run") or {}).get("id"))
        if r.get("verdict") == "FAIL":
            fails[r.get("step")] += 1
    out = [{"step": s, "runs": len(ids), "fails": fails.get(s, 0)}
           for s, ids in runs.items()
           if fails.get(s, 0) == 0 and len(ids) >= threshold]
    return {"basis_count": len(runs), "count": len(out), "threshold_runs": threshold,
            "steps": sorted(out, key=lambda x: -x["runs"])}


def _repeat_subject(rows, threshold: int) -> dict:
    """The same subject hash failing across rounds — non-convergence MEASURED.

    Each round of fixing is a new basis, so counting distinct bases per (step,
    subject-hash) counts genuine re-examinations rather than re-runs.
    """
    seen = defaultdict(set)
    for r in rows:
        if r.get("verdict") != "FAIL":
            continue
        for s in r.get("subjects") or []:
            seen[(r.get("step"), s.get("blob"), s.get("path"))].add(
                (r.get("basis") or {}).get("value"))
    out = [{"step": k[0], "path": k[2], "rounds": len(v)}
           for k, v in seen.items() if len(v) >= threshold]
    return {"basis_count": len(seen), "count": len(out), "threshold_rounds": threshold,
            "subjects": sorted(out, key=lambda x: -x["rounds"])[:50]}


def _basis_drift(rows) -> dict:
    """One step, differing basis kind or resolution — the FRZ-4 shape made visible."""
    kinds = defaultdict(set)
    fallbacks = defaultdict(int)
    for r in rows:
        b = r.get("basis") or {}
        kinds[r.get("step")].add((b.get("kind"), b.get("resolved_from")))
        if b.get("resolved_from") == "FALLBACK":
            fallbacks[r.get("step")] += 1
    drifting = [{"step": s, "variants": sorted(f"{k}:{rf}" for k, rf in v),
                 "fallbacks": fallbacks.get(s, 0)}
                for s, v in kinds.items() if len(v) > 1 or fallbacks.get(s)]
    return {"basis_count": len(kinds), "count": len(drifting), "steps": drifting}


def _edge_condition(rows) -> dict:
    """Appends that crossed the soft lock threshold. Sub-millisecond normally, so
    any hit means a stuck writer or a stalled fsync — never contention."""
    hits = [{"step": r.get("step"), "seconds": (r.get("cost") or {}).get("lock_wait_seconds"),
             "id": r.get("id")}
            for r in rows if (r.get("cost") or {}).get("lock_wait_seconds")]
    return {"basis_count": len(rows), "count": len(hits), "appends": hits[:50],
            "why": "review: an append waited past the soft threshold"}


def _overturn(rows) -> dict:
    """Keys carrying revisions — a regrade is evidence about the STEP, an accept is
    corpus debt, and they must be counted apart."""
    by_key = defaultdict(list)
    for r in rows:
        by_key[(r.get("step"), (r.get("basis") or {}).get("value"))].append(r)
    out = []
    for (s, b), recs in by_key.items():
        if len(recs) < 2:
            continue
        tip = max(recs, key=lambda r: r.get("revision", 0))
        out.append({"step": s, "basis": (b or "")[:12], "revisions": len(recs),
                    "tip_how": (tip.get("decided") or {}).get("how")})
    return {"basis_count": len(by_key), "count": len(out),
            "keys": sorted(out, key=lambda x: -x["revisions"])[:50]}
