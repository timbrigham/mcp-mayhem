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
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Config:
    """Both config files plus the sha that identifies them together.

    ``policy_sha`` covers BOTH files: a verdict is judged under the thresholds AND
    the type registry in force, so a change to either moves the bar. Recording one
    and not the other would let half the policy shift invisibly.
    """

    def __init__(self, policy_path, required_path):
        self.policy_path = Path(policy_path)
        self.required_path = Path(required_path)
        self.policy = _read(self.policy_path, "policy")
        self.required = _read(self.required_path, "required")
        self._validate()
        self.policy_sha = hashlib.sha256(
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
            for field in ("when",):
                val = spec.get(field)
                if val is not None and not isinstance(val, str):
                    raise ConfigError(
                        f"required.types[{name!r}].{field} must be a string glob, got "
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

    @property
    def max_depth(self) -> int:
        return int(self.policy["supersede"]["max_depth"])

    @property
    def actions(self) -> list[str]:
        return list(self.policy["actions"])

    @property
    def genesis(self) -> Optional[str]:
        return (self.policy.get("genesis") or {}).get("commit")

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


def _resolve(kind: str, filename: str) -> Path:
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
    return _ROOT / "config" / filename


def load(policy_path=None, required_path=None) -> Config:
    return Config(policy_path or _resolve("POLICY", "policy.v1.json"),
                  required_path or _resolve("REQUIRED", "required.v2.json"))
