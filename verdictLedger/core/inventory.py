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
    evidence: dict = {}        # step -> {path, ...} recorded as V16/V17 evidence
    ev_content: dict = {}      # (step, path, blob) -> the record that ran under it
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
            prior = ev_content.get(key)
            if prior is None or rev >= prior.get("revision", 0):
                ev_content[key] = r
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
    return by_content, by_path, legacy, evidence, ev_content


def _loosen(glob: str) -> str:
    """The same pattern with its `**/` segments removed.

    ⚠ `**/` is the ONE loosening applied, deliberately. It is not a general "try
    easier patterns until something matches" search — that would find a match for
    almost any typo and report confident nonsense. `**/` is the specific construct
    that LOOKS like it broadens a glob and in `fnmatch` narrows it, because it
    requires at least one `/`. Shell and gitignore intuitions produce it; nothing
    else here produces a silently-dead pattern.
    """
    out = glob
    while out.startswith("**/"):
        out = out[3:]
    return out.replace("/**/", "/")


def _dead_pattern(glob: str, files, field: str):
    """⭐⭐ A NARROWING THAT CANNOT EVER FIRE, TOLD APART FROM ONE THAT DOES NOT FIRE TODAY.

    Found by ZeroParadox 2026-08-25, one hour after the glob semantics were written
    down. `pdf_coupling` gates on `when: "**/*.pdf"`. Every tracked PDF in ZeroParadox
    is root-level — the layout rule REQUIRES it, formal documents live at the root
    under flat filenames — and `**/*.pdf` cannot match a root-level path. So the gate
    had never fired on a single artifact it exists to protect, and never could have.

    ⚠⚠ AND IT RENDERED AS `NOT_APPLICABLE — "no path matched '**/*.pdf'"`, WHICH IS
    TRUE. That is what makes this the worst shape available: a correct, calm sentence
    covering a gate that is structurally incapable of applying. Nothing distinguished
    *this gate does not apply to this push* from *this gate applies to nothing, ever*.

    ⚠ THE TEST CANNOT BE "MATCHES ZERO PATHS". That fires legitimately every time a
    push carries no PDFs, and a signal that fires constantly is one people learn to
    scroll past — the exact failure this module warns about elsewhere. The question
    that separates the two is: does the SAME pattern, loosened, match things that are
    sitting right here? Zero now and zero loosened is an honest narrowing. Zero now
    and FORTY loosened is a typo.

    The rule it was protecting: a changed PDF must arrive with the `scripts/` builder
    that produced it. The cost of it not firing is a PDF drifting from its builder and
    then being minted into a permanent DOI — four releases already carry latent flaws
    that cannot be withdrawn.
    """
    loosened = _loosen(glob)
    if loosened == glob:
        return None
    now = {p for p in files if fnmatch.fnmatch(p, glob)}
    hits = {p for p in files if fnmatch.fnmatch(p, loosened)}
    # ⚠⚠ STRICTLY MORE, NOT "MATCHES NOTHING" — AND THAT WIDENING CAME FROM A NEAR
    # MISS. The first version only fired when the pattern matched ZERO paths, which
    # caught `pdf_coupling`'s `**/*.pdf` against 40 root PDFs. On 2026-08-25
    # ZeroParadox proposed `ZeroParadox/**/*.lean` as a scope for four gating steps.
    # It matches 213 of the 218 tracked .lean files: `**/` requires at least one `/`,
    # so it silently drops the five sitting directly under `ZeroParadox/` —
    # AxiomProfile, BottomCannotBe, ClaimsMirror, DiagonalFixedPoint, Miniature.
    #
    # Those four rows would then have read 213/213 COMPLETE while five corpus files
    # went unexamined for ever — a green row over a scope that quietly dropped
    # content, which is worse than the dead pattern it was modelled on, because it
    # LOOKS like coverage. The zero-match rule could never see it.
    #
    # `**/` can only ever narrow (`*` already crosses `/`), so if loosening finds
    # more, the `**/` is dropping something. Flag it whether it drops all or five.
    if len(hits) <= len(now):
        return None
    dropped = sorted(hits - now)
    return {"field": field, "pattern": glob, "suggestion": loosened,
            "matches_now": len(now), "would_match": len(hits),
            "drops": len(dropped), "example": dropped[0],
            "kind": "dead" if not now else "narrowing"}


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
    (by_content, by_path, legacy_tips, evidence_paths,
     ev_content) = _subject_index(records)

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
        dead = [d for d in
                ([_dead_pattern(when, files, "when")] if when else [])
                + [_dead_pattern(g, files, "scope")
                   for g in (spec.get("scope") or [])]
                if d]
        if when and not any(fnmatch.fnmatch(p, when) for p in files):
            # ⚠ "It did not apply" and "it passed" must never render the same, and
            # the status carries the glob that excluded it.
            #
            # ⭐⭐ AND "it does not apply TODAY" must not render like "it applies to
            # NOTHING, EVER". `no path matched '**/*.pdf'` is a true, calm sentence
            # that covered a gate which had never once fired on the artifacts it
            # exists to protect. When the same pattern LOOSENED matches things
            # sitting right here, say so where the misleading sentence was.
            d = next((x for x in dead if x["field"] == "when"), None)
            why = (f"no path matched {when!r}"
                   if d is None else
                   f"⚠ DEAD PATTERN, not a narrowing: {when!r} matched 0 paths, but "
                   f"{d['suggestion']!r} matches {d['would_match']} of them "
                   f"(e.g. {d['example']!r}). `**/` requires at least one '/', so this "
                   f"glob cannot match a top-level file and this gate has almost "
                   f"certainly never fired. Fix the pattern; do not re-run.")
            rows.append({"step": step, "family": family, "status": "NOT_APPLICABLE",
                         "why": why, "record_id": None,
                         "subjects_covered": 0, "subjects_stale": 0,
                         "subjects_unexamined": 0, "scope": 0, "subjects_unscoped": [],
                         "dead_patterns": dead,
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
        # ⚠⚠ EVIDENCE IS *NOT* IN THE SUBJECT DENOMINATOR. Found by ZeroParadox
        # 2026-08-25 from arithmetic alone: `pdf_coupling` reported
        # `subjects_covered: 42` against `scope: 40`, and its record has exactly 40
        # subjects and 2 evidence entries. Evidence had been folded into the same
        # buckets as subjects, so it counted as coverage.
        #
        # ⚠ `covered > scope` SHOULD BE IMPOSSIBLE, and it rendered as a bigger number
        # — coverage looking BETTER than it is, which is the direction that matters.
        #
        # ⚠ It hid everywhere else because for almost every mechanical step the
        # evidence files are ALREADY subjects: `check_encoding` covers all 450 tracked
        # text files including `batch.py` and `common.py`, so 450 + 2 deduped to 451
        # and the double count was invisible. `pdf_coupling` is the first step whose
        # subjects are DISJOINT from its evidence, so it is the first place the two
        # could be told apart at all.
        judged = [p for p in files if p in in_scope or p in switch_set]
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

        # ⭐⭐ THE PRODUCER MOVING IS A DIFFERENT FACT FROM THE CORPUS MOVING, and
        # ZeroParadox asked the exact right question: does editing `common.py` stale a
        # step via its EVIDENCE (correct — that is what V16/V17 are for) or via a
        # phantom SUBJECT (wrong, and it would misreport which content moved)? Merged
        # into one bucket the two were indistinguishable in the row. They are counted
        # apart now, and the `why` says which one it was.
        ev_stale, ev_moved = 0, []
        for path in sorted(ev_set):
            if path not in files:
                continue
            if (step, path, files[path]) not in ev_content:
                ev_stale += 1
                ev_moved.append(path)

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
        elif ev_stale:
            # ⚠ Every subject still matches; what changed is the code or the brief
            # that PRODUCED the verdict. Re-running is exactly the right remedy here,
            # unlike LED-2's unclearable case — so the row says so plainly.
            status = "STALE"
            why = (f"every subject still matches, but the producer changed: "
                   f"{', '.join(ev_moved[:3])}"
                   f"{', …' if len(ev_moved) > 3 else ''} moved since this verdict was "
                   f"recorded. A verdict cannot outlive the code or brief that reached "
                   f"it — re-run the step.")
        else:
            status = "SATISFIED"

        # ⭐⭐ A SATISFIED ROW MAY BE CARRYING FINDINGS. V18 lets a PASS hold
        # `outstanding` entries — STOP-ORDINARY: reviewed, ordinary findings left, loop
        # cap reached, proceed. The verdict admits, so `complete` is unaffected BY
        # DESIGN (Tim, 2026-08-26). But "nothing was found" and "things were found and
        # judged ordinary" are different facts, and a bare SATISFIED renders them
        # identically — the ambiguity this module exists to remove. The number rides on
        # the row and in the inventory, the way `subjects_unexamined` and
        # `evidence_stale` do.
        outstanding = list((covered_rec or {}).get("outstanding") or [])             if status == "SATISFIED" else []

        if status == "SATISFIED" and record is not None:
            how = (record.get("decided") or {}).get("how", "?")
            how_counts[how] = how_counts.get(how, 0) + 1

        rows.append({"step": step, "family": family, "status": status,
                     "record_id": (record or {}).get("id"),
                     "dead_patterns": dead,
                     # ⚠ `covered` is measured over scope ∪ switches, so reporting
                     # it against `scope` alone made `covered > scope` — 22/21 for
                     # check_checkers, 43/42 for check_hashes, each inflated by its one
                     # switch file. Same shape ZeroParadox caught on evidence, arriving
                     # through the other member of the denominator. `judged` is the
                     # number `covered` is actually out of.
                     "judged": len(judged),
                     "outstanding": len(outstanding),
                     "outstanding_notes": [o.get("note") for o in outstanding
                                           if isinstance(o, dict)][:5],
                     "subjects_covered": covered, "subjects_stale": stale,
                     "evidence_stale": ev_stale, "evidence_moved": ev_moved,
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
        # ⭐⭐ COVERAGE BINDS ONLY WHEN POLICY SAYS SO. Until 2026-08-25 an in-scope
        # path a step had never examined was counted and not enforced, so a row could
        # read SATISFIED over a fraction of its own scope. `guards`: 4 of 504, green.
        if config.coverage_complete_required:
            short = [r["step"] for r in gating if r["subjects_unexamined"]]
            if short:
                complete = False

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
        # ⭐⭐ ALL rows, gating or not, and REPORTED RATHER THAN BLOCKING. A dead
        # pattern on a type nothing currently admits is still a gate that can never
        # fire, and promoting that type later would inherit the hole silently.
        #
        # ⚠ Making it BLOCK would refuse every push until every such glob is fixed,
        # and that is Tim's call rather than a side effect of a detector landing --
        # the same line `subjects_unexamined` draws. But a gate that cannot fire is
        # not a quiet fact, so it is on the row, in the `why` where the misleading
        # sentence used to be, and here.
        "dead_patterns": [d for r in rows for d in (r.get("dead_patterns") or [])],
        # ⚠ ALL registered steps, not just gating ones. The caller deciding what to RUN
        # is a different question from what GATES -- a hook has emitters for types that
        # may not be admitted, and must not be told to skip them just because nothing
        # currently gates on them.
        "needs_rerun": sorted(r["step"] for r in rows if r["needs_rerun"]),
        "missing": n("MISSING"), "stale": n("STALE"),
        "evidence_moved": sorted({p for r in rows
                                  for p in (r.get("evidence_moved") or [])}),
        # ⚠ Across ALL rows: a step admitted while carrying findings is a fact about
        # the action as a whole, not a detail of one row.
        "outstanding": sum(r.get("outstanding") or 0 for r in rows),
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


def coverage_gap(*, config, records, action: str, files: dict,
                 admission: list, step: Optional[str] = None,
                 limit: int = 200) -> dict:
    """THE WORK ORDER: which paths does each step still owe a PASS at THIS content?

    ⭐⭐ A TOOL RATHER THAN A GENERATED LIST, and that is the whole point. Tim asked
    2026-08-25 for every file at HEAD to be reanalysed, excluding only those with a
    complete passing set. The obvious answer was to compute the 503 paths once and
    hand them over as a file — which would be WRONG within minutes of the sweep
    starting, and would be a second copy of a fact the ledger already holds. This
    session has spent a day on what second copies do. Ask the question again instead.

    ⚠ DIFFERENT QUESTION FROM `coverage()`. That one asks "has ANY step ever named
    this path?" — a floor, useful on day one. This asks, per step, "is there a PASSING
    verdict over the bytes that are here NOW?" A path examined last week by a step
    that has since gone stale counts for `coverage()` and is missing here.

    ⚠ PASSING ONLY. A step whose record covers a path but FAILED has not discharged
    it, and listing it as covered would report work as done that must still be fixed.
    Measured 2026-08-25: `editorial`, `adversary` and `rely` cover their whole scope
    and pass NONE of it — 0 have, and the remedy is to fix findings, not to re-run.
    """
    reqs = config.requirements(action)
    passing = {}
    for r in records:
        if r.get("verdict") != "PASS":
            continue
        for sub in r.get("subjects") or []:
            if sub.get("git_blob_id"):
                passing[(r.get("step"), sub.get("path"), sub["git_blob_id"])] = r

    out = []
    for name in sorted(admission):
        if step and name != step:
            continue
        spec = reqs.get(name)
        if not spec or not spec["required"]:
            continue
        when = spec.get("when")
        globs = spec.get("scope") or ([when] if when else [])
        drop = spec.get("scope_exclude") or []
        applies, missing = 0, []
        for path, blob in sorted(files.items()):
            if when and not fnmatch.fnmatch(path, when):
                continue
            if globs and not any(fnmatch.fnmatch(path, g) for g in globs):
                continue
            if any(fnmatch.fnmatch(path, g) for g in drop):
                continue
            applies += 1
            if (name, path, blob) not in passing:
                missing.append(path)
        out.append({
            "step": name, "applies_to": applies, "missing": len(missing),
            "have": applies - len(missing),
            # ⚠ TRUNCATION IS REPORTED. A capped list that renders like a complete one
            # is the failure this whole server exists to end.
            "paths": missing[:limit],
            "truncated": max(0, len(missing) - limit),
            "remedy": ("nothing owed" if not missing else
                       "fix the findings — this step covers its scope and passes none "
                       "of it, so re-running changes nothing"
                       if applies and len(missing) == applies
                       and any(r.get("step") == name and r.get("verdict") == "FAIL"
                               for r in records)
                       else "run the step over the listed paths and record"),
        })
    return {"action": action, "steps": out,
            "total_missing": sum(s["missing"] for s in out),
            "complete_steps": sorted(s["step"] for s in out if not s["missing"]),
            "tracked": len(files)}


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
