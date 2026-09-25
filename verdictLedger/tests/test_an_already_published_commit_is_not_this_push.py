"""A commit already on the push target is not published BY this push.

⭐⭐ Tim's ruling 2026-09-25, and the case that produced it. `ce32401a` is GitHub's own merge
commit for PR #139 — created by the remote when the PR merged, pulled into `illustrated` by the
`R-BRANCH`-mandated `merge(origin/main)`, and already an ancestor of `origin/main`. Four
mechanical steps read STALE there, so the gate demanded verdicts on a commit whose bytes the
world already has. **Pushing publishes no new content from it.**

⚠⚠ THAT IS THE GRANDFATHERING CASE THE RATCHET MODEL ALREADY DESCRIBES — Tim, 2026-09-17: accept
today's baseline, ratchet new bytes. Bytes inherited from a required merge of a published ref are
baseline; this branch is not their publication event.

⛔⛔ AND IT IS NOT FORGIVING STALE, which Tim ruled against the same week. Measured on the live
range at the time:

    commit      blobs absent at tip    ancestor of origin/main
    ce32401a           141                     YES    <- inherited, already published
    69d1d979             9                      no    <- authored HERE, never judged
    3233e56f             0                      no

A STALE forgiveness fires on the LEFT column — churn — and cannot tell an inherited commit from
one we wrote, never reviewed, and overwrote before pushing. This fires on the RIGHT: PROVENANCE.
"""

import subprocess

import pytest

from core import canpush as canpush_mod
from test_can_push import _blob, _rec, _repo

STEP = "check_encoding"
PATH = "doc.md"


def _enable(ledger, on=True):
    """`on=None` leaves the key ABSENT, which is the real default path.

    ⛔⛔ THE FIRST VERSION OF THIS HELPER COULD ONLY SET IT EXPLICITLY, AND THAT MASKED A
    MUTANT. `test_it_is_off_unless_policy_says_otherwise` passed `on=False`, so flipping the
    config default from `raw is True` to `raw is not False` did not fail a single test — an
    explicit False is False under both readings. **The default is what happens when nobody
    writes the key**, and that case was never exercised.
    """
    ledger.config.policy = dict(ledger.config.policy or {})
    push = dict(ledger.config.policy.get("push") or {})
    if on is None:
        push.pop("forgive_inherited_published", None)
    else:
        push["forgive_inherited_published"] = on
    push["bar"] = "every_commit"      # isolate: no tip_green forgiveness in play
    ledger.config.policy["push"] = push


def _publish(tmp_path, upto):
    """A real bare remote with `upto` on origin/main, so the ancestry is genuine."""
    bare = tmp_path.parent / (tmp_path.name + "-origin.git")
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=tmp_path,
                   check=True, capture_output=True)
    subprocess.run(["git", "push", "-q", "origin", upto + ":refs/heads/main"], cwd=tmp_path,
                   check=True, capture_output=True)
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=tmp_path, check=True, capture_output=True)
    return bare


def _check(ledger, tmp_path, rng, records, admission=(STEP,)):
    return canpush_mod.check(records=list(records), config=ledger.config, repo=str(tmp_path),
                             rev_range=rng, admission=list(admission),
                             commit_admission=list(admission))


def test_a_commit_already_on_the_remote_stops_blocking(ledger, tmp_path):
    """⭐⭐ THE HEADLINE. An unjudged intermediate already reachable from origin/main is not this
    push's publication event, so it stops blocking — reported as its OWN category rather than as
    a defect the tip fixed."""
    base, shas = _repo(tmp_path, n=3)
    mid, tip = shas[0], shas[-1]
    _publish(tmp_path, mid)               # mid and everything under it is PUBLISHED
    _enable(ledger)

    records = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)]   # only the tip is judged
    result = _check(ledger, tmp_path, base + ".." + tip, records)

    pub = {e["commit"] for e in result["published_already"]}
    assert mid in pub, (
        "a commit already on origin/main still blocked: " + repr(result["published_already"]))
    assert result["inherited_published"]["checked"] is True
    assert result["inherited_published"]["verified_against"] == "ls-remote"
    # ⛔ and it must NOT be laundered through `forgiven`, which means something else entirely
    assert all(e["commit"] != mid for e in (result.get("forgiven") or [])), (
        "an inherited commit was reported as a defect the tip fixed")
    text = canpush_mod.render(result)
    assert "ALREADY PUBLISHED" in text and "PROVENANCE, NOT CHURN" in text, (
        "a forgiveness that does not say why is a gate stepped around silently")


