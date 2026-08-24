"""Audit git history against the ledger: did anything land without going through the gate?

⚠⚠ THIS WAS REPOINTED 2026-08-23, AND THE REASON MATTERS.

The first version joined the ledger against `gitRobot`'s `git_ops.jsonl`. **Both of
those are written by the sanctioned path**, so it could only detect disagreement
between two systems that already agree by construction:

  * a commit made THROUGH gitRobot has an audit row, and gitRobot refused it unless
    the inventory was complete — so records exist. Consistent, always.
  * a commit made AROUND gitRobot writes no audit row at all, so the join is blind
    to precisely the thing it sounded like it was checking.

It also claimed to close `GRB-2` — the dropped `preflight` that left no verdict and
no audit row — but both stores were silent TOGETHER, so a join between them sees
nothing. What actually caught that was a `started` row inside gitRobot's own log:
detectable from one stream, not from two.

**Git history is the one record a bypass cannot avoid writing to.** So the audit
walks `git rev-list`, resolves each commit's tree, and asks the ledger whether that
content was approved. No second stream, no join key, and nothing gitRobot has to
capture for it to work — `commit^{tree}` resolves from the head git already knows.

Three findings, in the shape of the question being asked:

  NOT_RUN      a commit whose content no step examined  — it bypassed the gate
  INCOMPLETE   examined, but the required set was short — it landed under-gated
  NOT_APPROVED examined, and the operative verdict was FAIL or UNDECIDED

⚠ Commits made from a human terminal are UNAFFECTED by gitRobot's deny rule by
design, so they will surface as NOT_RUN. That is the audit working, not noise —
but it is worth knowing before reading the output.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from core import inventory as inventory_mod

# Walking history is a read, but it is one git call per commit. A default cap
# keeps an unbounded range from looking like a hang; ⚠ truncation is REPORTED,
# never silent — a capped audit that reads as complete is the defect this whole
# server exists to end.
DEFAULT_LIMIT = 500


def _git(repo: str, *args: str) -> str:
    """Empty string on any failure — the CALLER decides what an empty result means.

    A missing directory raises from subprocess before git is even reached, and an
    audit that crashes reports nothing at all, which is worse than reporting that
    it has no ground truth.
    """
    try:
        proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _files_at(repo: str, ref: str) -> dict:
    """path -> blob sha for a commit."""
    out = {}
    for line in _git(repo, "ls-tree", "-r", ref).splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) >= 3:
            out[path.strip()] = parts[2]
    return out


def _genesis_floor_commit(records: list) -> Optional[str]:
    """The commit from which the audit claims anything.

    ⚠ A fact about when RECORDING began, never a claim that earlier work was
    verified. Without it every commit in the project's history reads as a bypass,
    and a warning nobody can act on is one people learn to scroll past.
    """
    for r in records:
        if r.get("step") == "genesis":
            return (r.get("basis") or {}).get("value")
    return None


def check(*, records: list, config, repo: Optional[str] = None,
          since: Optional[str] = None, limit: int = DEFAULT_LIMIT,
          action: str = "commit", admission: Optional[list] = None) -> dict:
    """⚠ Without an `admission` set the audit can still answer *"did anything
    examine this content?"* — that is NOT_RUN, and it needs no notion of
    sufficiency. It CANNOT answer *"was it sufficiently examined?"*, so
    INCOMPLETE is not evaluated and the result says so. Reporting clean because
    nobody said what sufficient means is the fail-open this system exists to end.
    """
    repo = repo or os.environ.get("ZPLEDGER_REPO", r"C:\Workspace\ZeroParadox")

    head = _git(repo, "rev-parse", "HEAD")
    if not head:
        return {"ok": False, "no_data": True, "repo": repo,
                "note": (f"{repo} is not a readable git repository, so the audit has no "
                         f"ground truth to compare against. This is a finding, not a pass."),
                "findings": []}

    floor = since or _genesis_floor_commit(records)
    if not floor:
        return {"ok": False, "no_data": True, "repo": repo, "head": head,
                "note": ("NO GENESIS RECORD — there is no floor, so the audit cannot say "
                         "which commits it is entitled to judge. Seed one with "
                         "genesis(<sha>); it records when this ledger started, and claims "
                         "nothing about anything earlier."),
                "findings": []}

    rev_range = f"{floor}..{head}"
    commits = [c for c in _git(repo, "rev-list", "--reverse", rev_range).splitlines() if c]

    # ⚠⚠ HOW MUCH IS BELOW THE FLOOR, counted and named. §9a scopes the audit to
    # commits at or after genesis on purpose, and that is right -- an unactionable
    # warning on every run trains people to scroll past it. But "reports nothing
    # before the floor" was implemented as SILENCE, so a reader saw three zeroes and
    # concluded the history was clean. Measured 2026-08-23: 23 audited, 151 below,
    # counts all zero. The floor still bounds what is JUDGED; this only stops the
    # result reading as a clean bill of health over commits nobody looked at.
    # ⚠ This is the repository's ENTIRE history before the floor, most of which
    # predates the ledger by years. It is context for the scoping sentence, NOT an
    # alarm — the load-bearing half of the note is "the counts describe N commits
    # only", and the number is there so nobody has to go and work it out.
    try:
        below = int((_git(repo, "rev-list", "--count", floor) or "0").strip())
    except (ValueError, OSError):
        below = 0
    truncated = len(commits) > limit > 0
    if truncated:
        commits = commits[-limit:]

    findings = []
    for commit in commits:
        tree = _git(repo, "rev-parse", f"{commit}^{{tree}}")
        files = _files_at(repo, commit)
        if not files:
            continue
        inv = inventory_mod.build(config=config, records=records, action=action,
                                  files=files, ref=commit, admission=admission)
        # "Did anything examine THIS CONTENT?" is independent of what would have
        # been SUFFICIENT.
        #
        # ⚠⚠ STALE IS NOT EXAMINED. It used to count here, and that inverted the
        # audit's headline question. STALE means a step examined DIFFERENT bytes; for
        # the bytes in this commit it did not run at all. Counting it as examined let
        # a commit nothing had ever looked at report `examined_by=3` and escape the
        # NOT_RUN finding -- the single finding this whole audit exists to produce.
        #
        # Measured 2026-08-23: three probe records against a throwaway tree made all
        # eight audited commits look examined. The bypass detector was reporting
        # coverage it did not have.
        examined = [r for r in inv["rows"]
                    if r["status"] in ("SATISFIED", "FAIL", "UNDECIDED")]
        subject = {"commit": commit, "tree": tree,
                   "subject": _git(repo, "log", "-1", "--pretty=%s", commit)[:80],
                   "examined_by": len(examined),
                   "required": inv["required"], "satisfied": inv["satisfied"]}
        if not examined:
            findings.append({**subject, "finding": "NOT_RUN",
                             "detail": ("no step examined this content — it did not go "
                                        "through the gate")})
        elif any(r["status"] in ("FAIL", "UNDECIDED") for r in inv["rows"]):
            names = [r["step"] for r in inv["rows"]
                     if r["status"] in ("FAIL", "UNDECIDED")]
            findings.append({**subject, "finding": "NOT_APPROVED",
                             "detail": f"landed over a non-passing verdict: {', '.join(names)}"})
        elif admission is not None and not inv["complete"]:
            names = [r["step"] for r in inv["rows"]
                     if r["status"] in ("MISSING", "STALE")]
            findings.append({**subject, "finding": "INCOMPLETE",
                             "detail": f"required but not satisfied: {', '.join(names)}"})

    return {
        "ok": not findings,
        "no_data": False,
        "repo": repo,
        "head": head,
        "genesis_floor": floor,
        "range": rev_range,
        "commits_audited": len(commits),
        "commits_below_floor": below,
        # ⚠ The sentence a human reads. "0 findings" over 23 of 174 commits is true
        # and misleading; this is the half that makes it neither.
        "floor_note": (
            f"⚠ THE COUNTS BELOW DESCRIBE {len(commits)} COMMIT(S) ONLY. "
            f"{below} commit(s) of prior history sit below the genesis floor and were "
            f"NOT audited — nothing is claimed about them, neither that they passed "
            f"nor that they failed. Zero findings here is not a clean bill of health "
            f"for the repository; it is a clean bill of health for the range."
            if below else None),
        "truncated": truncated,
        "truncation_note": (
            f"⚠ AUDIT CAPPED at the most recent {limit} commits of {rev_range}. Earlier "
            f"commits in range were NOT examined and are not claimed clean. Pass limit=0 "
            f"for the whole range." if truncated else None),
        "admission": sorted(admission) if admission is not None else None,
        "completeness_note": (None if admission is not None else
                              "⚠ NO ADMISSION SET GIVEN — NOT_RUN and NOT_APPROVED were "
                              "evaluated, INCOMPLETE was NOT. A commit that was partly "
                              "examined is not claimed clean here."),
        "counts": {k: sum(1 for f in findings if f["finding"] == k)
                   for k in ("NOT_RUN", "INCOMPLETE", "NOT_APPROVED")},
        "findings": findings,
    }
