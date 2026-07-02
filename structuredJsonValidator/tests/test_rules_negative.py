"""Negative tests for the §7 business rules (consumer-specific enforcement)."""

from consumers.lean.rules import validate
from tests.conftest import mutate


def test_conforming_sample_passes_business_rules(sample):
    assert validate(sample) == []


def test_duplicate_id_is_caught(sample):
    def dup(d):
        clone = dict(d["entries"][0])
        d["entries"].append(clone)
        d["counts"]["declarations"] = len(d["entries"])
    bad = mutate(sample, dup)
    assert any("duplicate id" in msg for msg in validate(bad))


def test_counts_mismatch_is_caught(sample):
    bad = mutate(sample, lambda d: d["counts"].__setitem__("declarations", 999))
    assert any("counts.declarations" in msg for msg in validate(bad))


def test_disposition_new_requires_old_null(sample):
    # entries[0] is 'pending' with old set; flip to 'new' → old must be null.
    bad = mutate(sample, lambda d: d["entries"][0].__setitem__("disposition", "new"))
    msgs = validate(bad)
    assert any("'new'" in m and "old" in m for m in msgs)


def test_disposition_dropped_requires_new_null(sample):
    def to_dropped(d):
        e = d["entries"][1]  # 'renamed' with new set
        e["disposition"] = "dropped"  # dropped requires new all-null
    bad = mutate(sample, to_dropped)
    msgs = validate(bad)
    assert any("'dropped'" in m and "new" in m for m in msgs)


def test_renamed_requires_reason(sample):
    bad = mutate(sample, lambda d: d["entries"][1].__setitem__("reason", None))
    assert any("reason" in m for m in validate(bad))


def test_pending_with_new_set_is_caught(sample):
    def bad_pending(d):
        d["entries"][0]["new"]["qualified"] = "X.y"  # pending requires new all-null
    bad = mutate(sample, bad_pending)
    assert any("'pending'" in m and "new" in m for m in validate(bad))
