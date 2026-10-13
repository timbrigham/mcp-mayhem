"""Business rules for the ``incidents`` collection.

An incident is an action a tool ALLOWED that was later found harmful. The register is the
observation source for measuring how well guards track what agents actually do: a refusal log
only ever shows patterns that are already guarded, so unguarded ones surface only here.

Rules beyond the schema:
  * ids are unique;
  * a ``guarded`` entry names all three of ``guard_commit``, ``regression_test`` and
    ``guarded_at``, and an entry that is not guarded names none of them. A guard claimed without
    its commit and test is a claim nobody can check;
  * ``pattern_id`` follows the declared pattern rule (below), so pattern counts from two
    analyses are comparable.

Pattern rule, version 1: ``<tool>.<operation>.<shape>`` in lower case, dot-separated, where
``shape`` names the risky form of the operation (e.g. ``gitrobot.push.refspec-force``). Two
incidents share a pattern exactly when the same guard would stop both.

Only the SHAPE of a pattern id is enforced here. Whether two incidents really share a guard is
a judgement the person recording them makes; no code can check it, so the rule's version is
recorded and pattern counts are comparable only under the same version.

Time order: when known, ``observed_at`` <= ``detected_at`` <= ``guarded_at``.
"""

from __future__ import annotations

PATTERN_RULE = "1"
GUARD_FIELDS = ("guard_commit", "regression_test", "guarded_at")


def _t(value: str):
    from datetime import datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate(document: dict) -> list[str]:
    violations: list[str] = []
    if document.get("pattern_rule") != PATTERN_RULE:
        violations.append(f"pattern_rule must be {PATTERN_RULE!r} (the rule this code applies), "
                          f"got {document.get('pattern_rule')!r}")
    seen: dict[str, int] = {}
    for idx, inc in enumerate(document.get("entries", [])):
        iid = inc.get("id")
        if iid in seen:
            violations.append(f"entries[{idx}]: duplicate id {iid!r} (first at entries[{seen[iid]}])")
        else:
            seen[iid] = idx
        named = [f for f in GUARD_FIELDS if inc.get(f) is not None]
        if inc.get("status") == "guarded" and len(named) != len(GUARD_FIELDS):
            missing = [f for f in GUARD_FIELDS if f not in named]
            violations.append(f"entries[{idx}] ({iid}): status 'guarded' requires "
                              f"{', '.join(GUARD_FIELDS)}; missing {', '.join(missing)}")
        if inc.get("status") != "guarded" and named:
            violations.append(f"entries[{idx}] ({iid}): status {inc.get('status')!r} must not name "
                              f"{', '.join(named)}; use set_guarded to record a guard")
        obs, det, grd = inc.get("observed_at"), inc.get("detected_at"), inc.get("guarded_at")
        if obs and det and _t(obs) > _t(det):
            violations.append(f"entries[{idx}] ({iid}): observed_at is after detected_at")
        if grd and det and _t(grd) < _t(det):
            violations.append(f"entries[{idx}] ({iid}): guarded_at is before detected_at")
        parts = str(inc.get("pattern_id", "")).split(".")
        if len(parts) != 3:
            violations.append(f"entries[{idx}] ({iid}): pattern_id must be <tool>.<operation>.<shape> "
                              f"under pattern rule {PATTERN_RULE}, got {inc.get('pattern_id')!r}")
    return violations
