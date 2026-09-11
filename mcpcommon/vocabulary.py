"""The fleet's shared vocabularies - ONE definition, imported by every server.

WHY THIS EXISTS, AND IT IS A DEFECT THAT ALREADY HAPPENED. Measured 2026-09-08: the
consumer-facing failure vocabulary was defined in TWO errors.py files that had diverged with
only `usage` in common -

    verdictLedger   config, ledger, unavailable, usage, validation
    gitRobot        gate, gitrobot, refusal, repo, usage
    mcpcommon/iserror.py emits `unhandled` and READS error_type on every refusal from every
                    server while owning none of it

Nine values, three definition sites, no shared source. A caller cannot enumerate what it may
receive, and two servers answering the same question with different words is the second copy
of the policy config.py forbids, at fleet scale.

Tim, 2026-09-08: "the standard and the definitions themselves are under the control of the mcp
instance, and the zeroparadox framework is strictly a consumer." This is that. And on the
duplication it retires: "definitely kill off all of the duplication."

THESE ARE DEFINITIONS, NOT DOCUMENTATION. The rule from CLAUDE.md's resource contract: a
vocabulary is GENERATED from the constants the code imports, never hand-authored. schema.py is
the model that already works - VERDICTS is defined once, ledger.py imports it, inputs.py
derives its Literal from it, and the wire enum comes from the same tuple, so the code would
BREAK if it disagreed. Anything here that a server merely DESCRIBES rather than IMPORTS is a
fourth copy, and the fourth copy is the one nobody notices.

MEANING BELONGS HERE TOO, and that is the half an enum cannot carry. ["PASS","FAIL","UNDECIDED"]
publishes the values; it cannot say that UNDECIDED is the honest verdict for a contested panel.
That meaning currently lives in prose that drifts - 27 exit-code assertions in one consumer
brief, four bedrock findings against them in one evening, every finding about a claim the
tooling never implemented.

WHAT DOES NOT BELONG HERE: registered step names, thresholds, and anything editable without a
restart. Those live in config and are served by requirements()/policy(). Publishing a threshold
here would be exactly the second copy this module exists to remove.
"""

from __future__ import annotations

ERROR_TYPES = {
    # ENUMERATION AGAIN, AND IT EXCLUDED THE COMMONEST CASE. "a bad argument name, a
    # missing required field" listed CAUSES -- the failure this file's exit-code entries
    # were twice corrected for -- and a bad argument VALUE matched neither, so a bad
    # `action` on gitRobot reported as "an unclassified fault" instead. Measured 2026-09-10.
    "usage": ("the CALL was malformed - a bad argument name, a bad argument VALUE, a "
              "missing required field. The server never performed the operation, so "
              "nothing changed; FIX THE CALL AND RETRY. Distinguished from `validation` "
              "by WHAT was wrong: usage means the request never became a valid one, "
              "validation means it did and its CONTENT broke a rule."),
    "validation": ("the call was well-formed and the CONTENT broke a rule. TERMINAL: do not "
                   "retry, fix the record. Every violation is reported at once so one round "
                   "trip is enough."),
    "refusal": ("the operation is DELIBERATELY not offered. Not a failure - a design decision, "
                "and the message names the sanctioned alternative."),
    "gate": ("a blocking gate leg failed, so the mutation did not run. The work is unstarted, "
             "not half-done."),
    "config": ("the server's own configuration could not be read or is invalid. Nothing is "
               "judged until it is fixed; this is served, never crashed on."),
    "repo": "the configured repository is missing, is not a git repo, or git itself failed.",
    "unavailable": ("a transient condition - a lock held, a resource busy. RETRYABLE, unlike "
                    "validation, and conflating the two is how a rule gets retried past."),
    # ADDED 2026-09-10. sjv had been EMITTING this value for as long as it has had an
    # integrity check, and it appeared in no published list -- because sjv's errors.py was
    # never bound to this table. It is genuinely distinct from `validation`: validation means
    # the CONTENT broke a rule, integrity means the FILE MOVED UNDER US and the content was
    # never judged at all.
    "integrity": ("the store's on-disk hash does not match the last audit hash - it was "
                  "edited OUT OF BAND, bypassing the handler. Detection, not prevention: "
                  "nothing here can say what changed or who changed it. HALT; do not write "
                  "over it, and re-establish the baseline deliberately."),
    "ledger": "an unclassified verdictLedger fault.",
    "gitrobot": "an unclassified gitRobot fault.",
    "unhandled": ("an exception the server did not classify. A BUG in the server, not in the "
                  "call - if you see this for an ordinary caller mistake, that is a defect."),
}

