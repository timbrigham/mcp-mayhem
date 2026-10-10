"""`inventory(ref, action)`: the complete set of keys for an action, and what is missing.

The requirement set is declared in advance. An inventory assembled from "the records
that happen to exist" is worthless, because "3 of 3 passed" and "5 never ran" render
identically. That is the enumerator-found-nothing defect (five measured instances),
arriving through a new door. So the manifest is the source and the records are
checked against it, never the other way round.

Identity is not satisfaction. A record is identified by `(step, basis, verdict,
reason, subjects, revision)`, but it satisfies a key while the content it examined
is unchanged: matched on `subjects[].git_blob_id`, never on basis. Matching on basis
would make every record expire on every commit: 40 files, 14 checks recorded against
tree X, one unrelated file changes, and the whole pipeline re-runs, including the
paid review rounds. "Re-run everything, always" only looks like rigour.

Five statuses, and none may ever collapse into another:
  SATISFIED; STALE (examined, content moved: re-run); MISSING (never examined: run
  it); NOT_APPLICABLE (a `when` glob did not match); FAIL/UNDECIDED.
"""

from __future__ import annotations

import fnmatch
import functools
import json
import os
import subprocess
from typing import Optional


@functools.lru_cache(maxsize=1_000_000)
def _fnmatch_memo(path: str, glob: str) -> bool:
    """`fnmatch.fnmatch`, memoised. 2026-10-04: the scope audit in `build` re-tests the same
    (subject path, glob) pairs on every call: 1.6M calls per inventory on the 8,410-record
    stream, each paying Windows `ntpath.normcase` twice (LCMapStringEx), about 3 s of every
    call. It is a pure function of its two arguments, so the memo is exactly equivalent (case
    folding included), and it is bounded so it cannot grow without limit."""
    return fnmatch.fnmatch(path, glob)


def _subject_index(records) -> tuple:
    """See `_subject_index_fold` for the semantics. 2026-10-04: a records snapshot from the
    store carries its cache state, so the fold is reused and extended instead of re-walking every
    record (measured: this walk dominated `inventory`, ~9 s per call on 8,410 records)."""
    cache, state = getattr(records, "_cache", None), getattr(records, "_state", None)
    if cache is not None and state is not None and len(records) == len(state.records):
        idx = cache.subject_index(state)
        if idx is not None:
            return idx
    return _subject_index_fold(None, records)


def _subject_index_fold(base, records) -> tuple:
    """(tips, legacy): path -> the tip record that most recently examined it, per step.

    Keyed on content. `by_content` maps (step, path, git_blob_id) to the record that
    examined exactly those bytes; `by_path` remembers that a step touched a path at
    all, which is what separates STALE ("examined, content moved") from MISSING
    ("never examined"). An earlier version kept one tip per (step, path), so a newer
    verdict erased an older commit's coverage. That was invisible under tip-only
    gating and fatal under range gating, where every commit but the last then reads
    STALE however diligently it was checked at the time.

    Legacy records are separated on purpose. Records written before 2026-08-23 carry
    a 64-hex sha256 under `sha256` instead of a git blob id. Left in the main index
    they compare unequal to every blob id and render as STALE, but "the content
    moved" and "recorded under a superseded identity scheme" are different facts
    with different remedies. Re-running a checker fixes the first and does nothing
    for the second.
    """
    # `base` is a previous result to extend with `records` (which must be the records that
    # follow it in stream order). It is never mutated: outer dicts are copied once, and any inner
    # set is copied before its first write, so a caller still holding `base` sees it unchanged.
    if base is None:
        by_content, by_path, legacy, evidence, ev_content, ev_by_subject = {}, {}, {}, {}, {}, {}
        fresh_sets = None                       # every set is new: no copying needed
    else:
        by_content, by_path, legacy, evidence, ev_content, ev_by_subject = (
            dict(d) for d in base)
        fresh_sets = set()                      # ids of sets already copied in this fold

    def _own(d, key):
        """d[key] as a set this fold may mutate (copy-on-write against `base`)."""
        cur = d.get(key)
        if cur is None:
            cur = set()
            d[key] = cur
            if fresh_sets is not None:
                fresh_sets.add(id(cur))
        elif fresh_sets is not None and id(cur) not in fresh_sets:
            cur = set(cur)
            d[key] = cur
            fresh_sets.add(id(cur))
        return cur

    # by_content: (step, path, blob) -> the record that examined it
    # by_path:    (step, path)        -> some record, for STALE
    # evidence:   step -> {path, ...} recorded as V16/V17 evidence
    # ev_content: (step, path, blob) -> the record that ran under it
    # ev_by_subject: (step, subject path, subject blob) -> {(evidence path, evidence blob), ...}
    #   cited by any record that examined those subject bytes. See the approved-blob exemption in
    #   `build`: it asks whether an approved producer judged these bytes, not whether one judged
    #   something.
    for r in records:
        step = r.get("step")
        rev = r.get("revision", 0)
        # V16 evidence is indexed exactly like a subject, and that is the half of V16 that
        # is not forgeable. Naming the checker module is forgeable by anyone willing to copy
        # a blob id; what is not forgeable is that the record now names a blob, so editing
        # the checker moves it, the key reads STALE, and the step re-runs. A forged
        # mechanical PASS therefore expires the next time the code it misreported changes,
        # instead of standing indefinitely.
        #
        # Tracked separately from subjects and never merged into them: `coverage()` reads
        # `subjects` directly, and folding evidence in would have every checker certifying
        # its own source as reviewed corpus. Evidence is a dependency of the verdict, not a
        # thing the verdict is about: the same relationship `switches` have, and it is
        # treated the same way below.
        for e in r.get("evidence") or []:
            path, blob = e.get("path"), e.get("git_blob_id")
            if not (path and blob):
                continue
            _own(evidence, step).add(path)
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
            cited = _own(ev_by_subject, key)
            for e in r.get("evidence") or []:
                if e.get("path") and e.get("git_blob_id"):
                    cited.add((e["path"], e["git_blob_id"]))
            prior = by_content.get(key)
            # Revision compares within one content key. Across different content
            # there is nothing to supersede: two verdicts about different bytes are
            # both true.
            if prior is None or rev >= prior.get("revision", 0):
                by_content[key] = r
            seen = by_path.get((step, path))
            if seen is None or rev >= seen.get("revision", 0):
                by_path[(step, path)] = r
    return by_content, by_path, legacy, evidence, ev_content, ev_by_subject


def _loosen(glob: str) -> str:
    """The same pattern with its `**/` segments removed.

    `**/` is the only loosening applied, deliberately. It is not a general "try
    easier patterns until something matches" search, which would find a match for
    almost any typo and report confident nonsense. `**/` is the specific construct
    that looks like it broadens a glob but in `fnmatch` narrows it, because it
    requires at least one `/`. Shell and gitignore intuitions produce it; nothing
    else here produces a silently dead pattern.
    """
    out = glob
    while out.startswith("**/"):
        out = out[3:]
    return out.replace("/**/", "/")


def _dead_pattern(glob: str, files, field: str):
    """A narrowing that can never fire, told apart from one that does not fire today.

    Found by the consuming project 2026-08-25, one hour after the glob semantics were
    written down. `pdf_coupling` gates on `when: "**/*.pdf"`. Every tracked PDF in that
    project is at the root (its layout rule requires formal documents to live at the
    root under flat filenames), and `**/*.pdf` cannot match a root-level path. So the
    gate had never fired on a single artifact it exists to protect, and never could have.

    It rendered as `NOT_APPLICABLE: "no path matched '**/*.pdf'"`, which is true. That
    is what makes this the worst shape available: a correct, calm sentence covering a
    gate that is structurally incapable of applying. Nothing distinguished "this gate
    does not apply to this push" from "this gate applies to nothing, ever".

    The test cannot be "matches zero paths". That fires legitimately every time a push
    carries no PDFs, and a signal that fires constantly is one people learn to scroll
    past, which is the failure this module warns about elsewhere. The question that
    separates the two is: does the same pattern, loosened, match things that are
    present? Zero now and zero loosened is an honest narrowing. Zero now and forty
    loosened is a typo.

    The rule it was protecting: a changed PDF must arrive with the `scripts/` builder
    that produced it. The cost of it not firing is a PDF drifting from its builder and
    then being minted into a permanent DOI; four releases already carry latent flaws
    that cannot be withdrawn.
    """
    loosened = _loosen(glob)
    if loosened == glob:
        return None
    now = {p for p in files if fnmatch.fnmatch(p, glob)}
    hits = {p for p in files if fnmatch.fnmatch(p, loosened)}
    # Strictly more, not "matches nothing", and that widening came from a near miss.
    # The first version only fired when the pattern matched zero paths, which caught
    # `pdf_coupling`'s `**/*.pdf` against 40 root PDFs. On 2026-08-25 the consuming
    # project proposed `<project>/**/*.lean` as a scope for four gating steps. It
    # matches 213 of the 218 tracked .lean files: `**/` requires at least one `/`, so
    # it silently drops the five files sitting directly under the top-level directory.
    #
    # Those four rows would then have read 213/213 COMPLETE while five corpus files
    # went unexamined indefinitely: a green row over a scope that quietly dropped
    # content. That is worse than the dead pattern it was modelled on, because it
    # looks like coverage. The zero-match rule could never see it.
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


