"""THE single renderer. Nothing else may produce a human verdict line.

Two representations written independently is `RLY28-1`: a report printing FAIL
rows over an exit code of 0. One value, one renderer — the pre-push hook's echo,
the manifest rows and the tag message all call this.

⚠ A FALLBACK basis prints the word, so the `FRZ-4` shape is visible in the line a
human actually reads rather than only in the JSON.
"""

from __future__ import annotations

from typing import Any


def render(record: dict) -> str:
    basis = record.get("basis") or {}
    decided = record.get("decided") or {}
    value = str(basis.get("value") or "")
    if len(value) > 12 and basis.get("kind") in ("tree", "ref"):
        value = value[:12]                       # a sha is recognisable at 12
    fallback = " FALLBACK" if basis.get("resolved_from") == "FALLBACK" else ""

    how = decided.get("how", "?")
    tally = ""
    if how == "agreement":
        tally = f" {decided.get('agreed')}/{decided.get('passes')}"
    elif how in ("signature", "override") and decided.get("who"):
        tally = f" {decided['who']}"

    rev = record.get("revision", 0)
    # ⚠ A key regraded four times must not read like one that passed cleanly.
    revision = f"  rev={rev}" if rev else ""

    waited = (record.get("cost") or {}).get("lock_wait_seconds")
    edge = f"  ⚠edge-condition lock_wait={waited}s" if waited else ""

    reason = record.get("reason") or ""
    return (f"{record.get('verdict', '?'):9} {record.get('step', '?')}  "
            f"tier={record.get('tier', '?')}  "
            f"basis={basis.get('kind')}:{value}{fallback}  "
            f"subjects={len(record.get('subjects') or [])}  "
            f"decided={how}{tally}{revision}{edge}"
            f"{('  ' + reason) if reason else ''}")


def render_inventory(inv: dict) -> str:
    """The allow/refuse line, grouped by family and showing the `how` breakdown.

    ⚠ A push carried by ten mechanical passes and one carried by ten signatures are
    different events, and nothing else would tell them apart. It matters most at a
    tag: a release whose keys are mostly `signature` is shipping known accepted
    debt, and that belongs in the deposit rather than in someone's memory.
    """
    counts = inv.get("how_breakdown") or {}
    breakdown = " · ".join(f"{k} {v}" for k, v in sorted(counts.items()) if v)
    head = ("ALLOWED " if inv.get("complete") else "REFUSED ")
    line = (f"{head} {inv.get('action')}  "
            f"{inv.get('satisfied')}/{inv.get('required')} keys"
            f"{('   ' + breakdown) if breakdown else ''}")
    if inv.get("complete"):
        return line

    lines = [line]
    for status in ("MISSING", "STALE", "UNDECIDED", "FAIL"):
        rows = [r for r in inv.get("rows", []) if r.get("status") == status]
        if not rows:
            continue
        for family in ("mechanical", "review"):
            names = sorted(r["step"] for r in rows if r.get("family") == family)
            if not names:
                continue
            # The remedies differ by an order of magnitude in cost, which is the
            # only reason the grouping exists.
            remedy = ("run python tools/verify/batch.py precommit"
                      if family == "mechanical" else "that is an agent round")
            lines.append(f"  {status:9} {family:10} {', '.join(names)}"
                         f"      INSTEAD: {remedy}")
    return "\n".join(lines)