DECISIONS = {
    # ⛔⛔ MISSING UNTIL 2026-09-10, AND THE CODE HAS EMITTED IT SINCE THE ASYNC PATH
    # EXISTED. `engine.py` writes `decision="started"` for both `preflight` and `push`,
    # and READS IT BACK -- `audit.last_where(op="preflight", head=head,
    # decision="started")` is how `preflight_status` finds a run at all. So a caller
    # enumerating this vocabulary to learn what an audit row may say would have missed
    # the one value that means WORK IS IN FLIGHT, and read a running push as no push.
    # ⚠ It survived because NOTHING BOUND THIS TABLE TO THE CODE -- see the note at the
    # top of the module. `_decision()` in gitRobot/core/audit.py now raises on an
    # unpublished value, the same way `_kind()` does for ERROR_TYPES.
    "started": ("the operation BEGAN and has not resolved. The only NON-TERMINAL value here -- a row carrying it is a promise of a later row, not an outcome. Reading it as success or failure is reading a question as an answer."),
    "allowed": "the operation ran and succeeded.",
    "refused": "gitRobot declined to run it - policy, not failure. The alternative is named.",
    "failed": "it ran and git returned non-zero. The tree may have changed.",
    "skipped": ("there was nothing to do, which is not the same as success and not the same as "
                "failure."),
}

ROW_STATUSES = {
    "SATISFIED": "a verdict covers these exact bytes and it passed.",
    "MISSING": ("no verdict exists for this step at this content. NOT a failure - nobody "
                "looked."),
    "STALE": ("a verdict exists but against different bytes, or its PRODUCER moved. It does not "
              "judge this content; re-run the step."),
    "FAIL": ("a verdict exists and it blocks. It indicts the subset it NAMES, never everything "
             "it examined."),
    "UNDECIDED": ("the step ran and could not decide - a crashed checker, a contested panel. "
                  "Distinct from both PASS and FAIL, and it blocks."),
    "REFUSED": ("a verdict was ATTEMPTED and rejected. Blocks, but condemns nothing: it is not "
                "a FAIL about the content."),
    "UNVALIDATED": ("the step is barred by min_coverage and examined too little of what this "
                    "commit CHANGED."),
    "LEGACY_IDENTITY": ("a verdict predating the current content key. Grandfathered, and named "
                        "rather than silently counted."),
    "NOT_APPLICABLE": "the registry narrows this step out for this action. It owes nothing.",
}

