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


# ⚠ TAKEN FROM `schema`, NEVER RESTATED. The vocabulary is declared once at
# `schema.VERDICTS`; a second copy here would be a list that drifts silently and then
# disagrees with the validator about what a verdict is. (The first draft of this line
# invented a fourth value, `WITHDRAWN`, that no record has ever carried — which is
# exactly the drift, arriving before the code had even landed.)
_VERDICTS = set(schema.VERDICTS)


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
        `config_sha` for the server to fill in.
        """
        cfg = self._require_config()
        rec = schema.empty_record()
        if isinstance(record, dict):
            rec.update({k: v for k, v in record.items() if k in schema.TOP_LEVEL})
            for extra in sorted(set(record) - set(schema.TOP_LEVEL)):
                rec[extra] = record[extra]    # kept so V7 can reject it BY NAME
        rec.setdefault("run", {})
        if not (rec["run"].get("config_sha") or "").strip():
            # ⚠⚠ DO NOT STAMP OVER A CALLER WHO USED THE OLD NAME. `run.policy_sha`
            # was renamed to `run.config_sha` on 2026-08-25. A caller still sending a
            # real value under the old key believes it has pinned the bar its verdict
            # is judged against; stamping the current sha would honour neither the
            # value nor the intent, and would do it SILENTLY — the caller's next
            # question ("why does my record name a different config?") has no
            # findable answer. Left blank, V10 fires and names the rename.
            #
            # ⚠ A null or empty old key is the ordinary pre-rename client and is
            # ignored, not refused: it pinned nothing, so nothing is being overridden.
            if not (rec["run"].get("policy_sha") or "").strip():
                rec["run"]["config_sha"] = cfg.config_sha
        if not rec["run"].get("started"):
            rec["run"]["started"] = _now()
        rec["id"] = schema.record_key(rec)
        return rec

    def validate(self, record: dict) -> dict:
        cfg = self._require_config()
        rec = self._prepare(record)
        violations = validate_mod.validate(
            rec, config=cfg, existing_ids=self.store.ids(), tips=self.store.tips(),
            known_config_shas=self.store.config_shas() | {cfg.config_sha})
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
                 "config_sha": cfg.config_sha,
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

    def narrow(self, *, record_id: str, failing: list, reason: Optional[str] = None,
               run_id: Optional[str] = None) -> dict:
        """⭐⭐ NARROW AN EXISTING FAIL'S INDICTMENT — the sanctioned correction for a wide FAIL.

        Re-emits the record at `revision + 1` with `failing` set, copying `subjects`, `evidence`,
        `basis`, `step` and `tier` **verbatim from the stored record**. Nothing is edited and
        nothing is withdrawn; the original stays readable, and `_index` resolves each content key
        to the highest revision, so the correction supersedes per content.

        ⚠⚠ THE POINT IS THAT THE SUBJECTS ARE NOT RETYPED. ZeroParadox, asked to correct two wide
        FAILs, could see only three routes and rejected all three: hand-author the emit
        (*"retyping 24 blob ids per record into a permanent stream, and transcription risk on an
        append-only record is exactly the wrong risk to take"*), recompute in a worktree carrying
        the OLD checker module, or add a `revision` passthrough to `emit_verdict` — which its own
        docstring forbids, because `revision` is a chain and using it to carry a second
        SIMULTANEOUS verdict would make a split look like a supersession. **All three were right
        to refuse.** This is the fourth route and it has none of those costs: the bytes come from
        the record, the revision comes from the store, and the operation can only ever narrow.

        ⚠ IT CAN ONLY NARROW. The verdict stays FAIL and the subject set is unchanged — this is
        not a route to regrade a FAIL into a PASS. That is `override`, it requires `who`, and it
        feeds the opposite signal on purpose.
        """
        original = self.store.get(record_id)
        if original is None:
            raise UsageError(f"no record {record_id!r} — narrow corrects a record that exists")
        if original.get("verdict") != "FAIL":
            raise UsageError(
                f"narrow applies to a FAIL; {record_id!r} is {original.get('verdict')!r}. "
                f"`failing` names what a FAIL indicts and is meaningless on anything else.")
        if not failing:
            raise UsageError(
                "narrow requires a non-empty failing list — an empty indictment resolves to a "
                "PASS at every path. To leave every subject indicted, do nothing: absent "
                "`failing` already means that.")
        subject_paths = {s.get("path") for s in (original.get("subjects") or [])}
        if not (set(failing) & subject_paths):
            raise UsageError(
                f"none of {sorted(failing)} is a subject of {record_id!r}. Entries that are not "
                f"subjects are inert for resolution, so this would exonerate the record rather "
                f"than narrow it. Pseudo-paths may ride ALONGSIDE a real subject.")

        # ⛔⛔ REFUSE TO RESURRECT A FAIL THAT A LATER VERDICT ALREADY SUPERSEDED.
        # Narrowing re-emits at a HIGHER revision, and revision is what decides ownership of a
        # content key — so narrowing a spent FAIL lifts it back ABOVE the PASSes that overtook
        # it. Measured 2026-09-02 in simulation: narrowing all six `check_checkers` FAILs put
        # `check_codebox.py@e64f7d16` — the TIP's own bytes, fixed at `972f8c2a` and passed
        # twice since — back under a FAIL and condemned the tip. Narrowing only the two records
        # that were genuinely current cleared every FAIL in the range.
        #
        # ⭐ ZeroParadox predicted this shape from the record alone and asked me not to build
        # the tip-green leg until it was settled. They were right that it bites — it bites
        # through REVISION rather than through blob-presence, and this is where it is stopped.
        from core import inventory as _inv
        by_content, _bp, _lg, _ev, _evc = _inv._subject_index(list(self.store))
        step = original.get("step")
        superseded = []
        for s_ in original.get("subjects") or []:
            if s_.get("path") not in set(failing):
                continue
            owner = by_content.get((step, s_.get("path"), s_.get("git_blob_id")))
            if owner is not None and owner.get("id") != record_id:
                superseded.append((s_.get("path"), owner.get("id")))
        if superseded:
            detail = "; ".join(f"{p} is now held by {oid}" for p, oid in superseded[:4])
            raise UsageError(
                f"{record_id!r} has already been SUPERSEDED on the bytes it would indict "
                f"({detail}). Narrowing re-emits at a higher revision, and revision decides "
                f"which record owns a content key — so this would lift a spent FAIL back above "
                f"the verdicts that overtook it, condemning content that has since passed. "
                f"⚠ If the later verdict is the wrong one, the remedy is a NEW verdict about "
                f"those bytes, not a narrowing of this one.")

        cfg = self._require_config()
        key = (original.get("step"), (original.get("basis") or {}).get("value"))
        tip = (self.store.tips().get(key) or {}).get("latest")
        revision = (tip.get("revision", 0) + 1) if tip else 1
        rec = schema.empty_record(
            step=original["step"], tier=original.get("tier", "M"), verdict="FAIL",
            reason=reason or original.get("reason"),
            basis=original.get("basis"),
            # ⚠ VERBATIM. Copied, never recomputed and never retyped — that is the whole value.
            subjects=list(original.get("subjects") or []),
            evidence=list(original.get("evidence") or []),
            revision=revision,
            decided=dict(original.get("decided") or {}),
            run={"id": run_id or os.environ.get("ZPLEDGER_RUN") or f"narrow-{_now()}",
                 "started": _now(), "config_sha": cfg.config_sha, "env": {}},
        )
        rec["failing"] = list(failing)
        return self.append(rec)

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
                 "started": _now(), "config_sha": cfg.config_sha, "env": {}},
        )
        return self.append(rec)

    # -- queries ---------------------------------------------------------------

    def get(self, record_id: str) -> Optional[dict]:
        return self.store.get(record_id)

    def find(self, *, step=None, verdict=None, tier=None, since=None,
             subject_sha=None, limit: int = 50) -> dict:
        # ⛔⛔ A FILTER THAT SILENTLY RETURNS NOTHING IS A FAIL-OPEN, and this one did.
        # Reported by ZeroParadox 2026-09-02: `find(step='check_checkers', verdict='fail')`
        # returned **count 0** while FOUR FAIL records for that step sat in the stream. The
        # comparison was exact against a stored `"FAIL"`, so the lowercase spelling matched
        # nothing — and an empty result is exactly what "there are no such records" looks like.
        #
        # ⚠ THEY ALMOST ACTED ON IT: *"I would have concluded no FAIL records existed if I had
        # not queried again unfiltered."* An interrogation tool that answers a typo with a
        # confident, calm, WRONG empty set is worse than one that errors — the same shape as
        # `pdf_coupling`'s truthful `NOT_APPLICABLE` over a gate that could never fire.
        #
        # Two fixes, because case was only half of it: fold the case, and REFUSE a value that
        # is not a verdict at all rather than returning the empty set that means "none found".
        if verdict is not None:
            verdict = str(verdict).strip().upper()
            if verdict not in _VERDICTS:
                raise UsageError(
                    f"{verdict!r} is not a verdict. Valid values are "
                    f"{', '.join(sorted(_VERDICTS))} (case-insensitive). Returning an empty "
                    f"result for an unrecognised filter would be indistinguishable from "
                    f"'no records match', which is how this was found.")
        if tier is not None:
            tier = str(tier).strip().upper()
        out = []
        for r in self.store:
            if step and r.get("step") != step:
                continue
            if verdict and str(r.get("verdict") or "").upper() != verdict:
                continue
            if tier and str(r.get("tier") or "").upper() != tier:
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
            "config_sha": self.config.config_sha if self.config else None,
            # ⚠ WHERE, not just WHAT. See `Config.paths`.
            **(self.config.paths() if self.config else {}),
            # ⚠⚠ COVERAGE ENFORCEMENT IS NOT A "RELAXATION" AND MUST NOT SHARE THAT
            # FIELD. `relaxations` exists for MIGRATION DEBT — a temporary state with a
            # deletion condition. Not-enforcing coverage is the standing default and
            # always has been, so listing it there would mean the list is never empty,
            # and a field that always says something says nothing. That is the control
            # `test_status_is_silent_when_nothing_is_relaxed` exists to hold.
            "coverage_enforced": (self.config.coverage_complete_required
                                  if self.config else None),
            "coverage_note": (None if not self.config
                              or self.config.coverage_complete_required else
                              "a step may report SATISFIED while never having examined "
                              "most of its in-scope paths — measured 2026-08-25, "
                              "`guards` read SATISFIED over 4 of 504 tracked paths. The "
                              "number is on every row as `subjects_unexamined`. Set "
                              "policy.coverage.require_complete = true (read live) once "
                              "a full sweep has genuinely run."),
            # ⚠ ON EVERY CALL, empty list included. A relaxation that only reports
            # itself when someone asks the right question is a relaxation nobody will
            # remember to remove.
            "relaxations": self.config.relaxations if self.config else [
                "CONFIG UNREADABLE — every rule is moot; the ledger serves UNDECIDED"],
            "undecided_steps": sorted(s for s in undecided_steps if s),
            # ⚠ NAME THE SOURCE. This is derived from the genesis RECORD in the
            # stream, never from config -- and rendering it without saying so read as
            # "a floor is configured" to a caller who had just seen
            # `policy.genesis.commit: None`. Measured 2026-08-23: it misled the other
            # session for a minute, which is a minute more than a status line is worth.
            "genesis": (f"records begin at {genesis['basis']['value']}; "
                        f"nothing before it is claimed "
                        f"(from the genesis RECORD, seeded {genesis['run'].get('started')}; "
                        f"the floor is not a config value)") if genesis else
                       "NO GENESIS RECORD — crossref cannot bound its history",
        }
