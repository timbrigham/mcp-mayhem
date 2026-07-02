"""Projections generated from the one source (spec §5). Views cannot drift from
the registry because they are computed from it on demand."""

from __future__ import annotations

from collections import Counter

_DISPOSITIONS = ["pending", "present", "moved", "renamed", "merged", "split", "dropped", "new"]


def status_table(document: dict, **_params) -> str:
    """A Markdown status table: count of entries per disposition."""
    entries = document.get("entries", [])
    counts = Counter(e.get("disposition") for e in entries)
    lines = ["| disposition | count |", "|---|---|"]
    for disp in _DISPOSITIONS:
        lines.append(f"| {disp} | {counts.get(disp, 0)} |")
    lines.append(f"| **total** | **{len(entries)}** |")
    return "\n".join(lines)


def domain_table(document: dict, **_params) -> str:
    """Markdown table: entry count per curated ontology.domain (null → '(unassigned)')."""
    entries = document.get("entries", [])
    counts = Counter((e.get("ontology", {}).get("domain") or "(unassigned)") for e in entries)
    lines = ["| domain | count |", "|---|---|"]
    for domain, n in sorted(counts.items()):
        lines.append(f"| {domain} | {n} |")
    return "\n".join(lines)


def _cardinality_min(cardinality) -> int:
    """Lower bound of a stored cardinality (normalized to {'min','max'} by
    set_vocab). Tolerates a raw range/count string too, for robustness."""
    if isinstance(cardinality, dict):
        try:
            return int(cardinality.get("min") or 0)
        except (TypeError, ValueError):
            return 0
    if isinstance(cardinality, str):
        tok = (cardinality.strip().split("..")[0].split() or [""])[0]
        return int(tok) if tok.isdigit() else 0
    return 0


_ANOMALY_DEFAULT_LIMIT = 50


def anomaly_table(document: dict, *, count_only: bool = False,
                  limit=None, offset: int = 0, **_params) -> str:
    """Soft-cardinality anomalies (interop tag-vocab work item).

    Cardinality in the vocab is an EXPECTATION, never enforced: a declaration may
    be multi-domain, zero-domain, or an 'impossible' combination — the
    framework's subject matter deliberately includes counterexamples and
    impossibilities, so the model must be able to REPRESENT them. This view only
    SURFACES entries whose required (min>=1) ontology axis is unset, for review;
    it blocks nothing.

    This IS the tagging worklist, so it is large by design — and returns a
    receipt, not the warehouse (interop issue #6). Every render leads with a
    summary (total + per-axis missing counts). ``count_only=True`` returns ONLY
    that summary. Otherwise the rows are paged: ``offset``/``limit`` window them,
    with a safe default page of 50; pass ``limit=0`` for all rows.
    """
    vocab = document.get("vocab") or {}
    required = sorted(f for f, spec in vocab.items()
                      if _cardinality_min(spec.get("cardinality")) >= 1)

    rows: list[tuple] = []
    per_axis = {f: 0 for f in required}
    for entry in document.get("entries", []):
        ont = entry.get("ontology") or {}
        missing = [f for f in required if ont.get(f) is None]
        if missing:
            rows.append((entry.get("id"), missing))
            for f in missing:
                per_axis[f] += 1
    total = len(rows)

    summary = [f"anomalies: {total} entr{'y' if total == 1 else 'ies'} "
               f"missing a required axis (of {len(document.get('entries', []))} total)",
               "", "| axis | missing |", "|---|---|"]
    for f in required:
        summary.append(f"| {f} | {per_axis[f]} |")
    if not required:
        summary.append("| _(no required axes in vocab)_ | |")

    if count_only:
        return "\n".join(summary)

    lim = _ANOMALY_DEFAULT_LIMIT if limit is None else limit
    window = rows[offset:] if lim in (0, None) else rows[offset:offset + lim]
    shown = f"showing {offset + 1}–{offset + len(window)} of {total}" if window else "none in range"
    lines = summary + ["",
                       f"rows ({shown}; offset={offset}, "
                       f"limit={'all' if lim in (0, None) else lim}, count_only for summary only)",
                       "", "| id | missing required axis |", "|---|---|"]
    for eid, missing in window:
        lines.append(f"| {eid} | {', '.join(missing)} |")
    if not window:
        lines.append("| _(none)_ | |")
    return "\n".join(lines)


VIEWS = {
    "status": status_table,
    "domains": domain_table,
    "anomalies": anomaly_table,
}
