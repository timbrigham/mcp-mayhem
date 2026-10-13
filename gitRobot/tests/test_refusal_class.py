"""Every refused audit row says why, from a closed, published set, set where the refusal happens.

Added 2026-10-09. Two text-based classifications of the same 177 historical refusals disagreed (44
patterns against 62), so the reason is now recorded by the code that refuses rather than recovered
from the message afterwards.
"""

import ast
from pathlib import Path

import pytest

from core.audit import AuditLog
from core.errors import RefusalError
from mcpcommon.vocabulary import REFUSAL_CLASSES, VOCABULARIES

ENGINE = Path(__file__).resolve().parents[1] / "core" / "engine.py"


def _last(robot):
    return robot.audit.read()[-1]


def test_the_closed_set_is_published():
    assert set(REFUSAL_CLASSES) == {"policy", "gate", "operational", "allowlist"}
    assert VOCABULARIES["refusal_class"] is REFUSAL_CLASSES
    assert all(REFUSAL_CLASSES[k].strip() for k in REFUSAL_CLASSES), "every value needs a meaning"


def test_policy(robot, dirty):
    with pytest.raises(RefusalError):
        robot.read("reset", ["--hard"])
    assert _last(robot)["refusal_class"] == "policy"


def test_allowlist(robot):
    with pytest.raises(RefusalError):
        robot.read("update-ref", ["refs/heads/x", "HEAD"])
    assert _last(robot)["refusal_class"] == "allowlist"


def test_operational(robot, tmp_path):
    msg = tmp_path / "m.txt"
    msg.write_text("m\n", encoding="utf-8")
    with pytest.raises(RefusalError, match="nothing is staged"):
        robot.commit(str(msg))
    assert _last(robot)["refusal_class"] == "operational"


def test_gate(robot, repo, tmp_path, fake_gate):
    fake_gate(1)
    (repo / "new.txt").write_text("x\n", encoding="utf-8")
    robot.stage(["new.txt"])
    msg = tmp_path / "m.txt"
    msg.write_text("m\n", encoding="utf-8")
    with pytest.raises(RefusalError, match="gate did not pass"):
        robot.commit(str(msg))
    assert _last(robot)["refusal_class"] == "gate"


def test_a_non_refused_row_carries_null(robot, dirty):
    robot.stage(["tracked.txt"])
    row = _last(robot)
    assert row["decision"] == "allowed" and "refusal_class" in row and row["refusal_class"] is None


@pytest.mark.parametrize("decision,cls", [("refused", None), ("refused", "because"),
                                          ("allowed", "policy")])
def test_the_writer_rejects_an_unclassified_or_misplaced_class(tmp_path, decision, cls):
    log = AuditLog(tmp_path / "a.jsonl")
    with pytest.raises(AssertionError):
        log.append(actor="t", op="x", args={}, decision=decision, refusal_class=cls)
    assert not (tmp_path / "a.jsonl").exists(), "nothing may be written when the check fails"


# How many refusals of each class every function raises. Pinned so that moving a refusal to a
# different class is a deliberate, reviewed diff rather than a silent edit; the future metric
# counts these, so a quiet reclassification would change its numbers without anyone noticing.
EXPECTED_CLASSES = {
    "_commit_body:gate": 1, "_merge_body:gate": 1, "_merge_body:operational": 4,
    "_recover_interrupted_merge:operational": 2, "_require_clean:operational": 1,
    "_require_current_freeze:gate": 2, "_require_inventory:gate": 3,
    "_require_inventory:operational": 1, "_target:operational": 1, "_target:policy": 1,
    "attest:gate": 1, "branch_delete:operational": 1, "branch_delete:policy": 1,
    "commit:gate": 1, "commit:operational": 1, "guard_tier1:policy": 1,
    "merge:operational": 1, "preflight:operational": 2, "pull_request:operational": 1,
    "pull_request:policy": 2, "push:operational": 3, "push:policy": 2,
    "read:allowlist": 1, "read:policy": 1, "rebase:policy": 1, "remove_files:policy": 2,
    "squash:operational": 2, "squash:policy": 1, "stage:policy": 2, "unstage:policy": 1,
    "worktree:operational": 1, "worktree:policy": 3,
}


def _tree():
    return ast.parse(ENGINE.read_text(encoding="utf-8"))


