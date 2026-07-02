"""Projections generated from the one source (spec §5). Views cannot drift from
the registry because they are computed from it on demand."""

from __future__ import annotations

from collections import Counter

_DISPOSITIONS = ["pending", "present", "moved", "renamed", "merged", "split", "dropped", "new"]


def status_table(document: dict) -> str:
    """A Markdown status table: count of entries per disposition."""
    entries = document.get("entries", [])
    counts = Counter(e.get("disposition") for e in entries)
    lines = ["| disposition | count |", "|---|---|"]
    for disp in _DISPOSITIONS:
        lines.append(f"| {disp} | {counts.get(disp, 0)} |")
    lines.append(f"| **total** | **{len(entries)}** |")
    return "\n".join(lines)


def domain_table(document: dict) -> str:
    """Markdown table: entry count per curated ontology.domain (null → '(unassigned)')."""
    entries = document.get("entries", [])
    counts = Counter((e.get("ontology", {}).get("domain") or "(unassigned)") for e in entries)
    lines = ["| domain | count |", "|---|---|"]
    for domain, n in sorted(counts.items()):
        lines.append(f"| {domain} | {n} |")
    return "\n".join(lines)


VIEWS = {
    "status": status_table,
    "domains": domain_table,
}
