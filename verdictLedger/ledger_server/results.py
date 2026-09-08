"""Declared RETURN shapes, so a caller does not have to parse a blob to learn what came back.

⚠⚠ EVERY SHAPE HERE WAS MEASURED, NOT INVENTED. Each was read off an actual response from the
running server on 2026-09-06 (or, for the five writers that cannot be safely called, off the
`return` statements in `core/ledger.py`). A hand-written schema is a claim about behaviour, and a
wrong one is worse than none — it publishes a contract the response violates, and the client that
suffers is the one that actually validates.

⭐ WHY THIS EXISTS AT ALL. `CLAUDE.md` states as a standard that every tool "declares
`outputSchema` and returns `structuredContent`", and until now ZERO of 81 tools did — every one
was annotated `-> dict`, which FastMCP cannot turn into a schema. That line was marked ⛔ in
CLAUDE.md as a rule the code did not satisfy, and ratcheted so it could not drift unnoticed. This
is the verdictLedger half of paying it off.

⚠⚠ `ok` IS THE ONLY REQUIRED KEY, AND EVERY OTHER FIELD IS OPTIONAL, DELIBERATELY. `_guard`
returns `{"ok": True, **result}` on success and `{"ok": False, "error_type": ...}` on a refusal,
so `ok` is the one field present on every path. Many of the rest are CONDITIONAL — `status`
carries `coverage_note` only when coverage is unenforced, `crossref` carries `no_data` only when
there is none. Declaring those required would publish a contract the server breaks on ordinary
calls. **A schema that over-promises is a worse artifact than one that under-promises**, because
the first fails on correct behaviour and the second merely says less.

⚠ THE REFUSAL SHAPE IS NOT DESCRIBED HERE AND MUST NOT BE. A refusal travels as `isError: true`
plus JSON in `content`, and `mcpcommon/iserror.py` deliberately attaches NO `structuredContent`
to it — a refusal does not match the success schema and should never be validated against one.
"""

from __future__ import annotations

from typing import Any, TypedDict


class Result(TypedDict):
    """The one field every tool returns on every path.

    ⚠ Do not add to this. A key that is not on the success AND refusal paths belongs in a
    specific result below, not in the base that claims to be universal.
    """
    ok: bool


# -- writes -------------------------------------------------------------------
# ⚠ Measured from `core/ledger.py` rather than by calling: appending a probe to test a shape is
# exactly the mistake that put `rely@def0143…#0` in the stream and blocked a tag.

class AppendResult(Result, total=False):
    id: str
    appended: bool
    reason: str          # only on the dedupe path: "identical record already present"


class GenesisResult(AppendResult, total=False):
    commit: str


# -- reads --------------------------------------------------------------------

class GetResult(Result, total=False):
    record: dict[str, Any] | None
    found: bool


class FindResult(Result, total=False):
    count: int
    returned: int
    records: list[dict[str, Any]]


class ValidateResult(Result, total=False):
    errors: list[str]
    error_type: str      # present only when there ARE violations — see Ledger.validate


class RenderResult(Result, total=False):
    line: str
    found: bool


class RequirementsResult(Result, total=False):
    action: str
    types: dict[str, Any]


class PolicyResult(Result, total=False):
    policy: dict[str, Any]
    config_sha: str
    actions: list[str]
    min_passes: int
    max_depth: int
    genesis: Any
    defaulted: list[dict[str, Any]]
    unpinned_modules: list[dict[str, Any]]
    # ⭐ Steps with no declared `min_coverage` — no bar on how much of their scope they must
    # examine. `coverage.require_complete` is ONE switch for every step: false leaves 823
    # in-scope paths under green rows, true blocks until a full sweep runs. This is the
    # per-step bar that lets that flip become a ratchet.
    coverage_unbarred: list[dict[str, Any]]
    min_coverage: dict[str, Any]
    policy_path: str
    required_path: str
    config_source: str


