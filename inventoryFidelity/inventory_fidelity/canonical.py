"""Canonical forms, and the ONE hash routine used by both registration and scan.

The metric compares a hash written into the inventory at registration time with a hash
computed from the deployed artifact at scan time. If those two hashes came from two different
routines, a "modified" result could mean the content changed or could mean the routines
disagree, and nothing would say which. So `register` and the scanner both call
`component_sha256` below; there is no second implementation to drift.

Declared forms:

  text  (.md .yaml .yml .txt)  UTF-8. One leading byte-order mark (U+FEFF) is removed. CRLF
                               and lone CR are rewritten to LF. Nothing else is changed:
                               trailing spaces, blank lines and a missing final newline all
                               still count as content.
  json  (.json)                Parsed, then re-serialised with
                               json.dumps(obj, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False), encoded UTF-8. Key order and insignificant
                               whitespace therefore do not change the hash.
  reference digest             For a model or dataset reference the hash IS the declared
                               content digest (see `reference_digest`); the referenced bytes
                               are not fetched.

BOM decision: a leading BOM is stripped in both text and JSON. A BOM is an encoding marker
that editors add or drop invisibly, the same as line-ending conversion, so treating it as
content would report "modified" for a change no reader can see. The cost is stated plainly:
adding or removing ONLY a BOM is not detected.

YAML is hashed as text, not parsed: the standard library has no YAML parser, so two YAML files
with the same meaning but different formatting hash differently.
"""

import hashlib
import json
import re

TEXT_SUFFIXES = (".md", ".yaml", ".yml", ".txt")
JSON_SUFFIXES = (".json",)
_BOM = "﻿"


class CanonicalFormError(ValueError):
    """The bytes cannot be put in their declared canonical form, so they cannot be hashed."""


def _decode(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanonicalFormError(f"not valid UTF-8 ({exc.reason} at byte {exc.start})") from None
    # Only ONE leading BOM is a marker; a second one would be content, and stays.
    return text[1:] if text.startswith(_BOM) else text


def canonical_text(raw: bytes) -> bytes:
    text = _decode(raw)
    # CRLF must be rewritten BEFORE lone CR. In the other order "\r\n" becomes "\n\n", and a
    # CRLF file would hash differently from its LF twin, which is the case this exists for.
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _refuse_duplicate_keys(pairs):
    # json.loads keeps the LAST of two equal keys and drops the other silently. Two files that
    # differ only in the dropped value would then hash the same, so a duplicate key is refused.
    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise CanonicalFormError(f"duplicate JSON object key {key!r}")
        seen.add(key)
    return dict(pairs)


def _refuse_constant(token):
    # NaN and Infinity are accepted by Python's json module but are not JSON; a canonical form
    # built on them would not be readable by other implementations.
    raise CanonicalFormError(f"non-standard JSON constant {token}")


def parse_json(raw: bytes):
    text = _decode(raw)
    try:
        return json.loads(text, object_pairs_hook=_refuse_duplicate_keys, parse_constant=_refuse_constant)
    except json.JSONDecodeError as exc:
        raise CanonicalFormError(f"not valid JSON ({exc.msg} at line {exc.lineno} column {exc.colno})") from None


def canonical_json(raw: bytes) -> bytes:
    obj = parse_json(raw)
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        # A JSON escape such as "\ud800" decodes to a lone surrogate, which has no UTF-8 form.
        raise CanonicalFormError("JSON string holds a lone surrogate, which has no UTF-8 encoding") from None


def form_for(relpath: str) -> str:
    """Which canonical form a file uses, from its suffix. An undeclared suffix is refused,
    never hashed as raw bytes, so every hash in a report was made under a declared form."""
    lower = relpath.lower()
    if lower.endswith(TEXT_SUFFIXES):
        return "text"
    if lower.endswith(JSON_SUFFIXES):
        return "json"
    raise CanonicalFormError(
        f"no canonical form is declared for {relpath!r}; declared suffixes: "
        + " ".join(TEXT_SUFFIXES + JSON_SUFFIXES))


def component_sha256(relpath: str, raw: bytes) -> str:
    """THE hash routine. Registration and scan both call this and nothing else."""
    form = form_for(relpath)
    canonical = canonical_text(raw) if form == "text" else canonical_json(raw)
    return hashlib.sha256(canonical).hexdigest()


# A content digest is "sha256:<64 hex>", optionally preceded by "<identifier>@". Anything else,
# notably a tag such as "llama3:latest", names a pointer that can be moved to other content, so
# it cannot say WHICH model or dataset is deployed.
_DIGEST = re.compile(r"(?:[^@\s]+@)?sha256:([0-9a-fA-F]{64})")


def reference_digest(ref) -> str:
    """The 64-hex SHA-256 digest a reference declares, lower-cased. Refuses a reference without one."""
    if not isinstance(ref, str) or not ref:
        raise CanonicalFormError("reference has no 'ref' string, so it carries no content digest")
    match = _DIGEST.fullmatch(ref)
    if match is None:
        raise CanonicalFormError(
            f"reference {ref!r} carries no content digest; expected sha256:<64 hex> "
            "or <name>@sha256:<64 hex>")
    return match.group(1).lower()
