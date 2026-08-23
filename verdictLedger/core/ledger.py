"""The composition root: config + store + validation, and every write path.

Everything enforceable lives here so `core` is a working library and CLI with no
MCP installed — same separation the two sibling servers keep. The MCP layer is
transport and enforces nothing.

⚠ There is exactly ONE validation implementation and it is here. `record.py` is a
thin client that serialises and posts; it holds no rules. That is what makes the
mirror defect unrepresentable rather than merely discouraged.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core import config as config_mod
from core import schema, validate as validate_mod
from core.errors import ConfigError, UsageError, ValidationFailure
from core.store import GENESIS_STEP, Store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    def __init__(self, data_path=None, *, policy_path=None, required_path=None):
        self.data_path = Path(data_path or os.environ.get(
            "ZPLEDGER_DATA", Path(__file__).resolve().parents[1] / "data" / "records.jsonl"))
        # ⚠ Config failure is not fatal at construction — it is a SERVED state.
        # An unloadable policy must make every gated action refuse with a reason,
        # not crash the process into a restart loop the supervisor cannot fix.
        self.config_error: Optional[str] = None
        try:
            self.config = config_mod.load(policy_path, required_path)
        except ConfigError as exc:
            self.config = None
            self.config_error = str(exc)
        lock = self.config.lock if self.config else {"soft_seconds": 5, "hard_seconds": 30}
        self.store = Store(self.data_path, soft_seconds=lock["soft_seconds"],
                           hard_seconds=lock["hard_seconds"])

    # -- guards ----------------------------------------------------------------

    def _require_config(self) -> config_mod.Config:
        if self.config is None:
            raise ConfigError(
                f"{self.config_error} — the ledger serves UNDECIDED and every gated "
                f"action refuses. It must never fall back to a built-in default, "
                f"because that is a second copy of the policy and the weaker one is "
                f"the copy nobody notices.")
        return self.config

    # -- validation ------------------------------------------------------------

    def _prepare(self, record: dict) -> dict:
        """Normalise a caller's record into the form that would be STORED.

        ⚠ `validate` and `append` MUST share this. A preview that judges the raw
        record while the write judges a stamped one is a preview that lies — it
        would report V10 against every client record, since the client leaves
        `policy_sha` for the server to fill in.
        """
        cfg = self._require_config()
        rec = schema.empty_record()
        if isinstance(record, dict):
            rec.update({k: v for k, v in record.items() if k in schema.TOP_LEVEL})
            for extra in sorted(set(record) - set(schema.TOP_LEVEL)):
                rec[extra] = record[extra]    # kept so V7 can reject it BY NAME
        rec.setdefault("run", {})
        if not (rec["run"].get("policy_sha") or "").strip():
            rec["run"]["policy_sha"] = cfg.policy_sha
        if not rec["run"].get("started"):
            rec["run"]["started"] = _now()
        rec["id"] = schema.record_key(rec)
        return rec

    def validate(self, record: dict) -> dict:
        cfg = self._require_config()
        rec = self._prepare(record)
        violations = validate_mod.validate(
            rec, config=cfg, existing_ids=self.store.ids(), tips=self.store.tips(),
            known_policy_shas=self.store.policy_shas() | {cfg.policy_sha})
        return {"ok": not violations, "errors": violations}

    # -- writing ---------------------------------------------------------------

    def append(self, record: dict) -> dict:
        """Validate, then append. Idempotent on identical identity (§4b)."""
        rec = self._prepare(record)
        result = self.validate(rec)
        if not result["ok"]:
            self.store.bump("invalid_appends")
            raise ValidationFailure(result["errors"])

        existing = self.store.get(rec["id"])
        if existing is not None:
            # Same key AND same payload = the same fact stated twice. A same-key
            # DIFFERENT-payload record never reaches here: V11 refuses it above as
            # branching, which is the distinction the key alone cannot draw.
            return {"id": rec["id"], "appended": False,
                    "reason": "identical record already present"}

        self.store.append(rec)
        return {"id": rec["id"], "appended": True}

    def seed_genesis(self, commit: str, note: Optional[str] = None) -> dict:
        """The floor below which `crossref` claims nothing (§9a).

        ⚠ It is a fact about when RECORDING began — never a claim that earlier work
        was verified. Without it, crossref reports every prior commit as an orphan
        forever, and a warning nobody can act on is one people learn to scroll past.
        """
        cfg = self._require_config()
        if self.store.genesis() is not None:
            return {"id": self.store.genesis()["id"], "appended": False,
                    "reason": "genesis already recorded"}
        rec = schema.empty_record(
            step=GENESIS_STEP, tier="H", verdict="PASS",
            reason=None,
            basis={"kind": "ref", "value": commit, "resolved_from": "explicit"},
            subjects=[{"git_blob_id": commit, "path": "<genesis>"}],
            decided={"how": "signature", "passes": 1, "agreed": 1,
                     "who": os.environ.get("ZPLEDGER_ACTOR", "operator")},
            run={"id": f"genesis-{commit[:12]}", "started": _now(),
                 "policy_sha": cfg.policy_sha,
                 "env": {"note": note or "records begin here; nothing before it is claimed"}},
        )
        return {**self.append(rec), "commit": commit}

    def sign(self, *, step: str, subjects: list, who: str, reason: str,
             basis: dict, tier: str = "H", run_id: Optional[str] = None) -> dict:
        """ACCEPT — "you are right, we ship anyway". The FAIL stands as carried debt."""
        if not (who or "").strip():
            raise UsageError("sign requires who — an anonymous human pass is V5")
        return self._decided(step=step, subjects=subjects, basis=basis, tier=tier,
                             how="signature", who=who, reason=reason, run_id=run_id)

    def override(self, *, step: str, subjects: list, who: str, reason: str,
                 basis: dict, tier: str = "H", run_id: Optional[str] = None) -> dict:
        """REGRADE — "you are wrong, the gate erred".

        ⚠ Feeds the OPPOSITE signal to `sign` and must never share its code path: an
        accept is corpus debt, an override is evidence the STEP is defective.
        """
        if not (who or "").strip():
            raise UsageError("override requires who")
        return self._decided(step=step, subjects=subjects, basis=basis, tier=tier,
                             how="override", who=who, reason=reason, run_id=run_id)

    def _decided(self, *, step, subjects, basis, tier, how, who, reason, run_id) -> dict:
        cfg = self._require_config()
        key = (step, (basis or {}).get("value"))
        tip = (self.store.tips().get(key) or {}).get("latest")
        revision = (tip.get("revision", 0) + 1) if tip else 0
        rec = schema.empty_record(
            step=step, tier=tier, verdict="PASS", reason=reason,
            basis=basis, subjects=list(subjects or []), revision=revision,
            decided={"how": how, "passes": 1, "agreed": 1, "who": who},
            run={"id": run_id or os.environ.get("ZPLEDGER_RUN") or f"manual-{_now()}",
                 "started": _now(), "policy_sha": cfg.policy_sha, "env": {}},
        )
        return self.append(rec)

    # -- queries ---------------------------------------------------------------

    def get(self, record_id: str) -> Optional[dict]:
        return self.store.get(record_id)

    def find(self, *, step=None, verdict=None, tier=None, since=None,
             subject_sha=None, limit: int = 50) -> dict:
        out = []
        for r in self.store:
            if step and r.get("step") != step:
                continue
            if verdict and r.get("verdict") != verdict:
                continue
            if tier and r.get("tier") != tier:
                continue
            if since and ((r.get("run") or {}).get("started") or "") < since:
                continue
            if subject_sha and not any(s.get("git_blob_id") == subject_sha
                                       for s in r.get("subjects") or []):
                continue
            out.append(r)
        return {"count": len(out), "returned": len(out[:limit]), "records": out[:limit]}

    def status(self) -> dict:
        health = self.store.health()
        genesis = self.store.genesis()
        undecided_steps = set()
        for key, entry in self.store.tips().items():
            latest = entry.get("latest") or {}
            if latest.get("verdict") == "UNDECIDED":
                undecided_steps.add(latest.get("step"))
        return {
            **health,
            "config_ok": self.config is not None,
            "config_error": self.config_error,
            "policy_sha": self.config.policy_sha if self.config else None,
            "undecided_steps": sorted(s for s in undecided_steps if s),
            "genesis": (f"records begin at {genesis['basis']['value']}; "
                        f"nothing before it is claimed") if genesis else
                       "NO GENESIS RECORD — crossref cannot bound its history",
        }
