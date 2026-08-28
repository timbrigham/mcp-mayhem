"""FastMCP server exposing verdictLedger over streamable HTTP.

Run:
    ZPLEDGER_DATA=... python -m ledger_server.server
    # ZPLEDGER_HOST (127.0.0.1), ZPLEDGER_PORT (8011), ZPLEDGER_ACTOR (mcp),
    # ZPLEDGER_REPO, ZPLEDGER_POLICY, ZPLEDGER_REQUIRED, ZPLEDGER_GITOPS

⚠⚠ THE MODULE PATH `ledger_server` IS LOAD-BEARING — never `mcp_server` (sjv),
never `gitrobot_server` (gitRobot). The supervisor identifies a running server by
process name plus a command-line substring, with no working-directory or port
filter, AND a repair force-kills every machine-wide match. A shared module path is
not merely ambiguous, it is actively collateral-killing.

⚠⚠ EVERY TOOL IS ASYNC AND OFFLOADS TO A WORKER THREAD. FastMCP calls a
synchronous tool function directly on the event loop, so any blocking work stalls
the whole server including the health endpoint the supervisor polls every 30s.
Measured on gitRobot 2026-08-22: a long call got the server declared Down and
killed mid-run, losing both the result and its audit trail. `signals`, `coverage`
and `crossref` all scan the whole stream and grow. A test asserts every REGISTERED
tool is a coroutine so this cannot regress.

⚠ THIS SERVER IS A MANDATORY DEPENDENCY OF EVERY COMMIT AND PUSH. When it is down,
nothing lands — intentional, not a fault. The remedy for a dead server is to start
it, not to add a bypass.
"""

from __future__ import annotations

import functools
import os
from typing import Any, Optional

import anyio.to_thread

from mcp.server.fastmcp import FastMCP

from core import canpush as canpush_mod
from core import crossref as crossref_mod
from core import inventory as inventory_mod
from core import render as render_mod
from core import signals as signals_mod
from core.errors import LedgerError, ValidationFailure
from core.ledger import Ledger

ACTOR = os.environ.get("ZPLEDGER_ACTOR", "mcp")
REPO = os.environ.get("ZPLEDGER_REPO", r"C:\Workspace\ZeroParadox")

mcp = FastMCP(
    "verdictLedger",
    host=os.environ.get("ZPLEDGER_HOST", "127.0.0.1"),
    port=int(os.environ.get("ZPLEDGER_PORT", "8011")),
)


def _ledger() -> Ledger:
    # Fresh per call so config edits take effect without a restart — that is the
    # behavioural proof that thresholds are data rather than constants.
    return Ledger()


async def _guard(fn, *args, **kwargs) -> dict:
    try:
        return {"ok": True, **await anyio.to_thread.run_sync(
            functools.partial(fn, *args, **kwargs))}
    except ValidationFailure as exc:
        # ⚠ Typed distinctly from every other failure. A caller must never confuse
        # "rejected" with "unavailable" — one is terminal, the other is retryable,
        # and conflating them is how a rule gets retried past.
        return {"ok": False, "error_type": "validation", "errors": exc.violations,
                "error": str(exc)}
    except LedgerError as exc:
        return {"ok": False, "error_type": exc.error_type, "error": str(exc)}


