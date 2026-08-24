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

import subprocess
from typing import Optional

from core import crossref as crossref_mod
from core import inventory as inventory_mod


# ⚠ A CAP, BECAUSE AN UNBOUNDED WALK IS A HANG. It is LOUD rather than silent: a
# truncated audit that renders like a complete one is the failure this server exists
# to end, so exceeding it REFUSES rather than reporting on the part it managed.
DEFAULT_LIMIT = 500


def _git(repo: str, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed: {(proc.stderr or '').strip()}")
    return proc.stdout


def _files_at(repo: str, ref: str) -> dict:
    """path -> git blob id for a commit. The whole comparison is this lookup."""
    out = {}
    for line in _git(repo, "ls-tree", "-r", ref).splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) >= 3:
            out[path.strip()] = parts[2]
    return out


def check(*, records: list, config, repo: str, rev_range: str, action: str = "push",
          admission: Optional[list] = None, commit_admission: Optional[list] = None,
          limit: int = DEFAULT_LIMIT) -> dict:
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
    """
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
    rows = []
    for i, commit in enumerate(commits):
        is_tip = (i == len(commits) - 1)
        # ⚠ The tip is what the world will see as the published state, so it carries
        # the full push bar. Everything under it is judged by the bar that applied
        # when it was MADE.
        this_action = action if is_tip else "commit"
        this_admission = admission if is_tip else commit_admission
        files = _files_at(repo, commit)
        inv = inventory_mod.build(config=config, records=records, action=this_action,
                                  files=files, ref=commit, admission=this_admission)
        rows.append({
            "commit": commit,
            "judged_as": this_action,
            "is_tip": is_tip,
            "subject": _git(repo, "log", "-1", "--pretty=%s", commit).strip()[:72],
            "complete": bool(inv.get("complete")),
            "required": inv["required"], "satisfied": inv["satisfied"],
            "missing": sorted(r["step"] for r in inv["rows"]
                              if r["gating"] and r["status"] == "MISSING"),
            "stale": sorted(r["step"] for r in inv["rows"]
                            if r["gating"] and r["status"] == "STALE"),
            "failed": sorted(r["step"] for r in inv["rows"]
                             if r["gating"] and r["status"] in ("FAIL", "UNDECIDED")),
            "legacy": sorted(r["step"] for r in inv["rows"]
                             if r["gating"] and r["status"] == "LEGACY_IDENTITY"),
            "admission_state": inv.get("admission_state"),
            "not_gating": inv.get("registered_not_admitting") or [],
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
        return {"ok": True, "allowed": True, "range": rev_range, "commits": [],
                "empty_range": True, "admitted": admitted,
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

    blocking = [r for r in rows if not r["complete"]]
    return {
        "ok": True,
        "allowed": not blocking,
        "range": rev_range,
        "commits_in_range": len(rows),
        "blocking_count": len(blocking),
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
        "failed": sorted({s for r in rows for s in r["failed"]}),
        "legacy": sorted({s for r in rows for s in r["legacy"]}),
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

    lines = [f"{'ALLOWED' if result['allowed'] else 'REFUSED'}  push  "
             f"{result['blocking_count']}/{result['commits_in_range']} commit(s) short"
             f"  @ {result['range']}"]

    # ⚠⭐ NARROWED COVERAGE, ON THE PUSH PATH. Measured 2026-08-23: a step that
    # examined one file of 201 read SATISFIED. `inventory` names it; without this the
    # push path -- the one that matters -- would still be silent.
    thin = [r["thinnest"] for r in result.get("commits") or [] if r.get("thinnest")]
    if thin:
        step, seen, scope = min(thin, key=lambda t: t[1] / t[2] if t[2] else 1)
        lines.append(f"  ⚠ NARROWED COVERAGE — thinnest gating step {step} examined "
                     f"{seen}/{scope} in-scope paths (reported, not blocking)")

    if result.get("audit_note"):
        lines.append("  " + result["audit_note"])

    if result.get("admission_state") in ("EMPTY", "UNSET"):
        lines.append("  ⚠⚠ NOTHING GATES THIS PUSH — the admission set is "
                     f"{'empty' if result['admission_state'] == 'EMPTY' else 'not set'}.")

    # the whole remaining job, in four lines
    for label, remedy in (("missing", "python tools/verify/batch.py precommit"),
                          ("stale", "re-run — recorded against different bytes"),
                          ("failed", "fix it"),
                          ("legacy", "re-record — superseded subject scheme")):
        names = result.get(label) or []
        if names:
            shown = ", ".join(names[:8]) + ("…" if len(names) > 8 else "")
            lines.append(f"  {label.upper():8} {shown}      INSTEAD: {remedy}")

    blocking = [r for r in result["commits"] if not r["complete"]]
    if blocking:
        lines.append(f"  commits short ({len(blocking)}):")
        for row in blocking[:SHOWN]:
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
