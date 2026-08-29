"""V1–V18. Each rule makes a defect this project has already paid for UNREPRESENTABLE.

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
          tips: Optional[dict] = None, known_config_shas: Optional[set] = None) -> list[str]:
    """V1–V18. ``tips`` maps ``(step, basis_value)`` -> the highest-revision record."""
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
    if not (run.get("id") or "").strip():
        out.append("V9: run.id is required — a verdict that cannot be tied to the run "
                   "that produced it makes cost-per-run and first-failure-latency "
                   "uncomputable, and two verdicts from one sweep indistinguishable "
                   "from two sweeps. SUPPLY IT: export ZPLEDGER_RUN=<name> before the "
                   "checker (record.emit reads it from the environment, so a hand-run "
                   "sets it exactly the way the pipeline does), or pass --run on the "
                   "CLI. It is ATTRIBUTION, not authentication — nothing here can tell "
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
                           f"revision {rev + 1}.")
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

    # The key must parse unambiguously. Git permits '#' in a ref name, so a
    # pathological basis could make `step@basis#revision` read two ways. One line,
    # rather than the escaping contract a digest would have needed.
    if schema.key_is_ambiguous(record):
        out.append(f"basis.value contains {schema.KEY_SEP_REVISION!r}, which would make "
                   f"the record key ambiguous. Rename the ref.")
    return out


def validate(record: dict, *, config: Config, existing_ids=None, tips=None,
             known_config_shas=None) -> list[str]:
    """Everything, structural first. Returns [] when the record is acceptable."""
    out = structural(record)
    if any(v.startswith(("record must", "schema must", "step must", "verdict must",
                         "basis must", "decided must")) for v in out):
        # Rules would produce noise on a record this malformed; the shape errors
        # are the actionable ones.
        return out
    return out + rules(record, config=config,
                       existing_ids=existing_ids if existing_ids is not None else set(),
                       tips=tips, known_config_shas=known_config_shas)


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