EXIT_CODES = {
    # ⛔ "FOUND NOTHING" WAS FALSE OF TWO REAL CHECKERS. Measured 2026-09-10 by the
    # provenance-ring session across all 17 mechanical checkers on a clean tree:
    # `check_poles` exited 0 printing "26 pole-equality site(s)" and `check_divergent`
    # exited 0 printing "5 surviving retired phrase(s)". They found things, enumerated
    # them, and exited 0.
    # ⚠ THE CHECKERS ARE NOT WRONG - THIS TABLE HAD NO SLOT. The consumer's own rules make
    # an enumeration "a READING LIST, never a finding list" and downgrade enumeration legs
    # to WARN, so exiting 0 is the DESIGNED behaviour for an advisory leg. The gap was that
    # {0,1,2,3} cannot express "ran, enumerated, owes no verdict", leaving an intended WARN
    # indistinguishable from clean to anything branching on the code alone.
    # ⛔ NOT FIXED BY MAKING THEM EXIT 1. That would turn advisory output into a finding and
    # block on a reading list. Fixed by saying what 0 actually means.
    0: ("ok - the check ran and OWES NO VERDICT. Usually it found nothing; it may also "
        "have printed an advisory enumeration that is explicitly not a finding. Read the "
        "output before concluding the tree is clean - 0 means 'nothing to answer for', "
        "not 'nothing to see'."),
    1: "the check ran and FOUND something. A real finding, not an error.",
    # ⛔⛔ THIS ENTRY WAS NEVER MEASURED EITHER, AND IT IS THE SECOND IN THIS DICT TO BE
    # WRONG FOR THE SAME REASON. The provenance note below is entirely about `3`; nobody ever
    # checked `2` against a caller. It read "the check could not run - usage error, bad
    # arguments, missing input", which is an ENUMERATION OF CAUSES - the exact failure the
    # `3` note says a vocabulary must not commit - and it describes none of the three things
    # the fleet actually returns 2 for. Measured 2026-09-10 in the consumer's
    # `tools/verify/record.py`:
    #
    #     emit() returned None      -> 2   the ledger was UNREACHABLE or REFUSED the record
    #     dry-run check() -> None   -> 2   unreachable; "nothing was learned about it"
    #     no recordable subjects    -> 2   "nothing recordable ... NEVER 0"
    #
    # NOT ONE of those is a usage error. In every one the check RAN; what failed was getting a
    # verdict recorded. ⚠ And my own `verdictLedger/client/record.py` - the template the
    # consumer copied - has said `sys.exit(2)` for "ledger unavailable or record rejected"
    # since before this dict existed. So the vocabulary contradicted the client it ships
    # beside, and the consumer holding the older faithful copy was the one who was right.
    #
    # ⭐ STATE THE SHAPE, NEVER THE CAUSES - the lesson `3` already paid for, applied here.
    # ⛔⛔ AND THE DISCRIMINATOR I ADDED ON 2026-09-10 WAS ITSELF FALSIFIED THE SAME DAY.
    # It read "2 means no verdict reached the ledger at all". Measured, ledger REACHABLE and
    # REFUSING - `record.py --step a_step_that_is_not_registered`:
    #
    #     exit 2
    #     UNDECIDED: record refused by verdictLedger:
    #       - V8: step '...' is not registered in required.v2.json
    #
    # The ledger was REACHED. It DECIDED. It decided NO. And the code is 2. So the broad
    # clause admitted the refusal path while the discriminator excluded it - one sentence
    # contradicting the one before it.
    #
    # ⚠ THE FIX IS NOT "MAKE REFUSAL EXIT 3". A V8 refusal is not indecision about CONTENT;
    # it is a well-formed decision that the record is inadmissible. It is correctly 2. The
    # SENTENCE was wrong: the honest axis is RECORDING, not REACHING.
    #
    # ⭐ AND FOR THE SECOND TIME IN ONE DAY THE CONSUMER HELD THE CORRECT GENERAL STATEMENT
    # AND THIS TABLE NARROWED IT WRONGLY. `client/record.py` says "could not be recorded (2)"
    # - true of BOTH the outage and the refusal. Specialising a correct general claim is the
    # failure mode of this file, twice now, in the same entry.
    2: ("COULD NOT ASK - no verdict was recorded because the ledger was never reached. "
        "NOT a finding, and never 0 or 1. RETRYABLE: the ledger is down, the URL is wrong, the "
        "call timed out - nothing has decided anything, so trying again is the correct next "
        "move. ⛔ DISTINGUISHED FROM 4, WHICH IS THE OTHER HALF OF WHAT 2 USED TO MEAN: 4 is "
        "asked AND REFUSED, which is TERMINAL and must never be retried. Distinguished from 3 "
        "by WHAT is missing: 3 means a verdict about the CONTENT was reached and could not "
        "resolve to finding-or-clean; 2 means the recording never happened because nobody "
        "answered. WHAT specifically failed is the CHECKER's to say, in that checker - never "
        "enumerated here."),
    3: ("UNDETERMINED - it ran and could not return a finding-or-clean answer. Must never "
        "collapse into 0 or 1; that collapse is the defect this whole vocabulary exists to "
        "make unrepresentable. ⚠ THIS IS ABOUT THE CONTENT, NOT ABOUT RECORDING: a verdict "
        "that was reached and could not be RECORDED is 2 or 4, never this. WHAT SPECIFICALLY "
        "made it undetermined is the CHECKER's to say, in that checker, mapped onto this - "
        "never enumerated here."),
    4: ("ASKED AND REFUSED - the ledger was reached, it DECIDED, and it said no. NOT a "
        "finding, and never 0 or 1. ⛔ TERMINAL: NEVER RETRY IT. A refusal is a rule being "
        "applied, so the same call will be refused again; retrying is how a caller under "
        "pressure gets past a rule it should have obeyed. Read the rule the server named and "
        "fix the call or the content. "
        "⭐ THIS VALUE EXISTS BECAUSE 2 USED TO CARRY BOTH HALVES AND THEY DIFFER ON THE ONE "
        "AXIS `error_type` SAYS MUST NEVER BE COLLAPSED - `unavailable` is RETRYABLE and "
        "`validation` is TERMINAL. Until 2026-09-10 both exited 2 and differed only in printed "
        "prose, so the vocabulary told callers to 'read the line' - dispatch on text, which is "
        "the fix this fleet forbids everywhere else. A DIFFERENT VALUE, NOT A DIFFERENT "
        "MESSAGE. "
        "⚠ THE CONSUMER GOT HERE FIRST AND THAT IS EVIDENCE, NOT COINCIDENCE. ZeroParadox's "
        "`check_briefs.classify_record_failure` had already split the code itself, and built "
        "`record.reachable()` - a SECOND network call - to recover a distinction `emit` "
        "already knew and threw away at its return. A workaround in the consumer is evidence "
        "of a gap here. ⛔ It chose 3 for this, which collides with 3's meaning above AND with "
        "`ci_report.SKIPPED_RC = 3`, where a 3 renders as **skipped** - a non-failure. That "
        "collision is why this is a NEW value rather than a widening of 3."),
    124: ("TIMED OUT - the check was started and killed before it could answer. NOT a finding, "
          "and never 0 or 1: nothing was decided, so this says nothing about the content. "
          "RETRYABLE in the same sense as 2 - nobody answered - but distinguished from it "
          "because the remedy is different: 2 means the LEDGER was unreachable, 124 means THIS "
          "CHECK ran too long and was cut off, so the next attempt needs a longer budget or a "
          "narrower scope, not a retry of the same call. "
          "⛔ 124 RATHER THAN THE NEXT FREE SMALL NUMBER, AND THE REASON IS COLLISION. `timeout(1)` "
          "has meant exactly this since long before this fleet, so a checker killed by an "
          "external timeout and one that self-reports arrive as the SAME value with the SAME "
          "meaning. Minting 5 here would have produced two numbers for one event, which is the "
          "defect one layer up from the one the split of 2 removed. "
          "⚠ IT WAS EMITTED BEFORE IT WAS PUBLISHED. `gitRobot/core/gates.py` has returned "
          "`exit_code=124` on `subprocess.TimeoutExpired` since before this table existed - a "
          "value the fleet produced and no caller could look up.")
}

