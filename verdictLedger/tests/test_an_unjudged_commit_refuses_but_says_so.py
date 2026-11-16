"""A commit with no admission set REFUSES, and the headline says it was NOT JUDGED.

Reported by the consumer 2026-11-16: `can_push` without `commit_admission` printed
`REFUSED push 1/2 commit(s) short` over one intermediate whose admission was UNSET, and
"it nearly read as a real block". The refusal is right: nobody declared what gates that
commit, and absence is never success. The WORDS were wrong: they priced "not judged" as
"failed", and the remedy for the two is different.
"""

from core.canpush import render


def _result(rows, *, allowed=False, owed=(), carried=()):
    blocking = [r for r in rows if not r["complete"]]
    return {"ok": True, "allowed": allowed, "range": "a..b", "commits_in_range": len(rows),
            "blocking_count": len(blocking),
            "blocking_unjudged": sum(1 for r in blocking
                                     if r.get("admission_state") in ("UNSET", "EMPTY")),
            "commits": rows, "ratchet": {"owed": list(owed), "carried_findings": list(carried)},
            "admission_state": "SET", "missing": [], "stale": [], "failed": [], "legacy": [],
            "refused": [], "forgiven": [], "not_gating": []}


def _row(commit, state="SET", complete=True, sat=1, req=1):
    return {"commit": commit * 40, "admission_state": state, "complete": complete,
            "satisfied": sat, "required": req, "subject": "s", "thinnest": None}


def test_all_unjudged_says_not_judged_and_still_refuses():
    head = render(_result([_row("a", "UNSET", complete=False), _row("b")])).splitlines()[0]
    assert head.startswith("REFUSED")
    assert "NOT JUDGED: 1 commit(s) have no admission set" in head
    assert "commit_admission" in head


def test_a_real_short_commit_keeps_the_plain_count():
    rows = [_row("a", "UNSET", complete=False), _row("b", complete=False, sat=0)]
    head = render(_result(rows)).splitlines()[0]
    assert "NOT JUDGED" not in head and "2/2 commit(s) short" in head


def test_owed_signatures_keep_the_plain_count():
    """An owed signature is a real obligation: it must not be renamed 'not judged'."""
    res = _result([_row("a", "UNSET", complete=False)], owed=[{"step": "s", "path": "p"}])
    head = render(res).splitlines()[0]
    assert "NOT JUDGED" not in head and "owed" in head
