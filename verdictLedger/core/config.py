"""Policy and the type registry — CONFIG, never constants.

**The line (§9d): if changing a POLICY means editing LOGIC, it is in the wrong
place.** How to validate a record is code. Which types exist, which actions exist,
how many passes unanimity means, and every signal threshold are data.

⚠⚠ FAIL CLOSED ON THE CONFIG ITSELF. An unloadable or schema-invalid config
serves NOTHING — validate, requirements and inventory all return UNDECIDED and
every gated action refuses. It must NEVER fall back to a built-in default,
because a built-in default is a second copy of the policy and the weaker of the
two is the copy nobody notices.

⚠ REQUIRED BY DEFAULT (§9b). A registered type binds on every action unless an
entry says otherwise, and saying otherwise costs a stated `reason`. A narrowing
without a reason is IGNORED and the type stays required — reusing the
`encoding_whitelist.txt` convention on purpose, because a typo in an exemption
must fail safe. Inclusion is free; exclusion is the thing that takes effort.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

from core.errors import ConfigError

POLICY_SCHEMA = "zp.policy.v1"
REQUIRED_SCHEMA = "zp.required.v2"

FAMILIES = ("mechanical", "review")


def _read(path: Path, label: str) -> dict:
    if not path.exists():
        raise ConfigError(
            f"{label} not found at {path}. The ledger serves nothing without it — "
            f"a built-in default would be a second copy of the policy.")
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigError(f"{label} unreadable at {path}: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{label} is not valid JSON ({path}): {exc}") from exc


def _sha(path: Path) -> str:
    """The identity of a config file, NORMALISED so that transport cannot change it.

    ⚠⚠ MEASURED 2026-08-25, AND IT IS THE DEFECT CLASS THIS SERVER EXISTS TO END.
    `policy.v1.json` moved from `6c62b62b…` to `380f4a70…` on being copied into
    ZeroParadox, because that repo's `.gitattributes` mandates LF for `*.json` and the
    file arrived CRLF. **Not one byte of the bar changed** — proved two ways, equal
    after newline normalisation and equal as parsed objects — yet the value that says
    "this is the policy your verdict was judged under" moved.

    Every reader was then wrong in a different direction: the migration check reads a
    correct move as a failed one, and V10 sees a policy it has never seen. Worse, it
    RECURS — a checkout with a different `core.autocrlf`, a new `.gitattributes` line,
    an editor that rewrites on save. Pinning the new value would have fixed one
    instance of a class.

    So line endings and a BOM are stripped before hashing. Both are invisible to
    `_read`, which parses with `utf-8-sig`, so two files that this loader cannot tell
    apart must not have different identities.

    ⚠ THIS IS NOT §4d's CANONICAL-JSON CONTRACT RETURNING. That was retired because
    RECORD identity needed a reproducible digest over a data structure, and git had
    already content-addressed the thing being judged. This hashes BYTES, as before —
    it merely declines to treat two encodings of one byte sequence as two files. No
    key order, no separators, nothing to reproduce.
    """
    raw = path.read_bytes()
    if raw.startswith(codecs.BOM_UTF8):
        raw = raw[len(codecs.BOM_UTF8):]
    raw = raw.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
    return hashlib.sha256(raw).hexdigest()


class Config:
    """Both config files plus the sha that identifies them together.

    ``config_sha`` covers BOTH files: a verdict is judged under the thresholds AND
    the type registry in force, so a change to either moves the bar. Recording one
    and not the other would let half the policy shift invisibly.

    ⚠⚠ IT WAS CALLED ``policy_sha`` UNTIL 2026-08-25, AND THE NAME WAS A LIE THIS
    VERY PARAGRAPH ALREADY CONTRADICTED. The text said "covers BOTH files"; the name
    said it digests one. ZeroParadox edited only ``required.v2.json``, watched the
    value move, and correctly reported that a field named for the policy file cannot
    answer "which policy file is deployed".

    ⚠ The name had already misled its own author: the registry-move handover told
    ZeroParadox to expect ``policy_sha`` unchanged across the move, AS a policy-file
    digest. That was wrong twice — once for line endings, once because it is a
    composite. A name that misleads the person who wrote it will mislead everyone.

    ⚠ RETIRED, NOT REDEFINED, following ``subjects[].sha256`` -> ``git_blob_id``: the
    same defect and the same fix. Redefining a name in place leaves every prior reader
    holding a meaning nobody will ever correct.
    """

    def __init__(self, policy_path, required_path):
        self.policy_path = Path(policy_path)
        self.required_path = Path(required_path)
        self.policy = _read(self.policy_path, "policy")
        self.required = _read(self.required_path, "required")
        self._validate()
        self.config_sha = hashlib.sha256(
            (_sha(self.policy_path) + _sha(self.required_path)).encode()).hexdigest()

    # -- schema checks, because a malformed policy must not half-apply ---------

    def _validate(self) -> None:
        p, r = self.policy, self.required
        if p.get("schema") != POLICY_SCHEMA:
            raise ConfigError(f"policy schema must be {POLICY_SCHEMA!r}, got {p.get('schema')!r}")
        if r.get("schema") != REQUIRED_SCHEMA:
            raise ConfigError(f"required schema must be {REQUIRED_SCHEMA!r}, got {r.get('schema')!r}")
        if not isinstance(p.get("actions"), list) or not p["actions"]:
            raise ConfigError("policy.actions must be a non-empty list")
        if not isinstance(p.get("agreement", {}).get("min_passes"), int):
            raise ConfigError("policy.agreement.min_passes must be an integer")
        if not isinstance(p.get("supersede", {}).get("max_depth"), int):
            raise ConfigError("policy.supersede.max_depth must be an integer")
        # ⭐⭐ REFUSE ON A MISSING POLICY-GRADE KEY, added 2026-09-07. This file's own
        # header has always said the bar "must never fall back to a built-in default,
        # because a built-in default is a second copy of the policy and the weaker one
        # is the copy nobody notices" — and that was enforced for the WHOLE FILE and
        # never for an INDIVIDUAL KEY. `push.bar` ran as an invisible built-in for
        # THREE DAYS, was "fixed" in the file only the tests load, and was found again
        # a day later because the live server reads a different one. Two discoveries
        # of one defect. `min_passes` and `max_depth` above are the model: no built-in
        # at all, raise if unset.
        #
        # ⛔⛔ THE LIST IS DELIBERATELY NOT ALL THREE KEYS THAT WERE DISCLOSED.
        # `migration.v16_evidence_required` is ABSENT FROM IT ON PURPOSE, and adding
        # it would be a real regression, not extra safety:
        #
        #   push.bar                        absent -> tip_green   PERMISSIVE
        #   coverage.require_complete       absent -> False       PERMISSIVE
        #   migration.v16_evidence_required absent -> True        STRICT
        #
        # Absence is only a defect where absence is the LOOSE direction. For V16,
        # deleting the key is how the cutover ENDS — `test_deleting_the_key_re_arms_
        # the_rule` pins that removal re-arms the rule, and `test_the_shipped_policy_
        # relaxes_nothing` pins that the shipped policy carries NO `migration` block
        # precisely so that leaving a live relaxation behind turns the suite red.
        # Requiring the key would force that block back into every policy file and
        # convert a safe, intended, terminal absence into a fatal one.
        #
        # ⚠ A TYPO IS STILL NOT REFUSED HERE, and that asymmetry is deliberate: an
        # unknown `push.bar` falls back to `every_commit`, the STRICTER bar. Missing
        # was the loose direction; misspelt is already the safe one.
        for dotted, block, key, kind, what in (
                ("push.bar", "push", "bar", str,
                 "what may be published: whether every commit in a range is judged, "
                 "or only the tip"),
                ("coverage.require_complete", "coverage", "require_complete", bool,
                 "whether a step may report SATISFIED having examined almost none of "
                 "its declared scope"),
        ):
            node = p.get(block)
            if not isinstance(node, dict) or key not in node:
                raise ConfigError(
                    f"policy.{dotted} is not set. It governs {what}. Its built-in "
                    f"fallback is the PERMISSIVE direction, so an absent key quietly "
                    f"buys the looser rule — write the value you are actually running "
                    f"under into the policy file. To keep today's behaviour exactly, "
                    f"set it to "
                    f"{'\"tip_green\"' if dotted == 'push.bar' else 'false'}.")
            # ⚠ `False` IS A CONFIGURED VALUE. A truthiness test here would refuse the
            # very value coverage.require_complete actually holds.
            if not isinstance(node[key], kind) or isinstance(node[key], bool) != (kind is bool):
                raise ConfigError(
                    f"policy.{dotted} must be {kind.__name__}, got {node[key]!r}")

        mig = p.get("migration")
        if mig is not None:
            if not isinstance(mig, dict):
                raise ConfigError("policy.migration must be an object")
            for key, val in mig.items():
                if not key.startswith("_") and not isinstance(val, bool):
                    # ⚠ A relaxation misspelt as the string "false" is TRUTHY, and a
                    # relaxation that silently reads as ON is the one failure this block
                    # must not have. Refuse the config outright rather than guess.
                    raise ConfigError(
                        f"policy.migration.{key} must be a boolean, got {val!r} — a "
                        f"relaxation written as a string reads as ON, which is the "
                        f"wrong direction to be wrong in")
        types = r.get("types")
        if not isinstance(types, dict) or not types:
            raise ConfigError("required.types must be a non-empty object")
        for name, spec in types.items():
            if not isinstance(spec, dict):
                raise ConfigError(f"required.types[{name!r}] must be an object")
            fam = spec.get("family")
            if fam not in FAMILIES:
                raise ConfigError(
                    f"required.types[{name!r}].family must be one of {FAMILIES}, got {fam!r}")

            # ⚠⚠ SHAPE-CHECK EVERY FIELD THE CODE READS. A config is data read LIVE
            # while the code that understands it needs a RESTART, so a value this build
            # predates would otherwise surface as a TypeError from inside fnmatch --
            # naming neither the file nor the field, and indistinguishable from the
            # server being down to any caller that swallows errors.
            for field in ("when", "module"):
                val = spec.get(field)
                if val is not None and not isinstance(val, str):
                    raise ConfigError(
                        f"required.types[{name!r}].{field} must be a string, got "
                        f"{type(val).__name__}. If this config was written for a newer "
                        f"build, RESTART the ledger rather than editing it back.")
            for field in ("scope", "switches", "scope_exclude"):
                val = spec.get(field)
                if val is None:
                    continue
                if isinstance(val, str):
                    val = [val]
                if not isinstance(val, list) or not all(
                        isinstance(x, str) and x for x in val):
                    raise ConfigError(
                        f"required.types[{name!r}].{field} must be a string or a list "
                        f"of non-empty strings, got {val!r}. If this config was written "
                        f"for a newer build, RESTART the ledger rather than editing it "
                        f"back — the config is read live and the code is not.")
            acts = spec.get("actions")
            if acts is not None and not (isinstance(acts, list) and all(
                    isinstance(x, str) for x in acts)):
                raise ConfigError(
                    f"required.types[{name!r}].actions must be a list of action names, "
                    f"got {acts!r}")

    # -- the values the rest of the system compares against -------------------

    @property
    def min_passes(self) -> int:
        return int(self.policy["agreement"]["min_passes"])

    def paths(self) -> dict:
        """The resolved locations of both config files, and how they were chosen.

        ⚠ `config_sha` answers "are we reading the same bytes?"; this answers "from
        where?". They are different questions and only the first one had an answer.
        """
        return {"policy_path": str(self.policy_path),
                "required_path": str(self.required_path),
                "config_source": (
                    f"ZPLEDGER_CONFIG={os.environ['ZPLEDGER_CONFIG']}"
                    if os.environ.get("ZPLEDGER_CONFIG") else
                    "per-file ZPLEDGER_POLICY/ZPLEDGER_REQUIRED"
                    if (os.environ.get("ZPLEDGER_POLICY")
                        or os.environ.get("ZPLEDGER_REQUIRED")) else
                    "the ledger's own config/ — the last-resort location, and NOT "
                    "where §7 says the bar belongs")}

    @property
    def registry_sha(self) -> str:
        """The identity of the TYPE REGISTRY alone — not the composite `config_sha`.

        ⚠⚠ SCOPE LIVES IN THE REGISTRY, so freezing scope means freezing THIS. It is
        deliberately separate from `config_sha`, which also covers `policy.v1.json`:
        raising a threshold or flipping a migration switch must not read as "the scope
        moved", or the freeze cries wolf and gets ignored — and a freeze people ignore
        is worse than none, because it still reads as protection.
        """
        return _sha(self.required_path)

    @property
    def frozen_registry_sha(self):
        """The registry sha this convergence run was started against, or None.

        ⚠ Tim, 2026-08-29: "no more random ass stuff getting into scope at a later
        point." Stating that as a rule makes it a convention someone remembers; putting
        the sha here makes every `progress` call check it. The mechanism is the point —
        `bar_drift` already showed that 8 of 12 green steps had earned their green
        under a registry that no longer existed, and nothing had surfaced it.
        """
        return (self.policy.get("convergence") or {}).get("frozen_registry_sha")

    @property
    def coverage_complete_required(self) -> bool:
        """Whether an in-scope path a step has NEVER examined blocks the action.

        ⚠⚠ THE POLICY CHANGE `subjects_unexamined` WAS ALWAYS WAITING FOR. `inventory`
        has counted it since 2026-08-23 and deliberately did not block, because
        refusing every action until every step covers every in-scope path is a
        decision about what a green row MEANS, not a bug fix.

        Tim made it 2026-08-25: *"every file needs a complete set of actual successful
        gate analysis.. not just this historical checkoff."*

        And the measurement that forced it: `guards` recorded a PASS over FOUR
        subjects — one .lean file and three baseline files — while declaring no scope,
        which under the strict default means it owes all 504 tracked paths. The row
        read SATISFIED. `check_prose` and `check_classes` read SATISFIED on records
        from 2026-08-23 covering ~216 of 504, still matching only because those files
        had not moved. A green row over 0.8% of a tree is the warrant-satisfied-
        while-empty defect with a rounding error instead of a zero.

        ⚠ DEFAULT FALSE, because turning it on refuses everything until the corpus is
        genuinely covered — which is the intended forcing function, but it must be a
        deliberate act with the sweep already planned, not a side effect of this
        landing. Read live like every other policy value: no restart.
        """
        return bool((self.policy.get("coverage") or {}).get("require_complete", False))

    @property
    def push_bar(self) -> str:
        """`"tip_green"` or `"every_commit"` — how a RANGE is judged.

        Tim, 2026-09-02, choosing between two stated options: **the published tip carries the
        full push bar, and every defect an intermediate honestly carries is FIXED BY THE TIP.**

        ⚠⚠ THE SECOND CLAUSE IS A REAL CONDITION, NOT A GRACE NOTE. "The tip is green" alone
        would publish a broken intermediate whose defect was never fixed at all. What
        `tip_green` forgives is a FAIL or UNDECIDED whose **indicted blobs are absent at the
        tip** — checkable only because `failing` made a FAIL say which bytes it condemns.

        ⚠ MISSING, STALE and LEGACY_IDENTITY still block at every commit. *"We never looked"*
        and *"we looked, it was broken, we fixed it"* are different facts, and only the second
        is a defect that can be fixed within a push.

        ⭐ WHY THE OLD BAR HAD TO MOVE: `every_commit` cannot express the normal shape of a
        remediation arc — a real defect at commit N, fixed at commit M, both inside one push.
        Under it that range can never be pushed commit-by-commit-green, and the only escape is
        rewriting history. `squash` does that and is remediation-only ON PRINCIPLE, because
        `can_push` justifies per-commit strictness on the grounds that intermediates are
        "fetchable, bisectable, citable forever" — so squashing satisfies the gate by destroying
        exactly what the gate protects.

        ⚠ UNKNOWN VALUES FALL BACK TO THE STRICTER BAR. A typo must not silently widen what may
        be published; `every_commit` is the safe direction to be wrong in.
        """
        raw = (self.policy.get("push") or {}).get("bar")
        value = str(raw).strip().lower() if raw is not None else "tip_green"
        return value if value in ("tip_green", "every_commit") else "every_commit"

    @property
    def push_bar_source(self) -> str:
        """`"policy"` if the bar was configured, `"default"` if nothing named it.

        ⛔⛔ THE BAR RAN ON AN INVISIBLE DEFAULT FOR THREE DAYS. Found by ZeroParadox 2026-09-05
        while a push was blocked: `can_push` reported `push_bar: "tip_green"` and they could not
        find the mechanism anywhere. They were right — **it is not in the policy the server
        reads.** I added `push.bar` to `verdictLedger/config/policy.v1.json`, which the TESTS
        load; the live server reads `ZPLEDGER_CONFIG` at ZeroParadox's `tools/verify`, and that
        file has no `push` key at all.

        ⚠⚠ So a rule governing what may be published was a hardcoded fallback, in a project
        whose first principle is CONFIG, NOT CONSTANTS — and it was undiscoverable precisely
        because it was working. A default that behaves correctly is the hardest kind to notice.

        ⭐ Reporting the SOURCE rather than only the value is what makes that findable: a reader
        asking "where is this configured" gets `default` and knows the answer is nowhere, rather
        than searching a file that will never contain it. Same reason `policy()` reports the
        PATH it loaded and not just a sha — nobody noticed the registry being served from the
        wrong repo for three days because nothing said where it came from.
        """
        return "policy" if (self.policy.get("push") or {}).get("bar") is not None else "default"

    @property
    def unpinned_modules(self) -> list:
        """Steps that declare a `module` but no `approved_modules` — running unpinned.

        ⚠⚠ THE COMPANION TO V16c, AND THE REASON AN ABSENT PIN IS NOT A SILENT PERMIT. V16 pins
        a step to a PATH; `approved_modules` pins it to a set of git blob ids, so an edited
        checker cannot record until its new build is approved by a reviewable edit in the same
        history as the change.

        ⛔ Refusing every UNPINNED step would brick all twenty mechanical steps the moment this
        shipped. That is an outage, not a loud failure. So an unpinned step still records — and
        appears here, on every `policy()` call, so nobody has to read source to discover which
        tools are unconstrained. **Absence disclosed is not the same as absence defaulted.**

        ⭐ Tim, 2026-09-06: *"the 'silently can't record' is the problem. fail loudly."* Both
        halves answer that. A VIOLATED pin refuses with the offending blob and the remedy; an
        ABSENT pin is named here rather than being invisible.
        """
        types = (self.required or {}).get("types") or self.required or {}
        if not isinstance(types, dict):
            return []
        out = []
        for step, spec in sorted(types.items()):
            if not isinstance(spec, dict):
                continue
            module = spec.get("module")
            if module and not spec.get("approved_modules"):
                out.append({"step": step, "module": module,
                            "risk": "any build of this file can record for this step"})
        return out

    @property
    def defaulted(self) -> list:
        """Every policy setting whose key is ABSENT, so a built-in constant is in force.

        ⚠⚠ A DEFAULT THAT BEHAVES CORRECTLY IS THE HARDEST KIND TO NOTICE, and this file's own
        header forbids exactly this: *"it must NEVER fall back to a built-in default, because a
        built-in default is a second copy of the policy and the weaker of the two is the copy
        nobody notices."* That rule is enforced for the WHOLE FILE — an unloadable config serves
        UNDECIDED — and was never enforced for an INDIVIDUAL KEY. A missing key defaults in
        silence.

        ⭐ Measured 2026-09-06: `push.bar` had been an invisible default for THREE DAYS, found by
        the consumer while a push was blocked, "fixed" by adding the key to the file the TESTS
        load, and found AGAIN a day later because the LIVE server reads a different file. Two
        discoveries of one defect, because nothing enumerated what was running on a built-in.

        ⛔ `direction` IS THE FIELD THAT MATTERS AND IT IS NOT COSMETIC. `push.bar` documents
        "UNKNOWN VALUES FALL BACK TO THE STRICTER BAR… every_commit is the safe direction to be
        wrong in" — and implements that for a TYPO while a MISSING key falls back to the LOOSER
        `tip_green`. So the more likely mistake gets the more permissive treatment. Reporting the
        direction is what makes that visible without changing what anything enforces.

        ⚠ `agreement.min_passes` and `supersede.max_depth` are deliberately ABSENT from this list:
        they have no built-in at all and raise if unset, which is the behaviour every entry here
        should eventually have. They are the model, not an oversight.

        ⭐ AND AS OF 2026-09-07 TWO ENTRIES REACHED THAT MODEL. `push.bar` and
        `coverage.require_complete` now RAISE in `_validate` when absent, so on a config that
        loaded they can never appear here — this list reports them only via the `Config.__new__`
        path a unit test uses. They are KEPT rather than deleted: the disclosure is what the
        refusal is built on, and if the refusal is ever weakened the disclosure must come back
        rather than the key going quiet again.

        ⛔ `migration.v16_evidence_required` STAYS DISCLOSURE-ONLY, and that is not an oversight
        either. Its default is STRICT, and deleting the key is how a V16 cutover ENDS — making
        absence fatal would force a live `migration` block into every policy file, which is the
        exact thing `test_the_shipped_policy_relaxes_nothing` exists to prevent. **Absence is a
        defect only where absence is the loose direction.** Disclosed, never refused.

        ⚠ The `lock.*` entries are operational rather than policy and stay disclosure-only for a
        different reason: a wrong lock timeout is a performance bug, not a widening of what may
        be published.
        """
        out = []

        def note(path: str, present: bool, in_force, direction: str, why: str):
            if not present:
                out.append({"key": path, "in_force": in_force,
                            "direction": direction, "governs": why})

        note("push.bar", (self.policy.get("push") or {}).get("bar") is not None,
             "tip_green", "LOOSER than the typo fallback (every_commit)",
             "what may be published: whether every commit in a range is judged or only the tip")
        note("coverage.require_complete",
             "require_complete" in (self.policy.get("coverage") or {}),
             False, "PERMISSIVE — coverage is not enforced",
             "whether a step may report SATISFIED having examined almost none of its scope")
        note("migration.v16_evidence_required",
             "v16_evidence_required" in (self.policy.get("migration") or {}),
             True, "strict — the safe direction",
             "whether a mechanical PASS is refused without evidence naming its checker")
        for k, v in (("soft_seconds", 5), ("hard_seconds", 30)):
            note(f"lock.{k}", k in (self.policy.get("lock") or {}), v,
                 "operational, not policy", "store lock timing")
        return out

    @property
    def v16_required(self) -> bool:
        """Whether V16 REFUSES a mechanical PASS with no evidence.

        ⚠⚠ ABSENT MEANS STRICT, and that direction is the whole safety of the switch.
        A relaxation must be written down to exist, so deleting the key at the end of
        the cutover re-arms the rule rather than disarming it, and a policy file that
        predates this build is strict rather than silently permissive. It is the
        reason-less-narrowing convention again: suppression costs effort, never
        absent-mindedness.
        """
        return bool((self.policy.get("migration") or {}).get(
            "v16_evidence_required", True))

    @property
    def relaxations(self) -> list[str]:
        """Every rule currently relaxed by `policy.migration`, with its consequence.

        ⚠ Read by `status()` on EVERY call, clean or not. A migration aid that stops
        announcing itself is how a temporary relaxation becomes the permanent bar --
        the same reason `signals` prints its counts when they are zero.
        """
        out = []
        if not self.v16_required:
            out.append(
                "V16 RELAXED: a mechanical PASS may carry no `evidence`, so the ledger "
                "cannot presently tell 'the checker ran and exited 0' from 'an agent "
                "said it did'. Set policy.migration.v16_evidence_required = true (read "
                "live, no restart) once emitters pass evidence, then delete the key.")
        return out

    @property
    def max_depth(self) -> int:
        return int(self.policy["supersede"]["max_depth"])

    @property
    def actions(self) -> list[str]:
        return list(self.policy["actions"])

    @property
    def genesis(self) -> Optional[str]:
        """⛔ REMOVED AS A CONFIG VALUE — always None, and callers must not add one.

        The floor is a claim about WHEN RECORDING BEGAN, so it belongs in the
        append-only, validated, attributable stream, not in a file anyone can edit
        without a trace. `crossref` has always read it from the genesis RECORD; this
        accessor read `policy.genesis.commit` and was called by nothing, while the
        policy comment instructed readers to set exactly that. A config value that
        looks authoritative, is documented as authoritative, and is consumed by
        nothing is the two-copies defect with the weaker copy being the one a reader
        is told to edit.

        Seed the floor with `zpledger genesis <sha>`.
        """
        return None

    @property
    def signals(self) -> dict:
        return dict(self.policy.get("signals") or {})

    @property
    def lock(self) -> dict:
        """Bounded-wait numbers. ⚠ ``hard_seconds`` is coupled to the process
        supervisor's poll interval — see store.py."""
        cfg = self.policy.get("lock") or {}
        return {"soft_seconds": float(cfg.get("soft_seconds", 5)),
                "hard_seconds": float(cfg.get("hard_seconds", 30))}

    @property
    def types(self) -> dict:
        return dict(self.required["types"])

    def is_registered(self, step: str) -> bool:
        return step in self.required["types"]

    def requirements(self, action: Optional[str] = None) -> dict:
        """Which types bind for an action, and why any of them do not.

        ⚠ REQUIRED BY DEFAULT. A minimal entry ``{"family": "..."}`` is the STRICT
        one: no `actions` and no `when` means required everywhere. A narrowing
        without a `reason` is dropped and the type falls back to required — so a
        typo in an exemption fails safe rather than silently exempting.
        """
        if action is not None and action not in self.actions:
            raise ConfigError(
                f"unknown action {action!r}; policy.actions = {self.actions}")
        out: dict[str, dict] = {}
        for name, spec in self.types.items():
            entry = {"family": spec["family"], "required": True,
                     "when": None, "scope": None, "reason": None, "narrowed": False,
                     # ⚠ NOT a narrowing: `switches` makes a type STRICTER, so it
                     # costs no stated reason. The reason-less-narrowing rule exists to
                     # stop silent WEAKENING; requiring one here would price the safe
                     # direction the same as the dangerous one.
                     "switches": list(spec.get("switches") or []),
                     # ⚠ NOT a narrowing either: `module` names the file whose
                     # execution a `mechanical` verdict is claiming, so declaring it
                     # makes V16 STRICTER — from "carry some evidence" to "carry THIS
                     # module". A stated reason is the price of weakening; this is the
                     # other direction and is free.
                     #
                     # ⚠ It is OPTIONAL, and that is a graduated bar, not an oversight.
                     # With no `module` declared V16 still refuses an empty `evidence`
                     # array, which is the forgery measured on 2026-08-24; declaring it
                     # additionally pins WHICH file. A required `module` would have
                     # refused every mechanical record until every type in a registry
                     # this server does not own had been annotated — the correct
                     # implementation bricking the system, again.
                     "module": spec.get("module"),
                     # ⚠⚠ AND WHICH BUILD OF IT — the same graduation one notch further.
                     # `module` pins the PATH so V16 goes from "carry some evidence" to
                     # "carry THIS module"; `approved_modules` pins the VERSION so V16c
                     # goes from "this module" to "an APPROVED build of this module". Also
                     # free: it makes the bar stricter, never weaker.
                     #
                     # ⚠ THIS ENTRY IS AN EXPLICIT WHITELIST AND THAT IS A TRAP FOR THE NEXT
                     # FIELD. `requirements()` rebuilds each spec key by key rather than
                     # passing the registry entry through, so a key absent from THIS dict is
                     # invisible to every rule downstream no matter what the registry says.
                     # Measured 2026-09-06: V16c was written, the registry was pinned, the
                     # spec looked correct when read directly — and nothing fired, because
                     # the key never survived this function. **A validator can only enforce
                     # what this dict carries.**
                     "approved_modules": list(spec.get("approved_modules") or []) or None,
                     "scope_exclude": None}
            reason = spec.get("reason")
            actions = spec.get("actions")
            when = spec.get("when")
            # ⚠ `scope` is NOT `when`. `when` says whether the type applies at all;
            # `scope` says which paths it examines when it does. A type with a narrow
            # scope is still REQUIRED -- it simply owes coverage of fewer paths.
            scope = spec.get("scope")
            if (actions is not None or when is not None or scope is not None
                    or spec.get("scope_exclude") is not None) and not (
                    isinstance(reason, str) and reason.strip()):
                # ⚠ Reason-less narrowing is IGNORED, not honoured.
                entry["reason"] = ("narrowing ignored: no reason given, so the type "
                                   "stays required for every action")
                out[name] = entry
                continue
            if actions is not None:
                entry["narrowed"] = True
                entry["reason"] = reason
                if action is not None and action not in actions:
                    entry["required"] = False
            if when is not None:
                entry["when"] = when
                entry["narrowed"] = True
                entry["reason"] = reason
            excl = spec.get("scope_exclude")
            if excl is not None:
                entry["scope_exclude"] = [excl] if isinstance(excl, str) else list(excl)
                # ⚠ An exclusion NARROWS, so it costs a stated reason like the rest.
                entry["narrowed"] = True
                entry["reason"] = reason
            if scope is not None:
                # ⚠ A STRING OR A LIST. A checker that reads two roots had to either
                # widen its glob until it was wrong or stay unscoped; both are worse
                # than saying what it reads. Normalised here so every consumer sees a
                # list and nobody re-implements the string case.
                scope = [scope] if isinstance(scope, str) else list(scope)
                # ⚠ A narrowing, so it costs a reason like the others -- and the
                # reason-less case above already fell through to "stays required over
                # every path", which is the safe direction.
                entry["scope"] = scope
                entry["narrowed"] = True
                entry["reason"] = reason
            out[name] = entry
        return out


