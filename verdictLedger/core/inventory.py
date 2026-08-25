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

    ⚠⚠ KEYED ON CONTENT. `by_content` maps (step, path, git_blob_id) to the record
    that examined exactly those bytes; `by_path` remembers that a step touched a path
    at all, which is what separates STALE ("examined, content moved") from MISSING
    ("never examined"). An earlier version kept one tip per (step, path) and so a
    newer verdict ERASED an older commit's coverage -- invisible under tip-only
    gating, fatal under range gating, where every commit but the last then reads
    STALE however diligently it was checked at the time.

    ⚠⚠ LEGACY IS SEPARATED ON PURPOSE. Records written before 2026-08-23 carry a
    64-hex sha256 under `sha256` instead of a git blob id. Left in the main index they
    compare unequal to every blob id and render as STALE -- and "the content moved"
    and "recorded under a superseded identity scheme" are different facts with
    different remedies. Re-running a checker fixes the first and does nothing for the
    second.
    """
    by_content: dict = {}      # (step, path, blob) -> the record that examined it
    by_path: dict = {}         # (step, path)        -> some record, for STALE
    legacy: dict = {}
    evidence: dict = {}        # step -> {path, ...} recorded as V16 evidence
    for r in records:
        step = r.get("step")
        rev = r.get("revision", 0)
        # ⭐⭐ V16 EVIDENCE IS INDEXED EXACTLY LIKE A SUBJECT, AND THAT IS THE HALF OF
        # V16 THAT IS NOT FORGEABLE. Naming the checker module is forgeable by anyone
        # willing to copy a blob id; what is not is that the record now names a blob,
        # so editing the checker moves it, the key reads STALE, and the step re-runs.
        # A forged mechanical PASS therefore expires the next time the code it lied
        # about changes, instead of standing for ever.
        #
        # ⚠ Tracked SEPARATELY from subjects and never merged into them: `coverage()`
        # reads `subjects` directly, and folding evidence in would have every checker
        # certifying its own source as reviewed corpus. It is a dependency of the
        # verdict, not a thing the verdict is about — the same relationship `switches`
        # have, and it is treated the same way below.
        for e in r.get("evidence") or []:
            path, blob = e.get("path"), e.get("git_blob_id")
            if not (path and blob):
                continue
            evidence.setdefault(step, set()).add(path)
            key = (step, path, blob)
            prior = by_content.get(key)
            if prior is None or rev >= prior.get("revision", 0):
                by_content[key] = r
            seen = by_path.get((step, path))
            if seen is None or rev >= seen.get("revision", 0):
                by_path[(step, path)] = r
        for s in r.get("subjects") or []:
            path, blob = s.get("path"), s.get("git_blob_id")
            if not blob:
                prior = legacy.get((step, path))
                if prior is None or rev >= prior[0].get("revision", 0):
                    legacy[(step, path)] = (r, None)
                continue
            key = (step, path, blob)
            prior = by_content.get(key)
            # ⚠ Revision compares WITHIN one content key. Across different content
            # there is nothing to supersede: two verdicts about different bytes are
            # both true.
            if prior is None or rev >= prior.get("revision", 0):
                by_content[key] = r
            seen = by_path.get((step, path))
            if seen is None or rev >= seen.get("revision", 0):
                by_path[(step, path)] = r
    return by_content, by_path, legacy, evidence


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
    by_content, by_path, legacy_tips, evidence_paths = _subject_index(records)

    rows = []
    how_counts: dict = {}
    for step, spec in sorted(reqs.items()):
        family = spec["family"]
        if not spec["required"]:
            rows.append({"step": step, "family": family, "status": "NOT_APPLICABLE",
                         "why": spec.get("reason") or "narrowed by action",
                         "record_id": None, "subjects_covered": 0,
                         "subjects_stale": 0, "subjects_unexamined": 0, "scope": 0, "subjects_unscoped": [],
                         "needs_rerun": False, "rerun_reason": None})
            continue
        when = spec.get("when")
        if when and not any(fnmatch.fnmatch(p, when) for p in files):
            # ⚠ "It did not apply" and "it passed" must never render the same, and
            # the status carries the glob that excluded it.
            rows.append({"step": step, "family": family, "status": "NOT_APPLICABLE",
                         "why": f"no path matched {when!r}", "record_id": None,
                         "subjects_covered": 0, "subjects_stale": 0,
                         "subjects_unexamined": 0, "scope": 0, "subjects_unscoped": [],
                         "needs_rerun": False, "rerun_reason": None})
            continue

        # ⭐⭐ HOW MUCH OF THE SCOPE WAS NEVER EXAMINED AT ALL.
        #
        # Measured 2026-08-23: a step that examined ONE file out of 201 reported
        # SATISFIED, because a path with no record for that step contributed to
        # neither `covered` nor `stale` and so was simply not counted. Absence
        # rendering as success -- the defect class this server exists to end,
        # arriving through the one door nobody had checked.
        #
        # It matters right now because ZeroParadox's `common.ledger_subjects` DROPS
        # any path whose worktree differs from the index. That fence is honest about
        # what it read, but the narrowing was invisible HERE, so a dirty tree quietly
        # shrank what a green key meant.
        #
        # ⚠ REPORTED, NOT YET BLOCKING. Making it block is a policy change that
        # would refuse every push until every step covers every in-scope path, and
        # that is Tim's call, not a side effect of a bug fix. But a downgraded gate
        # has to get LOUDER, so the number is on every row and in the rendered line.
        # ⚠ `scope` if declared, else `when`, else EVERY path. The default is the
        # strict reading and stays that way: a type that has not said what it examines
        # owes the whole tree. Measured 2026-08-23 -- without a declared scope, `guards`
        # reported 475 of 479 paths unexamined and would have been re-run on every
        # commit forever, which is the 18.26s this design exists to skip.
        # ⚠ `scope` is a LIST of globs; a path is in scope if ANY matches. `when`
        # remains a single glob because it answers a different question -- whether the
        # type applies at all -- and no measured case needed more than one.
        # ⚠⚠ fnmatch's `*` CROSSES `/`, so `*` alone is "every path" and a `**/`
        # prefix is WRONG rather than redundant -- `**/*` requires at least one
        # directory and misses every top-level file. Measured 2026-08-23.
        globs = spec.get("scope") or ([when] if when else [])
        drop = spec.get("scope_exclude") or []
        scope = [p for p in files
                 if (not globs or any(fnmatch.fnmatch(p, g) for g in globs))
                 and not any(fnmatch.fnmatch(p, g) for g in drop)]
        unexamined = sum(1 for p in scope
                         if (step, p, files[p]) not in by_content
                         and (step, p) not in by_path)

        # ⭐ THE SYMMETRIC NUMBER. `subjects_unexamined` finds a scope wider than the
        # property; this finds one NARROWER than what the checker actually examined --
        # the case the other is structurally blind to, because an excluded path
        # produces no residue at all and everything reads clean.
        #
        # Derived from the checker's own subject set rather than from the declaration,
        # which is the property that makes the pair work at all.
        #
        # Switches are subtracted because they are SUPPOSED to sit outside the scanned
        # scope -- they are the exemption surface, not the corpus. No further
        # subtraction is needed: `subjects` is everything the verdict depends on,
        # `scope` is what it examines, `switches` is what it depends on beyond that, so
        # `subjects` is contained in their union by construction. Anything left over is
        # an undeclared switch, a scope too narrow, or over-recording -- all three of
        # which someone should look at.
        in_scope = set(scope)
        switch_set = set(spec.get("switches") or [])
        # ⚠ V16 evidence is subtracted for the same reason switches are: the checker
        # module is SUPPOSED to sit outside the scanned scope. Reporting a step's own
        # source as "examined but unscoped" would make the signal fire on every
        # mechanical record ever written, and a signal that fires on everything is one
        # people learn to scroll past -- which is what `subjects_unscoped` exists to
        # avoid being.
        ev_set = evidence_paths.get(step, set())
        unscoped = sorted(p for p in files
                          if (step, p) in by_path
                          and p not in in_scope and p not in switch_set
                          and p not in ev_set)

        # ⚠⚠ THE VERDICT MUST COME FROM A RECORD THAT EXAMINED *THESE* BYTES.
        # Keeping one `record` for both covered and stale hits let a stale record
        # supply the verdict for a step that also had a covering one -- whichever
        # path happened to be iterated first won.
        #
        # ⭐⭐ LED-2, measured by ZeroParadox 2026-08-24: THE DENOMINATOR IS THE
        # STEP'S SCOPE, NEVER EVERY FILE. This loop used to walk all of `files`, so a
        # path the step had examined at some earlier basis but which its declared
        # `scope`/`scope_exclude` now puts OUTSIDE it still counted as `stale` --
        # with the record's blob IDs 4/4 IDENTICAL to the index, the row returned
        # STALE, "recorded against different bytes", remedy "re-run".
        #
        # Every part of that was wrong, and the remedy was the worst part: a checker
        # that correctly honours its own scope will never examine that path again, so
        # RE-RUNNING IS THE ONE ACTION THAT CAN NEVER CLEAR IT. It costs rounds and
        # teaches the operator that the gate is broken rather than that the scope is.
        # STALE and UNSCOPED are different facts with different remedies -- the same
        # collapse-of-distinct-statuses this module's own docstring forbids.
        #
        # ⚠ THIS IS A WEAKENING AND IT IS NAMED AS ONE. Out-of-scope residue used to
        # block an action; it no longer does. That block was unclearable, so it was
        # never a gate, only a wedge -- but the residue does not go quiet: it is on
        # every row as `subjects_unscoped`, in the inventory as `unscoped`, and it now
        # carries the MISSING row's `why` below. The scope is the thing to look at,
        # and `LED-1` is the standing example of a scope that is wrong.
        #
        # ⚠ SWITCHES AND V16 EVIDENCE ARE IN THE DENOMINATOR, not the scope. Both are
        # SUPPOSED to sit outside what a checker scans, and both must still be able to
        # stale the key -- that is the entire mechanism of V15 and of V16's expiry.
        # Dropping them here would silently disarm two rules from a third one's fix.
        judged = [p for p in files
                  if p in in_scope or p in switch_set or p in ev_set]
        covered, stale = 0, 0
        covered_rec, stale_rec = None, None
        for path in judged:
            rec = by_content.get((step, path, files[path]))
            if rec is not None:
                covered += 1
                covered_rec = covered_rec or rec
            elif (step, path) in by_path:
                # examined, but never at THIS content
                stale += 1
                stale_rec = stale_rec or by_path[(step, path)]

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
            if unscoped:
                # ⭐ LED-2's other half. "Never ran" and "ran, but everything it read
                # is outside its declared scope" are different facts, and only the
                # second one is fixed by editing the registry. Naming it here is what
                # stops the operator re-running a checker that cannot help.
                why = (f"nothing IN SCOPE has been examined -- but this step DID record "
                       f"{len(unscoped)} path(s) that its `scope`/`scope_exclude` puts "
                       f"outside it ({', '.join(unscoped[:3])}"
                       f"{', …' if len(unscoped) > 3 else ''}). If those are the paths "
                       f"it is meant to cover, the SCOPE is what needs fixing; "
                       f"re-running cannot move this row.")
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
                     "subjects_unexamined": unexamined, "scope": len(scope),
                     "subjects_unscoped": unscoped,
                     "why": why,
                     # ⭐ WHAT A CALLER MUST ACTUALLY RUN, answered here so no consumer
                     # builds a second staleness predicate (§12-0-alpha). Stated as a
                     # NEGATIVE on purpose: re-run unless the step is fully covered at
                     # this tree or does not apply. A positive list would have to
                     # enumerate every not-covered state, and the one it missed --
                     # SATISFIED-but-narrow -- is exactly the hole measured on
                     # 2026-08-23, where adding a file left a row green while the new
                     # path went unexamined.
                     "needs_rerun": not (status == "NOT_APPLICABLE"
                                         or (status == "SATISFIED" and unexamined == 0)),
                     "rerun_reason": (
                         None if status == "NOT_APPLICABLE"
                         or (status == "SATISFIED" and unexamined == 0)
                         else (f"{unexamined} in-scope path(s) never examined"
                               if status == "SATISFIED" else status.lower()))})

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
        "unexamined": sum(r["subjects_unexamined"] for r in rows
                          if r.get("gating") and r.get("subjects_unexamined")),
        # ⚠ ALL rows, not just gating ones: an undeclared switch on a type nothing
        # currently admits is still an undeclared switch, and promoting that type later
        # would inherit the hole silently.
        "unscoped": sorted({p for r in rows for p in (r.get("subjects_unscoped") or [])}),
        # ⚠ ALL registered steps, not just gating ones. The caller deciding what to RUN
        # is a different question from what GATES -- a hook has emitters for types that
        # may not be admitted, and must not be told to skip them just because nothing
        # currently gates on them.
        "needs_rerun": sorted(r["step"] for r in rows if r["needs_rerun"]),
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
