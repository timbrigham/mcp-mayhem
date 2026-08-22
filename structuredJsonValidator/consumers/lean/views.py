"""Projections generated from the one source (spec §5). Views cannot drift from
the registry because they are computed from it on demand."""

from __future__ import annotations

from collections import Counter
from typing import Optional

_DISPOSITIONS = ["pending", "present", "moved", "renamed", "merged", "split", "dropped",
                 "withdrawn", "new"]

# Dispositions whose declaration is NOT expected to exist at HEAD. A total that
# silently includes them overstates the corpus, which is the whole reason the
# table separates them out rather than just summing rows.
_NOT_LIVE = ("dropped", "merged", "split", "withdrawn")


def status_table(document: dict, **_params) -> str:
    """A Markdown status table: count of entries per disposition.

    Reports a LIVE total alongside the raw one. Terminal dispositions name a
    declaration that is gone (``dropped``), spent into another entry (``merged``/
    ``split``) or was added in error and never existed (``withdrawn``) — counting
    those as part of the corpus inflates it.
    """
    entries = document.get("entries", [])
    counts = Counter(e.get("disposition") for e in entries)
    retired = sum(counts.get(d, 0) for d in _NOT_LIVE)
    lines = ["| disposition | count |", "|---|---|"]
    for disp in _DISPOSITIONS:
        marker = " *(not live)*" if disp in _NOT_LIVE else ""
        lines.append(f"| {disp}{marker} | {counts.get(disp, 0)} |")
    lines.append(f"| **live total** | **{len(entries) - retired}** |")
    lines.append(f"| **all entries** | **{len(entries)}** |")
    return "\n".join(lines)


def domain_table(document: dict, **_params) -> str:
    """Markdown table: entry count per curated ontology.domain. Each entry's
    domain is a LIST (a multi-domain decl counts once per domain); an empty list
    counts as '(unassigned)'."""
    counts: Counter = Counter()
    for e in document.get("entries", []):
        domains = (e.get("ontology") or {}).get("domain") or []
        if domains:
            counts.update(domains)
        else:
            counts["(unassigned)"] += 1
    lines = ["| domain | count |", "|---|---|"]
    for domain, n in sorted(counts.items()):
        lines.append(f"| {domain} | {n} |")
    return "\n".join(lines)


