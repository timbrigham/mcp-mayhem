"""Every published vocabulary is BOUND to the code that emits it — or says it is not.

⛔⛔ THE DEFECT THESE PIN, MEASURED 2026-09-10. `mcpcommon/vocabulary.py` was built to be the
one definition of the fleet's vocabularies, and `CLAUDE.md` requires such a resource be
GENERATED from the constants the code imports, forbidding one that "merely describes what the
code happens to do". Counted that day:

    ERROR_TYPES    bound in 4 files   <- meets the standard
    DECISIONS      bound in 0 files
    ROW_STATUSES   bound in 0 files
    EXIT_CODES     bound in 0 files

⚠ So THREE OF THE FOUR WERE THE FORBIDDEN KIND, sitting in one dict beside the one that was
not, rendered by one function and served through one resource — indistinguishable to a reader.
`error_type` was consolidated because it was the live measured defect at the time; the other
three were added alongside it and nothing ever bound them.

⭐ AND BOTH UNBOUND FAILURES HAD ALREADY HAPPENED BY THE TIME ANYONE COUNTED:
  · `EXIT_CODES[3]` invented "a contested panel" — caught by the consumer's gate.
  · `EXIT_CODES[2]` described a usage error while every real emitter meant "could not RECORD",
    contradicting our own `client/record.py` — caught by a third session reading the resource.
  · `DECISIONS` omitted `started`, which `preflight` and `push` have always written and
    `preflight_status` READS BACK — caught only by counting binding sites.

A one-directional check lets debt sit forever, so each test below fails in BOTH directions:
when the code emits a value nobody published, AND when the table publishes one the code cannot
emit.
"""

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "gitRobot"))

from mcpcommon.vocabulary import (  # noqa: E402
    DECISIONS, EXIT_CODES, MINTABLE_EXIT_CODES, RESERVED_EXIT_CODES, ROW_STATUSES)


def _source(rel):
    return (_ROOT / rel).read_text(encoding="utf-8")


# -- decision -----------------------------------------------------------------
# ⛔ THE DECISION TESTS LIVE IN `gitRobot/tests/test_decision_vocabulary.py`, NOT HERE.
# Two reasons, both measured while writing them:
#   · `core.audit` resolves to verdictLedger's `core` package under this suite's sys.path,
#     so importing gitRobot's binding from here loads the wrong module and the test passes
#     or fails for a reason unrelated to its subject.
#   · A SOURCE-SCANNING test for emitted decisions is the wrong instrument. The first draft
#     matched `_receipt(op, {"path": ..., "repo": ...}, decision, ...)` and reported `path`,
#     `repo`, `paths`, `unlinked`, `cached` and `dirty_after_hours` as unpublished decision
#     values. They are DICT KEYS in the `args` argument. A regex that cannot see the
#     difference between an argument and a key inside one produces six false findings and
#     would have sent a reader to add them to the vocabulary.
# ⭐ The RUNTIME binding is exact where the regex is approximate: `_decision()` raises inside
# `audit.append`, through which every audit row passes, so any unpublished value fails the
# moment a code path writes one — and 336 gitRobot tests exercise those paths.

# -- row_status ---------------------------------------------------------------

def test_every_row_status_the_inventory_assigns_is_published():
    """⚠ `UNVALIDATED` was added 2026-09-07 and `CLAUDE.md` flagged that it "appears in no
    list, so nothing can enumerate the statuses a caller may receive". It is published now;
    this is what keeps the next one from repeating it."""
    src = _source("verdictLedger/core/inventory.py")
    assigned = set(re.findall(r'status["\]\s]*=\s*"([A-Z_]{3,})"', src))
    assigned |= set(re.findall(r'r\["status"\]\s*=\s*"([A-Z_]+)"', src))
    unpublished = sorted(assigned - set(ROW_STATUSES))
    assert not unpublished, (
        "inventory.py assigns row status(es) %s that ROW_STATUSES does not publish"
        % unpublished)


