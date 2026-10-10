"""The metric. `measure` is pure: it reads two values and returns a third, and does no I/O.

Every name in I (active or retired) and in P falls in exactly one class:

    matched         active, present, same hash
    modified        active, present, different hash
    vanished        active, absent
    phantom         present, not in I
    resurrected     retired, present
    retired-absent  retired, absent        (correct; not counted in either ratio)

    precision = m / (m + d + v)        of what the inventory says is active, the share that is
                                       deployed exactly as recorded
    recall    = m / (m + d + p + z)    of what is deployed, the share the inventory describes
                                       correctly

Matching is by EXACT NAME only. No rename is ever inferred, not even when a phantom has the
same hash as a vanished entry: a guessed rename would turn an inventory error into a match.
An unrecorded rename is therefore one vanished plus one phantom. This is the same match rule
as the exact-key `reconcile` in this repository's structuredJsonValidator; that code is not
imported, so this module stands alone.

A name named by a scan error (a duplicate, or an item with no digest or unreadable bytes) is
WITHHELD from classification on both sides: it is not counted present, and an active
inventory entry of that name is not counted vanished either, because the item IS deployed and
only its hash is unknown. Withheld names are listed in the report beside the errors.
"""

from .inventory import Inventory
from .scan import Scan

CLASSES = ("matched", "modified", "vanished", "phantom", "resurrected", "retired-absent")


def _ratio(numerator: int, denominator: int) -> dict:
    # A zero denominator means there is nothing to take a share of. It is reported as null and
    # never as 0 or 1: "no active entries" is not "every active entry is wrong", and an empty
    # deployment is not "everything deployed is described".
    return {"numerator": numerator, "denominator": denominator,
            "value": None if denominator == 0 else numerator / denominator}


def classify(name: str, inventory: Inventory, present) -> str:
    if name in inventory.active:
        if name not in present:
            return "vanished"
        return "matched" if present[name] == inventory.active[name] else "modified"
    if name in inventory.retired:
        return "resurrected" if name in present else "retired-absent"
    return "phantom"


def measure(inventory: Inventory, scan: Scan) -> dict:
    withheld = sorted({e.name for e in scan.errors if e.name is not None})
    present = {n: h for n, h in scan.present.items() if n not in withheld}

    names = {c: [] for c in CLASSES}
    for name in sorted(set(inventory.active) | set(inventory.retired) | set(present)):
        if name in withheld:
            continue
        names[classify(name, inventory, present)].append(name)

    counts = {c: len(v) for c, v in names.items()}
    m, d, v = counts["matched"], counts["modified"], counts["vanished"]
    p, z = counts["phantom"], counts["resurrected"]
    return {
        "counts": counts,
        "names": names,
        "precision": _ratio(m, m + d + v),
        "recall": _ratio(m, m + d + p + z),
        "withheld": withheld,
        "errors": [e.to_dict() for e in scan.errors],
        "locations": [dict(loc) for loc in scan.locations],
    }
