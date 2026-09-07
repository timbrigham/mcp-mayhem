"""Declared INPUT shapes — the contract at the door, not in a docstring.

⚠⚠ THE DEFECT. Measured 2026-09-05: the most important input on this fleet — the verdict
record itself — published `{"type": "object", "additionalProperties": true}`. **Any object at
all.** So `step`, `verdict`, `subjects`, `basis`, `run.id` and `failing` were invisible to the
protocol, and the real contract lived in a fifty-line docstring on `append` that a caller
using the tool directly never reads. `client/record.py` carried the same advice for callers
that imported it, and the two drifted 386 lines apart with `emit()` diverged.

⭐ Tim, 2026-09-07: *"the terms of how we accept input into the mcp servers.. that should be
an immediate gate."* A rendering cannot be more stable than what it renders. `UNVALIDATED` at
the output is worth nothing if any object at all may arrive at the input.

⛔⛔ STRUCTURAL FACTS ONLY, AND THE LINE IS NOT A STYLE PREFERENCE. `CLAUDE.md`: *"Registered
step names and thresholds stay in config, because baking policy into a static schema is the
second-copy-of-the-policy that `config.py` forbids."* So:

    HERE (structure)                     NOT HERE (policy, read live from config)
    the record's own vocabulary          which STEP NAMES are registered
    TIERS / VERDICTS / BASIS_KINDS       agreement.min_passes
    which keys exist, and their types    push.bar, coverage.require_complete

`step` is therefore a plain string. Declaring it as an enum of today's registered types would
publish a contract that goes stale the moment the registry moves — and the registry is
deliberately editable without a restart.

⚠⚠ THIS IS NOT A SECOND VALIDATOR. V1–V18 in `core/validate.py` remain the only judge of
whether a record may be RECORDED. This says only what SHAPE may arrive. Anything it rejects,
V-rules would reject too — never the reverse — and `test_the_input_model_accepts_every_record_
in_the_stream` pins that against all 2,361 records, because a model stricter than reality
refuses traffic that works today.

⚠ `failing` IS OPTIONAL HERE AND THAT IS DELIBERATE, STEP ONE OF TWO. 118 of 123 tier-A
blocking records carry no `failing`; requiring it before the consumer's emitter reaches 100%
would refuse every review gate on its next FAIL. Measured 2026-09-07: 37 of 92 recent blocking
records DO carry it, so the emitter can produce it and the gap is backlog rather than
incapacity. Requiring it is a SEPARATE switch, after the emitter — Tim's sequence: structure,
then emitter, then require.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.schema import BASIS_KINDS, SCHEMA_ID, TIERS, VERDICTS


class Subject(BaseModel):
    """A thing a verdict looked at, or indicts. **Content-keyed: the blob IS the claim.**

    ⚠ `path` is carried for humans and for scope matching; `git_blob_id` is what a coverage
    or indictment answer actually keys on. A subject without one is not addressable.
    """
    model_config = ConfigDict(extra="allow")     # forward-compatible; V7 names unknown keys
    path: str
    git_blob_id: Optional[str] = None


class Basis(BaseModel):
    """WHAT the verdict is about — a tree, a ref, a range, or a declared scope."""
    model_config = ConfigDict(extra="allow")
    kind: Optional[Literal[BASIS_KINDS]] = None      # type: ignore[valid-type]
    value: Optional[str] = None
    resolved_from: Optional[str] = None


class Decided(BaseModel):
    """HOW the verdict was reached. ⚠ `passes`/`agreed` are counts; the THRESHOLD they are
    compared against is `agreement.min_passes` and lives in config, never here."""
    model_config = ConfigDict(extra="allow")
    how: Optional[str] = None
    passes: Optional[int] = None
    agreed: Optional[int] = None
    who: Optional[str] = None


class Run(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: Optional[str] = None
    started: Optional[str] = None
    config_sha: Optional[str] = None
    policy_sha: Optional[str] = None      # ⚠ the pre-2026-08-25 name; V10 names the rename
    env: dict[str, Any] = Field(default_factory=dict)


class Cost(BaseModel):
    model_config = ConfigDict(extra="allow")
    seconds: Optional[float] = None
    usd: Optional[float] = None
    lock_wait_seconds: Optional[float] = None


class Record(BaseModel):
    """One verdict, as it may ARRIVE. Judged afterwards by V1–V18.

    ⚠ `extra="allow"` throughout is deliberate and is NOT laxity. V7 refuses unknown top-level
    keys BY NAME, which is a better error than a schema rejection that says only "extra fields
    not permitted" — and `_prepare` keeps extras precisely so V7 can name them. Rejecting here
    would replace a specific refusal with a generic one.
    """
    model_config = ConfigDict(extra="allow")

    schema_: Optional[str] = Field(default=None, alias="schema")
    id: Optional[str] = None
    step: Optional[str] = None                       # ⚠ plain str — registry is config
    tier: Optional[Literal[TIERS]] = None            # type: ignore[valid-type]
    verdict: Optional[Literal[VERDICTS]] = None      # type: ignore[valid-type]
    reason: Optional[str] = None
    basis: Optional[Basis] = None
    subjects: list[Subject] = Field(default_factory=list)
    evidence: list[Subject] = Field(default_factory=list)
    outstanding: list[Any] = Field(default_factory=list)
    # ⚠⚠ OPTIONAL, STEP ONE OF TWO — see the module docstring. Absent means ALL subjects are
    # indicted, which is the pre-2026-09-02 reading, so no historical FAIL is weakened.
    # ⚠ A LIST OF STRINGS, NOT SUBJECTS — measured, after modelling it wrong. The first draft
    # gave `failing` the same shape as `subjects` by analogy, and the stream refused it: 37
    # records carry `failing`, 308 elements, every one a `str`. Some are not even paths
    # ("tools/verify/(roster)"), so it is free-form identifiers rather than addressable
    # subjects. Caught by the accept-every-existing-record control, which is the whole reason
    # that control exists — a model stricter than reality refuses traffic that works today.
    failing: Optional[list[str]] = None
    decided: Optional[Decided] = None
    inputs: list[Any] = Field(default_factory=list)
    revision: Optional[int] = None
    cost: Optional[Cost] = None
    run: Optional[Run] = None


# ⚠ The literal the schema field must carry, exported so a test can assert the model and
# `core.schema` cannot drift apart.
EXPECTED_SCHEMA_ID = SCHEMA_ID
