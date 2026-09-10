"""Typed errors for the SSOT core.

BOUND TO THE FLEET VOCABULARY, AND IT WAS THE LAST SERVER THAT WAS NOT. Measured
2026-09-10: `ERROR_TYPES` was bound in four files -- gitRobot's errors.py, verdictLedger's,
mcpcommon/iserror.py and the conformance suite -- and sjv was in none of them. It emitted
`operation` and `integrity`, and NEITHER was published anywhere, while `mcpcommon/iserror.py`
read the field on every refusal from every server including this one.

That is the exact defect the consolidation was built to end, surviving in the one server the
consolidation did not reach: the fix landed on the two servers whose divergence had been
MEASURED, and the third was never counted.

`operation` IS `usage` AND ALWAYS WAS. OperationError's own docstring says "an operation is
unknown or its parameters are malformed", which is what `usage` publishes: "a bad argument
name, a bad argument VALUE, a missing required field". It was a private synonym for a public
value. `integrity` was a real condition nothing published covered, and is now published.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

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



class ValidationError(Exception):
    error_type = _kind("validation")
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
    error_type = _kind("integrity")
    """Raised when the on-disk file hash does not match the last audit hash.

    Means the file was edited out of band, bypassing the handler. This is
    detection, not prevention (spec §6/§10) — halt and alarm.
    """


class OperationError(Exception):
    error_type = _kind("usage")
    """Raised when an operation is unknown or its parameters are malformed.

    `usage`, not a private `operation`: this IS a malformed call, the caller can fix it and
    retry, and nothing about the server is broken.
    """
