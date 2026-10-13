"""The known incidents, each taken from an existing record rather than reconstructed from memory.

Every value is either quoted from its source or left null; where a required field is not known
exactly, the note says what the value is bounded by. Applied through the verbs, so seeding gets
the same validation and audit as any other write:

    python -m consumers.incidents.seeds <path/to/incidents.json>
"""

from __future__ import annotations

import sys

SEEDS = [
    {
        "add": {
            "observed_at": None,
            # The earliest record of this incident is gitRobot's first commit, ba30b87, at
            # 2026-08-22T20:27:40Z; the incident itself predates it, so it was detected no later.
            "detected_at": "2026-08-22T20:27:40+00:00",
            "detected_by": "unknown",
            "tool": "git (direct, before gitRobot)",
            "operation": "reset --hard",
            "args": ["reset", "--hard"],
            "harm": ("an agent told to leave the repository as it found it ran git reset --hard "
                     "three times on a shared tree, destroyed an uncommitted CLAUDE.md edit, and "
                     "reported the tree clean"),
            "pattern_id": "git.reset.work-destroying",
            "note": ("Source: gitRobot/README.md, 'Why all of git'. detected_at is the earliest "
                     "record (commit ba30b87), not the moment of detection; detected_by is unknown "
                     "because the README does not say who noticed. Refused on the real path from "
                     "ba30b87 by the read allow-list; the guard named below is 77c6d09, the first "
                     "commit where the named regression test exists and runs."),
        },
        "guard": {
            "guard_commit": "77c6d094cbde1cd4b47cc7780d944d660746ff43",
            "regression_test": ("gitRobot/tests/test_tier1_refusals.py::"
                                "test_refused_through_read_and_the_work_survives"),
            "guarded_at": "2026-10-10T02:12:12+00:00",
        },
    },
    {
        "add": {
            "observed_at": None,
            # Found while building a restriction-verification harness (commit 77c6d09).
            "detected_at": "2026-10-10T02:12:12+00:00",
            "detected_by": "review",
            "tool": "gitRobot push (MCP and CLI)",
            "operation": "push",
            "args": {"branch": "+illustrated"},
            "harm": ("a branch name with a leading '+' is a force refspec: the push overwrote a "
                     "colleague's commit on a diverged remote while push('illustrated') refused"),
            "pattern_id": "gitrobot.push.refspec-force",
            "note": ("Source: commit 77c6d09, found while building a restriction-verification "
                     "harness. observed_at is null: gitRobot's production audit log (6,042 rows, "
                     "2026-08-22 to 2026-10-13) holds no push whose branch starts with '+' or "
                     "contains ':'. detected_at is the fix commit's time, an upper bound."),
        },
        "guard": {
            "guard_commit": "77c6d094cbde1cd4b47cc7780d944d660746ff43",
            "regression_test": ("gitRobot/tests/test_push_refspec_is_not_a_force_flag.py::"
                                "test_refspec_syntax_is_refused_and_the_remote_commit_survives"),
            "guarded_at": "2026-10-10T02:12:12+00:00",
        },
    },
]


def apply_seeds(store, actor: str = "seed") -> list[str]:
    """Add each seed and record its guard. Refuses to seed a store that already has entries."""
    existing = store.load()["collections"]["incidents"]["entries"] if store.exists() else []
    if existing:
        raise SystemExit("the incidents store already has entries; seeds are applied once")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()     # notes are stamped when they are written
    ids = []
    for seed in SEEDS:
        res = store.apply("incidents", "add_incident", {**seed["add"], "note_at": now},
                          actor=actor)
        iid = res["entries_touched"][0]
        if seed.get("guard"):
            store.apply("incidents", "set_guarded", {"id": iid, **seed["guard"]}, actor=actor)
        ids.append(iid)
    return ids


if __name__ == "__main__":
    from consumers.incidents import build_incident_store
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m consumers.incidents.seeds <path/to/incidents.json>")
    print(apply_seeds(build_incident_store(sys.argv[1], actor="seed")))