class StatusResult(Result, total=False):
    records: int
    last_append: str
    schema: str
    invalid_appends: int
    # ⭐ Per-step refusals, keyed (step, rule) with counts and both timestamps. The
    # `invalid_appends` integer above is the same fact with no shape: it cannot say WHICH
    # step, WHICH rule, or WHEN, and a step whose record was refused rendered as MISSING —
    # indistinguishable from never having run.
    refusals: dict[str, Any]
    edge_conditions: int
    writable: bool
    problems: list[Any]
    healthy: bool
    config_ok: bool
    config_error: str | None
    config_sha: str
    policy_path: str
    required_path: str
    config_source: str
    coverage_enforced: bool | None
    coverage_note: str | None
    relaxations: list[str]
    undecided_steps: list[str]
    genesis: str


class InventoryResult(Result, total=False):
    ref: str
    action: str
    admission_state: str
    admitted: list[str]
    required: int
    satisfied: int
    unexamined: int
    unscoped: list[Any]
    dead_patterns: list[Any]
    needs_rerun: list[Any]
    missing: int
    stale: int
    evidence_moved: list[Any]
    outstanding: int
    legacy_identity: int
    undecided: int
    failed: int
    not_applicable: int
    complete: bool
    registered_not_admitting: list[str]
    # ⭐ Steps whose `approved_modules` no longer matches the module's blob in THIS tree.
    # V16c refuses these at append; this names the interval BEFORE that, which is however
    # long it takes the step to next record — measured 2026-09-07 at three commits for a
    # step outside the precommit suite.
    stale_pins: list[dict[str, Any]]
    # ⭐ The frozen convergence bar, beside `complete`. `complete: true` is a claim about a
    # SCOPE — if the registry moved since the run was frozen it is true about a different one.
    # Carried here because gitRobot's status() embeds an inventory, not a progress, so a
    # broken bar reached nobody: 19/19 green with `held: false` unmentioned.
    bar: dict[str, Any]
    how_breakdown: dict[str, Any]
    rows: list[dict[str, Any]]
    config_sha: str
    line: str


class ProgressResult(Result, total=False):
    action: str
    complete: bool
    bar: dict[str, Any]
    satisfied: int
    gating: int
    config_sha: str
    blocking: list[Any]
    green: list[Any]
    numbers: dict[str, Any]
    unexamined_total: int
    outstanding_total: int
    ref: str


class CoverageGapResult(Result, total=False):
    action: str
    steps: list[Any]
    total_missing: int
    complete_steps: list[str]
    tracked: int
    ref: str


class HealPlanResult(Result, total=False):
    action: str
    ref: str
    complete: bool
    failing_but_not_gating: list[Any]
    auto: list[Any]
    agent: list[Any]
    blocked: list[Any]
    summary: dict[str, Any]


class CoverageResult(Result, total=False):
    tracked: int
    examined: int
    uncovered: int
    paths: list[str]
    note: str | None


class CanPushResult(Result, total=False):
    allowed: bool
    range: str
    commits_in_range: int
    blocking_count: int
    push_bar: str
    push_bar_source: str
    forgiven: list[Any]
    forgiven_count: int
    tip: str
    commits_below_audit_floor: int
    audit_floor: str
    audit_note: str | None
    admitted: list[str]
    admission_state: str
    not_gating: list[Any]
    commits: list[dict[str, Any]]
    missing: list[Any]
    stale: list[Any]
    failed: list[Any]
    legacy: list[Any]
    config_sha: str
    # ⭐ Which FAMILY of admitted step has the CHANGED paths in scope. Added 2026-09-07 after
    # a push read ALLOWED 19/19 while zero review-family steps covered any of its 11 files —
    # `adversary` and `editorial` were green over a scope with no overlap at all. Reported,
    # never blocking: whether that refuses a push belongs to the admission set.
    # ⚠ `resolved: false` when the base could not be read — an unresolvable base is NOT
    # "nothing changed", and it carries no counts rather than counts of zero.
    witness: dict[str, Any]
    line: str


class CrossrefResult(Result, total=False):
    no_data: bool
    repo: str
    head: str
    genesis_floor: str
    range: str
    commits_audited: int
    commits_below_floor: int
    floor_note: str
    truncated: bool
    truncation_note: str
    admission: Any
    completeness_note: str
    counts: dict[str, Any]
    findings: list[Any]


class SignalsResult(Result, total=False):
    records_considered: int
    note: str | None
    families: dict[str, Any]
