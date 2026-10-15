"""Produce the PUBLIC fixture: a redacted extract of the private audit log, call logs, instance
map and incident register.

    python make_fixture.py --audit <private audit> --calls <private call log> [--calls ...]
                           --instances <private instance map> --register <private incidents.json>
                           [--manifest examples/guard-coverage/fixture/manifest.json]
                           [--out examples/guard-coverage/fixture] [--salt HEX]

Kept, and only this (everything else is dropped):
  audit rows   ts, op, decision, refusal_class, surface, versions -- each only when present
               in the source row, because an absent field means "before it existed" and must
               stay absent; session and client_call_id as salted SHA-256 (first 16 hex
               digits); args only on refused read/push rows, reduced to the rule-1 pattern
               feature (read: args.op).
  call rows    ts, surface, versions as above; session and client_call_id hashed the same way.
  instances    the map, both sides hashed: call id -> instance. An instance id is a transcript
               file's relative path, so it is hashed like every other id and no transcript name,
               path or content leaves.
  incidents    id, pattern_id, status, observed_at, detected_at, guarded_at, guard_commit,
               has_regression_test (a boolean: a hashed test name could be recovered from the
               manifest's clear names, since the salt is published), tool mapped to
               its entry-point label, session_known, session (salted SHA-256), and the entry
               points of any guard_history entries, and instance (hashed) when present.
No harm text, no notes, no paths, no other args.

The salt is written into metadata.json so the hashing is reproducible; the ids it hashes are
random MCP connection ids, so the salt does not make them guessable.

Before writing anything it measures the private inputs and the redacted extract and refuses
(exit 2) unless the two reports are identical, and unless the redaction scan is clean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from guard_coverage import core  # noqa: E402
from guard_coverage.inputs import (entry_point_of, load_audit, load_calls,  # noqa: E402
                                   load_instance_map, load_json)
from guard_coverage.rule import reduce_args  # noqa: E402

FILES = ("audit.jsonl", "calls.jsonl", "instances.json", "register.json", "manifest.json",
         "metadata.json", "expected_report.json")
FORBIDDEN = ("C:\\", "c:\\", "C:/", "Users", ".claude", "Workspace", "\\\\", ".lean",
             "tools/verify", "ZeroParadox/")


def h(salt, value, kind=None):
    """First 16 hex digits of sha256(salt:value), or of sha256(salt:kind:value) for a call id
    or an instance id. The kind keeps the namespaces apart: a register `session` that is in fact
    a conversation id must not hash to the same value as that conversation's instance id, which
    would let a reader join the two without the extract saying so."""
    if value is None:
        return None
    text = "%s:%s" % (salt, value) if kind is None else "%s:%s:%s" % (salt, kind, value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def reduce_row(row, salt):
    out = {"ts": row["ts"], "op": row["op"], "decision": row["decision"]}
    for k in ("refusal_class", "surface"):
        if k in row:
            out[k] = row[k]
    if "session" in row:
        out["session"] = h(salt, row["session"])
    if "client_call_id" in row:
        out["client_call_id"] = h(salt, row["client_call_id"], "call")
    if "versions" in row:
        v = row["versions"]
        out["versions"] = {k: v.get(k) for k in ("gitrobot_commit", "gitrobot_dirty",
                                                  "client_name", "client_version",
                                                  "consumer_hook_commit")}
    if row["decision"] == "refused" and row["op"] in ("read", "push"):
        a = reduce_args(row["op"], row.get("args"))
        if a:
            out["args"] = a
    return out


def reduce_call(row, salt):
    out = {"ts": row["ts"], "surface": row["surface"], "session": h(salt, row["session"]),
           "client_call_id": h(salt, row["client_call_id"], "call")}
    if "source" in row:
        out["source"] = row["source"]
    if "versions" in row:
        v = row["versions"]
        out["versions"] = {k: v.get(k) for k in ("gitrobot_commit", "gitrobot_dirty",
                                                  "client_name", "client_version",
                                                  "consumer_hook_commit")}
    return out


def reduce_map(m, ambiguous, salt):
    return {"map": {h(salt, k, "call"): h(salt, v, "instance") for k, v in sorted(m.items())},
            "ambiguous": sorted(h(salt, x, "call") for x in ambiguous)}


def reduce_register(doc, salt):
    coll = doc["collections"]["incidents"]
    entries = []
    for e in coll["entries"]:
        r = {"id": e["id"], "pattern_id": e["pattern_id"], "status": e["status"],
             "observed_at": e["observed_at"], "detected_at": e["detected_at"],
             "guarded_at": e["guarded_at"], "guard_commit": e["guard_commit"],
             "has_regression_test": bool(e["regression_test"]),
             "tool": entry_point_of(e["tool"]),
             "session_known": e["session"] is not None, "session": h(salt, e["session"])}
        if e.get("instance") is not None:
            r["instance"] = h(salt, e["instance"], "instance")
        if "guard_history" in e:
            r["guard_history"] = [{"entry_point": g.get("entry_point")}
                                  for g in e["guard_history"]]
        entries.append(r)
    return {"collections": {"incidents": {"schema_version": coll.get("schema_version"),
                                          "pattern_rule": coll["pattern_rule"],
                                          "entries": entries}}}


def dumps(obj):
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def scan(texts, register_doc):
    """Return redaction findings: forbidden fragments, or any harm/notes text."""
    secret = []
    for e in register_doc["collections"]["incidents"]["entries"]:
        secret.append(e.get("harm") or "")
        secret += [n.get("text", "") for n in e.get("notes", [])]
        if isinstance(e.get("args"), dict):
            for v in e["args"].values():
                secret += v if isinstance(v, list) else [str(v)]
    found = []
    for name, text in texts.items():
        for f in FORBIDDEN:
            if f in text:
                found.append("%s contains %r" % (name, f))
        for s in secret:
            # any 24-character run of a secret string is enough to call it leaked
            for i in range(0, max(1, len(s) - 23), 8):
                frag = s[i:i + 24]
                if len(frag) >= 12 and frag in text:
                    found.append("%s contains register text %r" % (name, frag))
                    break
    return found


def scan_raw_ids(texts, rows, calls, imap, register_entries=()):
    """Any raw id (session, call id, instance) surviving unhashed is a leak: an instance id is a
    transcript path, and a call id names a line in a private transcript."""
    raw = set(imap) | set(imap.values())
    for r in list(rows) + list(calls) + list(register_entries):
        for k in ("session", "client_call_id", "instance"):
            if isinstance(r.get(k), str):
                raw.add(r[k])
    found = []
    for name, text in texts.items():
        for v in raw:
            if len(v) >= 8 and v in text:
                found.append("%s contains a raw id %r" % (name, v[:12] + "..."))
                break
    return found


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--audit", required=True)
    p.add_argument("--calls", action="append", required=True)
    p.add_argument("--instances", required=True)
    p.add_argument("--register", required=True)
    p.add_argument("--manifest", default=str(HERE / "examples/guard-coverage/fixture/manifest.json"))
    p.add_argument("--out", default=str(HERE / "examples/guard-coverage/fixture"))
    p.add_argument("--salt")
    a = p.parse_args(argv)
    salt = a.salt or secrets.token_hex(16)

    rows = load_audit(a.audit)
    calls = load_calls(a.calls)
    imap, ambiguous = load_instance_map(a.instances)
    register = load_json(a.register, "register")
    manifest_bytes = Path(a.manifest).read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))

    red_rows = [reduce_row(r, salt) for r in rows]
    red_calls = [reduce_call(c, salt) for c in calls]
    red_map = reduce_map(imap, ambiguous, salt)
    red_reg = reduce_register(register, salt)
    real = core.measure(rows, register, manifest, calls=calls, instance_map=imap,
                        ambiguous_ids=ambiguous)
    fixt = core.measure([json.loads(json.dumps(r)) for r in red_rows], red_reg, manifest,
                        calls=[json.loads(json.dumps(c)) for c in red_calls],
                        instance_map=red_map["map"],
                        ambiguous_ids=frozenset(red_map["ambiguous"]))
    if real != fixt:
        sys.stderr.write("refused: the redacted extract does not reproduce the real report\n")
        return 2

    meta = {"what": "Redacted public extract of a private gitRobot audit log and incident "
                    "register, for Incident-Driven Guard Coverage. Real data, reduced.",
            "rule": "1",
            "unit": "agent instance",
            "session_hash": "first 16 hex digits of sha256(salt + ':' + id)",
            "call_id_hash": "first 16 hex digits of sha256(salt + ':call:' + id)",
            "instance_hash": "first 16 hex digits of sha256(salt + ':instance:' + id)",
            "salt_note": "The salt is published so the hashing is reproducible. Audit and call "
                         "row sessions are random MCP connection ids. A register entry's "
                         "session is whatever the register recorded: for an incident in an "
                         "agent shell it is the agent's conversation id, not an MCP id. Call "
                         "ids are random Claude Code tool_use ids. Instance ids are "
                         "transcript file names built from random conversation and agent ids. "
                         "None can be guessed, and the three kinds are hashed in separate "
                         "namespaces, so equal hashes never join different kinds of id. Test "
                         "names are not hashed: the register extract keeps only "
                         "has_regression_test.",
            "salt": salt,
            "source_audit_rows": len(rows),
            "source_call_rows": len(calls),
            "source_instance_map_entries": len(imap),
            "source_register_entries": len(red_reg["collections"]["incidents"]["entries"]),
            "kept_audit_fields": ["ts", "op", "decision", "refusal_class", "surface",
                                  "session (hashed)", "client_call_id (hashed)", "versions",
                                  "args (refused read: op; refused push: refspec shape)"],
            "kept_call_fields": ["ts", "surface", "session (hashed)",
                                 "client_call_id (hashed)", "versions",
                                 "source (on backfilled rows)"],
            "kept_instance_map": "client_call_id (hashed) -> instance (hashed); ambiguous: "
                                 "call ids found in several transcripts (hashed)",
            "kept_register_fields": ["id", "pattern_id", "status", "observed_at",
                                     "detected_at", "guarded_at", "guard_commit",
                                     "has_regression_test", "tool (entry point)",
                                     "session_known", "session (hashed)",
                                     "instance (hashed, when present)",
                                     "guard_history[].entry_point"]}
    texts = {
        "audit.jsonl": "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n"
                               for r in red_rows),
        "calls.jsonl": "".join(json.dumps(c, sort_keys=True, ensure_ascii=False) + "\n"
                               for c in red_calls),
        "instances.json": dumps(red_map),
        "register.json": dumps(red_reg),
        "manifest.json": manifest_bytes.decode("utf-8"),
        "metadata.json": dumps(meta),
        "expected_report.json": dumps(real),
    }
    problems = scan(texts, register) + scan_raw_ids(
        texts, rows, calls, imap, register["collections"]["incidents"]["entries"])
    if problems:
        sys.stderr.write("refused: redaction scan failed:\n  %s\n" % "\n  ".join(problems))
        return 2
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sums = []
    for name in FILES:
        data = texts[name].encode("utf-8")
        if b"\r\n" in data:
            sys.stderr.write("refused: %s would contain CRLF\n" % name)
            return 2
        if name != "manifest.json":
            (out / name).write_bytes(data)
        sums.append("%s  %s\n" % (hashlib.sha256(data).hexdigest(), name))
    (out / "CHECKSUMS.sha256").write_bytes("".join(sums).encode("utf-8"))
    print("wrote %d files to %s; real and fixture reports identical" % (len(FILES), out.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