# ⛔⛔ NOT EVERY TABLE ABOVE IS BOUND TO CODE, AND UNTIL 2026-09-10 NOTHING SAID SO.
# Measured that day, and it is the reason `exit_code` drifted twice and `decision` shipped
# incomplete:
#
#     ERROR_TYPES    bound in 4 files. gitRobot/core/errors.py and verdictLedger/core/errors.py
#                    both call `_kind()`, which RAISES on a value this module does not publish,
#                    and mcpcommon/iserror.py reads the field. The code breaks if it disagrees.
#     DECISIONS      bound in 0 files -- now 1, via `_decision()` in gitRobot/core/audit.py.
#     ROW_STATUSES   bound in 0 files. Held by a conformance test instead, because the statuses
#                    are computed across many branches of inventory.py.
#     EXIT_CODES     bound in 0 files. ⛔ THIS ENTRY SAID "AND UNBINDABLE FROM HERE" AND THAT
#                    WAS WRONG WITHIN HOURS. It is unIMPORTable - the emitters live in another
#                    repository - and I wrote that as unBINDable, which is a claim about a
#                    different axis. A binding does not need a symbol this process can import;
#                    it can be a MEASUREMENT a test session takes and this table is checked
#                    against. ⭐ Bound that way 2026-09-10: 17 checkers swept, plus the outage
#                    and refusal paths and a nonexistent-checker control. Two entries were
#                    falsified by that one sweep - see 0 and 2 below.
#
# ⚠ THE HAZARD IS THAT ALL FOUR LOOK IDENTICAL TO A READER. They sit in one dict, are rendered
# by one function, and are served through one resource, so a caller cannot tell the enforced
# table from the described one. `CLAUDE.md` requires a resource be GENERATED from the constants
# the code imports and forbids one that "merely describes what the code happens to do" -- and
# three of these four were the forbidden kind, published beside the one that was not.
#
# ⭐ SO `exit_code` IS A PUBLISHED CONVENTION THE FLEET DOES NOT ENFORCE, and saying that here
# is the honest alternative to implying a binding that cannot exist.

