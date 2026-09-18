"""A refused claim must BLOCK the push, and must stop blocking when the emitter is fixed.

⛔⛔ THE FAIL-OPEN, reported by ZeroParadox 2026-09-18 and reproduced from the live stream. Two
`editorial` rounds ran at basis `0dd7fa79444e` over DISJOINT file sets. V11 refused the second
because the (step, basis, revision) slot was taken — and the ledger went on reporting `editorial`
**PASS at that basis, having examined none of the five files where three BEDROCK findings lived.**
The refusal sat in the sidecar the entire time; the push path could not see it.

⚠⚠ THE SIDECAR AND THE `REFUSED` ROW BOTH ALREADY EXISTED. What was missing was the precondition
`_sync_can_push` had written down since 2026-09-13 and nobody had built: *"nothing ever clears
it... Clear entries on a later accepted record first, then pass it."* A refusal that never ends
cannot be allowed to block, so it was not consulted, so it protected nothing.

⭐ Tim's ruling, 2026-09-18: build the clearing, then wire it in — rather than change record
identity so the second record could land, which `inputs` chains and the consumer's defect ledger
both cite.
"""

import pytest

from conftest import good


def test_an_accepted_record_retires_the_steps_refusal(ledger):
    """⭐⭐ THE PRECONDITION. Without an END, a blocking refusal is a permanent wedge."""
    ledger.store.record_refusal("check_invariants", "V11", "2026-09-18T00:00:00+00:00")
    assert "check_invariants" in ledger.store.refusals()

    assert ledger.append(good())["appended"] is True

    assert "check_invariants" not in ledger.store.refusals(), (
        "an accepted record did not retire the step's refusal — wiring this into the push path "
        "would block that step forever")


def test_a_refusal_for_another_step_is_untouched(ledger):
    """⚠ Keyed on STEP, and only that step. An accepted record is evidence about the emitter
    that produced it and about nothing else."""
    ledger.store.record_refusal("adversary", "V11", "2026-09-18T00:00:00+00:00")

    assert ledger.append(good())["appended"] is True

    assert "adversary" in ledger.store.refusals(), "clearing leaked past the step that recorded"


def test_a_REFUSED_row_establishes_nothing_and_is_not_a_FAIL(ledger, tmp_path):
    """⛔ A REFUSED row condemns NOTHING — it is a defect in the RECORD, not a finding about the
    corpus. Reading it as a FAIL would stamp condemnation on blobs the ledger never judged.

    ⚠ AND ITS REMEDY MUST NOT BE "RE-RUN THE GATE": the gate DID run, the ledger declined its
    record, and re-running reproduces the refusal.
    """
    from core import inventory as inventory_mod
    cfg = ledger.config
    refusals = {"check_invariants": {"rule": "V11", "count": 2,
                                     "first_seen": "2026-09-18T00:00:00+00:00",
                                     "last_seen": "2026-09-18T01:00:00+00:00"}}
    inv = inventory_mod.build(config=cfg, records=[], action="commit",
                              files={"docs/x.md": "b" * 40}, ref="a" * 40,
                              admission=["check_invariants"], refusals=refusals, changed=None)
    row = [r for r in inv["rows"] if r["step"] == "check_invariants"][0]

    assert row["status"] == "REFUSED"
    assert not row.get("indicted"), "a REFUSED row must condemn nothing"
    assert "do not simply re-run" in row["why"].lower() or "do not" in row["why"].lower()
    assert inv["complete"] is False, "a refused claim must not read as a satisfied step"


def test_the_push_path_consults_the_sidecar_at_all(ledger):
    """⛔⛔ THE WIRING ITSELF, and the reason this test exists as its own case: every mechanism
    above was already built and correct on 2026-09-13, and the fail-open persisted for five days
    purely because `can_push` did not pass `refusals`. **A control that exists and is not
    consulted is indistinguishable from one that was never written.**
    """
    import inspect
    from ledger_server import server

    src = inspect.getsource(server._sync_can_push)
    assert "refusals=" in src, (
        "can_push does not pass the refusal sidecar — the REFUSED row can never appear on the "
        "one path that decides whether bytes reach the world")
