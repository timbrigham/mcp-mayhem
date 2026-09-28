"""`can_push`'s `allowed` prices the ledger's bar and not the push, and now says so.

⛔⛔ MEASURED 2026-09-28, AND IT COST A REAL PUSH. `can_push` answered ALLOWED with
`blocking_count: 0`, and `git push` then FAILED at the pre-push hook: `batch.py`'s routing legs
refused because `tools/verify/required.v2.json` had been edited after the last `/rely` round, so its
current bytes carried no signature.

⚠⚠ `witness.blind_to` ALREADY NAMED THAT LAYER, THAT MECHANISM, AND THAT EXACT FILE — *"the
pre-push hook's routing legs (`batch.py`), which enforce per-file `/rely` signatures over changed
routed files with no admission key … `tools/verify/required.v2.json` is the live instance."* The
disclosure was correct and specific. **It was not attached to the field anybody reads.**

⛔⛔ AND THE GAP WAS BUILT THE DAY BEFORE, BY ME. `preflight.passed` gained `passed_prices` on
2026-09-27, which tells its reader *"NOT a prediction that the push will be allowed … TO LEARN
WHETHER THE PUSH WILL GO: can_push(rev_range=…)"*. So the chain was:

    preflight.passed  ->  "ask can_push"
    can_push.allowed  ->  (no caveat at all)
    reality           ->  a layer can_push documents being blind to, refusing

**I pointed a reader at a surface that did not carry the warning I had just added to the one they
came from.** That is `SH-3` — the same fix applied at one level and not its sibling — sixth instance
in this file, and the only one I created rather than inherited.

⚠ IT IS NOT A DANGEROUS FAIL-OPEN. The hook held and nothing shipped wrongly. This is a false green
in a PREDICTIVE surface: it costs a wasted push cycle and a reader's trust, not correctness.

⭐ AND THE SAME SENTENCE CLOSES THE FIFTH INSTANCE. The "admission UNSET is NOT a coverage failure"
warning lived only in the RENDERED text, so a caller reading `blocking_count` programmatically got a
number with nothing saying it is meaningless when nothing declared what gates a commit. That one
caught ME, reconciling a figure with the consumer — I nearly reported a disagreement caused by my own
omitted `commit_admission`.
"""

import pytest

from core import canpush as canpush_mod
from test_can_push import _blob, _rec, _repo

STEP = "check_encoding"


def _check(ledger, tmp_path, rng, records=(), admission=(STEP,)):
    return canpush_mod.check(records=list(records), config=ledger.config, repo=str(tmp_path),
                             rev_range=rng, admission=list(admission),
                             commit_admission=list(admission))


def test_the_scope_names_the_layer_it_cannot_see(ledger):
    """⭐⭐ THE HEADLINE. A reader must be able to construct the next question from this text: what
    `allowed` covers, what it does not, and where the other answer lives."""
    s = canpush_mod.ALLOWED_SCOPE
    assert "ADMISSION BAR" in s
    # ⛔ it must DENY the inference that actually got made, not merely describe itself
    assert "NOT a prediction that" in s and "git push" in s
    # ⭐ and name the layer, not gesture at it — `witness.blind_to` is where the detail lives
    assert "pre-push hook" in s and "/rely" in s and "blind_to" in s
    # ⚠ the fifth instance rides in the same sentence
    assert "blocking_count" in s and "UNSET" in s and "commit_admission" in s


def test_it_renders_on_a_real_allowed_answer(ledger, tmp_path):
    """⚠ ON THE PATH THAT ANSWERS TRUE, which is the one that misleads. A caveat that appears only
    on refusals is the 2026-09-22 freeze caveat again: rendered in the broken state and silent in
    the state that produced the defect."""
    # ⚠ A SINGLE-COMMIT RANGE. A wider one leaves the intermediate commit's own row stale, so
    # `allowed` is False for a reason that has nothing to do with this field — the same fixture
    # mistake the carried-findings test made, caught the same way.
    base, shas = _repo(tmp_path, n=2)
    prev, tip = shas[0], shas[-1]
    result = _check(ledger, tmp_path, prev + ".." + tip,
                    [_rec(STEP, "doc.md", _blob(tmp_path, tip, "doc.md"), tip)])
    assert result["allowed"] is True, f"fixture no longer produces an allowed answer: {result}"
    assert result["allowed_prices"] == canpush_mod.ALLOWED_SCOPE


def test_it_renders_on_the_empty_range_too(ledger, tmp_path):
    """⛔⛔ THE SECOND PATH THAT CAN ANSWER TRUE, AND I NEARLY MISSED IT. Checking for other
    `allowed: True` returns is what found it — the empty-range branch. An empty range cannot be
    refused by the hook, so the caveat is not load-bearing there; it is present so that a field
    appearing on one `allowed: true` and not another cannot teach a reader it is optional."""
    base, shas = _repo(tmp_path, n=1)
    tip = shas[-1]
    result = _check(ledger, tmp_path, tip + ".." + tip)
    assert result.get("empty_range") is True, f"fixture did not produce an empty range: {result}"
    assert result["allowed"] is True
    assert result["allowed_prices"] == canpush_mod.ALLOWED_SCOPE, (
        "the empty-range path answers `allowed: true` without the scope statement, so the field "
        "is present on one true and absent on another")


def test_it_is_one_constant_and_not_a_restatement(ledger):
    """⛔ THE ANTI-DRIFT ASSERTION. Two `allowed: true` paths quoting one constant cannot disagree;
    two hand-written paragraphs will, and the one that goes stale is the one nobody re-reads. The
    first draft inlined the text at one return and would have needed a second copy for the other."""
    import inspect
    src = inspect.getsource(canpush_mod)
    literal = "THE LEDGER'S ADMISSION BAR OVER THIS RANGE"
    assert src.count(literal) == 1, (
        f"{src.count(literal)} copies of the scope text; it must be defined once and referenced")
    assert src.count('"allowed_prices": ALLOWED_SCOPE') == 2, (
        "both `allowed: true` paths must attach the constant — a scope statement on one and not "
        "the other is the half-applied guard this file has now shipped twice")


def test_blind_to_still_names_the_live_instance(ledger, tmp_path):
    """⚠ THE DETAIL MUST SURVIVE IN `witness.blind_to`, because `allowed_prices` points AT it. If
    the pointer outlives the detail, the scope statement becomes a promise to a missing page."""
    base, shas = _repo(tmp_path, n=2)
    tip = shas[-1]
    result = _check(ledger, tmp_path, base + ".." + tip,
                    [_rec(STEP, "doc.md", _blob(tmp_path, tip, "doc.md"), tip)])
    blind = ((result.get("witness") or {}).get("blind_to")) or ""
    assert "batch.py" in blind and "/rely" in blind, (
        "`allowed_prices` points readers at `witness.blind_to` and it no longer names the layer")
    assert "required.v2.json" in blind, (
        "blind_to no longer names the live instance — the file that actually refused a push on "
        "2026-09-28")
