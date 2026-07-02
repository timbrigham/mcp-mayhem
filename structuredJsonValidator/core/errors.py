"""Typed errors for the SSOT core."""

from __future__ import annotations


class ValidationError(Exception):
    """Raised when a document fails structural or business validation.

    Carries the *full* list of violations (the validator never stops at the
    first one) so callers can report every problem at once.
    """

    def __init__(self, violations: list[str]):
        self.violations = list(violations)
        super().__init__(
            f"{len(self.violations)} validation violation(s):\n  - "
            + "\n  - ".join(self.violations)
        )


class IntegrityError(Exception):
    """Raised when the on-disk file hash does not match the last audit hash.

    Means the file was edited out of band, bypassing the handler. This is
    detection, not prevention (spec §6/§10) — halt and alarm.
    """


class OperationError(Exception):
    """Raised when an operation is unknown or its parameters are malformed."""
