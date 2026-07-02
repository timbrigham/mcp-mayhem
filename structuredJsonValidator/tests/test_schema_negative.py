"""Negative tests for the structural validator: prove it is a real gate.

Each injects one class of malformation and asserts it is caught (spec §12.1).
"""

from core.schema import structural_violations
from tests.conftest import mutate


def test_conforming_sample_has_no_structural_violations(sample, schema):
    assert structural_violations(sample, schema) == []


def test_missing_required_key_is_caught(sample, schema):
    bad = mutate(sample, lambda d: d["entries"][0].pop("disposition"))
    v = structural_violations(bad, schema)
    assert any("disposition" in msg and "required" in msg for msg in v)


def test_bad_enum_value_is_caught(sample, schema):
    bad = mutate(sample, lambda d: d["entries"][0].__setitem__("disposition", "banana"))
    v = structural_violations(bad, schema)
    assert any("banana" in msg or "enum" in msg for msg in v)


def test_wrong_type_is_caught(sample, schema):
    bad = mutate(sample, lambda d: d["entries"][0]["old"].__setitem__("line", "not-an-int"))
    v = structural_violations(bad, schema)
    assert any("line" in msg for msg in v)


def test_extra_key_is_caught_additional_properties_false(sample, schema):
    bad = mutate(sample, lambda d: d["entries"][0].__setitem__("surprise", 1))
    v = structural_violations(bad, schema)
    assert any("surprise" in msg or "Additional" in msg for msg in v)


def test_null_in_nonleaf_object_is_caught(sample, schema):
    # Only leaf scalars may be null (spec §2 principle 2); a null 'old' object fails.
    bad = mutate(sample, lambda d: d["entries"][0].__setitem__("old", None))
    assert structural_violations(bad, schema)


def test_reports_all_violations_not_just_first(sample, schema):
    def wreck(d):
        d["entries"][0]["disposition"] = "banana"
        d["entries"][0].pop("reason")
        d["entries"][0]["old"]["line"] = "x"
    bad = mutate(sample, wreck)
    v = structural_violations(bad, schema)
    assert len(v) >= 3  # all reported, validator does not stop at the first
