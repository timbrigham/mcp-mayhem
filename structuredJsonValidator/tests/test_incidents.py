"""The incidents register: a separate SJV store, verb-only writes, guard fields all-or-nothing."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from consumers.incidents import build_incident_store, empty_doc, rules
from consumers.incidents.seeds import SEEDS, apply_seeds
from core.errors import IntegrityError, OperationError, ValidationError

ROOT = Path(__file__).resolve().parents[1]
BASE = {"detected_at": "2026-10-13T10:00:00+00:00", "detected_by": "review", "tool": "t",
        "operation": "op", "args": [], "harm": "something broke",
        "pattern_id": "tool.op.shape"}


@pytest.fixture
def store(tmp_path):
    return build_incident_store(tmp_path / "incidents.json", actor="test")


def _violations(store, entries):
    doc = {"schema_version": "1", "collections": {"incidents": {**empty_doc(), "entries": entries}}}
    return store.all_violations(doc)


def _entry(**over):
    e = {"id": "INC-0001", "observed_at": None, "session": None, "status": "open",
         "guard_commit": None, "regression_test": None, "guarded_at": None, "notes": [], **BASE}
    e.update(over)
    return e


def test_add_then_guard_then_annotate(store):
    iid = store.apply("incidents", "add_incident", dict(BASE))["entries_touched"][0]
    assert iid == "INC-0001"
    store.apply("incidents", "set_guarded", {"id": iid, "guard_commit": "a" * 40,
                                             "regression_test": "tests/x.py::t",
                                             "guarded_at": "2026-10-13T11:00:00Z"})
    store.apply("incidents", "annotate", {"id": iid, "text": "n", "at": "2026-10-13T12:00:00Z"})
    inc = store.get("incidents", iid)
    assert inc["status"] == "guarded" and inc["notes"][0]["text"] == "n"
    assert store.validate() == []
    assert store.verify_integrity()                    # the hash-chained audit agrees


def test_a_guarded_entry_without_its_guard_fields_is_rejected(store):
    for missing in rules.GUARD_FIELDS:
        e = _entry(status="guarded", guard_commit="a" * 40, regression_test="t::x",
                   guarded_at="2026-10-13T11:00:00Z")
        e[missing] = None
        v = _violations(store, [e])
        # the text AFTER "missing" names exactly the absent field; the clause before it lists all three
        assert any(x.endswith(f"missing {missing}") for x in v), (missing, v)


def test_an_unguarded_entry_may_not_name_a_guard(store):
    v = _violations(store, [_entry(status="open", guard_commit="a" * 40)])
    assert any("must not name" in x for x in v), v


def test_set_guarded_requires_all_three(store):
    iid = store.apply("incidents", "add_incident", dict(BASE))["entries_touched"][0]
    with pytest.raises(OperationError):
        store.apply("incidents", "set_guarded", {"id": iid, "guard_commit": "a" * 40,
                                                 "regression_test": "", "guarded_at": "2026-10-13T11:00:00Z"})


def test_add_incident_cannot_claim_guarded(store):
    with pytest.raises(OperationError):
        store.apply("incidents", "add_incident", {**BASE, "status": "guarded"})


@pytest.mark.parametrize("field,value", [
    ("detected_at", "2026-10-13T10:00:00-05:00"),     # not UTC
    ("pattern_id", "Tool.op"),                        # not <tool>.<operation>.<shape>
    ("detected_by", "someone"),
])
def test_bad_values_are_rejected(store, field, value):
    with pytest.raises(ValidationError):
        store.apply("incidents", "add_incident", {**BASE, field: value})


def test_ids_are_unique(store):
    v = _violations(store, [_entry(), _entry()])
    assert any("duplicate id" in x for x in v), v


def test_the_seeds_validate_and_apply_once(store):
    ids = apply_seeds(store)
    assert ids == ["INC-0001", "INC-0002"] and len(SEEDS) == 2
    assert store.validate() == []
    assert all(store.get("incidents", i)["status"] == "guarded" for i in ids)
    with pytest.raises(SystemExit):
        apply_seeds(store)


def test_tampering_with_the_file_is_detected(store):
    store.apply("incidents", "add_incident", dict(BASE))
    path = store.data_path
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["collections"]["incidents"]["entries"][0]["harm"] = "edited outside the verbs"
    path.write_bytes(json.dumps(doc).encode("utf-8"))
    with pytest.raises(IntegrityError):
        store.verify_integrity()


def test_the_cli_drives_the_incidents_consumer(tmp_path):
    data = tmp_path / "incidents.json"
    base = [sys.executable, "-m", "core.cli", "--data", str(data), "--consumer", "incidents",
            "--collection", "incidents"]
    r = subprocess.run(base + ["apply", "add_incident", "--json", json.dumps(BASE)], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(base + ["validate"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("pattern", ["tool.op", "a.b.c.d"])
def test_the_pattern_rule_needs_exactly_three_parts(store, pattern):
    """Lower-case and dot-separated, so the schema accepts it; only the pattern rule can refuse."""
    with pytest.raises(ValidationError, match="pattern_id must be"):
        store.apply("incidents", "add_incident", {**BASE, "pattern_id": pattern})

def _guard(store, iid, **over):
    store.apply("incidents", "set_guarded", {"id": iid, "guard_commit": "a" * 40,
                                             "regression_test": "tests/x.py::t",
                                             "guarded_at": "2026-10-13T11:00:00Z", **over})


def test_a_recorded_guard_cannot_be_rewritten(store):
    iid = store.apply("incidents", "add_incident", dict(BASE))["entries_touched"][0]
    _guard(store, iid)
    with pytest.raises(OperationError, match="only an open incident"):
        _guard(store, iid, guard_commit="b" * 40)
    assert store.get("incidents", iid)["guard_commit"] == "a" * 40


def test_wontfix_and_unknown_ids_cannot_be_guarded(store):
    iid = store.apply("incidents", "add_incident", {**BASE, "status": "wontfix"})["entries_touched"][0]
    with pytest.raises(OperationError):
        _guard(store, iid)
    with pytest.raises(OperationError, match="no incident"):
        _guard(store, "INC-0999")


@pytest.mark.parametrize("over,msg", [
    ({"observed_at": "2026-10-14T00:00:00Z"}, "observed_at is after detected_at"),
])
def test_time_order_is_enforced_on_add(store, over, msg):
    with pytest.raises(ValidationError, match=msg):
        store.apply("incidents", "add_incident", {**BASE, **over})


def test_a_guard_before_detection_is_rejected(store):
    iid = store.apply("incidents", "add_incident", dict(BASE))["entries_touched"][0]
    with pytest.raises(ValidationError, match="guarded_at is before detected_at"):
        _guard(store, iid, guarded_at="2000-01-01T00:00:00Z")


def test_a_write_after_tampering_is_refused(store):
    store.apply("incidents", "add_incident", dict(BASE))
    path = store.data_path
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["collections"]["incidents"]["entries"][0]["harm"] = "edited outside the verbs"
    path.write_bytes(json.dumps(doc).encode("utf-8"))
    with pytest.raises(IntegrityError):
        store.apply("incidents", "add_incident", dict(BASE))


def test_ids_continue_past_four_digits(store):
    v = _violations(store, [_entry(id="INC-10000")])
    assert not any("id" in x and "pattern" in x.lower() for x in v), v
    assert v == [], v