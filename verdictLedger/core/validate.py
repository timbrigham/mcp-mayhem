"""V1–V23. Each rule makes a defect this project has already paid for UNREPRESENTABLE.

⚠ Every violation is returned, never just the first. A caller fixing one rule per
round trip is a caller who stops using the thing.

⚠ A record that fails is NOT stored and NOT silently dropped: `append` raises with
the rule named, and the caller treats that as UNDECIDED.
"""

from __future__ import annotations

from typing import Optional

from core import schema
from core.config import Config

SIGNABLE_EXEMPT_FAMILIES = ()      # reserved: classes that may never be signed away


def structural(record: dict) -> list[str]:
    """Shape before rules. A rule cannot judge a record it cannot read."""
    out: list[str] = []
    if not isinstance(record, dict):
        return ["record must be an object"]
    if record.get("schema") != schema.SCHEMA_ID:
        out.append(f"schema must be {schema.SCHEMA_ID!r}, got {record.get('schema')!r}")

    unknown = sorted(set(record) - set(schema.TOP_LEVEL))
    if unknown:
        # V7 lives here because it is structural: an unknown key cannot be
        # meaningfully rule-checked, only rejected.
        out.append(f"V7: unknown top-level key(s) {unknown} — rejected, not ignored")

    if not isinstance(record.get("step"), str) or not record["step"].strip():
        out.append("step must be a non-empty string")
    if record.get("tier") not in schema.TIERS:
        out.append(f"tier must be one of {schema.TIERS}, got {record.get('tier')!r}")
    if record.get("verdict") not in schema.VERDICTS:
        out.append(f"verdict must be one of {schema.VERDICTS}, got {record.get('verdict')!r}")

    basis = record.get("basis")
    if not isinstance(basis, dict):
        out.append("basis must be an object")
    else:
        if basis.get("kind") not in schema.BASIS_KINDS:
            out.append(f"basis.kind must be one of {schema.BASIS_KINDS}")
        if not basis.get("value"):
            out.append("basis.value must be set")

    # ⚠⚠ `failing` IS ONLY MEANINGFUL ON A BLOCKING VERDICT, AND A MISPLACED ONE IS THE
    # WORST SHAPE AVAILABLE: the resolver reads it only where it blocks, so a `failing` list
    # on a PASS would be accepted, stored, and silently ignored — a record that LOOKS like it
    # narrows an indictment while narrowing nothing. Rejected rather than ignored, for the
    # same reason V7 rejects unknown keys.
    #
    # ⭐⭐ UNDECIDED ADMITS IT TOO, AND REFUSING IT WAS A REAL HOLE — mine, found by reading
    # my own guard against the copy-editor panel it was about to block. Tim, 2026-09-05:
    # three copy editors, two must agree, and *"the undecided is a perfect use case here when
    # the three copy editors disagreeing"*. A 2–1 split over forty files is UNDECIDED about
    # the ONE line they disagree on and perfectly decided about the other thirty-nine. With
    # `failing` refused on UNDECIDED, the panel's only legal move was a record that blocks all
    # forty — so the vocabulary Tim added to express a NARROW disagreement could only be
    # spelled as a WIDE one.
    #
    # ⚠ That is the 2026-09-02 `check_checkers` defect exactly, arriving through the door
    # built to stop it: one real dispute condemning every file examined beside it. The
    # difference is that this time the wide record would have been the only representable
    # one, which makes it worse than a malformed record — it would have been a CORRECT one.
    #
    # ⛔ PASS STILL REFUSES, and that asymmetry is the whole safety of the field. FAIL and
    # UNDECIDED both BLOCK, so narrowing one moves paths from blocked to clear and the reader
    # can see which. A PASS blocks nothing; `failing` there could only ever mean something the
    # resolver does not implement, and V18 already governs what a PASS may carry.
    # ⚠ V19 IS NOT HERE, AND THE NEUTER CONTROL IS WHY. It was first written in this
    # function, and `test_neuter_control_every_probe_depends_on_the_rules` — which stubs the
    # rule engine and asserts every probe goes green — stayed RED. A probe that survives the
    # rules being switched off is testing a proxy, not the rule. V19 is policy about what a
    # blocking verdict must CARRY, not about whether the record can be READ, so it lives in
    # `rules()` with V1-V23.
    if "failing" in record:
        failing = record.get("failing")
        if not isinstance(failing, list) or not all(
                isinstance(p, str) and p.strip() for p in failing):
            out.append("failing must be an array of non-empty path strings")
        elif record.get("verdict") not in ("FAIL", "UNDECIDED"):
            out.append(
                f"failing is only meaningful on a verdict that BLOCKS — FAIL or UNDECIDED — "
                f"got {record.get('verdict')!r}. It names the subset a blocking verdict "
                f"actually indicts, so on a non-blocking verdict it would be stored and "
                f"silently ignored. A PASS that wants to carry findings uses `outstanding`, "
                f"which V18 grades.")
        elif failing and not (set(failing) & {s.get("path") for s in (record.get("subjects") or [])
                                              if isinstance(s, dict)}):
            # ⚠⚠ A DISGUISED EXONERATION, AND IT IS THE EMPTY-`failing` HOLE WEARING A HAT.
            # Entries that are not subjects are INERT for resolution — nothing resolves a
            # pseudo-path like `tools/verify/(roster)` to content. So a `failing` naming ONLY
            # non-subjects indicts nothing resolvable, and the FAIL reads as a PASS at every
            # path it covers. At least one entry must be a real subject of this record.
            # ⚠ Naming pseudo-paths ALONGSIDE real ones stays legal and is encouraged: the
            # roster-level finding is a true indictment that happens not to be a file.
            out.append(
                f"failing names no subject of this record — every entry is inert for "
                f"resolution, so the {record.get('verdict')} would resolve to a PASS "
                f"everywhere it covers. At least one entry must be a path this record "
                f"actually examined.")
        elif not failing:
            # ⚠ An EMPTY list would read as "this FAIL indicts nothing", which resolves to a
            # PASS everywhere — a FAIL that cannot fail. Absent means all-subjects; empty must
            # not be a quiet way to spell exoneration.
            out.append(
                f"failing must not be empty on a {record.get('verdict')} — an empty "
                f"indictment resolves to a PASS at every path, which is a verdict that "
                f"blocks nothing while claiming to block. Omit the field to indict every "
                f"subject.")

    subjects = record.get("subjects")
    if not isinstance(subjects, list):
        out.append("subjects must be an array")
    else:
        for i, s in enumerate(subjects):
            if not isinstance(s, dict) or not s.get("git_blob_id") or not s.get("path"):
                out.append(f"subjects[{i}] needs both git_blob_id and path")
                continue
            bad = _not_a_blob_id(s["git_blob_id"], s.get("path"))
            if bad:
                out.append(f"subjects[{i}] {bad}")

    ev = record.get("evidence")
    if not isinstance(ev, list):
        out.append("evidence must be an array")
    else:
        for i, e in enumerate(ev):
            if not isinstance(e, dict) or not e.get("git_blob_id") or not e.get("path"):
                out.append(f"evidence[{i}] needs both git_blob_id and path")
                continue
            bad = _not_a_blob_id(e["git_blob_id"], e.get("path"))
            if bad:
                out.append(f"evidence[{i}] {bad}")

    out_list = record.get("outstanding")
    if not isinstance(out_list, list):
        out.append("outstanding must be an array")
    else:
        for i, o in enumerate(out_list):
            if not isinstance(o, dict):
                out.append(f"outstanding[{i}] must be an object")
                continue
            if not (o.get("severity") or "").strip():
                out.append(f"outstanding[{i}] needs a severity")
            if not (o.get("note") or "").strip():
                out.append(f"outstanding[{i}] needs a note — a finding nobody can "
                           f"read is not carried, it is lost")

    decided = record.get("decided")
    if not isinstance(decided, dict):
        out.append("decided must be an object")
    elif decided.get("how") not in schema.DECIDED_HOW:
        out.append(f"decided.how must be one of {schema.DECIDED_HOW}")

    if not isinstance(record.get("inputs"), list):
        out.append("inputs must be an array")
    rev = record.get("revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 0:
        out.append("revision must be a non-negative integer")
    if not isinstance(record.get("run"), dict):
        out.append("run must be an object")
    return out


def rules(record: dict, *, config: Config, existing_ids: set,
          tips: Optional[dict] = None, known_config_shas: Optional[set] = None,
          timed_steps: Optional[set] = None) -> list[str]:
    """V1–V23. ``tips`` maps ``(step, basis_value)`` -> the highest-revision record.

    ``timed_steps`` is the set of steps that have ever reported ``cost.seconds`` — V22's
    ratchet memory, from ``store.steps_timing()``. ⚠ ``None`` means the index was NOT
    SUPPLIED, which is a wiring fault rather than a clean record; see V22 for why that is
    pinned by a test instead of guessed at here.
    """
    out: list[str] = []
    basis = record.get("basis") or {}
    decided = record.get("decided") or {}
    run = record.get("run") or {}
    verdict = record.get("verdict")
    how = decided.get("how")

    # V15 — ⭐⭐ A SUBJECT SET IS EVERYTHING THE VERDICT DEPENDS ON, not merely
    # everything the checker read. Measured by ZeroParadox 2026-08-23: `check_pov`
    # recorded 291 subjects and NOT `pov_baseline.txt`, so grandfathering a new
    # violation into that baseline left the record reading SATISFIED -- every file it
    # named was unchanged. The verdict changed; the record could not tell.
    #
    # A convention cannot hold this: a record missing its switch looks perfectly
    # healthy and simply never goes stale, so the next checker to forget reintroduces
    # the hole invisibly. With the switch as a subject, editing a baseline moves a blob
    # the record names, the key goes STALE, and the checker re-runs.
    step_name = record.get("step")
    spec = (config.requirements() or {}).get(step_name) if step_name else None
    declared = list((spec or {}).get("switches") or [])
    # ⭐⭐ V19 — A BLOCKING VERDICT MUST SAY WHICH BYTES IT CONDEMNS. Landed 2026-09-07,
    # AFTER the consumer's emitter, in that order and never the reverse.
    #
    # ⚠⚠ ABSENT `failing` MEANS ALL SUBJECTS ARE INDICTED — absence carrying a MAXIMAL claim,
    # silently. Tim, this afternoon: *"absence should render as unknown, not pass."* The same
    # argument refuses absence rendering as EVERYTHING. `check_checkers` examined 24 files,
    # failed on one, and condemned all 24 — with the narrow set sitting in a local variable
    # (`LED-10a`). Worst-verdict-wins then read FAIL for every commit sharing those 23
    # innocent blobs, including one that predated the bad file existing.
    #
    # ⛔ WHY THIS IS ENFORCED HERE AND NOT ONLY IN THE CLIENT. All three emitter routes now
    # guarantee it — `common.py`'s `verdict = 'FAIL' if bad else 'PASS'` IS that identity, `agent_gate`
    # inherits it, and `record.py`'s CLI refuses the flagless case as of `acbe1c7`. **But that
    # guarantee lives entirely in the consumer's repo**, in a file whose own header says
    # editing it "stales EVERY mechanical step at once" — so it will be edited again, and an
    # identity is one refactor from being a policy someone gets wrong. `CLAUDE.md`: *"a rule
    # living in a client is a rule with one copy and no enforcement."* The gated party must
    # not be the sole enforcer of the gate.
    #
    # ⚠ HISTORICAL RECORDS ARE UNTOUCHED. Validation runs at APPEND; nothing re-validates the
    # stream. The 118 tier-A blocking records carrying no `failing` stay exactly as they are —
    # correcting one is a re-emission at a higher revision, a separate decision nobody made.
    # ⛔⛔ FAIL ONLY, NOT UNDECIDED, AND THE TEST SUITE REFUTED THE BLANKET VERSION.
    # `test_v16b_does_not_stop_a_dying_checker_recording_that_it_died` went red on the first
    # draft, and the design it defends is right: *"`failing` is the discriminator — if you
    # were specific enough to name which files defeated you, you were alive enough to name
    # yourself."* A checker that CRASHED cannot name a subset. Requiring one would stop it
    # recording that it died, and the step would render MISSING rather than UNDECIDED —
    # absence rendering as NOTHING instead of as unknown, which is the worse of the two and
    # the opposite of what this rule is for.
    #
    # ⭐ THE LINE IS CAPABILITY, NOT SAFETY DIRECTION. Both a wide FAIL and a wide UNDECIDED
    # are fail-CLOSED. The difference is that a FAIL always COULD have named its subset —
    # `check_checkers` had `_bad` sitting in a local variable while it condemned all 24 — and
    # a dead checker could not. Require it where the emitter had the answer and withheld it.
    #
    # ⚠ UNDECIDED stays governed by V16b: carrying `failing` obliges `evidence`; carrying
    # neither is the dying-checker case and stays recordable.
    if record.get("verdict") == "FAIL" and not record.get("failing"):
        out.append(
            "V19: a blocking verdict must name what it indicts. `failing` is absent or "
            "empty, which the resolver reads as INDICTING EVERY SUBJECT — a maximal claim "
            "made by omission. SATISFIED WHEN: `failing` lists the subset this verdict "
            "actually condemns; if it genuinely condemns all of them, pass the full subject "
            "list and say so explicitly. Absence is not a way to spell 'all'.")

    # ⭐⭐ V21 — EVERY VERDICT MUST NAME THE BLOB IT WAS PRODUCED FROM. Landed 2026-09-08.
    #
    # Tim: *"every entry needed a blob."* This is the rule; V20 is only the registry half of it.
    #
    # ⛔ WHY `how` MUST NOT GATE THIS, WHICH IS THE DEFECT. V16 requires evidence only when
    # `how == "mechanical"`. Measured 2026-09-08: `adversary` is 62/66 `delegated` and
    # `editorial` 51/55 — so V16 never fires on either, and NINE records across the two carry
    # no evidence at all. Those nine can never go STALE, because staleness is computed by
    # watching a named blob move and they name none. They are permanent verdicts.
    #
    # ⭐ THE PROPERTY THIS PROTECTS IS THE ONE THAT MAKES SELF-ENTERED GRADES SAFE. Subagents
    # record their own verdicts by design; what makes that sound is not review but EXPIRY —
    # "a forged verdict expires the next time the code it lied about changes." Expiry is
    # entirely a function of naming a blob. A record with no blob opts out of the only control
    # that was ever holding it, and it does so silently, by omission.
    #
    # ⚠ 62 of 66 already comply. This is not new behaviour being imposed; it is a convention
    # that four records quietly skipped being made unrepresentable.
    # ⚠ TWO SCOPE LIMITS, BOTH DELIBERATE AND BOTH MEASURED.
    # (1) `signature` and `override` ATTACH to a verdict somebody else produced — they are
    #     attestations, not gradings, and have no producing artifact of their own. Live
    #     ledger 2026-09-08: 4 signatures and 2 overrides carry no blob, correctly.
    # (2) It rides the SAME cutover switch as V16 rather than inventing a second one. V21 is
    #     V16's requirement generalised off `how`, so a registry mid-migration must be able
    #     to stage both together; two levers for one cutover is how they drift apart. The
    #     switch DEFAULTS STRICT, so the rule holds unless somebody explicitly relaxes it.
    ev = record.get("evidence")
    if (how not in ("signature", "override") and config.v16_required
            and not (isinstance(ev, list)
                     and any(isinstance(e, dict) and (e.get("git_blob_id") or "").strip()
                             for e in ev))):
        out.append(
            "V21: this verdict names no blob, so it can never be shown stale — staleness is "
            "computed by watching a named blob move. Satisfied when `evidence` carries at "
            "least one entry with a `git_blob_id`: the checker for a mechanical step, the "
            "brief for a delegated one — whatever produced this verdict.")

    # ⭐⭐ V20 — A STEP MUST DECLARE ITS PRODUCER, OR IT CANNOT RECORD. Landed 2026-09-08.
    #
    # Tim, 2026-09-08: *"everything is supposed to have some kind of pin for marking scope"*
    # and, on being told a refusal would brick six gating steps: *"bricking bad tooling until
    # it's fixed is good."* That overrules the earlier disclosure-only stance, deliberately.
    #
    # WHAT IT COSTS TO BE WRONG THE OTHER WAY. Measured on the live registry 2026-09-08:
    #     16 pinned · 4 declaring a module with no pin · 9 declaring NO module at all
    # and `policy()` reported "4 unpinned", because `unpinned_modules` asks "has a module but
    # no approved_modules" and is structurally blind to the nine. Six of those nine GATE —
    # adversary, build, editorial, pdf_coupling gate commit or push; release_ready and rely
    # gate tag. A verdict from a step with no declared producer cannot be tied to the code or
    # brief that reached it, so its staleness can never be computed: it is a claim with no
    # author that never expires.
    #
    # ⛔ THIS IS THE DECLARATION HALF ONLY, AND THE SPLIT IS DELIBERATE. Requiring
    # `approved_modules` too would be the full pin, but it entangles with V16c — which
    # compares the approved blob against the live tree — and every sample-config type would
    # need a blob id that matches whatever a test happens to put in `files`. Declaration is
    # checkable with no tree at all. `unpinned_modules` still discloses the build half, and
    # that is the next ratchet, not a rule quietly dropped.
    #
    # ⚠ ESCAPABLE BY DESIGN, WHICH IS THE ONLY REASON IT IS SAFE TO BRICK COMMIT. `build` and
    # `pdf_coupling` gate COMMIT, so a refusal here blocks the very commit that would fix the
    # registry — the exact deadlock class this session spent the day removing. It is not one,
    # because `server._ledger()` builds a fresh `Ledger` per call *"so config edits take
    # effect without a restart"*: declaring the producer in the working-tree registry is live
    # on the next append, with no commit and no restart. If that factory is ever made to
    # cache, THIS RULE BECOMES A DEADLOCK and must be revisited with it.
    if isinstance(step_name, str) and config.is_registered(step_name):
        _raw = ((config.required or {}).get("types") or {}).get(step_name) or {}
        _module = _raw.get("module")
        if not (isinstance(_module, str) and _module.strip()):
            out.append(
                f"V20: step {step_name!r} declares no `module`, so no producer can be pinned "
                f"and this verdict could never be shown stale. Satisfied when "
                f"`required.v2.json` gives {step_name!r} a `module` naming the file that "
                f"produces its verdicts (the checker for a mechanical step, the brief for a "
                f"review step); the edit is live on the next append, no restart needed.")

    if declared:
        named = {s.get("path") for s in (record.get("subjects") or [])
                 if isinstance(s, dict)}
        absent = [p for p in declared if p not in named]
        if absent:
            out.append(
                f"V15: step {step_name!r} declares switches {absent} that are not among "
                f"its subjects. A verdict that depends on an exemption list must NAME "
                f"it, or editing that list cannot make the key stale and a suppression "
                f"lands unverified.")

    # V16 — ⭐⭐ A MECHANICAL PASS MUST CARRY EVIDENCE ONLY A RUN PRODUCES.
    # Measured by ZeroParadox 2026-08-24 with `validate` (pure, no write): a record
    # claiming `tier:"M"`, `decided.how:"mechanical"`, `verdict:"PASS"` over real blob
    # IDs at a real basis returned `ok: true, errors: []`. An agent can certify that a
    # checker ran when it did not, and a spawned agent already reaches `append`.
    #
    # The only rule forbidding it lived in a CLIENT — `record.py`'s CLI mirror, whose
    # `--tier` accepts A/H and whose `--how` refuses `mechanical` — while that file's
    # own docstring says the rules live in the server "in exactly one place… what makes
    # the mirror defect unrepresentable rather than avoided by discipline". That rule
    # was the exception, and its only enforcing copy was on a path §12j removes.
    #
    # ⚠ THIS IS NOT AUTHENTICATION AND MUST NOT PRETEND TO BE. §2 rules out keys and
    # tokens; `sign` already concedes that a signature is an ATTRIBUTION. Naming the
    # module is forgeable by anyone willing to copy a blob id. The bar is CHECKABLE,
    # which the previous state was not, and it buys a second property that is not
    # forgeable at all: `inventory` treats evidence like a switch, so editing the
    # checker moves a blob the record names and the key goes STALE. A forged verdict
    # then expires the next time the code it lied about changes.
    #
    # ⚠ PASS ONLY, exactly like V2. A forged mechanical FAIL blocks, and blocking
    # wrongly is not the failure this system defends against; requiring evidence there
    # would also stop a checker that died before it could hash itself from recording
    # the fact that it died.
    # ⭐⭐ V16b — A MECHANICAL `UNDECIDED` THAT NAMES A SUBSET MUST NAME ITS OWN CHECKER.
    #
    # Added 2026-09-06 for the escalation path: a mechanical step that reaches the limit of what
    # it can judge records UNDECIDED, and something hands the failing bytes to an agent round
    # which supersedes at a higher revision. That handoff needs the CODE THAT GAVE UP, not a
    # description of it — `evidence` carries [{path, git_blob_id}], so the agent reads the exact
    # checker at the exact version, reconstructable from git alone.
    #
    # ⛔ AND IT IS DELIBERATELY NOT A BLANKET REQUIREMENT, because the comment below already
    # ruled that out and was right: "requiring evidence there would also stop a checker that DIED
    # before it could hash itself from recording the fact that it died." A crashed checker must
    # keep its ability to say so. So two different UNDECIDEDs exist and only one is escalatable:
    #
    #   "I ran and reached my limit"  -> knows WHICH bytes defeated it -> carries `failing`
    #   "I died"                      -> knows nothing                 -> carries no `failing`
    #
    # ⭐ `failing` IS THEREFORE THE DISCRIMINATOR, and the rule reads: **if you were specific
    # enough to name which files you could not judge, you were alive enough to name yourself.**
    # An UNDECIDED with no `failing` indicts every subject, is fail-closed, and stays recordable
    # by a checker in the middle of dying.
    #
    # ⚠ ZERO MIGRATION COST, AND THAT WINDOW IS WHY THIS LANDS NOW. There are 0 UNDECIDED records
    # in 2,313 and no producer has ever emitted one — the CLI could not until 2026-09-06. Every
    # producer is still unbuilt, so this is a rule the first one is born under rather than one
    # retrofitted onto a corpus.
    if (how == "mechanical" and verdict == "UNDECIDED" and config.v16_required
            and record.get("failing") and not (record.get("evidence") or [])):
        out.append(
            "V16b: a mechanical UNDECIDED that names `failing` must also carry `evidence` — "
            "[{path, git_blob_id}] for the checker module that could not decide. Naming WHICH "
            "bytes defeated you means you were running well enough to name YOURSELF, and an "
            "escalation cannot hand an agent the code that gave up unless the record says which "
            "code it was. SUPPLY IT: pass `evidence=record.module_evidence(__file__)`. A checker "
            "that DIED records UNDECIDED with no `failing` — that indicts every subject, is "
            "fail-closed, and is deliberately still allowed with no evidence.")

    if how == "mechanical" and verdict == "PASS" and config.v16_required:
        evidence = record.get("evidence") or []
        if not evidence:
            out.append(
                "V16: a mechanical PASS must carry `evidence` — at minimum "
                "[{path, git_blob_id}] for the checker module that produced it, so the "
                "verdict names the code that reached it. Emitters: pass "
                "`evidence=record.module_evidence(__file__)` through "
                "`common.record_if_asked`. `inputs` is NOT the place for it: V4 requires "
                "every inputs entry to name a record already in the stream.")
        else:
            module = (spec or {}).get("module")
            named = {e.get("path") for e in evidence if isinstance(e, dict)}
            if module and module not in named:
                out.append(
                    f"V16: step {step_name!r} declares module {module!r}, which is not "
                    f"among its evidence paths {sorted(p for p in named if p)}. A "
                    f"mechanical verdict must name the module the registry says "
                    f"implements it, or the evidence field certifies some other file.")

            # ⭐⭐ V16c — WHICH VERSION OF THE TOOL, not merely which file.
            #
            # V16 above pins the step to a PATH: `check_prose` verdicts must name
            # `tools/verify/check_prose.py`. That answers "was this recorded by the right tool"
            # and not "was it recorded by an APPROVED BUILD of it" — an edited checker records
            # exactly as happily as a reviewed one, because a path is not a version.
            #
            # `approved_modules` closes that: a list of git blob ids the registry accepts for
            # this step's module. Evidence carries `{path, git_blob_id}` already, so nothing new
            # is transmitted and no key exists anywhere — the identity is the CONTENT, verifiable
            # against git by anyone, which is the same instrument the whole ledger already rests
            # on.
            #
            # ⛔⛔ ABSENT MEANS UNPINNED AND IS DISCLOSED, NEVER SILENTLY PERMITTED. A step with
            # no `approved_modules` still records — refusing every unpinned step would brick all
            # 20 mechanical steps the moment this shipped, which is an outage, not a loud
            # failure. Instead `Config.unpinned_modules` enumerates exactly which steps are
            # running unpinned, and `policy()` returns it on every call beside `defaulted`.
            # **The absence is a fact the caller is told, not a default nobody can see.**
            #
            # ⚠ Tim, 2026-09-06, on the two-step cost of pinning (edit the tool, then approve its
            # new hash): *"the 'silently can't record' is the problem. fail loudly."* So a
            # VIOLATED pin refuses with the actual blob in the message, ready to paste — the next
            # attempt is on different bytes, so naming the bytes that failed is useless without
            # naming the bytes to approve.
            # ⛔⛔ ON A NEW BUILD: REPLACE THE HASH, DO NOT ACCUMULATE. Decided 2026-09-06.
            #
            #   * GIT IS ALREADY THE HISTORY. `required.v2.json` is versioned, so every past
            #     approved set is recoverable with `git log -p`. A list inside the field
            #     duplicates what git content-addresses, and the duplicate is the copy that rots.
            #   * AN ACCUMULATING LIST STOPS BEING A PIN. Approve v1, v2, v3, v4 and eventually
            #     every build ever written is approved — still LOOKING pinned while constraining
            #     nothing. That is `RLY31-6`'s shape: a control that decayed into permissiveness
            #     while appearing to hold, with nothing positioned to notice.
            #   * OLD RECORDS DO NOT NEED IT. Nothing re-validates the stored stream; `validate`
            #     runs only at append. A record made under v1 stays exactly as valid as the day
            #     it landed, whatever the registry says now.
            #
            # ⚠ THE ONLY LEGITIMATE PAIR IS A ROLLOUT WINDOW — v2 shipping while a run is in
            # flight on v1. If you take it, give the second entry a STATED EXPIRY the way
            # `copy_editor`'s `_why_not_admitted_yet` does, or the transitional pair quietly
            # becomes permanent.
            #
            # ⭐ AND THE TWO-STEP COST IS SMALLER THAN IT LOOKS, because editing a checker
            # ALREADY stales every row it produced — `inventory` compares `evidence` blobs
            # against current content and reports "every subject still matches, but the producer
            # changed". A v2 therefore means re-running that step regardless. Approving the new
            # blob is one line in the same commit that ships the code, not a separate chore.
            approved = (spec or {}).get("approved_modules")
            if module and approved:
                got = {e.get("git_blob_id") for e in evidence
                       if isinstance(e, dict) and e.get("path") == module}
                if got and not (got & set(approved)):
                    actual = sorted(g for g in got if g)
                    out.append(
                        f"V16c: step {step_name!r} was produced by an UNAPPROVED build of "
                        f"{module!r}. Evidence names blob {actual[0] if actual else '?'}, and "
                        f"the registry approves {sorted(approved)}. A path says which tool ran; "
                        f"a blob says which VERSION of it, and only the second is reviewable. "
                        f"SATISFIED WHEN: either record with an approved build, or add this "
                        f"blob to `approved_modules` for {step_name!r} in the registry — which "
                        f"is a REVIEWABLE EDIT in the same history as the tool change, and is "
                        f"the point of pinning rather than an obstacle to it.")

    # V17 — ⭐⭐ A DELEGATED VERDICT NAMES THE BRIEF IT RAN UNDER.
    # Tim, 2026-08-25: "the entire idea having these agents is so that I can delegate
    # trust to them." Before this, no delegated review could record a PASS at all --
    # `agreement` refuses one round (V3), `mechanical` is a lie about a computation,
    # and `signature` means a HUMAN accepted. Measured the same day: NINE agent review
    # records in the stream, every one a FAIL.
    #
    # ⚠ THE ACCOUNTABILITY IS THE BRIEF, NOT A PROCESS IDENTITY. §2 rules out keys and
    # `sign` concedes attribution is not authentication, so "prove you are that agent"
    # was never on the table. What IS checkable: which instructions governed the round,
    # and whether they have changed since. `evidence` names the brief's blob, so
    # `inventory` stales the key the moment the brief is edited and the gate re-runs.
    # A delegated verdict cannot outlive the instructions it was made under.
    #
    # ⚠ STRICT FROM DAY ONE, and this is the one place that is free. A NEW enum value
    # has no existing traffic to brick -- every rule here could only ever refuse a
    # record that does not exist yet. V16 needed a relaxation and a cutover precisely
    # because it constrained records already flowing.
    if how == "delegated":
        who = (decided.get("who") or "").strip()
        if not who:
            out.append(
                "V17: how 'delegated' requires `who` — the gate or brief that judged "
                "this. A finding attributed to nobody is the anonymous-approval hole "
                "V5 closes, arriving through the review door instead of the human one.")
        if record.get("tier") != "A":
            # ⚠ The NARROW case of LED-7 (tier and `how` disagreeing), closed here for
            # `delegated` only. A delegated round is an AI round: 'M' claims a
            # computation and 'H' claims a person. LED-7 stays open for the rest --
            # one moving part at a time.
            out.append(
                f"V17: how 'delegated' is an AI round, so tier must be 'A', got "
                f"{record.get('tier')!r}. 'M' claims a computation and 'H' claims a "
                f"person decided; both are a different verdict than the one that "
                f"happened.")
        if verdict == "PASS" and not (record.get("evidence") or []):
            out.append(
                "V17: a delegated PASS must carry `evidence` naming the brief it ran "
                "under — [{path, git_blob_id}] for e.g. `.claude/commands/<gate>.md`. "
                "That is what makes the verdict expire when the brief changes, and it "
                "is the whole of the accountability: not who ran it, but under which "
                "instructions, over which bytes.")

    # ⭐⭐ V23 — A VOTED PANEL, WHICH V3 MADE UNREPRESENTABLE. Tim's ruling 2026-09-27.
    #
    # ⚠⚠ THE GAP WAS NAMED AND DEFERRED SINCE 2026-09-08 and expired without anyone noticing:
    # `copy_editor._module_why` recorded the tension between a 2-of-3 brief and V3's unanimity
    # "unresolved on purpose … `copy_editor` is admitted by nothing so nothing is gated on the
    # answer." Admitting it at push voided that premise, and the first real panel run split 2-of-3
    # with no honest way to record it: V3 refuses a non-unanimous `agreement` PASS, and the only
    # route left was re-running until uniform — which the consumer's own registry calls
    # "blocking on a coin flip", since byte-identical input is measured to return different
    # verdicts, and which re-rolls until the DISSENTER disappears.
    #
    # ⛔ WHAT MAKES A VOTE SAFE IS V18, NOT THIS RULE, and that is why this one is short.
    # `SEVERITY_ON_A_PASS` is `("ordinary",)`, so a reader grading BEDROCK or BLOCKING makes a
    # passing record UNREPRESENTABLE however the tally fell. The threshold only ever decides
    # ORDINARY matters. ⚠ Safe only while findings UNION across readers and only the VERDICT is
    # voted — an EMITTER obligation this server cannot check, because it sees what the record
    # carries and not how many readers found what.
    if how == "panel":
        passes, agreed = decided.get("passes"), decided.get("agreed")
        thr = decided.get("threshold")
        floor = config.panel_min_threshold
        if not (decided.get("who") or "").strip():
            out.append(
                "V23: how 'panel' requires `who` — which panel decided. Same argument as "
                "`delegated`: the accountability is not a process identity, it is WHICH gate ran "
                "under WHICH brief, and a tally with nobody attached is a number without a "
                "claimant. SUPPLY decided.who=<the panel, e.g. 'copy_editor panel (3 readers)'>.")
        if not all(isinstance(v, int) and not isinstance(v, bool)
                   for v in (passes, agreed, thr)):
            out.append(
                "V23: how 'panel' requires integer decided.passes, decided.agreed and "
                "decided.threshold. ⚠ `threshold` is the threshold that APPLIED and belongs on "
                "the record, not only in policy: policy can be edited later, and a stored verdict "
                "must keep saying which rule it met.")
        else:
            if thr < floor:
                out.append(
                    f"V23: decided.threshold is {thr}, below the floor of {floor} "
                    f"(policy.panel.min_threshold, default 2). A threshold of 1 is a SINGLE AGENT "
                    f"WEARING A PANEL BADGE, which is exactly what V3 refuses for `agreement` — "
                    f"and a panel whose divergence signal cannot exist is not a panel. SUPPLY a "
                    f"threshold of at least {floor}, or raise the floor deliberately in policy.")
            if passes < thr:
                out.append(
                    f"V23: decided.passes is {passes} and decided.threshold is {thr} — fewer "
                    f"readers RAN than the verdict claims agreed. SUPPLY passes >= threshold; if "
                    f"only {passes} reader(s) ran, the honest threshold is at most {passes}.")
            if agreed > passes:
                out.append(
                    f"V23: decided.agreed is {agreed} of decided.passes {passes} — more readers "
                    f"agreed than ran. SUPPLY agreed <= passes.")
            if verdict == "PASS" and agreed < thr:
                out.append(
                    f"V23: a PASS claims the panel's threshold was met, and {agreed} of {passes} "
                    f"agreed against a threshold of {thr}. ⭐ THIS IS NOT A DEAD END: a split "
                    f"below threshold is honestly recorded as UNDECIDED, which blocks and carries "
                    f"`failing` naming the disputed subset — and a human may then accept it with "
                    f"sign(who=…). SUPPLY verdict='UNDECIDED' for a split, or agreed >= {thr}.")
        # ⭐ SAME REQUIREMENT AS V17's DELEGATED PASS, FOR THE SAME REASON RATHER THAN BY ANALOGY.
        # A panel's accountability is the brief its readers ran under, so naming the brief's blob
        # is what makes the verdict EXPIRE when the brief is edited — the key goes stale and the
        # panel re-runs. A verdict that outlives its instructions is the thing this buys.
        if verdict == "PASS" and not (record.get("evidence") or []):
            out.append(
                "V23: a panel PASS must carry `evidence` naming the brief its readers ran under "
                "— [{path, git_blob_id}] for e.g. `.claude/commands/<gate>.md`. That is what "
                "makes the verdict expire when the brief changes, and it is the whole of the "
                "accountability: not who ran it, but under which instructions, over which bytes.")

    # V18 — ⭐⭐ A PASS MAY CARRY FINDINGS, AND ONLY ORDINARY ONES.
    # Tim ruled 2026-08-26 that STOP-ORDINARY is a PASS condition: reviewed, ordinary
    # findings outstanding, loop cap reached, PROCEED. Before this the record had only
    # pass and fail, so editorial round 6 recorded FAIL with the reason line explaining
    # itself — the agent refusing to paper over a vocabulary gap, which was right.
    #
    # ⚠⚠ THE SEVERITY SPLIT IS THE ENTIRE SAFETY OF THIS, so `ordinary` is the ONLY
    # value that may appear on a PASS. Anything else — bedrock, blocking, or a word
    # this rule has never heard of — REFUSES. That direction matters: an unrecognised
    # severity must not sail through on the assumption it is minor, and enumerating
    # every gate's vocabulary here would mean a gate inventing a new word gets a free
    # pass until someone updates a list. `rely` grades BLOCKING/ORDINARY and editorial
    # grades BEDROCK/ORDINARY; only the shared word admits.
    #
    # ⚠ IT IS AN ATTRIBUTED JUDGEMENT, NOT A MEASUREMENT, and the record says by whom.
    # Severity is the reviewing agent's own claim — `rely.md` names the temptation
    # exactly: "do not inflate a finding to BLOCKING to keep the loop alive, and do
    # not deflate one to end it." Nothing here can detect a deflated finding. What it
    # can do is make the claim attributable, and V17 already does: `who` on every
    # delegated record, `evidence` naming the brief on a delegated PASS. So a later
    # reader sees who called it ordinary and under which instructions.
    #
    # ⚠ FAIL and UNDECIDED may carry anything. They already block; constraining the
    # severity there would only stop a gate reporting what it found.
    if verdict == "PASS":
        for i, o in enumerate(record.get("outstanding") or []):
            if not isinstance(o, dict):
                continue
            sev = (o.get("severity") or "").strip().lower()
            if sev not in schema.SEVERITY_ON_A_PASS:
                out.append(
                    f"V18: outstanding[{i}] has severity {o.get('severity')!r}; a PASS "
                    f"may only carry {schema.SEVERITY_ON_A_PASS}. STOP-ORDINARY is a "
                    f"pass condition BECAUSE the findings were judged ordinary — that "
                    f"split is the whole safety of it, and this must never become a "
                    f"route to ship a bedrock or blocking finding. Record FAIL, or "
                    f"re-grade the finding honestly and say who did.")

    # V1 — a silent fallback to a permissive basis is FRZ-4. Recording it as
    # FALLBACK is what makes basis drift visible without probing for it.
    if basis.get("resolved_from") not in schema.RESOLVED_FROM:
        out.append(f"V1: basis.resolved_from must be one of {schema.RESOLVED_FROM}")

    # V2 — warrant-satisfied-while-empty. Five measured instances.
    if verdict == "PASS" and not (record.get("subjects") or []):
        # ⚠⚠ NAME THE COMMON CAUSE, NOT JUST THE FACT. Measured 2026-08-29: with an
        # EMPTY INDEX, `ledger_subjects` correctly fences every edited path (worktree
        # differs from index), the subject list comes back empty, and three checkers
        # reported `exit 1` / `exit 2 — ran, but its verdict was NOT RECORDED`. That
        # reads as three broken checkers. All five passed and recorded the moment
        # anything was staged — same command, same bytes on disk, only the index
        # changed. The ZP session ran each checker bare, then with --block, then with
        # --block --record before the basis was the variable it looked at.
        #
        # The old text said only that a step cannot pass having examined nothing —
        # true, and it points at the CHECKER. §3's rule applies here as everywhere: a
        # refusal that does not name the alternative sends the reader somewhere else.
        # This is the third of my messages to do that (V9 cost a preflight cycle, V11
        # sent them to supersede when staging was the answer), and all three share one
        # shape: written from the RULE's point of view rather than the caller's.
        out.append("V2: verdict PASS with an empty subjects array — a step cannot "
                   "pass having examined nothing. ⚠ IF YOU ARE RECORDING AGAINST THE "
                   "INDEX AND NOTHING IS STAGED, THAT IS THE CAUSE: every edited path "
                   "differs from the index, `ledger_subjects` fences all of them, and "
                   "the subject list arrives empty. The checker is fine — stage the "
                   "paths you edited and re-run. Otherwise the step genuinely examined "
                   "nothing, and that is the defect this rule exists to catch.")

    # V3 — fake unanimity, and single-pass AI verdicts wearing an agreement badge.
    if verdict == "PASS" and how == "agreement":
        passes, agreed = decided.get("passes"), decided.get("agreed")
        if not isinstance(passes, int) or not isinstance(agreed, int):
            out.append("V3: agreement requires integer passes and agreed")
        else:
            if agreed != passes:
                out.append(f"V3: agreement requires agreed == passes ({agreed} != {passes})")
            if passes < config.min_passes:
                out.append(f"V3: agreement requires passes >= {config.min_passes} "
                           f"(policy.agreement.min_passes), got {passes}")

    # V4 — an aggregate claiming a pass over steps that never ran.
    for rid in record.get("inputs") or []:
        if rid not in existing_ids:
            out.append(f"V4: inputs references {rid!r}, which is not in the stream")

    # V5 — an anonymous human pass.
    if how == "signature" and not (decided.get("who") or "").strip():
        out.append("V5: how 'signature' requires a non-null who")

    # V6 — a block nobody can act on.
    if verdict in ("FAIL", "UNDECIDED"):
        reason = record.get("reason")
        if not (isinstance(reason, str) and reason.strip()):
            out.append(f"V6: verdict {verdict} requires a non-empty reason")

    # V8 — 'prose' and 'check_prose' silently becoming two steps, each looking
    # satisfied while the other looks missing. An unregistered type cannot record
    # AT ALL, so the pipeline blocks the moment someone wires in an unregistered
    # check — loudly, at the desk of the person who can fix it.
    step = record.get("step")
    if isinstance(step, str) and not config.is_registered(step):
        out.append(f"V8: step {step!r} is not registered in required.v2.json — "
                   f"an unregistered check cannot record, so it cannot silently not count")

    # V9 — a record that cannot be tied to the run that produced it. Without it,
    # cost-per-run and first-failure-latency are uncomputable and two verdicts from
    # one sweep cannot be told from two sweeps.
    #
    # ⚠⚠ THE MESSAGE USED TO SAY run.id "comes from the pipeline, NOT THE CALLER'S
    # IMAGINATION", AND THAT SENT A READER THE WRONG WAY. Measured 2026-08-26:
    # ZeroParadox ran seven stale checkers by hand, was refused by V9 on every one, and
    # concluded "the only way to refresh those keys is to let hooks.py run them" —
    # a whole preflight cycle to do what one exported variable does.
    #
    # It is FALSE that a caller cannot supply it. `record.emit` reads
    # `os.environ["ZPLEDGER_RUN"]`, so ANY caller sets it the same way the pipeline
    # does. Nothing here distinguishes a pipeline run from an exported string, and the
    # old wording claimed it did — the same overclaim V16 is careful not to make. This
    # is ATTRIBUTION, not authentication: it ties a verdict to a named run so a reader
    # can find the others from that run, and that is the whole claim.
    #
    # ⚠ §3's rule applies to a validation refusal as much as to a git one: a refusal
    # that does not name the alternative is how a workaround gets invented. Name it.
    #
    # ⛔⛔ AND NAME ONLY WHAT THIS SERVER CAN GUARANTEE. This message ALSO used to offer
    # "or pass --run on the CLI", and that is a claim about the CALLER'S argparse, which
    # this server cannot see and does not own. Measured 2026-09-09: `check_claude_md.py`
    # accepts [-h] [--measure] [--selftest] [--record] and has NO `--run`, so a consumer
    # refused by V9 was handed two remedies of which one did not exist for the checker
    # in their hand. They reported the environment half worked first try.
    #
    # ⚠ THAT IS THE SAME DEFECT AS THE 2026-08-26 ONE DIRECTLY ABOVE, IN THE SAME
    # SENTENCE, WITH THE SIGN FLIPPED. The old wording refused a route that DID work; the
    # new wording offered a route that DOES NOT. Both are this server describing a caller
    # it cannot observe. `ZPLEDGER_RUN` is different in kind: `record.emit` and
    # `Ledger.append` both read it here, in this repo, so it is the one route a refusal
    # written on this side can promise. A second route that MIGHT exist does not add
    # help; it adds a coin flip to a message whose whole job is to end one.
    if not (run.get("id") or "").strip():
        out.append("V9: run.id is required — a verdict that cannot be tied to the run "
                   "that produced it makes cost-per-run and first-failure-latency "
                   "uncomputable, and two verdicts from one sweep indistinguishable "
                   "from two sweeps. SUPPLY IT: export ZPLEDGER_RUN=<name> before the "
                   "checker — record.emit and this server both read it from the "
                   "environment, so a hand-run sets it exactly the way the pipeline "
                   "does. It is ATTRIBUTION, not authentication — nothing here can tell "
                   "a pipeline run from an exported string, and it does not try to.")

    # V10 — policy changes silently re-qualifying every past record.
    ps = run.get("config_sha")
    if not (ps or "").strip():
        if (run.get("policy_sha") or "").strip():
            # ⚠ NAME THE RENAME. A caller still sending the old key is not making a
            # generic mistake, and "run.config_sha is required" would send them
            # looking for a field they think they already set.
            out.append("V10: run.policy_sha was RENAMED to run.config_sha on "
                       "2026-08-25 — it covers the policy AND the registry, and a name "
                       "saying otherwise misled its own author. Leave it null and the "
                       "server stamps it; do not copy the old key forward.")
        else:
            out.append("V10: run.config_sha is required — a verdict must be "
                       "interpretable against the bar that was in force")
    elif known_config_shas is not None and ps not in known_config_shas:
        out.append(f"V10: run.config_sha {ps[:12]}… names a config the ledger has "
                   f"never seen; the field would otherwise be decorative")

    # V11 / V13 — branching and endless regrading, both scoped to one basis.
    key = (step, basis.get("value"))
    rev = record.get("revision")
    if isinstance(rev, int) and not isinstance(rev, bool):
        if rev > config.max_depth:
            out.append(f"V13: revision {rev} exceeds policy.supersede.max_depth "
                       f"({config.max_depth}) — regraded to the cap; the step or the "
                       f"subject needs fixing, not another regrade")
        if tips is not None:
            seen = tips.get(key)
            occupant = (seen or {}).get("revisions", {}).get(rev)
            # ⚠ Only a DIFFERENT record in this slot is branching. The same record
            # appended twice is the same fact and dedupes, so the slot check must
            # compare PAYLOADS — the key alone cannot tell a duplicate from a
            # conflict, because both share it by definition.
            if occupant is not None and schema.payload(occupant) != schema.payload(record):
                # ⚠ NAME WHAT DIFFERS. Measured by ZeroParadox 2026-08-25 during the
                # V16 cutover: it re-ran a checker at an unchanged index, the record
                # now carried `evidence` where the stored one did not, and V11
                # correctly refused it — but said only "branching", so a one-field
                # delta read as a conflict. The rule was right; the message sent
                # someone hunting for a second record that did not exist.
                #
                # ⚠ A record differing in NOTHING never reaches here — `append`
                # dedupes identical payloads. So there is always a field to name, and
                # refusing to name it is withholding the only thing the caller needs.
                was, now = schema.payload(occupant), schema.payload(record)
                differs = sorted(k for k in set(was) | set(now)
                                 if was.get(k) != now.get(k))
                # ⚠⚠ NAME THE ORDERING RULE FIRST. Measured 2026-08-29: a checker
                # FAILED, its finding was fixed IN THE WORKTREE, and the re-run hit
                # this — because an unstaged fix leaves the INDEX unchanged, so the
                # basis is the same and the subjects are the same and the verdict
                # flipped. The message said "supersede it with revision N+1", which is
                # (a) wrong for this case and (b) not something the checker wrappers
                # can even do — they expose no --revision. A remedy the tool cannot
                # perform is LED-2's shape arriving in a validation message.
                #
                # ⚠ Staging the fix is the actual answer: it moves the index tree, so
                # the basis changes and there is no collision to supersede. The
                # supersede route is real but it is for a genuine REGRADE of content
                # that has not moved, which is the rarer case.
                out.append(f"V11: revision {rev} already exists for step {step!r} at this "
                           f"basis, with a DIFFERENT {', '.join(differs)} — "
                           f"(step, basis, revision) is unique, so branching is "
                           f"unrepresentable rather than merely detected. An identical "
                           f"record would have deduped silently; this one is a second, "
                           f"conflicting claim about the same content. "
                           f"⚠ IF YOU JUST FIXED A FINDING AND RE-RAN: STAGE THE FIX "
                           f"FIRST. An unstaged edit leaves the INDEX unchanged, so the "
                           f"basis does not move and the new verdict collides with the "
                           f"old one. `git add` the fix and re-run — the basis changes "
                           f"and there is nothing to supersede. Only if the content "
                           f"genuinely has not moved is this a REGRADE, and that is "
                           f"revision {rev + 1}. "
                           # ⛔⛔ AND THE REGRADE IS UNREACHABLE FOR A WHOLE FAMILY, WHICH THIS
                           # MESSAGE USED TO SEND THEM TO ANYWAY. The comment above already
                           # says a remedy the tool cannot perform is LED-2's shape arriving in
                           # a validation message — that was fixed for the STAGE case and left
                           # standing in the regrade clause, which is the branch a HISTORICAL
                           # basis always takes, because history cannot be staged.
                           #
                           # Measured 2026-09-25 by the ZeroParadox session, hitting exactly
                           # this: four mechanical checkers at a merge commit, all exit 2, and
                           # the named escape wired to every family except theirs. Their
                           # emitter (`tools/verify/record.py`) takes `--revision` but its
                           # `--tier` is {A, H} and `--how` is {delegated, agreement,
                           # signature, override} — no M, no mechanical — while
                           # `common.emit_verdict` exposes no revision at all.
                           #
                           # ⚠⚠ SO THE MESSAGE NOW FORECLOSES THE TWO WRONG ROUTES IT USED TO
                           # LEAVE OPEN, because a caller who cannot reach the right one will
                           # reach for a neighbour. They declined both unprompted and their
                           # reasons are the ones written here: hand-building a mechanical
                           # verdict outside the emit path is the act this system exists to
                           # prevent, and relabelling it as a review-tier `override` asserts
                           # the mechanical gate ERRED when it did not — it was produced by a
                           # build that could not see the path.
                           f"⛔ IF YOUR EMITTER CANNOT SET A REVISION — mechanical checker "
                           f"wrappers typically cannot, and a historical basis can never be "
                           f"staged — then the regrade above is NOT available to you and this "
                           f"record cannot be made by that path. Do NOT hand-build one through "
                           f"`append`, and do NOT relabel it as a review-tier `override`: the "
                           f"first bypasses the emit path this gate exists to enforce, and the "
                           f"second asserts the earlier verdict was WRONG when it was merely "
                           f"produced by a build that could not see everything. The fix is in "
                           f"the emitter, and until it exists the slot at revision {rev} holds "
                           f"whatever landed first — which is why a heal that reports success "
                           f"without clearing the step is expensive: it CONSUMES THE KEY.")
            if rev > 0 and seen is not None and (rev - 1) not in seen.get("revisions", {}):
                out.append(f"V11: revision {rev} has no revision {rev - 1} to supersede "
                           f"at this basis — a chain never crosses bases")
            if rev > 0 and seen is None:
                out.append(f"V11: revision {rev} with no prior revision at this basis")

    # V12 — "sudo it away by declaring it a false positive", the one move that
    # could otherwise unmake every rule above.
    if how == "override" and tips is not None:
        prior = (tips.get(key) or {}).get("latest")
        if prior is not None:
            prior_who = ((prior.get("decided") or {}).get("who") or "").strip()
            who = (decided.get("who") or "").strip()
            if not who:
                out.append("V12: how 'override' requires who")
            elif prior_who and who == prior_who:
                unanimous = (isinstance(decided.get("passes"), int)
                             and decided.get("passes") == decided.get("agreed")
                             and decided.get("passes", 0) >= config.min_passes)
                if not unanimous:
                    out.append(f"V12: {who!r} cannot override their own prior decision on "
                               f"this key without unanimity — otherwise a finding is "
                               f"sudo-ed away by the person it was raised against")

    # ⚠ V14 (deterministic `reason`) IS RETIRED. It existed only because `reason`
    # was an input to a per-record hash, so a checker reporting its own duration
    # would silently break dedupe. With the key reduced to (step, basis, revision)
    # the prose is payload, free to say whatever is most useful to a human, and the
    # rule it needed disappears with the hash that required it.
    #
    # ⭐⭐ AND V22 BELOW IS THE SAME FIELD, NOW MANDATORY — WHICH IS WHY THE RETIREMENT
    # NOTE STAYS HERE INSTEAD OF BEING DELETED. This file once FORBADE a checker from
    # reporting its own duration; it now requires it. The thing that changed is not the
    # policy, it is the key: `schema.payload()` excludes `cost` by name ("observational
    # fields … must not make the same fact look like a different one"), so a duration can
    # no longer make a re-run read as a conflict. **The hazard V14 was written for is
    # closed structurally, not by asking emitters to be careful** — which is the only
    # reason V22 is safe to require at all.
    #
    # ⛔ THE MIRROR HAZARD IS LIVE RIGHT NOW AND IT IS `reason`, WHICH *IS* IN THE PAYLOAD.
    # The consumer's `agent_gate` formats its dollar figure into its reason prose
    # (`"… , $%.3f. ADVISORY: …"`). Two otherwise-identical runs at one basis therefore
    # differ in exactly that varying number, so the second is not a dedupe — it is a V11
    # conflict whose named delta is `reason`. ⚠ PREDICTED FROM THE TWO CODE PATHS, NOT
    # OBSERVED: a V11 refusal writes no record, so the stream cannot show it and the
    # calllog is a rotating buffer that may never be cited as evidence. Moving the figure
    # out of `reason` and into `cost.usd` removes the hazard as a side effect of V22.

    # ⭐⭐ V22 — A SAVE DOES NOT COMPLETE WITHOUT A WALL CLOCK. Tim, 2026-09-26:
    # *"Let me make the cost a mandatory field in order to, for the save to be completed
    # correctly."* Measured the same day, and the measurement is why the rule is shaped the
    # way it is rather than as a flat requirement: across 5,940 records there are exactly
    # THREE distinct `cost` shapes and **not one populated value in any of them** —
    # 5,928 × `{"seconds": null, "usd": 0.0}`, 9 × the same plus a null
    # `lock_wait_seconds`, 3 × `usd` as int `0`. The field has existed, been carried on
    # every record, and measured nothing, for the life of the stream.
    #
    # ⚠ THAT IS WHY THE ~40% FIGURE COULD NEVER BE CHECKED. The one question anybody
    # actually asked of this data — what does a panel run cost — was unanswerable in either
    # direction, because `cost` was structurally present and semantically empty. An absent
    # field would have been honest; a present empty one reads as "measured, and it was
    # nothing".
    #
    # ⛔⛔ IT IS A PER-STEP RATCHET AND NOT A FLAG DAY, AND THE ALTERNATIVE WAS PRICED
    # BEFORE IT WAS REJECTED. All ~22 emit call sites in the consumer route through ONE
    # function in a file this server cannot touch (their `required.v2.json` states it:
    # *"every one of the 22 call sites routes through them"*). A hard requirement today
    # therefore refuses every append from ~30 GATING steps at once, every step reads
    # MISSING, and no push happens until another repository changes. **A rule that locks
    # the fleet in order to acquire a field is a rule that gets switched off** — and this
    # file's own §"absence is never success" is worth less than the gate it disables.
    #
    # ⭐ SO THE OBLIGATION IS EARNED RATHER THAN DECLARED: `store.steps_timing()` is the set
    # of steps that have ever reported a wall clock, and a step in that set may never stop.
    # A step that has never reported is untouched. No outage, no flag day, and the ratchet
    # is monotone — which is the same changed-path shape the push bar already uses.
    #
    # ⚠ `timed_steps is None` MEANS THE INDEX WAS NOT SUPPLIED, WHICH IS A WIRING FAULT AND
    # NOT A CLEAN RECORD. It cannot be treated as an empty set (that fails OPEN, silently,
    # on the one path that matters) and it cannot refuse everything (that breaks every
    # direct caller of `rules()`). So the wiring is pinned by a TEST that fails if
    # `ledger.py` stops passing it, rather than by a runtime branch that would have to
    # guess. ⛔ An assertion that never ran is indistinguishable from one that passed: the
    # test asserts the kwarg reaches `rules`, not merely that nothing broke.
    # ⛔⛔ A HUMAN ACCEPT AND A HUMAN REGRADE HAVE NO RUN TO PRICE, AND THE RATCHET MUST NOT
    # DEMAND ONE. Found 2026-09-26 the same way the `narrow` defect was — by running the suite
    # rather than by reading the rule. `Ledger._decided()` builds the record behind `sign`,
    # `override` and `accept`; there is no checker, no subprocess and no elapsed anything, so
    # the only way to satisfy a timing requirement would be to fabricate a number or to price
    # this server's own write and label it as the step's cost. **That is the defect `usd` was
    # just rescued from, one field over.**
    #
    # ⭐ THE EXEMPT SET IS THE CLOSED SET OF HUMAN ACTS, AND THE DIRECTION IS DELIBERATE. A
    # `decided.how` value added LATER is BOUND rather than exempt — same argument as
    # `_strip_rationale`'s denylist in `config.py`: an allowlist of "kinds that must report"
    # would let a new kind escape silently, while this way a new kind trips a visible bar and
    # somebody prices it. `agreement` and `delegated` are deliberately NOT here: an agent round
    # spends real wall clock and real money, which is the case this whole field exists for.
    #
    # ⚠ IT IS NOT A BYPASS, AND THAT WAS CHECKED RATHER THAN ASSUMED. Claiming `signature`
    # requires a non-null `who` (V5) and `override` requires one plus a prohibition on
    # overriding your own decision (V12). A mechanical emitter cannot reach this branch without
    # naming a human and making a far larger claim than a missing duration.
    _NO_RUN_TO_PRICE = ("signature", "override")
    cost = record.get("cost") or {}
    secs = cost.get("seconds")
    if (timed_steps is not None and step in timed_steps and secs is None
            and how not in _NO_RUN_TO_PRICE):
        # ⛔ NAME ONLY WHAT THIS SERVER CAN GUARANTEE — the V9 lesson, which cost a
        # consumer a whole preflight cycle by offering a `--run` flag their checker did not
        # have. This server owns `append`, so it can promise that a numeric `cost.seconds`
        # on the record is accepted. It owns NOTHING about how the emitter measures one, so
        # it must not name a function, a flag, or a helper in the caller's repo.
        # ⭐ The remedy that needs no claim about their code is THEIR OWN PRIOR RECORD: this
        # step has already done it once, so a working example exists in the stream and the
        # refusal points at it rather than describing a route this server cannot see.
        out.append(
            f"V22: step {step!r} has already reported `cost.seconds` on an earlier record, "
            f"so it may not go back to recording without one — a step that can measure its "
            f"own wall clock and stops is indistinguishable from one that never could. "
            f"SUPPLY IT: set `cost.seconds` to the step's elapsed wall clock as a number, "
            f"and `cost.seconds_prices` to a short string naming WHAT that number prices "
            f"(what the clock was started around), then append again. This server reads "
            f"both off the record; how the emitter measures them is the emitter's. "
            f"⚠ IF ONLY SOME OF THIS STEP'S CODE PATHS REPORT A CLOCK, THAT IS THE BUG — "
            f"the ratchet binds the STEP, so a checker that times its pass path and not its "
            f"fail path locks itself out on its next failure. Convert the step whole.")
    # ⚠ SHAPE IS CHECKED WHENEVER THE VALUE IS PRESENT, RATCHET OR NOT — it costs an
    # unconverted step nothing and it stops the first conversion from landing a figure
    # nobody can read. A string "12.4s", a negative, or a bool would all have passed.
    if secs is not None:
        if isinstance(secs, bool) or not isinstance(secs, (int, float)):
            out.append(f"V22: cost.seconds must be a number of seconds, not "
                       f"{type(secs).__name__} — a duration that has to be parsed is a "
                       f"duration two readers will parse differently. SUPPLY IT as an int "
                       f"or float; the unit is seconds and is not carried in the value.")
        elif secs < 0:
            out.append(f"V22: cost.seconds is {secs}, which is not a duration. A negative "
                       f"elapsed time means the clock was read against the wrong origin — "
                       f"the usual cause is subtracting a start captured in a later process. "
                       f"SUPPLY a non-negative elapsed measured within one process.")
        # ⛔ A NUMBER WITHOUT ITS OBJECT IS THIS REPOSITORY'S FOUNDING DEFECT, AND HERE IT
        # IS CHEAP TO MAKE UNREPRESENTABLE. The same wall clock means three different things
        # depending on where it started: measured from an emitter module's import it is a
        # LOWER BOUND on the step (interpreter startup and everything before that import are
        # outside it); measured around `main()` it is the step; measured across a process
        # that ran two steps it is neither, and reads as a step duration while pricing a
        # process. That last one is not hypothetical — the consumer's `batch.py` runs each
        # checker as a subprocess (so a per-process origin is valid there), while
        # `guards.py` and `move_ridealong.py` import `check_*` modules IN-PROCESS, where the
        # same origin would silently accumulate.
        if not (isinstance(cost.get("seconds_prices"), str)
                and cost.get("seconds_prices").strip()):
            out.append(
                "V22: cost.seconds carries a number and cost.seconds_prices does not say "
                "what it prices. The same elapsed time is a LOWER BOUND on the step when "
                "the clock starts at an emitter import, the step itself when it starts "
                "around the step's entry point, and neither when one process ran two steps. "
                "SUPPLY `cost.seconds_prices` as a short non-empty string naming the origin "
                "the clock was started from, so a reader comparing this against a budget "
                "knows which object it describes.")
    # ⚠ `usd` IS DELIBERATELY NOT REQUIRED AND MUST NOT BECOME SO. Of ~31 registered steps,
    # one (`agent_gate`) invokes a model and can read a real `total_cost_usd`; the rest are
    # mechanical checkers that cannot spend. Requiring it would make 30 emitters assert a
    # 0.0 none of them can honestly claim — which is precisely the defect the null default
    # was changed to remove. Shape only, and only when present.
    usd = cost.get("usd")
    if usd is not None and (isinstance(usd, bool) or not isinstance(usd, (int, float))
                            or usd < 0):
        out.append(f"V22: cost.usd must be a non-negative number or absent, not {usd!r}. "
                   f"⚠ ABSENT AND ZERO ARE DIFFERENT CLAIMS: absent says this step did not "
                   f"report a spend, 0.0 says it measured one and it was nothing. Only an "
                   f"emitter that actually reads a cost may write the second.")

    # The key must parse unambiguously. Git permits '#' in a ref name, so a
    # pathological basis could make `step@basis#revision` read two ways. One line,
    # rather than the escaping contract a digest would have needed.
    if schema.key_is_ambiguous(record):
        out.append(f"basis.value contains {schema.KEY_SEP_REVISION!r}, which would make "
                   f"the record key ambiguous. Rename the ref.")
    return out


def validate(record: dict, *, config: Config, existing_ids=None, tips=None,
             known_config_shas=None, timed_steps=None) -> list[str]:
    """Everything, structural first. Returns [] when the record is acceptable."""
    out = structural(record)
    if any(v.startswith(("record must", "schema must", "step must", "verdict must",
                         "basis must", "decided must")) for v in out):
        # Rules would produce noise on a record this malformed; the shape errors
        # are the actionable ones.
        return out
    return out + rules(record, config=config,
                       existing_ids=existing_ids if existing_ids is not None else set(),
                       tips=tips, known_config_shas=known_config_shas,
                       timed_steps=timed_steps)


# -- the subject identity must be one git could have produced -------------------

_OBJECT_FORMAT = None


def _object_hex_len() -> int | None:
    """How many hex characters a git object id has in THIS repo (40 for sha1, 64 for
    sha256 repos). None when the repo cannot be resolved, in which case the check is
    skipped rather than guessed at."""
    global _OBJECT_FORMAT
    if _OBJECT_FORMAT is None:
        import os
        import subprocess
        repo = os.environ.get("ZPLEDGER_REPO")
        _OBJECT_FORMAT = 0                       # sentinel: looked, found nothing
        if repo:
            try:
                proc = subprocess.run(["git", "rev-parse", "--show-object-format"],
                                      cwd=repo, capture_output=True, text=True,
                                      timeout=10)
                fmt = (proc.stdout or "").strip()
                _OBJECT_FORMAT = {"sha1": 40, "sha256": 64}.get(fmt, 0)
            except (OSError, subprocess.SubprocessError):
                _OBJECT_FORMAT = 0
    return _OBJECT_FORMAT or None


def _not_a_blob_id(value, path) -> str | None:
    """⚠⚠ CATCHES THE 2026-08-23 DEFECT AT THE DOOR.

    `subjects[].git_blob_id` must carry GIT'S BLOB ID -- the value `git ls-tree` prints and
    the only thing `inventory` compares against. The field used to be named `sha256`,
    so a client computed a sha256 digest of the file bytes. That is a different hash
    function over a different byte string (git prefixes ``b"blob <len>\0"``), so it
    could never match: the record appended cleanly and then read STALE forever, which
    is indistinguishable from a staleness bug and cost an afternoon of correctly
    verifying that the sha256 matched disk.

    A record that can never be satisfied is not a valid record. Refusing it here with
    the reason beats letting it rot, which is the same fail-open shape as absence
    rendering as success.
    """
    if not isinstance(value, str):
        return "git_blob_id must be a string"
    v = value.strip()
    if v != value or not v:
        return "git_blob_id must not carry surrounding whitespace"
    if v != v.lower() or any(c not in "0123456789abcdef" for c in v):
        return f"git_blob_id {v!r} is not lowercase hex; git object ids are"

    # ⚠ FAIL CLOSED. An unresolvable repo used to SKIP this check, which is the
    # fail-open shape the whole server exists to end: the one environment where the
    # format is unknown is exactly where a wrong value would go unnoticed. 40 is
    # git's default object format; a sha256 repo overrides it when it can be read.
    want = _object_hex_len() or 40
    if len(v) == want:
        return None
    if want == 40 and len(v) == 64:
        return (f"git_blob_id for {path!r} is 64 hex characters, but this repository's git "
                f"object ids are 40. This is almost certainly a sha256 of the file "
                f"contents -- git's blob id is SHA-1 over b'blob <len>\\0' + data, a "
                f"different hash over different bytes, and it can NEVER match. Use "
                f"client.record.blob_id(path) or column 3 of `git ls-tree -r <ref>`. "
                f"Refused rather than appended, because such a record reads STALE "
                f"forever and looks like a staleness bug.")
    return (f"git_blob_id for {path!r} is {len(v)} hex characters; this repository's git "
            f"object ids are {want}")