# ⭐⭐ MINT A DEDICATED CODE WHENEVER A CASE NEEDS ONE - Tim, 2026-09-10: "I am completely good
# with having a dedicated response code anytime ... it's not like it's possible to run out of
# numbers." That is the policy, and this constant is the ONE fence it needs, because the numbers
# are not in fact all free.
#
# ⛔ MEASURED 2026-09-10 ON THIS MACHINE: Windows preserves exit codes as 32-bit, so
# `sys.exit(256)` and `sys.exit(300)` come back as 256 and 300 intact. ⚠ POSIX DOES NOT - `wait()`
# exposes only the low 8 bits, so 256 arrives as **0, a SUCCESS**, and 300 arrives as 44. That is
# a documented platform property of POSIX and is NOT something measured here; what was measured
# here is that this dev box does not truncate, which is exactly what makes it dangerous. **The
# same checker exiting 256 is a catastrophic false PASS on Linux CI and a distinct code on the
# machine it was written on** - one value, two meanings, split by platform.
#
# ⚠ AND THE HIGH BAND IS ALREADY SPOKEN FOR ON POSIX: 126 is "found but not executable", 127 is
# "command not found", and 128+N is "killed by signal N" - so a minted 130 is indistinguishable
# from a Ctrl-C, and a minted 139 from a segfault. 125 belongs to `timeout` itself.
#
# ⭐ SO: MINT FREELY IN 1..123, and adopt an existing convention rather than inventing a rival
# for the same event (which is why TIMED OUT is 124 and not 5). 0 is reserved for success.
MINTABLE_EXIT_CODES = range(1, 124)

RESERVED_EXIT_CODES = {
    124: "GNU `timeout` - the command was killed after exceeding its budget. ADOPTED above.",
    125: "`timeout` itself failed, as distinct from the command it was running.",
    126: "the command was found and could not be executed (permissions, not-a-binary).",
    127: "the command was not found at all.",
    "128+N": "killed by signal N on POSIX - 130 is SIGINT, 137 SIGKILL, 139 SIGSEGV.",
    ">255": "TRUNCATED ON POSIX to the low 8 bits. 256 becomes 0, a SUCCESS. Never mint here.",
}

