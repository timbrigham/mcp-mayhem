"""Classification rules: map an observation to a pattern id.

Rule "1" is the only rule. It is declared here, in code, and a caller asking for any other
version is refused (the measurement would otherwise be computed under a rule nobody wrote).

RULE "1"
  Incidents     carry their pattern_id in the register; rule 1 takes it as recorded.
  Refusals      pattern = "gitrobot.<op>.<shape>", where <shape> is computed from structured
                fields only, never from message text:
                  read   the git subcommand in args.op            e.g. gitrobot.read.reset
                  push   "refspec-force" if args.branch starts with "+",
                         "refspec" if args.branch contains ":",
                         otherwise "branch"                         e.g. gitrobot.push.refspec-force
                  other  "any" (one pattern per op)                e.g. gitrobot.merge.any
                Names are lower-cased; characters outside [a-z0-9-] become "-". A missing or
                non-string field gives the shape "unknown", so an unparseable row still lands
                in a visible pattern rather than vanishing.

HOW REFUSALS MEET THE INCIDENT PATTERN SPACE
  By exact string equality and nothing else. There is no alias table in rule 1. The push
  shape was chosen so that a refused '+branch' push is the same pattern as incident
  gitrobot.push.refspec-force. A refused `read reset` is gitrobot.read.reset and does NOT
  coincide with git.reset.work-destroying: args.op alone cannot tell `reset --hard` from
  `reset --soft`, and the incident went through a different entry point. Making two names
  coincide requires a new rule version, not a fuzzy match.
"""

from __future__ import annotations

import re

KNOWN_RULES = ("1",)

_SAFE = re.compile(r"[^a-z0-9-]")


class UnknownRule(ValueError):
    pass


def require_rule(rule: str) -> str:
    if rule not in KNOWN_RULES:
        raise UnknownRule(
            "classification rule %r is not defined; known rules: %s"
            % (rule, ", ".join(KNOWN_RULES)))
    return rule


def _name(value) -> str:
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    return _SAFE.sub("-", value.strip().lower())


def refusal_shape(op: str, args) -> str:
    args = args if isinstance(args, dict) else {}
    if op == "read":
        return _name(args.get("op"))
    if op == "push":
        branch = args.get("branch")
        if not isinstance(branch, str):
            return "unknown"
        if branch.startswith("+"):
            return "refspec-force"
        if ":" in branch:
            return "refspec"
        return "branch"
    return "any"


def refusal_pattern(rule: str, op: str, args) -> str:
    require_rule(rule)
    return "gitrobot.%s.%s" % (_name(op), refusal_shape(op, args))


def reduce_args(op: str, args):
    """The smallest args that give the same rule-1 pattern. Used by the public fixture so
    that no argument beyond the pattern feature is published."""
    args = args if isinstance(args, dict) else {}
    if op == "read":
        return {"op": args["op"]} if "op" in args else {}
    if op == "push":
        branch = args.get("branch")
        if not isinstance(branch, str):
            return {}
        shape = refusal_shape(op, args)
        stand_in = {"refspec-force": "+b", "refspec": "a:b", "branch": "b"}[shape]
        return {"branch": stand_in}
    return {}
