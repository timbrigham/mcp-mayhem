"""Typed errors for gitRobot.

Every one of these becomes ``{ok: false, error_type, error}`` at the MCP surface —
never a transport crash, and never a bare string an agent has to pattern-match.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# The fleet vocabulary is defined ONCE at the repo root and imported, never restated. Measured
# 2026-09-08: this file and its sibling had diverged to share only `usage`, while
# mcpcommon/iserror.py read the field on every refusal from every server and owned none of it.
_root = _Path(__file__).resolve().parents[2]
if str(_root) not in _sys.path:
    _sys.path.insert(0, str(_root))
from mcpcommon.vocabulary import ERROR_TYPES as _ERROR_TYPES


def _kind(name):
    """The shared value, and a hard failure if this server invents one nobody published."""
    if name not in _ERROR_TYPES:
        raise AssertionError(
            "error_type %r is not in mcpcommon.vocabulary.ERROR_TYPES. Add it there so every "
            "server and every caller can enumerate it, rather than defining it here." % name)
    return name



class GitRobotError(Exception):
    """Base for everything this server raises deliberately."""

    error_type = _kind("gitrobot")


class RefusalError(GitRobotError):
    """A Tier 1 operation, or a Tier 2 operation whose precondition failed.

    Carries ``alternative`` — the thing the caller should do INSTEAD. A refusal
    that does not say what to do next is how bypasses get invented, so the
    alternative is a required constructor argument rather than a nicety, and
    ``refusal_id`` lets the caller pull the long form back out via ``explain``.
    """

    error_type = _kind("refusal")

    def __init__(self, message: str, *, alternative: str, refusal_id: str = ""):
        self.alternative = alternative
        self.refusal_id = refusal_id
        super().__init__(message)


class GateError(GitRobotError):
    """A blocking gate leg failed, so the mutation did not run."""

    error_type = _kind("gate")

    def __init__(self, message: str, *, phase: str, exit_code: int, output: str = ""):
        self.phase = phase
        self.exit_code = exit_code
        self.output = output
        super().__init__(message)


class RepoError(GitRobotError):
    """The configured repository is missing, is not a git repo, or git failed."""

    error_type = _kind("repo")


class ConfigError(GitRobotError):
    """This server's own configuration could not be read, or is invalid.

    NOT THE CALLER'S FAULT AND NOT AN UNCLASSIFIED FAULT, WHICH IS HOW EIGHT OF THESE
    REPORTED UNTIL 2026-09-10. Every admission-set problem -- file absent, unreadable,
    a bad `default`, a malformed entry list, a duplicate -- raised a bare `GitRobotError`
    and therefore travelled as `error_type: "gitrobot"`, whose own published meaning is
    "an unclassified gitRobot fault".

    So the single most consequential failure this server has -- it cannot read the file
    that decides what gates a push -- was indistinguishable on the wire from any
    unhandled internal fault. `iserror.py` and every consumer branch on that field.

    `config` already existed in `mcpcommon.vocabulary.ERROR_TYPES`, published and unused
    here: "the server's own configuration could not be read or is invalid. Nothing is
    judged until it is fixed." The value was available; nothing raised it.
    """

    error_type = _kind("config")


class UsageError(GitRobotError):
    """Malformed arguments — an unknown read op, an empty path list, and so on."""

    error_type = _kind("usage")