def _values(expr, fn=None, depth=0):
    """The string values an expression can take: a literal, a conditional of literals, or a local
    variable whose every assignment in `fn` is one of those. None when it cannot be resolved."""
    if isinstance(expr, ast.Constant) and (isinstance(expr.value, str) or expr.value is None):
        return [expr.value]          # None: the not-refused branch of a conditional class
    if isinstance(expr, ast.IfExp):
        a, b = _values(expr.body, fn, depth), _values(expr.orelse, fn, depth)
        return None if a is None or b is None else a + b
    if isinstance(expr, ast.Name) and fn is not None and depth < 3:
        out = []
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and any(
                    isinstance(tg, ast.Name) and tg.id == expr.id for tg in node.targets):
                v = _values(node.value, fn, depth + 1)
                if v is None:
                    return None
                out += v
        return out or None
    return None


def _calls():
    """(function, call) for every call in the engine, skipping the two forwarding mechanisms:
    `_refuse` and `_receipt` pass their caller's values through, and their callers are checked."""
    tree = _tree()
    forwarding = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name in ("_refuse", "_receipt"):
            forwarding |= {id(x) for x in ast.walk(n)}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if (id(node) not in forwarding and isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)):
                yield fn, node


def _refusal_sites():
    """(function name, line, refusal_class expression) for every refusal the engine can write."""
    seen = set()
    for fn, node in _calls():
        kw = {k.arg: k.value for k in node.keywords}
        is_refusal = node.func.attr == "_refuse" or (
            node.func.attr == "append" and "decision" in kw
            and "refused" in (_values(kw["decision"], fn) or ["refused"]))
        if is_refusal and id(node) not in seen:
            seen.add(id(node))
            yield fn.name, node.lineno, kw.get("refusal_class")


def test_every_refusal_site_names_a_class_from_the_set():
    sites = list(_refusal_sites())
    assert len(sites) >= 46, "fewer refusal sites than classified; the scan broke"
    for name, line, value in sites:
        assert value is not None, f"engine.py:{line} ({name}) refuses without a refusal_class"
        values = [v for v in (_values(value) or []) if v is not None]
        assert values and set(values) <= set(REFUSAL_CLASSES), (line, ast.unparse(value))


def test_the_class_table_is_pinned():
    import collections
    got = collections.Counter()
    for name, _line, value in _refusal_sites():
        for v in sorted(set(_values(value) or []) - {None}):
            got[f"{name}:{v}"] += 1
    assert dict(got) == EXPECTED_CLASSES


def test_no_computed_decision_can_become_an_unclassified_refusal():
    """A decision computed at runtime must resolve statically to known values; if 'refused' is
    one of them, the call must carry a refusal_class. Otherwise AuditLog.append would raise in
    place of the refusal, after whatever the operation already did."""
    checked = 0
    for fn, node in _calls():
        if node.func.attr not in ("append", "_receipt"):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        dec = kw.get("decision")
        if dec is None and node.func.attr == "_receipt" and len(node.args) > 2:
            dec = node.args[2]
        if dec is None:
            continue
        checked += 1
        values = _values(dec, fn)
        assert values is not None, f"engine.py:{node.lineno} ({fn.name}): decision not resolvable"
        if "refused" in values:
            assert "refusal_class" in kw, f"engine.py:{node.lineno} can refuse without a class"
    assert checked >= 20, "the decision scan found too few writers; it broke"


def test_push_refspec_syntax_is_policy_but_a_missing_branch_is_operational(robot):
    with pytest.raises(RefusalError):
        robot.push("+illustrated", reason="r")
    assert _last(robot)["refusal_class"] == "policy"
    with pytest.raises(RefusalError):
        robot.push("no-such-branch", reason="r")
    assert _last(robot)["refusal_class"] == "operational"


def test_a_missing_reason_is_operational(robot):
    with pytest.raises(RefusalError):
        robot.push("illustrated", reason=None)
    assert _last(robot)["refusal_class"] == "operational"


def test_a_foreign_existing_path_is_policy_but_a_vanished_one_is_operational(robot, tmp_path):
    foreign = tmp_path / "somewhere-else"
    foreign.mkdir()
    with pytest.raises(RefusalError):
        robot.read("status", worktree=str(foreign))
    assert _last(robot)["refusal_class"] == "policy"
    with pytest.raises(RefusalError):
        robot.read("status", worktree=str(tmp_path / "reaped-long-ago"))
    assert _last(robot)["refusal_class"] == "operational"
