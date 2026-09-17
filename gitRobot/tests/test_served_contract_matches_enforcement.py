"""The SERVED description must name the gate the server actually enforces.

⛔⛔ MEASURED 2026-09-16. `push`'s MCP description read "On the main repo: requires a passing
preflight() for the CURRENT HEAD", and `preflight`'s read "Run this BEFORE push — push refuses
without it". Neither has been true since the preflight bit was deleted: engine.py says "THERE IS
NO PREFLIGHT PRECONDITION, AND ITS REMOVAL IS THE POINT", and the only precondition is the
verdictLedger inventory for the exact HEAD.

⚠ ZeroParadox reported it, and the cost is the point: the docstring is the ONLY surface a caller
can read, so they had let a push run believing a passing preflight receipt was discharging a
stated requirement. Right answer, wrong reason — the server does not implement that requirement.

⛔ WORSE, IT TAUGHT THE FAILURE THE SERVER REMOVED: "a passing preflight makes a push safe" is
exactly the belief falsified on 2026-08-23, when the bit said pass while the ledger said 0/19.

So this file pins BEHAVIOUR first — a push with no preflight at all is allowed when the ledger
allows it — and then pins the served text against the behaviour.
"""

import json

import pytest

from core import ledger as ledger_client
from core.errors import RefusalError
from gitrobot_server import server as srv


def _allow(monkeypatch, robot):
    monkeypatch.setattr(ledger_client, "can_push", lambda *a, **k: {
        "ok": True, "allowed": True, "range": "origin/illustrated..illustrated",
        "commits_in_range": 1, "blocking_count": 0, "tip": robot.git.head(),
        "admitted": ["build"], "admission_state": "SET", "not_gating": [],
        "config_sha": "p", "commits": [], "line": "ALLOWED"})


def _refuse(monkeypatch, robot):
    monkeypatch.setattr(ledger_client, "can_push", lambda *a, **k: {
        "ok": True, "allowed": False, "range": "origin/illustrated..illustrated",
        "commits_in_range": 1, "blocking_count": 1, "tip": robot.git.head(),
        "admitted": ["build"], "admission_state": "SET", "not_gating": [],
        "config_sha": "p", "commits": [], "missing": ["build"],
        "line": "REFUSED  push  1/1 commit(s) short"})


def _commit(robot, repo, tmp_path, name="a.txt"):
    (repo / name).write_text(name, encoding="utf-8")
    robot.stage([name])
    msg = tmp_path / "m.txt"
    msg.write_text("m\n", encoding="utf-8")
    robot.commit(str(msg))


def test_a_push_with_no_preflight_is_allowed_when_the_ledger_allows(robot, repo, tmp_path,
                                                                    fake_gate, monkeypatch):
    """⭐ THE BEHAVIOUR THE DESCRIPTION MUST DESCRIBE. No preflight has ever run in this store,
    and the push proceeds — so "requires a passing preflight" was false as served."""
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    _allow(monkeypatch, robot)

    assert robot.preflight_status()["state"] == "none", "fixture assumption: no preflight ran"
    out = robot.push("illustrated", reason="the ledger is the gate", wait=True)

    assert out["decision"] == "allowed"


def test_the_ledger_is_what_refuses_and_it_refuses_synchronously(robot, repo, tmp_path,
                                                                 fake_gate, monkeypatch):
    """⚠ The other half: a refusal comes back from the call the caller made, not from a poll."""
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    _refuse(monkeypatch, robot)

    with pytest.raises(RefusalError) as exc:
        robot.push("illustrated", reason="should refuse", wait=True)
    assert "admission set is not satisfied" in str(exc.value)


def test_the_served_push_description_names_the_ledger_not_preflight():
    """⛔ THE RATCHET. A served contract that names the wrong gate is worse than a thin one: a
    caller cannot read the code, so the description IS the contract."""
    doc = srv.push.__doc__ or ""
    assert "verdictLedger INVENTORY" in doc or "verdictLedger inventory" in doc, (
        "push's description must name the gate it actually enforces")
    for banned in ("requires a passing preflight",
                   "requires a passing preflight() for the CURRENT HEAD"):
        assert banned not in doc, f"push's description still claims: {banned!r}"
    assert "PREVIEW, NOT A PRECONDITION" in doc.upper()


def test_the_served_preflight_description_does_not_claim_to_gate():
    doc = srv.preflight.__doc__ or ""
    assert "push refuses without it" not in doc
    assert "push stays refused until" not in doc
    assert "PRECONDITION" in doc.upper()


def test_push_status_says_a_failed_run_carries_its_reason():
    """The `died` paragraph was excellent and `failed` had nothing, so a caller who hit `failed`
    had no hint that a reason existed. It does, in `output`."""
    doc = srv.push_status.__doc__ or ""
    assert "`failed`" in doc and "output" in doc
    assert "died" in doc


def test_every_gate_claim_in_the_served_surface_is_about_the_ledger():
    """⚠ SWEEP, not a spot check: no tool description may tell a caller that preflight gates a
    push. Same lesson as the routing prefix that was an allowlist — the fix and the claim must
    cover the same set."""
    offenders = []
    for name in dir(srv):
        fn = getattr(srv, name)
        doc = getattr(fn, "__doc__", None)
        if not callable(fn) or not doc:
            continue
        low = doc.lower()
        if "preflight" in low and ("requires a passing preflight" in low
                                   or "push refuses without" in low
                                   or "push stays refused until a run" in low):
            offenders.append(name)
    assert not offenders, f"tool description(s) still claim preflight gates a push: {offenders}"

def test_no_served_description_states_a_fixed_pipeline_duration():
    """⛔ A DURATION IS A MEASUREMENT AND GOES STALE. `push` served "~25 minutes" from 2026-09-03
    to 2026-09-17. The figure was real — one run, 1498s, on 2026-08-30 — promoted to a present-tense
    claim about the pipeline, and by the time a caller quoted it back it was 2.1x the median of the
    47 runs in the audit log (672s). It is the first number anyone reasoning about the re-run reaches
    for, so it must not be served as a constant.

    ⚠ The bar is a served DESCRIPTION, not a code comment: dated history like "took 1498s on
    2026-08-30" is exactly what this project's comment style asks for and stays."""
    import re
    offenders = []
    for name in dir(srv):
        fn = getattr(srv, name)
        doc = getattr(fn, "__doc__", None)
        if not callable(fn) or not doc:
            continue
        for m in re.finditer(r"~\s*\d+\s*(?:min|minute|second|sec)", doc, re.I):
            offenders.append(f"{name}: {m.group(0)!r}")
    assert not offenders, (
        "served description(s) state a fixed pipeline duration; it is a property of the range: %s"
        % offenders)
    assert "median" in (srv.push.__doc__ or ""), (
        "push should give the measured distribution instead, and say to read a receipt")
