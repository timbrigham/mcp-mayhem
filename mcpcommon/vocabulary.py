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
    "usage": ("the CALL was malformed - a bad argument name, a missing required field. Fix the "
              "call and retry; the server never saw a valid request."),
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
    0: "ok - the check ran and found nothing.",
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
    2: ("NO USABLE VERDICT was produced - the check could not run, or its result could not "
        "be recorded. NOT a finding, and never 0 or 1. Distinguished from 3 by WHERE the gap "
        "is: 3 means it ran and could not decide about the CONTENT; 2 means no verdict "
        "reached the ledger at all. WHAT specifically failed is the CHECKER's to say, in "
        "that checker - never enumerated here."),
    # THE FIRST DRAFT OF THIS ENTRY WAS WRONG AND IT IS WORTH THE COMMENT. It read "scope not
    # resolved, a contested panel, a dependency unavailable" - an ENUMERATION of causes,
    # written without checking what the consumer's code does with 3. Measured 2026-09-09 after
    # their editorial gate caught it: their tree branches on 3 in THREE places -
    # check_paths.EXIT_SKIPPED (scope could not be determined), check_briefs.py:572, and
    # hooks.py:697 ON THE PUSH PATH, where 3 means "the ledger REACHED and REFUSED this record
    # - a DECISION, not an outage". NEITHER is a contested panel. The definition invented a
    # meaning the code does not implement and omitted two it does, inside the module built to
    # end exactly that. A vocabulary that enumerates CAUSES is a second copy of its callers.
    3: ("UNDETERMINED - it ran and could not return a finding-or-clean answer. Must never "
        "collapse into 0 or 1; that collapse is the defect this whole vocabulary exists to "
        "make unrepresentable. WHAT SPECIFICALLY made it undetermined is the CHECKER's to say, "
        "in that checker, mapped onto this - never enumerated here."),
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
#     EXIT_CODES     bound in 0 files, AND UNBINDABLE FROM HERE -- exit codes are emitted by the
#                    CONSUMER's checkers, in another repository. Only our own
#                    verdictLedger/client/record.py is in reach.
#
# ⚠ THE HAZARD IS THAT ALL FOUR LOOK IDENTICAL TO A READER. They sit in one dict, are rendered
# by one function, and are served through one resource, so a caller cannot tell the enforced
# table from the described one. `CLAUDE.md` requires a resource be GENERATED from the constants
# the code imports and forbids one that "merely describes what the code happens to do" -- and
# three of these four were the forbidden kind, published beside the one that was not.
#
# ⭐ SO `exit_code` IS A PUBLISHED CONVENTION THE FLEET DOES NOT ENFORCE, and saying that here
# is the honest alternative to implying a binding that cannot exist.

VOCABULARIES = {
    "error_type": ERROR_TYPES,
    "decision": DECISIONS,
    "row_status": ROW_STATUSES,
    "exit_code": EXIT_CODES,
}


def render_markdown():
    """The vocabularies as a document, GENERATED from the constants above.

    Never transcribe this into a brief or a readme. A copy is the fourth one and it goes stale
    the way a README's test count does - measured four times in one evening in one file. Point
    at the served resource instead.
    """
    out = ["# The fleet vocabularies", "",
           "One definition, imported by every server, rendered from the constants in",
           "mcpcommon/vocabulary.py. If a document restates any of this, the document is the",
           "copy that will be wrong.", ""]
    for name, table in VOCABULARIES.items():
        out.append("## " + name)
        out.append("")
        for key, meaning in table.items():
            out.append("- **`%s`** - %s" % (key, meaning))
        out.append("")
    return chr(10).join(out)
