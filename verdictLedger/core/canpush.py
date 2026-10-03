"""`can_push(range)` — the one question §12-0-alpha says the client is allowed to ask.

**Tim, 2026-08-23:** *"the entire idea here is to eliminate and push as much of the
flow for cross checking this into the MCP server with a 'these are the keys needed,
does commit xyz have them so we can push safely'. There should be a substantial
reduction in the amount of extra stuff to compute."*

So the client hands over a RANGE EXPRESSION and nothing else. This module resolves it
with `git rev-list`, walks every commit, and answers once. gitRobot assembles no file
list, hashes nothing, and re-derives no completeness.

⚠⚠ EVERY COMMIT IN THE RANGE, NOT JUST THE TIP, and this is the correction that
required the module.

`push` used to ask about `HEAD` alone. A push publishes a RANGE — measured
2026-08-23, `preflight` logged `scope 0 ref(s)` while the push that followed logged
`scope 1 ref(s) — range 5892cbc..55f2d6a`, 43 commits. Gating the tip certifies the
content that will EXIST while every intermediate commit rides along unexamined, and
those commits are just as published: they are fetchable, bisectable, and citable
forever. `crossref` measured eight of them at NOT_RUN.

That is SCOPE-1 reborn inside the fix for SCOPE-1 — certifying a different subject
from the one being promoted — which §12-0 names as the trap to avoid.

⚠ THE STRICTNESS IS AFFORDABLE BECAUSE OF THE COMMIT GATE. Requiring keys at every
commit sounds punitive until you notice `batch.py precommit` already runs at every
commit; once it records, each commit carries its own keys as a side effect of normal
work. That is precisely what the `commit` admission set is for, and it is why the two
gates are worth having rather than one.
"""

from __future__ import annotations

import fnmatch
import subprocess
from typing import Optional

from core import crossref as crossref_mod
from core import inventory as inventory_mod


# ⚠ A CAP, BECAUSE AN UNBOUNDED WALK IS A HANG. It is LOUD rather than silent: a
# truncated audit that renders like a complete one is the failure this server exists
# to end, so exceeding it REFUSES rather than reporting on the part it managed.
FAMILIES = frozenset(("mechanical", "review"))

DEFAULT_LIMIT = 500


