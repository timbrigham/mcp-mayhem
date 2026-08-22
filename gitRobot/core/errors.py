"""Typed errors for gitRobot.

Every one of these becomes ``{ok: false, error_type, error}`` at the MCP surface —
never a transport crash, and never a bare string an agent has to pattern-match.
"""

from __future__ import annotations


class GitRobotError(Exception):
    """Base for everything this server raises deliberately."""

    error_type = "gitrobot"


class RefusalError(GitRobotError):
    """A Tier 1 operation, or a Tier 2 operation whose precondition failed.

    Carries ``alternative`` — the thing the caller should do INSTEAD. A refusal
    that does not say what to do next is how bypasses get invented, so the
    alternative is a required constructor argument rather than a nicety, and
    ``refusal_id`` lets the caller pull the long form back out via ``explain``.
    """

    error_type = "refusal"

    def __init__(self, message: str, *, alternative: str, refusal_id: str = ""):
        self.alternative = alternative
        self.refusal_id = refusal_id
        super().__init__(message)


class GateError(GitRobotError):
    """A blocking gate leg failed, so the mutation did not run."""

    error_type = "gate"

    def __init__(self, message: str, *, phase: str, exit_code: int, output: str = ""):
        self.phase = phase
        self.exit_code = exit_code
        self.output = output
        super().__init__(message)


class RepoError(GitRobotError):
    """The configured repository is missing, is not a git repo, or git failed."""

    error_type = "repo"


class UsageError(GitRobotError):
    """Malformed arguments — an unknown read op, an empty path list, and so on."""

    error_type = "usage"
