"""Typed errors. Every one becomes ``{ok: false, error_type, error}`` at the MCP
surface — never a transport crash, never a bare string a caller has to parse.

⚠ The distinctions here are load-bearing, not cosmetic. If "the ledger could not
take it" and "the ledger rejected it" look alike, a caller under pressure retries
its way past a validation rule — which is the adversary this server exists to
stop. ``ValidationFailure`` is terminal by construction; ``Unavailable`` is the
only one anything may retry.
"""

from __future__ import annotations


class LedgerError(Exception):
    error_type = "ledger"


class ValidationFailure(LedgerError):
    """A record broke one or more of V1–V14. NEVER retried.

    Carries every violation, not just the first — a caller fixing one rule at a
    time across three round trips is a caller that gives up and works around it.
    """

    error_type = "validation"

    def __init__(self, violations: list[str]):
        self.violations = list(violations)
        super().__init__(f"{len(self.violations)} violation(s): " + "; ".join(self.violations))


class ConfigError(LedgerError):
    """Policy or the type registry is missing, unreadable, or schema-invalid.

    ⚠ This must never degrade to a built-in default. A built-in default is a
    second copy of the policy, and the weaker of the two is the copy nobody
    notices. An unloadable config serves UNDECIDED and refuses every gated action.
    """

    error_type = "config"


class Unavailable(LedgerError):
    """The store could not be written — a wedged writer, a full disk, a lock that
    never came free. The ONLY retryable class, and even then boundedly."""

    error_type = "unavailable"


class UsageError(LedgerError):
    """Malformed arguments: an unknown action, a bad limit, a missing id."""

    error_type = "usage"