def _git(repo: str, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed: {(proc.stderr or '').strip()}")
    return proc.stdout


ALLOWED_SCOPE = (
    "THE LEDGER'S ADMISSION BAR OVER THIS RANGE, AND NOTHING ELSE. `allowed: true` means "
    "every admitted step is satisfied for every commit here — it is NOT a prediction that "
    "`git push` will succeed. ⛔ A SECOND ENFORCEMENT LAYER IS OUT OF VIEW: the pre-push "
    "hook's routing legs enforce per-file `/rely` signatures over changed routed files "
    "with no admission key, and `witness.blind_to` names it and its live instance. "
    "Measured 2026-09-28: ALLOWED here, then refused there. "
    "⚠ AND `blocking_count` IS MEANINGLESS WHERE `admission_state` IS UNSET OR EMPTY — "
    "nothing declared what must gate that commit, which is not a coverage failure. Pass "
    "`commit_admission` (gitRobot admission(action='commit')) to judge intermediates, or "
    "the count prices a question nobody asked.")


def _files_at(repo: str, ref: str) -> dict:
    """path -> git blob id for a commit. The whole comparison is this lookup.

    ⚠ THE FOURTH COPY OF THIS PARSE, now asking git for the field BY NAME like the
    other three. It happened to be correct — `ls-tree -r` does put the sha in field 2
    — but "happened to be correct" is exactly what the ledger's `_files` looked like
    until 2026-08-25, when it turned out to be reading the STAGE for staged entries,
    and every key at that basis had been unsatisfiable since the day it shipped.
    `%(objectname)` cannot be the wrong field.
    """
    out = {}
    for line in _git(repo, "ls-tree", "-r", ref,
                     "--format=%(objectname)%x09%(path)").splitlines():
        if "\t" not in line:
            continue
        blob, path = line.split("\t", 1)
        out[path.strip()] = blob.strip()
    return out



def _judging_steps(config, admitted) -> list:
    """Admitted steps whose scope STATES an obligation surface.

    ⛔⛔ A STEP THAT DECLARES NO SCOPE HAS NOT CLAIMED EVERYTHING — IT HAS CLAIMED NOTHING, AND
    READING ITS SILENCE AS "EVERY FILE" IS ABSENCE TREATED AS A CLAIM. Measured 2026-09-18 over
    ZeroParadox's 29-commit arc: the changed-path ratchet raises 328 obligations if every admitted
    step counts and 2 if only the ones with a declared scope do. The entire difference is seven
    steps with no `scope` and no `when` -- build, check_figures, check_modal, check_moved,
    check_negatives, check_paths, check_pov -- which by defaulting to "everything" drag in every
    PDF in the tree and ask a reviewer about a rendering rather than a claim.

    ⚠ Excluding them is not a weakening, it is declining to invent an obligation nobody wrote. If
    one of those steps SHOULD own a surface, the fix is a `scope` in the registry, where a reader
    can see it -- not a default in this function.

    ⭐ MEASURED EQUIVALENCE, worth knowing before anyone "simplifies" this: restricting to the
    REVIEW FAMILY alone gives the identical answer on every range tested, because the scoped
    mechanical steps already sweep their scope at precommit. The review family IS the gap. This
    keeps the scoped mechanical steps in anyway, so a step that stops sweeping starts blocking
    rather than silently going dark.

    ⛔⛔ THIS FUNCTION'S OUTPUT IS A REGISTRY READ, SO THE RATCHET'S COST IS SET BY A FILE THIS
    REPO DOES NOT OWN — AND THAT COUPLING WAS MEASURED AT 43x, NOT ARGUED. Raised by the
    ZeroParadox session 2026-09-18, reviewing the build: *"the ratchet's entire live surface is
    currently one review step, so a change to `prior_art`'s scope changes the ratchet's cost with
    no other signal."* Priced the same day over 13 daily arcs (the granularity a push has here),
    the SAME ranges under TWO registries:

        prior_art scope                                    arcs owing   obligations
        TODAY  ['ZeroParadox/*.lean','scripts/build_*.py','*.md']   8/13          41
        BEFORE `a67ee7a` (2026-09-17 15:54Z), no '*.md'             1/13           1

    ⭐ ALL 40 `prior_art` OBLIGATIONS TRACE TO ONE LINE ADDED TO ONE GLOB LIST THE DAY BEFORE.
    The ratchet itself raises ONE obligation across two weeks; the widening raises the other 40.

    ⛔⛔ THE FIGURE ABOVE READ 43 FOR SIX HOURS AND THAT WAS A MEASUREMENT DEFECT OF THE EXACT
    CLASS THIS MODULE POLICES. The harness bucketed arcs with `git log --since="14 days ago"` —
    **a MOVING WINDOW**. It slid about an hour between two runs, dropped the oldest commit from
    the 09-04 bucket, changed that arc's BASE, and took it from 7 obligations to 5. Same label,
    different object, an hour apart. ⚠ Two independent routes (`check()` and `_ratchet()` called
    directly) agreed exactly on every arc, which is what proved the gap was the boundary and not
    the code.
    ⚠ THE RATIO SURVIVES AND THE ABSOLUTE DID NOT: both sides of the 41-vs-1 comparison were
    computed in ONE run against ONE window, so their relationship holds; the standalone number
    was published as reproducible and was not. **Everything here is now pinned to named shas
    (`a87757e..b13e67c`, 128 commits, 13 arcs) and will reproduce.** Never date-bound a
    measurement that will be quoted later.
    ⚠ THE COST IS INTENTIONAL — the widening was Tim's "Mirror now" call — but it arrives THROUGH
    this gate, so a reader who sees the gate refuse will attribute the cost to the ratchet, which
    is a true number read against the wrong cause.

    ⛔ AND IT CORRECTS A CLAIM MADE IN `df3872d`'S OWN COMMIT MESSAGE: *"every owed signature on
    every range tested is prior_art."* True of the FOUR ranges tested, false at 13 — `adversary`
    raises one, on 09-08, and is the only obligation that survives removing the widening. **A
    sample of four generalised to "the entire live surface is one step"; the smallest honest
    sample that could have falsified it was thirteen.**

    ⚠ WHAT FOLLOWS FOR THE FREEZE, which is the instrument that would have SIGNALLED this:
    `frozen_registry_sha` exists precisely so a registry change under work in progress is an
    EVENT rather than background drift. `a67ee7a` moved the ratchet's cost by 43x with nothing
    naming it — see `.mcp-local/queue/gate-ratchets-only-bytes-it-has-seen.md` steps 5 and 6.
    """
    out = []
    for step in admitted or []:
        spec = (config.required.get("types") or {}).get(step)
        if not isinstance(spec, dict):
            continue
        if spec.get("scope") or spec.get("when"):
            out.append(step)
    return sorted(out)


def _changed_across(repo: str, base: str, tip: str) -> tuple:
    """(paths this range changes and that EXIST at the tip, paths that are pure renames).

    ⚠ A PURE RENAME RE-OWES NOTHING, and that is a consequence of content-keying rather than a
    concession: a verdict binds (step, path, blob), the bytes did not move, and what breaks on a
    rename is POINTERS to the old path -- which is `check_moved`'s job and a different failure.
    ⚠ Deletions owe nothing either: a path that has left the tree publishes no bytes.
    """
    renamed = set()
    for line in _git(repo, "diff", "--diff-filter=R", "-M", "--name-status", base, tip).splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            renamed.add(parts[2].strip())
    changed = []
    for line in _git(repo, "diff", "--name-only", base, tip).splitlines():
        p = line.strip()
        if p:
            changed.append(p)
    return changed, renamed


def _ratchet(*, config, repo: str, base: str, tip: str, tip_files: dict, admitted,
             by_content, recs_by_content: Optional[dict] = None) -> dict:
    """⭐⭐ THE CHANGED-PATH RATCHET: bytes this push CHANGES must have been judged AT THOSE BYTES.

    ⛔⛔ WHY IT EXISTS. Coverage is content-keyed, so a path a step examined BEFORE goes STALE when
    it changes and blocks -- while a path that step has NEVER examined passes in silence, however
    much it changed. The ratchet therefore engaged on known files and disengaged on new content,
    which is the exact opposite of the intent. Tim, 2026-09-17: *"I thought the concept was to
    accept the baseline of how it sits today and ratchet all new bytes?"*

    MEASURED THE SAME DAY, why this is not theoretical: over the 29-commit arc pushed on 09-16,
    328 (step, changed path) obligations had no verdict at the new bytes and the gate raised TWO of
    them -- 326 invisible because the step had no prior verdict to go stale. Over the previous
    seven days, 121 of 563 published file-versions carried no review-family verdict at the bytes
    that shipped; three were still live and unreviewed at the tip, including a prose home of a
    recorded prior-art incident.

    ⚠ THE BACKLOG IS GRANDFATHERED BY CONSTRUCTION. This asks only about paths the range CHANGES;
    1,102 never-examined paths sit untouched in scope and are nobody's debt until edited. That is
    the difference between this and `coverage.require_complete`, which would block every push until
    the whole corpus had been swept.
    """
    obligations = []
    if not admitted:
        return {"checked": False, "why": "no admission set, so nothing states what must judge"}
    steps = _judging_steps(config, admitted)
    changed, renamed = _changed_across(repo, base, tip)
    # ⛔⛔ SESSION STATE CAN NEVER BE OWED, BECAUSE NOBODY IS PERMITTED TO RECORD IT. `RATCHET-2`,
    # reported by ZeroParadox 2026-09-18 after it blocked a real push for SIX COMMITS: the subject
    # fence refuses `gate_round.json` as a verdict subject unconditionally, so a commit touching it
    # made this function owe a signature no caller could ever land, and the remedy printed below
    # — "run each step over the paths named and record" — was structurally impossible to execute.
    # ⚠ A REFUSAL WHOSE SUCCESS CONDITION CANNOT BE MET IS WORSE THAN A BARE REFUSAL: it sends the
    # caller to do work the system will reject. See `config.session_state_paths` for why this
    # reads the consumer's own declaration instead of listing the paths here.
    session_state = config.session_state_paths
    for path in changed:
        if path not in tip_files:          # deleted by the range: publishes no bytes
            continue
        if path in renamed:                # pure rename: same bytes, already judged
            continue
        if path in session_state:          # unjudgeable by construction — see above
            continue
        blob = tip_files[path]
        for step in steps:
            if not _in_scope(config, step, path):
                continue
            if (step, path, blob) in by_content:
                continue
            obligations.append({"step": step, "path": path, "git_blob_id": blob})
    # ⭐⭐ A FINDING MAY NOT BE CARRIED ACROSS A CHANGE TO ITS OWN FILE. Tim's ruling 2026-09-27.
    #
    # ⚠⚠ THE MEASUREMENT THAT PROMPTED IT: 953 `outstanding` entries in the stream, 948 of them
    # `ordinary`, **893 sitting on PASSING records**, and nothing anywhere gating, thresholding or
    # ageing them. Top contributors editorial 316, adversary 296, prior_art 197. So an ordinary
    # finding was preserved, attributable, and permanently inert — better than silenced, because a
    # reader can find it, but never ACTED on. After 948 of them the field is where findings go to
    # be counted rather than resolved.
    #
    # ⭐ THE RULE IS NARROW ON PURPOSE AND THE NARROWNESS IS THE ARGUMENT. It does not ask anyone
    # to clear the 893: a path nobody touched keeps its findings, exactly as the changed-path
    # ratchet above grandfathers unexamined bytes. It binds ONE case — **you edited the file the
    # finding is about, and the finding is still there.** At that moment the finding was in front
    # of whoever made the edit, and carrying it forward is a decision rather than a backlog.
    #
    # ⛔ IDENTITY IS `(severity, note)` AND A REWORDED FINDING ESCAPES. Said out loud rather than
    # implied to be airtight: nothing here can tell a genuinely different finding from the same one
    # rephrased, so this catches carry-forward and not evasion. That is the same honest footing
    # V18 takes on severity — *"Nothing here can detect a DEFLATED finding"* — and the same remedy:
    # the claim is attributable, because the record names who recorded it under which brief.
    #
    # ⚠ ORDINARY ONLY, because anything worse cannot be on a PASS at all (V18), so a carried
    # bedrock finding is already unrepresentable and needs nothing from this rule.
    carried = []
    base_files = _files_at(repo, base)
    for path in changed:
        if path not in tip_files or path in renamed or path in session_state:
            continue
        old_blob = base_files.get(path)
        # ⚠⚠ THE SECOND CLAUSE IS DEFENCE IN DEPTH AND NO TEST ON THIS PLATFORM CAN REACH IT, WHICH
        # IS RECORDED HERE RATHER THAN LEFT AS AN UNEXPLAINED MUTATION SURVIVOR. `changed` comes
        # from `_changed_across`, which already excludes paths whose bytes did not move — that is
        # where the grandfathering of the 893 actually happens, and a mutation deleting
        # `old_blob == tip_files[path]` therefore changes no outcome and no test fails.
        # ⛔ It is KEPT because `git diff --name-only` can name a path whose BLOB is unchanged — a
        # mode-only change is the case — and this loop must never call such a path carried. That
        # fixture cannot be built here: git on Windows runs with `core.filemode` false, so a mode
        # change is invisible to the diff in the first place.
        # ⭐ A surviving mutant that is understood and deliberately kept is a different thing from
        # one nobody noticed. This comment is the difference.
        if not old_blob or old_blob == tip_files[path]:
            continue                       # not actually a content change for this path
        for step in steps:
            if not _in_scope(config, step, path):
                continue
            _recs = recs_by_content or {}
            new_rec = _recs.get((step, path, tip_files[path]))
            old_rec = _recs.get((step, path, old_blob))
            if not (new_rec and old_rec):
                continue                   # nothing to compare: not a carry-forward
            def _ordinary(rec):
                return {((o.get("severity") or "").strip().lower(),
                         (o.get("note") or "").strip())
                        for o in (rec.get("outstanding") or [])
                        if isinstance(o, dict)
                        and (o.get("severity") or "").strip().lower() == "ordinary"
                        and (o.get("path") in (None, path) or not o.get("path"))}
            both = _ordinary(new_rec) & _ordinary(old_rec)
            for _sev, _note in sorted(both):
                carried.append({"step": step, "path": path,
                                "severity": _sev, "note": _note[:300],
                                "old_blob": old_blob, "new_blob": tip_files[path],
                                "why": ("this finding was recorded against an earlier build of "
                                        "this path and is recorded again against the new bytes — "
                                        "so it was in front of whoever changed the file. Fix it, "
                                        "or record the new verdict without it if it no longer "
                                        "holds. ⚠ A path nobody touched keeps its findings; this "
                                        "binds only a finding carried ACROSS a change to its own "
                                        "file.")})
    return {"checked": True, "steps_consulted": steps,
            "changed_paths": len([p for p in changed if p in tip_files and p not in renamed]),
            "renames_exempt": sorted(renamed),
            "owed": obligations,
            # ⛔ ITS OWN LIST, NEVER FOLDED INTO `owed`. The remedies are opposite: `owed` says
            # RUN THE STEP over bytes nobody judged; this says a step already ran, twice, and
            # reported the same thing both times. Collapsing them would tell a caller to re-run a
            # checker that will reproduce the finding — `RLY41-2`'s shape, a true blocking answer
            # wearing a remedy for a different failure.
            "carried_findings": carried}


def _content_indexes(records: list) -> tuple:
    """((step, path, blob) keys actually judged, the record at each key).

    Lifted out of `check` 2026-10-03 so `owed_between` asks the SAME question against the
    same index rather than a copy of it."""
    # (step, path, blob) actually judged -- the ratchet asks about CHANGED paths against this.
    by_content_keys = {(r.get("step"), s.get("path"), s.get("git_blob_id"))
                       for r in records for s in (r.get("subjects") or [])
                       if s.get("git_blob_id")}
    # ⚠ THE RECORDS THEMSELVES, for the carried-finding check, which must compare the
    # `outstanding` of the record at the OLD blob against the one at the NEW blob. The key SET
    # above answers "was this judged"; it cannot answer "what did the judgement say", and my first
    # attempt called `.get()` on it — 35 tests failed with `'set' object has no attribute 'get'`,
    # which is the honest cost of assuming a name meant a mapping.
    # ⚠ Highest revision wins, matching `_subject_index`: a superseded finding is not carried.
    recs_by_content: dict = {}
    for r in records:
        for s in (r.get("subjects") or []):
            if not s.get("git_blob_id"):
                continue
            k = (r.get("step"), s.get("path"), s.get("git_blob_id"))
            prior = recs_by_content.get(k)
            if prior is None or r.get("revision", 0) >= prior.get("revision", 0):
                recs_by_content[k] = r
    return by_content_keys, recs_by_content


OWED_SCOPE = (
    "THE CHANGED-PATH RATCHET between TWO NAMED COMMITS: every (admitted step, path) whose bytes "
    "differ from `base` to `tip`, is in that step's scope, and carries NO record at the tip's "
    "blob. It is the same `_ratchet` can_push runs — but can_push's base is the parent of the "
    "OLDEST commit in its range, which for a merge is the branch's fork point, so it also counts "
    "this side's own changes. Here the caller names the base, so a merge can ask exactly what "
    "IT imported. NOT a push answer: it ignores stale, failed, refused and every per-commit bar.")


def owed_between(*, records: list, config, repo: str, base: str, tip: str,
                 admission: Optional[list]) -> dict:
    """What `base..tip` changed that no admitted step has judged at the tip's bytes.

    ⭐ Asked for by ZeroParadox 2026-10-03 (Tim ratified the policy in his own turn): unjudged
    bytes imported by a merge are owed by the importing session, and the cost must surface AT
    MERGE TIME. Measured 2026-09-24: a session-start merge of origin/main turned a two-file
    defect fix into a fourteen-signature bill nobody saw until push.

    ⚠ `admission=None` IS NOT "NOTHING OWED". The ratchet returns `checked: False` and this
    returns `owed_count: None` — "I could not tell" and "nothing is owed" are different facts.
    """
    try:
        base_sha = _git(repo, "rev-parse", "--verify", f"{base}^{{commit}}").strip()
        tip_sha = _git(repo, "rev-parse", "--verify", f"{tip}^{{commit}}").strip()
    except ValueError as exc:
        return {"checked": False, "why": f"could not resolve base/tip: {exc}",
                "owed_count": None, "owed_prices": OWED_SCOPE}
    keys, recs = _content_indexes(records)
    admitted = sorted(admission) if admission is not None else None
    r = _ratchet(config=config, repo=repo, base=base_sha, tip=tip_sha,
                 tip_files=_files_at(repo, tip_sha), admitted=admitted,
                 by_content=keys, recs_by_content=recs)
    out = {"base": base_sha, "tip": tip_sha, "owed_prices": OWED_SCOPE, **r}
    if not r.get("checked"):
        out["owed_count"] = None
        return out
    owed = r.get("owed") or []
    by_step: dict = {}
    for o in owed:
        by_step[o["step"]] = by_step.get(o["step"], 0) + 1
    out.update({"owed_count": len(owed),
                "owed_paths": sorted({o["path"] for o in owed}),
                "owed_by_step": dict(sorted(by_step.items()))})
    return out


def _in_scope(config, step: str, path: str) -> bool:
    spec = (config.required.get("types") or {}).get(step) or {}
    # ⚠ SESSION STATE IS IN NO STEP'S SCOPE. Held HERE rather than only in `_ratchet`, which
    # filtered it separately: a helper that answers "is this in scope" must be right on its own,
    # or the next caller inherits an answer that was only ever corrected downstream. Enumerated
    # 2026-09-20 as the third member of this sibling set, after `coverage_gap` was found still
    # naming a path no caller may record.
    if path in config.session_state_paths:
        return False
    globs = spec.get("scope") or ([spec["when"]] if spec.get("when") else None)
    if globs is None:
        return False                       # no declared surface -- see _judging_steps
    if not any(fnmatch.fnmatch(path, g) for g in globs):
        return False
    # ⛔⛔ THROUGH `config.scope_exclude_for`, NOT `spec["scope_exclude"]`, AND THAT ONE WORD WAS A
    # REAL DEFECT FOR A DAY. `spec` is the RAW REGISTRY, and the harness loop-break register lives
    # in THIS repo — `config/loopbreaks.v1.json` — merged only inside `config.requirements()`. So
    # this function, the changed-path ratchet's only scope test, never saw a carve Tim had signed.
    #
    # ⚠⚠ MEASURED 2026-09-27: `copy_editor`'s carve for its own brief was PRESENT in
    # `requirements('push')` and ABSENT here, so the ratchet owed a verdict on the one path a
    # signed loop break exists to remove. I verified the carve on the served surface, concluded it
    # worked, and told the consumer their correct report was wrong — they had run the panel and
    # cleared a real obligation.
    #
    # ⭐ The register is worth nothing to a reader that does not go through the resolver, which is
    # why there is now exactly one.
    return not any(fnmatch.fnmatch(path, g)
                   for g in config.scope_exclude_for(step))


def _witness(*, config, repo: str, base: str, tip_files: dict, admitted) -> dict:
    """Which FAMILY of step, if any, has the paths this range CHANGES in its scope.

    ⚠⚠ THE HUMAN WAS THE DETECTOR FOR THIS, AND THAT IS THE DEFECT. Measured 2026-09-07:
    a push of 11 files — CLAUDE.md and ten under `tools/verify/` — reported ALLOWED, 19/19
    satisfied, 0 blocking. `adversary` and `editorial` were both admitted, both SATISFIED,
    both `gating: true`, 73/73 subjects, 0 unexamined. Every number was correct.

    ⛔ AND BOTH COVERED **ZERO** OF THE ELEVEN CHANGED PATHS. Their scope is the published
    prose surface and `scope_exclude` drops `CLAUDE.md` and `tools/*.md`, so a green
    adversary row said nothing whatever about what the push actually contained. The only
    review-family step scoped to that surface is `rely`, which is excluded from admission
    by design — so not one review step gated one file in that push.

    ⭐ Tim caught it by reading a status line and asking why a step that must gate was
    sitting in a list of things that do not. That question is a SET INTERSECTION —
    `scope ∩ changed = ∅` — over data this module already holds, and a person should never
    be the instrument for it. This is that question, asked on every call.

    ⚠ IT REPORTS AND NEVER BLOCKS. Whether an uncovered path should refuse a push is gate
    policy and belongs to the admission set, not here; shipping it as a gate would have
    refused a push that every configured rule permits. **The claim is only that `ALLOWED`
    must stop rendering identically whether a family looked or not.**

    ⚠ CHANGED means the blob MOVED across the range — added, deleted, or rewritten. A path
    present at both ends with one blob is untouched by this push and is nobody's debt here,
    however wide a step's scope is.
    """
    try:
        base_files = _files_at(repo, base)
    except ValueError:
        # ⚠ An unresolvable base is not "nothing changed". Say so and claim nothing —
        # rendering it as full coverage is the exact failure this function exists to end.
        return {"resolved": False,
                "why": ("the range base could not be resolved, so no claim is made about "
                        "which families witnessed these paths")}

    # ⚠ Session state is not content and is never a verdict subject, so counting it as an
    # "unwitnessed" path would report a family as having missed a file no family may examine.
    # Third member of the same sibling set as `build`'s scope and `coverage_gap`'s — enumerated
    # 2026-09-20 rather than grepped, which is what found the other two.
    _session_state = config.session_state_paths
    changed = sorted(p for p in set(base_files) | set(tip_files)
                     if base_files.get(p) != tip_files.get(p) and p not in _session_state)
    types = (config.required or {}).get("types") or {}
    admit = set(admitted or [])

    by_family, uncovered = {}, {}
    for path in changed:
        fams = set()
        for step, spec in types.items():
            if step not in admit or not isinstance(spec, dict):
                continue
            when = spec.get("when")
            globs = spec.get("scope") or ([when] if when else [])
            # ⛔⛔ THE SECOND RAW-REGISTRY SCOPE READER, FOUND BY SWEEPING FOR THE CLASS RATHER THAN
            # FIXING THE INSTANCE. `types` here is `config.required["types"]` — the registry as
            # written — so like `_in_scope` before it, this never saw a harness loop-break carve.
            # ⚠ The consequence is milder than the ratchet's and still wrong: `_witness` would
            # report a step as COVERING a path Tim carved out of its scope, which is a false
            # positive in the one field built to answer "did any admitted family actually look at
            # these bytes". A carve makes a step look at LESS; a witness claiming otherwise
            # overstates coverage.
            # ⭐ Three further readers were checked in the same sweep and are SAFE: they iterate
            # `config.requirements(action)`, which merges the carve already.
            drop = config.scope_exclude_for(step)
            if globs and not any(fnmatch.fnmatch(path, g) for g in globs):
                continue
            if any(fnmatch.fnmatch(path, g) for g in drop):
                continue
            fams.add(spec.get("family") or "unknown")
        for f in fams:
            by_family[f] = by_family.get(f, 0) + 1
        for f in (FAMILIES - fams):
            uncovered.setdefault(f, []).append(path)

    # ⭐⭐ A PATH NO FAMILY CLAIMS IS A DIFFERENT FACT FROM A PATH ANOTHER FAMILY CLAIMS BY
    # DESIGN, AND THIS BLOCK REPORTED THEM IDENTICALLY. Split 2026-09-22 on Tim's ruling,
    # raised by the ZeroParadox session after the ⚠⚠ fired on an INTENDED configuration:
    # two deposited PDFs sat outside every admitted REVIEW step, and that is correct — a PDF
    # is a rendered binary object, review judges SOURCE, and the source→PDF link is already
    # mechanically gated by `check_hashes` and `pdf_coupling`.
    #
    # ⛔ THE WARNING WAS RIGHT ABOUT THE FACTS AND WRONG ABOUT THE ALARM, which is the more
    # expensive kind of wrong: an alarm that fires on a configuration nobody intends to
    # change trains its reader to skip it, and then it is not there on the day it means
    # something. Same failure as a flaky test — the cost is paid later, by the reader who
    # was right to stop looking.
    #
    # ⚠ THE DISCRIMINATOR IS A SET INTERSECTION THIS FUNCTION ALREADY HELD: a path
    # unwitnessed by `review` but witnessed by SOME admitted family is covered, by a
    # different family, on purpose. A path witnessed by NO admitted family at all is the
    # real gap — nothing whatever looked at it, and that is the 2026-09-07 defect this
    # function was built for.
    witnessed_by_any = {p for p in changed
                        if any(p not in uncovered.get(f, ()) for f in FAMILIES)}
    unclaimed = sorted(p for p in changed if p not in witnessed_by_any)
    return {"resolved": True,
            "changed_paths": len(changed),
            "witnessed_by_family": {f: by_family.get(f, 0) for f in sorted(FAMILIES)},
            "unwitnessed_by_family": {f: uncovered[f] for f in sorted(uncovered)},
            # ⭐ THE FIELD A CALLER SHOULD BRANCH ON. `unwitnessed_by_family` answers "which
            # family missed this" and is the right answer to a different question; this
            # answers "did ANYTHING look", which is the one the alarm is about.
            "unclaimed_by_every_family": unclaimed,
            "unclaimed_count": len(unclaimed),
            "covered_by_another_family": len(changed) - len(unclaimed),
            # ⛔⛔ THIS INSTRUMENT SEES ONE OF THE TWO ENFORCEMENT LAYERS, AND UNTIL 2026-09-22
            # IT DID NOT SAY SO. Raised by the ZeroParadox session, and the decisive part is
            # that THIS SERVER ALREADY DOCUMENTED THE FACT somewhere else —
            # `ledger_server/server.py` on `can_push`: the pre-push hook's routing legs are
            # *"an obligation that lives in `batch.py`, has no admission key, and this server
            # cannot see."* The knowledge was in the repo; the field reporting the number did
            # not carry it.
            #
            # ⚠⚠ THE LIVE INSTANCE, AND IT IS THE ONE THAT NEARLY GOT MIS-FILED.
            # `tools/verify/required.v2.json` is claimed at push by exactly one ADMITTED step,
            # `check_encoding` (mechanical) — `rely`, whose scope covers it, is
            # registered-not-admitted, so it witnesses nothing HERE. That reads like an
            # admission-set gap. It is not: `/rely`'s ROUTING LEG in the pre-push hook is a
            # per-file signature check over changed routed files, it is BLOCKING, and it named
            # that exact file on the `1c56442` push. **The file is gated. This instrument is
            # blind to the layer that gates it.**
            #
            # ⛔ RECORDING IT AS AN ADMISSION GAP WOULD HAVE CAUSED THE WRONG FIX — admitting
            # `rely` at push, duplicating an obligation the hook already enforces and charging
            # a full review-type verdict on every checker edit. Their correction, and it is
            # right. `rely` IS TWO DIFFERENT THINGS WITH ONE NAME: the ledger TYPE and the
            # hook's ROUTING LEG. Excluding the first never disabled the second.
            #
            # ⭐ SO THE DISCRIMINATOR IS ONE CLAUSE LONGER THAN THIS MODULE CAN EVALUATE: not
            # "is the right judge ADMITTED" but "is the right judge ENFORCING, in whatever
            # layer it enforces in". This module can only answer for the ledger layer, so it
            # names the layer instead of implying it answered for both.
            # ⛔⛔ A COUNT, NOT ONLY A NAME, AND THE REASON IS THIS SESSION'S OWN LESSON
            # APPLIED TO THE FIX FOR IT. The first version published only
            # `enforcement_layer: "ledger_admission"`, and ZeroParadox asked the right
            # question about it: **does that read as a qualifier or as a reassurance?** A
            # field naming the layer, sitting beside a count, skims as *"good, the layer is
            # named"* rather than *"this number answers half the question."*
            #
            # ⚠⚠ 1 OF 2 CANNOT BE SKIMMED AS COMPLETE. That is the whole argument, and it is
            # the same one that produced `coverage_gaps` an hour earlier: `witness` worked
            # because it published counts; `unvalidated` failed because it published prose. A
            # name is prose with a colon in front of it.
            "enforcement_layer": "ledger_admission",
            "enforcement_layers_visible": 1,
            "enforcement_layers_total": 2,
            "blind_to": ("the pre-push hook's routing legs (`batch.py`), which enforce "
                         "per-file `/rely` signatures over changed routed files with no "
                         "admission key. A path reported here as unwitnessed may be gated "
                         "there — `tools/verify/required.v2.json` is the live instance. "
                         "⚠ An unwitnessed path is a question to ask, never a proof that "
                         "nothing gates it."),
            "note": ("counts paths CHANGED by this range whose scope is claimed by at least "
                     "one ADMITTED step of that family. A family at 0 examined nothing this "
                     "push touched, however green its rows read. ⚠ `unclaimed_by_every_family` "
                     "is the alarm: a path absent from one family's scope may be covered by "
                     "another family BY DESIGN (a rendered PDF is judged mechanically, not by "
                     "review), and reporting those two as one condition trains a reader to "
                     "ignore both. Reported, never blocking.")}


def _inherited_published(repo: str, commits: list) -> dict:
    """Which of these commits are ALREADY PUBLISHED on the remote this push targets.

    ⭐⭐ Tim's ruling 2026-09-25. A commit that is already an ancestor of a ref on the push
    target was published by a different, sanctioned route — for `ce32401a` that is GitHub
    creating a merge commit for PR #139, pulled in by the `R-BRANCH`-mandated
    `merge(origin/main)`. **This push is not its publication event and publishes no new bytes
    from it.** See `config.forgive_inherited_published` for why that is grandfathering rather
    than a loosening.

    ⛔⛔ KEYED ON THE REMOTE WE ARE PUSHING TO, WITH NO CONFIGURED URL, AND THAT IS DELIBERATE.
    Tim raised the hazard that made it necessary: *"origin main should be safe in theory, as
    long as the URL it means doesn't change."* `origin` is a local alias and a `set-url`
    re-points it silently — measured the same day, the consumer's checkout already carried a
    second remote named `fake` aimed at a scratchpad temp directory.
    ⭐ So the condition is self-referential ON PURPOSE: *already on the remote this push
    targets*. If `origin` is re-pointed, BOTH HALVES MOVE TOGETHER — we would be pushing to
    the re-pointed place too, and "already there" stays exactly true and still means this push
    publishes nothing new. A pinned URL would have to be kept in step with reality by hand;
    this cannot drift because it never names a URL at all. The remaining hazard — *you pushed
    to the wrong place* — is a different defect, and gitRobot's receipt now names the resolved
    URL so it is visible.

    ⚠⚠ THE TRACKING REF IS A LOCAL CACHE AND IS VERIFIED, NOT TRUSTED. `origin/main` is updated
    only by `fetch`, so a stale one could claim a commit is published when it had been
    force-removed remotely. Every tracking ref used here is checked against `ls-remote` and a
    disagreement forgives NOTHING — the whole answer fails closed rather than the one ref, since
    a cache wrong about one ref is not evidence about the others.
    """
    try:
        raw = _git(repo, "for-each-ref", "--format=%(refname) %(objectname)",
                   "refs/remotes/origin")
    except ValueError as exc:
        return {"checked": False, "why": f"remote-tracking refs unreadable: {exc}", "commits": []}
    tracked = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) == 2 and not parts[0].endswith("/HEAD"):
            tracked[parts[0].split("refs/remotes/origin/", 1)[-1]] = parts[1]
    if not tracked:
        return {"checked": False, "why": "no remote-tracking refs for origin", "commits": []}
    # ⛔ THE AUTHORITY IS THE REMOTE, NOT THE CACHE.
    try:
        ls = _git(repo, "ls-remote", "--heads", "origin")
    except ValueError as exc:
        return {"checked": False,
                "why": (f"could not reach the remote to verify the tracking refs ({exc}), so "
                        f"nothing is forgiven — a cache that cannot be checked is not evidence"),
                "commits": []}
    live = {}
    for line in ls.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("refs/heads/"):
            live[parts[1].split("refs/heads/", 1)[1]] = parts[0]
    stale = sorted(b for b, sha in tracked.items() if live.get(b) != sha)
    if stale:
        return {"checked": False,
                "why": (f"the local tracking refs disagree with the remote on {len(stale)} "
                        f"branch(es) — {', '.join(stale[:4])}. Nothing is forgiven: a cache "
                        f"wrong about one ref is not evidence about the others. Fetch first."),
                "commits": []}
    out = []
    for c in commits:
        for branch, sha in tracked.items():
            if _is_ancestor(repo, c, sha):
                out.append({"commit": c, "published_on": f"origin/{branch}"})
                break
    return {"checked": True, "verified_against": "ls-remote",
            "branches_checked": len(tracked), "commits": out,
            "note": ("commits already reachable from a ref on the remote this push targets, so "
                     "this push publishes no new bytes from them. ⚠ Provenance, NOT churn: a "
                     "commit authored here whose blobs merely changed before the tip is NOT "
                     "in this list and still blocks.")}


