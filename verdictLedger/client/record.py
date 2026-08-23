"""verdictLedger client for ZeroParadox checkers. STDLIB ONLY, NO RULES.

Install as `tools/verify/record.py` in the ZP repo. Every checker calls `emit`.

⚠⚠ THIS FILE HOLDS NO VALIDATION LOGIC. It serialises and posts; the rules live in
the server, in exactly one place. That is what makes the mirror defect
unrepresentable rather than avoided by discipline — there is no second
implementation to drift.

⚠ If the ledger is unreachable or refuses, `emit` returns None and THE CALLER
BLOCKS. Never a warning, never a pass, never a local fallback write — a local
fallback is the two-route design returning through the back door.

    rid = record.emit(...)
    if rid is None:
        print("UNDECIDED: ledger unavailable or record rejected"); sys.exit(2)

⚠ EXIT 2, NEVER 0, NEVER 1. Distinguish "the check failed" (1) from "the check
could not be recorded" (2), or the pipeline cannot tell a finding from an outage.

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


def emit(step, tier, verdict, subjects, basis, reason=None,
         inputs=(), decided=None, cost=None, revision=0):
    """Append one record. Returns its id, or None if refused or unreachable.

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
        "decided": decided or {"how": "mechanical", "passes": 1, "agreed": 1, "who": None},
        "inputs": list(inputs or []),
        "revision": revision,
        "cost": cost or {"seconds": None, "usd": 0.0},
        "run": {"id": os.environ.get("ZPLEDGER_RUN"), "started": None,
                "policy_sha": None, "env": {}},
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
            return None
        if out is None:
            print("UNDECIDED: verdictLedger returned no usable payload")
            return None
        if out.get("ok"):
            return out.get("id")
        # A refusal is TERMINAL. Do not retry it.
        errs = out.get("errors") or [out.get("error", "unknown")]
        print("UNDECIDED: record refused by verdictLedger:")
        for e in errs:
            print(f"  - {e}")
        return None
    print(f"UNDECIDED: verdictLedger unreachable ({last_error})")
    return None
