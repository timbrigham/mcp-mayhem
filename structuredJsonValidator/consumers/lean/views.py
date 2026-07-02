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


def _cardinality_min(cardinality) -> int:
    """Lower bound of a cardinality spec ('1', '1..*' → 1; else 0)."""
    return 1 if isinstance(cardinality, str) and cardinality.strip().startswith("1") else 0


def anomaly_table(document: dict) -> str:
    """Soft-cardinality anomalies (interop tag-vocab work item).

    Cardinality in the vocab is an EXPECTATION, never enforced: a declaration may
    be multi-domain, zero-domain, or an 'impossible' combination — the
    framework's subject matter deliberately includes counterexamples and
    impossibilities, so the model must be able to REPRESENT them. This view only
    SURFACES entries whose required (min>=1) ontology axis is unset, for review;
    it blocks nothing.
    """
    vocab = document.get("vocab") or {}
    required = sorted(f for f, spec in vocab.items()
                      if _cardinality_min(spec.get("cardinality")) >= 1)
    lines = ["| id | missing required axis |", "|---|---|"]
    hits = 0
    for entry in document.get("entries", []):
        ont = entry.get("ontology") or {}
        missing = [f for f in required if ont.get(f) is None]
        if missing:
            hits += 1
            lines.append(f"| {entry.get('id')} | {', '.join(missing)} |")
    if not hits:
        lines.append("| _(none)_ | |")
    return "\n".join(lines)


VIEWS = {
    "status": status_table,
    "domains": domain_table,
    "anomalies": anomaly_table,
}
