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
    """A record broke one or more of V1–V16. NEVER retried.

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
    """Malformed arguments — and it must say what a PASSING next attempt looks like.

    ⭐⭐ `satisfied_when` IS REQUIRED, AND THE REASON IS CONTENT-KEYING APPLIED TO REFUSALS.
    Tim, 2026-09-04: *"why wouldn't you want to call out exactly what the success conditions
    are? It's like a teacher grading homework. **The next iteration is already going to be on a
    different blob.**"*

    A refusal phrased as a fact about the CURRENT bytes is stale the moment the caller acts on
    it: they return with different content and everything the message said no longer applies.
    **The success condition is the only part that survives the change** — which is the same
    reason a verdict binds to `(step, path, blob)` rather than to a basis.

    ⚠⚠ TWO CLAIMS, TWO FIELDS, FOR THE REASON `subjects` AND `failing` HAD TO BE SPLIT:

        what            what went wrong, about THESE bytes      — perishable
        satisfied_when  what the NEXT attempt must satisfy      — blob-independent

    Sharing one slot lets a description of the failure pass for guidance. Measured 2026-09-03 in
    the sibling server: a refusal read *"reset it to 0 and commit that"* — an instruction about
    the current file, which was ALSO the action that erased the record of a walked cap. A field
    named `satisfied_when` rejects that content by being read; a field named `alternative` does
    not.

    ⚠ NO DEFAULT, ON PURPOSE. A default would make omission the quiet path, and this exists
    because the quiet path was taken twelve times here. **What structure cannot do is check that
    the condition is CORRECT** — no control detects semantics. It forces the author to answer
    the question separately, and that is the whole of what it buys.

    ⭐ DERIVE IT FROM THE AUTHORITY WHERE ONE EXISTS, never restate. `find` names
    `schema.VERDICTS`, the same constant the validator uses, so it cannot drift. `can_push`
    names `requirements(action=…)` rather than listing twenty steps. A restated condition is
    prose, and prose goes stale exactly like the `reason` field does.
    """

    error_type = "usage"

    def __init__(self, what: str, satisfied_when: str):
        self.what = what
        self.satisfied_when = satisfied_when
        super().__init__(f"{what}\n  SATISFIED WHEN: {satisfied_when}")