# ⭐⭐ THE FIFTH TABLE, AND IT IS THE ONE THE OTHER FOUR KEPT POINTING AT.
# Tim, 2026-09-10: "shouldn't you be able to standardize this? I mean quite frankly that's been
# the problem the entire time."
#
# ⛔ COUNTED THAT DAY: the rule below appears EIGHT TIMES in CLAUDE.md, in seven different
# spellings -- "never report a number without naming what it prices", "measure it independently
# on both sides", "quote it FROM the source", "pre-register a prediction", "a checker's answer
# is only as scoped as its caller made it", "a true value read against the WRONG OBJECT" -- plus
# "name the session beside a relayed measurement", which is in the HANDOFF and scores ZERO in
# CLAUDE.md. So the most-restated rule in the repo was the one vocabulary nobody consolidated,
# and its copies do not even share a file. That is the exact defect the other four tables were
# built to end, sitting one level up and describing the tables themselves.
#
# ⭐ EVERY DISAGREEMENT MEASURED ON 2026-09-10 WAS A MISSING FIELD FROM THIS TABLE, and the
# taxonomy was DERIVED from those failures rather than invented:
#     "MCP works in subagents"          missing OBJECT      (which tool? old ones yes, new no)
#     "No files found"                  missing INSTRUMENT  (harness Grep honours .gitignore)
#     "subagents cannot reach ledger"   missing PROVENANCE  (relayed twice, never re-derived)
#     "1717 of 1717 unresolvable"       missing SCOPE       (a root nobody named)
#     "27 unpushed"                     missing OBJECT      (which rev range)
#     "gitRobot is the only commit path" missing OBJECT     (which repository)
#     "install as tools/verify/record.py" missing OBJECT    (which record.py -- 278 vs 1165 lines)
#     "the servers are running HEAD"    missing INSTRUMENT  (a commit time, not a process start)
#
# ⚠ HOW STRONGLY THIS IS BOUND, STATED HONESTLY, BECAUSE OVERSTATING IT WOULD BE THE DEFECT.
# `ERROR_TYPES` is bound by `_kind()` raising in four files. THIS table cannot be bound that way,
# for the same reason `EXIT_CODES` is described in the test suite as "the one table that is
# UNBINDABLE from this side": the emitters are AGENTS WRITING PROSE, not functions. A published
# convention the fleet does not mechanically enforce is still worth publishing -- but it must SAY
# it is one, or it becomes a claim about enforcement that nothing enforces.
CLAIM_FIELDS = {
    "object": (
        "WHAT the claim is about, named precisely enough that a second party measures the SAME "
        "THING. This is the field whose absence is this fleet's defining defect: a TRUE value "
        "read against the WRONG OBJECT. ⛔ THE TEST: could two people who agree on every word "
        "of the claim still be measuring different things? Then the object is not named. "
        "'27 unpushed' fails it; '27 on origin/illustrated..illustrated, which is what the push "
        "publishes' does not. "
        "⭐ THE REMEDY, EARNED FROM THREE MEASURED INSTANCES IN ONE DAY AND THE SAME MOVE EVERY "
        "TIME: GO TO THE SERVED SURFACE AND READ WHAT IT ACTUALLY ACCEPTS, RATHER THAN WHAT THE "
        "FAMILIAR THING ACCEPTS. 2026-09-10: `git commit -- <path>` semantics were read onto "
        "gitRobot's `commit`, whose published parameters are only "
        "(message_file, reason, repo_mode, worktree) - `tools/list` refutes it in one call. "
        "'MCP works in subagents' was true of `status` and false of `vocabulary`, and the "
        "deferred registry says which. A relayed 'expects a clean tree' was true of `merge` and "
        "false of `push`, and `_require_clean`'s caller list says which. ⚠ THE FAILURE MODE IS "
        "ALWAYS REASONING FROM THE ANALOGUE: the familiar tool, the sibling server, the "
        "remembered shape. A published contract is the only thing that answers for THIS object, "
        "and it is one call away. ⛔ AND THE SUBJECT DECIDES THE OBJECT, NOT THE CONVENTION: a "
        "gate over files an agent READS AT RUNTIME must examine the WORKING TREE, because that "
        "is what gets read - while a verdict about them may still only indict bytes at the ref. "
        "What a checker EXAMINES and what a verdict may INDICT are different questions, and "
        "fusing them is this field's defect wearing a design decision."),
    "instrument": (
        "HOW it was measured, named as the TOOL and not just the query -- because the query is "
        "what you chose and the SCOPE IS WHAT THE INSTRUMENT CHOSE FOR YOU. ⛔ Measured "
        "2026-09-10: shell `grep` and the harness `Grep` tool, same pattern, same tree, opposite "
        "answers, because the second honours .gitignore and said only 'No files found'. ⚠ AND "
        "TWO INSTRUMENTS IS NOT ENOUGH: two that share a scope restriction agree perfectly and "
        "are both wrong, and agreement then reads as CORROBORATION, which is worse than a lone "
        "probe. You must know WHICH IS WIDER AND WHY."),
    "scope": (
        "WHAT WAS AND WAS NOT COVERED, including the exclusions you did not type. A checker's "
        "answer is only as scoped as its caller made it -- the same pipeline printed opposite "
        "prior-art answers thirty minutes apart because one invocation was handed refs and one "
        "was not. ⛔ An ABSENCE claim is a claim about the INSTRUMENT until its scope is stated: "
        "'not located as of <date>, searched as follows' names the tool, never just the pattern."),
    "provenance": (
        "WHO established it and WHEN, in UTC -- and whether you MEASURED it or RELAYED it. ⛔ "
        "THE TWO ARE DIFFERENT CLAIMS AND ONLY ONE OF THEM IS YOURS. A relayed measurement "
        "carries the name of the session that made it; a relayed INSTRUCTION carries more "
        "weight still, because it authorises rather than informs, and a session that cannot "
        "name which message and which words has not got one. ⚠ Measured 2026-09-10: a premise "
        "was re-derived correctly and its CONSEQUENCE was inherited unchecked, and the "
        "inherited half became a recommendation to widen a permission surface. ⭐ Outcome never "
        "retroactively upgrades evidence: a question carrying a discriminating test does the "
        "work of an assertion and cannot go false."),
}

