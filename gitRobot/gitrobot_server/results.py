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
    # ⚠ present on the preflight receipt paths too — see PreflightStatusResult.passed_prices
    passed_prices: str
    # ⭐⭐ WHAT THE LEDGER SAYS AT THIS TIP — the second half of Tim's 2026-09-26 ruling, and a
    # SEPARATE FIELD from `passed` on purpose. `passed` is a value the consumer branches on, so
    # changing its meaning is a coordinated client-first change; this answers the question a
    # caller was actually asking without touching the one they dispatch on.
    # ⚠ `state` is SET / EMPTY / UNSET / UNKNOWN, and UNKNOWN means the ledger could not be read —
    # never a pass. `would_push_be_allowed_at_this_tip` is None in that case rather than a boolean,
    # because True and False both claim knowledge nobody has.
    # ⛔ STILL TIP-SCOPED. Consulting the admission set closed one of the two gaps: a push
    # publishes a RANGE, and an intermediate can block one this field calls clear (measured
    # 2026-09-05, eleven of them after a green preflight). `scope` says so on every payload.
    admission_at_tip: dict[str, Any]
    note: str
    # ⭐ WHICH REPOSITORY A PUSH TARGETED, BY URL. `branch` says where ON the remote; this says
    # WHICH remote, and `origin` is a local alias a `set-url` re-points silently. On EVERY push
    # receipt including the failed ones — a re-pointed remote fails looking like something else
    # ("src refspec does not match any"), so naming it only on success documents the easy case.
    # ⚠ "unresolved" when it could not be read, never absent: an absent field reads as "nothing
    # to say", and here the thing to say is that we do not know where this went.
    remote_url: str


class ReadResult(Result, total=False):
    """An allow-listed read-only git command. No gate, no audit."""
    op: str
    args: list[str]
    worktree: str | None
    exit_code: int
    output: str


class FlightRow(TypedDict, total=False):
    """One long-running operation's check-in summary, as `status.in_flight` reports it.

    ⚠⚠ `cap_seconds` IS NOT ONE NUMBER ACROSS THE TWO ROWS AND MUST NOT BE READ AS ONE. A
    preflight is bounded by the pre-push GATE PHASE (1800s); a push is bounded by the whole
    `git push` subprocess (3600s), hook and network together. `cap_prices` says which, on every
    row, because a caller comparing an elapsed time against the wrong ceiling is this repo's
    founding defect in its cheapest form.

    ⛔ `stuck: false` IS NOT "FINE". It is false for a concluded run, for a run inside its
    budget, AND for a run whose age could not be established — `note` distinguishes the last
    one, and `state` is the field that says what is actually happening.
    """
    state: str
    run_id: str | None
    started_at: str | None
    elapsed_seconds: int | None
    stuck: bool
    cap_seconds: int
    cap_prices: str
    detail_via: str
    note: str


class InFlight(TypedDict, total=False):
    """Both long-running operations, or — if the audit could not be read — `error` and `note`
    INSTEAD of them. ⚠ An absent row is never "nothing is running"; see the `error` note."""
    preflight: FlightRow
    push: FlightRow
    error: str
    note: str


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
    # ⭐ THE CHECK-IN, added 2026-09-21. Delegated from preflight_status()/push_status() — a
    # SUMMARY of each, deliberately without the gate transcripts, since `status` is documented
    # cheap. `detail_via` on each row names the tool holding the rest.
    in_flight: InFlight


class PreflightStatusResult(Result, total=False):
    state: str
    # ⛔⛔ WHAT `state: "passed"` PRICES, AND WHAT IT DOES NOT. Added 2026-09-26, the THIRD time
    # this surface produced a false green: the consumer read PASSED 21/21 and can_push REFUSED
    # the same range on a stale admitted step. `preflight` runs the GATE PIPELINE and has never
    # consulted the admission set — so `passed` is not a prediction that the push is allowed, and
    # the `21/21` is gates rather than admission keys. ⚠ Same field on the `preflight()` returns,
    # from ONE constant (`engine.PREFLIGHT_SCOPE`), because a scope warning on one of two
    # surfaces is the half-applied guard that shipped once already.
    passed_prices: str
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
    # ⚠ TWO DIFFERENT INSTANTS, TWO NAMES, NEVER ONE. `ts` is when the run CONCLUDED and appears
    # on the terminal states; `started_at` is when it BEGAN and appears on `running` and `died`.
    # The WHEN-vs-WHOSE collapse this repo keeps finding is the same shape as a start stamp and
    # a finish stamp sharing a key.
    ts: str
    # ⭐ Added 2026-09-21: without it a caller polling `running` could not tell a 30-second push
    # from a 40-minute one, which is the state where elapsed time IS the question.
    # `preflight_status` had published it since it was written; this one had not.
    started_at: str
    cap_seconds: int
    # ⭐ WHICH REPOSITORY, BY URL. `branch` says where on the remote; this says WHICH remote,
    # and `origin` is a local alias that a `set-url` re-points silently. Read from the STARTED
    # row rather than resolved again, so it prices the push that happened.
    remote_url: str
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
    requested: Any          # the `name` asked for, or None for every published vocabulary
    vocabularies: dict      # {vocabulary_name: {value: meaning}} — keys are STRINGS on the wire
    markdown: str           # the same render the resource serves, so both audiences agree
    error_type: str
    error: str
    satisfied_when: str
