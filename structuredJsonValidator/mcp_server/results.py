"""Declared RETURN shapes for sjv, so a caller need not parse a blob to read a result.

⚠⚠ MEASURED, NOT INVENTED — and measuring changed the design. The read shapes were taken off
live responses on 2026-09-06; the write shape off `core/engine.py`'s `apply`/`apply_store`.

⛔⛔ THERE IS NO UNIVERSAL `ok` HERE, UNLIKE THE OTHER TWO SERVERS. verdictLedger and gitRobot
route every tool through a `_guard` that stamps `{"ok": True, …}`, so `ok` is on every path and
is declared REQUIRED there. sjv's READS do not: `find(count_only=True)` returns `{"count": …}`,
`validate` returns `{"valid", "violations"}`, `history` returns `{"records"}` — no `ok` at all.
Only the WRITES carry it, via `_write`.

⭐ That was found by calling the tools rather than by assuming the fleet was uniform. Declaring
`ok` required here — the obvious move after doing the other two servers — would have published a
contract that three read tools break on every successful call. **A schema copied from a sibling
is a claim about THIS server that was measured on a DIFFERENT one.**

⚠ So every field here is optional. That says less than the other two modules, and it says only
true things.

⚠ THE REFUSAL SHAPE IS NOT DESCRIBED. Enforcement failures come back as
`{ok: false, error_type, error}` — plus `violations`/`violation_count` for a validation failure —
and `mcpcommon/iserror.py` attaches no `structuredContent` to a refusal.
"""

from __future__ import annotations

from typing import Any, TypedDict


class WriteResult(TypedDict, total=False):
    """What every §9 write verb returns through `_write` / `_write_store`.

    ⚠ `resulting_sha256` is the integrity chain: the audit records it after each op, and the
    next op verifies against it. A write that reports one is a write that extended the chain.
    """
    ok: bool
    op: str
    collection: str
    entries_touched: list[str]
    resulting_sha256: str
    # -- op-specific extras, all conditional
    id: str
    ids: list[str]
    claim_id: str
    created: list[str]
    removed: list[str]
    changed: int
    note: str


class GetResult(TypedDict, total=False):
    found: bool
    entry: dict[str, Any] | None


class FindResult(TypedDict, total=False):
    """⚠ `count_only=True` returns ONLY `count` — no `entries`, no `returned`. That is the
    cheapest form and the reason this whole TypedDict is optional-only."""
    count: int
    returned: int
    entries: list[dict[str, Any]]


class HistoryResult(TypedDict, total=False):
    records: list[dict[str, Any]]


class ViewResult(TypedDict, total=False):
    ok: bool
    collection: str
    kind: str
    text: str


class ValidateResult(TypedDict, total=False):
    """⚠ `valid`, not `ok`. A validation answer is not a call outcome, and conflating them would
    make a successful call reporting an invalid store look like a failed call."""
    valid: bool
    violations: list[str]


class VerifyIntegrityResult(TypedDict, total=False):
    ok: bool
    hash: str


class CheckHeadResult(TypedDict, total=False):
    # `ok` is the CALL status. `matches` is the FINDING — they were the same key until
    # 2026-09-10, and the domain value won by dict-spread ordering, which made a successful
    # call that found drift look like a refused one.
    ok: bool
    matches: bool
    # ⚠ The RESOLVED ABSOLUTE root, never the string the caller passed. A relative root in a
    # response cannot be interpreted by anyone who does not know the server's cwd.
    root: str
    note: str
    tier: str
    checked: int
    resolved: int
    unresolvable_files: int
    duplicate_live_names: int
    missing_files: list[Any]
    missing_files_by_file: dict[str, Any]
    duplicates: list[Any]


class ExportResult(TypedDict, total=False):
    ok: bool
    collections: dict[str, Any]
    text: str
    count: int


class VocabularyResult(TypedDict, total=False):
    """The fleet vocabularies as data — the TOOL transport of `docs://sjv/vocabulary`.

    ⛔ NOTE THE BASE CLASS: `TypedDict`, not this file's `Result`, and NO `ok` on success.
    sjv does not stamp `ok` on reads — `validate` returns {valid, violations},
    `find(count_only)` returns {count} — and CLAUDE.md names copying a sibling's base class
    here as the way to publish a contract three read tools break on every successful call.
    `ok` appears ONLY on the refusal branch, where it is false beside an `error_type`.

    ⭐ The vocabulary CONTENT is identical across all three servers and the conformance suite
    fails if it diverges. Only the ENVELOPE differs, and it differs because these servers
    genuinely differ.
    """

    names: list             # every published vocabulary name, regardless of `name`
    requested: Any          # the `name` asked for, or None for all four
    vocabularies: dict      # {vocabulary_name: {value: meaning}} — keys are STRINGS on the wire
    markdown: str           # the same render the resource serves, so both audiences agree
    ok: bool                # REFUSAL ONLY, and always false when present
    error_type: str
    error: str
    satisfied_when: str