def _is_ancestor(repo: str, maybe_ancestor: str, descendant: str) -> bool:
    """`git merge-base --is-ancestor`, as a bool. A non-zero exit is 'no', not an error."""
    try:
        subprocess.run(["git", "merge-base", "--is-ancestor", maybe_ancestor, descendant],
                       cwd=repo, capture_output=True, timeout=60, check=True)
        return True
    except Exception:                                                       # noqa: BLE001
        return False


def _coverage_gaps(rows: list) -> dict:
    """Gating steps that read SATISFIED without examining their whole scope, AS NUMBERS.

    ⛔⛔ THE FINDING THIS ANSWERS, from the ZeroParadox session 2026-09-22: *"A step that
    examined a sliver is indistinguishable BY VALUE from one that examined everything; the
    difference lives entirely in a warning string, and consumers branch on the value."* They
    were right, and the proof was two fields away in the same response — `witness` reports
    counts, so a caller can act on it.

    ⚠ `worst` IS A RATIO AND THE COUNTS TRAVEL WITH IT. A bare "thinnest step" names an
    outlier; the count says whether it is a condition. Measured 2026-09-07 when that lesson
    was first paid for: NINE of nineteen gating steps read SATISFIED with 823 in-scope paths
    unexamined between them, and the line named ONE — understating it ninefold, in the
    direction that reads as healthier.
    """
    by_step: dict = {}
    for row in rows:
        for step, examined, in_scope in (row.get("unvalidated") or ()):
            # ⚠ WORST-CASE PER STEP ACROSS THE RANGE, not last-seen. A step that examined its
            # whole scope at the tip and a sliver at commit 3 has published a sliver; taking
            # whichever commit happened to be iterated last would report the flattering one.
            prev = by_step.get(step)
            if prev is None or (examined / in_scope if in_scope else 1) < prev["ratio"]:
                by_step[step] = {"examined": examined, "in_scope": in_scope,
                                 "ratio": (examined / in_scope) if in_scope else 1.0}
    unexamined = sum(v["in_scope"] - v["examined"] for v in by_step.values())
    worst = min(by_step.items(), key=lambda kv: kv[1]["ratio"], default=None)
    return {
        "steps": len(by_step),
        "paths_unexamined": unexamined,
        "by_step": {k: {"examined": v["examined"], "in_scope": v["in_scope"]}
                    for k, v in sorted(by_step.items())},
        "worst_step": None if worst is None else worst[0],
        "worst_examined": None if worst is None else worst[1]["examined"],
        "worst_in_scope": None if worst is None else worst[1]["in_scope"],
        "note": ("gating steps whose rows read SATISFIED while paths in their declared scope "
                 "were never examined at these bytes. REPORTED, NEVER BLOCKING — whether an "
                 "unexamined path refuses a push is `coverage.require_complete`, which is "
                 "policy. ⚠ `steps: 0` means every gating step examined its whole scope; it "
                 "does NOT mean coverage was not checked."),
    }


