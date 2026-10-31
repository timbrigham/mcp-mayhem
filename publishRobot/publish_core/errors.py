"""Typed errors for publishRobot.

Every one of these becomes ``{ok: false, error_type, error, satisfied_when}`` at the MCP
surface. ``satisfied_when`` is required, never optional: a refusal that names only the failure
describes bytes the next attempt will not carry (CLAUDE.md, "a refusal names the success
condition").
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# The fleet vocabulary is defined ONCE at the repo root and imported, never restated.
_root = _Path(__file__).resolve().parents[2]
if str(_root) not in _sys.path:
    _sys.path.insert(0, str(_root))
from mcpcommon.vocabulary import ERROR_TYPES as _ERROR_TYPES, REFUSAL_CLASSES as _REFUSAL_CLASSES


def _kind(name):
    """The shared value, and a hard failure if this server invents one nobody published."""
    if name not in _ERROR_TYPES:
        raise AssertionError("error_type %r is not in mcpcommon.vocabulary.ERROR_TYPES" % name)
    return name


class PublishError(Exception):
    """Base for everything this server raises deliberately."""

    error_type = _kind("unhandled")

    def __init__(self, what: str, satisfied_when: str):
        if not (satisfied_when or "").strip():
            raise AssertionError("a publishRobot error must say what would satisfy it")
        self.satisfied_when = satisfied_when
        super().__init__(what)


class UsageError(PublishError):
    """The call was malformed: an unknown action, a missing field, an unknown queue id."""

    error_type = _kind("usage")


class ConfigError(PublishError):
    """The allow-list or the tracker could not be read. Nothing posts until it is fixed."""

    error_type = _kind("config")


class UnavailableError(PublishError):
    """The queue is locked by the other process. Transient: retrying is correct."""

    error_type = _kind("unavailable")


class RefusalError(PublishError):
    """A rule stopped the call: a repo off the allow-list, approved bytes that differ from the
    queued bytes, an entry already posted."""

    error_type = _kind("refusal")

    def __init__(self, what: str, satisfied_when: str, *, refusal_class: str):
        if refusal_class not in _REFUSAL_CLASSES:
            raise AssertionError("refusal_class %r is not published" % refusal_class)
        self.refusal_class = refusal_class
        super().__init__(what, satisfied_when)
