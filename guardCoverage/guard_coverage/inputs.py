"""Load and validate the three inputs. Anything missing or malformed raises InputError.

Absence is never success: a missing file, an empty audit log, a register with no incidents
collection, or a manifest without guards is refused, never measured as "nothing found".
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

# The entry point an incident happened through, taken from the register's free-text `tool`
# field by this explicit table. An unknown `tool` is refused rather than guessed, because
# the entry point decides membership in G.
ENTRY_POINTS = ("gitrobot-mcp/cli", "agent-shell")

TOOL_ENTRY_POINTS = {
    "git (direct, before gitRobot)": "agent-shell",
    "gitRobot push (MCP and CLI)": "gitrobot-mcp/cli",
    "PowerShell (agent shell, not gitRobot)": "agent-shell",
    # Used only by the synthetic replay's end-to-end check.
    "synthetic:gitrobot": "gitrobot-mcp/cli",
}

REGISTER_STATUSES = ("open", "guarded", "wontfix")
MANIFEST_VERSIONS = ("1",)


class InputError(ValueError):
    pass


def parse_ts(value, where: str) -> datetime:
    if not isinstance(value, str):
        raise InputError("%s: timestamp must be an ISO-8601 string, got %r" % (where, value))
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InputError("%s: not an ISO-8601 timestamp: %r" % (where, value)) from None
    if ts.tzinfo is None:
        raise InputError("%s: timestamp has no UTC offset: %r" % (where, value))
    return ts


def parse_opt_ts(value, where: str):
    return None if value is None else parse_ts(value, where)


def entry_point_of(tool) -> str:
    if tool in ENTRY_POINTS:
        return tool
    if tool in TOOL_ENTRY_POINTS:
        return TOOL_ENTRY_POINTS[tool]
    raise InputError("incident tool %r has no entry-point mapping; add it to "
                     "TOOL_ENTRY_POINTS rather than guessing" % (tool,))


def _read(path) -> bytes:
    p = Path(path)
    if not p.is_file():
        raise InputError("input file not found: %s" % p.name)
    return p.read_bytes()


def load_audit(path) -> list:
    rows = []
    for i, line in enumerate(_read(path).decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise InputError("audit log line %d is not JSON: %s" % (i, e.msg)) from None
        validate_row(row, "audit log line %d" % i)
        rows.append(row)
    if not rows:
        raise InputError("audit log has no rows")
    return rows


def load_calls(paths) -> list:
    """Call rows (gitRobot's tool_calls.jsonl, or rows backfilled into that shape) from one or
    more JSONL files. An empty set is refused: the unit is counted from these rows."""
    rows = []
    for path in paths:
        for i, line in enumerate(_read(path).decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise InputError("call log %s line %d is not JSON: %s"
                                 % (Path(path).name, i, e.msg)) from None
            validate_call(row, "call log %s line %d" % (Path(path).name, i))
            rows.append(row)
    if not rows:
        raise InputError("call logs have no rows")
    return rows


def validate_call(row, where):
    if not isinstance(row, dict):
        raise InputError("%s: not an object" % where)
    for k in ("ts", "surface", "session", "client_call_id"):
        if k not in row:
            raise InputError("%s: missing %r" % (where, k))
    if "versions" in row and not isinstance(row["versions"], dict):
        raise InputError("%s: versions must be an object" % where)
    return parse_ts(row["ts"], where)


def load_instance_map(path):
    """{"map": {client_call_id: instance}, "ambiguous": [client_call_id, ...]}: which agent
    instance made each call, and the ids found in several transcripts (optional list).
    Returns (map, frozenset of ambiguous ids)."""
    return validate_instance_map(load_json(path, "instance map"))


def validate_instance_map(doc):
    m = doc.get("map") if isinstance(doc, dict) else None
    if not isinstance(m, dict) or not all(isinstance(k, str) and k and isinstance(v, str) and v
                                          for k, v in m.items()):
        raise InputError("instance map needs a 'map' object of call id -> instance id strings")
    amb = doc.get("ambiguous", [])
    if not isinstance(amb, list) or not all(isinstance(x, str) and x for x in amb):
        raise InputError("instance map 'ambiguous' must be a list of call id strings")
    if set(amb) & set(m):
        raise InputError("instance map lists an id as both mapped and ambiguous")
    return m, frozenset(amb)


def validate_row(row, where):
    if not isinstance(row, dict):
        raise InputError("%s: not an object" % where)
    for k in ("ts", "op", "decision"):
        if k not in row:
            raise InputError("%s: missing %r" % (where, k))
    if "versions" in row and not isinstance(row["versions"], dict):
        raise InputError("%s: versions must be an object" % where)
    return parse_ts(row["ts"], where)


def load_json(path, what):
    try:
        return json.loads(_read(path).decode("utf-8"))
    except json.JSONDecodeError as e:
        raise InputError("%s is not JSON: %s" % (what, e.msg)) from None


_INCIDENT_KEYS = ("id", "pattern_id", "status", "observed_at", "detected_at", "session",
                  "tool", "guard_commit", "guarded_at")


def validate_register(doc) -> dict:
    try:
        coll = doc["collections"]["incidents"]
        entries = coll["entries"]
        rule = coll["pattern_rule"]
    except (KeyError, TypeError):
        raise InputError("register has no collections.incidents with pattern_rule and "
                         "entries") from None
    if not isinstance(entries, list):
        raise InputError("register entries must be a list")
    out = []
    for e in entries:
        where = "register entry %s" % (e.get("id") if isinstance(e, dict) else "?")
        if not isinstance(e, dict):
            raise InputError("%s: not an object" % where)
        for k in _INCIDENT_KEYS:
            if k not in e:
                raise InputError("%s: missing %r" % (where, k))
        # The register names its test; the public extract carries only whether one exists
        # (a hashed name would be recoverable from the manifest's clear names).
        if "regression_test" in e:
            has_test = bool(e["regression_test"])
        elif isinstance(e.get("has_regression_test"), bool):
            has_test = e["has_regression_test"]
        else:
            raise InputError("%s: missing 'regression_test' (or boolean "
                             "'has_regression_test')" % where)
        if e["status"] not in REGISTER_STATUSES:
            raise InputError("%s: status %r not in %s" % (where, e["status"], REGISTER_STATUSES))
        if e["status"] == "guarded" and not (e["guard_commit"] and has_test
                                             and e["guarded_at"]):
            raise InputError("%s: guarded without guard_commit, regression_test and "
                             "guarded_at together" % where)
        if not isinstance(e["pattern_id"], str) or not e["pattern_id"]:
            raise InputError("%s: pattern_id must be a non-empty string" % where)
        out.append({
            "id": e["id"], "pattern_id": e["pattern_id"], "status": e["status"],
            "observed_at": parse_opt_ts(e["observed_at"], where),
            "detected_at": parse_ts(e["detected_at"], where),
            "session": e["session"],
            # OPTIONAL: the agent instance the incident happened in. Without it the incident
            # counts toward items 1 and 2 but stays out of item 4.
            "instance": _opt_str(e.get("instance"), where, "instance"),
            "entry_point": entry_point_of(e["tool"]),
            "guard_commit": e["guard_commit"], "has_regression_test": has_test,
            "guarded_at": parse_opt_ts(e["guarded_at"], where),
        })
    return {"pattern_rule": rule, "entries": out}


def _opt_str(value, where, name):
    if value is not None and (not isinstance(value, str) or not value):
        raise InputError("%s: %s must be a non-empty string or null" % (where, name))
    return value


def validate_manifest(doc) -> dict:
    if not isinstance(doc, dict) or doc.get("manifest_version") not in MANIFEST_VERSIONS:
        raise InputError("manifest_version must be one of %s" % (MANIFEST_VERSIONS,))
    guards = doc.get("guards")
    if not isinstance(guards, list) or not guards:
        raise InputError("manifest declares no guards")
    out, seen = [], set()
    for g in guards:
        where = "manifest guard %s" % (g.get("id") if isinstance(g, dict) else "?")
        if not isinstance(g, dict):
            raise InputError("%s: not an object" % where)
        for k in ("id", "repo", "entry_point", "logs_refusals", "version", "version_at",
                  "pattern_ids", "regression_test"):
            if k not in g:
                raise InputError("%s: missing %r" % (where, k))
        if g["id"] in seen:
            raise InputError("%s: duplicate id" % where)
        seen.add(g["id"])
        if not isinstance(g["logs_refusals"], bool):
            raise InputError("%s: logs_refusals must be true or false" % where)
        if not isinstance(g["entry_point"], str) or not g["entry_point"]:
            raise InputError("%s: entry_point must be a non-empty string" % where)
        tests = g["regression_test"]
        if not isinstance(g["pattern_ids"], list) or not isinstance(tests, dict):
            raise InputError("%s: pattern_ids must be a list and regression_test an object"
                             % where)
        # Every guarded pattern states its test or an explicit null: an omitted entry would
        # otherwise be indistinguishable from "no test".
        if set(tests) != set(g["pattern_ids"]):
            raise InputError("%s: regression_test keys must equal pattern_ids exactly" % where)
        recs = {}
        for pid, rec in tests.items():
            if rec is None:
                recs[pid] = None
                continue
            if not isinstance(rec, dict) or not all(rec.get(k) for k in
                                                    ("test", "guard_commit", "guarded_at")):
                raise InputError("%s: regression_test[%s] needs test, guard_commit and "
                                 "guarded_at, or null" % (where, pid))
            recs[pid] = {"test": rec["test"], "guard_commit": rec["guard_commit"],
                         "guarded_at": parse_ts(rec["guarded_at"], where)}
        version_at = parse_opt_ts(g["version_at"], where)
        # Optional version_history: earlier {version, version_at} pairs, so windows can
        # restart at every dated guard version, not only at the current one.
        hist = g.get("version_history", [])
        if not isinstance(hist, list):
            raise InputError("%s: version_history must be a list" % where)
        versions = []
        for h in hist:
            if not isinstance(h, dict) or not h.get("version") or not h.get("version_at"):
                raise InputError("%s: each version_history entry needs version and "
                                 "version_at" % where)
            versions.append((parse_ts(h["version_at"], where), h["version"]))
        if g["version"] is not None and version_at is not None:
            versions.append((version_at, g["version"]))
        versions.sort(key=lambda x: x[0])
        out.append({"id": g["id"], "repo": g["repo"], "entry_point": g["entry_point"],
                    "logs_refusals": g["logs_refusals"], "version": g["version"],
                    "version_at": version_at, "versions": versions,
                    "patterns": recs})
    # The unit is an AGENT session. Which MCP clients are agents is declared, never assumed:
    # an allow-list, so a new automation client cannot silently inflate n. Absent means "not
    # declared", and then no session counts (reported with its reason), never "all of them".
    agents = doc.get("agent_clients")
    if agents is not None and (not isinstance(agents, list)
                               or not all(isinstance(a, str) and a for a in agents)):
        raise InputError("manifest agent_clients must be a list of client names")
    # The unit is an AGENT INSTANCE (one agent context, such as a subagent), and how a call is
    # tied to one is declared, never assumed: which client's call ids the instance map covers.
    # Absent means no call can be placed in an instance, and then nothing counts toward n.
    src = doc.get("instance_source")
    if src is not None:
        if not isinstance(src, dict) or not isinstance(src.get("client"), str) or not src["client"]:
            raise InputError("manifest instance_source needs a 'client' name")
        if agents is None or src["client"] not in agents:
            raise InputError("manifest instance_source client %r is not a declared agent client"
                             % src["client"])
    return {"guards": out, "agent_clients": None if agents is None else set(agents),
            "instance_client": None if src is None else src["client"]}


def load_windows(path) -> list:
    doc = load_json(path, "windows file")
    b = doc.get("boundaries") if isinstance(doc, dict) else None
    if not isinstance(b, list) or not b:
        raise InputError("windows file needs a non-empty 'boundaries' list of timestamps")
    return sorted(parse_ts(x, "windows boundary") for x in b)