def _files(ref: str) -> dict:
    """path -> GIT BLOB ID for the content being promoted.

    ⚠⚠ THE BLOB IS NOT IN THE SAME FIELD IN THE TWO COMMANDS, AND READING IT FROM THE
    WRONG ONE COST THE ENTIRE STAGED BASIS.

        git ls-files -s   ->  <mode> <blob> <stage> TAB <path>     blob is field 1
        git ls-tree  -r   ->  <mode> blob  <sha>    TAB <path>     sha  is field 2

    This took field 2 for BOTH. For `ls-tree` that is the sha and correct; for
    `ls-files` it is the STAGE, which is `0` on every unconflicted entry. So
    `ref="staged"` returned {path: "0"} for all 503 tracked files, no subject could
    ever match one, and EVERY key at the staged basis read STALE or MISSING for ever.

    ⚠ IT FAILED CLOSED, WHICH IS WHY IT SURVIVED. `complete` requires stale == 0, so
    actions were refused rather than admitted — and an unsatisfiable gate and a
    correctly-blocking gate look identical from outside. Found 2026-08-25 only because
    a `pdf_coupling` PASS whose 40 subjects matched the index EXACTLY still reported
    `STALE, covered 0`.

    ⚠⚠ THE MIRROR DEFECT, THREE IMPLEMENTATIONS DEEP. `client/record.py` parses
    `ls-files -s` with field 1 (right); gitRobot's `_blobs` takes the field as a
    parameter and names the difference (right); this took field 2 (wrong). And the
    unit tests never reached it: every inventory test passes a `files` dict in
    directly, so the one function that builds that dict in production had no coverage
    at all.
    """
    import subprocess
    from core.errors import Unavailable
    # ⭐⭐ ASK GIT FOR THE FIELD BY NAME. `--format` (ls-tree 2.36, ls-files 2.38)
    # makes both commands print the SAME two columns, so there is no field to count
    # and no per-command layout to remember. That is what actually removes the class:
    # `%(objectname)` cannot accidentally be the stage.
    #
    # ⚠ STILL THE GIT BINARY, ON PURPOSE. A native binding (libgit2) would remove the
    # parse too, and would introduce something worse in exchange: it REIMPLEMENTS git,
    # and this comparison is only meaningful if the id equals what `git add` actually
    # wrote. Filters are live here — ZeroParadox's .gitattributes mandates LF for
    # *.json, and CRLF moved `policy_sha` on 2026-08-25 — so a binding that computed a
    # filtered blob even slightly differently would produce records that append
    # cleanly and read STALE for ever. That is the 2026-08-23 sha256 defect again,
    # subtler and harder to find. `client/record.py` already refuses to hash files
    # itself for exactly this reason.
    staged = (ref == "staged")
    fmt = "--format=%(objectname)%x09%(path)"
    args = (["ls-files", fmt] if staged else ["ls-tree", "-r", ref, fmt])
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    # ⚠⚠ AN UNSUPPORTED `--format` PRINTS `fatal:` TO STDERR AND NOTHING TO STDOUT,
    # which would yield {} — every key MISSING, the whole gate unsatisfiable, and
    # fail-closed in the way that hides. Exactly how the stage-column bug survived.
    # Refuse loudly instead of returning an empty world.
    if proc.returncode != 0 or not proc.stdout.strip():
        raise Unavailable(
            f"git {' '.join(args[:2])} produced nothing for ref {ref!r} in {REPO}: "
            f"{(proc.stderr or '').strip()[:200]}. `--format` needs git >= 2.38 "
            f"(ls-files) / 2.36 (ls-tree). An empty file list is NOT served as an "
            f"empty repository — every key would read MISSING and the gate would be "
            f"unsatisfiable rather than merely blocking.")
    out = {}
    for line in proc.stdout.splitlines():
        if "\t" not in line:
            continue
        blob, path = line.split("\t", 1)
        out[path.strip()] = blob.strip()
    return out


# -- writes -------------------------------------------------------------------

