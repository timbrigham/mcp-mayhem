"""The pure metric: each class, exact-name matching, ratios, null on a zero denominator."""

import pytest

from inventory_fidelity import CLASSES, Inventory, Scan, measure
from inventory_fidelity.scan import ScanError

A, B = "a" * 64, "b" * 64


def run(active=None, retired=(), present=None, errors=()):
    return measure(Inventory(active=active or {}, retired=frozenset(retired)),
                   Scan(present=present or {}, errors=errors))


@pytest.mark.parametrize("active,retired,present,expected", [
    ({"x": A}, (), {"x": A}, "matched"),
    ({"x": A}, (), {"x": B}, "modified"),
    ({"x": A}, (), {}, "vanished"),
    ({}, (), {"x": A}, "phantom"),
    ({}, ("x",), {"x": A}, "resurrected"),
    ({}, ("x",), {}, "retired-absent"),
])
def test_each_class(active, retired, present, expected):
    r = run(active, retired, present)
    assert r["names"][expected] == ["x"]
    assert r["counts"] == {c: (1 if c == expected else 0) for c in CLASSES}


def test_every_name_lands_in_exactly_one_class():
    r = run({"m": A, "d": A, "v": A}, ("z", "ra"), {"m": A, "d": B, "p": A, "z": A})
    flat = [n for c in CLASSES for n in r["names"][c]]
    assert sorted(flat) == sorted({"m", "d", "v", "p", "z", "ra"})
    assert len(flat) == len(set(flat))
    assert r["precision"] == {"numerator": 1, "denominator": 3, "value": 1 / 3}
    assert r["recall"] == {"numerator": 1, "denominator": 4, "value": 0.25}


def test_retired_absent_is_excluded_from_both_ratios():
    r = run({"m": A}, ("gone1", "gone2"), {"m": A})
    assert r["counts"]["retired-absent"] == 2
    assert r["precision"]["denominator"] == 1 and r["recall"]["denominator"] == 1


def test_unrecorded_rename_is_vanished_plus_phantom_even_with_the_same_hash():
    # Same bytes under a new name. A rename-guessing matcher would call this "matched".
    r = run({"tools/old.json": A}, (), {"tools/new.json": A})
    assert r["names"]["vanished"] == ["tools/old.json"]
    assert r["names"]["phantom"] == ["tools/new.json"]
    assert r["counts"]["matched"] == 0


def test_matching_is_exact_name_not_case_folded_or_normalised():
    # Both directions: a matcher that folds only one side passes either direction alone.
    for inv_name, scan_name in (("prompts/System.md", "prompts/system.md"),
                                ("prompts/system.md", "prompts/System.md"),
                                ("tools/a.json", "tools//a.json")):
        r = run({inv_name: A}, (), {scan_name: A})
        assert r["counts"]["matched"] == 0, (inv_name, scan_name)
        assert r["names"]["vanished"] == [inv_name] and r["names"]["phantom"] == [scan_name]


def test_zero_denominators_are_null_not_zero_or_one():
    r = run()
    assert r["precision"] == {"numerator": 0, "denominator": 0, "value": None}
    assert r["recall"] == {"numerator": 0, "denominator": 0, "value": None}


def test_only_phantoms_gives_null_precision_and_zero_recall():
    r = run({}, (), {"p": A})
    assert r["precision"]["value"] is None
    assert r["recall"] == {"numerator": 0, "denominator": 1, "value": 0.0}


def test_only_vanished_gives_zero_precision_and_null_recall():
    r = run({"v": A}, (), {})
    assert r["precision"] == {"numerator": 0, "denominator": 1, "value": 0.0}
    assert r["recall"]["value"] is None


def test_a_name_with_a_scan_error_is_withheld_not_called_vanished():
    err = ScanError("no-digest", "chat-model", "models.json references[0]", "tag only")
    r = run({"chat-model": A, "m": A}, (), {"m": A}, errors=(err,))
    assert r["withheld"] == ["chat-model"]
    assert all("chat-model" not in r["names"][c] for c in CLASSES)
    assert r["counts"]["vanished"] == 0
    assert r["errors"][0]["kind"] == "no-digest"


def test_measure_does_not_mutate_its_inputs():
    inv = Inventory(active={"x": A}, retired=frozenset({"r"}))
    scan = Scan(present={"x": B})
    before = (dict(inv.active), set(inv.retired), dict(scan.present))
    measure(inv, scan)
    assert before == (dict(inv.active), set(inv.retired), dict(scan.present))
