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
from typing import Optional

from consumers.readings.views import verdict_for
from core.errors import OperationError

STATES = ("never_run", "brief_moved", "partial", "fail", "pass")


def _git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode != 0:
        raise OperationError(
            f"git {' '.join(args)} failed in {str(root)!r}: {r.stderr.strip()}",
            satisfied_when="`root` is the consumer's git checkout and `ref` resolves in it")
    return r.stdout


def resolve_commit(root: Path, ref: str) -> str:
    return _git(root, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def briefs_at(root: Path, commit: str, document: dict) -> dict:
    """Every brief path any indexed run names, mapped to its blob at ``commit`` (None if
    the path does not exist there, which matches no run and so decides nothing)."""
    out: dict = {}
    for p in sorted({r["brief"]["path"] for r in document.get("runs", [])}):
        r = subprocess.run(["git", "-C", str(root), "rev-parse", f"{commit}:{p}"],
                           capture_output=True, text=True)
        out[p] = r.stdout.strip() if r.returncode == 0 else None
    return out


def line_counter(root: Path):
    """A memoised blob -> line count reader over ``root``'s object store. Counts lines the
    way an editor numbers them: a final line without a newline still counts. None if the
    blob is not in the repository, which makes a ranged file `partial`, never decided."""
    memo: dict = {}

    def count(blob: str) -> Optional[int]:
        if blob not in memo:
            r = subprocess.run(["git", "-C", str(root), "cat-file", "blob", blob],
                               capture_output=True)
            if r.returncode != 0:
                memo[blob] = None
            else:
                b = r.stdout
                memo[blob] = b.count(b"\n") + (1 if b and not b.endswith(b"\n") else 0)
        return memo[blob]
    return count


def coverage(document: dict, *, root: Path, ref: str, scope: list,
             scope_exclude: Optional[list] = None, limit: int = 50) -> dict:
    if not scope or not all(isinstance(g, str) and g for g in scope):
        raise OperationError(
            "scope is empty",
            satisfied_when="pass the registry's `scope` for the reconstruct step, e.g. "
                           "['ZeroParadox/*.lean']; an empty scope would report 0 of 0 as done")
    commit = resolve_commit(root, ref)
    files: list[tuple[str, str]] = []
    for line in _git(root, "ls-tree", "-r", commit).splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[1] == "blob" and any(
                fnmatch.fnmatch(path, g) for g in scope) and not any(
                fnmatch.fnmatch(path, g) for g in (scope_exclude or [])):
            files.append((path, parts[2]))
    files.sort()

    current = briefs_at(root, commit, document)
    counter = line_counter(root)
    buckets: dict = {s: [] for s in STATES}
    for path, blob in files:
        v = verdict_for(document, path, blob, current_briefs=current, line_counter=counter)
        if v["state"] in ("never_run", "brief_moved", "partial"):
            buckets[v["state"]].append(path)
        else:
            buckets["pass" if v["record"]["verdict"] == "PASS" else "fail"].append(path)

    counts = {s: len(buckets[s]) for s in STATES}
    counts["total"] = len(files)
    if sum(counts[s] for s in STATES) != counts["total"]:      # the partition must close
        raise OperationError("coverage buckets do not partition the files",
                             satisfied_when="never; this is a defect in sjv")
    return {
        "object": f"tree of {ref} at commit {commit}",
        "commit": commit,
        "scope": list(scope),
        "scope_exclude": list(scope_exclude or []),
        "briefs_at_ref": current,
        "counts": counts,
        "files": {s: buckets[s][:limit] for s in STATES},
        "truncated": {s: len(buckets[s]) > limit for s in STATES},
        "means": "sjv's derivation of what reconstruct_verdict would serve; whether the "
                 "record was appended and accepted is verdictLedger can_push's answer",
    }