@mcp.tool()
async def append(record: dict) -> dict:
    """Append one verdict. Validated against V1-V18; REFUSES anything short.

    ⚠ THIS DOCSTRING IS THE WRITING GUIDE. `client/record.py` carries the same advice
    for callers that import it, and an agent calling this tool directly never sees
    that file — which is how a correct emitter came to be written against half the
    contract. If you are about to hand-build a record, read to the end.

    THE KEY IS `step@basis#revision`. Nothing else. An identical record at an
    occupied key dedupes and returns `appended: false`; a DIFFERENT one at the same
    key is refused by V11 as a conflict, naming the field that moved.

    HOW TO PICK `decided.how` — this is the field agents get wrong:

      mechanical  a computation ran. REQUIRES `evidence` on a PASS (V16): the checker
                  module's {path, git_blob_id}. Editing that module then stales the
                  key, which is the point.
      delegated   ONE agent round under a named brief. REQUIRES `who` (the gate) and,
                  on a PASS, `evidence` naming the BRIEF. tier must be "A". This is
                  the route for a review gate (V17).
      agreement   a real panel: V3 wants `agreed == passes >= policy.min_passes`.
                  ONE record carries the whole round; do NOT write one per pass.
      signature   a HUMAN accepted a verdict the round did not produce. `who` is a
                  person (V5). Never an agent's name — `delegated` is for that.
      override    a REGRADE: "the gate erred". V12 forbids overriding your own prior
                  decision on a key without unanimity.

    ⭐⭐ SPLIT A MIXED ROUND. A step that examined forty files and failed on one emits
    a PASS over the thirty-nine and a FAIL over the one — that is what keeps coverage
    exact, and a single FAIL over all forty leaves the thirty-nine with NO passing
    coverage for ever. Both records carry the same basis; the second needs
    `revision: 1`, because `(step, basis, revision)` is unique. Nothing is superseded:
    revision only supersedes WITHIN one content key, and disjoint subject sets never
    collide.

    ⚠ FINDINGS THAT SURVIVE A PASS go in `outstanding` — [{severity, note, path}].
    Only `ordinary` may ride a PASS (V18); bedrock or blocking must FAIL. This is
    STOP-ORDINARY: reviewed, ordinary findings left, loop cap reached, proceed.

    ⚠ `subjects` is WHAT THE VERDICT IS ABOUT, carrying git BLOB IDs — the value
    `git ls-tree` prints, never a content digest of the file. `inputs` is for
    AGGREGATES and holds RECORD KEYS, never blob ids (V4).

    ⚠ `run.id` is required (V9). Export ZPLEDGER_RUN before the run; a hand-run sets
    it exactly the way the pipeline does.

    ⚠ A REFUSAL IS TERMINAL. Do not retry it — fix the record. Retrying a rejected
    record is how a validation rule gets worn down, and the errors list names every
    violation at once so one round trip is enough."""
    return await _guard(_ledger().append, record)


@mcp.tool()
async def sign(step: str, subjects: list[dict], who: str, reason: str,
               basis: dict, tier: str = "H") -> dict:
    """ACCEPT — "you are right, we ship anyway". The FAIL stands as carried debt.

    `who` is REQUIRED and is NEVER verified. A signature is an ATTRIBUTION, not an
    authentication: it makes a decision attributable after the fact, which is the
    whole and only claim being made."""
    return await _guard(_ledger().sign, step=step, subjects=subjects, who=who,
                        reason=reason, basis=basis, tier=tier)


@mcp.tool()
async def override(step: str, subjects: list[dict], who: str, reason: str,
                   basis: dict, tier: str = "H") -> dict:
    """REGRADE — "you are wrong, the gate erred".

    Feeds the OPPOSITE signal to `sign` and shares no code path with it: an accept
    is corpus debt, an override is evidence the STEP is defective.

    ⚠ V12: on a non-signable-class finding, `who` must differ from the signer of
    the revision it replaces — otherwise a finding is sudo-ed away by the person it
    was raised against, which is the one move that could unmake every other rule."""
    return await _guard(_ledger().override, step=step, subjects=subjects, who=who,
                        reason=reason, basis=basis, tier=tier)


@mcp.tool()
async def genesis(commit: str, note: Optional[str] = None) -> dict:
    """Seed the recording floor: the commit from which crossref claims anything.

    ⚠ A fact about when RECORDING began — never a claim that earlier work was
    verified. Without it every prior commit is a permanent P1 orphan, and a warning
    nobody can act on is one people learn to scroll past."""
    return await _guard(_ledger().seed_genesis, commit, note)


# -- reads --------------------------------------------------------------------

@mcp.tool()
async def validate(record: dict) -> dict:
    """Schema plus V1-V18. Pure, no write — use it to check a record BEFORE
    appending. Returns {ok, errors[]} with EVERY
    violation, not just the first — one rule per round trip is how a caller gives
    up and works around the thing."""
    return await _guard(_ledger().validate, record)


@mcp.tool()
async def get(id: str) -> dict:
    """One record by id."""
    return await _guard(lambda: {"record": _ledger().get(id),
                                 "found": _ledger().get(id) is not None})