# ⭐⭐ THE SIXTH TABLE, AND IT IS THE AXIS EVERY CONFUSION OF 2026-09-10/11 TURNED ON.
# Tim: "I think I was just getting clean up on working tree versus head."
#
# ⛔ THREE DIFFERENT OBJECTS ARE IN PLAY AT ALL TIMES and English calls all three "the files".
# A claim like "the tree is clean", "it is blocked", or "that file is fine" is UNFALSIFIABLE
# until it says WHICH. Measured instances, all in ~24 hours, all the same shape:
#
#   "a dirty tree blocks a push"       WORKING TREE asserted; push keys to HEAD. Twice relayed.
#   check_figures blocked a commit     it read the WORKING TREE; the commit carries the INDEX
#   the FAIL could not be recorded     it indicted WORKING TREE bytes; subjects key to a REF
#   "merge is refused while dirty"     true of the WORKING TREE until it was not; HEAD unmoved
#   record.py "modified in the worktree since it was staged"   WORKING TREE vs INDEX, exactly
#
# ⭐ THE PRINCIPLE WAS ALREADY WRITTEN, ONCE, IN ONE COMMENT -- gitRobot engine.py: "Read from
# the index (`:path`), never the working tree -- the question is what a commit would carry."
# That is the whole rule and it had no canonical home, so it could not be cited, only re-derived.
TREE_OBJECTS = {
    "working_tree": (
        "THE BYTES ON DISK RIGHT NOW. What an editor shows and what any process that opens the "
        "file reads. ⭐ IT IS THE OPERATIVE OBJECT FOR ANYTHING READ AT RUNTIME: a spawned agent "
        "reads its brief from DISK, not from the index, so a gate over agent-read files must "
        "examine this one or it is blind where its subject lives. ⛔ IT IS NOT WHAT A COMMIT "
        "CARRIES. A finding here can be entirely real and still concern bytes that are in no "
        "commit and no push. Fleet operations that key to it: gitRobot's dirty-tree guard for "
        "switch/rebase/squash, and `carried_forward` on a merge receipt - which REPORTS and "
        "does not block."),
    "index": (
        "WHAT A COMMIT WOULD CARRY - the staged content, `git show :<path>`. ⛔ THE QUESTION A "
        "COMMIT GATE IS ACTUALLY ASKING, and the reason gitRobot reads `:path` rather than the "
        "file. Fleet operations that key to it: `ledger_subjects(ref='INDEX')` - the DEFAULT, so "
        "a verdict's subjects are index blobs unless a caller says otherwise - and the staged "
        "arc-round read. ⚠ A path whose working tree differs from its index cannot be a subject: "
        "the ledger refuses to let a verdict, or an indictment, travel to bytes that are not at "
        "the ref. ⭐ AND GIT ITSELF FENCES THIS ONE: a merge over a dirty INDEX is refused by "
        "git, because `--no-commit` would sweep the index into the merge commit; a merge over "
        "unstaged changes is allowed, because they are not in it."),
    "head": (
        "THE LAST COMMIT - what is already recorded, and what a push PUBLISHES. ⛔ UNCOMMITTED "
        "WORK IS IN NONE OF IT, which is why a dirty working tree is irrelevant to a push and "
        "why gitRobot has never gated a push on tree state. Fleet operations that key to it: "
        "`_require_inventory`, which refuses a push unless the ledger is green for the EXACT "
        "HEAD hash, and every audit receipt's `head` field. ⚠ THE COMMONEST ERROR IN THIS "
        "FLEET IS PRICING ONE OF THESE THREE AND NAMING ANOTHER: a verdict recorded against "
        "INDEX blobs does not describe HEAD, and a push evaluates HEAD - so recording while "
        "the index and HEAD disagree produces rows that read STALE, correctly, and refuse."),
}

VOCABULARIES = {
    "error_type": ERROR_TYPES,
    "decision": DECISIONS,
    "row_status": ROW_STATUSES,
    "exit_code": EXIT_CODES,
    "claim_field": CLAIM_FIELDS,
    "tree_object": TREE_OBJECTS,
}