def test_no_row_status_is_published_that_the_inventory_cannot_assign():
    """⚠ THE OTHER DIRECTION, WHICH IS THE HALF THAT ROTS QUIETLY. A published status no
    code can produce tells a caller to handle a case that will never arrive — and unlike a
    missing value it never fails loudly, so nothing ever prompts its removal."""
    src = _source("verdictLedger/core/inventory.py")
    unproducible = sorted(s for s in ROW_STATUSES if '"%s"' % s not in src)
    assert not unproducible, (
        "ROW_STATUSES publishes %s but inventory.py never assigns them" % unproducible)


# -- exit_code ----------------------------------------------------------------

def test_exit_codes_our_own_client_emits_are_published():
    """⛔⛔ THIS TEST'S SCOPE IS DELIBERATELY NARROW AND SAYS SO, BECAUSE IMPLYING MORE
    WOULD BE THE DEFECT IT EXISTS TO CATCH.

    Exit codes are emitted by the CONSUMER's checkers, in another repository. Nothing here
    can import them, so `EXIT_CODES` is the one table in the dict that is UNBINDABLE from
    this side — a published convention the fleet does not enforce.

    ⭐ What IS in reach is `verdictLedger/client/record.py`, our own template, which the
    consumer copied. It is the only exit-code emitter this repo owns, and in 2026-09-10 it
    was the thing the vocabulary CONTRADICTED: the client had said `sys.exit(2)` for "ledger
    unavailable or record rejected" since before the dict existed, while the dict published
    "the check could not run — usage error". The copy held still and the ORIGIN drifted."""
    src = _source("verdictLedger/client/record.py")
    emitted = {int(c) for c in re.findall(r'sys\.exit\((\d)\)', src)}
    assert emitted, "no sys.exit(N) found — this test's only binding has moved"
    unpublished = sorted(emitted - set(EXIT_CODES))
    assert not unpublished, (
        "client/record.py exits with code(s) %s that EXIT_CODES does not publish"
        % unpublished)


def test_exit_code_2_no_longer_carries_the_refusal_it_used_to():
    """⛔⛔ THE SPLIT, 2026-09-10. Entry 2 used to admit BOTH "none was reached" AND "one was
    reached and REJECTED", and two earlier versions of this test PINNED that — first to a
    phrasing, then to the property. Both were right about the code at the time and both were
    guarding a collapse rather than a distinction.

    ⚠ The two halves differ on the one axis `error_type` says must never be collapsed:
    `unavailable` is RETRYABLE, `validation` is TERMINAL. While they shared a code the only
    remedy the vocabulary could offer was "read the line" — dispatch on prose, which this
    fleet forbids everywhere else. A DIFFERENT VALUE, NOT A DIFFERENT MESSAGE.

    ⭐ THE CONSUMER HAD ALREADY DONE THIS AND ITS WORKAROUND IS WHAT DATED THE GAP.
    `check_briefs.classify_record_failure` split the code itself, on the strength of a second
    network call (`record.reachable()`) recovering what `emit` already knew and discarded.
    """
    two = EXIT_CODES[2].lower()
    # ⚠ THE FIRST DRAFT OF THIS ASSERTION BANNED THE WORD "refus" ANYWHERE IN ENTRY 2 AND WENT
    # RED ON A CORRECT ENTRY — because 2 legitimately POINTS AT 4 ("4 is asked AND REFUSED"),
    # and a cross-reference is not a claim. That is the same brittleness as the version of
    # this test that pinned a phrasing rather than a behaviour, two drafts ago. The property
    # is that 2 no longer names the refusal as one of ITS OWN outcomes.
    assert "reached and rejected" not in two, (
        "entry 2 still claims the refusal as its own outcome — that is 4 now, and an entry "
        "claiming both is the collapse this split removed")
    assert "could not ask" in two, "entry 2 must lead with the half it kept"
    assert "retry" in two, "entry 2 must still say it is the RETRYABLE half"
    assert "4" in two, "entry 2 must name 4, or a reader cannot find the other half"
    assert "3" in two, "entry 2 must still say how it differs from 3, or the two collapse"


