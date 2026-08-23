"""THE HARD CONTRACT: push refuses unless the ledger says the admission set is green.

⚠⚠ THIS FILE EXISTS BECAUSE OF A MEASURED FAILURE. On 2026-08-23 a push of
`55f2d6a` was ALLOWED — 19 blocking checks green, preflight passed, audited,
pushed — while `verdictLedger`'s inventory for that exact hash reported
`0/19 keys, complete: false`. Two systems, opposite answers, and the enforcement
point never asked. Every control here is one half of making that unrepeatable.

The load-bearing distinction throughout: the REGISTRY says what may be RECORDED,
the ADMISSION SET says what must PASS. They are two different facts, not two
copies of one, and conflating them forces a correct implementation to block every
push until every registered type has an emitter.
"""

import json

import pytest

from core import ledger as ledger_client
from core.errors import GitRobotError, RefusalError


def _msg(tmp_path, text="m\n"):
    p = tmp_path / "msg.txt"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _commit(robot, repo, tmp_path, name="a.txt"):
    (repo / name).write_text(name, encoding="utf-8")
    robot.stage([name])
    robot.commit(_msg(tmp_path))


# -- ⭐ THE HEADLINE REGRESSION -----------------------------------------------

def test_push_refuses_when_the_inventory_is_incomplete(robot, repo, tmp_path,
                                                       fake_gate, ledger_refuses):
    """⭐ THIS CONTROL FAILING IS THE EXACT EVENT OF 2026-08-23."""
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    robot.preflight(wait=True)                     # preflight PASSES

    with pytest.raises(RefusalError) as exc:
        robot.push("illustrated", reason="shipping")

    assert "admission set is not satisfied" in str(exc.value)
    # ⚠ The refusal prints the ROWS, not a count — the remedies differ by an order
    # of magnitude in cost and summarising throws that away.
    assert "MISSING  mechanical  build, check_prose" in str(exc.value)
    assert "no flag that skips it" in exc.value.alternative
    # and nothing reached the remote
    assert robot.read("log", ["origin/illustrated", "--oneline"])["output"].count("\n") == 0


def test_a_passing_preflight_is_not_enough(robot, repo, tmp_path, fake_gate,
                                           ledger_refuses):
    """⭐ Guards against the enforcement point drifting back to preflight, which is
    where it was when it failed."""
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    assert robot.preflight(wait=True)["passed"] is True
    with pytest.raises(RefusalError, match="admission set is not satisfied"):
        robot.push("illustrated", reason="shipping")


def test_the_refusal_is_audited_like_any_other(robot, repo, tmp_path, fake_gate,
                                               ledger_refuses):
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    robot.preflight(wait=True)
    with pytest.raises(RefusalError):
        robot.push("illustrated", reason="shipping")
    record = robot.audit.read()[-1]
    assert record["op"] == "push" and record["decision"] == "refused"
    assert "admission set" in record["detail"]


# -- ⭐ AN EMPTY ADMISSION SET REFUSES ----------------------------------------

def test_an_empty_admission_set_refuses_rather_than_warning(robot, repo, tmp_path,
                                                            fake_gate, ledger_empty):
    """⭐⭐ THE SECOND HALF OF THE 2026-08-23 FAILURE, and the subtler half.

    Tim: "It should have been impossible to push without having the preset of
    requirements from verdictLedger created." An EMPTY admission set is that preset
    not existing. The first build of this gate rendered it as ALLOWED with a loud
    capitalised warning — which is fail-OPEN in the costume of fail-closed, because
    a warning nobody is obliged to act on gates nothing at all.
    """
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    with pytest.raises(RefusalError) as exc:
        robot.push("illustrated", reason="shipping")

    assert "NOTHING GATES THIS PUSH" in str(exc.value)
    # ⚠ It must name the way OUT, or the only discoverable fix is to delete the gate.
    assert "config/admission.v1.json" in exc.value.alternative
    assert "build" in exc.value.alternative          # a type available to promote
    remote = robot.read("log", ["origin/illustrated", "--oneline"])["output"]
    assert len(remote.splitlines()) == 1        # still only the initial commit


