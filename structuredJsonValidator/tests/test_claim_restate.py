"""restate_claim: change what a claim SAYS without erasing what it said.

Requested by ZeroParadox 2026-09-15. Tim ruled that `DA-1` and `node-computability` overclaim and
must be restated. No op could change a statement, and drop + add erases the claim's recorded history,
which Tim declined. The design is Tim's, 2026-09-15: a separate `restatements` list, not `history`,
with reason, date and `by` all required.
"""

import json

import pytest

from consumers.store import build_store
from core.errors import OperationError


def _claim(s, cid):
    r = s.find("claims", claim_id=cid)
    return r[0] if r else None


def _restate(s, cid="DA-1", statement="narrower", **over):
    params = {"claim_id": cid, "statement": statement, "date": "2026-09-15",
              "reason": "overclaims", "by": "Tim"}
    params.update(over)
    return s.apply("claims", "restate_claim", params)


def _seeded(tmp_path):
    s = build_store(tmp_path / "store.json")
    s.apply("claims", "add_claim", {"claim_id": "DA-1", "statement": "the broad claim",
                                    "status": "conj", "date": "2026-09-01"})
    return s


def test_a_restatement_keeps_the_replaced_text_and_who_ruled(tmp_path):
    """⭐ THE REQUEST. The new text is current, and the old text is readable with date, reason
    and the person who ruled."""
    s = _seeded(tmp_path)
    _restate(s)

    c = _claim(s, "DA-1")
    assert c["statement"] == "narrower"
    assert c["restatements"] == [{"prior_statement": "the broad claim", "date": "2026-09-15",
                                  "reason": "overclaims", "by": "Tim"}]
    assert s.validate() == []


def test_status_history_is_untouched(tmp_path):
    """⚠ A SEPARATE LIST ON PURPOSE. `history` is status provenance, and its entries are locked to
    {status, date}. A restatement must not add a row there or change the claim's status."""
    s = _seeded(tmp_path)
    before = _claim(s, "DA-1")
    _restate(s)
    after = _claim(s, "DA-1")
    assert after["history"] == before["history"]
    assert after["status"] == before["status"] and after["date"] == before["date"]


def test_restatements_chain_in_order(tmp_path):
    """Two restatements leave the full chain: original -> first -> current."""
    s = _seeded(tmp_path)
    _restate(s, statement="first narrowing")
    _restate(s, statement="second narrowing", date="2026-09-16", reason="still overclaims")
    c = _claim(s, "DA-1")
    assert [r["prior_statement"] for r in c["restatements"]] == ["the broad claim",
                                                                "first narrowing"]
    assert c["statement"] == "second narrowing"


@pytest.mark.parametrize("field", ["statement", "date", "reason", "by"])
def test_every_provenance_field_is_required(tmp_path, field):
    """⛔ `by` especially: nothing else on a claim can say who ruled. An empty value is refused,
    and the claim is left exactly as it was."""
    s = _seeded(tmp_path)
    before = _claim(s, "DA-1")
    with pytest.raises(OperationError, match=field):
        _restate(s, **{field: "  "})
    assert _claim(s, "DA-1") == before


def test_a_restatement_to_the_same_text_is_refused(tmp_path):
    """⚠ It would append a row asserting a change that did not happen."""
    s = _seeded(tmp_path)
    with pytest.raises(OperationError, match="already says exactly that"):
        _restate(s, statement="the broad claim")
    assert "restatements" not in _claim(s, "DA-1")


def test_an_unknown_claim_is_refused(tmp_path):
    s = _seeded(tmp_path)
    with pytest.raises(OperationError, match="no claim"):
        _restate(s, cid="NOPE")


def test_a_malformed_restatement_row_fails_schema(tmp_path):
    """The schema, not only the op, holds the shape: a row missing `by` fails validation, so a
    hand-edited or old-client store cannot carry an unattributed restatement."""
    s = _seeded(tmp_path)
    doc = json.loads((tmp_path / "store.json").read_text(encoding="utf-8"))
    claim = doc["collections"]["claims"]["entries"][0]
    claim["restatements"] = [{"prior_statement": "x", "date": "2026-09-15", "reason": "r"}]
    assert any("by" in v for v in s.all_violations(doc))


def test_export_full_carries_the_restatement(tmp_path):
    """ZeroParadox consumes the export, so the restatement must reach it."""
    s = _seeded(tmp_path)
    _restate(s)
    s.export_full(tmp_path / "pub.json")
    text = (tmp_path / "pub.json").read_text(encoding="utf-8")
    pub = json.loads(text)
    claims = pub["collections"]["claims"]["entries"]
    assert claims[0]["statement"] == "narrower"
    assert claims[0]["restatements"][0]["by"] == "Tim"


def test_a_never_restated_claim_is_unchanged_in_shape(tmp_path):
    """⚠ Additive: claims that were never restated carry no `restatements` key, so existing
    exports and ZeroParadox's diff guard see no change for them."""
    s = _seeded(tmp_path)
    assert "restatements" not in _claim(s, "DA-1")
    assert s.validate() == []