def convergence_bar(config) -> dict:
    """Has the scope moved since this run was frozen? `{frozen, held, registry_sha, note}`.

    A frozen bar that is merely agreed is a convention; one recorded as a sha is checked on
    every call. Scope lives in the registry, so the freeze is keyed on the registry sha alone:
    a threshold change must not read as a scope change and make the freeze raise false alarms.

    Lifted out of `progress()` 2026-09-07 so `inventory()` can carry it too, and lifted rather
    than copied. The consuming project measured why it matters: `progress()` reported
    `complete: true, satisfied 19/19` beside `bar.held: false`, and gitRobot's `status()`,
    which embeds an inventory rather than a progress, surfaced the 19/19 and not the broken
    bar. A reader of the gate's own status saw green.

    That is the shape this module exists to remove: `complete` is a true value against a
    scope the caller has not been told moved. Complete against which registry? The two facts
    belong on the same answer, or the first one is a claim about an unnamed object.
    """
    # Two bases, and the answer says which one it used. Added 2026-09-18 (a design decision by
    # the maintainer) after measuring that 812 bytes of added rationale moved `registry_sha`
    # while enforcement stayed byte-identical; see `config.registry_scope_digest`. A freeze keyed
    # on the file breaks on comment edits, and a freeze that breaks for reasons nobody caused is
    # one people learn to ignore, which is the failure this function's docstring warns about.
    #
    # The legacy basis is still honoured rather than silently reinterpreted. A stored
    # `frozen_registry_sha` is a file hash; comparing it against a scope digest would read as
    # "the bar moved" forever, for a reason no reader could see. It keeps its own meaning, and
    # the payload names the basis so nobody has to infer which object was compared.
    digest_now = config.registry_scope_digest
    frozen_digest = config.frozen_scope_digest
    # The arc-length basis, preferred when it exists. A design decision (2026-09-26): freeze at
    # the ends of the arcs. A freeze taken at an arc's end cannot be compared against an object
    # that moves whenever a pin is substituted inside the arc. That happened six times on the
    # day of the decision, with the canonical length held at 27254 across all six and moving
    # only on the one real policy change (+846).
    rule_now = config.registry_rule_digest
    frozen_rule = config.frozen_rule_digest
    if frozen_rule:
        basis, frozen, now = "rule_digest", frozen_rule, rule_now
    elif frozen_digest:
        basis, frozen, now = "scope_digest", frozen_digest, digest_now
    else:
        basis, frozen, now = "registry_file_sha", config.frozen_registry_sha, config.registry_sha
    base = {"basis": basis, "registry_sha": config.registry_sha, "scope_digest": digest_now,
            "rule_digest": rule_now}
    # The exemption is disclosed on every path, including the green one, and that disclosure is
    # the entire safety of the second object. `rule_digest` is deliberately blind to a pin
    # substitution, so without this block a repin would be invisible rather than merely
    # non-blocking: an exemption nobody has accounted for.
    #
    # It renders only when both frozen values exist, because that is the only state in which
    # "the difference is pins-only" is a derivable fact rather than an assumption. With just the
    # rule digest frozen, a moved scope digest cannot be attributed.
    if basis == "rule_digest" and frozen_digest:
        pins_moved = frozen_digest != digest_now
        base["pin_exemption"] = {
            "active": bool(pins_moved and frozen_rule == rule_now),
            "scope_digest_frozen_at": frozen_digest,
            "scope_digest_now": digest_now,
            "what_it_excuses": ("a pin substitution (%s) moves the scope digest and no rule; "
                                "against the rule digest it moves nothing"
                                % ", ".join(config.pin_fields)),
            # Named, not proxied. A days- or count-based cap here would be a control testing a
            # proxy for the property. The property is "the arc ended", and this server cannot
            # see an arc: the round counter is worktree-local by construction and is discarded
            # with the worktree. So the bound is stated as a human act rather than asserted as
            # enforced.
            "bounded_by": ("THE ARC'S END, WHICH THIS SERVER CANNOT OBSERVE. Re-freeze both "
                           "values when the arc closes; nothing here expires on its own, and no "
                           "timer stands in for the boundary."),
        }
    if not frozen:
        return {**base, "frozen": False, "note": (
            "NO FROZEN BAR. Scope may widen mid-run and a widened scope does NOT "
            "re-open a green row, so progress can be reset invisibly. Set "
            "policy.convergence.frozen_scope_digest to the current scope_digest "
            "before starting a convergence run.")}
    if frozen == now:
        # The ordering caveat belongs on the held state too; shipping it only in the broken
        # block left the one path where it is silent. Found by a peer review 2026-09-22, of a
        # guard just written for the consuming project:
        #
        #   BROKEN -> re-freeze        the reader sees the warning. The path it was written for.
        #   HELD   -> edit + re-freeze the block never rendered, so the warning never printed.
        #             The caller freezes to the digest read before editing, it is stale on
        #             arrival, and the warning appears only afterwards, describing what was
        #             just done.
        #
        # The second path is not an exotic case; it is the tidy version of the ordinary
        # workflow: one commit, edit and freeze together, from a bar that was not broken. The
        # guard was silent in exactly the configuration that produces the defect.
        #
        # It goes on the note and not into an alarm, deliberately. The reviewer raised the
        # false-alarm trade-off rather than prescribing a fix: "print it whenever the registry
        # is dirty" would fire on ordinary work and teach its reader to skip it, which is the
        # failure the same day spent undoing in the `witness` block. A note attached to the
        # value is read exactly when someone consults the value, which is the only moment the
        # caveat matters.
        return {**base, "frozen": True, "held": True,
                "note": (f"the registry is unchanged since this run was frozen (basis: {basis})"
                         + (" ⚠ IF YOU ARE ABOUT TO RE-FREEZE AND EDIT THE REGISTRY IN ONE "
                            "CHANGE: `reason` is a SERVED key and is inside this digest, so "
                            "EDIT FIRST and derive the value from the post-edit file. Freezing "
                            "to the digest above and then editing a served key makes the "
                            "checkpoint stale on arrival, silently."
                            if basis == "scope_digest" else ""))}
    out = {**base, "frozen": True, "held": False, "frozen_at": frozen,
           "note": ("⚠⚠ THE BAR MOVED MID-RUN. The registry has changed since "
                    "this convergence run was frozen, so any step that went green earlier "
                    "was judged against a different scope and will NOT re-open on its own. "
                    "Either revert the registry, or re-freeze deliberately and expect the "
                    "numbers to mean less than they did.")}
    # If the legacy file basis tripped while enforcement did not move, say so; otherwise the
    # reader is told "the scope moved" about a documentation edit, which is the false alarm
    # this change exists to remove.
    if basis == "registry_file_sha":
        out["note"] += (
            " ⚠ BASIS IS THE REGISTRY FILE HASH, which moves on ANY byte — a comment edit reads "
            "identically to a rule change here. Migrate to policy.convergence.frozen_scope_digest "
            f"(current scope_digest: {digest_now[:12]}), which prices enforcement alone.")
    return out


def registry_types_at(config, repo: Optional[str], files: dict) -> tuple:
    """`(types, basis)`: the registry as committed in `files`, for judging producer pins.

    Why this exists: measured by the consuming project 2026-09-13 and reproduced here.
    `guards.py@2775fcf6` was approved long enough for nine intermediates to record under
    it, then unpinned at 548b1216. A commit reverting guards.py to 2775fcf6 on top of the
    unpin (dad75d6b, never pushed) read ALLOWED 19/19 with zero new records. V16c refused
    a new record from that build at append time; nothing asked at read time.

    Why the registry at the ref and not today's (a design decision by the maintainer,
    option C of those considered). At every commit in that arc the committed registry approved
    exactly the checker blob the commit carried (929a9f89: guards 2775fcf6, decls
    c39bb97b). So "was this producer approved when this content was committed" is the
    question history can answer honestly. Judged against today's registry instead,
    simulated over the live stream: 13/20 of the already-pushed arc and 86/93 of the last
    93 commits went stale, and every future checker edit would need the approve, record,
    unpin sequence. The per-ref rule cost 3/20 and 54/93, against today's 50/93.

    Works for the index as well as a commit: `files` maps the registry's repo path to the
    blob a commit would carry, and the blob is read by id.

    Absence is never success. When the committed registry cannot be read, the current
    registry's pins apply (the stricter reading), and `basis` names why. `repo=None` means
    the caller could not say where the content lives; the read-time check is then not
    applied, and `basis` says so rather than implying it ran.
    """
    current = config.required.get("types") or {}
    if not repo:
        return current, "unchecked: no repository was given, so the read-time pin check did not run"
    try:
        rel = os.path.relpath(os.path.realpath(str(config.required_path)),
                              os.path.realpath(str(repo))).replace(os.sep, "/")
    except ValueError:                      # a different drive on Windows
        rel = ".."
    if rel.startswith(".."):
        return current, "current: the registry is not tracked inside the repository"
    blob = files.get(rel)
    if not blob:
        return current, f"current: no committed {rel} at this ref"
    try:
        proc = subprocess.run(["git", "cat-file", "-p", blob], cwd=str(repo),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=30)
        if proc.returncode != 0:
            raise ValueError(proc.stderr.strip())
        types = json.loads(proc.stdout).get("types")
        if not isinstance(types, dict):
            raise ValueError("no `types` object")
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        return current, f"current: {rel}@{blob[:12]} could not be read ({exc})"
    return types, f"ref: {rel}@{blob[:12]}"