def test_a_locally_authored_unjudged_commit_still_blocks(ledger, tmp_path):
    """⛔⛔ THE CONTROL, AND THE WHOLE REASON THIS IS NOT THE STALE FORGIVENESS. A commit authored
    here, never judged, is not published anywhere and must still block. Without this the test
    above cannot distinguish provenance from churn."""
    base, shas = _repo(tmp_path, n=3)
    mid, tip = shas[0], shas[-1]
    _publish(tmp_path, base)              # only the BASE is published; mid is ours
    _enable(ledger)

    records = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)]
    result = _check(ledger, tmp_path, base + ".." + tip, records)

    pub = {e["commit"] for e in result["published_already"]}
    assert mid not in pub, "a locally authored, unpublished commit was forgiven"
    assert result["allowed"] is False, "the range was allowed despite an unjudged local commit"


def test_the_tip_is_never_forgiven_this_way(ledger, tmp_path):
    """⚠ THE TIP IS WHAT THIS PUSH PUBLISHES. If it were already on the remote there would be
    nothing to push, so it must never appear here however its ancestry reads."""
    base, shas = _repo(tmp_path, n=2)
    tip = shas[-1]
    _publish(tmp_path, tip)               # everything, tip included, is on origin/main
    _enable(ledger)

    result = _check(ledger, tmp_path, base + ".." + tip, [])
    assert all(e["commit"] != tip for e in result["published_already"]), (
        "the TIP was forgiven as already-published — it is what the push publishes")


def test_it_is_off_unless_policy_says_otherwise(ledger, tmp_path):
    """⚠ A FORGIVENESS THAT ARRIVES SWITCHED ON IS A GATE THAT QUIETLY WIDENED. Default false,
    and the payload says WHY it did not apply rather than returning an empty list that reads as
    "nothing qualified"."""
    base, shas = _repo(tmp_path, n=3)
    mid, tip = shas[0], shas[-1]
    _publish(tmp_path, mid)
    _enable(ledger, on=None)          # ABSENT, not explicit False — see `_enable`

    result = _check(ledger, tmp_path, base + ".." + tip,
                    [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)])

    assert result["published_already"] == []
    assert result["inherited_published"]["checked"] is False
    assert "not set" in result["inherited_published"]["why"], (
        "an empty list with no reason reads as 'none qualified', a different fact")
    assert result["allowed"] is False, "the default must not forgive anything"


def test_an_unreachable_remote_forgives_nothing(ledger, tmp_path, monkeypatch):
    """⛔⛔ THE TRACKING REF IS A CACHE AND IS VERIFIED, NOT TRUSTED. `origin/main` moves only on
    `fetch`, so a stale one could claim a commit is published when it had been force-removed
    remotely. If the remote cannot be reached to check, NOTHING is forgiven — and the reason is
    stated, because "could not check" and "nothing qualified" are different facts."""
    base, shas = _repo(tmp_path, n=3)
    mid, tip = shas[0], shas[-1]
    _publish(tmp_path, mid)
    _enable(ledger)

    real = canpush_mod._git

    def no_ls_remote(repo, *args):
        if args and args[0] == "ls-remote":
            raise ValueError("network unreachable")
        return real(repo, *args)
    monkeypatch.setattr(canpush_mod, "_git", no_ls_remote)

    result = _check(ledger, tmp_path, base + ".." + tip,
                    [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)])

    assert result["published_already"] == [], "forgave on an unverifiable cache"
    assert result["inherited_published"]["checked"] is False
    assert "could not reach the remote" in result["inherited_published"]["why"]
    assert result["allowed"] is False


def test_a_stale_but_reachable_tracking_cache_forgives_nothing(ledger, tmp_path):
    """⛔⛔ THE GAP MY OWN MUTATION RUN FOUND. `test_an_unreachable_remote_forgives_nothing`
    makes `ls-remote` RAISE, so it returns before the staleness comparison is ever reached —
    which meant neutering that comparison failed no test at all. The dangerous case is not an
    unreachable remote; it is a remote that answers and DISAGREES with the local cache.

    ⚠⚠ That is the case a force-push creates: the tracking ref still names a commit the remote
    no longer has, so "already published" would be asserted about bytes that were withdrawn.
    Verified by moving the remote branch under the cache without fetching.
    """
    base, shas = _repo(tmp_path, n=3)
    mid, tip = shas[0], shas[-1]
    bare = _publish(tmp_path, mid)
    _enable(ledger)

    # the remote moves; the local tracking ref is NOT refetched, so the cache is now stale
    subprocess.run(["git", "push", "-q", "--force", str(bare), base + ":refs/heads/main"],
                   cwd=tmp_path, check=True, capture_output=True)

    result = _check(ledger, tmp_path, base + ".." + tip,
                   [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)])

    assert result["published_already"] == [], (
        "forgave on a tracking ref the remote no longer agrees with")
    assert result["inherited_published"]["checked"] is False
    assert "disagree with the remote" in result["inherited_published"]["why"]
    assert result["allowed"] is False