def _cardinality_bounds(cardinality) -> tuple[int, Optional[int]]:
    """(min, max) of a stored cardinality (normalized to {'min','max'} by
    set_vocab; max None = uncapped). Tolerates a raw range/count string too."""
    if isinstance(cardinality, dict):
        try:
            mn = int(cardinality.get("min") or 0)
        except (TypeError, ValueError):
            mn = 0
        mx = cardinality.get("max")
        return mn, (int(mx) if isinstance(mx, int) else None)
    if isinstance(cardinality, str):
        tok = (cardinality.strip().split("..")[0].split() or [""])[0]
        return (int(tok) if tok.isdigit() else 0), None
    return 0, None


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

    Each axis is a LIST; an anomaly is a count outside its soft cardinality —
    below ``min`` (e.g. a required axis unset) or above ``max`` (over-cap, only
    when ``max`` is not null; ``max: null`` = uncapped, so multi-value axes like
    domain never over-flag). This IS the tagging worklist, so it is large by
    design — and returns a receipt, not the warehouse (interop issue #6). Every
    render leads with a summary (total + per-axis anomaly counts).
    ``count_only=True`` returns ONLY that summary. Otherwise rows are paged:
    ``offset``/``limit`` window them, default page 50; ``limit=0`` for all.
    """
    vocab = document.get("vocab") or {}
    bounds = {f: _cardinality_bounds(spec.get("cardinality")) for f, spec in vocab.items()}
    # Only axes with an active bound (min>=1, or a finite max) can anomaly.
    active = sorted(f for f, (mn, mx) in bounds.items() if mn >= 1 or mx is not None)

    rows: list[tuple] = []
    per_axis = {f: 0 for f in active}
    for entry in document.get("entries", []):
        ont = entry.get("ontology") or {}
        bad = []
        for f in active:
            mn, mx = bounds[f]
            n = len(ont.get(f) or [])
            if n < mn:
                bad.append(f)  # under (e.g. required-but-missing)
            elif mx is not None and n > mx:
                bad.append(f"{f}>{mx}")  # over the soft cap
        if bad:
            rows.append((entry.get("id"), bad))
            for f in bad:
                per_axis[f.split(">")[0]] += 1
    total = len(rows)

    summary = [f"anomalies: {total} entr{'y' if total == 1 else 'ies'} "
               f"outside a soft cardinality (of {len(document.get('entries', []))} total)",
               "", "| axis | anomalies |", "|---|---|"]
    for f in active:
        summary.append(f"| {f} | {per_axis[f]} |")
    if not active:
        summary.append("| _(no cardinality bounds in vocab)_ | |")

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


_PHANTOM_DEFAULT_LIMIT = 50


def phantom_table(document: dict, *, root: str = ".", count_only: bool = False,
                  limit=None, offset: int = 0, **_params) -> str:
    """Entries whose ``new.file`` does not resolve on disk — the drift `validate` cannot see.

    ``validate`` and ``verify_integrity`` check internal conformance and hash
    continuity. Neither resolves anything against the filesystem, so a registry can
    be green while describing declarations of a file that no longer exists — which
    is what let a reverted file's entries sit unnoticed. This makes that class
    mechanically visible instead of depending on someone remembering to look.

    Sibling of the ``anomalies`` view (the tagging worklist); this is the same idea
    one level down, and it is paged the same way (interop issue #6).

    NEVER A GATE, deliberately: the registry is legitimately edited from machines
    that may not have the corpus checked out, so a missing file there means "not
    checked out", not "drift". Pass ``root`` to point at the corpus.

    Scope: only entries expected to still exist AND carrying a HEAD identity. A
    terminal entry names something that is *supposed* to be gone, and a still-
    ``pending`` entry's location is an anchor-era path, stale by design.

    For the stronger check — that the declaration is actually DECLARED in the file
    it names — use the ``check_head`` tool with ``tier='names'``.
    """
    from pathlib import Path

    from consumers.lean.rules import effective_qualified

    base = Path(root)
    rows: list[tuple[str, str, str]] = []
    checked = 0
    for entry in document.get("entries", []):
        group, qualified, present = effective_qualified(entry)
        if not qualified or not present or group != "new":
            continue
        rel = (entry.get("new") or {}).get("file")
        if not rel:
            continue
        checked += 1
        if not (base / rel).exists():
            rows.append((entry.get("id", "?"), qualified, rel))

    by_file: Counter = Counter(rel for _, _, rel in rows)
    total = len(rows)
    summary = [f"phantom declarations (new.file does not resolve under {base}): "
               f"**{total}** of {checked} checked", "",
               "| missing file | entries |", "|---|---|"]
    for rel, n in sorted(by_file.items()):
        summary.append(f"| {rel} | {n} |")
    if not by_file:
        summary.append("| _(none — every checked new.file resolves)_ | |")
    if count_only:
        return "\n".join(summary)

    lim = _PHANTOM_DEFAULT_LIMIT if limit is None else limit
    window = rows[offset:] if lim in (0, None) else rows[offset:offset + lim]
    shown = (f"showing {offset + 1}–{offset + len(window)} of {total}"
             if window else "none in range")
    lines = summary + ["", f"rows ({shown})", "", "| id | qualified | file |", "|---|---|---|"]
    for eid, qualified, rel in window:
        lines.append(f"| {eid} | {qualified} | {rel} |")
    if not window:
        lines.append("| _(none)_ | | |")
    return "\n".join(lines)


VIEWS = {
    "status": status_table,
    "domains": domain_table,
    "anomalies": anomaly_table,
    "phantoms": phantom_table,
}
