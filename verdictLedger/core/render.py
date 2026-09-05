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
    elif how in ("signature", "override", "delegated") and decided.get("who"):
        tally = f" {decided['who']}"

    rev = record.get("revision", 0)
    # ⚠ A key regraded four times must not read like one that passed cleanly.
    revision = f"  rev={rev}" if rev else ""

    waited = (record.get("cost") or {}).get("lock_wait_seconds")
    edge = f"  ⚠edge-condition lock_wait={waited}s" if waited else ""

    # ⚠⚠ A CAPPED PASS MUST NOT LOOK LIKE A CLEAN ONE. This is the render half of
    # V18: the verdict admits, so everything downstream treats it as SATISFIED, and
    # the ONE place a human reads the row is here. Without this the two states are
    # indistinguishable at exactly the moment someone is deciding whether to trust it.
    n = len(record.get("outstanding") or [])
    carried = f"  ⚠{n} outstanding" if n else ""

    reason = record.get("reason") or ""
    return (f"{record.get('verdict', '?'):9}{carried} {record.get('step', '?')}  "
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

    # ⚠⭐ A GREEN KEY OVER A NARROWED SCOPE. Measured 2026-08-23: a step that examined
    # ONE file out of 201 still read SATISFIED, because a path with no record for that
    # step counted as neither covered nor stale and so was not counted at all.
    #
    # ⚠⚠ THIS SITS BEFORE THE `complete` EARLY RETURN ON PURPOSE. A COMPLETE inventory
    # over a narrowed scope is the only case where this warning is load-bearing — an
    # incomplete one already refuses. Printing it only on failures would hide it in
    # exactly the situation it exists for.
    #
    # ⚠ Reported, NOT blocking. Making it block would refuse every push until every
    # step covers every in-scope path, and that is a policy decision rather than a
    # side effect of a bug fix.
    thin = [row for row in inv.get("rows") or []
            if row.get("gating") and row.get("subjects_unexamined")]
    if thin:
        worst = sorted(thin, key=lambda x: -x["subjects_unexamined"])[:4]
        lines.append("  ⚠ NARROWED COVERAGE — examined fewer paths than are in scope: "
                     + ", ".join(f"{w['step']} {w['scope'] - w['subjects_unexamined']}"
                                 f"/{w['scope']}" for w in worst)
                     + (f" (+{len(thin) - 4} more)" if len(thin) > 4 else ""))

    # ⚠⭐ THE SYMMETRIC ALARM. Also before the `complete` early return: an undeclared
    # switch or a too-narrow scope shows up on a GREEN inventory by definition, since
    # the paths involved are covered -- they are simply not accounted for.
    unscoped = inv.get("unscoped") or []
    if unscoped:
        lines.append("  ⚠ EXAMINED BUT UNSCOPED — recorded, yet outside the declared "
                     "scope and not a declared switch: "
                     + ", ".join(unscoped[:4])
                     + (f" (+{len(unscoped) - 4} more)" if len(unscoped) > 4 else ""))

    # ⚠⭐ THE THIRD MEMBER OF THAT FAMILY, and it lands here for the identical reason: a
    # narrowed row is SATISFIED by definition, so it can ONLY ever appear on an inventory
    # that is otherwise green. Printing it after the early return would print it never.
    #
    # ⭐⭐ NARROWED-CLEAN IS NOT CLEAN. The covering record BLOCKS — it indicted other paths
    # at this step — and the reason this scope passes is that none of those paths are in it.
    # That is a correct result and a materially different one from "a checker looked at this
    # and was happy", which is what a bare SATISFIED says. `canpush` already refuses the same
    # collapse one level up ("whether the range was clean or merely forgiven is the exact
    # collapse this gate exists to prevent"); forgiveness is this operation applied to a
    # commit, and the argument was only ever surfaced for the outer half.
    #
    # ⚠ REPORTED, NOT BLOCKING — same call as NARROWED COVERAGE above. The narrowing is the
    # designed behaviour; a reader being unable to SEE it was the defect.
    narrowed = [row for row in inv.get("rows") or []
                if row.get("gating") and row.get("narrowed_from")]
    if narrowed:
        shown = ", ".join(f"{r['step']} (from {r['narrowed_from']})" for r in narrowed[:4])
        lines.append(f"  ⚠ NARROWED INDICTMENT — {len(narrowed)} row(s) pass because the "
                     f"covering record indicts OTHER paths, not because it was clean: "
                     + shown
                     + (f" (+{len(narrowed) - 4} more)" if len(narrowed) > 4 else ""))

    if inv.get("complete"):
        return "\n".join(lines)

    for status in ("MISSING", "STALE", "LEGACY_IDENTITY", "UNDECIDED", "FAIL"):
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
                      "LEGACY_IDENTITY": ("re-record — written under the superseded "
                                          "`sha256` subject scheme, not comparable"),
                      "UNDECIDED": "the ledger could not judge it — investigate",
                      "FAIL": "fix it"}[status]
            lines.append(f"  {status:9} {family:10} {', '.join(names)}"
                         f"      INSTEAD: {remedy}")
    return "\n".join(lines)
