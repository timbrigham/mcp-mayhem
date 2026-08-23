"""`inventory(ref, action)` — the complete set of keys for an action, and what is missing.

⚠⚠ THE REQUIREMENT SET IS DECLARED IN ADVANCE. An inventory assembled from "the
records that happen to exist" is worthless, because *"3 of 3 passed"* and *"5 never
ran"* render identically — the enumerator-found-nothing defect, five measured
instances, arriving through a new door. So the manifest is the source and the
records are checked against it, never the other way round.

⚠ IDENTITY IS NOT SATISFACTION. A record is IDENTIFIED by `(step, basis, verdict,
reason, subjects, revision)`, but it SATISFIES a key while the content it examined
is unchanged — matched on `subjects[].git_blob_id`, never on basis. Matching on basis
would make every record die on every commit: 40 files, 14 checks recorded against
tree X, one unrelated file changes, and the whole pipeline re-runs including the
paid review rounds. "Re-run everything, always" wears the costume of rigour.

⚠ Five statuses, and none may ever collapse into another:
  SATISFIED · STALE (examined, content moved — re-run) · MISSING (never examined —
  run at all) · NOT_APPLICABLE (a `when` glob did not match) · FAIL/UNDECIDED.
"""

from __future__ import annotations

import fnmatch
from typing import Optional


def _subject_index(records) -> tuple:
    """(tips, legacy): path -> the tip record that most recently examined it, per step.

    ⚠⚠ LEGACY IS SEPARATED ON PURPOSE. Records written before 2026-08-23 carry a
    64-hex sha256 under `sha256` instead of a git blob id. Left in the main index they
    compare unequal to every blob id and render as STALE -- and "the content moved"
    and "recorded under a superseded identity scheme" are different facts with
    different remedies. Re-running a checker fixes the first and does nothing for the
    second.
    """
    out: dict = {}
    legacy: dict = {}
    for r in records:
        step = r.get("step")
        for s in r.get("subjects") or []:
            key = (step, s.get("path"))
            target = out if s.get("git_blob_id") else legacy
            prior = target.get(key)
            if prior is None or r.get("revision", 0) >= prior[0].get("revision", 0):
                target[key] = (r, s.get("git_blob_id"))
    return out, legacy