def build(*, config, records, action: str, files: dict,
          ref: Optional[str] = None, admission: Optional[list] = None,
          refusals: Optional[dict] = None,
          changed: Optional[set] = None, published: Optional[set] = None,
          repo: Optional[str] = None, subject_index: Optional[tuple] = None,
          scope_audit: Optional[dict] = None) -> dict:
    """``files`` maps path -> git blob id for the content being promoted.

    The blob id, not a content digest, and the distinction cost an afternoon. These
    values come straight from `git ls-tree` / `git ls-files -s`, and a subject matches
    only if it carries the same thing. The field used to be called `sha256`, so a
    client computed a sha256 of the file bytes: a different hash function over a
    different byte string (git prefixes "blob <len>\0"). No key could ever be
    satisfied, and every record decayed to STALE permanently.

    Two lists, not two copies. The registry (config.types) says what may be recorded;
    the admission set says what must be green to let an action through. They answer
    different questions, so `complete` is computed against `admission`, not against
    every registered type. Twenty experimental gates recording while three admit a
    push is a coherent, intended state.

    An earlier model conflated them, and the sign that it was wrong is that its
    correct implementation blocks every push until every registered type has an
    emitter. A model whose correct implementation disables the system is describing
    the wrong system.

    `admission=None` means "no admission set was named", which is not the same as an
    empty one and must never read as satisfied; see `admission_state`.
    """
    reqs = config.requirements(action)
    # The index is a pure function of `records`, and a range walk used to rebuild it once per
    # commit. Measured 2026-09-22 by profiling a real 43-commit push: `_subject_index` ran 43
    # times over the same 5,375-record stream, 349 s of a 675 s profiled run. 52% of the work
    # was recomputing a value that could not have changed. `canpush.check` holds one `records`
    # list for the whole walk, so it now builds this once and passes it down.
    #
    # This is a reachability fix, not a cosmetic speedup. `gitRobot.push` calls `can_push`
    # over the whole range synchronously before it emits the `run_id`, so the cost of this
    # walk is paid inside the client's 300 s call window. Measured the same day: a 43-commit
    # push spent 339 s here and the client abandoned the call 39 seconds short. The handle
    # that exists so a long push survives a short window was itself gated behind the most
    # expensive call in the flow, so the bigger the arc, the more certainly the caller lost
    # it.
    #
    # Safe because `build` only reads these structures, verified by reading every use before
    # the change: one lookup (`by_path[(step, path)]`) and no assignment, `.pop`,
    # `.setdefault` or `del` against any of the six. A mutated index shared across commits
    # would corrupt every row after the first, silently and in the direction that reads as
    # coverage.
    #
    # Optional, and absent means compute, never "assume an empty index". `ledger.py` and
    # every direct caller keep the old behaviour; a new parameter must not change what a
    # caller who does not pass it receives.
    (by_content, by_path, legacy_tips, evidence_paths,
     ev_content, ev_by_subject) = subject_index or _subject_index(records)
    pin_types, pin_basis = registry_types_at(config, repo, files)
    pin_checked = not pin_basis.startswith("unchecked")

    rows = []
    _scope_paths, _unexamined_paths = {}, {}
    how_counts: dict = {}
    for step, spec in sorted(reqs.items()):
        family = spec["family"]
        if not spec["required"]:
            # `not_applicable_because` names which of the NOT_APPLICABLE causes this is, as a
            # value rather than prose. Added 2026-10-09 for `evidence-currency`, whose output
            # had labelled every such step "empty scope", which is true of one cause in three.
            rows.append({"step": step, "family": family, "status": "NOT_APPLICABLE",
                         "not_applicable_because": "not_required_for_action",
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
            # "It did not apply" and "it passed" must never render the same, and the
            # status carries the glob that excluded it.
            #
            # Equally, "it does not apply today" must not render like "it applies to
            # nothing, ever". `no path matched '**/*.pdf'` is a true, calm sentence that
            # covered a gate which had never once fired on the artifacts it exists to
            # protect. When the same pattern, loosened, matches files that are present,
            # say so where the misleading sentence was.
            d = next((x for x in dead if x["field"] == "when"), None)
            why = (f"no path matched {when!r}"
                   if d is None else
                   f"⚠ DEAD PATTERN, not a narrowing: {when!r} matched 0 paths, but "
                   f"{d['suggestion']!r} matches {d['would_match']} of them "
                   f"(e.g. {d['example']!r}). `**/` requires at least one '/', so this "
                   f"glob cannot match a top-level file and this gate has almost "
                   f"certainly never fired. Fix the pattern; do not re-run.")
            rows.append({"step": step, "family": family, "status": "NOT_APPLICABLE",
                         "not_applicable_because": "when_matched_no_file",
                         "why": why, "record_id": None,
                         "subjects_covered": 0, "subjects_stale": 0,
                         "subjects_unexamined": 0, "scope": 0, "subjects_unscoped": [],
                         "dead_patterns": dead,
                         "needs_rerun": False, "rerun_reason": None})
            continue

        # How much of the scope was never examined at all.
        #
        # Measured 2026-08-23: a step that examined one file out of 201 reported
        # SATISFIED, because a path with no record for that step contributed to
        # neither `covered` nor `stale` and so was simply not counted. Absence
        # rendered as success, the defect class this server exists to end, arriving
        # through the one path nobody had checked.
        #
        # It matters because the consuming project's `common.ledger_subjects` drops
        # any path whose worktree differs from the index. That fence is honest about
        # what it read, but the narrowing was invisible here, so a dirty tree quietly
        # shrank what a green key meant.
        #
        # Reported, not yet blocking. Making it block is a policy change that would
        # refuse every push until every step covers every in-scope path, and that is
        # the maintainer's decision, not a side effect of a bug fix. But a downgraded
        # gate has to be more visible, so the number is on every row and in the
        # rendered line.
        # `scope` if declared, else `when`, else every path. The default is the strict
        # reading and stays that way: a type that has not said what it examines owes
        # the whole tree. Measured 2026-08-23: without a declared scope, `guards`
        # reported 475 of 479 paths unexamined and would have been re-run on every
        # commit indefinitely, which is the 18.26 s this design exists to skip.
        # `scope` is a list of globs; a path is in scope if any matches. `when` remains
        # a single glob because it answers a different question (whether the type
        # applies at all), and no measured case needed more than one.
        # fnmatch's `*` crosses `/`, so `*` alone is "every path" and a `**/` prefix is
        # wrong rather than redundant: `**/*` requires at least one directory and
        # misses every top-level file. Measured 2026-08-23.
        globs = spec.get("scope") or ([when] if when else [])
        drop = spec.get("scope_exclude") or []
        # Session state is not in any step's scope, because nobody may record it.
        # Second occurrence of this defect, reported by the consuming project 2026-09-18, and
        # this one hard-blocked a push with a remedy no caller could execute. `check_encoding`'s
        # scope claimed `gate_round.json` (482 paths); the subject fence refuses it as a verdict
        # subject unconditionally; so coverage could never exceed 481/482, the commit could
        # never be complete, and `progress` printed "run the step over the listed paths and
        # record" for a path `record.py` declines at the same time.
        #
        # Worse than the first occurrence, which is why it had to be fixed here. Last time the
        # caller escaped by restoring the file's canonical bytes, which took it out of the range
        # diff. Here the blocking commits were already written and their trees hold the modified
        # blob; nothing done at HEAD changes what an earlier commit contains. The only
        # caller-side escapes left were rewriting history (forbidden) or never committing the
        # file (impossible: it is tracked precisely so it always reads round 0).
        #
        # It lands at the one place scope is computed, as the consuming project asked. Their
        # `session_state.txt` header predicted this: the list is declared in four places and
        # asks to be the one they collapse onto. The ratchet became a fifth reader and
        # per-commit coverage a sixth. Fixing it per consumer guarantees a seventh, so every
        # derived set (`_scope_paths`, `unexamined_paths`, `judged`, staleness, the
        # min_coverage bar) now inherits the exclusion from here rather than re-deriving it.
        #
        # The checkers still read these files. Their header is explicit: this is not an
        # exemption from being checked; a BOM in `gate_round.json` still blocks. What is
        # excluded is recording a verdict subject about them, because a verdict binds
        # (step, path, blob) and a session-state file's blob is an accident of when a counter
        # last ran.
        session_state = config.session_state_paths
        scope = [p for p in files
                 if (not globs or any(fnmatch.fnmatch(p, g) for g in globs))
                 and not any(fnmatch.fnmatch(p, g) for g in drop)
                 and p not in session_state]
        unexamined_paths = [p for p in scope
                            if (step, p, files[p]) not in by_content
                            and (step, p) not in by_path]
        unexamined = len(unexamined_paths)
        # Kept local, not on the row. The per-step bar needs the actual paths to intersect
        # with what a commit changed, and putting 522 of them on every row for twenty steps
        # would bloat every response for a field almost nobody reads.
        _scope_paths[step] = set(scope)
        _unexamined_paths[step] = set(unexamined_paths)

        # The symmetric number. `subjects_unexamined` finds a scope wider than the
        # property; this finds one narrower than what the checker actually examined,
        # the case the other is structurally blind to, because an excluded path
        # produces no residue at all and everything reads clean.
        #
        # Derived from the checker's own subject set rather than from the declaration,
        # which is the property that makes the pair work at all.
        #
        # Switches are subtracted because they are supposed to sit outside the scanned
        # scope: they are the exemption surface, not the corpus. No further
        # subtraction is needed: `subjects` is everything the verdict depends on,
        # `scope` is what it examines, `switches` is what it depends on beyond that, so
        # `subjects` is contained in their union by construction. Anything left over is
        # an undeclared switch, a scope too narrow, or over-recording -- all three of
        # which someone should look at.
        in_scope = set(scope)
        switch_set = set(spec.get("switches") or [])
        # V16 evidence is subtracted for the same reason switches are: the checker
        # module is supposed to sit outside the scanned scope. Reporting a step's own
        # source as "examined but unscoped" would make the signal fire on every
        # mechanical record ever written, and a signal that fires on everything is one
        # people learn to scroll past -- which is what `subjects_unscoped` exists to
        # avoid being.
        ev_set = evidence_paths.get(step, set())
        unscoped = sorted(p for p in files
                          if (step, p) in by_path
                          and p not in in_scope and p not in switch_set
                          and p not in ev_set)

        # The verdict must come from a record that examined these bytes. Keeping one
        # `record` for both covered and stale hits let a stale record supply the verdict
        # for a step that also had a covering one: whichever path happened to be
        # iterated first won.
        #
        # Measured by the consuming project 2026-08-24: the denominator is the step's
        # scope, never every file. This loop used to walk all of `files`, so a path the
        # step had examined at some earlier basis, but which its declared
        # `scope`/`scope_exclude` now puts outside it, still counted as `stale`. With
        # the record's blob ids 4/4 identical to the index, the row returned STALE,
        # "recorded against different bytes", remedy "re-run".
        #
        # Every part of that was wrong, and the remedy was the worst part: a checker
        # that correctly honours its own scope will never examine that path again, so
        # re-running is the one action that can never clear it. It costs rounds and
        # teaches the operator that the gate is broken rather than that the scope is.
        # STALE and UNSCOPED are different facts with different remedies; this is the
        # collapse of distinct statuses that this module's docstring forbids.
        #
        # This is a weakening, and it is named as one. Out-of-scope residue used to
        # block an action; it no longer does. That block was unclearable, so it was
        # never a gate, only an obstruction. But the residue does not go quiet: it is
        # on every row as `subjects_unscoped`, in the inventory as `unscoped`, and it
        # now carries the MISSING row's `why` below. The scope is the thing to look at,
        # and there is a standing known example of a scope that is wrong.
        #
        # Switches and V16 evidence are in the denominator, not the scope. Both are
        # supposed to sit outside what a checker scans, and both must still be able to
        # stale the key: that is the entire mechanism of V15 and of V16's expiry.
        # Dropping them here would silently disarm two rules as a side effect of a
        # fix to a third.
        # Evidence is not in the subject denominator. Found by the consuming project
        # 2026-08-25 from arithmetic alone: `pdf_coupling` reported
        # `subjects_covered: 42` against `scope: 40`, and its record has exactly 40
        # subjects and 2 evidence entries. Evidence had been folded into the same
        # buckets as subjects, so it counted as coverage.
        #
        # `covered > scope` should be impossible, and it rendered as a bigger number:
        # coverage looking better than it is, which is the direction that matters.
        #
        # It was hidden everywhere else because for almost every mechanical step the
        # evidence files are already subjects: `check_encoding` covers all 450 tracked
        # text files including `batch.py` and `common.py`, so 450 + 2 deduplicated to
        # 451 and the double count was invisible. `pdf_coupling` is the first step
        # whose subjects are disjoint from its evidence, so it is the first place the
        # two could be told apart at all.
        judged = [p for p in files if p in in_scope or p in switch_set]
        # The worst covering verdict wins, not the first one found. This was
        # `covered_rec = covered_rec or rec`, so the row's verdict came from whichever
        # record happened to cover the alphabetically first path. That is a fail-open,
        # measured 2026-08-28 while answering a question from the consuming project:
        #
        #   FAIL over {bad1.md, bad2.md} + PASS over {ok1.md, ok2.md}
        #      -> status FAIL, complete False        (the FAIL sorts first)
        #   FAIL over {zbad1.md, zbad2.md} + PASS over {aok1.md, aok2.md}
        #      -> status SATISFIED, complete TRUE    (the PASS sorts first)
        #
        # Same records, same basis, same content, opposite admission, decided by
        # filename. A recorded FAIL became invisible and the push was allowed.
        #
        # It matters because the split is the documented design. `record.emit` says
        # "a step that examined forty files and failed on one emits a PASS over the
        # thirty-nine and a FAIL over the one". Every round that does what the
        # docstring asks produces exactly the two-record shape this mishandled, so the
        # correct usage was the one that triggered it.
        #
        # Genuine supersession is unaffected. `by_content` already resolves each path
        # to its highest-revision record for that content, so a FAIL properly regraded
        # by a later PASS over the same bytes never reaches this list. Taking the worst
        # across paths is a different question from taking the latest at a path, and
        # only the second is what `revision` means.
        covered, stale = 0, 0
        covered_recs, stale_rec, stale_paths = [], None, []
        r_stale_out_of_range = False
        for path in judged:
            rec = by_content.get((step, path, files[path]))
            if rec is not None:
                covered += 1
                covered_recs.append((path, rec))
            elif (step, path) in by_path:
                # examined, but never at this content
                stale += 1
                stale_paths.append(path)
                stale_rec = stale_rec or by_path[(step, path)]
        _SEVERITY = {"FAIL": 0, "UNDECIDED": 1, "PASS": 2}

        # Examined is not indicted. A FAIL record condemns only the paths it names as
        # failing; for every other subject it is ordinary passing coverage.
        #
        # Measured 2026-09-02, when it had condemned an entire push. `check_checkers`
        # emitted one FAIL over all 24 checkers because two of them were bad, so its
        # subject set and its indictment were the same list:
        #
        #     FAIL @140bf315  subjects=24  reason="2 failing subject(s):
        #                                   tools/verify/(roster), .../check_codebox.py"
        #     PASS @8cd8cc32  subjects=24        <- the tip, genuinely clean
        #
        # 23 of those 24 subjects carry blobs identical in both records. The FAIL was
        # written last, so `>=` in `_index` gave it those 23 content keys, and
        # worst-verdict-wins then read a FAIL for the tip, whose only actually indicted
        # file, `check_codebox.py`, had moved `ddba1f95 -> e64f7d16` and been fixed.
        #
        # It spread backwards through history too: a commit that predated
        # `check_codebox.py` entirely still read FAIL, because the 23 innocent blobs it
        # shares were enough. One real defect in one file condemned every commit that
        # merely contained the files examined beside it, and no re-run could clear it.
        #
        # This is the content-keyed rule applied in the direction it was missing.
        # Coverage already required proof that these exact bytes were examined; a
        # verdict may not travel to bytes nobody judged. Condemnation is the same claim
        # with the sign flipped, and it was travelling freely.
        #
        # `record.emit`'s own docstring specifies the correct shape ("a step that
        # examined forty files and failed on one emits a PASS over the thirty-nine and
        # a FAIL over the one"), so a single wide FAIL was always malformed. It is
        # tolerated rather than rejected because the stream is append-only and records
        # written before this rule existed cannot be withdrawn.
        #
        # Absent `failing` means all subjects are indicted: exactly the pre-existing
        # behaviour, so no historical FAIL is silently weakened by this change. The
        # remedy for a record like the one above is to re-emit it at a higher revision
        # with `failing` naming the real subset; that is what revisions are for, and it
        # supersedes per content without editing the past.
        # Both blocking verdicts narrow. UNDECIDED was missing here for as long as the
        # validator refused to let it carry `failing` at all; those are two halves of one
        # gap, which is why they were changed together. A panel that splits 2-1 over forty
        # files (a design decision, 2026-09-05: UNDECIDED is the intended verdict when three
        # copy editors disagree) is undecided about the disputed line and decided about the
        # other thirty-nine. Narrowing on FAIL only would have left it condemning all forty.
        #
        # The order of these two changes is not optional. Teaching the validator to accept
        # `failing` on an UNDECIDED without teaching the resolver to read it produces exactly
        # the shape that guard's own comment calls the worst available: a field stored,
        # accepted, and silently ignored, a record that looks like it narrows and does not.
        # Refused but honest is better than accepted but inert.
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
            # The row's verdict must be the worst one that actually applies here. If the
            # worst covering record blocks but indicts nothing in this scope, the row is
            # SATISFIED and must not render that record's verdict; otherwise the narrowing
            # above changes `complete` while the displayed status still says FAIL (or
            # UNDECIDED), which is the collapse this module exists to prevent.
            #
            # `_narrowed_from` carries the original verdict rather than a flag, so a reader
            # can tell a narrowed FAIL from a narrowed UNDECIDED. They are different claims:
            # one says "judged and condemned elsewhere", the other "judged and disputed
            # elsewhere", and collapsing them would lose the distinction UNDECIDED was added
            # to make.
            _v = covered_rec.get("verdict")
            if (_v in ("FAIL", "UNDECIDED")
                    and _severity_at(_p, covered_rec) == _SEVERITY["PASS"]):
                covered_rec = dict(covered_rec, verdict="PASS", _narrowed_from=_v)

        # The bytes this row actually condemns, named, not just the fact that it failed.
        # Required by the tip-green bar (a design decision, 2026-09-02): a range may publish
        # when the tip is green and every intermediate's defects are fixed within the same
        # push, which is only answerable if a FAIL says which bytes it condemns. Without this,
        # a caller asking "was this fixed?" can only re-run the checker, and re-running is
        # exactly what cannot clear an honest FAIL about bytes that have since moved on.
        indicted = []
        for _p, _r in covered_recs:
            if (_r.get("verdict") in ("FAIL", "UNDECIDED")
                    and _severity_at(_p, _r) != _SEVERITY["PASS"]):
                indicted.append({"path": _p, "git_blob_id": files[_p],
                                 "record_id": _r.get("id")})

        # The producer moving is a different fact from the corpus moving. The consuming
        # project asked the right question: does editing `common.py` stale a step via its
        # evidence (correct; that is what V16/V17 are for) or via a phantom subject (wrong,
        # and it would misreport which content moved)? Merged into one bucket, the two were
        # indistinguishable in the row. They are counted apart now, and the `why` says
        # which one it was.
        # Evidence citing an approved blob is not stale, and until 2026-09-12 it was. This
        # compared the evidence blob only against `files[path]` (the blob at this ref)
        # while `V16c` compares it against `approved_modules`. Where the checker has moved
        # since the ref, those are different values and no record can satisfy both:
        #
        #     evidence cites the blob at the ref  ->  matches here, V16c refuses the append
        #     evidence cites the approved blob    ->  appends, and this still counted it stale
        #
        # Measured on a live block 2026-09-11/12: `guards@e730a049` sat at 16/17 with
        # `evidence_stale: 1` that no ordinary record could discharge. Each rule was right
        # alone; their conjunction was unsatisfiable, which is the failure mode a rule cannot
        # detect about itself.
        #
        # The remedy text made it worse by naming an outcome the procedure cannot produce:
        # "the fresh record will cite the current checker". A checker derives its repo from
        # `__file__`, so it always reads the tree it lives in: placing the current build in a
        # worktree at an old ref makes it differ from that ref, and running the worktree's own
        # copy cites the old blob. Unreachable by construction, not merely awkward. Found in a
        # peer review by the consuming project, whose layer owns that half.
        #
        # The question this field answers is "has the producer changed, so the verdict may no
        # longer hold", not "would the pipeline have done this at that commit". A record
        # citing an approved checker is the strongest evidence available, not stale evidence.
        #
        # This paragraph used to say "A record citing the current approved checker ... an
        # approved blob counts as fresh no matter which ref it is read at", and the 2026-09-13
        # per-ref pin made that false without anyone updating it. `_approved_blobs` came from
        # `registry_types_at` (the registry as committed at the ref), so "current" was exactly
        # the set it did not consult. Corrected 2026-09-27; the precise rule is now: a citation
        # approved by the registry that governed the content when it was committed, or by the
        # registry governing it now, counts as fresh. Both sets are unioned below; see that
        # comment for why the union is required rather than merely convenient.
        #
        # The outdated sentence cost a peer three permanent records. It was quoted to them as
        # authority for citing today's approved blob, twice, without running the code it
        # describes. The record they wrote was correctly shaped and could never have worked. A
        # load-bearing comment that has drifted from its code is worse than no comment: it is
        # wrong with apparent authority, and it is read exactly when someone needs to be right.
        # The lesson is that a claim about behaviour must be traced in the code before it is
        # relayed, especially by whoever wrote the comment.
        _approved_blobs = set()
        # The pins come from the registry committed at this ref when the caller named the
        # repository; see `registry_types_at`. Scope, family and everything else still come
        # from the live registry: only the producer pin is judged per ref.
        _spec_ev = pin_types.get(step)
        _pinned_module = _spec_ev.get("module") if isinstance(_spec_ev, dict) else None
        if isinstance(_spec_ev, dict):
            _a = _spec_ev.get("approved_modules")
            if isinstance(_a, str):
                _approved_blobs = {_a}
            elif _a:
                _approved_blobs = set(_a)
        # The live registry's approvals are unioned in, because without them this check and
        # V16c ask the same question of different registries and no record can satisfy both.
        #
        # Measured 2026-09-27, the third time this pair has been unsatisfiable on the same
        # step. At `guards@8192e54`:
        #
        #     V16c, at append, reads `config.required`  -> approves only 7dbd4741 (today's)
        #     this check, at read, read `pin_types`     -> approved only b6e81935 (the ref's)
        #
        # so citing the ref's blob was refused at append, and citing today's approved blob
        # appended and never cleared. The consuming project wrote three correctly shaped
        # records against two successive wrong diagnoses on this side before the actual
        # decision was traced, which named the values above in one line.
        #
        # Neither half was wrong alone, which is why it survived two fixes. Per-ref at read is
        # a design decision of 2026-09-13 (option C, see `registry_types_at`) and it measured
        # better: judged against today's registry instead, 13/20 of the pushed arc and 86/93 of
        # the last 93 commits went stale, against 3/20 and 54/93 per ref. Live at append is
        # defensible on its own terms: a new verdict should not come from a build nobody
        # currently approves. The 2026-09-12 fix above made an approved blob count as fresh and
        # worked while both sides read one registry; the 09-13 per-ref decision reopened the gap
        # from the other direction, and nobody checked the interaction because that decision
        # was argued on staleness rates.
        #
        # The union is the smallest change that makes the pair satisfiable: a citation approved
        # by the registry that governed the content when it was committed, or by the registry
        # governing it now, is approved by a registry with standing over it either way. A record
        # citing today's build passes V16c and then clears here.
        #
        # It does not reopen the reverted-checker case `registry_types_at` documents, checked
        # rather than assumed: `guards.py@2775fcf6` after the 548b1216 unpin is approved by
        # neither registry, so the union still excludes it and a commit reverting to that blob
        # still reads stale. The union admits only blobs some registry with standing actually
        # approved.
        _live_spec = (config.required.get("types") or {}).get(step) or {}
        _live_a = _live_spec.get("approved_modules")
        if isinstance(_live_a, str):
            _approved_blobs |= {_live_a}
        elif _live_a:
            _approved_blobs |= set(_live_a)

        ev_stale, ev_moved, ev_unapproved = 0, [], []
        for path in sorted(ev_set):
            if path not in files:
                continue
            # The at-ref route is closed to a pinned module whose blob here is not approved.
            # In the reverted-checker case (see `registry_types_at`), records citing
            # guards.py@2775fcf6 freshened a commit that reverted to it after the unpin,
            # because this route asks only whether some record cited the producer blob found
            # at this ref. Where the registry pins the module, a blob it does not approve
            # cannot be fresh evidence however many records cite it, which is the rule V16c
            # already applies at append.
            if (pin_checked and _approved_blobs and path == _pinned_module
                    and files[path] not in _approved_blobs):
                ev_unapproved.append(path)
            elif (step, path, files[path]) in ev_content:
                continue
            # Approved-and-cited counts as fresh only where the citing record examined these
            # bytes. Every subject this row covers must have been judged by a record that
            # cites an approved build of this producer.
            #
            # Until 2026-09-13 this asked whether any record cited an approved build, about
            # any subjects at all. Measured on the consuming project at 929a9f89, simulating
            # a pin of pdf_coupling to batch.py 1fffe944: the records citing it covered 38 of
            # the commit's 40 PDFs. The other 2 had only ever been judged by older builds, and
            # the row still read fresh. The pinned producer was real and it was cited: a true
            # value read against the wrong subjects. The maintainer chose to tighten it before
            # that pin landed.
            #
            # Tightened for the approved route only, as decided. The at-ref check above is
            # still global and has the same shape; that is a separate decision.
            #
            # And not vacuously. A row covering nothing has no subject an approved build could
            # have judged, so `all()` over an empty list must not earn the exemption.
            _covered_paths = [_p for _p, _r in covered_recs]
            if _approved_blobs and _covered_paths and all(
                    any((path, _b) in ev_by_subject.get((step, _p, files[_p]), ())
                        for _b in _approved_blobs)
                    for _p in _covered_paths):
                continue
            ev_stale += 1
            ev_moved.append(path)

        record = covered_rec or stale_rec
        legacy_hit = next((legacy_tips[(step, p)] for p in files
                           if (step, p) in legacy_tips), None)

        why = None
        if covered == 0 and stale == 0 and legacy_hit is not None:
            # Not stale, and not missing. The step did examine this path; the record
            # is simply unusable, and the remedy is to re-record rather than to re-run
            # or to run at all.
            status = "LEGACY_IDENTITY"
            record = legacy_hit[0]
            why = ("recorded under the superseded `sha256` subject scheme and cannot be "
                   "compared to a git blob id; re-record it (or let it age out)")
        elif covered == 0 and stale == 0 and (refusals or {}).get(step):
            # A claim was attempted and not accepted, which is not the same fact as nothing
            # having been tried; until 2026-09-07 both rendered as MISSING.
            #
            # It is not `FAIL` and must never be read as one. A FAIL condemns subjects; a
            # REFUSED condemns nothing, because it establishes nothing. So this row carries no
            # `indicted`, contributes nothing to any indictment set, and never reaches
            # tip-green forgiveness. The consuming project's framing, and it is the right one:
            # treating it as a FAIL would stamp condemnation on blobs the ledger never judged,
            # the examined-is-not-indicted defect (see `failing` above) arriving by a new route.
            #
            # And the remedy must not say "re-run the gate". Measured by the consuming project
            # before they branched on it: the generic fall-through already blocked, and already
            # said "run the gate and let it record its own verdict", the one instruction that
            # cannot work. The gate did run; the ledger declined its record; re-running
            # reproduces the refusal. A true blocking answer paired with a remedy for a
            # different failure.
            _r = (refusals or {})[step]
            status = "REFUSED"
            why = (f"the ledger REFUSED this claim ({_r.get('rule')}); NOTHING has been "
                   f"established about these subjects. This is a defect in the RECORD, not a "
                   f"finding about the corpus — do not simply re-run the gate, which would "
                   f"reproduce it. Refused {_r.get('count')} time(s), first "
                   f"{str(_r.get('first_seen'))[:19]}, last {str(_r.get('last_seen'))[:19]}. "
                   f"Fix the record the emitter sends, then record again.")
        elif covered == 0 and stale == 0:
            status = "MISSING"
            if unscoped:
                # The other half of the scope-denominator fix above. "Never ran" and
                # "ran, but everything it read is outside its declared scope" are
                # different facts, and only the second one is fixed by editing the
                # registry. Naming it here is what stops the operator re-running a
                # checker that cannot help.
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
            # A FAIL against other bytes demotes to STALE like any other verdict. It used
            # to stay FAIL permanently: the FAIL branch ran before this one, so a PASS
            # recorded against moved content was correctly demoted while a FAIL was not.
            # One probe FAIL therefore condemned every commit in the audit, and nothing
            # could clear it except a PASS on the exact sha. That is an audit that raises
            # a false alarm on every run, which trains a reader to ignore it, the precise
            # failure this system exists to prevent.
            #
            # This weakens no gate: `complete` already requires stale == 0 as well as
            # failed == 0, so the action is refused either way. It changes only what the
            # reader is told, from "it failed" to "it was never run on this".
            status = "STALE"
            if stale_rec is not None and stale_rec.get("verdict") in ("FAIL", "UNDECIDED"):
                why = (f"last verdict was {stale_rec['verdict']} but against different "
                       f"bytes ({stale_rec['id']}) -- it does not judge this content")
            # Subject staleness over paths this range does not touch is reported, not blocking.
            # A design decision (2026-09-18) on a measured case: six commits touching only
            # `tools/verify/` were blocked because `editorial` was STALE over one prose file that
            # they never touched, and that had entered editorial's scope that same morning.
            #
            # The asymmetry is the argument. At that moment `prior_art` carried 247 paths it had
            # never examined and `adversary` 24, and neither blocked anything, because
            # `coverage.require_complete` is false. One path examined once at older bytes
            # blocked six unrelated commits. Both states say the same thing about the bytes
            # being published: nobody has judged them. The only difference is whether the step
            # happened to look at an older version, which has no bearing on what ships. The
            # gate was blocking on the strictly less alarming of the two.
            #
            # The real risk is already covered. The changed-path ratchet refuses any path the
            # range changes that lacks a verdict at its new bytes, so a file cannot ship
            # unreviewed. With the ratchet in place, subject staleness over an untouched path is
            # a backlog artifact, and the backlog is accepted and ratcheted forward, which is
            # the whole model. That prose file was stale precisely because it moved before
            # editorial claimed it.
            #
            # Evidence staleness (the branch below) is unaffected and still blocks. That is a
            # different fact (the producer changed, so no subject is judged by a live checker)
            # and it is not scoped to paths in the range. Do not fold the two together.
            #
            # `changed is None` means the caller asked about a ref, not a range, so "did this
            # push touch it" has no answer. It keeps blocking: absence must not quietly weaken a
            # gate.
            # The set this branch must ask about is what the push publishes, not what one
            # commit touched. Split out 2026-09-21 (a design decision) after a reproduction:
            # `can_push` passed its per-commit diff here, so at the tip a path changed early in
            # the range and not re-touched by the tip commit read as "out of range" while the
            # push shipped exactly those bytes. `published` is the range's changed set at the
            # tip and the commit's own at every intermediate; see the long note at the call
            # site for the fail-open the mis-scoping composed into.
            #
            # It falls back to `changed`, not to "everything", so a caller that has not been
            # taught the distinction keeps the old, stricter-or-equal behaviour rather than
            # silently widening forgiveness. A new parameter must never loosen a gate for
            # callers that do not pass it.
            _publishes = changed if published is None else published
            if changed is not None and not (set(stale_paths) & set(_publishes)):
                r_stale_out_of_range = True
                why = (f"{why} ⚠ REPORTED, NOT BLOCKING: none of the {len(stale_paths)} stale "
                       f"path(s) are changed by this range, so this push publishes no bytes this "
                       f"step has left unjudged. The changed-path ratchet governs what this "
                       f"range DOES touch. Stale here: "
                       f"{', '.join(sorted(stale_paths)[:3])}"
                       f"{' …' if len(stale_paths) > 3 else ''}")
        elif ev_stale:
            # Every subject still matches; what changed is the code or the brief that
            # produced the verdict. Re-running is exactly the right remedy here, unlike the
            # unclearable out-of-scope case above, so the row says so plainly.
            status = "STALE"
            if ev_unapproved:
                why = (f"the producer at this ref is NOT APPROVED by the registry that applies "
                       f"({pin_basis}): "
                       f"{', '.join(u + '@' + files[u][:12] for u in ev_unapproved)}. Records "
                       f"citing that build do not count, whenever they were written. Approve "
                       f"the build in the same commit, or restore an approved one.")
            else:
                why = (f"every subject still matches, but the producer changed: "
                       f"{', '.join(ev_moved[:3])}"
                       f"{', …' if len(ev_moved) > 3 else ''} moved since this verdict was "
                       f"recorded. A verdict cannot outlive the code or brief that reached "
                       f"it — re-run the step.")
        else:
            status = "SATISFIED"

        # A SATISFIED row may be carrying findings. V18 lets a PASS hold `outstanding`
        # entries for the stop-with-ordinary-findings case: reviewed, ordinary findings
        # left, loop cap reached, proceed. The verdict admits, so `complete` is unaffected
        # by design (a design decision, 2026-08-26). But "nothing was found" and "things
        # were found and judged ordinary" are different facts, and a bare SATISFIED renders
        # them identically, the ambiguity this module exists to remove. The number rides on
        # the row and in the inventory, the way `subjects_unexamined` and `evidence_stale`
        # do.
        # And they must not vanish when the row stops being SATISFIED. This read
        # `... if status == "SATISFIED" else []`, so the moment a later commit moved one
        # subject the row went STALE and its findings rendered as `outstanding: 0`.
        # Measured 2026-08-30: editorial and adversary held 7 and 5 recorded findings and
        # `inventory` reported zero for both. Raised by the consuming project.
        #
        # It matters more under the ordinary loop cap than it did when V18 shipped. With the
        # cap, the gates record PASS-with-`outstanding` rather than FAIL, so `outstanding` is
        # now the primary carrier of every finding not being fixed before a push. Zeroing it
        # on staleness turns "reviewed, not certified clean" into "reviewed, findings lost",
        # silently, because 0 and 0 are the same bytes.
        #
        # So the findings come from the winning record whether it covers or is stale, and
        # `outstanding_stale` says which. A reader must be able to tell "no findings" from
        # "findings recorded against bytes that have since moved"; the second is still a
        # fact about the corpus, and it is the one a stale row was hiding.
        # The union across every covering record, not one of them. The first version read
        # `covered_rec`, which is `min(covered_recs, key=severity)`, and `covered_recs` holds
        # one entry per covered path. When every candidate is PASS the severity key ties, so
        # `min` returns whichever record happens to cover the alphabetically first path.
        # Measured 2026-08-30: adversary resolved to an older `039aa56f#2` carrying 11 findings
        # while `adversary@01418e4#0` carrying 7 (the round the caller was actually pushing)
        # contributed nothing. The count was right and the findings were the wrong ones.
        #
        # A step can have several records covering it at once, so `outstanding` sourced from
        # one of them means the field's value depends on a selection rule nothing states, and
        # a reader seeing `11` cannot tell it is not `11 of 27`. That is the same defect as the
        # zeroing, one layer out: a number that renders identically whether it is complete or
        # partial. The consuming project reported it as a measurement rather than a cause,
        # which is why it was actionable.
        #
        # Findings are additive facts about the corpus, so the union is the honest answer and
        # `outstanding_from` names which records contributed. Deduplicated by note, because the
        # same finding restated in a later round is one finding, not two; an inflated count is
        # as misleading as a truncated one.
        # `covered_recs` holds (path, record) pairs since the indictment narrowing above,
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
                     # A STALE row whose stale paths are all outside this range. Still
                     # STALE (the step has not judged those bytes), but it does not refuse
                     # this push. See the subject-staleness branch above.
                     "stale_out_of_range": r_stale_out_of_range,
                     "stale_paths": sorted(stale_paths),
                     "record_id": (record or {}).get("id"),
                     # The bytes condemned, so "is it fixed?" is answerable without
                     # re-running a checker that cannot clear an honest FAIL. Empty on every
                     # non-failing row. See the tip-green bar in `canpush`.
                     "indicted": indicted,
                     # Narrowed-clean is not the same fact as clean, and until this line
                     # existed a reader could not tell them apart. A row that says SATISFIED
                     # because the covering record indicted other paths has been judged by a
                     # verdict that blocks somewhere; a row that says SATISFIED because the
                     # verdict was a PASS has not. Both rendered identically.
                     #
                     # `canpush` already refuses that collapse one level up ("whether the
                     # range was clean or merely forgiven is the exact collapse this gate
                     # exists to prevent"), and forgiveness is narrowing applied to a commit.
                     # The provenance was surfaced for the outer case and dropped for the
                     # inner one, so the same argument reached only half its subject.
                     #
                     # Carries the original verdict, not a boolean: narrowed from FAIL means
                     # "condemned elsewhere", narrowed from UNDECIDED means "disputed
                     # elsewhere", and those are different things to go and read.
                     "narrowed_from": (record or {}).get("_narrowed_from"),
                     "dead_patterns": dead,
                     # `covered` is measured over scope plus switches, so reporting it
                     # against `scope` alone made `covered > scope`: 22/21 for
                     # check_checkers, 43/42 for check_hashes, each inflated by its one
                     # switch file. The same shape the consuming project caught on
                     # evidence, arriving through the other member of the denominator.
                     # `judged` is the number `covered` is actually out of.
                     "judged": len(judged),
                     "outstanding": len(outstanding),
                     # Never report a count without its currency. Findings carried by a
                     # STALE record are about bytes that have moved; they are still findings,
                     # and a reader who cannot tell will either act on stale ones or ignore
                     # live ones. Same reason `evidence_stale` sits beside `subjects_stale`.
                     "outstanding_stale": bool(outstanding) and status != "SATISFIED",
                     # Provenance travels with the count. Without it a reader cannot tell
                     # `11` from `11 of 27`, which is the ambiguity this row exists to
                     # remove; the same argument put `outstanding_stale` beside the number.
                     "outstanding_from": _out_from,
                     "outstanding_notes": [o.get("note") for o in outstanding
                                           if isinstance(o, dict)][:5],
                     "subjects_covered": covered, "subjects_stale": stale,
                     "evidence_stale": ev_stale, "evidence_moved": ev_moved,
                     "evidence_unapproved": ev_unapproved,
                     "subjects_unexamined": unexamined, "scope": len(scope),
                     "subjects_unscoped": unscoped,
                     "why": why,
                     # What a caller must actually run, answered here so no consumer
                     # builds a second staleness predicate. Stated as a negative on
                     # purpose: re-run unless the step is fully covered at this tree or
                     # does not apply. A positive list would have to enumerate every
                     # not-covered state, and the one it missed (SATISFIED but narrow)
                     # is exactly the gap measured on 2026-08-23, where adding a file
                     # left a row green while the new path went unexamined.
                     "needs_rerun": not (status == "NOT_APPLICABLE"
                                         or (status == "SATISFIED" and unexamined == 0)),
                     "rerun_reason": (
                         None if status == "NOT_APPLICABLE"
                         or (status == "SATISFIED" and unexamined == 0)
                         else (f"{unexamined} in-scope path(s) never examined"
                               if status == "SATISFIED" else status.lower()))})

    # Pins that no longer match the tree, disclosed before the step next records, not at the
    # moment it is refused. Added 2026-09-07 on the consuming project's measurement:
    # `check_checkers` had been pinned to a superseded build since `acbe1c7` and nothing
    # noticed, because it is not in the five-checker precommit suite, so no run attempted
    # its record until push.
    #
    # Their phrasing is the general form: a pin's enforcement point and a pin's staleness
    # are different events, and the gap between them is however long it takes that step to
    # next record. V16c is enforced at append (correctly, since that is where a verdict is
    # claimed), so a pin can sit stale for days on a step that records rarely, and the first
    # sign is a refused commit. This makes the interval visible instead.
    #
    # It is disclosure, never a gate. A stale pin refuses at append and that is where the
    # refusal belongs; reporting it here would be a second enforcement point disagreeing with
    # the first. `unpinned_modules` on `policy()` is the same shape for the same reason:
    # absence disclosed is not absence defaulted.
    stale_pins = []
    for _step, _spec in sorted((config.required.get("types") or {}).items()):
        if not isinstance(_spec, dict):
            continue
        _mod, _approved = _spec.get("module"), _spec.get("approved_modules")
        if not _mod or not _approved:
            continue
        _live = files.get(_mod)
        if _live is None:
            continue          # not in this tree; V16/V17 own that, not this
        if _live not in ([_approved] if isinstance(_approved, str) else list(_approved)):
            stale_pins.append({
                "step": _step, "module": _mod, "live": _live,
                "approved": [_approved] if isinstance(_approved, str) else list(_approved),
                "consequence": ("this step CANNOT record until the registry approves the "
                                "current build — V16c refuses it at append. Nothing has gone "
                                "wrong yet; this is the interval before it does."),
            })

    # Circular gates: a step that grades its own producer. Added 2026-09-08 after the
    # maintainer called the fifth consecutive round on one blob "a failure of the gate itself"
    # that "should not have been possible."
    #
    # The shape. Two rules, each correct alone. (1) A verdict goes STALE when the code or
    # brief that produced it moves: a verdict cannot outlive its producer. (2) A step's scope
    # says what it must examine. When a step's own producer sits inside its own scope, editing
    # that producer does two things at once: it changes a subject the step owes a verdict for,
    # and it invalidates the step as producer of every verdict it has ever reached. If the step
    # is also admitted for the action that would carry the fix, the fix cannot land while the
    # finding it fixes is what blocks it. Measured on `adversary`: nine FAIL in ten rounds, the
    # last two on identical subject counts, unmoved.
    #
    # It must read both producer routes or it reports the smaller number. Mechanical steps
    # declare their producer in the registry (`module`); agent steps declare it in the record
    # (`evidence`). Measured 2026-09-08: the registry route alone returns 3 and misses
    # `adversary` and `editorial` entirely, the two that motivated the check. The union is 5.
    # A detector that reads one route is a detector that certifies the other route clean.
    #
    # Disclosure, never a gate: the same rule as `stale_pins` above. A gate that refuses
    # because a gate is circular is one more thing that can deadlock, and the remedy is a
    # policy choice (pin the producer, or narrow the scope) that belongs to the admission set
    # and to the maintainer, not to a row status invented here.
    _latest_evidence = {}
    for _rec in records:
        _s = _rec.get("step")
        if _s and _rec.get("evidence"):
            _latest_evidence[_s] = {e.get("path") for e in _rec["evidence"] if e.get("path")}
    circular_gates = []
    #
    # Two measured traps, both hit while building this, both caught by the negative test.
    # (1) Read scope from `reqs`, not from the raw registry. `_scope_paths` above is built
    #     from `config.requirements(action)`, and `requirements()` discards a narrowing that
    #     carries no `reason`. The raw registry therefore shows a scope that the resolved
    #     requirement does not have, and intersecting one against the other compares two
    #     different questions. The first draft did exactly that.
    # (2) A step that declares no scope is not in scope for everything here. The scope
    #     resolver treats empty globs as "every path" (`not globs or ...`), which is right
    #     for coverage and wrong for this: it makes every unscoped step's producer trivially
    #     self-graded, and the disclosure fills with steps that have no scope problem at all.
    #     An undeclared scope is a different finding, and `unscoped` already reports it.
    _raw_types = (config.required.get("types") or {})
    for _step, _spec in sorted(reqs.items()):
        if not _spec.get("required"):
            continue
        if not (_spec.get("scope") or _spec.get("when")):
            continue          # no declared scope; see trap (2) above
        _own_scope = set(_scope_paths.get(_step) or ())
        if not _own_scope:
            continue          # nothing in scope in this tree; nothing to be circular about
        _producers = set()
        _module = _spec.get("module") or (_raw_types.get(_step) or {}).get("module")
        if _module:
            _producers.add(_module)
        _producers |= _latest_evidence.get(_step, set())
        _self_graded = sorted(_producers & _own_scope)
        if not _self_graded:
            continue
        circular_gates.append({
            "step": _step,
            "producers_in_own_scope": _self_graded,
            "route": sorted({("registry" if p == _module else "evidence")
                             for p in _self_graded}),
            "admitted": admission is not None and _step in set(admission),
            "consequence": ("editing this producer changes a subject this step must pass AND "
                            "stales every verdict it produced. Blocking only where the step is "
                            "also admitted for this action."),
        })

    # A step recording a verdict over a path outside its own declared scope.
    #
    # The gap this names. Twenty-two validation rules, V1 through V21, and not one compares
    # a record's `subjects` against the step's declared scope. `V8` refuses an unregistered
    # step and says nothing about subjects, so a registered step may record a PASS over any
    # path in the tree and the ledger accepts it. Confirmed 2026-09-09 by reading every rule,
    # after a probe was refused on V15/V16c/V1 first and answered a different question than
    # the one asked.
    #
    # It is not the same defect as the one the consuming project reported, which is why it
    # needed its own field. They reported "6 of 16 changed paths fall outside every admitted
    # review step's scope". That is under-coverage (paths nobody covers), and `witness` on
    # `can_push` already reports it. This is the mirror image: over-claim, a step reaching
    # outside its scope. The two point in opposite directions and only this one is invisible.
    #
    # The two are not independent, and that is why this matters. Over-claim is the mechanism
    # by which under-coverage hides: if a step may name subjects outside its scope and nothing
    # refuses it, coverage counts can be inflated by records never entitled to those paths,
    # and the inflated number looks better, which is the direction nobody re-runs. A green
    # `19/19` is only as good as the subject lists behind it.
    #
    # Disclosure, never a gate: deliberately, and a decision by the maintainer (2026-09-09).
    # The fix would be a new refusal rejecting records the ledger accepts today, which is a
    # coordinated change exactly like `isError`: landing it unilaterally turns a working
    # pipeline into a blocked one at a moment nobody chose. `undeclared_producers`,
    # `loop_breaks_expired`, `coverage_unbarred`, `stale_pins` and `circular_gates` all
    # started as disclosures for the same reason.
    #
    # Traps. The first two are `circular_gates`' and are documented above; the later ones
    # are this field's alone and would have made it report wrongly.
    # (1) Scope from `reqs`, not the raw registry: `requirements()` discards a narrowing
    #     with no `reason`, so the registry shows a scope the resolved requirement lacks.
    # (2) A step declaring no scope is skipped. It has no boundary, so it cannot reach
    #     outside one. `unscoped` already reports that as its own finding.
    # (3) Match against the globs, never against `_scope_paths`. `_scope_paths` is the
    #     globs intersected with this tree, so a subject naming a path that has since been
    #     deleted is absent from it while having been perfectly in scope when recorded.
    #     Testing membership there would report every deleted file as an out-of-scope
    #     claim: a true value read against the wrong object, in the field written to catch
    #     exactly that. `evidence_moved` is where a moved subject belongs.
    # (4) Exclude declared `switches`, because V15 requires them as subjects and they are
    #     deliberately outside the content scope. V15 (validate.py): "step X declares
    #     switches Y that are not among its subjects. A verdict that depends on an exemption
    #     list must NAME it, or editing that list cannot make the key stale and a suppression
    #     lands unverified." So a baseline or whitelist is mandated in `subjects` and will never
    #     match the scope globs.
    #     Measured on the first live run, before this exclusion: ten steps reported, and
    #     `check_checkers`, `check_classes` and `check_hashes` were explained entirely by
    #     their own declared switches: three phantom steps and 320 phantom records, all of
    #     them a control doing exactly what another control demands. Shipping that would
    #     have sent the consumer chasing compliance with V15 as though it were a defect.
    #     This trap has the same shape as the first three: the path really is outside the
    #     globs, and "outside the globs" is not what the field claims to mean.
    _raw_types_s2 = (config.required.get("types") or {})
    # Commit-invariant, and a range walk used to recompute it once per commit. This loop reads
    # only `reqs` (derived from config + action), `records`, and `admission`, nothing about
    # the commit being judged. Across a 43-commit range there are exactly two distinct
    # answers, one for the tip (`push`) and one for the intermediates (`commit`), and it was
    # computing 43. Measured 2026-09-22: `fnmatch` was called 44.6 million times in one range
    # walk, 228 s of a 675 s profiled run, with 89M of those calls spent inside Windows'
    # `ntpath.normcase` -> `LCMapStringEx`. Nearly all of it was the same subject paths being
    # re-tested against the same globs.
    #
    # The key carries both variables, not just the action. `admitted` is stamped on every
    # row this loop emits, so two calls sharing an action but differing in admission are not
    # interchangeable. Keying on action alone would serve one call's rows to another: a
    # cache returning a true value computed against the wrong object, which is the defect
    # class this module exists to remove.
    #
    # The loop body is unchanged. On a hit the iterable is empty and the loop simply does
    # not run, rather than the body being re-indented under a conditional. This is
    # deliberate, so that a before/after comparison of this function's output is a real
    # check and not a reading of two differently shaped blocks.
    _audit_key = (action, tuple(sorted(admission or ())))
    _cached_audit = None if scope_audit is None else scope_audit.get(_audit_key)
    subjects_outside_scope = []
    for _step, _spec in (() if _cached_audit is not None else sorted(reqs.items())):
        _when = _spec.get("when")
        _globs = _spec.get("scope") or ([_when] if _when else [])
        if not _globs:
            continue          # no declared scope; see trap (2)
        _drop = _spec.get("scope_exclude") or []
        # trap (4): V15 mandates these as subjects; they are not an over-claim.
        _switches = set(_spec.get("switches") or ())
        _outside, _record_ids = {}, []
        for _rec in records:
            if _rec.get("step") != _step:
                continue
            _bad = sorted({
                _sub.get("path") for _sub in (_rec.get("subjects") or [])
                if _sub.get("path")
                and _sub["path"] not in _switches
                and (not any(_fnmatch_memo(_sub["path"], _g) for _g in _globs)
                     or any(_fnmatch_memo(_sub["path"], _g) for _g in _drop))
            })
            if _bad:
                _record_ids.append(_rec.get("id"))
                for _p in _bad:
                    _outside[_p] = _outside.get(_p, 0) + 1
        if not _outside:
            continue
        # Aggregated by step, not by record, so the field is bounded by the registry
        # (tens) rather than by the stream (thousands). The per-path list is capped and
        # the cap is disclosed: a silently truncated list reads as "that was all of them",
        # which is the defect this field exists to surface.
        _paths = sorted(_outside, key=lambda p: (-_outside[p], p))
        subjects_outside_scope.append({
            "step": _step,
            "paths": _paths[:10],
            "paths_total": len(_paths),
            "paths_omitted": max(0, len(_paths) - 10),
            "records_affected": len(_record_ids),
            "example_record": _record_ids[0] if _record_ids else None,
            "declared_scope": list(_globs),
            "admitted": admission is not None and _step in set(admission),
            "consequence": ("this step recorded a verdict over a path outside its declared "
                            "scope. Nothing refuses that today, so any coverage count "
                            "including these subjects is inflated in the direction that "
                            "does not get re-run. REPORTED, NEVER BLOCKING."),
        })

    # Store or restore; an absent cache still computes, never "assume none found".
    if _cached_audit is not None:
        subjects_outside_scope = _cached_audit
    elif scope_audit is not None:
        scope_audit[_audit_key] = subjects_outside_scope

    # Only admitted types decide `complete`. Everything else is reported so the
    # caller can see it, and so a promotion gap is visible rather than silent.
    admitted = None if admission is None else set(admission)
    for r in rows:
        r["gating"] = (admitted is not None and r["step"] in admitted
                       and r["status"] != "NOT_APPLICABLE")

    gating = [r for r in rows if r["gating"]]

    def n(status):
        return sum(1 for r in gating if r["status"] == status)

    def n_blocking_stale():
        """STALE rows that actually refuse this range.

        A STALE row whose stale paths are untouched by the range is reported and does not
        block (a design decision, 2026-09-18; the reasoning is at the subject-staleness
        branch). It still counts as STALE everywhere a reader looks; only `complete` changes.
        A row that vanished from the stale list would hide the backlog instead of
        grandfathering it.
        """
        return sum(1 for r in gating
                   if r["status"] == "STALE" and not r.get("stale_out_of_range"))

    required = len(gating)
    satisfied = n("SATISFIED")
    registered_not_admitting = sorted(
        r["step"] for r in rows
        if not r["gating"] and r["status"] != "NOT_APPLICABLE")

    if admitted is None:
        # Not the same as an empty admission set. "Nobody said what gates this" must
        # never render as "everything is fine"; that is the fail-open shape this
        # system exists to end.
        state = "UNSET"
        complete = False
    elif not admitted:
        # Legitimate on day one, when no checker emits yet, but it must be loudly
        # reported, or "the gate is on" gets believed while it gates nothing.
        state = "EMPTY"
        complete = True
    else:
        state = "SET"
        # `REFUSED` was missing from this list, and that is the other half of the 2026-09-18
        # fail-open. The status was added 2026-09-07 with a correct render ("NOTHING has been
        # established about these subjects") and never wired into completeness, so it described
        # a blocked state while gating nothing. A row that says nothing was established, sitting
        # inside a `complete: true`, is the precise shape this module exists to remove.
        #
        # It belongs here by the same argument as `MISSING`. A claim the ledger declined
        # establishes exactly as much as a claim nobody made; less, in fact, because someone
        # tried and the attempt is on record. Reading it as satisfied is "absence renders as
        # success" with an extra step.
        #
        # It is bounded because the refusal now ends. `Ledger.append` retires a step's sidecar
        # entry on any accepted record, so this can block without permanently stalling: fix the
        # emitter, record, and the row clears. Before that existed, adding REFUSED here would
        # have been a permanent block, which is why the 2026-09-13 decision not to consult the
        # sidecar at all was right at the time.
        complete = (n("MISSING") == 0 and n_blocking_stale() == 0
                    and n("UNDECIDED") == 0 and n("FAIL") == 0
                    and n("LEGACY_IDENTITY") == 0 and n("REFUSED") == 0)
        # Coverage binds only when policy says so. Until 2026-08-25 an in-scope path a step
        # had never examined was counted and not enforced, so a row could read SATISFIED
        # over a fraction of its own scope. `guards`: 4 of 504, green.
        if config.coverage_complete_required:
            short = [r["step"] for r in gating if r["subjects_unexamined"]]
            if short:
                complete = False

        # And the per-step bar, which binds whether or not the global switch is on.
        # `coverage.require_complete` is one switch for every step at once, and neither
        # position is the answer: `false` leaves 823 in-scope paths under green rows
        # (measured 2026-09-07, 9 gating steps), `true` blocks essentially everything until
        # a full sweep runs. The spread is why: `check_classes` sits at 220/220 and could be
        # barred at 1.0 today at no cost, `check_pov` at 305/522 plainly cannot.
        #
        # So a step may declare `min_coverage` and be held to it alone. That turns one switch
        # into a ratchet: bar the steps that are already complete, and advance as sweeps land.
        # An absent bar is disclosed on `policy()` as `coverage_unbarred`, never silent;
        # requiring every step to declare one would block the whole corpus the day it shipped.
        # The bar prices what this commit changed, not the whole scope. Corrected 2026-09-07,
        # hours after shipping the wrong version, after the maintainer raised the concern of
        # an unrelated file entering a continually growing scope and blocking work.
        #
        # The concern was confirmed by measurement. Barred against the whole scope, a step at
        # 1.0 broke the moment anyone added a file matching its glob:
        #
        #     check_prose 1.0, scope *.md, record covers a.md
        #       {a.md}                      SATISFIED    1/1
        #       {a.md, unrelated.md}        UNVALIDATED  1/2   <- nobody touched a.md
        #
        # A green row earned honestly went red because the denominator grew without anyone
        # deciding it should. That is the convergence-freeze defect one field over: "8 of 12
        # green steps had earned their green under a registry that no longer existed."
        #
        # So the bar asks: did you examine the in-scope paths this commit changed? A
        # file someone adds later cannot retroactively break a row you earned; a file you add
        # into a barred step's scope must be examined in the same push. Incremental and
        # ratcheting, which is the only way a bar can be adopted one step at a time.
        #
        # `changed is None` means the caller asked about a ref, not a range, so "what did you
        # change" has no answer there. The bar is not evaluated and the row says so, rather
        # than passing silently. Absence renders as unknown, not as pass.
        bars = config.min_coverage
        if bars:
            under = []
            for r in gating:
                bar = bars.get(r["step"])
                if bar is None:
                    continue
                r["bar"] = bar
                if changed is None:
                    r["bar_evaluated"] = False
                    r["bar_note"] = ("declared, NOT evaluated: this answer is about a ref, and "
                                     "the bar prices the paths a RANGE changed. can_push "
                                     "evaluates it.")
                    continue
                in_scope_changed = _scope_paths.get(r["step"], set()) & changed
                r["bar_evaluated"] = True
                if not in_scope_changed:
                    continue          # this commit touched nothing this step owns
                unex = _unexamined_paths.get(r["step"], set())
                missed = sorted(in_scope_changed & unex)
                seen = len(in_scope_changed) - len(missed)
                if (seen / len(in_scope_changed)) < bar:
                    under.append(r["step"])
                    r["status"] = "UNVALIDATED"
                    r["why"] = (
                        f"this commit changed {len(in_scope_changed)} path(s) in this step's "
                        f"scope and it examined {seen} of them, below the {bar:.0%} bar the "
                        f"step declares. Unexamined: {missed[:3]}"
                        f"{' …' if len(missed) > 3 else ''}. Not a finding about the corpus — "
                        f"what it DID examine passed. Run it over the changed paths.")
            if under:
                complete = False

    return {
        "ref": ref, "action": action,
        # Which registry judged the producer pins, so "fresh" can be traced to a file and a
        # blob. `unchecked` means no repository was given and the read-time check did not run.
        "pin_basis": pin_basis,
        "admission_state": state,
        "admitted": sorted(admitted) if admitted is not None else None,
        "required": required, "satisfied": satisfied,
        "unexamined": sum(r["subjects_unexamined"] for r in rows
                          if r.get("gating") and r.get("subjects_unexamined")),
        # All rows, not just gating ones: an undeclared switch on a type nothing
        # currently admits is still an undeclared switch, and promoting that type later
        # would inherit the gap silently.
        "unscoped": sorted({p for r in rows for p in (r.get("subjects_unscoped") or [])}),
        # All rows, gating or not, and reported rather than blocking. A dead pattern on a
        # type nothing currently admits is still a gate that can never fire, and
        # promoting that type later would inherit the gap silently.
        #
        # Making it block would refuse every push until every such glob is fixed, and
        # that is the maintainer's decision rather than a side effect of a detector
        # landing: the same line `subjects_unexamined` draws. But a gate that cannot
        # fire is not a quiet fact, so it is on the row, in the `why` where the
        # misleading sentence used to be, and here.
        "dead_patterns": [d for r in rows for d in (r.get("dead_patterns") or [])],
        # All registered steps, not just gating ones. Deciding what to run is a different
        # question from what gates: a hook has emitters for types that may not be
        # admitted, and must not be told to skip them just because nothing currently
        # gates on them.
        "needs_rerun": sorted(r["step"] for r in rows if r["needs_rerun"]),
        "missing": n("MISSING"), "stale": n("STALE"),
        "evidence_moved": sorted({p for r in rows
                                  for p in (r.get("evidence_moved") or [])}),
        # Across all rows: a step admitted while carrying findings is a fact about
        # the action as a whole, not a detail of one row.
        "outstanding": sum(r.get("outstanding") or 0 for r in rows),
        "legacy_identity": n("LEGACY_IDENTITY"),
        "undecided": n("UNDECIDED"), "failed": n("FAIL"),
        "not_applicable": sum(1 for r in rows if r["status"] == "NOT_APPLICABLE"),
        # gitRobot's rule is that these are all zero. The ledger computes; the
        # consumer requires. Re-deriving completeness on the other side would be
        # the mirror defect in the highest-stakes possible location.
        "complete": complete,
        "registered_not_admitting": registered_not_admitting,
        # Placed beside `complete`, and that placement is the point. `complete: true` is a
        # claim about a scope; if the registry moved since the run was frozen, it is true
        # about a different one than the reader assumes. gitRobot's status() embeds this
        # block, so a broken bar reached nobody until it was carried here.
        "bar": convergence_bar(config),
        # Reported, never gating; see the block that computes it. The refusal lives at
        # append, where the claim is made; this is the interval before it fires.
        "stale_pins": stale_pins,
        "circular_gates": circular_gates,
        "subjects_outside_scope": subjects_outside_scope,
        "how_breakdown": how_counts,
        "rows": rows,
    }