@mcp.tool()
async def find(step: Optional[str] = None, verdict: Optional[str] = None,
               tier: Optional[str] = None, since: Optional[str] = None,
               subject_sha: Optional[str] = None, limit: int = 50) -> dict:
    """Query the stream. `count` is the full match total, `returned` is how many came back."""
    return await _guard(_ledger().find, step=step, verdict=verdict, tier=tier,
                        since=since, subject_sha=subject_sha, limit=limit)


@mcp.tool()
async def render(id: str) -> dict:
    """THE single renderer for a human verdict line.

    Everything that prints a verdict calls this — the pre-push echo, the manifest
    rows, the tag message. Two representations written independently is a report
    printing FAIL rows over an exit code of 0."""
    return await _guard(_sync_render, id)


def _sync_render(record_id: str) -> dict:
    rec = _ledger().get(record_id)
    if rec is None:
        return {"line": None, "found": False}
    return {"line": render_mod.render(rec), "found": True}


@mcp.tool()
async def requirements(action: Optional[str] = None) -> dict:
    """THE SINGLE COPY of the type registry. gitRobot reads it from here.

    ⚠ Two copies of the requirement list would make every inventory a lie in the
    most convincing possible way: both sides internally consistent, disagreeing
    about what "complete" means.

    REQUIRED BY DEFAULT — a registered type binds on every action unless an entry
    says otherwise, and a narrowing with no `reason` is ignored so the type stays
    required. Inclusion is free; exclusion takes effort."""
    return await _guard(lambda: {"action": action,
                                 "types": _ledger()._require_config().requirements(action)})


@mcp.tool()
async def policy() -> dict:
    """Thresholds, actions, min_passes, the genesis floor, and the policy sha.

    Every value the process compares against is here rather than in code. Change a
    threshold and the verdict changes with no restart — that is the behavioural
    proof it is data."""
    return await _guard(_sync_policy)


def _sync_policy() -> dict:
    led = _ledger()
    cfg = led._require_config()
    return {"policy": cfg.policy, "config_sha": cfg.config_sha,
            "actions": cfg.actions, "min_passes": cfg.min_passes,
            "max_depth": cfg.max_depth, "genesis": cfg.genesis,
            # ⚠⚠ WHERE THE BAR WAS ACTUALLY READ FROM. Added 2026-08-25 after a
            # deployment served the registry from the ledger's own repo for three days
            # while §7, `config.py`'s docstring and §0's build table all said it came
            # from ZeroParadox's `tools/verify`. Every reader of every one of those
            # came away believing the correct thing, and nothing could contradict them:
            # this call returned the CONTENT and the sha, never the PATH. It surfaced
            # only because a sibling session went looking for the file and could not
            # find it.
            #
            # ⚠ A `config_sha` proves two readers see the same BYTES. It cannot tell
            # either of them which FILE those bytes came from, which is the question
            # that was unanswerable.
            **cfg.paths()}