def build(*, config, records, action: str, files: dict,
          ref: Optional[str] = None, admission: Optional[list] = None) -> dict:
    """``files`` maps path -> GIT BLOB ID for the content being promoted.

    ⚠⚠ THE BLOB ID, NOT A CONTENT DIGEST, and the distinction cost an afternoon.
    These values come straight from `git ls-tree` / `git ls-files -s`, and a
    subject matches only if it carries the same thing. The field used to be called
    `sha256`, so a client computed a sha256 of the file bytes — a different hash
    function over a different byte string (git prefixes "blob <len>\0") — and no
    key could ever be satisfied. Every record rotted to STALE forever.

    ⚠⚠ TWO LISTS, NOT TWO COPIES. The REGISTRY (config.types) says what may be
    RECORDED; the ADMISSION SET says what must be green to let an action through.
    They answer different questions, so `complete` is computed against `admission`
    — not against every registered type. Twenty experimental gates recording while
    three admit a push is a coherent, intended state.

    An earlier model conflated them, and the tell that it was wrong is that its
    correct implementation blocks every push until every registered type has an
    emitter. A model whose correct implementation bricks the system is describing
    the wrong system.

    ⚠ `admission=None` means "no admission set was named", which is NOT the same
    as an empty one and must never read as satisfied — see `admission_state`.
    """
    reqs = config.requirements(action)
    tips, legacy_tips = _subject_index(records)

    rows = []
    how_counts: dict = {}
    for step, spec in sorted(reqs.items()):
        family = spec["family"]
        if not spec["required"]:
            rows.append({"step": step, "family": family, "status": "NOT_APPLICABLE",
                         "why": spec.get("reason") or "narrowed by action",
                         "record_id": None, "subjects_covered": 0})
            continue
        when = spec.get("when")
        if when and not any(fnmatch.fnmatch(p, when) for p in files):
            # ⚠ "It did not apply" and "it passed" must never render the same, and
            # the status carries the glob that excluded it.
            rows.append({"step": step, "family": family, "status": "NOT_APPLICABLE",
                         "why": f"no path matched {when!r}", "record_id": None,
                         "subjects_covered": 0})
            continue

        # ⚠⚠ THE VERDICT MUST COME FROM A RECORD THAT EXAMINED *THESE* BYTES.
        # Keeping one `record` for both covered and stale hits let a stale record
        # supply the verdict for a step that also had a covering one -- whichever
        # path happened to be iterated first won.
        covered, stale = 0, 0
        covered_rec, stale_rec = None, None
        for path, sha in files.items():
            hit = tips.get((step, path))
            if hit is None:
                continue
            rec, recorded_sha = hit
            if recorded_sha == sha:
                covered += 1
                covered_rec = covered_rec or rec
            else:
                stale += 1
                stale_rec = stale_rec or rec
        record = covered_rec or stale_rec
        legacy_hit = next((legacy_tips[(step, p)] for p in files
                           if (step, p) in legacy_tips), None)

        why = None
        if covered == 0 and stale == 0 and legacy_hit is not None:
            # ⚠ NOT stale, and NOT missing. The step DID examine this path; the record
            # is simply unusable, and the remedy is to re-record rather than to re-run
            # or to run at all.
            status = "LEGACY_IDENTITY"
            record = legacy_hit[0]
            why = ("recorded under the superseded `sha256` subject scheme and cannot be "
                   "compared to a git blob id; re-record it (or let it age out)")
        elif covered == 0 and stale == 0:
            status = "MISSING"
        elif covered and covered_rec.get("verdict") == "FAIL":
            status = "FAIL"
        elif covered and covered_rec.get("verdict") == "UNDECIDED":
            status = "UNDECIDED"
        elif stale:
            # ⚠⚠ A FAIL AGAINST OTHER BYTES DEMOTES TO STALE LIKE ANY OTHER VERDICT.
            # It used to stay FAIL forever: the FAIL branch ran before this one, so a
            # PASS recorded against moved content was correctly demoted while a FAIL
            # was not. One probe FAIL therefore condemned every commit in the audit,
            # and no amount of re-running could clear it except a PASS on the exact
            # sha. That is an audit that cries wolf on every run -- which trains a
            # reader to ignore it, the precise failure this system exists to prevent.
            #
            # This weakens NO gate: `complete` already requires stale == 0 as well as
            # failed == 0, so the action is refused either way. It changes only what
            # the reader is TOLD, from "it failed" to "it was never run on this".
            status = "STALE"
            if stale_rec is not None and stale_rec.get("verdict") in ("FAIL", "UNDECIDED"):
                why = (f"last verdict was {stale_rec['verdict']} but against different "
                       f"bytes ({stale_rec['id']}) -- it does not judge this content")
        else:
            status = "SATISFIED"

        if status == "SATISFIED" and record is not None:
            how = (record.get("decided") or {}).get("how", "?")
            how_counts[how] = how_counts.get(how, 0) + 1

        rows.append({"step": step, "family": family, "status": status,
                     "record_id": (record or {}).get("id"),
                     "subjects_covered": covered, "subjects_stale": stale,
                     "why": why})

    # Only ADMITTED types decide `complete`. Everything else is reported so the
    # caller can see it, and so a promotion gap is visible rather than silent.
    admitted = None if admission is None else set(admission)
    for r in rows:
        r["gating"] = (admitted is not None and r["step"] in admitted
                       and r["status"] != "NOT_APPLICABLE")

    gating = [r for r in rows if r["gating"]]

    def n(status):
        return sum(1 for r in gating if r["status"] == status)

    required = len(gating)
    satisfied = n("SATISFIED")
    registered_not_admitting = sorted(
        r["step"] for r in rows
        if not r["gating"] and r["status"] != "NOT_APPLICABLE")

    if admitted is None:
        # ⚠ NOT the same as an empty admission set. "Nobody said what gates this"
        # must never render as "everything is fine" — that is the fail-open shape
        # this whole system exists to end.
        state = "UNSET"
        complete = False
    elif not admitted:
        # Legitimate on day one, when no checker emits yet — but it must SCREAM,
        # or "the gate is on" gets believed while it gates nothing.
        state = "EMPTY"
        complete = True
    else:
        state = "SET"
        complete = (n("MISSING") == 0 and n("STALE") == 0
                    and n("UNDECIDED") == 0 and n("FAIL") == 0
                    and n("LEGACY_IDENTITY") == 0)

    return {
        "ref": ref, "action": action,
        "admission_state": state,
        "admitted": sorted(admitted) if admitted is not None else None,
        "required": required, "satisfied": satisfied,
        "missing": n("MISSING"), "stale": n("STALE"),
        "legacy_identity": n("LEGACY_IDENTITY"),
        "undecided": n("UNDECIDED"), "failed": n("FAIL"),
        "not_applicable": sum(1 for r in rows if r["status"] == "NOT_APPLICABLE"),
        # gitRobot's rule is that these are all zero. The ledger COMPUTES; the
        # consumer REQUIRES. Re-deriving completeness on the other side would be
        # the mirror defect in the highest-stakes possible location.
        "complete": complete,
        "registered_not_admitting": registered_not_admitting,
        "how_breakdown": how_counts,
        "rows": rows,
    }


def coverage(*, records, paths: list) -> dict:
    """Tracked paths MINUS the union of every `subjects` entry ever recorded.

    ⚠ On an empty stream this reports EVERYTHING uncovered, never a clean bill of
    health. Day one is exactly when the stream is empty, and that is the fail-open
    shape this project has been bitten by five times.
    """
    examined = {s.get("path") for r in records for s in (r.get("subjects") or [])}
    uncovered = sorted(p for p in paths if p not in examined)
    return {
        "tracked": len(paths), "examined": len(set(paths) & examined),
        "uncovered": len(uncovered), "paths": uncovered[:200],
        "note": ("nothing recorded — every tracked path is uncovered"
                 if not examined else None),
    }