def check(*, records: list, config, repo: str, rev_range: str, action: str = "push",
          admission: Optional[list] = None, commit_admission: Optional[list] = None,
          limit: int = DEFAULT_LIMIT, refusals: Optional[dict] = None) -> dict:
    """Can this range be pushed? One answer, over every commit it publishes.

    ⚠⚠ INTERMEDIATE COMMITS ARE JUDGED AS COMMITS; THE TIP IS JUDGED AS A PUSH.

    An earlier build asked `action="push"` of every commit, so each one had to carry
    `adversary`, `editorial` and `prior_art` -- three agent rounds per commit, 129 for
    a 43-commit range. That is not a strict gate, it is an unsatisfiable one.

    The registry already said otherwise and this ignored it: those three carry
    `actions: ["push", "tag"]`, which IS the statement that they judge the work being
    PUBLISHED rather than each step of reaching it. 12-0-ter's rule -- if admission and
    the registry disagree, the registry is the list with the stated reasons -- applies
    to a consumer overriding a narrowing just as much as to a thinned admission set.

    ⚠ Nothing is weakened: every commit still earns the full COMMIT set, which is the
    property range gating exists for. The review types are required once, of the thing
    actually published.

    ⚠ `admission=None` is NOT an empty set -- it means nobody said what gates this
    action, and it refuses. Same for `commit_admission`: absent is not empty.

    ⛔ `refusals` WAS PASSED HERE FOR SIX DAYS BEFORE THIS SIGNATURE TOOK IT. 5ebd805
    (2026-09-07) taught `inventory` to render a refused claim as REFUSED rather than
    MISSING, and passed `refusals=` into this function from the CLI. This signature never
    accepted it, so `zpledger can-push` raised TypeError on every call (reproduced
    2026-09-13). Accepting it fixes the CLI.

    ⚠ THE MCP SERVER STILL DOES NOT PASS IT, ON PURPOSE. See `_sync_can_push`: the sidecar
    never clears, so wired in today it would hand the wrong remedy to nearly every
    never-run row. With `refusals=None` no `refused` key is emitted anywhere, because an
    empty list would claim "nothing was refused" about a sidecar nobody read.
    """
    consulted = refusals is not None
    try:
        raw = _git(repo, "rev-list", "--reverse", rev_range)
    except ValueError as exc:
        return {"ok": False, "allowed": False, "error": str(exc),
                "range": rev_range,
                "why": ("the range could not be resolved, so nothing is claimed about "
                        "it — an unresolvable range must never read as 'nothing to "
                        "check'")}

    commits = [c for c in raw.split() if c]
    if len(commits) > limit:
        # ⚠ REFUSE, do not truncate. Reporting on the most recent N of a larger range
        # would render exactly like a complete answer.
        return {"ok": True, "allowed": False, "range": rev_range,
                "commits_in_range": len(commits), "limit": limit,
                "why": (f"the range holds {len(commits)} commits, over the {limit} this "
                        f"will walk. REFUSED rather than truncated: an answer about "
                        f"part of a range renders identically to one about all of it."),
                "commits": []}

    admitted = sorted(admission) if admission is not None else None
    by_content_keys, recs_by_content = _content_indexes(records)
    # ⭐⭐ BUILT ONCE FOR THE WHOLE WALK — see the long note at `inventory.build`. It is a pure
    # function of `records`, which does not change across the commits of one call, and
    # rebuilding it per commit was 52% of a measured 43-commit run.
    _index = inventory_mod._subject_index(records)
    # ⚠ Shared across the walk, keyed by (action, admission) inside `build` — two
    # entries for a range, not one per commit. See the note at its use site.
    _scope_audit: dict = {}
    rows = []
    prev_files = None
    for i, commit in enumerate(commits):
        is_tip = (i == len(commits) - 1)
        # ⚠ The tip is what the world will see as the published state, so it carries
        # the full push bar. Everything under it is judged by the bar that applied
        # when it was MADE.
        this_action = action if is_tip else "commit"
        this_admission = admission if is_tip else commit_admission
        files = _files_at(repo, commit)
        # ⭐ WHAT THIS COMMIT CHANGED, so a declared `min_coverage` prices the paths it
        # TOUCHED rather than its whole scope. Barred against the scope, a step at 1.0 broke
        # the moment anyone added a matching file — measured 2026-09-07, and Tim caught it
        # before a single bar was set: *"I don't want to end up in that same damn boat of
        # some random unrelated file getting included in scope that continually grows."*
        #
        # ⚠ The PARENT's tree, taken from the previous iteration where the range is linear,
        # so this costs ONE extra `ls-tree` for the first commit and none after it.
        if prev_files is None:
            try:
                prev_files = _files_at(repo, commit + "^")
            except ValueError:
                prev_files = {}          # a root commit: everything in it is changed
        changed = {p for p in set(prev_files) | set(files)
                   if prev_files.get(p) != files.get(p)}
        # ⛔⛔ TWO DIFFERENT QUESTIONS, AND ONE ARGUMENT WAS ANSWERING BOTH — WHICH IS THIS
        # REPO'S FOUNDING DEFECT WEARING A PARAMETER NAME. Fixed 2026-09-21, Tim's ruling,
        # after the gap below was REPRODUCED rather than argued:
        #
        #     "what did THIS COMMIT touch"    prices `min_coverage`. Per-commit is correct and
        #                                     deliberate — Tim, 2026-09-07: *"I don't want to
        #                                     end up in that same damn boat of some random
        #                                     unrelated file getting included in scope."*
        #     "what does THIS PUSH publish"   scopes STALE forgiveness. The TIP row is the push
        #                                     authorisation, and a push publishes the RANGE.
        #
        # ⚠⚠ THE TIP ROW WAS PRICING THE SECOND AGAINST THE FIRST. A path changed early in the
        # range and not re-touched by the tip commit fell OUTSIDE the tip's own diff, so a STALE
        # row over it was forgiven as "out of range" — while the push published exactly those
        # bytes. Measured on the live fleet the day this was written: `inventory()` on the tip
        # answered `complete: False` and `can_push`'s row for the SAME ref answered
        # `complete: true`, both correct under their own scoping, disagreeing with nothing to
        # explain it. A merge tip makes it worst, since a merge's first-parent diff can be tiny.
        #
        # ⛔ AND THE THREE MECHANISMS COMPOSED INTO A REAL FAIL-OPEN, DEMONSTRATED IN A FIXTURE:
        # a step that is push-admitted, NOT commit-admitted, and declares no scope is (1) not
        # gated on intermediates, (2) forgiven at the tip by the mis-scoping above, and (3)
        # skipped by the ratchet, which by design consults only steps that state an obligation
        # surface. The probe returned `allowed: True` over a tip reading `stale: [check_prose]`.
        # ⚠ It was not live — all four push-only steps declare scopes — but the push-only SET
        # was created the same day by narrowing `check_hashes`, and the scopes of the other
        # three were under active edit that afternoon. Held by a coincidence between two files,
        # one of them in a repo this one does not own.
        #
        # ⭐ INTERMEDIATES ARE UNCHANGED. Their bar is the one that applied when they were made,
        # and per-commit staleness is right for them; only the tip's authorisation moves.
        published = changed
        if is_tip:
            _across, _ = _changed_across(repo, commits[0] + "^", commit)
            published = set(_across)
        inv = inventory_mod.build(config=config, records=records, action=this_action,
                                  files=files, ref=commit, admission=this_admission,
                                  refusals=refusals, changed=changed, published=published,
                                  repo=repo, subject_index=_index,
                                  scope_audit=_scope_audit)
        prev_files = files
        if is_tip:
            tip_files = files
        rows.append({
            # ⚠ Carried so the TIP-GREEN pass below can ask what each failing row CONDEMNS
            # rather than only that it failed. Stripped before the result is returned.
            "_indicted": [i for r in inv["rows"] if r.get("gating")
                          for i in (r.get("indicted") or [])],
            "commit": commit,
            "judged_as": this_action,
            # which registry judged the producer pins at this commit (see inventory.registry_types_at)
            "pin_basis": inv.get("pin_basis"),
            "is_tip": is_tip,
            "subject": _git(repo, "log", "-1", "--pretty=%s", commit).strip()[:72],
            "complete": bool(inv.get("complete")),
            "required": inv["required"], "satisfied": inv["satisfied"],
            "missing": sorted(r["step"] for r in inv["rows"]
                              if r["gating"] and r["status"] == "MISSING"),
            "stale": sorted(r["step"] for r in inv["rows"]
                            if r["gating"] and r["status"] == "STALE"),
            # ⛔⛔ WHY `complete` CAN BE TRUE BESIDE A NON-EMPTY `stale`, NAMED ON THE ROW.
            #
            # ⚠⚠ MEASURED 2026-09-26, AND THE MEASUREMENT IS TWO PEOPLE RATHER THAN A PROBE.
            # This row rendered `required: 21, satisfied: 20, stale: ["copy_editor"],
            # complete: true` — all four correct — and **two readers who had each spent the day
            # inside this system independently concluded it was a FAIL-OPEN on the push path,
            # within an hour of each other.** One filed it as a defect against the other's code;
            # the other confirmed it to Tim before re-deriving. Neither was careless: nothing in
            # the payload said which of the 21 was unsatisfied or why that was allowed.
            #
            # ⭐ THE BEHAVIOUR WAS RIGHT AND THE RENDERING WAS INDEFENSIBLE. Tim's 2026-09-18
            # ruling is that a STALE row whose stale paths are untouched by the range does not
            # refuse it — `n_blocking_stale()` in `inventory.py` — and in the case measured,
            # `copy_editor` was stale while the range published only two `.json` files that
            # match none of its scope globs AND sit under its `tools/*` exclusion. Zero paths in
            # scope, by two independent routes. The forgiveness was exactly correct.
            #
            # ⛔ SO THIS IS THE `cap_prices` / `would_block_push_scope` / `passed_prices` PATTERN
            # FOR THE FOURTH TIME, and the lesson each time is the same: a TRUE number whose
            # object is unstated gets read against the wrong object. "Never report a number
            # without naming what it prices" is this repository's founding rule, and
            # `satisfied: 20` of `required: 21` beside `complete: true` broke it in my own output.
            #
            # ⚠ NOT FOLDED INTO `stale`, and not removed from it. The row stays STALE everywhere
            # a reader looks — `n_blocking_stale`'s own comment says a row that vanished from the
            # stale list would hide the backlog instead of grandfathering it. This says why it
            # does not block; it does not say it is fine.
            "stale_forgiven": [
                {"step": r["step"],
                 "stale_paths": (r.get("stale_paths") or [])[:20],
                 "stale_path_count": len(r.get("stale_paths") or []),
                 "why": ("STALE, and none of the paths it has not judged are published by this "
                         "range — so it does not refuse THIS push and is NOT counted in "
                         "`satisfied`. That is why `complete` can be true while `satisfied` is "
                         "below `required`. ⚠ The step is still stale: it has not examined "
                         "those bytes, and it will block any range that publishes them.")}
                for r in inv["rows"]
                if r["gating"] and r["status"] == "STALE" and r.get("stale_out_of_range")],
            "failed": sorted(r["step"] for r in inv["rows"]
                             if r["gating"] and r["status"] in ("FAIL", "UNDECIDED")),
            "legacy": sorted(r["step"] for r in inv["rows"]
                             if r["gating"] and r["status"] == "LEGACY_IDENTITY"),
            # ⭐ A CLAIM WAS ATTEMPTED AND THE LEDGER DECLINED IT. Its own list rather than
            # folded into `missing`, because the remedies are opposite: MISSING says run the
            # step, REFUSED says re-running reproduces the refusal and the RECORD must change.
            "refused": sorted(r["step"] for r in inv["rows"]
                              if r["gating"] and r["status"] == "REFUSED"),
            "admission_state": inv.get("admission_state"),
            "not_gating": inv.get("registered_not_admitting") or [],
            # ⭐⭐ THE STEPS THAT PASS ONLY BECAUSE THE COVERING RECORD INDICTS ELSEWHERE.
            # Found by asking ZeroParadox's `SH-3` question of my own fix, 2026-09-05: a fix
            # applied at one level and not its sibling. `render_inventory` had just learned to
            # print NARROWED INDICTMENT; the PUSH path — the one that matters — was still
            # silent, exactly as it was for NARROWED COVERAGE until 2026-08-23 taught it the
            # same lesson. Two arguments, the same asymmetry, three weeks apart.
            "narrowed": sorted({f"{r['step']} (from {r['narrowed_from']})"
                                for r in inv["rows"]
                                if r.get("gating") and r.get("narrowed_from")}),
            # ⭐ THE SAME FACT AS A PAIR, so `narrowed_passes` on the result can be assembled
            # without parsing the human string above — see the note at its construction.
            "narrowed_pairs": sorted({(r["step"], r["narrowed_from"])
                                      for r in inv["rows"]
                                      if r.get("gating") and r.get("narrowed_from")}),
            # ⭐⭐ HOW MANY GATING STEPS HAVE NOT EXAMINED THEIR SCOPE, not just the worst
            # one. Added 2026-09-07. `thinnest` has reported the extreme since 2026-08-23 and
            # a reader sees ONE step named — measured the same day this landed, NINE of
            # nineteen gating steps read SATISFIED with 823 in-scope paths never examined
            # between them. Naming the extreme and omitting the count understates the
            # condition by a factor of nine, in the direction that reads as healthier.
            #
            # ⚠ REPORTED, NOT BLOCKING, and deliberately so. Whether an unexamined path
            # refuses a push is `coverage.require_complete`, which is policy and is FALSE.
            # This changes only what the reader is TOLD. Tim, 2026-09-07: *"absence should
            # render as unknown, not pass"* — the row still says SATISFIED, and until that
            # is a coordinated change the line is where the truth can be said for free.
            "unvalidated": sorted(
                (r["step"], r["scope"] - r["subjects_unexamined"], r["scope"])
                for r in inv["rows"]
                if r.get("gating") and (r.get("subjects_unexamined") or 0) > 0),
            # the thinnest gating step at this commit, so a green key over a narrow
            # scope is visible on THE PUSH PATH and not only in `inventory`
            "thinnest": min(
                ((r["step"], r["scope"] - r["subjects_unexamined"], r["scope"])
                 for r in inv["rows"]
                 if r.get("gating") and r.get("subjects_unexamined")),
                key=lambda t: t[1] / t[2] if t[2] else 1, default=None),
        })

    # ⚠ An EMPTY range is not a satisfied one. Pushing nothing is legitimate, but it
    # must be named rather than rendered as "all keys green".
    if not rows:
        # ⚠ THE SCOPE STATEMENT RENDERS HERE TOO, on the OTHER path that can answer `allowed:
        # true`. An empty range cannot be refused by the pre-push hook — there is nothing to
        # route — so the caveat is not load-bearing for this case. It is present anyway, because a
        # field that appears on one `allowed: true` and not another teaches a reader it is
        # optional, and the 2026-09-22 freeze caveat shipped exactly that way: rendered in the
        # broken state, silent in the state that produced the defect.
        return {"ok": True, "allowed": True, "range": rev_range, "commits": [],
                "empty_range": True, "admitted": admitted,
                "allowed_prices": ALLOWED_SCOPE,
                "why": "the range publishes no commits; nothing was gated because "
                       "nothing is being promoted"}

    # ⚠⚠ HOW MUCH OF THIS RANGE THE AUDIT DOES NOT CLAIM. Measured 2026-08-23:
    # 174 unpushed, 23 above the genesis floor, 151 below it -- and those 151 are in
    # BOTH tools' scope and NEITHER tool's answer. This gate refuses them; `crossref`
    # stops at the floor and says nothing about them. Each is right under its own
    # scoping and together they read as "the audit is clean and the push is refused,
    # about the same commits".
    #
    # Reported here rather than fixed by moving the floor, which would not audit
    # anything -- it would only lower where judgement starts so the audit says
    # something, which is a claim nobody made.
    below_floor = 0
    floor = crossref_mod._genesis_floor_commit(records)
    if floor:
        try:
            above = {c for c in _git(repo, "rev-list", f"{floor}..{rev_range.split('..')[-1]}").split() if c}
            below_floor = sum(1 for r in rows if r["commit"] not in above)
        except ValueError:
            below_floor = 0

    # ⭐⭐ THE TIP-GREEN BAR. Tim, 2026-09-02: a range may publish when the tip carries the full
    # push bar AND every defect an intermediate honestly carries is FIXED BY THE TIP.
    #
    # ⚠⚠ THE SECOND CLAUSE IS THE WHOLE SAFETY OF IT. "The tip is green" alone would publish a
    # broken intermediate whose defect was never fixed at all, which is not what was authorised.
    # An intermediate is forgiven ONLY when every blob its failing rows INDICT is absent at the
    # tip — the defect is demonstrably gone from what the world will fetch.
    #
    # ⚠ MISSING / STALE / LEGACY STILL BLOCK EVERYWHERE. "We never looked" is not "we looked, it
    # was broken, and we fixed it"; only the second is a defect a push can carry a fix for.
    # Collapsing them would silently turn this bar into "the tip is green".
    #
    # ⭐ WHY THE OLD BAR HAD TO MOVE: `every_commit` cannot express the NORMAL shape of a
    # remediation arc — a real defect at N, fixed at M, both in one push. Measured 2026-09-02:
    # two commits honestly carried an orphan checker, and under `every_commit` that sixteen-
    # commit range could never be pushed commit-by-commit-green. The only escape was rewriting
    # history, which is what `squash` does and which is remediation-only on principle.
    bar = getattr(config, "push_bar", "every_commit")
    # ⭐⭐ ALREADY-PUBLISHED COMMITS, Tim's ruling 2026-09-25 — computed ONCE for the range and
    # only when policy opts in. Defaults off: a forgiveness that arrives switched on is a gate
    # that quietly widened. See `config.forgive_inherited_published` and `_inherited_published`.
    inherited = {"checked": False, "why": "policy.push.forgive_inherited_published is not set",
                 "commits": []}
    if getattr(config, "forgive_inherited_published", False):
        inherited = _inherited_published(repo, [r["commit"] for r in rows if not r["is_tip"]])
    _inherited_at = {c["commit"]: c["published_on"] for c in (inherited.get("commits") or [])}
    forgiven = []
    published_already = []
    blocking = []
    for r in rows:
        if r["complete"]:
            continue
        # ⛔⛔ ITS OWN LIST, NEVER FOLDED INTO `forgiven`, BECAUSE THE REASON IS DIFFERENT.
        # `forgiven` means "a real defect, superseded by the tip". This means "not published by
        # this push at all". A reader who cannot tell them apart cannot tell a fixed defect from
        # an unexamined inheritance, and collapsing two reasons into one list is the shape this
        # module exists to refuse.
        #
        # ⚠ NEVER THE TIP. The tip IS what this push publishes; if it were already on the remote
        # there would be nothing to push. `_inherited_published` is handed non-tip commits only,
        # and this guard restates it so a future edit to that call cannot quietly widen it.
        if not r["is_tip"] and r["commit"] in _inherited_at:
            published_already.append({
                "commit": r["commit"],
                "published_on": _inherited_at[r["commit"]],
                "short": r["missing"] + r["stale"] + r["legacy"] + r["refused"] + r["failed"],
            })
            continue
        if (bar == "tip_green" and not r["is_tip"]
                and not r["missing"] and not r["stale"] and not r["legacy"]
                # ⛔⛔ AND NOT REFUSED. Before 2026-09-13 a refused step read MISSING here and
                # blocked for that reason. Once it has its own status, leaving it off this
                # line would forgive a commit carrying a fixed FAIL plus a claim the ledger
                # never accepted: "we never looked" wearing a new name.
                and not r["refused"]
                and r["failed"]
                # every indicted blob must be GONE at the tip
                and all(tip_files.get(i["path"]) != i["git_blob_id"]
                        for i in r["_indicted"])
                # ⚠ AND THERE MUST BE SOMETHING TO CHECK. A failing row that names no indicted
                # bytes would vacuously satisfy `all(...)` and be forgiven on no evidence —
                # the empty-set fail-open this codebase has paid for repeatedly. A pre-`failing`
                # wide FAIL always names its subjects, so this only excludes genuinely
                # contentless rows.
                and r["_indicted"]):
            forgiven.append({
                "commit": r["commit"], "steps": r["failed"],
                "indicted_and_fixed_by_tip": sorted(
                    {i["path"] for i in r["_indicted"]}),
            })
            continue
        blocking.append(r)
    for r in rows:
        r.pop("_indicted", None)
        if not consulted:
            r.pop("refused", None)

    # ⚠ COMPUTED OVER THE WHOLE RANGE AT THE TIP'S BYTES, which is what the push PUBLISHES.
    # Per-commit would re-ask about intermediate bytes the world never sees at the tip and would
    # turn one arc into hundreds of obligations -- measured at 328 for a 29-commit range.
    ratchet = _ratchet(config=config, repo=repo, base=rows[0]["commit"] + "^",
                       tip=rows[-1]["commit"], tip_files=tip_files, admitted=admitted,
                       by_content=by_content_keys,
                       recs_by_content=recs_by_content)
    owed = ratchet.get("owed") or []
    # ⭐⭐ A CARRIED FINDING BLOCKS, Tim's ruling 2026-09-27 — "a finding may not be carried ACROSS
    # a change to its own file". It is a SEPARATE term in the decision rather than folded into
    # `owed`, for the same reason the lists are separate: `owed` means run the step, this means the
    # step ran twice and said the same thing, and a caller told to re-run would reproduce it.
    carried = ratchet.get("carried_findings") or []

    return {
        "ok": True,
        "allowed": (not blocking) and not owed and not carried,
        # ⛔⛔ WHAT `allowed` PRICES, AND — THE PART THAT COST A PUSH — WHAT IT DOES NOT.
        #
        # ⚠⚠ MEASURED 2026-09-28. `can_push` answered ALLOWED, blocking_count 0, and the push then
        # FAILED at the pre-push hook: `batch.py`'s routing legs refused because
        # `tools/verify/required.v2.json` had been edited after the last `/rely` round, so its
        # current bytes carried no signature. **`witness.blind_to` names that layer, that
        # mechanism, and that exact file as "the live instance"** — the disclosure was already
        # correct and specific, and it was not attached to the field anyone reads.
        #
        # ⛔⛔ AND I BUILT THIS GAP THE DAY BEFORE. `preflight.passed` gained `passed_prices` on
        # 2026-09-27, which says *"NOT a prediction that the push will be allowed … TO LEARN
        # WHETHER THE PUSH WILL GO: can_push(rev_range=…)"*. So the chain was: preflight says ask
        # can_push; can_push says ALLOWED with no caveat; a layer can_push documents being blind to
        # refuses. **I pointed a reader at a surface that did not carry the warning I had just
        # added to the one they came from** — the same fix applied at one level and not its sibling,
        # which is `SH-3`, sixth instance in this file, and this one was mine to have prevented.
        #
        # ⚠ IT IS NOT A DANGEROUS FAIL-OPEN AND SHOULD NOT BE READ AS ONE. The hook held and
        # nothing shipped wrongly; this is a false green in a PREDICTIVE surface, which costs a
        # wasted push cycle and a reader's trust rather than correctness.
        #
        # ⭐ AND THE SECOND SENTENCE CLOSES THE FIFTH INSTANCE IN THE SAME BREATH: the "admission
        # UNSET is NOT a coverage failure" warning lived only in the RENDERED text, so a caller
        # reading `blocking_count` programmatically got a number with nothing saying it is
        # meaningless when nothing declared what gates a commit. That one caught ME, reconciling a
        # figure with the consumer, and I nearly reported a disagreement caused by my own omitted
        # `commit_admission`.
        "allowed_prices": ALLOWED_SCOPE,
        "range": rev_range,
        "commits_in_range": len(rows),
        "blocking_count": len(blocking),
        "push_bar": bar,
        # ⚠ WHERE THE BAR CAME FROM, not just what it is. ZeroParadox could not find the
        # mechanism that produced their refusal because it was a hardcoded default, not a
        # policy value — and a default that behaves correctly is the hardest kind to notice.
        "push_bar_source": getattr(config, "push_bar_source", "default"),
        # ⚠ NEVER FORGIVE SILENTLY. A commit excused by the bar must be named, with the paths
        # whose defect the tip fixed — otherwise "allowed" renders identically whether the range
        # was clean or merely forgiven, which is the collapse this whole gate exists to prevent.
        "forgiven": forgiven,
        "forgiven_count": len(forgiven),
        "tip": rows[-1]["commit"],
        "commits_below_audit_floor": below_floor,
        "audit_floor": floor,
        "audit_note": (
            f"⚠ {below_floor} of {len(rows)} commit(s) in this range sit BELOW the "
            f"genesis floor {(floor or '')[:12]}. `crossref` claims nothing about them "
            f"— so they are refused here and unaudited there. Neither tool is wrong; "
            f"the audit was scoped to when recording began and this gate was not."
            if below_floor else None),
        "admitted": admitted,
        "admission_state": rows[-1]["admission_state"],
        "not_gating": rows[-1]["not_gating"],
        "commits": rows,
        # the union, so a caller can see the whole remaining job at once
        "missing": sorted({s for r in rows for s in r["missing"]}),
        "stale": sorted({s for r in rows for s in r["stale"]}),
        # ⛔⛔ THE UNION OF THE ROW-LEVEL FORGIVENESSES, because the top of the payload is where a
        # reader looks FIRST and the two who misread this never reached the rows. A field that
        # explains `complete: true` beside an unsatisfied count, but only inside `commits[n]`,
        # is the half-applied guard shape: the 2026-09-22 freeze caveat rendered in the BROKEN
        # state and was silent in the state that produced the defect.
        # ⚠ `steps` and not the full detail — the per-path list stays on the row it belongs to,
        # so this stays cheap on a long range.
        "stale_forgiven": sorted({e["step"] for r in rows
                                  for e in (r.get("stale_forgiven") or [])}),
        "failed": sorted({s for r in rows for s in r["failed"]}),
        "legacy": sorted({s for r in rows for s in r["legacy"]}),
        **({"refused": sorted({s for r in rows for s in r.get("refused") or []})}
           if consulted else {}),
        # ⭐ Disclosure, not a gate — see `_witness`. ALLOWED must not render the same
        # whether a whole family of steps looked at this push or never touched it.
        # ⚠ The base is the FIRST commit's PARENT, not the left side of `rev_range`.
        # It is the state this push departs from under `..` and `...` alike, and it
        # does not re-parse a range string a caller may have written either way.
        # ⭐⭐ THE CHANGED-PATH RATCHET. Unlike `witness`, this BLOCKS: see `_ratchet`.
        "ratchet": ratchet,
        # ⛔⛔ THE REGISTRY FREEZE, ON THE PUSH PATH AT LAST — AND ITS ABSENCE HERE WAS THE
        # 2026-09-07 DEFECT UNFIXED AT ITS SIBLING. `convergence_bar`'s own docstring records
        # the finding: *"`progress()` reported complete: true, satisfied 19/19 beside
        # bar.held: false — and gitRobot's status(), which embeds an inventory, surfaced the
        # 19/19 and not the broken bar. A reader of the gate's own status saw green."* That was
        # repaired by lifting the bar onto `inventory`. It was never lifted onto `can_push`,
        # which is the call that decides whether bytes reach the world.
        #
        # ⚠ MEASURED 2026-09-18: `inventory` answers `held: false` ("THE BAR MOVED MID-RUN")
        # for the live registry, and `can_push` did not carry the field at all. The freeze has
        # read broken since `cd3309a` on 09-16 and the push path never said so — three registry
        # versions and five days, including `a67ee7a`, which moved this gate's cost 43x.
        #
        # ⛔ AND A NAME COLLISION WAS HIDING IT. This response already publishes `push_bar`
        # (`tip_green` / `every_commit`), a DIFFERENT object. A reader who sees a key called
        # "bar" has every reason to believe the bar is reported, so the missing one could not be
        # noticed by reading the response. Hence `registry_freeze`, not `bar`: two distinct
        # objects may not share a word in one payload, which is the `EXIT_CODES` rule applied to
        # field names. ⚠ `inventory` keeps `bar` — renaming a published field is a coordinated
        # change, and the render below names both objects explicitly so neither is inferred.
        #
        # ⚠ REPORTED, NOT BLOCKING, and deliberately: making a stale freeze refuse would block
        # every push in the fleet this instant, which is a policy change and Tim's call. See
        # `.mcp-local/queue/gate-ratchets-only-bytes-it-has-seen.md` steps 5 and 6.
        # ⭐⭐ ALREADY PUBLISHED ON THE PUSH TARGET — its own field, never merged into
        # `forgiven`, because "a defect the tip fixed" and "not published by this push" are
        # different claims. `inherited_published.checked` is FALSE when policy has not opted in
        # or when the remote could not be reached to verify the tracking cache, and in both
        # cases NOTHING is forgiven — absence here must never read as "nothing qualified".
        "published_already": published_already,
        "published_already_count": len(published_already),
        "inherited_published": inherited,
        "registry_freeze": inventory_mod.convergence_bar(config),
        "witness": _witness(config=config, repo=repo,
                            base=rows[0]["commit"] + "^",
                            tip_files=tip_files, admitted=admitted),
        # ⛔⛔ THE CONDITION AS A **VALUE**, NOT ONLY AS A WARNING STRING. Added 2026-09-22 on
        # Tim's ruling, and the finding is the ZeroParadox session's: `can_push` reported 11
        # gating steps reading SATISFIED over **1123 in-scope paths never examined** —
        # `adversary` 98/121, `editorial` 99/122, `prior_art` 95/340 — and every number lived
        # in prose. **A step that examined a sliver was indistinguishable BY VALUE from one
        # that examined everything, and consumers branch on values.**
        #
        # ⭐ THE MODEL WAS ALREADY TWO FIELDS AWAY AND THAT IS WHY THIS IS EMBARRASSING RATHER
        # THAN SUBTLE: `witness` reports counts, so a caller can act on it. `unvalidated` was
        # per-commit tuples plus a rendered sentence, so the AGGREGATE — the number a reader
        # actually quotes — existed only in text. Their phrasing: this is `R-ZERONULL` at the
        # value level, an unknown rendering as a pass.
        #
        # ⚠ REPORTED, NOT BLOCKING, unchanged. Whether an unexamined path refuses a push is
        # `coverage.require_complete`, which is policy and is FALSE. This changes only what a
        # caller can READ without parsing a blob — which is the standard every other field on
        # this response is already held to.
        "coverage_gaps": _coverage_gaps(rows),
        # ⚠ AND THE SIBLING FINDING: a NARROWED row is green because the covering record
        # indicts OTHER paths, not because anything here was clean. Their phrasing, kept
        # because it is better than anything this module had: *"the row says pass; what it
        # records is that somebody else was convicted."* It was a list of display strings;
        # it is now a value a caller can branch on, with the source verdict split out.
        # ⚠ BUILT FROM THE STRUCTURED PAIRS ON EACH ROW, NEVER BY PARSING THE DISPLAY STRING
        # BACK APART. `narrowed` is `"step (from FAIL)"` for humans; re-splitting it here
        # would make the render the source of truth for a machine-readable field, so a
        # cosmetic wording change would silently alter what callers receive.
        "narrowed_passes": [
            {"step": s, "from_verdict": v}
            for s, v in sorted({p for row in rows
                                for p in (row.get("narrowed_pairs") or ())})],
    }