@mcp.tool()
async def inventory(action: str, ref: str = "staged",
                    admission: Optional[list[str]] = None) -> dict:
    """Required vs satisfied vs MISSING for a ref — the complete key set for an action.

    ⚠ The requirement set is declared IN ADVANCE. An inventory assembled from "the
    records that happen to exist" is worthless, because "3 of 3 passed" and "5
    never ran" render identically.

    Six statuses and none may collapse into another: SATISFIED · STALE (examined,
    content moved — re-run) · MISSING (never examined — run at all) ·
    NOT_APPLICABLE (a `when` glob did not match, and it carries the glob) ·
    LEGACY_IDENTITY (recorded under the superseded `sha256` scheme — RE-RECORD, not
    re-run) · FAIL/UNDECIDED. `complete` is true only when missing, stale, undecided,
    failed and legacy are all zero — gitRobot REQUIRES that; the ledger COMPUTES it.

    ⚠⚠ COVERED IS NOT PASSING, AND THIS IS THE FIELD MOST OFTEN MISREAD.
    `subjects_covered` counts paths some record examined at THIS content — including
    a record that FAILED. So a 70-subject FAIL makes all 70 covered and none of them
    passing, and the step accumulates no usable coverage. If you want "which paths
    still owe a PASS", call `coverage_gap`; it is PASS-only and returns the list.

    ⚠ THE ROW'S VERDICT IS THE WORST COVERING VERDICT, not the newest and not the
    first. A step with a FAIL over some paths and a PASS over others reads FAIL, and
    `record_id` names the record that failed. (Until 2026-08-28 it named whichever
    record covered the alphabetically-first path, which let a recorded FAIL go
    invisible when its filenames sorted late.)

    ⚠ EXTRA NUMBERS THAT DO NOT BLOCK BUT SHOULD BE READ: `subjects_unexamined`
    (in-scope paths this step has NEVER examined — `guards` once read SATISFIED over
    4 of 504), `evidence_stale` (the checker or brief that produced the verdict has
    moved — re-run), `unscoped` (paths a step examined that its declared scope
    excludes), `dead_patterns` (a glob that matches nothing, or that silently drops
    paths a looser form would catch), and `outstanding` (findings riding a PASS under
    V18). Set `policy.coverage.require_complete` to make unexamined paths BLOCK.

    ⚠⚠ TWO LISTS. `admission` names which registered types GATE this action; the registry
    says only what may be RECORDED. Twenty experimental gates recording while three admit a
    push is intended. Omitting `admission` is NOT an empty set — it means nobody said what
    gates this, and it refuses."""
    return await _guard(_sync_inventory, action, ref, admission)


def _sync_inventory(action: str, ref: str, admission=None) -> dict:
    led = _ledger()
    cfg = led._require_config()
    inv = inventory_mod.build(config=cfg, records=led.store.records(),
                              action=action, files=_files(ref), ref=ref,
                              admission=admission)
    inv["config_sha"] = cfg.config_sha
    inv["line"] = render_mod.render_inventory(inv)
    return inv


@mcp.tool()
async def coverage_gap(action: str = "push", ref: str = "staged",
                       admission: Optional[list[str]] = None,
                       step: Optional[str] = None, limit: int = 200) -> dict:
    """THE WORK ORDER: which paths does each admitted step still owe a PASS at THIS
    content? Ask it again rather than caching the answer — it changes as work lands.

    Returns per step: `applies_to`, `have`, `missing`, the missing `paths` (capped by
    `limit`, with `truncated` counting the rest), and a `remedy`.

    ⚠ DIFFERENT QUESTION FROM `coverage`. That asks "has ANY step ever named this
    path?" — a floor. This asks, per step, "is there a PASSING verdict over the bytes
    that are here NOW?" A path examined last week by a step that has since gone stale
    counts for `coverage` and is missing here.

    ⚠ PASSING ONLY, and the `remedy` says which kind of work each step needs. A step
    that covers its whole scope and passes none of it does not need re-running — it
    needs its findings fixed. Measured 2026-08-25: editorial, adversary and rely were
    each 0 have / all missing, for exactly that reason.

    ⚠ `admission` is required: nobody said what gates this action is not the same as
    nothing gating it."""
    return await _guard(_sync_coverage_gap, action, ref, admission, step, limit)


def _sync_coverage_gap(action, ref, admission, step, limit) -> dict:
    led = _ledger()
    cfg = led._require_config()
    if admission is None:
        from core.errors import UsageError
        raise UsageError(
            "coverage_gap requires an admission set — which steps gate this action. "
            "Omitting it is not an empty set; it means nobody said, and answering "
            "anyway would report a work order that gates nothing.")
    out = inventory_mod.coverage_gap(config=cfg, records=led.store.records(),
                                     action=action, files=_files(ref),
                                     admission=admission, step=step, limit=limit)
    out["ref"] = ref
    return out


@mcp.tool()
async def coverage(ref: str = "HEAD") -> dict:
    """Tracked paths MINUS the union of every `subjects` entry ever recorded.

    ⚠ On an empty stream this reports EVERYTHING uncovered, never a clean bill of
    health. Day one is exactly when the stream is empty."""
    return await _guard(lambda: inventory_mod.coverage(
        records=_ledger().store.records(), paths=list(_files(ref))))


