"""The unit: an agent instance. Which instance made a call, and calls recovered from an HTTP log.

The unit changed on 2026-10-15 from an MCP session to an AGENT INSTANCE: one agent context, such
as a subagent, identified on each logged call by a client declared as an agent. One long-lived
Claude Code process spawns many short-lived subagents over a single MCP session (gitRobot logged
2026-10-13 15:02Z .. 10-14 22:46Z as one session), so a session could never reach n >= 100.

A call is tied to an instance by the client's own per-call id (`client_call_id`). For Claude Code
that id is the `tool_use` id, and it appears in one transcript file: the main conversation
(`<conversation>.jsonl`) or a subagent (`<conversation>/subagents/agent-<id>.jsonl`). The
instance is that file, named by its path relative to the transcript directory, without `.jsonl`.
A forked subagent's transcript starts with a COPY of its parent's history, call ids included, so
an id can sit in several files with nothing to say which one made the call: such an id is left
out of the map and listed as ambiguous, never assigned.

`index_transcripts` builds the map from the transcript directories it is given. The directories
are private and are arguments, never manifest content. The map it returns holds only ids, the
instance name and the client version recorded on the same transcript line, no transcript text.

`calls_from_http` is the one-off BACKFILL: it recovers call rows from the rotating HTTP call log
(which carried the id in each request's `_meta`). The rows carry the fields measure() reads, with
gitRobot's `tool_calls.jsonl` names where it has them (`outcome`), but they are NOT identical to
forward rows: `ts` is the request START here and the end of the call there, and they carry
`source: "http_calls backfill"`. `link_refusals` adds the id to audit refusal rows written before
the audit rows carried it, by a unique-match rule, and counts what it cannot link.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .inputs import InputError, parse_ts

TOOL_USE = '"tool_use"'


# --------------------------------------------------------------------- transcripts -> instances
def index_transcripts(dirs, wanted=None):
    """Map client call id -> {"instance", "client_version"} from Claude Code transcripts.

    `wanted`: optional set of ids; others are not kept (the transcripts hold every tool call the
    agents made, not only gitRobot's). An id found in two files is ambiguous: it is left out of
    the map, never assigned to either, and returned in `ambiguous`.
    Returns (map, ambiguous ids, stats)."""
    found = defaultdict(set)
    version = {}
    files = 0
    for d in dirs:
        root = Path(d)
        if not root.is_dir():
            raise InputError("transcript directory not found: %s" % root.name)
        for f in sorted(root.rglob("*.jsonl")):
            files += 1
            instance = f.relative_to(root).as_posix()[:-len(".jsonl")]
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if TOOL_USE not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    content = (rec.get("message") or {}).get("content")
                    if not isinstance(content, list):
                        continue
                    for c in content:
                        if not isinstance(c, dict) or c.get("type") != "tool_use":
                            continue
                        cid = c.get("id")
                        if not isinstance(cid, str) or (wanted is not None and cid not in wanted):
                            continue
                        found[cid].add(instance)
                        version.setdefault((cid, instance), rec.get("version"))
    out, ambiguous = {}, set()
    for cid, where in found.items():
        if len(where) != 1:
            ambiguous.add(cid)
            continue
        (inst,) = where
        out[cid] = {"instance": inst, "client_version": version[(cid, inst)]}
    return out, ambiguous, {"transcript_files": files, "ids_mapped": len(out),
                            "ids_in_more_than_one_file": len(ambiguous)}


# --------------------------------------------------------------------- HTTP log -> call rows
CLIENT_CALL_ID_KEY = "claudecode/toolUseId"
BACKFILL_CLIENT = "claude-code"
SOURCE = "http_calls backfill"

# A body's decision, in gitRobot tool_calls.jsonl's `outcome` vocabulary.
_OUTCOME = {"allowed": "returned", "refused": "refused", "failed": "error", None: None}


def _sse_json(resp):
    """The JSON-RPC message inside a streamable-HTTP response body (an SSE `data:` line)."""
    if not isinstance(resp, str):
        return None
    for line in resp.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except ValueError:
                return None
    try:
        return json.loads(resp)
    except ValueError:
        return None


def call_outcome(resp):
    """(decision, error_type, refusal_id) from a tools/call response, or (None, None, None) when
    the body cannot be read (truncated, or not JSON). Never guessed from prose. decision is
    allowed | refused | failed; calls_from_http writes it in the `outcome` vocabulary."""
    msg = _sse_json(resp)
    if not isinstance(msg, dict):
        return None, None, None
    if "error" in msg:
        return "failed", None, None                  # a JSON-RPC error: the tool did not answer
    result = msg.get("result")
    if not isinstance(result, dict):
        return None, None, None
    body = result.get("structuredContent")
    if body is None:
        try:
            body = json.loads(result["content"][0]["text"])
        except (KeyError, IndexError, TypeError, ValueError):
            body = None
    if not isinstance(body, dict):
        return ("failed", None, None) if result.get("isError") else (None, None, None)
    if body.get("ok") is False and body.get("error_type"):
        if body["error_type"] == "refusal":
            return "refused", "refusal", body.get("refusal_id") or None
        return "failed", body["error_type"], None
    return "allowed", None, None


def server_spans(audit_rows):
    """Contiguous spans of one gitRobot SERVER process, from its audit rows that carry
    `versions`: [(first_ts, last_ts, pid, gitrobot_commit, gitrobot_dirty)], in time order. A
    process is known to have run between its first and last row; outside every span nothing is
    assumed. CLI rows are left out: a CLI run is its own short process beside the server."""
    by_pid = {}
    for r in audit_rows:
        v = r.get("versions")
        if not isinstance(v, dict) or "pid" not in r or r.get("surface") == "cli":
            continue
        ts = parse_ts(r["ts"], "audit row")
        key = (r["pid"], v.get("gitrobot_commit"), v.get("gitrobot_dirty"))
        lo, hi = by_pid.get(key, (ts, ts))
        by_pid[key] = (min(lo, ts), max(hi, ts))
    spans = sorted((lo, hi) + key for key, (lo, hi) in by_pid.items())
    for a, b in zip(spans, spans[1:]):
        if b[0] <= a[1]:
            raise InputError("audit rows from two gitRobot processes overlap in time (pids %s "
                             "and %s): server versions cannot be placed" % (a[2], b[2]))
    return spans


FLOOR = timedelta(seconds=1)      # the HTTP log floors the request start to the second


def _span_of(spans, ts):
    """The one span the call's TRUE start, in [ts, ts + 1 s), can fall in: a span whose
    [first, last] row times it can overlap. Several, or none: None, with the reason."""
    hits = [s for s in spans if s[0] - FLOOR < ts <= s[1]]
    if len(hits) == 1:
        return hits[0], None
    return None, ("outside every audit-row server span: no versions" if not hits else
                  "start could be in two server spans: no versions")


def _ts(r):
    try:
        ts = datetime.fromisoformat(r["ts"])
    except (KeyError, TypeError, ValueError):
        raise InputError("HTTP log row without a readable ts: %r" % (r.get("ts"),)) from None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)


def calls_from_http(http_rows, audit_rows, transcript_map):
    """Backfill call rows from the HTTP call log. `transcript_map` from index_transcripts.

    Each row: ts (the request's START, UTC, floored to the second: the HTTP log writes it
    without an offset), duration_ms (the request's length, from the same log), tool, surface
    'mcp', session, client_call_id, outcome/error_type/refusal_id from the response body (null
    when unreadable), source, and versions:
      gitrobot_commit, gitrobot_dirty   from the one audit-row server span the call's start can
                                        fall in (versions ABSENT when none or several: not placed)
      client_name, client_version       what the SAME SESSION's audit rows say (the connection's
                                        own initialize self-report, as forward rows carry it);
                                        else, when the id resolves in the transcripts,
                                        "claude-code" and the version on that transcript line;
                                        else null: the HTTP log never recorded the client
      consumer_hook_commit              null, as on gitRobot's own rows
    Returns (rows, stats)."""
    spans = server_spans(audit_rows)
    by_session = defaultdict(Counter)
    for a in audit_rows:
        v = a.get("versions")
        if isinstance(v, dict) and a.get("session") and v.get("client_name"):
            by_session[a["session"]][(v["client_name"], v.get("client_version"))] += 1
    session_client = {s: next(iter(seen)) for s, seen in by_session.items() if len(seen) == 1}
    out, stats = [], Counter()
    for r in http_rows:
        if r.get("rpc_method") != "tools/call":
            continue
        stats["tools/call rows"] += 1
        try:
            req = json.loads(r.get("req") or "")
        except ValueError:
            req = None
        if not isinstance(req, dict):
            stats["request unreadable: skipped"] += 1
            continue
        params = req.get("params") or {}
        meta = params.get("_meta") or {}
        cid = meta.get(CLIENT_CALL_ID_KEY)
        cid = cid if isinstance(cid, str) and cid else None
        ts = _ts(r)
        decision, error_type, refusal_id = call_outcome(r.get("resp"))
        if decision is None:
            stats["response unreadable: outcome null"] += 1
        row = {"ts": ts.isoformat(), "tool": params.get("name") or r.get("tool"),
               "surface": "mcp", "session": r.get("session"), "client_call_id": cid,
               "outcome": _OUTCOME[decision], "error_type": error_type,
               "refusal_id": refusal_id, "duration_ms": r.get("ms"), "source": SOURCE}
        span, why = _span_of(spans, ts)
        if span is None:
            stats[why] += 1
        else:
            hit = transcript_map.get(cid) if cid else None
            sess = r.get("session")
            if sess in session_client:
                name, version = session_client[sess]
                stats["client from the session's audit rows"] += 1
                if hit and (name, version) != (BACKFILL_CLIENT, hit["client_version"]):
                    stats["client differs between session audit rows and transcript"] += 1
            elif sess in by_session:
                name = version = None
                stats["session's audit rows name several clients: client null"] += 1
            elif hit:
                name, version = BACKFILL_CLIENT, hit["client_version"]
                stats["client from the transcript"] += 1
            else:
                name = version = None
            row["versions"] = {"gitrobot_commit": span[3], "gitrobot_dirty": span[4],
                               "client_name": name, "client_version": version,
                               "consumer_hook_commit": None}
        out.append(row)
    out.sort(key=lambda x: x["ts"])
    return out, dict(stats)


# --------------------------------------------------------------------- refusals -> call ids
# The HTTP log's ts is the request START floored to the second, so the audit row written during
# the call lies in [ts, ts + 1 s + duration]. SLACK absorbs clock rounding at both ends.
LINK_SLACK = timedelta(seconds=0.5)


def _rid(detail):
    if isinstance(detail, str) and detail.startswith("[") and "]" in detail:
        return detail[1:detail.index("]")]
    return None


def _during(c, ts):
    start = parse_ts(c["ts"], "call row")
    end = start + FLOOR + timedelta(milliseconds=c.get("duration_ms") or 0)
    return start - LINK_SLACK <= ts <= end + LINK_SLACK


def link_refusals(audit_rows, call_rows):
    """Give each refused audit row without `client_call_id` the id of the call that produced it.

    The rule, a unique match or nothing: among ALL call rows in the same session that were in
    progress when the audit row was written (call start <= audit ts <= call start + 1 s +
    duration, LINK_SLACK either side), there must be exactly one; it must be a refusal carrying
    a call id, with the same refusal_id when both have one, and not already linked. Every call
    is a candidate, whatever its outcome, so a concurrent call with an unreadable body makes the
    match ambiguous instead of leaving one refusal to be pinned on the other's instance. The tool
    is not compared: an op such as `worktree.target` is refused by several tools. Zero or
    several candidates, or one that does not qualify, is counted, never guessed.
    Returns (new rows, stats); input rows are not modified."""
    by_session = defaultdict(list)
    for i, c in enumerate(call_rows):
        by_session[c.get("session")].append(i)
    used, out, stats = set(), [], Counter()
    for r in audit_rows:
        if r.get("decision") != "refused" or "client_call_id" in r:
            out.append(r)
            continue
        stats["refused rows without client_call_id"] += 1
        ts = parse_ts(r["ts"], "audit row")
        hits = [i for i in by_session.get(r.get("session"), ()) if _during(call_rows[i], ts)]
        if len(hits) != 1:
            out.append(r)
            stats["unlinked: %s calls in progress" % ("no" if not hits else "several")] += 1
            continue
        c = call_rows[hits[0]]
        rid = _rid(r.get("detail"))
        if (c.get("outcome") != "refused" or not c.get("client_call_id") or hits[0] in used
                or (rid and c.get("refusal_id") and c["refusal_id"] != rid)):
            out.append(r)
            stats["unlinked: the one call in progress is not this refusal"] += 1
            continue
        used.add(hits[0])
        out.append(dict(r, client_call_id=c["client_call_id"]))
        stats["linked"] += 1
    return out, dict(stats)