def test_the_empty_refusal_distinguishes_empty_from_unsatisfied(robot, repo, tmp_path,
                                                                fake_gate, ledger_empty):
    """"Nothing was required" and "requirements failed" have different remedies —
    promote a type vs. fix the code. Reporting one as the other sends the reader to
    the wrong system."""
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    with pytest.raises(RefusalError) as exc:
        robot.push("illustrated", reason="shipping")
    assert "admission set is not satisfied" not in str(exc.value)


def test_status_names_the_empty_set_as_a_blocker(robot, ledger_empty):
    """⚠ A status that says "clear" over a push that refuses is worse than no status."""
    blockers = robot.status()["would_block_push"]
    assert any("nothing gates a push" in b for b in blockers)


# -- the inventory is consulted at PUSH, over the pushed hash, every time -----

def test_the_inventory_is_asked_for_the_current_head(robot, repo, tmp_path,
                                                     fake_gate, monkeypatch):
    """⚠ preflight validates the TREE; only push knows what is being published.
    Measured: preflight logged `scope 0 ref(s)` while the push logged `scope 1`."""
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    robot.preflight(wait=True)

    seen = []

    def spy(ref, action, admission=None):
        seen.append((ref, action))
        return {"ok": True, "complete": True, "ref": ref, "action": action,
                "admitted": ["build"], "admission_state": "SET", "policy_sha": "p",
                "required": 1, "satisfied": 1, "line": "ALLOWED"}

    monkeypatch.setattr(ledger_client, "inventory", spy)
    robot.push("illustrated", reason="shipping")

    assert len(seen) == 1
    assert seen[0] == (robot.git.head(), "push")


def test_the_hash_specificity_control(robot, repo, tmp_path, fake_gate, monkeypatch):
    """⭐ Satisfy every key for hash A, commit again to reach B, assert push refuses
    at B. Proves the keys bind to the HASH, not to the session."""
    fake_gate(0)
    _commit(robot, repo, tmp_path, "a.txt")
    good_hash = robot.git.head()

    def only_a(ref, action, admission=None):
        ok = ref == good_hash
        return {"ok": True, "complete": ok, "ref": ref, "action": action,
                "admitted": ["build"], "admission_state": "SET", "policy_sha": "p",
                "required": 1, "satisfied": 1 if ok else 0,
                "line": ("ALLOWED" if ok else "REFUSED  push  0/1 admission keys")}

    monkeypatch.setattr(ledger_client, "inventory", only_a)
    robot.preflight(wait=True)
    robot.push("illustrated", reason="hash A is satisfied")

    _commit(robot, repo, tmp_path, "b.txt")           # now at hash B
    robot.preflight(wait=True)
    with pytest.raises(RefusalError, match="admission set is not satisfied"):
        robot.push("illustrated", reason="hash B is not")


# -- ⭐ FAIL CLOSED WHEN THE LEDGER IS DOWN, WITH ITS OWN ERROR TYPE ----------

def test_a_down_ledger_refuses_with_its_own_error_type(robot, repo, tmp_path,
                                                       fake_gate, ledger_down):
    """⚠ Distinguishable from a policy refusal, or somebody debugs the wrong thing
    at 2am."""
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    robot.preflight(wait=True)
    with pytest.raises(ledger_client.LedgerUnreachable) as exc:
        robot.push("illustrated", reason="shipping")
    assert exc.value.error_type == "ledger_unreachable"
    assert robot.read("log", ["origin/illustrated", "--oneline"])["output"].count("\n") == 0


def test_the_real_client_names_the_no_fallback_rule(monkeypatch):
    """The wording matters: a caller told only "unreachable" may go looking for a
    way around. Tested against the REAL client on a dead port, not a fixture."""
    monkeypatch.setattr(ledger_client, "URL", "http://127.0.0.1:59999/mcp")
    monkeypatch.setattr(ledger_client, "TIMEOUT", 2.0)
    with pytest.raises(ledger_client.LedgerUnreachable) as exc:
        ledger_client.call("inventory", {"action": "push", "ref": "HEAD"})
    assert "two-route design returning through the back door" in str(exc.value)
    assert exc.value.error_type == "ledger_unreachable"


