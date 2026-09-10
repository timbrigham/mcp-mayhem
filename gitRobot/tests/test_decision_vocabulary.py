"""`decision` is bound to the published vocabulary at the one point every audit row passes.

⛔⛔ THE DEFECT, MEASURED 2026-09-10. `mcpcommon/vocabulary.py` published four decision values
— allowed, refused, failed, skipped — while this server emitted FIVE. `started` is written by
both `preflight` and `push`, and `preflight_status` FINDS A RUN BY QUERYING FOR IT:

    audit.last_where(op="preflight", head=head, decision="started")

So the one value meaning WORK IS IN FLIGHT appeared in no published list. A caller enumerating
the vocabulary to learn what an audit row may say would read a RUNNING push as no push — the
`0`-vs-`null` shape, in the table built to end exactly that.

⚠ IT SURVIVED BECAUSE NOTHING BOUND THE TABLE TO THE CODE. Counted that day: `ERROR_TYPES`
bound in four files, `DECISIONS`/`ROW_STATUSES`/`EXIT_CODES` in zero. The consolidation that
fixed `error_type` — a live measured defect at the time — never reached the three tables added
beside it, and all four look identical in one dict rendered by one function.

⭐ THE BINDING IS AT `audit.append`, NOT AT THE CALL SITES. Twenty-odd callers pass a decision;
one function receives them all. Bounding at the choke point is the same argument `_receipt`
already makes about clipping, and the same one it got WRONG by clipping `detail` while `extra`
went past untouched — so this one is placed where the value cannot route around it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.audit import _decision  # noqa: E402
from mcpcommon.vocabulary import DECISIONS  # noqa: E402


def test_a_published_decision_passes_through_unchanged():
    for value in DECISIONS:
        assert _decision(value) == value


def test_an_unpublished_decision_is_REFUSED_not_coerced():
    """⛔ SEEN TO FAIL, WHICH IS THE ONLY VERSION WORTH HAVING. A guard that demonstrates the
    accept path and asserts the reject path is an unpriced exemption bought with a fix.

    ⚠ And it must RAISE rather than coerce or drop: a silently-dropped decision would leave
    an audit row with no decision at all, which reads as an absent record rather than a wrong
    one — absence rendering as success, one more time."""
    try:
        _decision("halfway")
    except AssertionError as exc:
        assert "DECISIONS" in str(exc)
        assert "Add it there" in str(exc), (
            "the refusal must name the success condition — where to add the value — not "
            "merely state that this one is wrong")
    else:
        raise AssertionError("an unpublished decision was ACCEPTED; the binding is inert")


def test_started_is_published_because_the_async_path_reads_it_back():
    """⚠ THE SPECIFIC REGRESSION. `started` is the only NON-TERMINAL value in the table: a row
    carrying it promises a later row rather than reporting an outcome. Dropping it from the
    vocabulary again would not break this server — it would break every caller trying to tell
    a push in flight from no push at all."""
    assert "started" in DECISIONS
    assert "NON-TERMINAL" in DECISIONS["started"], (
        "the meaning must say it is not an outcome, or a caller will branch on it as one")


def test_the_audit_layer_is_where_the_check_lives():
    """⚠ A binding at the call sites is a binding with twenty copies. This asserts the choke
    point still routes through the check, so moving the call out of `append` fails loudly
    rather than silently unbinding the vocabulary."""
    src = (Path(__file__).resolve().parents[1] / "core" / "audit.py").read_text(
        encoding="utf-8")
    assert "decision = _decision(decision)" in src, (
        "audit.append no longer validates `decision` — every published value is now a claim "
        "nothing enforces")
