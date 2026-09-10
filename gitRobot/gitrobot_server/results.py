"""Declared RETURN shapes for gitRobot, so a caller need not parse a blob to read a result.

⚠⚠ MEASURED, NOT INVENTED. The read shapes were taken off live responses from the running
server on 2026-09-06; the mutating shapes were read off `_receipt` and its callers in
`core/engine.py`, because calling `commit` or `push` to discover a shape is exactly the mistake
that put a probe verdict in the ledger and blocked a tag.

⭐ `CLAUDE.md` states as a standard that every tool declares `outputSchema`. verdictLedger's 20
were paid off first; this is gitRobot's 22.

⚠⚠ `ok` IS THE ONLY REQUIRED KEY. `_guard` returns `{"ok": True, **result}` on success and
`{"ok": False, "error_type": …}` on a refusal, so `ok` is the one field on every path. Everything
else is optional and that is deliberate: most of these fields are conditional — `gates` appears
only when gates ran, `run_id` only on an async push, `worktree` only when one was targeted.
**Declaring a conditional field required publishes a contract the server breaks on ordinary
calls**, which is worse than declaring nothing.

⚠ THE REFUSAL SHAPE IS NOT DESCRIBED HERE. A refusal travels as `isError: true` plus JSON in
`content` — carrying `error_type`, `error`, and for a `RefusalError` also `alternative` and
`refusal_id` — and `mcpcommon/iserror.py` deliberately attaches no `structuredContent` to it. A
refusal does not match a success schema and must never be validated against one.
"""

from __future__ import annotations

from typing import Any, TypedDict


class Result(TypedDict):
    """The one field present on every path, success or refusal."""
    ok: bool


class ReceiptResult(Result, total=False):
    """What every MEDIATED (Tier 2) operation returns — `_receipt` plus its per-tool extras.

    ⚠ `head`/`branch`/`tree` name the repository the operation ACTUALLY TOUCHED, not the main
    one. They are read from `target`, not `self.git` — a distinction that was wrong until
    2026-09-06 and made a `.claude-local` push report the main repo's HEAD.
    """
    op: str
    decision: str
    head: str
    branch: str
    tree: dict[str, Any]
    gates: list[dict[str, Any]]
    # -- per-tool extras, all conditional
    output: str
    # ⭐ WHAT THE CALLER NEEDS TO KNOW ABOUT `output`, BECAUSE IT IS BOUNDED. Added
    # 2026-09-09 with `_bound_receipt_output`. `output_bytes` prices the FULL text the
    # operation produced, NEVER the excerpt above it — the same rule `calllog.py` holds,
    # and the reason bounding is safe here at all. `output_truncated` says plainly
    # whether anything was cut, because a clipped output that renders like a complete
    # one is this project's recurring defect and would be worst in the record of what
    # an operation did.
    # ⚠ MEASURED: merge was returning 147,922 bytes to say "0 bad exit(s)".
    output_bytes: int
    output_truncated: bool
    # ⚠ `error` WAS RETURNED AND NEVER DECLARED — `stage` passes
    # `extra={"error": result.output}` and has since before this file existed. Declaring
    # it now rather than leaving a second raw-stdout field undocumented beside the one
    # that just got fixed; an understated contract costs more than a wrong one, because
    # nothing ever fails.
    error: str
    error_bytes: int
    error_truncated: bool
    exit_code: int
    args: list[str]
    worktree: str | None
    path: str
    linked: list[str]
    arc_state: dict[str, Any]
    recording_here_is_real: str
    subjects: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    inventory: str | None
    run_id: str
    state: str
    note: str


class ReadResult(Result, total=False):
    """An allow-listed read-only git command. No gate, no audit."""
    op: str
    args: list[str]
    worktree: str | None
    exit_code: int
    output: str


class StatusResult(Result, total=False):
    """⚠ `would_block_push` is TIP-SCOPED and must never be read as "the push will go" — see the
    tool docstring. `would_block_push_scope` and `range_question` exist to say so and must not be
    separated from it."""
    repo: str
    branch: str
    head: str
    tree: dict[str, Any]
    unpushed: int
    gates_available: bool
    inventory: dict[str, Any]
    would_block_push: list[Any]
    would_block_push_scope: str
    range_question: str


class PreflightStatusResult(Result, total=False):
    state: str
    head: str
    run_id: str
    ts: str
    gates: list[dict[str, Any]]
    # ⭐ A TIMEOUT IS NOT A VERDICT. Added 2026-09-07 after pre-push crossed 1800s and this
    # returned `state: "failed"` with the only evidence — exit 124 — buried in `gates[0].note`,
    # while the ledger said ALLOWED and the consumer's own prepush said PASS. A caller
    # branching on `state` read "the clock ran out" as "the gate refused you".
    # ⚠ `state` deliberately still says "failed"; changing a value a live consumer branches on
    # is coordinated, client-first, exactly as `isError` was. This is the discriminator beside it.
    failure_kind: str          # "timeout" | "verdict" — only when state == "failed"
    # ⚠ The budget, published because it is a BUILT-IN CONSTANT in core/gates.py that no caller
    # can otherwise read — and on `running` too, which is the state where waiting is the question.
    gate_timeout_seconds: dict[str, int]
    started_at: str
    started_pid: int
    note: str


class PushStatusResult(Result, total=False):
    state: str
    run_id: str
    branch: str
    head: str
    ts: str
    output: str | None


class AdmissionResult(Result, total=False):
    """The admission set alone. ~665 bytes against requirements()' 11,904.

    MEASURED 2026-09-08: of requirements(action='push'), `exclusion_rationale` is 9,463 bytes
    (79%) and `admitted` is 303 (2.5%). The consumer read only `admitted`, ~99 times, and had
    no way to ask for less. This is the field, plus a POINTER to where the rest lives rather
    than a copy of it.
    """
    action: str
    admitted: list[str]
    count: int
    registered_not_admitted: list[str]
    full_detail: str


class RequirementsResult(Result, total=False):
    """⚠ This is the ADMISSION SET (what must be GREEN), never the registry (what may be
    RECORDED). The two differ deliberately and by the same count — see the tool docstring."""
    action: str
    admitted: list[str]
    admitted_count: int
    registered_not_admitted: list[str]
    registry_unreadable: str | None
    exclusion_rationale: dict[str, Any]
    preconditions: list[str]
    order_of_operations: list[str]
    which_tool_answers_what: dict[str, Any]
    source: str


class ExplainResult(Result, total=False):
    refusal_id: str
    op: str
    args: list[str]
    what: str
    alternative: str
    ts: str
    found: bool


class HistoryResult(Result, total=False):
    count: int
    total: int
    path: str
    full: bool
    omitted: int
    note: str
    records: list[dict[str, Any]]


class VocabularyResult(Result, total=False):
    """The fleet vocabularies as data — the TOOL transport of `docs://*/vocabulary`.

    ⭐ THIS SHAPE MUST BE IDENTICAL ON EVERY SERVER THAT SERVES IT, and the conformance suite
    fails if the CONTENT diverges. What legitimately differs per server is the ENVELOPE: this
    file's servers stamp `ok` in `_guard`, and sjv does not stamp one at all. Copying a
    sibling's base class is how a contract gets published that the server breaks on every call.
    """

    names: list             # every published vocabulary name, regardless of `name`
    requested: Any          # the `name` asked for, or None for all four
    vocabularies: dict      # {vocabulary_name: {value: meaning}} — keys are STRINGS on the wire
    markdown: str           # the same render the resource serves, so both audiences agree
    error_type: str
    error: str
    satisfied_when: str
