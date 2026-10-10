"""The inventory file: what the system is SAID to contain.

Format (JSON, UTF-8):

    {"active":  [{"name": "prompts/system.md", "sha256": "<64 lowercase hex>"}, ...],
     "retired": ["tools/legacy.json", ...]}

Both keys are required and no others are allowed. An inventory that breaks a rule is REFUSED
rather than measured, because any number computed from it would describe a list that does not
mean what it says.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class CannotMeasure(Exception):
    """Nothing was measured. Carries what was wrong and what input would succeed."""

    def __init__(self, what: str, satisfied_when: str):
        super().__init__(what)
        self.what = what
        self.satisfied_when = satisfied_when


class InventoryRefused(CannotMeasure):
    """The inventory was read but breaks a rule of the format."""


@dataclass(frozen=True)
class Inventory:
    active: Mapping[str, str] = field(default_factory=dict)
    retired: frozenset = frozenset()

    def __post_init__(self):
        # Re-checked here, not only in the file parser, so an Inventory built in code (as the
        # tests do) is held to the same rule as one read from disk.
        both = sorted(set(self.active) & set(self.retired))
        if both:
            raise InventoryRefused(
                f"names are both active and retired: {', '.join(both)}",
                "each name appears either under 'active' or under 'retired', never both")
        object.__setattr__(self, "active", MappingProxyType(dict(self.active)))
        object.__setattr__(self, "retired", frozenset(self.retired))


def _no_duplicate_keys(pairs):
    keys = [k for k, _ in pairs]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise InventoryRefused(f"duplicate JSON key(s) {dupes}",
                               "every JSON object in the inventory has unique keys")
    return dict(pairs)


def parse_inventory(raw: bytes) -> Inventory:
    try:
        doc = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryRefused(f"inventory is not valid UTF-8 JSON ({exc})",
                               "the inventory is a UTF-8 JSON document") from None

    shape = 'a JSON object {"active": [{"name": ..., "sha256": ...}, ...], "retired": [names]}'
    if not isinstance(doc, dict) or set(doc) != {"active", "retired"}:
        # 'retired' is required even when empty: a misspelt key would otherwise read as
        # "nothing is retired" and turn every resurrection into a phantom.
        got = sorted(doc) if isinstance(doc, dict) else type(doc).__name__
        raise InventoryRefused(f"inventory must have exactly the keys active and retired; got {got}", shape)
    if not isinstance(doc["active"], list) or not isinstance(doc["retired"], list):
        raise InventoryRefused("'active' and 'retired' must both be lists", shape)

    active: dict[str, str] = {}
    for i, entry in enumerate(doc["active"]):
        if not isinstance(entry, dict) or set(entry) != {"name", "sha256"}:
            raise InventoryRefused(f"active[{i}] must be an object with exactly 'name' and 'sha256'", shape)
        name, digest = entry["name"], entry["sha256"]
        if not isinstance(name, str) or not name:
            raise InventoryRefused(f"active[{i}] has no name", "every active entry has a non-empty name")
        if not isinstance(digest, str) or not _SHA256_HEX.fullmatch(digest):
            raise InventoryRefused(f"active entry {name!r} has sha256 {digest!r}",
                                   "every sha256 is 64 lowercase hex characters, as printed by 'register'")
        if name in active:
            # A dict would silently keep the second entry, and the inventory would then claim
            # one hash while the file on disk holds two.
            raise InventoryRefused(f"active name {name!r} appears more than once",
                                   "each active name appears exactly once")
        active[name] = digest

    retired: set[str] = set()
    for i, name in enumerate(doc["retired"]):
        if not isinstance(name, str) or not name:
            raise InventoryRefused(f"retired[{i}] is not a non-empty string", "every retired entry is a name")
        if name in retired:
            raise InventoryRefused(f"retired name {name!r} appears more than once",
                                   "each retired name appears exactly once")
        retired.add(name)

    return Inventory(active=active, retired=frozenset(retired))


def load_inventory(path: Path) -> Inventory:
    # Opened read-only; nothing in this package ever writes the inventory.
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        raise CannotMeasure(f"inventory file {str(path)!r} does not exist",
                            "--inventory names an existing inventory file") from None
    except OSError as exc:
        raise CannotMeasure(f"inventory file {str(path)!r} could not be read ({exc.strerror})",
                            "--inventory names a readable file") from None
    return parse_inventory(raw)
