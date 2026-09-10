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

from mcpcommon.vocabulary import DECISIONS, EXIT_CODES, ROW_STATUSES  # noqa: E402


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


def test_exit_code_2_covers_BOTH_the_outage_and_the_refusal_path():
    """⛔⛔ MEASURED 2026-09-10, AND IT FALSIFIED THE FIX MADE EARLIER THE SAME DAY. Entry 2
    was corrected to say "2 means no verdict reached the ledger at all". A test session then
    ran the refusal path — ledger REACHABLE, `record.py --step <unregistered>`:

        exit 2 / "UNDECIDED: record refused by verdictLedger: - V8: step ... not registered"

    The ledger was REACHED. It DECIDED. It decided NO. And the code is 2. So the broad clause
    admitted the refusal while the discriminator excluded it — one sentence contradicting the
    one before it, in the entry I had just corrected for being too specific.

    ⚠ THIS TEST NOW ASSERTS THE PROPERTY, NOT MY WORDING. Its first version required the
    literal string "could not be recorded" and went red on a correction that made the entry
    MORE accurate — a guard pinned to a phrasing rather than a behaviour, which is the same
    brittleness as the defect it watches."""
    two = EXIT_CODES[2].lower()
    assert "reached" in two and ("reject" in two or "refus" in two), (
        "entry 2 must admit BOTH paths: no verdict reached, AND one reached and rejected")
    assert "3" in two, "entry 2 must say how it differs from 3, or the two collapse"


def test_exit_code_2_warns_that_it_collapses_retryable_and_terminal():
    """⛔⛔ THE R-ZERONULL FINDING, AND IT IS THE MOST SERIOUS THING ARM 1 RETURNED. An outage
    and a refusal return THE SAME VALUE and differ only in printed prose.

    ⚠ THOSE TWO MAP ONTO THE ONE DISTINCTION THIS FLEET'S OWN `error_type` TABLE SAYS MUST
    NEVER BE COLLAPSED — `unavailable` is RETRYABLE, `validation` is TERMINAL, and conflating
    them is documented there as "how a rule gets retried past". A caller branching on the exit
    code alone cannot tell "the ledger is down, try again" from "the ledger said no, stop".

    ⭐ The consumer already built `reachable()` to split one exit code in two. A workaround in
    the consumer is EVIDENCE of a gap here, not a substitute for naming it. Until the code
    space can carry the difference, the vocabulary must at least say it cannot."""
    two = EXIT_CODES[2].lower()
    assert "retry" in two, (
        "entry 2 must warn that the code alone does not distinguish retryable from terminal")


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