class UnknownVocabulary(ValueError):
    """Raised for a vocabulary name nobody publishes. Carries `satisfied_when`.

    ⚠ NOT a server error type. `mcpcommon` cannot import any server's error classes without
    inverting the dependency, so this carries the two fields a refusal owes and each server
    maps it to ITS OWN `usage` refusal at the tool boundary. One message, three envelopes.
    """

    def __init__(self, what, satisfied_when):
        super().__init__(what)
        self.satisfied_when = satisfied_when


def _select(name=None):
    """The requested tables, or all of them. Refuses a name nobody publishes."""
    if name is None:
        return dict(VOCABULARIES)
    if name not in VOCABULARIES:
        raise UnknownVocabulary(
            "no vocabulary named %r" % (name,),
            "pass `name` as one of %s, or omit it for all four. Refusing rather than "
            "returning an empty set, because an empty vocabulary reads as 'this value has no "
            "published meanings' when it means 'you asked for a table that does not exist'."
            % (", ".join(repr(k) for k in VOCABULARIES),))
    return {name: VOCABULARIES[name]}


def render_markdown(name=None):
    """The vocabularies as a document, GENERATED from the constants above.

    Never transcribe this into a brief or a readme. A copy is the fourth one and it goes stale
    the way a README's test count does - measured four times in one evening in one file. Point
    at the served resource instead.
    """
    tables = _select(name)
    out = ["# The fleet vocabularies", "",
           "One definition, imported by every server, rendered from the constants in",
           "mcpcommon/vocabulary.py. If a document restates any of this, the document is the",
           "copy that will be wrong.", ""]
    for vocab_name, table in tables.items():
        out.append("## " + vocab_name)
        out.append("")
        for key, meaning in table.items():
            out.append("- **`%s`** - %s" % (key, meaning))
        out.append("")
    return chr(10).join(out)


def as_payload(name=None):
    """THE SAME CONTENT `render_markdown` RENDERS, AS DATA - for the TOOL transport.

    ⛔⛔ WHY A TOOL EXISTS BESIDE THE RESOURCE, AND IT IS NOT CONVENIENCE. Measured 2026-09-10
    across three sessions: **a spawned subagent cannot reach the MCP resource surface at all.**
    `ListMcpResourcesTool` and `ReadMcpResourceTool` answer "No such tool available: <name>.
    <name> is disabled for this session, in subagents as well as here" - and a FABRICATED name
    returns the same prefix WITHOUT that second sentence, which is the control proving the tools
    are present and SUPPRESSED rather than unregistered.

    ⭐ CONFIRMED HARNESS-LEVEL, NOT PROJECT-SCOPED. The suppression survives in mcp-mayhem,
    whose subagents demonstrably DO reach `mcp__` tools (gate 3 passes here). So no project
    config can lift it.

    ⚠ AND EVERY GATE BRIEF IS EXECUTED BY A SPAWNED AGENT. So the canonical, generated,
    single-source vocabulary was unreachable to its most important reader, and only
    restatements remained - the exact failure the resource was built to prevent. A subagent
    asked "what does exit 2 mean" had no route to the rendered definition.

    ⭐ TWO TRANSPORTS, ONE SOURCE. This function and `render_markdown` read the SAME constants
    through the SAME `_select`, so they cannot disagree; the resource serves the markdown and
    the tool serves this. Neither is a copy of the other.

    ⚠ `markdown` IS INCLUDED DELIBERATELY. A caller that only has the tool transport must be
    able to obtain exactly what a resource reader sees, or the two audiences are reading
    different documents and the divergence is invisible from both sides.
    """
    tables = _select(name)
    # ⛔ KEYS ARE STRINGIFIED HERE, ON PURPOSE, AND NOT LEFT TO THE SERIALISER. `EXIT_CODES` is
    # keyed by INT; JSON object keys can only be strings. So over the wire `{2: "..."}` becomes
    # `{"2": "..."}` silently, and a caller doing `vocabularies["exit_code"][2]` gets a KeyError
    # while `["2"]` works - with nothing in the schema saying which to use, because the schema
    # describes the Python shape and the transport quietly changed it.
    # ⭐ Converting here makes the published contract the SAME one the caller receives. The
    # alternative is a shape that is true in the process and false on the wire, which is this
    # fleet's defect class with the transport as the wrong object.
    return {
        "names": list(VOCABULARIES),
        "requested": name,
        "vocabularies": {k: {str(vk): vv for vk, vv in v.items()} for k, v in tables.items()},
        "markdown": render_markdown(name),
    }
