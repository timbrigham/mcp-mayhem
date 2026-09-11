"""verdictLedger client for ZeroParadox checkers. STDLIB ONLY, NO RULES.

⛔⛔ DO NOT INSTALL THIS OVER A CONSUMER'S `tools/verify/record.py`. THIS HEADER USED TO SAY
"Install as tools/verify/record.py in the ZP repo" AND FOLLOWING IT DESTROYS WORK.

Measured 2026-09-10, this file against the copy actually running in ZeroParadox:

    this file   278 lines    "outstanding|failing" appears  0 times
    theirs     1165 lines    "outstanding|failing" appears 60 times

and EIGHT public functions exist only in theirs -- stale_or_missing, step_status, owing_paths,
read_ref, reachable, build_record, check, and `_cli`, which every gate brief shells out to.
⚠ So this is NOT a newer version of that file. It is a THINNER, OLDER, DIFFERENT object that
has never been what they run, and it cannot express `failing` -- which CLAUDE.md calls
load-bearing, because a FAIL indicts the subset it NAMES rather than everything it examined.

⭐ THE INSTRUCTION WAS ACTED ON AND CAUGHT MID-APPLY BY THE CONSUMER, not by us. Blast radius
was measured afterwards: `ZPLEDGER_URL` appears in exactly two files on this machine, so only
one consumer ever took it.

WHAT THIS FILE IS: the REFERENCE for the append protocol and the emit/emit_ex contract -- read
it, port from it, never copy it wholesale. A consumer that already has a record.py takes the
DELTA. Every checker calls `emit`; nothing about that changed.

⚠⚠ THIS FILE HOLDS NO VALIDATION LOGIC. It serialises and posts; the rules live in
the server, in exactly one place. That is what makes the mirror defect
unrepresentable rather than avoided by discipline — there is no second
implementation to drift.

⚠ If the ledger is unreachable or refuses, `emit` returns None and THE CALLER
BLOCKS. Never a warning, never a pass, never a local fallback write — a local
fallback is the two-route design returning through the back door.

⛔⛔ USE `emit_ex` AND EXIT 2-vs-4. `emit` collapses two DIFFERENT failures into one
`None`, and they differ on the one axis `error_type` says must never be collapsed —
an outage is RETRYABLE, a refusal is TERMINAL.

    rid, failure = record.emit_ex(...)
    if failure == "refused":
        sys.exit(4)          # asked and REFUSED — terminal, never retry
    if failure:
        sys.exit(2)          # could not ask — retryable

⚠ EXIT 2 OR 4, NEVER 0, NEVER 1. Distinguish "the check failed" (1) from "the check
could not be recorded" (2 or 4), or the pipeline cannot tell a finding from an outage.

⭐ WHY `emit_ex` EXISTS — MEASURED 2026-09-10, AND THE CONSUMER GOT HERE FIRST. `emit`
already KNEW which failure it had: the refusal branch carries the comment "A refusal is
TERMINAL. Do not retry it." and then returns the SAME `None` as a timeout. The
information existed and was destroyed at the return. So ZeroParadox built
`record.reachable()` — a SECOND NETWORK CALL — to recover a distinction this function
had already made, and `check_briefs.classify_record_failure` remapped the exit code on
the strength of it. **A workaround in the consumer is evidence of a gap here, not a
substitute for closing it.**

⚠ `emit` IS UNCHANGED AND STILL RETURNS id-or-None. Existing installed copies keep
working; nothing breaks by not upgrading. `emit_ex` is additive.

Measured 2026-08-22: streamable-HTTP MCP over urllib works — initialize,
notifications/initialized, tools/call; session id from the Mcp-Session-Id response
header; payload on the SSE `data:` line. No `mcp` dependency needed here.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

URL = os.environ.get("ZPLEDGER_URL", "http://127.0.0.1:8011/mcp")
TIMEOUT = float(os.environ.get("ZPLEDGER_TIMEOUT", "45"))

# ⚠ RETRY IS MECHANICAL AND TYPED, NEVER A JUDGEMENT. Transport failures are
# transient (a supervisor restart mid-call) and retried boundedly. A VALIDATION
# refusal is terminal and never retried: if "could not take it" and "rejected it"
# look alike, a caller under pressure retries its way past a rule.
_TRANSPORT_TRIES = 3
_BACKOFF = 0.4

_HEADERS = {"Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"}


def _post(payload, session=None):
    headers = dict(_HEADERS)
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.headers.get("Mcp-Session-Id"), resp.read().decode("utf-8")


def _parse(body):
    for line in body.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return json.loads(body) if body.strip() else None


def _call(tool: str, arguments: dict):
    """One MCP round trip. Returns the parsed tool payload, or None."""
    sid, body = _post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "zp-record", "version": "1"}}})
    _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session=sid)
    _, body = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": tool, "arguments": arguments}}, session=sid)
    res = _parse(body)
    if not res or "result" not in res:
        return None
    content = res["result"].get("content") or []
    if not content:
        return None
    try:
        return json.loads(content[0].get("text", ""))
    except (ValueError, AttributeError):
        return None


# -- the subject identity ------------------------------------------------------

def blob_id(path: str, *, repo: str = ".") -> str:
    """The GIT BLOB ID for a working-tree file — what `subjects[].git_blob_id` holds.

    ⚠⚠ DELEGATES TO GIT ON PURPOSE. A blob id is not a hash of the bytes on disk.
    It is sha1("blob " + len + NUL + CONTENT AS GIT STORED IT), and `git add` applies
    the repo's filters (`text=auto eol=lf`) when writing the object. On a CRLF
    checkout the stored object and the working bytes differ, so hashing the file
    directly yields a value that is right on one machine and silently wrong on
    another — the worst shape of defect, since it passes wherever it is developed.

    An earlier build of this helper did exactly that. It agreed with git only because
    the file under test was already LF.

    ⚠ DO NOT COMPUTE A sha256 OF THE FILE either. The ledger compares against what
    `git ls-tree` prints; a content digest is a different hash over a different byte
    string, appends cleanly, and then reads STALE forever — which looks exactly like
    a staleness bug and is not one. Measured 2026-08-23; it cost an afternoon.
    """
    import subprocess
    proc = subprocess.run(["git", "hash-object", "--", path], cwd=repo,
                          capture_output=True, text=True, encoding="utf-8")
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        raise RuntimeError(f"git hash-object failed for {path!r}: "
                           f"{(proc.stderr or '').strip()}")
    return out


def blobs_staged(*, repo: str = ".") -> dict:
    """path -> blob id for the INDEX — the content a commit would actually record.

    ⚠ 12-0-quater: a blob id names the STAGED object, while `batch.py precommit`
    scans the working tree. Stage a file, edit it further without staging, and those
    are different byte sequences. Use this when the verdict must describe what will
    be committed rather than what happens to be on disk.
    """
    import subprocess
    out = {}
    proc = subprocess.run(["git", "ls-files", "-s"], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    for line in proc.stdout.splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) >= 3:
            out[path.strip()] = parts[1]
    return out


def blobs_at(ref: str, *, repo: str = ".") -> dict:
    """path -> blob id for every file at `ref`. Cheaper than hashing files yourself
    and it is definitionally what the ledger will compare against."""
    import subprocess
    out = {}
    proc = subprocess.run(["git", "ls-tree", "-r", ref], cwd=repo,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    for line in proc.stdout.splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) >= 3:
            out[path.strip()] = parts[2]
    return out


def module_evidence(*paths, repo: str = ".") -> list:
    """[{path, git_blob_id}] for the checker's OWN source — what V16 requires.

    ⚠⚠ CALL IT WITH `__file__` AND LET IT DO THE REST. The path recorded must be
    REPO-RELATIVE with forward slashes, because that is what `git ls-files` prints and
    what `inventory` compares against; an absolute Windows path appends cleanly and
    then matches nothing forever, which is the same shape as the sha256 defect above.

        evidence = record.module_evidence(__file__)                    # this checker
        evidence = record.module_evidence(__file__, common.__file__)   # and its library

    ⚠ It hashes the WORKING-TREE file, on purpose: the bytes that ran are the bytes on
    disk, not whatever is staged. A checker running against a modified copy of itself
    must record THAT copy, or the evidence describes code that did not execute.
    """
    import os
    import subprocess
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=repo,
                          capture_output=True, text=True, encoding="utf-8")
    top = (root.stdout or "").strip()
    out = []
    for path in paths:
        rel = path
        if top:
            try:
                rel = os.path.relpath(os.path.abspath(path), top)
            except ValueError:
                # A different drive on Windows: outside the repo entirely, so there is
                # nothing honest to record. Refuse rather than record the absolute path,
                # which would never match and would read as a staleness bug forever.
                raise RuntimeError(
                    f"{path!r} is not inside the repository at {top!r}; a checker "
                    f"outside the tree cannot name itself as evidence")
        out.append({"path": rel.replace(os.sep, "/"),
                    "git_blob_id": blob_id(path, repo=repo)})
    return out


def emit(step, tier, verdict, subjects, basis, reason=None,
         inputs=(), decided=None, cost=None, revision=0, evidence=()):
    """Append one record. Returns its id, or None if refused or unreachable.

    ⚠ THIS SIGNATURE IS FROZEN FOR THE INSTALLED COPIES. It cannot tell a refusal from an
    outage — call `emit_ex` when you need to choose an exit code, which is every caller
    that gates on the result.
    """
    return emit_ex(step, tier, verdict, subjects, basis, reason=reason, inputs=inputs,
                   decided=decided, cost=cost, revision=revision, evidence=evidence)[0]


def emit_ex(step, tier, verdict, subjects, basis, reason=None,
            inputs=(), decided=None, cost=None, revision=0, evidence=()):
    """Append one record. Returns `(record_id, failure)`.

    `failure` is None on success, "refused" when the ledger DECIDED and said no, and
    "unreachable" when it was never asked. ⛔ The two map onto exit 4 and exit 2 and must
    never be merged: a refusal is a RULE being applied, so retrying it is how a caller gets
    past a rule it should have obeyed.

    `subjects` is a list of {"path", "git_blob_id"} — WHAT THIS VERDICT IS ABOUT, not
    everything the step glanced at. A step that examined forty files and failed on
    one emits a PASS over the thirty-nine and a FAIL over the one; that is what
    keeps coverage exact and makes repeat-subject a hash count rather than a grep
    over prose.
    """
    record = {
        "schema": "zp.record.v1",
        "step": step, "tier": tier, "verdict": verdict,
        "reason": reason,
        "basis": basis,
        "subjects": list(subjects or []),
        # ⚠ V16: a mechanical PASS is REFUSED without this. It is not `inputs` —
        # V4 requires every inputs entry to name a record already in the stream.
        "evidence": list(evidence or []),
        "decided": decided or {"how": "mechanical", "passes": 1, "agreed": 1, "who": None},
        "inputs": list(inputs or []),
        "revision": revision,
        "cost": cost or {"seconds": None, "usd": 0.0},
        "run": {"id": os.environ.get("ZPLEDGER_RUN"), "started": None,
                "config_sha": None, "env": {}},
    }

    last_error = None
    for attempt in range(_TRANSPORT_TRIES):
        try:
            out = _call("append", {"record": record})
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < _TRANSPORT_TRIES:
                time.sleep(_BACKOFF * (attempt + 1))
                continue
            print(f"UNDECIDED: verdictLedger unreachable at {URL} ({exc})")
            return None, "unreachable"
        if out is None:
            print("UNDECIDED: verdictLedger returned no usable payload")
            return None, "unreachable"
        if out.get("ok"):
            return out.get("id"), None
        # A refusal is TERMINAL. Do not retry it.
        errs = out.get("errors") or [out.get("error", "unknown")]
        print("UNDECIDED: record refused by verdictLedger:")
        for e in errs:
            print(f"  - {e}")
        return None, "refused"
    print(f"UNDECIDED: verdictLedger unreachable ({last_error})")
    return None, "unreachable"
