"""`requirements(action)` — the success conditions, served from the config that gates.

⭐⭐ Tim, 2026-08-30: *"a specific endpoint to call that documents the exact success conditions
... so whenever a chronic mistake like that is made it will have the 'this is what you need to
do to fix it' directly in front at the right moment."*

⚠⚠ THE CHRONIC MISTAKE, MEASURED THE SAME DAY. gitRobot served its admission set NOWHERE, so a
caller asking "what gates a push?" could only reach verdictLedger's `requirements()` — the type
REGISTRY, which is a different list. Both are 20 entries for `push`; 19 are shared; the ledger
marks `rely` required and gitRobot admits `build` instead. **Same count, different members**, so
comparing sizes says they agree. ZeroParadox followed the documented contract and reported `rely`
to its user as blocking a push it does not gate.
"""

import pytest

from core import ledger as ledger_client


def test_it_serves_the_set_the_gate_actually_reads(robot):
    """⭐⭐ THE HEADLINE. The admitted list must be the SAME OBJECT the push path consults —
    not a copy, not a description of one."""
    out = robot.requirements("push")
    assert out["admitted"] == sorted(ledger_client.admission_for("push"))
    assert out["admitted_count"] == len(out["admitted"])
    assert "admission.v1.json" in out["source"]


def test_registered_is_not_admitted_and_it_says_so(robot):
    """⚠⚠ THE DISTINCTION THE MISTAKE TURNED ON. Registered means RECORDABLE; admitted means
    REQUIRED. A caller who conflates them chases a gate that was deliberately excluded."""
    out = robot.requirements("push")
    assert "registered_not_admitted" in out
    note = out["_registered_vs_admitted"]
    assert "RECORDED" in note and "GREEN" in note
    assert "does NOT block" in note


def test_the_exclusion_rationale_is_quoted_not_paraphrased(robot):
    """⚠ The reasons come out of `admission.v1.json`'s own `_`-prefixed keys. A paraphrase
    here would be a second explanation that drifts from the exclusion it explains."""
    out = robot.requirements("push")
    assert out["exclusion_rationale"], "no rationale surfaced"
    assert all(k.startswith("_") for k in out["exclusion_rationale"])


def test_it_states_the_order_and_puts_blocked_before_auto(robot):
    """⚠⚠ ORDER IS PART OF THE SUCCESS CONDITION, and getting it wrong wastes the work.
    Recording `auto` before fixing `blocked` buys verdicts against content about to change —
    they die on the next commit. ZeroParadox caught this in a sequence I had written backwards."""
    steps = " ".join(robot.requirements("push")["order_of_operations"]).lower()
    assert steps.index("blocked") < steps.index("auto"), "fix-before-rerun order lost"


def test_it_names_which_tool_answers_which_question(robot):
    """⚠ Tim, 2026-08-29: "we also keep having issues with which indicators to use." Five
    numbers with no stated priority is how a reader picks the flattering one — so the mapping
    is served, not written in a document nobody is obliged to open."""
    which = robot.requirements("push")["which_tool_answers_what"]
    joined = " ".join(which.values())
    for tool in ("heal_plan", "can_push", "inventory", "progress"):
        assert tool in joined


def test_an_unknown_action_refuses_rather_than_reporting_nothing(robot):
    """⚠ An unnamed action must never read as unrestricted — the same rule `admission_for`
    enforces. Reporting "0 admitted" for a typo is an unchecked action with a receipt."""
    with pytest.raises(Exception):
        robot.requirements("shove")


def test_it_actually_names_the_excluded_types(robot):
    """⚠⚠ THE TEST THAT WAS MISSING, AND ITS ABSENCE HID A FAIL-OPEN. The first version called
    a ledger function that does not exist and swallowed the AttributeError, so
    `registered_not_admitted` returned `[]` — reading as "nothing is excluded" when it meant
    "I could not look". Every other test passed: none asserted the list was NON-EMPTY.

    That is the whole failure this tool exists to prevent, committed inside the tool. `rely` is
    the type the confusion turned on, so it is named explicitly — asserting merely "non-empty"
    would pass on a list that happened to contain something else."""
    out = robot.requirements("push")
    assert out["registry_unreadable"] is None, out["registry_unreadable"]
    assert "rely" in out["registered_not_admitted"]


def test_an_unreadable_registry_is_reported_not_rendered_as_empty(robot, monkeypatch):
    """⚠⚠ AN EMPTY EXCLUSION LIST AND AN UNREADABLE REGISTRY MUST NOT LOOK THE SAME. `[]` with
    no error means "everything registered is admitted"; `[]` with an error means the answer is
    unknown. Collapsing them is how the original defect read as a clean result."""
    from core import ledger as lc

    def boom(tool, arguments):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(lc, "call", boom)
    out = robot.requirements("push")
    assert out["registered_not_admitted"] == []
    assert "ledger down" in out["registry_unreadable"]