def test_a_down_ledger_never_falls_back_to_the_exit_code_path(robot, repo, tmp_path,
                                                              fake_gate, ledger_down):
    """⭐ THE NO-FALLBACK CONTROL — the regression most likely to be reintroduced by
    someone "restoring compatibility". A green preflight must not rescue a push."""
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    assert robot.preflight(wait=True)["passed"] is True   # the old route says yes
    with pytest.raises(ledger_client.LedgerUnreachable):
        robot.push("illustrated", reason="shipping")
    assert robot.read("log", ["origin/illustrated", "--oneline"])["output"].count("\n") == 0


# -- ⭐ TWO LISTS, NOT TWO COPIES ---------------------------------------------

def test_registering_a_type_does_not_gate_a_push(tmp_path):
    """⭐ THE 20-EXPERIMENTAL-GATES CASE. Registering is free; gating is a
    deliberate promotion."""
    cfg = tmp_path / "admission.v1.json"
    cfg.write_text(json.dumps({"schema": "zp.admission.v1",
                               "default": "NOT_ADMITTING",
                               "admission": {"commit": [], "push": [], "tag": []}}),
                   encoding="utf-8")
    assert ledger_client.admission_for("push", cfg) == []


def test_promotion_binds_immediately(tmp_path):
    cfg = tmp_path / "admission.v1.json"
    cfg.write_text(json.dumps({"schema": "zp.admission.v1",
                               "default": "NOT_ADMITTING",
                               "admission": {"commit": [], "push": ["build"], "tag": []}}),
                   encoding="utf-8")
    assert ledger_client.admission_for("push", cfg) == ["build"]
    assert ledger_client.admission_for("commit", cfg) == []


def test_a_missing_admission_set_refuses_rather_than_assuming_empty(robot, repo,
                                                                    tmp_path, fake_gate,
                                                                    monkeypatch):
    """⚠ An ABSENT list is not an EMPTY one. Treating "nobody said" as "nothing
    required" is the fail-open shape this whole system exists to end."""
    monkeypatch.setenv("GITROBOT_ADMISSION", str(tmp_path / "nope.json"))
    with pytest.raises(GitRobotError, match="admission set not found"):
        ledger_client.admission_for("push")


def test_an_unnamed_action_refuses(tmp_path):
    cfg = tmp_path / "admission.v1.json"
    cfg.write_text(json.dumps({"schema": "zp.admission.v1",
                               "default": "NOT_ADMITTING",
                               "admission": {"commit": []}}), encoding="utf-8")
    with pytest.raises(GitRobotError, match="names no entry for action"):
        ledger_client.admission_for("push", cfg)


# -- the join is recorded, so a moved bar cannot reinterpret a past action ----

def test_an_allowed_push_records_the_inventory_that_authorised_it(robot, repo, tmp_path,
                                                                  fake_gate, ledger_ok):
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    robot.preflight(wait=True)
    robot.push("illustrated", reason="shipping")

    record = robot.audit.read()[-1]
    assert record["decision"] == "allowed"
    assert record["args"]["inventory_ref"] == robot.git.head()
    assert record["args"]["policy_sha"] == "policy-sha"


def test_the_nested_repo_is_not_gated_by_the_ledger(robot, nested_local, tmp_path,
                                                    ledger_down):
    """`.claude-local` has no gate pipeline and no verdicts; demanding an inventory
    there would make its push permanently unreachable rather than safe."""
    (nested_local / "notes.md").write_text("x", encoding="utf-8")
    robot.stage(["-A"], repo_mode=".claude-local")
    msg = tmp_path / "m.txt"
    msg.write_text("note\n", encoding="utf-8")
    robot.commit(str(msg), repo_mode=".claude-local")
    out = robot.push("master", reason="back up notes", repo_mode=".claude-local")
    assert out["decision"] == "allowed"
