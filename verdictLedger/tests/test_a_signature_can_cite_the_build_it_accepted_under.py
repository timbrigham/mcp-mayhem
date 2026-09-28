"""`sign` carries evidence, because without it one axis had no route at all.

⛔⛔ THE UNSATISFIABLE CONJUNCTION, MEASURED 2026-09-27 ACROSS BOTH REPOSITORIES. `evidence_stale`
is computed from the evidence paths a record CITES. `sign` carried none, so **no signature, at any
revision, could ever clear it** — and V13 caps revisions at 5, so even brute force ended in a wall.

⚠⚠ AND THE MECHANICAL ROUTE WAS CLOSED TOO, which is what made this the server's defect rather
than a procedure for the consumer to work around. To cite an approved producer build over an older
commit's subjects, a checker must BE that build while reading those bytes. Their subject fence —
correctly — drops any path differing from that worktree's HEAD:

    substitute the approved build into a worktree  ->  the producer is excluded as "differs"
    check out the old subjects at HEAD             ->  the subjects are excluded as "differs"

Same wall from either side. **Their fence is right**: it exists to stop records claiming bytes
nobody read, measured 2026-08-23 after `ZPLEDGER_BASIS=<older sha>` manufactured keys silently.
Each rule correct alone; the pair closing every route — the shape `inventory.py` already records
paying for on 2026-09-11/12, *"the failure mode a rule cannot detect about itself."*

⭐ THE CONSUMER ASKED BEFORE WRITING A PERMANENT RECORD, and asked the exact right question:
*"does `evidence_stale` even respond to a `signature`-type record at all, given a signature carries
no `evidence` field by design?"* The answer was no. They then tested the mechanical route rather
than assuming, and reported it unreachable. I had said in advance that would make it mine.

⛔ WHAT A SIGNATURE WITH EVIDENCE DOES *NOT* CLAIM, because that was the real objection: it never
asserts an execution. `passes: 1, agreed: 1`, and V3 does not apply to a signature at all.
`evidence` names the PRODUCER BUILD the verdict was accepted under — a checkable fact about a blob.
"""

import pytest

from conftest import good
from core.errors import UsageError, ValidationFailure

STEP = "check_invariants"
BLOB = "c" * 40
MODULE = "tools/verify/check_invariants.py"


def _basis(v="a"):
    return {"kind": "tree", "value": v * 40, "resolved_from": "explicit"}


def _subjects():
    return [{"path": "docs/x.md", "git_blob_id": "b" * 40}]


def test_a_signature_can_carry_evidence(ledger):
    """⭐⭐ THE HEADLINE. Without this the evidence axis had no route from any mechanism."""
    out = ledger.sign(step=STEP, subjects=_subjects(), who="tim",
                      reason="accepting carried debt; producer is the approved build",
                      basis=_basis(),
                      evidence=[{"path": MODULE, "git_blob_id": BLOB}])
    rec = ledger.store.get(out["id"])
    assert rec["decided"]["how"] == "signature"
    assert rec["evidence"] == [{"path": MODULE, "git_blob_id": BLOB}], (
        "the evidence a human cited was dropped, which is the whole defect")


def test_it_stays_optional(ledger):
    """⚠ REQUIRING IT WOULD MAKE EVERY ORDINARY ACCEPT INVENT ONE, and a placeholder attribution
    is worse than an honest absence — the same argument that keeps `who` off a mechanical record.
    An accept that has no producer build to name must stay legal."""
    out = ledger.sign(step=STEP, subjects=_subjects(), who="tim",
                      reason="ordinary accept, no producer claim", basis=_basis("d"))
    assert ledger.store.get(out["id"])["evidence"] == []


def test_a_signature_still_requires_a_human(ledger):
    """⛔ EVIDENCE DOES NOT BUY ITS WAY PAST V5. Adding a field must not weaken the one thing a
    signature is: attributable to a person."""
    with pytest.raises(UsageError):
        ledger.sign(step=STEP, subjects=_subjects(), who="  ", reason="x", basis=_basis("e"),
                    evidence=[{"path": MODULE, "git_blob_id": BLOB}])


def test_evidence_is_shape_checked_like_everywhere_else(ledger):
    """⚠ A NEW DOOR INTO A FIELD MUST NOT BE A LOOSER DOOR. `structural()` requires every evidence
    entry to carry both a path and a blob id; arriving via `sign` changes nothing about that."""
    with pytest.raises(ValidationFailure):
        ledger.sign(step=STEP, subjects=_subjects(), who="tim", reason="x", basis=_basis("f"),
                    evidence=[{"path": MODULE}])          # no git_blob_id


def test_override_does_not_gain_evidence(ledger):
    """⛔⛔ SCOPE CONTROL, AND IT IS A CLAIM ABOUT MEANING RATHER THAN TIDINESS. `sign` is an
    ACCEPT — "you are right, we ship anyway" — so naming the build it was accepted under is
    coherent. `override` is a REGRADE — "the gate erred" — which feeds the opposite signal, and
    `ledger.py` says the two must never share a code path.

    ⚠ If a future ruling extends it, this test is where that decision gets recorded rather than
    inherited from a parameter someone copied across.
    """
    import inspect
    src = inspect.signature(ledger.override)
    assert "evidence" not in src.parameters, (
        "override gained an evidence parameter; that is a separate ruling about what a regrade "
        "claims, not a side effect of fixing the accept path")


def test_the_mcp_tool_exposes_it(ledger):
    """⚠ A CAPABILITY ONLY IN `core` IS A CAPABILITY THE CONSUMER DOES NOT HAVE. They reach this
    server over MCP; the fix is worthless to them if the tool signature does not carry it."""
    import inspect
    from ledger_server import server
    fn = server.sign.fn if hasattr(server.sign, "fn") else server.sign
    params = inspect.signature(fn).parameters
    assert "evidence" in params, (
        "core.sign accepts evidence and the MCP tool does not, so the only caller who needs it "
        "cannot pass it")
    # ⛔⛔ AND IT MUST BE FORWARDED, NOT MERELY ACCEPTED. The first version of this test asserted
    # only that the parameter EXISTS, and a mutant that deleted `evidence=evidence` from the
    # `_guard` call SURVIVED — the tool would have accepted the argument and silently dropped it,
    # which is worse than not offering it: a caller would believe they had cited a build. Fifth
    # proxy-matching assertion of mine caught by mutation this week.
    assert "evidence=evidence" in inspect.getsource(fn), (
        "the MCP tool accepts `evidence` and does not pass it on, so a caller's citation is "
        "silently discarded")
    # ⚠ and it must stay optional on the wire too — a required field here would break every
    # existing sign call the consumer makes
    assert params["evidence"].default is None
