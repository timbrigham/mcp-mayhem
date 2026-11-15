"""A declaration's record carries only what somebody actually reported (Tim, 2026-11-15).

*"you can only sign off on what people have actually stated themselves"* — the petition rule.
The first field it lands on is ``verify.sorry_free``: three write paths stored ``True`` when
nobody reported a value, and every proved/deep claim in the live store rested only on such
defaults. See ``consumers.lean.operations.reported_sorry_free`` for the measurement.

Each write path gets its own test, because the defect lived in three places and a guard on two
of them reads exactly like a guard on all three.
"""

import pytest

from consumers.lean.operations import reported_sorry_free
from consumers.store import build_store
from core.errors import ValidationError

ANCHOR = {"branch": "origin/main", "commit": None, "tree": None}


def _store(tmp_path):
    return build_store(tmp_path / "store.json")


def _unreported_scan(n):
    # Deliberately NO sorry_free key: this is what every real import in the audit looked like.
    return [{"qualified": f"A.d{i}", "short": f"d{i}", "kind": "def",
             "file": "f.lean", "line": i, "prefix": "A"} for i in range(n)]


def _verify_values(s):
    ents = s.find("declarations")
    assert len(ents) > 0  # floor: an empty find must not pass the assertions below vacuously
    return [e["verify"]["sorry_free"] for e in ents]


def test_helper_maps_unreported_to_unknown_and_keeps_reports():
    assert reported_sorry_free(None) is None
    assert reported_sorry_free(True) is True
    assert reported_sorry_free(False) is False


def test_import_baseline_without_a_report_records_unknown(tmp_path):
    s = _store(tmp_path)
    s.apply("declarations", "import_baseline",
            {"scanner_output": _unreported_scan(3), "anchor": ANCHOR})
    assert _verify_values(s) == [None, None, None]


def test_import_baseline_keeps_a_reported_value(tmp_path):
    s = _store(tmp_path)
    scan = _unreported_scan(2)
    scan[0]["sorry_free"] = True
    scan[1]["sorry_free"] = False
    s.apply("declarations", "import_baseline", {"scanner_output": scan, "anchor": ANCHOR})
    assert sorted(_verify_values(s), key=str) == [False, True]


def test_add_new_without_a_report_records_unknown(tmp_path):
    s = _store(tmp_path)
    s.apply("declarations", "add_new",
            {"new": {"qualified": "A.fresh", "file": "f.lean"}, "reason": "new at HEAD"})
    assert _verify_values(s) == [None]


def test_store_migrate_batch_add_new_without_a_report_records_unknown(tmp_path):
    # The third write path, and the one carrying 2,741 of the live store's entries.
    s = _store(tmp_path)
    s.apply_store("migrate_batch", {"add_new": [
        {"qualified": "A.b1", "file": "f.lean"}, {"qualified": "A.b2", "file": "f.lean"}]})
    assert _verify_values(s) == [None, None]


def _claim_with_one_witness(s, *, sorry_free):
    s.apply("declarations", "import_baseline",
            {"scanner_output": _unreported_scan(1), "anchor": ANCHOR})
    eid = s.find("declarations")[0]["id"]
    if sorry_free is not None:
        s.apply("declarations", "set_verify", {"id": eid, "sorry_free": sorry_free})
    s.apply("claims", "add_claim", {"claim_id": "T", "statement": "x", "status": "conj"})
    s.apply("declarations", "link_claim", {"id": eid, "claim": "T"})
    return eid


def test_an_unknown_witness_cannot_hold_up_a_proved_claim(tmp_path):
    s = _store(tmp_path)
    eid = _claim_with_one_witness(s, sorry_free=None)
    with pytest.raises(ValidationError) as exc:
        s.apply("claims", "set_status", {"claim_id": "T", "status": "proved"})
    msg = str(exc.value)
    # The refusal says WHICH kind of missing it is and how to satisfy it.
    assert "UNKNOWN" in msg and eid in msg and "set_verify" in msg


def test_a_reported_witness_holds_up_a_proved_claim(tmp_path):
    s = _store(tmp_path)
    _claim_with_one_witness(s, sorry_free=True)
    s.apply("claims", "set_status", {"claim_id": "T", "status": "proved"})
    assert s.validate() == []


def test_a_false_witness_refuses_without_the_unknown_hint(tmp_path):
    # FALSE (the build found a sorry) and UNKNOWN (nobody looked) have different remedies.
    s = _store(tmp_path)
    _claim_with_one_witness(s, sorry_free=False)
    with pytest.raises(ValidationError) as exc:
        s.apply("claims", "set_status", {"claim_id": "T", "status": "proved"})
    assert "UNKNOWN" not in str(exc.value)
