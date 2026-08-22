"""Acceptance tests for the `withdrawn` disposition (interop request 2026-08-22).

An entry added by `add_new` for a declaration that was then REVERTED had no legal
terminal state: `dropped` presupposes a prior identity ("this existed and is now
gone") and these never existed at HEAD. The two available workarounds both write
false history — fabricating an `old.qualified`, or re-seeding via
`import_baseline` — and are exactly the defect a provenance registry exists to
prevent.

`withdrawn` is the mirror image of `dropped`, and the `old` side keeps them
honest: `dropped` requires a REAL anchored identity, `withdrawn` requires that
there is none. Neither can launder the other.

Mapped to the requester's definition of done:
  * `withdrawn` accepted with the §3 constraints, REJECTED when the old identity
    is real;
  * `withdraw` registered, reason required, terminal, `reopen` undoes it;
  * `drop` on an `add_new` entry still refused (must not regress);
  * `view('status')` counts `withdrawn` separately and excludes it from live;
  * the `phantoms` projection (§5).
"""

import json

import pytest

from consumers.store import build_store
from core.errors import OperationError, ValidationError

ANCHOR = {"branch": "origin/main", "commit": None, "tree": None}


def _store(tmp_path):
    return build_store(tmp_path / "store.json")


def _found(s, n=2):
    scan = [{"qualified": f"ZP.d{i}", "short": f"d{i}", "kind": "def",
             "file": f"ZP/M{i}.lean", "line": i, "prefix": "ZP"} for i in range(n)]
    s.apply("declarations", "import_baseline", {"scanner_output": scan, "anchor": ANCHOR})
    return [e["id"] for e in s.find("declarations")]


def _born(s, qualified="ZeroParadox.host_verdict_axis",
          file="ZeroParadox/Settheory/HostVerdict.lean"):
    res = s.apply("declarations", "add_new",
                  {"new": {"qualified": qualified, "file": file},
                   "reason": "HostVerdict.lean: the trinary carving"})
    return res["entries_touched"][0]


def _legacy_born(s, qualified="ZeroParadox.trinary_faces",
                 file="ZeroParadox/Settheory/HostVerdict.lean"):
    """The PRE-#16a shape: disposition 'new' with a fully null old — what the seven
    stranded entries actually look like in the live store."""
    eid = _born(s, qualified, file)
    doc = s.load()
    for entry in doc["collections"]["declarations"]["entries"]:
        if entry["id"] == eid:
            entry["old"] = {"qualified": None, "short": None, "kind": None,
                            "file": None, "line": None, "prefix": None}
    s.data_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    s.seal()
    return eid


# -- §6: withdraw succeeds on an add_new entry --------------------------------

@pytest.mark.parametrize("legacy", [False, True], ids=["synthetic-old", "legacy-null-old"])
def test_withdraw_an_add_new_entry_succeeds(tmp_path, legacy):
    s = _store(tmp_path)
    _found(s)
    eid = _legacy_born(s) if legacy else _born(s)
    s.apply("declarations", "withdraw",
            {"id": eid, "reason": "HostVerdict.lean reverted in full (7b997fa, 4a56da4) "
                                  "after a prior-art failure"})
    entry = s.get("declarations", eid)
    assert entry["disposition"] == "withdrawn"
    # the name it was added under is KEPT — that is the substance of the record
    assert entry["new"]["qualified"] == ("ZeroParadox.trinary_faces" if legacy
                                         else "ZeroParadox.host_verdict_axis")
    assert "reverted in full" in entry["reason"]
    assert s.validate() == []


def test_withdraw_requires_a_reason(tmp_path):
    s = _store(tmp_path)
    _found(s)
    eid = _born(s)
    with pytest.raises(OperationError, match="reason"):
        s.apply("declarations", "withdraw", {"id": eid, "reason": "   "})
    assert s.get("declarations", eid)["disposition"] == "new"


# -- §6: withdraw is REFUSED on an entry with a real identity ------------------

def test_withdraw_an_anchored_entry_is_refused(tmp_path):
    """The constraint that keeps the two dispositions honest: a declaration that
    genuinely existed cannot be relabelled 'added in error'."""
    s = _store(tmp_path)
    ids = _found(s)
    with pytest.raises(OperationError, match="did exist at the anchor|real anchored identity"):
        s.apply("declarations", "withdraw", {"id": ids[0], "reason": "tidying"})
    assert s.get("declarations", ids[0])["disposition"] == "pending"
    assert s.validate() == []


