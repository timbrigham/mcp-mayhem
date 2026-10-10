"""The inventory format: what is refused, and that refusal means nothing is measured."""

import json

import pytest

from inventory_fidelity import Inventory, InventoryRefused, parse_inventory

A, B = "a" * 64, "b" * 64


def raw(doc) -> bytes:
    return json.dumps(doc).encode("utf-8")


def test_a_valid_inventory_parses():
    inv = parse_inventory(raw({"active": [{"name": "x", "sha256": A}], "retired": ["r"]}))
    assert dict(inv.active) == {"x": A} and inv.retired == {"r"}


def test_a_name_both_active_and_retired_is_refused_from_file():
    with pytest.raises(InventoryRefused, match="both active and retired"):
        parse_inventory(raw({"active": [{"name": "x", "sha256": A}], "retired": ["x"]}))


def test_a_name_both_active_and_retired_is_refused_in_code_too():
    with pytest.raises(InventoryRefused, match="both active and retired"):
        Inventory(active={"x": A}, retired=frozenset({"x"}))


def test_duplicate_active_names_are_refused_even_with_equal_hashes():
    with pytest.raises(InventoryRefused, match="more than once"):
        parse_inventory(raw({"active": [{"name": "x", "sha256": A}, {"name": "x", "sha256": A}], "retired": []}))


def test_duplicate_active_names_with_different_hashes_are_refused():
    with pytest.raises(InventoryRefused, match="more than once"):
        parse_inventory(raw({"active": [{"name": "x", "sha256": A}, {"name": "x", "sha256": B}], "retired": []}))


def test_duplicate_retired_names_are_refused():
    with pytest.raises(InventoryRefused, match="more than once"):
        parse_inventory(raw({"active": [], "retired": ["r", "r"]}))


@pytest.mark.parametrize("doc", [
    {"active": []},                                   # 'retired' missing: absence is not "none retired"
    {"retired": []},
    {"active": [], "retired": [], "extra": 1},
    {"active": [{"name": "x"}], "retired": []},
    {"active": [{"name": "", "sha256": A}], "retired": []},
    {"active": [{"name": "x", "sha256": "A" * 64}], "retired": []},
    {"active": [{"name": "x", "sha256": "abc"}], "retired": []},
    {"active": [], "retired": [""]},
    [],
])
def test_malformed_inventories_are_refused(doc):
    with pytest.raises(InventoryRefused):
        parse_inventory(raw(doc))


def test_a_duplicate_json_key_is_refused():
    with pytest.raises(InventoryRefused, match="duplicate JSON key"):
        parse_inventory(b'{"active": [], "retired": [], "retired": ["x"]}')


def test_a_refusal_names_what_would_succeed():
    with pytest.raises(InventoryRefused) as exc:
        parse_inventory(raw({"active": [{"name": "x", "sha256": A}], "retired": ["x"]}))
    assert exc.value.satisfied_when
