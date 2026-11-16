"""Reconstruct coverage over a whole tree: for the burn-down (Tim, 2026-11-16:
*"get the tool working and the gate settings mandatory.. once that's in place the
burn down"*).

For every file at ``ref`` matching ``scope``, at the blob that ref carries, report
which of five states it is in:

    never_run     no indexed run examined these bytes
    brief_moved   runs examined these bytes, but every one ran under a brief that is
                  not the brief at ``ref`` — the ledger stales such a record on
                  arrival (V17), so it covers nothing. Measured the day this was
                  written: run w8r1 used reconstruct.md d8d36a3b, HEAD carried d3642ae3.
    fail          a current-brief run left an open or applied DIFF-1 item
    pass          a current-brief run with every item decided
    (and the total, so the five always add up)

⛔ WHICH OBJECT: the TREE OF ``ref`` (default HEAD — what a push publishes), read
with ``git ls-tree``. Not the working tree and not the index. The answer names the
commit it resolved to, because "HEAD" is a different commit an hour later.

⚠ THIS IS SJV'S DERIVATION, NOT THE GATE. A ``pass`` here means the record body
``reconstruct_verdict`` would serve is a PASS. Whether the emitter APPENDED it, and
whether the ledger accepts it, is verdictLedger's answer — ask ``can_push`` for that.

⚠ ``scope`` HAS NO DEFAULT ON PURPOSE. It must be the registry's ``scope`` for the
step, passed by the caller; a default here would be a second copy of the policy in a
server that does not own it. Matching is ``fnmatch``, the matcher the ledger uses,
so ``*`` crosses ``/`` exactly as it does there.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

from consumers.readings.views import verdict_for
from core.errors import OperationError

STATES = ("never_run", "brief_moved", "fail", "pass")


def _git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode != 0:
        raise OperationError(
            f"git {' '.join(args)} failed in {str(root)!r}: {r.stderr.strip()}",
            satisfied_when="`root` is the consumer's git checkout and `ref` resolves in it")
    return r.stdout


def coverage(document: dict, *, root: Path, ref: str, scope: list,
             limit: int = 50) -> dict:
    if not scope or not all(isinstance(g, str) and g for g in scope):
        raise OperationError(
            "scope is empty",
            satisfied_when="pass the registry's `scope` for the reconstruct step, e.g. "
                           "['ZeroParadox/*.lean']; an empty scope would report 0 of 0 as done")
    commit = _git(root, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    files: list[tuple[str, str]] = []
    for line in _git(root, "ls-tree", "-r", commit).splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[1] == "blob" and any(
                fnmatch.fnmatch(path, g) for g in scope):
            files.append((path, parts[2]))
    files.sort()

    brief_at_ref: dict = {}

    def _brief_current(run: dict) -> bool:
        p = run["brief"]["path"]
        if p not in brief_at_ref:
            out = subprocess.run(["git", "-C", str(root), "rev-parse", f"{commit}:{p}"],
                                 capture_output=True, text=True)
            brief_at_ref[p] = out.stdout.strip() if out.returncode == 0 else None
        return brief_at_ref[p] == run["brief"]["git_blob_id"]

    runs_by_id = {r["run_id"]: r for r in document.get("runs", [])}
    buckets: dict = {s: [] for s in STATES}
    for path, blob in files:
        v = verdict_for(document, path, blob)
        if v["state"] == "never_run":
            buckets["never_run"].append(path)
            continue
        current = [rid for rid in v["runs"] if _brief_current(runs_by_id[rid])]
        if not current:
            buckets["brief_moved"].append(path)
            continue
        # Re-derive over CURRENT-brief runs only, so an old-brief run's items cannot
        # decide a file the current brief has also read.
        sub = {"runs": [runs_by_id[r] for r in current],
               "entries": document.get("entries", [])}
        verdict = verdict_for(sub, path, blob)["record"]["verdict"]
        buckets["pass" if verdict == "PASS" else "fail"].append(path)

    counts = {s: len(buckets[s]) for s in STATES}
    counts["total"] = len(files)
    if sum(counts[s] for s in STATES) != counts["total"]:      # the partition must close
        raise OperationError("coverage buckets do not partition the files",
                             satisfied_when="never; this is a defect in sjv")
    return {
        "object": f"tree of {ref} at commit {commit}",
        "commit": commit,
        "scope": list(scope),
        "briefs_at_ref": brief_at_ref,
        "counts": counts,
        "files": {s: buckets[s][:limit] for s in STATES},
        "truncated": {s: len(buckets[s]) > limit for s in STATES},
        "means": "sjv's derivation of what reconstruct_verdict would serve; whether the "
                 "record was appended and accepted is verdictLedger can_push's answer",
    }
