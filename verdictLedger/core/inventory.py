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
        # ⚠⚠ THE WORST COVERING VERDICT WINS, NOT THE FIRST ONE FOUND. This was
        # `covered_rec = covered_rec or rec`, so the row's verdict came from whichever
        # record happened to cover the alphabetically-first path — and that is a
        # FAIL-OPEN, measured 2026-08-28 while answering ZeroParadox:
        #
        #   FAIL over {bad1.md, bad2.md} + PASS over {ok1.md, ok2.md}
        #      -> status FAIL, complete False        (the FAIL sorts first)
        #   FAIL over {zbad1.md, zbad2.md} + PASS over {aok1.md, aok2.md}
        #      -> status SATISFIED, complete TRUE    (the PASS sorts first)
        #
        # Same records, same basis, same content, opposite admission — decided by
        # FILENAME. A recorded FAIL became invisible and the push was allowed.
        #
        # ⚠ IT MATTERS NOW BECAUSE THE SPLIT IS THE DOCUMENTED DESIGN. `record.emit`
        # says "a step that examined forty files and failed on one emits a PASS over
        # the thirty-nine and a FAIL over the one". Every round that does what the
        # docstring asks produces exactly the two-record shape this mishandled, so the
        # correct usage was the one that triggered it.
        #
        # ⚠ GENUINE SUPERSESSION IS UNAFFECTED. `by_content` already resolves each
        # path to its HIGHEST-revision record for that content, so a FAIL properly
        # regraded by a later PASS over the same bytes never reaches this list. Taking
        # the worst ACROSS paths is a different question from taking the latest AT a
        # path, and only the second is what `revision` means.
        covered, stale = 0, 0
        covered_recs, stale_rec = [], None
        for path in judged:
            rec = by_content.get((step, path, files[path]))
            if rec is not None:
                covered += 1
                covered_recs.append((path, rec))
            elif (step, path) in by_path:
                # examined, but never at THIS content
                stale += 1
                stale_rec = stale_rec or by_path[(step, path)]
        _SEVERITY = {"FAIL": 0, "UNDECIDED": 1, "PASS": 2}

        # ⭐⭐⭐ EXAMINED IS NOT INDICTED. A FAIL record condemns ONLY the paths it
        # NAMES as failing; for every other subject it is ordinary PASSING coverage.
        #
        # ⛔ MEASURED 2026-09-02, and it had condemned an entire push. `check_checkers`
        # emitted ONE FAIL over all 24 checkers because two of them were bad, so its
        # subject set and its indictment were the same list:
        #
        #     FAIL @140bf315  subjects=24  reason="2 failing subject(s):
        #                                   tools/verify/(roster), .../check_codebox.py"
        #     PASS @8cd8cc32  subjects=24        <- the tip, genuinely clean
        #
        # 23 of those 24 subjects carry blobs IDENTICAL in both records. The FAIL was
        # written LAST, so `>=` in `_index` gave it those 23 content keys, and
        # worst-verdict-wins then read a FAIL for the TIP — whose only actually-indicted
        # file, `check_codebox.py`, had moved `ddba1f95 -> e64f7d16` and been fixed.
        #
        # ⚠⚠ IT SPREAD BACKWARDS THROUGH HISTORY TOO: a commit predating
        # `check_codebox.py` ENTIRELY still read FAIL, because the 23 innocent blobs it
        # shares were enough. One real defect in one file condemned every commit that
        # merely contained the files examined beside it, and no re-run could clear it.
        #
        # ⭐ THIS IS THE CONTENT-KEYED RULE APPLIED IN THE DIRECTION IT WAS MISSING.
        # Coverage already required proof that THESE EXACT BYTES were examined; a
        # verdict may not travel to bytes nobody judged. Condemnation is the same claim
        # with the sign flipped, and it was travelling freely.
        #
        # ⚠ `record.emit`'s own docstring specifies the correct shape — "a step that
        # examined forty files and failed on one emits a PASS over the thirty-nine and
        # a FAIL over the one" — so a single wide FAIL was always malformed. It is
        # tolerated rather than rejected because the stream is APPEND-ONLY and records
        # written before this rule existed cannot be withdrawn.
        #
        # ⚠⚠ ABSENT `failing` MEANS ALL SUBJECTS ARE INDICTED — the pre-existing
        # behaviour exactly, so no historical FAIL is silently weakened by this landing.
        # The remedy for a record like the one above is to re-emit it at a HIGHER
        # REVISION with `failing` naming the real subset; that is what revisions are
        # for, and it supersedes per-content without editing the past.
        # ⭐⭐ BOTH BLOCKING VERDICTS NARROW, and UNDECIDED was missing here for as long as
        # the validator refused to let it carry `failing` at all — the two halves of one
        # hole, which is why they land together. A panel that splits 2–1 over forty files
        # (Tim, 2026-09-05: *"the undecided is a perfect use case here when the three copy
        # editors disagreeing"*) is undecided about the disputed line and DECIDED about the
        # other thirty-nine. Narrowing on FAIL only would have left it condemning all forty.
        #
        # ⚠ THE ORDER OF THESE TWO CHANGES IS NOT OPTIONAL. Teaching the validator to ACCEPT
        # `failing` on an UNDECIDED without teaching the resolver to READ it produces exactly
        # the shape that guard's own comment calls the worst available: a field stored,
        # accepted, and silently ignored — a record that LOOKS like it narrows and does not.
        # Refused-but-honest beats accepted-but-inert.
        def _severity_at(path, rec):
            v = rec.get("verdict")
            if v in ("FAIL", "UNDECIDED"):
                failing = rec.get("failing")
                if failing is not None and path not in set(failing):
                    return _SEVERITY["PASS"]
            return _SEVERITY.get(v, 3)

        covered_rec = None
        if covered_recs:
            _p, covered_rec = min(covered_recs, key=lambda pr: _severity_at(pr[0], pr[1]))
            # ⚠ The ROW's verdict must be the worst one that actually applies here. If
            # the worst covering record blocks but indicts nothing in this scope, the row is
            # SATISFIED and must not render that record's verdict — otherwise the narrowing
            # above changes `complete` while the displayed status still says FAIL (or
            # UNDECIDED), which is the collapse this module exists to prevent.
            #
            # ⚠ `_narrowed_from` carries the ORIGINAL verdict rather than a flag, so a reader
            # can tell a narrowed FAIL from a narrowed UNDECIDED. They are different claims:
            # one says "judged and condemned elsewhere", the other "judged and DISPUTED
            # elsewhere", and collapsing them would lose the distinction Tim added UNDECIDED
            # to make.
            _v = covered_rec.get("verdict")
            if (_v in ("FAIL", "UNDECIDED")
                    and _severity_at(_p, covered_rec) == _SEVERITY["PASS"]):
                covered_rec = dict(covered_rec, verdict="PASS", _narrowed_from=_v)

        # ⭐⭐ THE BYTES THIS ROW ACTUALLY CONDEMNS, NAMED — not just the fact that it failed.
        # Required by the TIP-GREEN bar (Tim, 2026-09-02): a range may publish when the tip is
        # green **and every intermediate's defects are fixed within the same push**, which is
        # only answerable if a FAIL says WHICH BYTES it condemns. Without this, a caller asking
        # "was this fixed?" can only re-run the checker — and re-running is exactly what cannot
        # clear an honest FAIL about bytes that have since moved on.
        indicted = []
        for _p, _r in covered_recs:
            if (_r.get("verdict") in ("FAIL", "UNDECIDED")
                    and _severity_at(_p, _r) != _SEVERITY["PASS"]):
                indicted.append({"path": _p, "git_blob_id": files[_p],
                                 "record_id": _r.get("id")})

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
        # ⚠⚠ AND THEY MUST NOT VANISH WHEN THE ROW STOPS BEING SATISFIED. This read
        # `... if status == "SATISFIED" else []`, so the moment a later commit moved one
        # subject the row went STALE and its findings rendered as `outstanding: 0` —
        # measured 2026-08-30: editorial and adversary held 7 and 5 recorded findings and
        # `inventory` reported zero for both. Raised by ZeroParadox as LED-7.
        #
        # ⭐ IT MATTERS MORE UNDER THE ORDINARY CAP THAN IT DID WHEN V18 SHIPPED. With
        # R-LOOPCAP the gates record PASS-with-`outstanding` rather than FAIL, so
        # `outstanding` is now the PRIMARY carrier of every finding not being fixed before a
        # push. Zeroing it on staleness turns "reviewed, not certified clean" into
        # "reviewed, findings lost" — silently, because 0 and 0 are the same bytes.
        #
        # ⚠ SO THE FINDINGS COME FROM THE WINNING RECORD WHETHER IT COVERS OR IS STALE, and
        # `outstanding_stale` says which. A reader must be able to tell "no findings" from
        # "findings recorded against bytes that have since moved" — the second is still a
        # fact about the corpus, and it is the one a stale row was hiding.
        # ⚠⚠ THE UNION ACROSS EVERY COVERING RECORD, NOT ONE OF THEM. The first version read
        # `covered_rec`, which is `min(covered_recs, key=severity)` — and `covered_recs` holds
        # one entry PER COVERED PATH. When every candidate is PASS the severity key ties, so
        # `min` returns whichever record happens to cover the alphabetically first path.
        # Measured 2026-08-30: adversary resolved to an older `039aa56f#2` carrying 11 findings
        # while `adversary@01418e4#0` carrying 7 — the round the caller was actually pushing —
        # contributed nothing. The count was right and the FINDINGS were the wrong ones.
        #
        # ⭐ A STEP CAN HAVE SEVERAL RECORDS COVERING IT AT ONCE, so `outstanding` sourced from
        # ONE of them means the field's value depends on a selection rule nothing states, and a
        # reader seeing `11` cannot tell it is not `11 of 27`. That is the same defect as the
        # zeroing, one layer out: a number that renders identically whether it is complete or
        # partial. ZeroParadox's observation, reported as a measurement rather than a cause —
        # which is why it was actionable.
        #
        # ⚠ Findings are ADDITIVE facts about the corpus, so the union is the honest answer and
        # `outstanding_from` names which records contributed. Deduped by note, because the same
        # finding restated in a later round is one finding, not two — an inflated count is as
        # misleading as a truncated one.
        # ⚠ `covered_recs` holds (path, record) PAIRS since the indictment narrowing above —
        # unwrapped here rather than at the append, because the path is what decides whether a
        # FAIL applies and it must stay attached until that question is answered.
        _covering = [_r for _p, _r in covered_recs]
        if status == "SATISFIED":
            _out_recs = _covering
        else:
            _out_recs = _covering or ([stale_rec] if stale_rec else [])
        _seen_ids, _seen_notes, outstanding, _out_from = set(), set(), [], []
        for _rec in _out_recs:
            _rid = (_rec or {}).get("id")
            if _rid in _seen_ids:
                continue
            _seen_ids.add(_rid)
            _contributed = False
            for _o in ((_rec or {}).get("outstanding") or []):
                _key = _o.get("note") if isinstance(_o, dict) else str(_o)
                if _key in _seen_notes:
                    continue
                _seen_notes.add(_key)
                outstanding.append(_o)
                _contributed = True
            if _contributed:
                _out_from.append(_rid)

        if status == "SATISFIED" and record is not None:
            how = (record.get("decided") or {}).get("how", "?")
            how_counts[how] = how_counts.get(how, 0) + 1

        rows.append({"step": step, "family": family, "status": status,
                     "record_id": (record or {}).get("id"),
                     # ⚠ THE BYTES CONDEMNED, so "is it fixed?" is answerable without
                     # re-running a checker that cannot clear an honest FAIL. Empty on every
                     # non-failing row. See the TIP-GREEN bar in `canpush`.
                     "indicted": indicted,
                     # ⭐⭐ NARROWED-CLEAN IS NOT THE SAME FACT AS CLEAN, and until this line
                     # existed a reader could not tell them apart. A row that says SATISFIED
                     # because the covering record indicted OTHER paths has been judged by a
                     # verdict that BLOCKS somewhere; a row that says SATISFIED because the
                     # verdict was a PASS has not. Both rendered identically.
                     #
                     # ⚠ `canpush` already refuses that collapse one level up — "whether the
                     # range was clean or merely forgiven is the exact collapse this gate
                     # exists to prevent" — and forgiveness is narrowing applied to a commit.
                     # The provenance was surfaced for the outer case and dropped for the
                     # inner one, so the same argument reached only half its subject.
                     #
                     # ⚠ Carries the ORIGINAL verdict, not a boolean: narrowed from FAIL means
                     # "condemned elsewhere", narrowed from UNDECIDED means "DISPUTED
                     # elsewhere", and those are different things to go read.
                     "narrowed_from": (record or {}).get("_narrowed_from"),
                     "dead_patterns": dead,
                     # ⚠ `covered` is measured over scope ∪ switches, so reporting
                     # it against `scope` alone made `covered > scope` — 22/21 for
                     # check_checkers, 43/42 for check_hashes, each inflated by its one
                     # switch file. Same shape ZeroParadox caught on evidence, arriving
                     # through the other member of the denominator. `judged` is the
                     # number `covered` is actually out of.
                     "judged": len(judged),
                     "outstanding": len(outstanding),
                     # ⚠ NEVER REPORT A COUNT WITHOUT ITS CURRENCY. Findings carried by a
                     # STALE record are about bytes that have moved; they are still findings,
                     # and a reader who cannot tell will either act on stale ones or ignore
                     # live ones. Same reason `evidence_stale` sits beside `subjects_stale`.
                     "outstanding_stale": bool(outstanding) and status != "SATISFIED",
                     # ⚠ PROVENANCE TRAVELS WITH THE COUNT. Without it a reader cannot tell
                     # `11` from `11 of 27`, which is the ambiguity this row exists to remove —
                     # the same argument that put `outstanding_stale` beside the number.
                     "outstanding_from": _out_from,
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


def progress(*, config, records, action: str, files: dict, admission: list,
             rounds: int = 8) -> dict:
    """ONE VIEW: what blocks the push, and is it converging?

    ⭐⭐ Tim, 2026-08-29: "my only concern is that you end up in some kind of a loop
    where you're not actually making progress.. so we would definitely need some kind
    of progress tracking done so that we're actually seeing everything from a single
    viewpoint, and actually making progress towards convergence."

    `inventory` answers "is it green NOW" and `coverage_gap` answers "which paths owe
    a PASS". Neither answers "is this getting better", and that is the question a loop
    hides in: every round can look identical while the underlying numbers drift the
    wrong way, and nobody notices because each snapshot is read on its own.

    ⚠⚠ THE BAR MUST NOT MOVE UNDER THE WORK, AND THIS IS WHERE THAT IS VISIBLE.
    Every record carries `run.config_sha` — the identity of the policy AND registry it
    was judged under. A scope widened mid-convergence silently invalidates the reason a
    step went green, and the row keeps reading SATISFIED because coverage is keyed on
    content, not on the bar. `bar_drift` names every step whose passing records were
    earned under a DIFFERENT config than the one now in force. Tim, same day: "no more
    random ass stuff getting into scope at a later point."

    ⚠ `history` is per step, newest last, so a reader sees direction rather than a
    point. A review gate whose findings are not shrinking across rounds is the loop
    this exists to surface — and the honest signal is that its verdicts stay FAIL while
    its subject count does not move.
    """
    inv = build(config=config, records=records, action=action, files=files,
                admission=admission)
    gap = coverage_gap(config=config, records=records, action=action, files=files,
                       admission=admission, limit=0)
    gap_by_step = {s["step"]: s for s in gap["steps"]}
    current_sha = config.config_sha

    # per step, the verdicts in the order they were recorded
    by_step: dict = {}
    for r in sorted(records, key=lambda r: ((r.get("run") or {}).get("started") or "")):
        by_step.setdefault(r.get("step"), []).append(r)

    blocking, converging = [], []
    for row in sorted(inv["rows"], key=lambda r: r["step"]):
        if not row["gating"]:
            continue
        step = row["step"]
        hist = by_step.get(step, [])[-rounds:]
        seq = [{"at": ((h.get("run") or {}).get("started") or "")[:16],
                "verdict": h.get("verdict"),
                "subjects": len(h.get("subjects") or []),
                "outstanding": len(h.get("outstanding") or [])} for h in hist]

        if row["status"] != "SATISFIED":
            g = gap_by_step.get(step, {})
            # ⚠⚠ A BLOCKING ROW MUST EXPLAIN ITSELF EVEN WHEN IT OWES NOTHING.
            # Measured 2026-08-29 cycle 1: `claim_review` read STALE / owes 0 / remedy
            # "nothing owed" — three fields that look like a contradiction and are not.
            # It was stale on its EVIDENCE (the producer moved), and `coverage_gap`
            # counts SCOPE paths only, so the work number is legitimately zero while
            # the step is legitimately blocked.
            #
            # Two correct numbers reading as a contradiction is the indicator problem
            # Tim named an hour earlier, arriving in the tool built to answer it. The
            # row now carries `why` from the inventory and states the real remedy.
            owes = g.get("missing")
            remedy = g.get("remedy")
            if not owes and row["status"] != "SATISFIED":
                remedy = (f"nothing in SCOPE is owed — this step is {row['status']} for "
                          f"another reason: "
                          + (f"its producer moved ({', '.join(row.get('evidence_moved') or [])})"
                             if row.get("evidence_stale") else
                             (row.get("why") or "see the inventory row"))
                          + ". Re-run it.")
            blocking.append({
                "step": step, "status": row["status"],
                "covered": row["subjects_covered"], "scope": row["scope"],
                "owes_a_pass": owes,
                "never_examined": row["subjects_unexamined"],
                "evidence_stale": row.get("evidence_stale", 0),
                "why": row.get("why"),
                "remedy": remedy,
                "history": seq,
            })
        else:
            converging.append(step)

    # ⚠⚠ HAS THE SCOPE MOVED SINCE THIS RUN STARTED? A frozen bar that is merely
    # AGREED is a convention; one recorded as a sha is checked on every call. Scope
    # lives in the registry, so the freeze is keyed on the registry sha alone —
    # a threshold change must not read as a scope change.
    frozen = config.frozen_registry_sha
    now = config.registry_sha
    if not frozen:
        freeze = {"frozen": False, "note": (
            "NO FROZEN BAR. Scope may widen mid-run and a widened scope does NOT "
            "re-open a green row, so progress can be reset invisibly. Set "
            "policy.convergence.frozen_registry_sha to the current registry_sha "
            "before starting a convergence run."), "registry_sha": now}
    elif frozen == now:
        freeze = {"frozen": True, "held": True, "registry_sha": now,
                  "note": "the registry is unchanged since this run was frozen"}
    else:
        freeze = {"frozen": True, "held": False, "registry_sha": now,
                  "frozen_at": frozen,
                  "note": ("⚠⚠ THE BAR MOVED MID-RUN. The registry has changed since "
                           "this convergence run was frozen, so any step that went "
                           "green earlier was judged against a different scope and "
                           "will NOT re-open on its own. Either revert the registry, "
                           "or re-freeze deliberately and expect the numbers below to "
                           "mean less than they did.")}

    return {
        "action": action, "complete": inv["complete"],
        "bar": freeze,
        "satisfied": len(converging),
        "gating": len(converging) + len(blocking),
        "config_sha": current_sha,
        # ⚠ The whole point: what is left, with its direction attached.
        "blocking": blocking,
        "green": sorted(converging),
        # ⚠⚠ `bar_drift` WAS HERE AND IS DELETED, 40 MINUTES AFTER IT WAS WRITTEN.
        # It keyed on `run.config_sha`, which covers policy.v1.json as well as the
        # registry — so the very act of recording this convergence freeze in the policy
        # made it report 19 of 19 steps drifted, while the SCOPE had not moved at all.
        # A signal that fires on every threshold tweak is one people scroll past, and
        # it would have been permanently red from the moment it shipped.
        #
        # `bar` above answers the same question properly, keyed on the REGISTRY sha
        # alone, which is where scope lives. Two mechanisms for one question with the
        # weaker one noisier is the two-copies defect — kept as a comment rather than a
        # deletion, because a rule removed for a reason is worth more on the page than
        # a gap someone re-derives.
        # ⭐⭐ THE NUMBERS, RECONCILED IN ONE PLACE. Tim, 2026-08-29: "we also keep
        # having issues with which indicators to use... that's a concern."
        #
        # Measured the same day, same tree: FIVE "how much is left" numbers across four
        # different denominators — 13/19 steps, 812 unexamined, 877 missing, 12
        # uncovered, 38 unscoped. Each was added to answer a real question and none
        # said how it related to the others, so a reader could not tell which to act on
        # — and 812 against 877 is the worst kind of disagreement, close enough to look
        # like one of them is a bug.
        #
        # They are not in conflict; they are nested, and nobody had ever written the
        # nesting down:
        #
        #   uncovered  ⊂  unexamined  ⊂  owes_a_pass
        #
        # `coverage.uncovered`  paths NO step ever named. A day-one floor.
        # `unexamined`          (step, path) pairs where THAT step never examined the
        #                       path. Wider: a path can be covered by one step and
        #                       unexamined by another.
        # `owes_a_pass`         (step, path) pairs lacking a PASSING verdict at the
        #                       CURRENT content. Widest, and the only one that is
        #                       actually the work: it also counts paths a step DID
        #                       examine, at bytes that have since moved or under a
        #                       verdict that failed.
        #
        # ⚠ `owes_a_pass` IS THE WORK NUMBER. `satisfied/gating` is the GATE number.
        # Everything else is a drill-down, and this block exists so nobody has to
        # reconcile them by hand again.
        "numbers": {
            "gate": {"value": f"{len(converging)}/{len(converging) + len(blocking)}",
                     "means": "admitted steps SATISFIED — this is what `complete` is",
                     "act_on": "the `blocking` list above"},
            "work": {"value": gap.get("total_missing"),
                     "means": "(step, path) pairs lacking a PASSING verdict at the "
                              "current content — the actual remaining work",
                     "act_on": "coverage_gap(step=...) for the path list"},
            "never_examined": {"value": inv.get("unexamined"),
                               "means": "a SUBSET of `work`: pairs that step has never "
                                        "examined at all, as opposed to examined and "
                                        "since moved or failed"},
            "unscoped": {"value": len(inv.get("unscoped") or []),
                         "means": "paths a step examined that its declared scope "
                                  "EXCLUDES — a scope that does not match what the "
                                  "checker reads. Never blocks; read it when a step "
                                  "cannot close"},
            "outstanding": {"value": inv.get("outstanding"),
                            "means": "findings riding a PASS under V18 — ordinary "
                                     "only, and they do not block"},
            "note": ("uncovered ⊂ never_examined ⊂ work. They are nested, not "
                     "competing. `work` is the number to drive down; `gate` is the "
                     "number that decides the push."),
        },
        "unexamined_total": inv.get("unexamined"),
        "outstanding_total": inv.get("outstanding"),
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


def heal_plan(*, config, records, action: str, files: dict, admission: list) -> dict:
    """⭐⭐ WHAT TO RE-RUN TO MAKE THIS REF GREEN — split by WHO CAN DO IT, and by whether
    re-running would help at all.

    Tim, 2026-08-30: *"I absolutely love the term self-healing, anytime that that can be
    implemented."* This is the witness half of that, and deliberately ONLY the witness half.
    The ledger says what is stale, why, and what would clear it. It does not run anything.

    ⚠⚠ THE DISTINCTION THIS TOOL EXISTS FOR: **STALE IS HEALABLE, FAILED IS NOT.** A STALE
    verdict means the content (or the checker that judged it) moved, so the answer is simply
    unknown again — re-running produces a fresh answer and clears it. A FAILED verdict means
    the checker looked and found something; re-running finds it again. Conflating them is how
    you get a self-healing loop that spins forever on a real finding, which is precisely the
    "loop where you're not actually making progress" this project already built `progress()`
    to detect. So `auto` never contains a FAIL, and `blocked` says why in those words.

    ⚠ AND THE SECOND SPLIT IS `family`, WHICH THE REGISTRY ALREADY CARRIES. A `mechanical`
    step is deterministic and cheap — measured 2026-08-30, the six that block an ordinary
    multi-commit push re-run in **16.1s total**. A `review` step needs an agent, judgment, and
    minutes-to-dollars. Only the first can honestly be called self-healing; calling an agent
    round "automatic" is how a review becomes a rubber stamp.

    ⚠ IT NAMES STEPS, NOT COMMANDS, and that is not an omission. The live registry carries no
    `module` for any of its 24 types (measured), so the ledger cannot name the invocation
    without inventing a second copy of something the domain repo already knows. The consumer
    knows how to run its own checkers; it just did not know which ones were owed.
    """
    inv = build(config=config, records=records, action=action, files=files,
                admission=admission)
    gap = coverage_gap(config=config, records=records, action=action, files=files,
                       admission=admission, limit=0)
    owed = {s["step"]: s.get("owes_a_pass") for s in gap["steps"]}

    auto, agent, blocked = [], [], []
    for row in inv.get("rows", []):
        if not row.get("gating") or row.get("status") == "SATISFIED":
            continue
        entry = {
            "step": row.get("step"),
            "family": row.get("family"),
            "status": row.get("status"),
            "owes_a_pass": owed.get(row.get("step")),
            # WHY it is not green, because the two reasons have different remedies
            "subjects_stale": row.get("subjects_stale"),
            "evidence_stale": row.get("evidence_stale"),
            "evidence_moved": row.get("evidence_moved") or [],
        }
        status = row.get("status")
        if status in ("FAIL", "FAILED"):
            entry["why_not_auto"] = (
                "FAILED, not stale. The checker looked and found something; re-running finds "
                "it again. Fix the finding, then re-run.")
            blocked.append(entry)
        elif row.get("family") == "review":
            entry["why_not_auto"] = (
                "review family — needs an agent round and a judgement. Automating this would "
                "turn a review into a rubber stamp.")
            agent.append(entry)
        else:
            entry["heals_by"] = (
                "re-running the checker at this basis and recording the result"
                + (" (its evidence moved, so the fresh record will cite the current checker)"
                   if row.get("evidence_stale") else ""))
            auto.append(entry)

    # ⚠⚠ NAME THE FAILING STEPS THAT DO **NOT** GATE, OR A CALLER CHASES ONE FOREVER.
    # Measured 2026-08-30: ZeroParadox read `rely` as blocking its push. It is FAIL and it is
    # REGISTERED, but `admission.v1.json` deliberately removed it from commit and push — its
    # scope is `tools/verify/*`, so every fix to the tooling stales it while it gates the
    # commit carrying that fix, and its declared 60-file scope contradicts its own brief's
    # "do not run it at full". It is documented there as unsatisfiable BY CONSTRUCTION. A heal
    # plan that stays silent about it lets someone burn rounds on a gate that cannot close and
    # was never asked to. Listed, and explicitly marked as not gating this action.
    not_gating_failing = []
    _named = set()
    for row in inv.get("rows", []):
        if row.get("gating") or row.get("status") not in ("FAIL", "FAILED"):
            continue
        _named.add(row.get("step"))
        not_gating_failing.append({
            "step": row.get("step"),
            "status": row.get("status"),
            "note": (f"FAILING but NOT in the admission set for {action!r}, so it does not "
                     f"block. Do not spend rounds on it unless you are deliberately raising "
                     f"the bar — check config/admission.v1.json for why it was excluded."),
        })

    # ⚠⚠ A NARROWED STEP HIDES ITS FAILURES BEHIND `NOT_APPLICABLE`, AND THAT COST THE MOST
    # SERIOUS FINDING OF 2026-08-30. `prior_art` is narrowed to `actions: []` with `scope: 0`,
    # so `inventory` evaluates no subjects for it, reports `record_id: null`, and the loop above
    # never sees a verdict at all — its status is the NARROWING, not the judgement. Meanwhile a
    # real `prior_art` FAIL sat in the store: *"closest prior art located and uncited"*, naming
    # a paper that documented the same phenomenon five months earlier at far larger scale. It
    # appeared in NO bucket, on the surface that decides whether to push.
    #
    # ⭐ "NARROWED OUT" AND "NOTHING FOUND" MUST NOT RENDER IDENTICALLY. This bucket was added
    # hours earlier for exactly that principle and had this hole in it: it scanned ROWS, and a
    # step with no scope has nothing to put in a row. So scan the RECORDS too — a FAIL whose
    # subjects still match current content is a live finding whatever the registry says about
    # whether it gates.
    _by_content = {(s.get("path"), s.get("git_blob_id"))
                   for _r in records for s in (_r.get("subjects") or [])}
    _latest: dict = {}
    for _r in sorted(records, key=lambda r: ((r.get("run") or {}).get("started") or "")):
        _latest[_r.get("step")] = _r
    for _step, _r in sorted(_latest.items()):
        if _step in _named or _step in {e["step"] for e in blocked}:
            continue
        if _r.get("verdict") not in ("FAIL", "FAILED"):
            continue
        # does it still describe the tree in front of us?
        _live = [s for s in (_r.get("subjects") or [])
                 if files.get(s.get("path")) == s.get("git_blob_id")]
        if not _live:
            continue
        not_gating_failing.append({
            "step": _step,
            "status": "FAIL (step not evaluated for this action)",
            "live_subjects": len(_live),
            "note": (f"A FAILING record whose subjects STILL MATCH current content, for a step "
                     f"the registry does not evaluate for {action!r} — narrowed, or out of "
                     f"scope. It does not block, and it is not nothing: someone ran this and it "
                     f"found something that is still true of these bytes."),
        })

    return {
        "ok": True,
        "action": action,
        "ref": inv.get("ref"),
        "complete": inv.get("complete"),
        "failing_but_not_gating": sorted(not_gating_failing, key=lambda e: e["step"]),
        "auto": sorted(auto, key=lambda e: e["step"]),
        "agent": sorted(agent, key=lambda e: e["step"]),
        "blocked": sorted(blocked, key=lambda e: e["step"]),
        "summary": {
            "auto": len(auto), "agent": len(agent), "blocked": len(blocked),
            "healable": len(auto),
            "note": ("`auto` is mechanical and stale — re-run and record, no judgement. "
                     "`agent` needs a review round. `blocked` is FAILED: re-running will not "
                     "help, the finding has to be fixed."),
        },
    }
