"""Reader / projection engine over the entries array (spec §5, §9).

Generic dotted-path filters, e.g. ``find(disposition="pending",
**{"ontology.domain": "number"})``. No knowledge of any consumer's fields — the
caller names the paths.
"""

from __future__ import annotations

from typing import Any, Optional

_MISSING = object()


def get_path(entry: dict, dotted: str) -> Any:
    """Resolve a dotted path within an entry; returns ``_MISSING`` if absent."""
    node: Any = entry
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return _MISSING
    return node


def get(entries: list[dict], id_key: str, entry_id: str) -> Optional[dict]:
    for entry in entries:
        if entry.get(id_key) == entry_id:
            return entry
    return None


def find(entries: list[dict], **filters: Any) -> list[dict]:
    """Return entries matching every ``dotted.path == value`` filter (AND)."""
    results: list[dict] = []
    for entry in entries:
        if all(get_path(entry, key) == value for key, value in filters.items()):
            results.append(entry)
    return results
