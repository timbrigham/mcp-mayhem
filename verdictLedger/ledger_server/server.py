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
    import subprocess
    args = (["ls-files", "-s"] if ref == "staged" else ["ls-tree", "-r", ref])
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    out = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            path = line.split("\t", 1)[-1].strip() if "\t" in line else parts[-1]
            out[path] = parts[2]
    return out


# -- writes -------------------------------------------------------------------

@mcp.tool()
async def append(record: dict) -> dict:
    """Validate against V1-V14, then append. Returns {id}. REFUSES invalid records.

    Idempotent on identity — (step, basis, verdict, reason, subjects, revision).
    No wall clock is in the hash, so the same verdict over the same content is the
    same record however long it took to reach.

    ⚠ A refusal is TERMINAL. Do not retry it: fix the record. Retrying a rejected
    record is how a validation rule gets worn down."""
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
    """Schema plus V1-V14. Pure, no write. Returns {ok, errors[]} with EVERY
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
    return {"policy": cfg.policy, "policy_sha": cfg.policy_sha,
            "actions": cfg.actions, "min_passes": cfg.min_passes,
            "max_depth": cfg.max_depth, "genesis": cfg.genesis}


@mcp.tool()
async def inventory(action: str, ref: str = "staged",
                    admission: Optional[list[str]] = None) -> dict:
    """Required vs satisfied vs MISSING for a ref — the complete key set for an action.

    ⚠ The requirement set is declared IN ADVANCE. An inventory assembled from "the
    records that happen to exist" is worthless, because "3 of 3 passed" and "5
    never ran" render identically.

    Five statuses and none may collapse into another: SATISFIED · STALE (examined,
    content moved — re-run) · MISSING (never examined — run at all) ·
    NOT_APPLICABLE (a `when` glob did not match, and it carries the glob) ·
    FAIL/UNDECIDED. `complete` is true only when missing, stale, undecided and
    failed are all zero — gitRobot REQUIRES that; the ledger COMPUTES it.

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
    inv["policy_sha"] = cfg.policy_sha
    inv["line"] = render_mod.render_inventory(inv)
    return inv


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
    result["policy_sha"] = led._require_config().policy_sha
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