SHOWN = 5


def render(result: dict) -> str:
    """The human line.

    ⚠ LEADS WITH THE UNION, THEN A FEW COMMITS. `GRB-4` measured `history()`
    returning 194,296 characters at its own default -- "the tool whose stated purpose
    is answering 'did this guard ever fire?' after an incident cannot be read at the
    moment it is needed." A 46-commit range printing three lines each is that defect
    again. The union answers "what work remains" in four lines; the per-commit rows
    answer "which commit" and only the first few are needed to see the shape.

    ⚠ But the COUNT of un-shown commits is always printed. Silently showing five of
    forty-six would render like a complete answer, which is the thing this file
    refuses to do elsewhere.
    """
    if not result.get("ok"):
        return f"REFUSED  push  {result.get('why') or result.get('error')}"
    if result.get("empty_range"):
        return f"ALLOWED  push  {result['range']} — {result['why']}"
    if "commits" in result and not result["commits"]:
        return f"REFUSED  push  {result.get('why')}"

    # ⛔⛔ "NOT EVALUATED" AND "REFUSED, N SHORT" ARE DIFFERENT FACTS AND MUST NOT SHARE A LINE.
    # Reported by ZeroParadox 2026-09-03 against a real push: the headline read
    # `REFUSED push 13/13 commit(s) short` with every commit at `0/0`, under a correct ⚠⚠ line
    # saying the admission set was not set. Their words: **"the surface reads as a refusal and
    # means unconfigured, and those are different facts."**
    #
    # ⚠ "SHORT" MEANS MISSING REQUIRED KEYS. With nothing required, nothing is short — so the
    # headline asserted thirteen failures where zero checks had run, and `0/0` per commit reads
    # as satisfied-of-required rather than nobody-said-what-to-check.
    #
    # ⚠⚠ `allowed` STAYS FALSE. An unconfigured gate must fail closed; only the RENDERING
    # changes. `progress`, `coverage_gap` and `heal_plan` all REFUSE a bare call outright, and
    # this was the one sibling that computed a confidently misleading answer instead.
    #
    # ⭐ AND IT NAMES THE ALTERNATIVE RATHER THAN THE PROBLEM — Tim, 2026-09-03: *"instead of a
    # refusal you include the exact instructions that it needs to provide."* The ledger CANNOT
    # print the step names: the admission set lives in gitRobot's `admission.v1.json` and the
    # two-lists separation is deliberate. What it can do is name the tool that serves them.
    if result.get("admission_state") in ("EMPTY", "UNSET"):
        unset = result["admission_state"] == "UNSET"
        return "\n".join([
            f"NOT EVALUATED  push  {result['commits_in_range']} commit(s)  @ {result['range']}",
            f"  ⚠⚠ NOTHING GATED THIS RANGE — the admission set is "
            f"{'not set' if unset else 'empty'}, so no commit was checked against anything.",
            f"  ⚠ This is NOT a verdict on the commits. None of them is 'short': nothing was "
            f"required, so nothing could be missing. Treated as REFUSED because an unconfigured "
            f"gate fails closed.",
            "  TO GET A REAL ANSWER, pass both sets — the tip carries the push bar, the commits "
            "under it carry the bar that applied when they were made:",
            "",
            "      gitRobot:  requirements(action='push')     -> the push set",
            "      gitRobot:  requirements(action='commit')   -> the commit set",
            "",
            f"      can_push(rev_range='{result['range']}',",
            "               admission=<the push set>,",
            "               commit_admission=<the commit set>)",
            "",
            "  ⚠ The sets live in gitRobot's admission.v1.json, NOT in this ledger's registry — "
            "they differ, and asking the wrong one has already produced a wrong report. "
            "gitRobot's own push path fills them in automatically; only a direct call omits them.",
        ])

    # ⛔⛔ AND THE RATCHET MADE THIS THE THIRD INSTANCE OF THE DEFECT DIRECTLY ABOVE, IN THE SAME
    # LINE. Measured 2026-09-18, the day the ratchet shipped: a range it refuses ALONE renders
    # `REFUSED  push  0/10 commit(s) short` — because zero commits ARE short. Every commit has
    # every required verdict; what is missing is a signature on bytes the range CHANGES. So the
    # headline stated a true number and named it as the reason for a refusal it had no part in,
    # which is the 2026-09-03 finding with a new cause: **"the surface reads as a refusal and
    # means <something else>, and those are different facts."**
    #
    # ⚠ THE COUNT STAYS. It is true and a reader needs it; what it may not do is stand alone as
    # the explanation when something else is doing the refusing.
    owed_n = len((result.get("ratchet") or {}).get("owed") or [])
    counts = f"{result['blocking_count']}/{result['commits_in_range']} commit(s) short"
    if owed_n:
        counts += f", {owed_n} signature(s) owed on changed bytes"
    lines = [f"{'ALLOWED' if result['allowed'] else 'REFUSED'}  push  "
             f"{counts}  @ {result['range']}"]

    # ⚠⭐ NARROWED COVERAGE, ON THE PUSH PATH. Measured 2026-08-23: a step that
    # examined one file of 201 read SATISFIED. `inventory` names it; without this the
    # push path -- the one that matters -- would still be silent.
    thin = [r["thinnest"] for r in result.get("commits") or [] if r.get("thinnest")]
    if thin:
        step, seen, scope = min(thin, key=lambda t: t[1] / t[2] if t[2] else 1)
        # ⚠ THE COUNT AND THE TOTAL, not only the extreme — see `unvalidated` above. Naming
        # one step when nine are in the same state reads as an outlier rather than a
        # condition.
        # ⚠⚠ THE PROSE READS THE PUBLISHED FIELD, IT DOES NOT RE-DERIVE IT. Until 2026-09-22
        # this block recomputed the aggregate from the commit rows, so the sentence a human
        # read and the value a machine read were two computations of one fact with nothing
        # comparing them — and only the sentence carried the aggregate at all. One source,
        # two transports, which is the rule this fleet already applies to its vocabularies.
        gaps = result.get("coverage_gaps") or {}
        if gaps.get("steps"):
            lines.append(
                f"  ⚠ UNVALIDATED COVERAGE — {gaps['steps']} gating step(s) read SATISFIED "
                f"without examining their full scope: {gaps['paths_unexamined']} in-scope "
                f"path(s) never looked at. Thinnest is {gaps['worst_step']} at "
                f"{gaps['worst_examined']}/{gaps['worst_in_scope']} "
                f"(reported, not blocking; the same numbers are in `coverage_gaps`).")
        else:
            lines.append(f"  ⚠ NARROWED COVERAGE — thinnest gating step {step} examined "
                         f"{seen}/{scope} in-scope paths (reported, not blocking)")

    # ⚠⭐ NARROWED INDICTMENT, ON THE PUSH PATH — the sibling of the block above, and it was
    # missing for the same reason that one was until 2026-08-23: the argument got made where
    # it was noticed and not where it is read. A commit whose keys are green ONLY because the
    # covering records condemn paths outside its scope is a materially different fact from one
    # a checker examined and was happy with, and `ALLOWED` renders them identically.
    #
    # ⚠ REPORTED, NOT BLOCKING. The narrowing is correct behaviour — a verdict may not travel
    # to bytes nobody judged, in either direction. What must not happen is a reader being
    # unable to tell that it happened, which is the same standard `forgiven` is held to four
    # lines below.
    narrowed = sorted({n for r in result.get("commits") or [] for n in (r.get("narrowed") or [])})
    if narrowed:
        lines.append(f"  ⚠ NARROWED INDICTMENT — {len(narrowed)} gating step(s) pass because "
                     f"the covering record indicts OTHER paths, not because it was clean: "
                     + ", ".join(narrowed[:4])
                     + (f" (+{len(narrowed) - 4} more)" if len(narrowed) > 4 else ""))

    # ⚠⚠ A FORGIVEN COMMIT IS NAMED, ALWAYS. Under the TIP-GREEN bar an intermediate may carry
    # an honest FAIL and still publish, provided the tip fixed it. That is a real weakening of
    # what "ALLOWED" used to mean, and an ALLOWED line that renders identically whether the
    # range was clean or merely forgiven is the exact collapse this gate exists to prevent.
    # ⚠ A BAR NOBODY CONFIGURED IS WORTH SAYING OUT LOUD. It is not wrong — the default is
    # deliberate — but a reader asking "where is this set" deserves to learn the answer is
    # nowhere, rather than searching a policy file that does not contain it.
    if result.get("push_bar_source") == "default":
        lines.append(f"  ⚠ push bar '{result.get('push_bar')}' is the built-in DEFAULT — no "
                     f"`push.bar` in the loaded policy. `policy()` reports which file that is.")

    # ⭐⭐ A FAMILY THAT LOOKED AT NOTHING MUST SAY SO IN THE LINE, not only in the payload.
    # The push_bar_source defect above is the precedent: the caller who hit it was reading
    # RENDERED output, and a provenance field nobody sees is the same silence in a new field.
    w = result.get("witness") or {}
    if w.get("resolved") is False:
        lines.append(f"  ⚠ WITNESS UNKNOWN — {w.get('why')}")
    # ⛔⛔ THE ALARM WAS DEMOTED HERE AND THE DEMOTION WAS REVERTED THE SAME HOUR, BECAUSE AN
    # EXISTING TEST PROVED THE DISCRIMINATOR WAS A PROXY. Keeping the whole story, because the
    # mistake is more instructive than the fix.
    #
    # THE FINDING WAS REAL. ZeroParadox reported the ⚠⚠ firing over two deposited PDFs, and
    # Tim ruled that configuration CORRECT: a PDF is a rendered binary object, review judges
    # SOURCE, and the source→PDF link is already mechanically gated by `check_hashes` +
    # `pdf_coupling`. Measured on the live range: 67 changed paths, 53 outside every admitted
    # REVIEW step, 0 outside every family. An alarm that fires on a configuration nobody
    # intends to change teaches its reader to skip it, so it is not there on the day it means
    # something.
    #
    # ⛔⛔ BUT "COVERED BY ANOTHER FAMILY" IS NOT "THE RIGHT JUDGE LOOKED", AND THAT IS THE
    # PROXY. Demoting the ⚠⚠ whenever SOME family claimed the path failed
    # `test_a_family_that_examined_nothing_in_the_push_is_named` — the 2026-09-07 regression
    # test, where eleven prose files were covered by a MECHANICAL step and by no review step.
    # Under the demotion that defect would have printed as a mild aside. **A markdown file
    # checked for encoding is still unreviewed prose.** Tim's PDF ruling holds because the
    # SOURCE→artifact link is separately gated, not because the path has any family's claim
    # on it — and this code cannot tell those two apart from scope globs alone.
    #
    # ⭐ SO THE ⚠⚠ IS UNCHANGED AND `unclaimed_by_every_family` IS PUBLISHED BESIDE IT as the
    # strictly-worse case it genuinely is. The real discriminator — "is this a generated
    # artifact whose source is reviewed" — is registry knowledge this module does not have,
    # and inventing it here would be the same proxy one level down. It is Tim's and the
    # consumer's to declare, in the registry, where a reader can see it.
    #
    # ⚠ THE GUARD THAT CAUGHT THIS WAS WRITTEN IN SEPTEMBER FOR A DIFFERENT DEFECT and it
    # fired on a change made with a ruling in hand. That is the argument for keeping
    # regression tests whose original incident is long fixed.
    unclaimed = w.get("unclaimed_by_every_family") or []
    for fam, paths in sorted((w.get("unwitnessed_by_family") or {}).items()):
        lines.append(
            f"  ⚠⚠ NO {fam.upper()} STEP EXAMINED THIS PUSH — {len(paths)} of "
            f"{w.get('changed_paths')} changed path(s) fall outside the scope of every "
            f"ADMITTED {fam} step, so a green {fam} row prices a DIFFERENT set of files:")
        for path in paths[:SHOWN]:
            lines.append(f"       {path}")
        if len(paths) > SHOWN:
            lines.append(f"       … and {len(paths) - SHOWN} more")
        # ⭐ THE NEW FACT IS OFFERED AS CONTEXT, NOT AS AN EXCUSE — see the long note below.
        if unclaimed:
            lines.append(
                f"     ⛔ {len(unclaimed)} of them are claimed by NO family at all: "
                f"{', '.join(unclaimed[:3])}{' …' if len(unclaimed) > 3 else ''}")
        lines.append(
            f"     ⚠ Reported, NOT blocking — whether this refuses a push is the admission "
            f"set's call, not the ledger's.")
        # ⚠⚠ NAME WHAT THIS PRICES, IN THE LINE. The rule is this repo's first one and the
        # field above is where it was being broken: these counts price the LEDGER ADMISSION
        # layer only, and the pre-push hook enforces a second layer this server cannot see.
        # A reader who takes "unwitnessed" for "ungated" draws the wrong conclusion and the
        # wrong remedy — measured on `tools/verify/required.v2.json`, which is gated by a
        # BLOCKING hook routing leg and reads unwitnessed here.
        lines.append(
            f"     ⚠ These count 1 OF 2 ENFORCEMENT LAYERS — the ledger admission set. "
            f"The pre-push hook enforces "
            f"per-file `/rely` signatures over changed routed files with no admission key, "
            f"and this server cannot see that layer — so an unwitnessed path is a question "
            f"to ask, never proof that nothing gates it.")

    # ⛔⛔ A FORGIVENESS IS NEVER SILENT. Same standard `forgiven` is held to four lines down:
    # a commit that stopped blocking must say WHY, or a reader cannot tell a gate that passed
    # from a gate that was stepped around. Tim's ruling 2026-09-25 created this category; this
    # line is what keeps it auditable.
    if result.get("published_already"):
        pa = result["published_already"]
        lines.append(
            f"  ⚠ {len(pa)} commit(s) NOT BLOCKING BECAUSE THEY ARE ALREADY PUBLISHED on the "
            f"remote this push targets — this push publishes no new bytes from them:")
        for e in pa[:SHOWN]:
            lines.append(f"       {e['commit'][:12]}  already on {e['published_on']}  "
                         f"(short: {', '.join(e['short'][:4]) or '—'})")
        if len(pa) > SHOWN:
            lines.append(f"       … and {len(pa) - SHOWN} more")
        lines.append(
            f"     ⚠ PROVENANCE, NOT CHURN. A commit authored here whose blobs merely changed "
            f"before the tip is NOT in this list and still blocks. Verified against ls-remote, "
            f"so a stale tracking cache forgives nothing.")
    elif (result.get("inherited_published") or {}).get("checked") is False and result.get("commits"):
        # ⚠ SAY WHY IT COULD NOT BE CHECKED, rather than letting an empty list read as "none
        # qualified". The two are different facts and only one is an answer.
        _why = (result["inherited_published"] or {}).get("why") or ""
        if "not set" not in _why:
            lines.append(f"  ⚠ ALREADY-PUBLISHED FORGIVENESS NOT APPLIED — {_why}")

    if result.get("forgiven"):
        # ⚠ "a real FAIL" WAS WRONG THE MOMENT `failing` LANDED ON UNDECIDED. `failed` is
        # populated from status in ("FAIL", "UNDECIDED"), so a forgiven commit may carry a
        # DISPUTED verdict rather than a condemning one. Both are forgivable on the same
        # evidence — the bytes are gone from what the world will fetch — but a reader told
        # "FAIL" about an UNDECIDED is being handed the wrong claim, which is the defect
        # class this file exists to render honestly.
        lines.append(f"  ⚠ {result['forgiven_count']} commit(s) FORGIVEN under the "
                     f"{result.get('push_bar')} bar — each carries a real blocking verdict "
                     f"(FAIL or UNDECIDED) whose indicted bytes are ABSENT at the tip:")
        for f in result["forgiven"][:SHOWN]:
            lines.append(f"    {f['commit'][:12]}  {', '.join(f['steps'])}"
                         f"  fixed by tip: {', '.join(f['indicted_and_fixed_by_tip'][:3])}")
        if len(result["forgiven"]) > SHOWN:
            lines.append(f"    … and {len(result['forgiven']) - SHOWN} more")

    if result.get("audit_note"):
        lines.append("  " + result["audit_note"])

    # ⚠ The EMPTY/UNSET case returns early above with the full instruction block, so there is
    # no branch here. Left as a comment rather than deleted silently: a reader looking for where
    # the admission-state warning went should find it, not conclude it was dropped.

    # ⭐⭐ THE RATCHET NAMES EVERY SIGNATURE IT WANTS. A gate that refuses without saying what
    # would clear it forces the caller to re-derive the obligation, and the caller cannot: the
    # rule lives here and the changed-path set lives in git. Measured 2026-09-18 as the whole
    # point of the disclosure -- the consumer must be able to count and place the rounds itself.
    rt = result.get("ratchet") or {}
    owed = rt.get("owed") or []
    if owed:
        by_step = {}
        for o in owed:
            by_step.setdefault(o["step"], []).append(o["path"])
        lines.append(f"  ⛔ CHANGED BYTES NOT JUDGED — {len(owed)} signature(s) owed over "
                     f"{rt.get('changed_paths')} changed path(s). These files MOVED in this push and "
                     f"no verdict covers the new bytes:")
        for step in sorted(by_step):
            paths = sorted(by_step[step])
            shown = ", ".join(paths[:4]) + (f" (+{len(paths) - 4} more)" if len(paths) > 4 else "")
            lines.append(f"       {step:14} {len(paths):3} path(s)  {shown}")
        lines.append("     INSTEAD: run each step over the paths named and record; the backlog is "
                     "NOT owed — only what this push changes.")
        if rt.get("renames_exempt"):
            lines.append(f"     ⚠ {len(rt['renames_exempt'])} pure rename(s) exempt: the bytes did "
                         f"not move, so what was judged still holds.")

    # ⛔⛔ "STALE" AND "OWED" NAME DIFFERENT WORK, AND THE RENDER LISTED BOTH AS IF THEY WERE ONE.
    # Raised by the ZeroParadox session 2026-09-18, mid-drill, seeing `prior_art` named twice from
    # two causes: *"a reader who clears only the STALE row has not cleared the ratchet, and nothing
    # says the two are satisfied by the same action here. They happen to be, this time. Are there
    # cases where they are not?"*
    #
    # ⭐ MEASURED THE SAME HOUR OVER 11 LIVE ARCS: the two sets differ in TEN. Their hypothetical
    # is the COMMON case, not the corner:
    #
    #     09-05, 09-06   STALE `guards`, ratchet owes NOTHING  -> clearing the ratchet clears nothing
    #     09-14          STALE `prior_art`, ratchet owes NOTHING
    #     09-08/09/11/16 owed, nothing stale                   -> no existing verdict to re-run
    #     09-12          STALE {guards, prior_art}, owed {prior_art}
    #     09-13          the only arc where they coincide
    #
    # ⚠ AND THE REMEDIES CAN BE DIFFERENT IN KIND, NOT ONLY IN SCOPE. A step goes STALE when its
    # EVIDENCE moves — edit `tools/verify/*` and every commit citing that checker is stale through
    # no change of its own — and no number of content rounds clears that. The ratchet only ever
    # asks about CONTENT this range changed. Telling a caller to "run each step over the paths
    # named" while a stale row needs a different action entirely is the remedy defect this file
    # fixes everywhere else.
    tip_rows = [c for c in (result.get("commits") or []) if c.get("is_tip")]
    stale_steps = set(tip_rows[0].get("stale") or []) if tip_rows else set()
    owed_steps = {o["step"] for o in owed}
    if stale_steps != owed_steps and (stale_steps or owed_steps):
        stale_only = sorted(stale_steps - owed_steps)
        owed_only = sorted(owed_steps - stale_steps)
        lines.append("  ⚠⚠ 'STALE' AND 'OWED' ARE DIFFERENT WORK HERE — CLEARING ONE DOES NOT "
                     "CLEAR THE OTHER:")
        if stale_only:
            lines.append(f"       STALE, not owed:  {', '.join(stale_only)}  — the ratchet does NOT "
                         f"ask about these; they are stale against their OWN subjects or evidence, "
                         f"and a round over the paths named above will not touch them.")
        if owed_only:
            lines.append(f"       OWED, not stale:  {', '.join(owed_only)}  — no existing verdict "
                         f"to re-run; these paths have never been judged at these bytes.")
        if stale_steps & owed_steps:
            lines.append(f"       BOTH:             {', '.join(sorted(stale_steps & owed_steps))}  "
                         f"— one round may clear both, but only if it covers the paths named above.")

    # ⛔⛔ THE REGISTRY FREEZE, SAID OUT LOUD ON THE PUSH PATH — see `registry_freeze` above for
    # why it was absent and why it is not called `bar` here.
    # ⚠ IT NAMES BOTH OBJECTS EXPLICITLY. `push_bar` and this are different things and the word
    # "bar" belongs to neither alone; a line that says only "the bar moved" is the collision
    # again, in prose.
    fz = result.get("registry_freeze") or {}
    if fz.get("frozen") and not fz.get("held"):
        lines.append(
            f"  ⚠⚠ THE REGISTRY FREEZE IS BROKEN — the rule set moved since the checkpoint was "
            f"taken, so every green row in this range was judged against a scope that has since "
            f"changed, and a widened scope does NOT re-open a row that already went green.")
        # ⛔⛔ THE "NOW" HALF MUST COME FROM THE SAME BASIS AS THE "FROZEN" HALF, AND UNTIL
        # 2026-09-21 IT DID NOT. Measured on the live fleet that day, under the scope_digest
        # basis this line read:
        #     frozen at 211569c3d832  ·  registry now d59065e57f7f
        # `frozen_at` was a SCOPE DIGEST and `registry_sha` is a FILE HASH. Two different
        # objects printed as a before/after pair — they would differ even if nothing whatever
        # had moved, so the line cannot distinguish "the bar moved" from "these are not the
        # same kind of hash". That is this repo's founding defect class, in the render of the
        # field added to remove it.
        # ⚠ AND THE REMEDY IT IMPLIED WAS ACTIVELY HARMFUL: the very next line tells the reader
        # to re-freeze, and the only hash on offer to re-freeze WITH was the file sha. Writing
        # that into `frozen_scope_digest` never compares equal to a scope digest, so the freeze
        # would read BROKEN forever and the fix would be indistinguishable from the fault.
        # ⭐ `basis` was already on the payload — `convergence_bar` names the object it compared
        # precisely so nobody downstream has to infer it. This render inferred it anyway.
        _basis = str(fz.get("basis") or "")
        _now = fz.get("scope_digest") if _basis == "scope_digest" else fz.get("registry_sha")
        _what = "scope digest" if _basis == "scope_digest" else "registry file sha"
        lines.append(
            f"       frozen at {str(fz.get('frozen_at'))[:12]}  ·  now "
            f"{str(_now)[:12]}   (both are the {_what}; basis: {_basis})")
        # ⚠ AND THIS LINE NAMED A FIELD TOO — hardcoded to the LEGACY one, so under the
        # scope_digest basis it pointed the reader at a setting the live freeze does not use.
        # Caught 2026-09-21 by the assertion one test wrote for the line ABOVE it: the same
        # defect twice in four lines, because a literal field name in prose is a copy.
        _field = ("policy.convergence.frozen_scope_digest" if _basis == "scope_digest"
                  else "policy.convergence.frozen_registry_sha")
        lines.append(
            f"     ⚠ This is the CONVERGENCE freeze ({_field}), NOT "
            "the `push_bar` above — different objects, and only one of them is a checkpoint.")
        # ⚠ AND THE REMEDY NAMES THE FIELD AND THE VALUE (`_field` above), because the field it
        # must be written into differs BY BASIS and the two hashes are one paste away from
        # each other.
        lines.append(
            f"     INSTEAD: re-freeze deliberately — set {_field} to {str(_now)[:12]}… (the "
            f"{_what} above) and expect the numbers to mean less than they did, or revert the "
            "registry. Reported, NOT blocking.")
        # ⛔⛔ THE ORDERING TRAP, AND IT LIVES HERE BECAUSE HERE IS WHERE SOMEONE ABOUT TO
        # RE-FREEZE IS READING. Raised by the ZeroParadox session 2026-09-22 while briefing a
        # re-freeze Tim had just authorised — caught before it bit, which is why it is worth
        # writing down rather than only fixing.
        #
        # `reason` is a SERVED key, so it is inside the enforcement digest. Freeze to the
        # current digest, then edit a served key in the same change, and the checkpoint is
        # STALE ON ARRIVAL — `can_push` will correctly report BROKEN on a freeze taken minutes
        # earlier, and the write itself gives no sign at the time.
        #
        # ⚠⚠ AND THE TWO OPERATIONS CO-OCCUR BY CONSTRUCTION, which is what makes it a trap
        # rather than a footnote: re-freezing is exactly the moment someone is already editing
        # the registry, because a moved bar is what sent them here. Nothing in the mechanism
        # enforces the order.
        #
        # ⭐ Placed in the LINE and not only in a docstring on today's own evidence: a caveat
        # in a long description does not survive contact with a specific result line. The
        # consumer had the two-layer `rely` caveat in a tool description they had read, and
        # still drew the conclusion it forbids, because the number is met in a different frame.
        if _basis == "scope_digest":
            lines.append(
                "     ⛔ ORDER MATTERS: `reason` is a SERVED key and is INSIDE this digest. If "
                "you are also editing the registry, EDIT FIRST, derive the digest from the "
                "post-edit file, then freeze — one commit. Freezing first makes the checkpoint "
                "stale on arrival, silently, and it surfaces only on the next call.")
    elif not fz.get("frozen") and fz.get("note"):
        lines.append(
            "  ⚠ NO REGISTRY FREEZE IS SET, so there is no agreed rule set to measure this push "
            "against; scope may widen mid-run and will not re-open a green row. Reported, NOT "
            "blocking.")

    # the whole remaining job, one line per kind
    #
    # ⚠ `refused` DISPLAYS AS "REFUSED CLAIM", NOT "REFUSED". The headline of this same render
    # opens `REFUSED  push`, and a union line opening `REFUSED  check_encoding` sits one
    # indent under it saying something different: that the LEDGER declined a CLAIM, not that
    # the PUSH was declined. Caught 2026-09-13 when the control written for this line picked
    # up the headline instead.
    for label, shown_as, remedy in (
            ("missing", "MISSING", "python tools/verify/batch.py precommit"),
            ("stale", "STALE", "re-run — recorded against different bytes"),
            ("failed", "FAILED", "fix it"),
            ("legacy", "LEGACY", "re-record — superseded subject scheme"),
            ("refused", "REFUSED CLAIM", "fix the record the emitter sends — re-running "
                                         "reproduces the refusal")):
        names = result.get(label) or []
        if names:
            shown = ", ".join(names[:8]) + ("…" if len(names) > 8 else "")
            lines.append(f"  {shown_as:8} {shown}      INSTEAD: {remedy}")

    blocking = [r for r in result["commits"] if not r["complete"]]
    if blocking:
        lines.append(f"  commits short ({len(blocking)}):")
        for row in blocking[:SHOWN]:
            # ⛔⛔ `0/0` FOR AN UNSET ADMISSION READS AS SATISFIED-AND-YET-BLOCKING, AND IT COST
            # THE CONSUMER A WRONG DIAGNOSIS. Reported 2026-09-18: they called `can_push` with
            # only the PUSH set, so every INTERMEDIATE — judged under `commit` — had no admission
            # at all, rendering `0/0 short`. They read it as a plumbing artifact and went looking
            # elsewhere; `progress(action='commit')` held the real answer.
            #
            # ⚠⚠ THIS IS THE 2026-09-03 HEADLINE DEFECT ONE LINE DOWN. That one said
            # `REFUSED 13/13 commit(s) short` when the set was merely unset, and their words then
            # were *"the surface reads as a refusal and means unconfigured, and those are
            # different facts."* The headline was fixed and the PER-COMMIT rows kept the shape —
            # the same fix applied at one level and not its sibling, which is the `SH-3` pattern
            # this file has now hit four times.
            #
            # ⚠ "SHORT" MEANS MISSING REQUIRED KEYS. With nothing required, nothing is short.
            if row.get("admission_state") in ("UNSET", "EMPTY"):
                lines.append(
                    f"    {row['commit'][:12]}  admission {row['admission_state']} — NOT a "
                    f"coverage failure; nothing declared what must gate this commit, so no "
                    f"count is meaningful. Pass `commit_admission` (gitRobot "
                    f"admission(action='commit')) to judge intermediates.  {row['subject']}")
            else:
                lines.append(f"    {row['commit'][:12]}  {row['satisfied']}/{row['required']}"
                             f"  {row['subject']}")
        if len(blocking) > SHOWN:
            lines.append(f"    … and {len(blocking) - SHOWN} more — pass --json for "
                         f"every commit")

    if result.get("not_gating"):
        n = result["not_gating"]
        lines.append(f"  not gating push: {len(n)} registered type(s) — "
                     f"{', '.join(sorted(n)[:8])}"
                     f"{'…' if len(n) > 8 else ''} (promote in the admission set)")
    return "\n".join(lines)
