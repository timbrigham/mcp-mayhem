"""Declared RETURN shapes for publishRobot.

`ok` is the only required key: `_guard` puts it on every path. Everything else is conditional,
and declaring a conditional field required publishes a contract the server breaks on ordinary
calls. A refusal travels as `isError: true` with JSON in `content` and no `structuredContent`,
so it is never validated against these.
"""

from __future__ import annotations

from typing import Any, TypedDict


class Result(TypedDict):
    ok: bool


class QueueResult(Result, total=False):
    op: str
    decision: str
    id: str
    sha256: str
    state: str
    payload: dict[str, Any]
    next: str


class ApproveResult(Result, total=False):
    op: str
    decision: str
    id: str
    sha256: str
    # `url`/`number` on success; `error` when GitHub refused, including the half of a two-step
    # action (close-with-comment, labels) that did land.
    result: dict[str, Any]
    # None when nothing was posted. `written: false` means the post HAPPENED and only the
    # tracker line failed; the line is returned so it can be added by hand.
    tracker: dict[str, Any] | None


class WithdrawResult(Result, total=False):
    op: str
    decision: str
    id: str


class PendingResult(Result, total=False):
    entries: list[dict[str, Any]]
    count: int


class HistoryResult(Result, total=False):
    rows: list[dict[str, Any]]
    total: int
