"""Declared RETURN shapes for reservoirSearch.

`ok` is the only required key: `_guard` puts it on every path. A refusal travels as
`isError: true` with JSON in `content` and no `structuredContent`, so it is never validated
against these.
"""

from __future__ import annotations

from typing import Any, TypedDict


class Result(TypedDict):
    ok: bool


class SearchResult(Result, total=False):
    total: int
    truncated: int
    results: list[dict[str, Any]]
    index: dict[str, Any]


class PackageResult(Result, total=False):
    requested: str
    key: str
    resolved_alias: bool
    metadata: dict[str, Any]
    latest: dict[str, Any]
    versions_total: int
    versions: list[dict[str, Any]]
    versions_truncated: int
    builds_total: int
    builds_latest: list[dict[str, Any]]
    readme_note: str
    index: dict[str, Any]


class DependentsResult(Result, total=False):
    package: str
    key: str
    direct: int
    transitive: int
    total: int
    truncated: int
    results: list[dict[str, Any]]
    scope: str
    index: dict[str, Any]


class BuildsOnResult(Result, total=False):
    toolchain: str
    total: int
    truncated: int
    results: list[dict[str, Any]]
    scope: str
    index: dict[str, Any]


class ToolchainsResult(Result, total=False):
    toolchains: list[dict[str, Any]]
    index: dict[str, Any]


class StatusResult(Result, total=False):
    root: str
    loaded_at: str
    packages: int
    aliases: int
    skipped: int
    load_seconds: float
    reloads: int
    skipped_entries: list[dict[str, Any]]
    unresolved_dependency_entries: int
    freshness: str
