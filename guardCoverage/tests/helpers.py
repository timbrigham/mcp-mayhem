"""Small hand-built inputs for the tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)

VERS = {"gitrobot_commit": "aaa", "gitrobot_dirty": False, "client_name": "cc",
        "client_version": "1", "consumer_hook_commit": None}


def ts(hours):
    return (T0 + timedelta(hours=hours)).isoformat()


def row(h, op="status", decision="allowed", *, session="s1", surface="mcp",
        refusal_class=None, versions=VERS, args=None, legacy=False):
    """A post-2026-10-13 row unless legacy=True (then the newer fields are ABSENT)."""
    r = {"ts": ts(h), "op": op, "decision": decision, "args": args or {}}
    if legacy:
        return r
    r.update(surface=surface, session=session, refusal_class=refusal_class)
    if versions is not None:
        r["versions"] = dict(versions)
    return r


def refusal(h, session="s1", sub="reset", op="read", cls="policy", **kw):
    return row(h, op, "refused", session=session, refusal_class=cls,
               args={"op": sub} if op == "read" else kw.pop("args", {}), **kw)


def sessions(n, start=0, versions=VERS):
    return [row(start + i, session="s%04d" % i, versions=versions) for i in range(n)]


def incident(iid, pattern, *, tool="gitRobot push (MCP and CLI)", session=None,
             observed=None, detected=0, status="guarded", commit="c1", test="t::x",
             guarded=10):
    return {"id": iid, "pattern_id": pattern, "status": status,
            "observed_at": None if observed is None else ts(observed),
            "detected_at": ts(detected), "session": session, "tool": tool,
            "guard_commit": commit if status == "guarded" else None,
            "regression_test": test if status == "guarded" else None,
            "guarded_at": ts(guarded) if status == "guarded" else None,
            "harm": "secret harm", "notes": []}


def register(*entries, rule="1"):
    return {"collections": {"incidents": {"schema_version": "1", "pattern_rule": rule,
                                          "entries": list(entries)}}}


def guard(gid, entry_point, patterns, *, logs=True, version="v1", version_at=None):
    """patterns: {pattern_id: (guard_commit, guarded_at_hours) or None for no test}."""
    return {"id": gid, "repo": "r", "entry_point": entry_point, "logs_refusals": logs,
            "version": version, "version_at": None if version_at is None else ts(version_at),
            "pattern_ids": list(patterns),
            "regression_test": {p: (None if v is None else
                                    {"test": "t", "guard_commit": v[0], "guarded_at": ts(v[1])})
                                for p, v in patterns.items()}}


def manifest(*guards):
    gs = list(guards)
    if not any(g["id"] == "gitrobot" for g in gs):
        gs.insert(0, guard("gitrobot", "gitrobot-mcp/cli", {}, version_at=-1000))
    # "cc" is the client name helper rows carry (VERS), declared as the agent client
    return {"manifest_version": "1", "guards": gs, "agent_clients": ["cc"]}