@mcp.tool()
async def can_push(rev_range: str, admission: Optional[list[str]] = None,
                   commit_admission: Optional[list[str]] = None,
                   action: str = "push", limit: int = 500) -> dict:
    """⭐⭐ THE ONE QUESTION A CLIENT ASKS: may this RANGE be pushed?

    §12-0-alpha: "these are the keys needed, does commit xyz have them so we can push
    safely. There should be a substantial reduction in the amount of extra stuff to
    compute." The caller hands over a range expression and obeys the answer. It
    assembles no file list, hashes nothing, and re-derives no completeness.

    ⚠⚠ EVERY COMMIT IN THE RANGE, NOT JUST THE TIP. A push publishes a range --
    measured 2026-08-23, a push logged `scope 1 ref(s) -- range 5892cbc..55f2d6a`, 43
    commits, while the gate asked only about HEAD. Gating the tip certifies the content
    that will EXIST while intermediate commits ride along unexamined, and those are
    just as published: fetchable, bisectable and citable forever. `crossref` measured
    eight of them NOT_RUN. That is SCOPE-1 reborn inside the fix for it.

    ⚠ An over-long range REFUSES rather than truncating: an answer about part of a
    range renders identically to one about all of it.

    ⚠ `admission=None` is not an empty set -- it means nobody said what gates this."""
    return await _guard(_sync_can_push, rev_range, admission, commit_admission,
                        action, limit)


def _sync_can_push(rev_range, admission, commit_admission, action, limit) -> dict:
    led = _ledger()
    result = canpush_mod.check(records=led.store.records(),
                               config=led._require_config(), repo=REPO,
                               rev_range=rev_range, action=action,
                               admission=admission,
                               commit_admission=commit_admission, limit=limit)
    result["config_sha"] = led._require_config().config_sha
    result["line"] = canpush_mod.render(result)
    return result


@mcp.tool()
async def crossref(since: Optional[str] = None, limit: int = 500) -> dict:
    """Audit GIT HISTORY against the ledger: did anything land without the gate?

    Walks `rev-list <genesis>..HEAD`, resolves each commit's tree, and asks whether that
    content was approved. Three findings, in the shape of the question:

      NOT_RUN       no step examined this content — it bypassed the gate
      INCOMPLETE    examined, but the required set was short
      NOT_APPROVED  landed over a FAIL or UNDECIDED verdict

    ⚠ It compares against git, NOT against gitRobot's audit log. An earlier version joined
    the two stores, but both are written by the sanctioned path — so a commit made AROUND
    gitRobot leaves no audit row and the join was blind to exactly what it claimed to check.
    Git history is the one record a bypass cannot avoid writing to.

    ⚠ Commits from a human terminal are unaffected by gitRobot's deny rule BY DESIGN, so they
    surface as NOT_RUN. That is the audit working, not noise.

    ⚠ Capped at `limit` commits by default; truncation is REPORTED, never silent. limit=0 for
    the whole range."""
    return await _guard(_sync_crossref, since, limit)


def _sync_crossref(since, limit) -> dict:
    led = _ledger()
    return crossref_mod.check(records=led.store.records(),
                              config=led._require_config(), repo=REPO,
                              since=since, limit=limit)


@mcp.tool()
async def signals(family: Optional[str] = None, step: Optional[str] = None) -> dict:
    """The signal families, computed from the record fields alone.

    ⚠ Counts print on every call, clean or not — a signal nobody reads manufactures
    the appearance of coverage. Every family carries a `basis_count` so a zero
    reads as "nothing to judge" rather than "judged fine"."""
    return await _guard(lambda: signals_mod.compute(
        records=_ledger().store.records(), config=_ledger().config,
        family=family, step=step))


@mcp.tool()
async def status() -> dict:
    """Stream health, config state, invalid-append count, edge conditions, the
    genesis floor, and the steps whose latest verdict is UNDECIDED.

    ⚠ Must never report healthy while writes are failing — it proves the stream is
    readable AND the directory writable, not merely that rows exist."""
    return await _guard(_ledger().status)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
