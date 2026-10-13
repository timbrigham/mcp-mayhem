"""Read-only projections of the ``incidents`` collection."""

from __future__ import annotations

import collections
import json


def summary(document: dict, **_params) -> str:
    """Counts by status and by pattern, as JSON."""
    entries = document.get("entries", [])
    by_pattern = collections.defaultdict(lambda: collections.Counter())
    for e in entries:
        by_pattern[e["pattern_id"]][e["status"]] += 1
    return json.dumps({
        "pattern_rule": document.get("pattern_rule"),
        "incidents": len(entries),
        "by_status": dict(collections.Counter(e["status"] for e in entries)),
        "by_pattern": {k: dict(v) for k, v in sorted(by_pattern.items())},
    }, indent=2)


VIEWS = {"summary": summary}