def test_schema_rejects_withdrawn_with_a_real_old(tmp_path):
    """Enforced in the rules, not only in the op — a hand-edited or apply-routed
    write cannot bypass it."""
    s = _store(tmp_path)
    ids = _found(s)
    doc = s.load()
    for entry in doc["collections"]["declarations"]["entries"]:
        if entry["id"] == ids[0]:
            entry["disposition"] = "withdrawn"
            entry["new"] = {"qualified": "ZP.d0", "short": "d0",
                            "file": "ZP/M0.lean", "namespace": "ZP"}
            entry["reason"] = "laundering a real declaration"
    violations = s.all_violations(doc)
    assert any("must be null or synthetic" in v for v in violations)


def test_drop_still_refused_on_an_add_new_entry(tmp_path):
    """Must not regress: `dropped` stays reserved for declarations that existed."""
    s = _store(tmp_path)
    _found(s)
    eid = _born(s)
    with pytest.raises(OperationError, match="withdraw"):
        s.apply("declarations", "drop", {"id": eid, "reason": "reverted"})
    assert s.get("declarations", eid)["disposition"] == "new"


def test_drop_still_works_on_an_anchored_entry(tmp_path):
    s = _store(tmp_path)
    ids = _found(s)
    s.apply("declarations", "drop", {"id": ids[0], "reason": "deleted at HEAD"})
    entry = s.get("declarations", ids[0])
    assert entry["disposition"] == "dropped" and entry["new"]["qualified"] is None
    assert s.validate() == []


# -- §6: terminal + reopen round-trip ------------------------------------------

def test_withdrawn_is_terminal(tmp_path):
    s = _store(tmp_path)
    _found(s)
    eid = _born(s)
    s.apply("declarations", "withdraw", {"id": eid, "reason": "reverted"})
    with pytest.raises(OperationError, match="is withdrawn; reopen it first"):
        s.apply("declarations", "rename",
                {"id": eid, "new_qualified": "ZP.x", "new_file": "f.lean",
                 "namespace": "ZP", "reason": "r"})


def test_reopen_round_trips_a_withdrawal(tmp_path):
    """Round-trip means back to where it was — 'new'. Returning it to 'pending'
    would assert it existed at the anchor, the false history withdrawn avoids."""
    s = _store(tmp_path)
    _found(s)
    eid = _born(s)
    before = s.get("declarations", eid)["new"]["qualified"]
    s.apply("declarations", "withdraw", {"id": eid, "reason": "reverted"})
    s.apply("declarations", "reopen", {"id": eid, "reason": "revert was itself reverted"})
    entry = s.get("declarations", eid)
    assert entry["disposition"] == "new"
    assert entry["new"]["qualified"] == before
    assert s.validate() == []


def test_reopen_still_returns_an_anchored_drop_to_pending(tmp_path):
    s = _store(tmp_path)
    ids = _found(s)
    s.apply("declarations", "drop", {"id": ids[0], "reason": "gone"})
    s.apply("declarations", "reopen", {"id": ids[0], "reason": "back"})
    entry = s.get("declarations", ids[0])
    assert entry["disposition"] == "pending" and entry["new"]["qualified"] is None
    assert s.validate() == []


# -- §3: a withdrawn name is GONE — deps and uniqueness ------------------------

def test_a_deps_edge_onto_a_withdrawn_entry_dangles(tmp_path):
    """Same rule as dropped, and it falls out of the match rule rather than being
    a special case: a withdrawn name is expected-GONE."""
    s = _store(tmp_path)
    _found(s)
    eid = _born(s, "ZeroParadox.nu_hosted_face")
    s.apply("deps", "import_deps",
            {"edges": [{"from": "ZP.d0", "to": "ZeroParadox.nu_hosted_face"}]})
    with pytest.raises(ValidationError, match="dangling edge"):
        s.apply("declarations", "withdraw", {"id": eid, "reason": "reverted"})
    assert s.get("declarations", eid)["disposition"] == "new"   # rolled back
    assert s.validate() == []