def _gap_remedy(name: str, applies: int, missing: list, records, files: dict) -> str:
    """What to do about this step's gap, and never advice that would waste the attempt.

    The defect this replaces, measured 2026-09-09 and reported by the consuming project.
    The condition was `any(r["step"] == name and r["verdict"] == "FAIL" for r in records)`:
    any FAIL anywhere in the stream, ever, with no test that it was about the bytes in
    hand. So a step whose row status is `LEGACY_IDENTITY` was told "fix the findings, so
    re-running changes nothing" on the strength of a FAIL from some earlier tree.

    It also contradicted the other tool at the same ref. `inventory` said of `build`:
    "recorded under the superseded sha256 subject scheme; re-record it (or let it age
    out)". `coverage_gap` said re-running changes nothing. Two tools, one step, one ref,
    opposite instructions, and the wrong one told the caller not to do the single thing
    that would clear it. Measured at tag scope: `build`, 524 applies, 0 have, gating.

    The test is whether the FAIL is live at this content. A FAIL indicts bytes. If every
    subject it names has since moved, it is not the reason this step has no PASS today, and
    "re-running changes nothing" is false. This is the same error as taking `records[-1]`
    for the deciding record: a real FAIL, read against the wrong tree.

    Deliberately not reusing the row status, which `coverage_gap` does not build. The
    honest local test is the one the status itself is derived from: does a FAIL name a
    subject at a blob this tree still has.
    """
    if not missing:
        return "nothing owed"
    covers_whole_scope = bool(applies) and len(missing) == applies
    if covers_whole_scope:
        for r in records:
            if r.get("step") != name or r.get("verdict") != "FAIL":
                continue
            for sub in (r.get("subjects") or []):
                path, blob = sub.get("path"), sub.get("git_blob_id")
                if blob and path and files.get(path) == blob:
                    return ("fix the findings — this step covers its scope and passes "
                            "none of it, so re-running changes nothing")
    return "run the step over the listed paths and record"