def test_exit_code_4_is_the_terminal_refusal_and_says_never_retry():
    """⛔ 4 IS TERMINAL AND THE WORD MUST BE THERE. A refusal is a RULE being applied, so the
    same call will be refused again; retrying is how a caller under pressure gets past a rule
    it should have obeyed. `error_type` documents that exact failure as the reason `unavailable`
    and `validation` may never share a code."""
    four = EXIT_CODES[4].lower()
    assert "refus" in four, "4 must name the refusal it prices"
    assert "terminal" in four, "4 must say it is terminal"
    assert "retry" in four, "4 must tell the caller not to retry"
    assert "reject" not in EXIT_CODES[3].lower(), (
        "3 is CONTENT-undetermined; a refused RECORD is 2 or 4 and must not leak into it")


def test_our_client_actually_distinguishes_a_refusal_from_an_outage():
    """⛔⛔ THE FIRST VERSION OF THIS TEST WAS PROSE COVERAGE AND A CONTROL CAUGHT IT.

    It asserted the literals `"refused"` and `"unreachable"` appeared in record.py's SOURCE.
    Arming a control — making `emit_ex`'s refusal branch return "unreachable" — did NOT fail it,
    because the word `"refused"` still appeared in the DOCSTRING. A test that greps the file for
    a string it also documents cannot tell an implementation from its own description. That is
    the defect this whole session kept finding: a test pinning a shape while looking like cover.

    ⭐ THIS ONE EXERCISES THE BRANCHES. A published value nothing can emit is the defect, not
    the fix — `config` sat in ERROR_TYPES published and unused until 2026-09-10, and adding 4
    while the client could only ever produce one code would have been the same shape.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_record_under_test", _ROOT / "verdictLedger" / "client" / "record.py")
    record = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(record)

    calls = {"n": 0}

    def refuses(*_a, **_k):
        calls["n"] += 1
        return {"ok": False, "errors": ["V8: step 'nope' is not registered"]}

    def unreachable(*_a, **_k):
        calls["n"] += 1
        raise OSError("connection refused")

    args = ("step", "tier", "PASS", [], "basis")

    record._call = refuses
    rid, failure = record.emit_ex(*args)
    assert rid is None and failure == "refused", (
        "a ledger that ANSWERED and said no must be tagged terminal, not as an outage — "
        "got %r" % (failure,))
    before = calls["n"]

    record._call = unreachable
    rid, failure = record.emit_ex(*args)
    assert rid is None and failure == "unreachable", (
        "a transport failure must be tagged retryable — got %r" % (failure,))
    assert calls["n"] > before + 1, (
        "the unreachable path must RETRY; a refusal must not. If these retry alike, the "
        "terminal/retryable split exists in the tag and not in the behaviour")

    # And the codes those two map onto must both be published.
    assert 2 in EXIT_CODES and 4 in EXIT_CODES


def test_every_published_exit_code_is_mintable_or_a_deliberately_adopted_convention():
    """⭐⭐ THE FENCE ON "MINT A CODE ANY TIME" — Tim, 2026-09-10: "I am completely good with
    having a dedicated response code anytime ... it's not like it's possible to run out of
    numbers." The policy is right and the numbers are NOT all free.

    ⛔ MEASURED ON THIS MACHINE 2026-09-10: Windows preserves exit codes as 32-bit —
    `sys.exit(256)` and `sys.exit(300)` return 256 and 300 intact. ⚠ POSIX exposes only the low
    8 bits, so 256 arrives as **0, A SUCCESS**. That half is a documented platform property and
    is NOT measured here; what IS measured here is that the dev box does not truncate, which is
    precisely what makes it dangerous — **the same checker exiting 256 is a catastrophic false
    PASS on Linux CI and a distinct code on the machine it was written on.**

    ⚠ And 126/127/128+N are already spoken for on POSIX, so a minted 130 is indistinguishable
    from a Ctrl-C and a 139 from a segfault.
    """
    for code in EXIT_CODES:
        if code == 0:
            continue
        if code in MINTABLE_EXIT_CODES:
            continue
        assert code in RESERVED_EXIT_CODES, (
            "exit code %d is outside the mintable band 1..123 and is not a documented "
            "convention. Either mint inside the band or record why this number was adopted."
            % code)
        assert "ADOPTED" in RESERVED_EXIT_CODES[code], (
            "exit code %d is published but its reserved-map entry does not say it was "
            "deliberately adopted — a published code sitting on a platform meaning is two "
            "answers to one number" % code)


def test_no_published_code_can_be_truncated_into_success():
    """⛔ THE ONE THAT WOULD BE UNRECOVERABLE. A code above 255 becomes `code & 0xFF` on POSIX,
    and any multiple of 256 becomes 0 — the pipeline reads a PASS for a check that failed.
    A false FAILURE gets re-run and discovers itself; this is the other direction."""
    for code in EXIT_CODES:
        assert 0 <= code <= 255, "exit code %d truncates on POSIX" % code
        assert code == 0 or (code & 0xFF) != 0, (
            "exit code %d becomes 0 — a SUCCESS — after POSIX truncation" % code)


def test_exit_codes_gitrobot_actually_emits_are_published():
    """⛔⛔ THE RATCHET IN THE DIRECTION THAT WAS NEVER CHECKED: the code emits a value nobody
    published. Found 2026-09-10 by applying Tim's mint-a-code policy and asking what we already
    emit — `gitRobot/core/gates.py` has returned `exit_code=124` on `subprocess.TimeoutExpired`
    since before EXIT_CODES existed, and 124 was in no published list. A caller receiving it had
    no route to its meaning.

    ⚠ SCOPE, STATED SO IT IS NOT READ AS WIDER: this scans ONE file for literal `exit_code=N`
    assignments. It is not a proof that nothing else in the fleet emits an unpublished code."""
    src = _source("gitRobot/core/gates.py")
    emitted = {int(c) for c in re.findall(r"exit_code=(\d+)", src)}
    assert emitted, "no literal exit_code=N found — this test's binding has moved"
    unpublished = sorted(emitted - set(EXIT_CODES))
    assert not unpublished, (
        "gates.py emits exit code(s) %s that EXIT_CODES does not publish" % unpublished)


def test_exit_code_0_does_not_claim_the_check_found_nothing():
    """⛔ MEASURED: `check_poles` exits 0 printing "26 pole-equality site(s)" and
    `check_divergent` exits 0 printing "5 surviving retired phrase(s)". Published 0 said "the
    check ran and found nothing", which is FALSE of both.

    ⚠ The checkers are not wrong — an advisory enumeration is "a READING LIST, never a finding
    list" by the consumer's own rule, so exiting 0 is DESIGNED. The table had no slot for
    "ran, enumerated, owes no verdict", leaving an intended WARN indistinguishable from clean.
    ⛔ And the wrong fix would be making them exit 1, which turns a reading list into a
    blocking finding."""
    zero = EXIT_CODES[0].lower()
    # ⚠ NOT a ban on the phrase "found nothing" — the entry may say that is the USUAL case
    # and remain true. What it must not do is stop there, which is what made it false of an
    # advisory leg. So the test asserts the exception is NAMED, not that a word is absent.
    # (The first draft banned the substring and went red on correct text — a guard reading a
    # phrasing where it meant to read a property, twice in one file.)
    assert "owes no verdict" in zero or "nothing to answer" in zero, (
        "0 must say what it actually certifies — that nothing is OWED, not that nothing exists")
    assert "enumeration" in zero or "advisory" in zero, (
        "0 must name the advisory-enumeration case, or an intended WARN reads as clean")