def test_a_withdrawn_name_frees_the_uniqueness_gate(tmp_path):
    """Withdrawing a name makes it available again — the entry no longer claims a
    live declaration, so re-adding the name later is not a duplicate."""
    s = _store(tmp_path)
    _found(s)
    first = _born(s, "ZeroParadox.wf_host_refuses_nu")
    s.apply("declarations", "withdraw", {"id": first, "reason": "reverted"})
    second = _born(s, "ZeroParadox.wf_host_refuses_nu")
    assert second != first
    assert s.validate() == []


# -- §6: the status view ------------------------------------------------------

def test_status_view_counts_withdrawn_and_excludes_it_from_live(tmp_path):
    s = _store(tmp_path)
    _found(s, 3)
    eid = _born(s)
    s.apply("declarations", "withdraw", {"id": eid, "reason": "reverted"})
    text = s.export_view("declarations", "status")
    assert "| withdrawn *(not live)* | 1 |" in text
    assert "| **live total** | **3** |" in text
    assert "| **all entries** | **4** |" in text


# -- §5: the phantoms projection ----------------------------------------------

def test_phantoms_view_lists_entries_whose_file_is_gone(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    root = tmp_path / "corpus"
    (root / "ZeroParadox").mkdir(parents=True)
    (root / "ZeroParadox" / "Live.lean").write_text("def alive := 1\n", encoding="utf-8")
    _born(s, "ZeroParadox.alive", "ZeroParadox/Live.lean")
    for name in ("host_verdict_axis", "nu_hosted_face"):
        _born(s, f"ZeroParadox.{name}", "ZeroParadox/Settheory/HostVerdict.lean")

    assert s.validate() == []          # green, while describing a file that is gone
    text = s.export_view("declarations", "phantoms", root=str(root))
    assert "**2** of 3 checked" in text
    assert "| ZeroParadox/Settheory/HostVerdict.lean | 2 |" in text
    assert "ZeroParadox.host_verdict_axis" in text
    assert "ZeroParadox.alive" not in text


def test_phantoms_view_ignores_terminal_and_anchor_era_entries(tmp_path):
    """A pending entry's location is an anchor-era path (stale by design) and a
    withdrawn/dropped entry is SUPPOSED to be gone — neither is drift."""
    s = _store(tmp_path)
    _found(s, 2)                      # both still pending, anchor-era files
    eid = _born(s)
    s.apply("declarations", "withdraw", {"id": eid, "reason": "reverted"})
    root = tmp_path / "corpus"
    root.mkdir()
    text = s.export_view("declarations", "phantoms", root=str(root))
    assert "**0** of 0 checked" in text


def test_phantoms_view_count_only(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    _born(s, "ZeroParadox.ghost", "ZeroParadox/Gone.lean")
    root = tmp_path / "corpus"
    root.mkdir()
    text = s.export_view("declarations", "phantoms", root=str(root), count_only=True)
    assert "**1** of 1 checked" in text
    assert "| id | qualified | file |" not in text      # summary only, no rows


# -- the seven, end to end -----------------------------------------------------

def test_the_seven_withdraw_in_sequence_and_export(tmp_path):
    """The requester's migration: withdraw each of the seven, then validate ->
    verify_integrity -> export. Total unchanged; new -> withdrawn."""
    s = _store(tmp_path)
    _found(s, 2)
    names = ["host_verdict_axis", "nu_hosted_forces_non_wf", "wf_host_refuses_nu",
             "nu_hosted_face", "nu_refused_face", "engine_blind_to_verdict",
             "trinary_faces"]
    ids = [_born(s, f"ZeroParadox.{n}") for n in names]
    total_before = len(s.find("declarations"))

    for eid in ids:
        s.apply("declarations", "withdraw",
                {"id": eid, "reason": "HostVerdict.lean reverted in full (7b997fa, 4a56da4)"})

    assert s.validate() == []
    s.verify_integrity()
    assert len(s.find("declarations")) == total_before          # nothing removed
    assert len(s.find("declarations", disposition="withdrawn")) == 7
    assert len(s.find("declarations", disposition="new")) == 0
    res = s.export_full(tmp_path / "ssot.json")
    assert res["entries"] == total_before