def coverage_gap(*, config, records, action: str, files: dict,
                 admission: list, step: Optional[str] = None,
                 limit: int = 200) -> dict:
    """The work order: which paths does each step still owe a PASS at this content?

    A tool rather than a generated list, and that is the whole point. The maintainer
    asked on 2026-08-25 for every file at HEAD to be reanalysed, excluding only those
    with a complete passing set. The obvious answer was to compute the 503 paths once
    and hand them over as a file, which would be wrong within minutes of the sweep
    starting and would be a second copy of a fact the ledger already holds. Second
    copies drift; ask the question again instead.

    A different question from `coverage()`. That one asks "has any step ever named
    this path?", a floor, useful on day one. This asks, per step, "is there a passing
    verdict over the bytes that are here now?" A path examined last week by a step
    that has since gone stale counts for `coverage()` and is missing here.

    Passing only. A step whose record covers a path but failed has not discharged it,
    and listing it as covered would report work as done that must still be fixed.
    Measured 2026-08-25: `editorial`, `adversary` and `rely` cover their whole scope
    and pass none of it: 0 have, and the remedy is to fix findings, not to re-run.
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
        # The sibling of `build`'s scope, and it kept the old behaviour for an hour after
        # `build` was fixed. 2026-09-20: session state was excluded from `build`, which then read
        # `check_encoding` SATISFIED at scope 481, while this function still answered
        # `missing: 1 of 482, paths: ["gate_round.json"], remedy: "run the step over the listed
        # paths and record"`. The two surfaces disagreed, and the one a caller reads to learn
        # what to record is the one that named a path nobody is permitted to record.
        #
        # Found by enumeration, not by a sweep, applying a rule from a peer review: after a
        # correction, ask what sibling set the fixed member belongs to. Fourteen `fnmatch`
        # sites decide scope across two modules; the exclusion had reached two. A grep for
        # `session_state` finds the sites that have it, which is the exact inverse of the
        # question.
        session_state = config.session_state_paths
        applies, missing = 0, []
        for path, blob in sorted(files.items()):
            if path in session_state:
                continue                      # unrecordable by construction; see `build`
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
            # Truncation is reported. A capped list that renders like a complete one is
            # the failure this server exists to end.
            "paths": missing[:limit],
            "truncated": max(0, len(missing) - limit),
            "remedy": _gap_remedy(name, applies, missing, records, files),
        })
    return {"action": action, "steps": out,
            "total_missing": sum(s["missing"] for s in out),
            "complete_steps": sorted(s["step"] for s in out if not s["missing"]),
            "tracked": len(files)}


def progress(*, config, records, action: str, files: dict, admission: list,
             rounds: int = 8, repo: Optional[str] = None) -> dict:
    """One view: what blocks the push, and is it converging?

    A design requirement (2026-08-29): guard against a review loop that makes no real
    progress, by tracking progress toward convergence from a single viewpoint.

    `inventory` answers "is it green now" and `coverage_gap` answers "which paths owe
    a PASS". Neither answers "is this getting better", and that is the question a loop
    hides in: every round can look identical while the underlying numbers drift the
    wrong way, and nobody notices because each snapshot is read on its own.

    The bar must not move under the work, and this is where that is visible. Every
    record carries `run.config_sha`, the identity of the policy and registry it was
    judged under. A scope widened mid-convergence silently invalidates the reason a
    step went green, and the row keeps reading SATISFIED because coverage is keyed on
    content, not on the bar. `bar_drift` names every step whose passing records were
    earned under a different config than the one now in force. The same day's
    requirement: nothing unrelated may enter scope at a later point.

    `history` is per step, newest last, so a reader sees direction rather than a
    point. A review gate whose findings are not shrinking across rounds is the loop
    this exists to surface, and the honest signal is that its verdicts stay FAIL while
    its subject count does not move.
    """
    inv = build(config=config, records=records, action=action, files=files,
                admission=admission, repo=repo)
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
            # A blocking row must explain itself even when it owes nothing. Measured
            # 2026-08-29, cycle 1: `claim_review` read STALE / owes 0 / remedy "nothing
            # owed", three fields that look like a contradiction and are not. It was
            # stale on its evidence (the producer moved), and `coverage_gap` counts scope
            # paths only, so the work number is legitimately zero while the step is
            # legitimately blocked.
            #
            # Two correct numbers reading as a contradiction is the indicator problem the
            # maintainer had raised an hour earlier, arriving in the tool built to answer
            # it. The row now carries `why` from the inventory and states the real remedy.
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

    freeze = convergence_bar(config)

    return {
        "action": action, "complete": inv["complete"],
        "bar": freeze,
        "satisfied": len(converging),
        "gating": len(converging) + len(blocking),
        "config_sha": current_sha,
        # The whole point: what is left, with its direction attached.
        "blocking": blocking,
        "green": sorted(converging),
        # `bar_drift` was here and was deleted 40 minutes after it was written. It keyed
        # on `run.config_sha`, which covers policy.v1.json as well as the registry, so
        # the very act of recording this convergence freeze in the policy made it report
        # 19 of 19 steps drifted while the scope had not moved at all. A signal that
        # fires on every threshold tweak is one people scroll past, and it would have
        # been permanently red from the moment it shipped.
        #
        # `bar` above answers the same question properly, keyed on the registry sha
        # alone, which is where scope lives. Two mechanisms for one question, with the
        # weaker one noisier, is the two-copies defect. Kept as a comment rather than
        # deleted outright, because a rule removed for a reason is worth more on the page
        # than a gap someone re-derives.
        # The numbers, reconciled in one place. The maintainer noted on 2026-08-29 that
        # which indicator to use kept causing confusion.
        #
        # Measured the same day, same tree: five "how much is left" numbers across four
        # different denominators: 13/19 steps, 812 unexamined, 877 missing, 12
        # uncovered, 38 unscoped. Each was added to answer a real question and none
        # said how it related to the others, so a reader could not tell which to act on,
        # and 812 against 877 is the worst kind of disagreement, close enough to look
        # like one of them is a bug.
        #
        # They are not in conflict; they are nested, and nobody had ever written the
        # nesting down:
        #
        #   uncovered  ⊂  unexamined  ⊂  owes_a_pass
        #
        # `coverage.uncovered`  paths no step ever named. A day-one floor.
        # `unexamined`          (step, path) pairs where that step never examined the
        #                       path. Wider: a path can be covered by one step and
        #                       unexamined by another.
        # `owes_a_pass`         (step, path) pairs lacking a passing verdict at the
        #                       current content. Widest, and the only one that is
        #                       actually the work: it also counts paths a step did
        #                       examine, at bytes that have since moved or under a
        #                       verdict that failed.
        #
        # `owes_a_pass` is the work number. `satisfied/gating` is the gate number.
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
    """Tracked paths minus the union of every `subjects` entry ever recorded.

    On an empty stream this reports everything uncovered, never a clean bill of
    health. Day one is exactly when the stream is empty, and that is the fail-open
    shape this project has been hit by five times.
    """
    examined = {s.get("path") for r in records for s in (r.get("subjects") or [])}
    uncovered = sorted(p for p in paths if p not in examined)
    return {
        "tracked": len(paths), "examined": len(set(paths) & examined),
        "uncovered": len(uncovered), "paths": uncovered[:200],
        "note": ("nothing recorded — every tracked path is uncovered"
                 if not examined else None),
    }


def heal_plan(*, config, records, action: str, files: dict, admission: list,
              repo: Optional[str] = None) -> dict:
    """What to re-run to make this ref green, split by who can do it, and by whether
    re-running would help at all.

    A design request (2026-08-30): support self-healing wherever it can be implemented.
    This is the witness half of that, and deliberately only the witness half. The ledger
    says what is stale, why, and what would clear it. It does not run anything.

    The distinction this tool exists for: stale is healable, failed is not. A STALE
    verdict means the content (or the checker that judged it) moved, so the answer is simply
    unknown again; re-running produces a fresh answer and clears it. A FAILED verdict means
    the checker looked and found something; re-running finds it again. Conflating them is how
    you get a self-healing loop that spins indefinitely on a real finding, which is precisely
    the no-progress loop this project already built `progress()` to detect. So `auto` never
    contains a FAIL, and `blocked` says why in those words.

    The second split is `family`, which the registry already carries. A `mechanical` step
    is deterministic and cheap: measured 2026-08-30, the six that block an ordinary
    multi-commit push re-run in 16.1 s total. A `review` step needs an agent, judgement, and
    minutes to dollars of cost. Only the first can honestly be called self-healing; calling
    an agent round "automatic" is how a review becomes a rubber stamp.

    It names steps, not commands, and that is not an omission. The live registry carries no
    `module` for any of its 24 types (measured), so the ledger cannot name the invocation
    without inventing a second copy of something the domain repo already knows. The consumer
    knows how to run its own checkers; it just did not know which ones were owed.
    """
    inv = build(config=config, records=records, action=action, files=files,
                admission=admission, repo=repo)
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
            # why it is not green, because the two reasons have different remedies
            "subjects_stale": row.get("subjects_stale"),
            "evidence_stale": row.get("evidence_stale"),
            "evidence_moved": row.get("evidence_moved") or [],
            # Which paths, not just how many; the count was published without the identity
            # for as long as this field had existed. Added 2026-09-25 (a design decision by
            # the maintainer) after the count sent a caller into a heal that could not work
            # and then could not explain why.
            #
            # The count is the half that cannot discriminate, and that is measured. The
            # consumer healed a stale step from a worktree, recorded 418 subjects where 419
            # were needed, got exit 0 and a receipt reading `recorded PASS`, and the step
            # stayed STALE. They proposed refusing any record covering fewer in-scope paths
            # than exist at its basis, but across the live stream `check_figures` records
            # carry 365 to 428 subjects, with 417 the commonest value, seen 75 times. 418 sits
            # squarely inside the normal spread, so no threshold separates a reduced universe
            # from an ordinary partial run, and with `coverage.require_complete` false the
            # majority of records are partial by design.
            #
            # The identity discriminates where the count cannot. "419 needed, 418 recorded"
            # is unactionable; "the path still unjudged is `X`" is a diagnosis. It also answers
            # a question nobody could answer from the count: whether the misses are a real
            # coverage gap or an `applies_to` broader than the checker's target. Measured the
            # same day on `check_figures`: of its 109 never-examined paths, 40 are rendered
            # PDFs and 12 are `.ttf` fonts, plus CI workflows, `LICENSE` and `CNAME`. A
            # figures checker was never going to open a font.
            #
            # It is already computed; see `stale_paths` on the row above. The information
            # was in the same function and stopped one field short of the reader.
            "stale_paths": row.get("stale_paths") or [],
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
            # This parenthetical used to promise something no procedure can produce: "its
            # evidence moved, so the fresh record will cite the current checker". A checker
            # derives its repo from `__file__`, so it always reads the tree it lives in:
            # placing the current build in a worktree at an older ref makes it differ from
            # that ref, and running the worktree's own copy cites the old blob. It was not
            # merely false at an intermediate ref; it was unreachable by construction, for a
            # reason in the consumer's layer. Found in a peer review by the consuming project
            # 2026-09-11, after it cost them a blocked push and a wasted heal attempt.
            #
            # A remedy naming an unreachable success condition is the one thing the refusal
            # contract forbids outright: could a reader construct a passing next attempt from
            # this alone? There, no; every attempt led back to the same obstacle. It now says
            # where to run the checker, which is the part that was missing.
            # The caveat used to be conditional, and the common case got the bare string.
            # Corrected 2026-09-25. Everything below the `evidence_stale` clause fires only
            # when the producer moved; a subject-stale row with a current producer (the common
            # case) received exactly "re-running the checker at this basis and recording the
            # result", eleven words with no target and no warning.
            #
            # This code was also misread by its own author, which is why it is written out.
            # Asked whether this text sent a caller to a worktree, the author read the
            # assembled string, saw the warning, and reported that it points away from one,
            # without noticing the warning sits inside `if row.get("evidence_stale")`. The
            # consumer had acted on the other branch and was right, and was wrongly told they
            # were mistaken. A true value read against the wrong object: a branch quoted as if
            # it were the whole string. Two surfaces pointed at the worktree and only one had
            # been closed.
            #
            # Naming the paths is what makes the remedy constructible, which is the standard a
            # refusal is held to here: could a reader build a passing next attempt from this
            # alone? From "re-run at this basis", no: it does not say what is missing, so a run
            # that comes back short reads as success. From the paths, yes.
            _sp = row.get("stale_paths") or []
            entry["heals_by"] = (
                "re-running the checker at this basis and recording the result"
                + (f" — the path(s) still unjudged at this basis are: "
                   f"{', '.join(_sp[:6])}{f' … and {len(_sp) - 6} more' if len(_sp) > 6 else ''}. "
                   f"⚠ VERIFY THE RE-RUN COVERED THEM: a checker enumerates the tree it lives "
                   f"in, so a run from a reduced checkout can come back with FEWER subjects, "
                   f"exit 0, and leave this step stale. Compare the subjects recorded against "
                   f"the paths named here rather than trusting the exit code."
                   if _sp else "")
                + (" — its PRODUCER moved, so run the APPROVED build and let the record cite "
                   "that blob. A checker reads the tree it lives in, so this cannot be done "
                   "by re-running the copy sitting at this ref; a record citing an approved "
                   "producer is fresh no matter which ref it was read at."
                   if row.get("evidence_stale") else ""))
            auto.append(entry)

    # Name the failing steps that do not gate, or a caller chases one indefinitely.
    # Measured 2026-08-30: the consuming project read `rely` as blocking its push. It is FAIL
    # and it is registered, but `admission.v1.json` deliberately removed it from commit and
    # push: its scope is `tools/verify/*`, so every fix to the tooling stales it while it
    # gates the commit carrying that fix, and its declared 60-file scope contradicts its own
    # brief's "do not run it at full". Corrected 2026-09-09: that contradiction makes `rely`
    # unsatisfiable only if `coverage.require_complete` is true. It is false, and `rely` has
    # 6 PASS records and is admitted at `tag`. The exclusion from commit/push is a fact about
    # `admission.v1.json`, not a property of the type. A heal plan that stays silent about it
    # lets someone spend rounds on a gate that cannot close and was never asked to. Listed,
    # and explicitly marked as not gating this action.
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

    # A narrowed step hides its failures behind `NOT_APPLICABLE`, and that hid the most serious
    # finding of 2026-08-30. `prior_art` is narrowed to `actions: []` with `scope: 0`, so
    # `inventory` evaluates no subjects for it, reports `record_id: null`, and the loop above
    # never sees a verdict at all: its status is the narrowing, not the judgement. Meanwhile a
    # real `prior_art` FAIL sat in the store ("closest prior art located and uncited"), naming
    # a paper that documented the same phenomenon five months earlier at far larger scale. It
    # appeared in no bucket, on the surface that decides whether to push.
    #
    # "Narrowed out" and "nothing found" must not render identically. This bucket was added
    # hours earlier for exactly that principle and had this gap in it: it scanned rows, and a
    # step with no scope has nothing to put in a row. So scan the records too: a FAIL whose
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
