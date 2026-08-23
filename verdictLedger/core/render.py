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
    """The allow/refuse line. ⚠ It must make three things visible at once: the
    verdict, HOW the passing keys were carried, and what is registered but not
    gating — because a finished gate nobody promoted never gates, silently, and
    silence is what made this class expensive."""
    counts = inv.get("how_breakdown") or {}
    breakdown = " · ".join(f"{k} {v}" for k, v in sorted(counts.items()) if v)
    state = inv.get("admission_state")
    ref = (inv.get("ref") or "")[:12]

    head = "ALLOWED " if inv.get("complete") else "REFUSED "
    line = (f"{head} {inv.get('action')}  "
            f"{inv.get('satisfied')}/{inv.get('required')} admission keys"
            f"{('  @ ' + ref) if ref else ''}"
            f"{('   ' + breakdown) if breakdown else ''}")
    lines = [line]

    if state == "UNSET":
        lines.append("  ⚠⚠ NO ADMISSION SET NAMED — nothing said what gates this action, "
                     "which is not the same as nothing being required. REFUSED.")
    elif state == "EMPTY":
        lines.append("  ⚠⚠ ADMISSION SET IS EMPTY — this action was admitted WITHOUT any "
                     "verdict gating it. Legitimate before emitters land; it must not be "
                     "read as 'the gate passed'.")

    not_gating = inv.get("registered_not_admitting") or []
    if not_gating:
        shown = ", ".join(not_gating[:8]) + ("…" if len(not_gating) > 8 else "")
        lines.append(f"  not gating {inv.get('action')}: {len(not_gating)} registered "
                     f"type(s) — {shown} (promote in the admission set)")

    if inv.get("complete"):
        return "\n".join(lines)

    for status in ("MISSING", "STALE", "UNDECIDED", "FAIL"):
        rows = [r for r in inv.get("rows", []) if r.get("status") == status and r.get("gating")]
        if not rows:
            continue
        for family in ("mechanical", "review"):
            names = sorted(r["step"] for r in rows if r.get("family") == family)
            if not names:
                continue
            # The remedies differ by an order of magnitude in cost, which is the
            # only reason the grouping exists.
            remedy = {"MISSING": ("python tools/verify/batch.py precommit"
                                  if family == "mechanical" else "that is an agent round"),
                      "STALE": "re-run — recorded against different bytes",
                      "UNDECIDED": "the ledger could not judge it — investigate",
                      "FAIL": "fix it"}[status]
            lines.append(f"  {status:9} {family:10} {', '.join(names)}"
                         f"      INSTEAD: {remedy}")
    return "\n".join(lines)