_ROOT = Path(__file__).resolve().parents[1]


def _resolve(kind: str, filename: str, local_name: str) -> Path:
    """Where a config file lives, in precedence order.

    ``ZPLEDGER_CONFIG`` names a DIRECTORY holding both files — normally
    ``<ZeroParadox>/tools/verify``, because the bar must be a reviewable diff in
    the same history as the work it gates (§7). A per-file override wins over it,
    and the ledger's own ``config/`` is the last resort.

    ⚠ THIS IS A SEARCH PATH, NOT A FALLBACK VALUE. If a location is named and the
    file is not there, the loader RAISES — it never quietly serves different
    content than the operator pointed it at. Falling back to built-in *values* is
    the forbidden thing; choosing between explicitly configured *locations* is not.
    """
    per_file = os.environ.get(f"ZPLEDGER_{kind}")
    if per_file:
        return Path(per_file)
    directory = os.environ.get("ZPLEDGER_CONFIG")
    if directory:
        candidate = Path(directory) / filename
        if not candidate.exists():
            raise ConfigError(
                f"ZPLEDGER_CONFIG names {directory}, but {filename} is not there. "
                f"The ledger serves nothing rather than reading a different copy — "
                f"two copies of the bar is the defect this arrangement exists to "
                f"prevent. Put {filename} in that directory, or unset ZPLEDGER_CONFIG "
                f"to use the ledger's own config/.")
        return candidate
    # ⚠⚠ THE LOCAL COPY IS `.sample.json`, AND THE SUFFIX IS THE POINT. Tim, 2026-09-06:
    # *"if we have local copies of those files such as required.v2.json, I really want
    # '.sample', '.test' or something appended so it's obvious when we have segregated files
    # being used that aren't what we generally would have in use in production. Duplicate names
    # not segmenting which is which is dangerous."*
    #
    # ⛔ MEASURED COST OF THE OLD NAMING, TWICE IN TWO DAYS. `verdictLedger/config/policy.v1.json`
    # and `ZeroParadox/tools/verify/policy.v1.json` were the same filename in two repos. The
    # `push.bar` key was added to the first — which only tests and this last-resort read — while
    # the LIVE server reads the second. The bar went on running as a built-in, and the consumer
    # session discovered the same defect a second time a day later, because nothing in either
    # path said which one was the bar.
    #
    # ⚠ AND THE DIRECTION IS NOT UNIFORM ACROSS THE FLEET, which is why the names have to carry
    # it: for policy and the registry MY copy is the local one and ZeroParadox's is live, but for
    # `admission.v1.json` it is the other way round — gitRobot's IS live and ZeroParadox's is read
    # by nothing. A reader who learns the rule from one file gets the other backwards.
    return _ROOT / "config" / local_name


def load(policy_path=None, required_path=None) -> Config:
    return Config(policy_path or _resolve("POLICY", "policy.v1.json",
                                       "policy.v1.sample.json"),
                  required_path or _resolve("REQUIRED", "required.v2.json",
                                            "required.v2.sample.json"))
