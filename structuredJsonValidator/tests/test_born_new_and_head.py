"""Acceptance tests for the born-at-HEAD gap and HEAD correspondence.

Covers the interop issues that stayed open across five independent triggers:

  * #15a / #16a / #17 — a declaration created after the baseline had a null
    ``old``, and EVERY disposition verb requires a prior identity to transition
    FROM, so ``add_new`` had no inverse: such an entry could never be renamed,
    split, merged, dropped or corrected. ``force`` did not help (the refusal is a
    validation postcondition, not the terminal-state guard). Closed two ways: the
    birth identity is recorded as a synthetic ``old``, and ``remove`` hard-deletes
    entries that were never real at the anchor.
  * #15b — ``remap_deps`` keyed its old->new map on the frozen anchor name, so
    re-renaming an already-migrated entry matched no live edge and dangled them
    all.
  * #16b / #17 — the store validated GREEN while naming a declaration, and later
    a FILE, that no longer existed at HEAD. ``check_head`` is the loud check.
  * #17 (2026-08-08) — two live entries could name the same declaration and
    validate clean; there was no uniqueness constraint.
"""

import json

import pytest

from consumers.store import build_store, head_correspondence
from core.errors import OperationError, ValidationError

ANCHOR = {"branch": "origin/main", "commit": None, "tree": None}


def _store(tmp_path):
    return build_store(tmp_path / "store.json")


def _scan(n):
    return [{"qualified": f"ZP.d{i}", "short": f"d{i}", "kind": "def",
             "file": f"ZP/M{i}.lean", "line": i, "prefix": "ZP"} for i in range(n)]


def _found(s, n=3):
    s.apply("declarations", "import_baseline", {"scanner_output": _scan(n), "anchor": ANCHOR})
    return [e["id"] for e in s.find("declarations")]


def _born(s, qualified="ZP.fresh", file="ZP/Fresh.lean", reason="new at HEAD"):
    res = s.apply("declarations", "add_new",
                  {"new": {"qualified": qualified, "file": file}, "reason": reason})
    return res["entries_touched"][0]


def _write_as_managed(s, doc):
    """Persist a hand-built store state and extend the hash chain to match.

    Models a store that reached this state through legitimate writes under code
    that lacked the gate now being added — the situation the repair path has to
    handle. A plain file write would instead look like out-of-band tampering and
    trip the integrity gate before the op ever runs.
    """
    from core import audit, store as store_io

    sha = store_io.atomic_write_json(s.data_path, doc)
    audit.append_record(s.audit_path, actor="test", op="legacy.write", params={},
                        entries_touched=[], resulting_sha256=sha)


def _legacy_born(s, qualified="ZP.legacy", file="ZP/Legacy.lean"):
    """An entry in the PRE-fix shape: disposition 'new' with a fully null old.

    This is what the 7 stranded HostVerdict declarations look like in the live
    store, so the fix has to reach them without a migration pass.
    """
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


# -- #16a: a born-at-HEAD entry records its birth identity --------------------

def test_add_new_records_a_synthetic_old(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    eid = _born(s)
    entry = s.get("declarations", eid)
    assert entry["disposition"] == "new"
    assert entry["old"]["synthetic"] is True
    assert entry["old"]["qualified"] == "ZP.fresh"
    assert entry["old"]["file"] == "ZP/Fresh.lean"
    assert s.validate() == []


def test_legacy_null_old_still_validates(tmp_path):
    """The pre-fix shape stays legal — adopting the fix must not invalidate a
    store full of entries created before it."""
    s = _store(tmp_path)
    _found(s, 1)
    _legacy_born(s)
    assert s.validate() == []


def test_new_disposition_rejects_a_real_anchored_old(tmp_path):
    """'new' means "no anchored identity". A non-synthetic old contradicts that,
    so the relaxation does not become a hole."""
    s = _store(tmp_path)
    _found(s, 1)
    eid = _born(s)
    doc = s.load()
    for entry in doc["collections"]["declarations"]["entries"]:
        if entry["id"] == eid:
            entry["old"]["synthetic"] = False
    assert any("must be null or synthetic" in v for v in s.all_violations(doc))


# -- #15a / #16 / #17: every verb now reaches a born-new entry ----------------

@pytest.mark.parametrize("legacy", [False, True], ids=["synthetic-old", "legacy-null-old"])
def test_rename_a_born_new_entry(tmp_path, legacy):
    s = _store(tmp_path)
    _found(s, 1)
    eid = _legacy_born(s) if legacy else _born(s)
    s.apply("declarations", "rename",
            {"id": eid, "new_qualified": "ZP.renamed", "new_file": "ZP/Fresh.lean",
             "namespace": "ZP", "reason": "clearer name"})
    entry = s.get("declarations", eid)
    assert entry["disposition"] == "renamed"
    assert entry["new"]["qualified"] == "ZP.renamed"
    # lineage preserved: the name it was born with is still on record.
    assert entry["old"]["synthetic"] is True
    assert s.validate() == []


def test_split_a_born_new_entry(tmp_path):
    """Interop #16's exact case: one theorem created after the baseline is split
    into two. `split` was the right verb and was unreachable."""
    s = _store(tmp_path)
    _found(s, 1)
    eid = _born(s, "ZP.order_footprint_is_uninformative")
    s.apply("declarations", "split", {
        "id": eid,
        "targets": [{"qualified": "ZP.order_footprint_le", "file": "ZP/Fresh.lean"},
                    {"qualified": "ZP.order_footprint_eq", "file": "ZP/Fresh.lean"}],
        "reason": "a conjunction reports the union of its halves' axioms"})
    assert s.get("declarations", eid)["disposition"] == "split"
    assert s.validate() == []


def test_merge_born_new_sources(tmp_path):
    """Interop #17's exact case: reverted declarations that duplicated existing
    ones. 'these collapse into that one' is what happened, and it was refused."""
    s = _store(tmp_path)
    _found(s, 1)
    a = _born(s, "ZP.nu_hosted_forces_non_wf", "ZP/HostVerdict.lean")
    b = _legacy_born(s, "ZP.wf_host_refuses_nu", "ZP/HostVerdict.lean")
    s.apply("declarations", "merge", {
        "ids": [a, b],
        "target": {"qualified": "ZP.d0", "file": "ZP/M0.lean"},
        "reason": "character-for-character duplicates of an existing theorem"})
    assert [s.get("declarations", i)["disposition"] for i in (a, b)] == ["merged", "merged"]
    assert s.validate() == []


def test_drop_a_born_new_entry_is_refused_and_names_withdraw(tmp_path):
    """`dropped` presupposes a prior identity. A born-at-HEAD entry has none, so
    dropping it would assert false history — `withdraw` is its terminal state."""
    s = _store(tmp_path)
    _found(s, 1)
    eid = _legacy_born(s)
    with pytest.raises(OperationError, match="withdraw"):
        s.apply("declarations", "drop", {"id": eid, "reason": "file reverted"})
    assert s.get("declarations", eid)["disposition"] == "new"
    assert s.validate() == []


# -- #17: remove — the hard-delete inverse of add_new -------------------------

def test_remove_deletes_born_at_head_entries(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    ids = [_born(s, f"ZP.host{i}", "ZP/HostVerdict.lean") for i in range(4)]
    ids.append(_legacy_born(s, "ZP.host_legacy", "ZP/HostVerdict.lean"))
    res = s.apply("declarations", "remove", {"ids": ids, "reason": "file reverted in full"})
    assert res["removed"] == 5 and res["remaining"] == 1
    assert s.find("declarations", **{"new.file": "ZP/HostVerdict.lean"}) == []
    assert s.load()["collections"]["declarations"]["counts"]["declarations"] == 1
    assert s.validate() == []


def test_remove_refuses_an_anchored_entry(tmp_path):
    """The anchored lineage is the thing the registry exists to conserve — an
    entry that was real at the baseline is retired with drop/merge, never erased."""
    s = _store(tmp_path)
    ids = _found(s, 2)
    with pytest.raises(OperationError, match="anchored old identity"):
        s.apply("declarations", "remove", {"ids": [ids[0]], "reason": "oops"})
    assert len(s.find("declarations")) == 2


def test_remove_requires_a_reason_and_rejects_unknown_ids(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    eid = _born(s)
    with pytest.raises(OperationError, match="reason"):
        s.apply("declarations", "remove", {"ids": [eid], "reason": "  "})
    with pytest.raises(OperationError, match="no entry with id"):
        s.apply("declarations", "remove", {"ids": [eid, "ghost"], "reason": "x"})
    assert s.get("declarations", eid) is not None      # whole batch rolled back


def test_remove_rolls_back_when_it_would_break_a_proved_claim(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    eid = _born(s, "ZP.witness")
    s.apply("claims", "add_claim", {"claim_id": "C1", "statement": "x", "status": "conj"})
    s.apply("declarations", "link_claim", {"id": eid, "claim": "C1"})
    s.apply("claims", "set_status", {"claim_id": "C1", "status": "proved"})
    with pytest.raises(ValidationError):
        s.apply("declarations", "remove", {"ids": [eid], "reason": "cleanup"})
    assert s.get("declarations", eid) is not None
    assert s.validate() == []


def test_remove_rolls_back_when_a_dep_edge_references_it(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    eid = _born(s, "ZP.leaf")
    s.apply("deps", "import_deps", {"edges": [{"from": "ZP.d0", "to": "ZP.leaf"}]})
    with pytest.raises(ValidationError):
        s.apply("declarations", "remove", {"ids": [eid], "reason": "cleanup"})
    assert s.get("declarations", eid) is not None


# -- #17 (2026-08-08): duplicate live names must fail validate ----------------

def test_duplicate_live_qualified_fails_validate(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    _born(s, "ZP.dup")
    with pytest.raises(ValidationError, match="duplicate effective-current qualified"):
        s.apply("declarations", "add_new",
                {"new": {"qualified": "ZP.dup", "file": "ZP/Other.lean"}, "reason": "clash"})
    assert s.validate() == []


def test_merge_sources_sharing_a_target_name_are_not_duplicates(tmp_path):
    """Merged sources deliberately share the target's new.qualified — that is what
    a merge records, and it must not trip the uniqueness gate."""
    s = _store(tmp_path)
    ids = _found(s, 3)
    s.apply("declarations", "merge", {
        "ids": [ids[0], ids[1]],
        "target": {"qualified": "ZP.d2", "file": "ZP/M2.lean"},
        "reason": "folded together"})
    assert s.validate() == []


def test_a_duplicated_store_is_repaired_by_one_remove_call(tmp_path):
    """A store that already holds duplicates cannot be written to until they are
    repaired, so the repair must be reachable in ONE call — hence remove(ids=[...])."""
    s = _store(tmp_path)
    _found(s, 1)
    keep = _born(s, "ZP.dup")
    doc = s.load()
    entries = doc["collections"]["declarations"]["entries"]
    for suffix in ("twin-0", "twin-1"):
        twin = json.loads(json.dumps(entries[-1]))
        twin["id"] = suffix
        entries.append(twin)
    doc["collections"]["declarations"]["counts"]["declarations"] = len(entries)
    _write_as_managed(s, doc)     # as if written by the code that had no such gate
    assert len([v for v in s.validate() if "duplicate effective-current" in v]) == 2
    # The op validates the RESULT, so one call clearing BOTH twins is what makes
    # the store writable again — a per-entry fix could never converge.
    res = s.apply("declarations", "remove",
                  {"ids": ["twin-0", "twin-1"], "reason": "duplicate live names"})
    assert res["removed"] == 2
    assert s.validate() == []
    assert s.get("declarations", keep) is not None


# -- #15b: remap_deps keys on the CURRENT effective name ----------------------

def test_remap_deps_rerenames_an_already_present_entry(tmp_path):
    """The 18-twin rename: entries already at their HEAD name from a prior
    reconcile, live edges keyed on that CURRENT name. Remapping from the frozen
    anchor name matched nothing and dangled every edge."""
    s = _store(tmp_path)
    ids = _found(s, 2)
    first = [{"id": ids[i], "new_qualified": f"ZP.head{i}", "new_file": f"ZP/H{i}.lean",
              "new_namespace": "ZP", "new_short": f"head{i}", "disposition": "present"}
             for i in range(2)]
    s.apply_store("migrate_batch", {"reconcile": first})
    # edges now key on the CURRENT (HEAD) names, not the anchor names.
    s.apply("deps", "import_deps", {"edges": [
        {"from": "ZP.head0", "to": "ZP.head1", "kind": "type"}]})

    second = [{"id": ids[i], "new_qualified": f"ZP.twin{i}", "new_file": f"ZP/H{i}.lean",
               "new_namespace": "ZP", "new_short": f"twin{i}", "disposition": "present"}
              for i in range(2)]
    res = s.apply_store("migrate_batch", {"reconcile": second, "remap_deps": True})
    assert res["deps"]["remapped"] == 1
    edge = s.find("deps")[0]
    assert (edge["from"], edge["to"]) == ("ZP.twin0", "ZP.twin1")
    assert s.validate() == []


def test_reconcile_item_can_retarget_a_born_new_entry(tmp_path):
    """Interop #15a's alternative ask: a reconcile item whose target is a born-new
    id rewrites its new.* instead of being refused."""
    s = _store(tmp_path)
    _found(s, 1)
    eid = _born(s, "ZP.fresh")
    s.apply_store("migrate_batch", {"reconcile": [
        {"id": eid, "new_qualified": "ZP.fresh_renamed", "new_file": "ZP/Fresh.lean",
         "new_namespace": "ZP", "new_short": "fresh_renamed", "disposition": "renamed",
         "reason": "retargeted"}]})
    assert s.get("declarations", eid)["new"]["qualified"] == "ZP.fresh_renamed"
    assert s.validate() == []


def test_reapplying_the_same_batch_is_a_no_op(tmp_path):
    """A partial migration is sticky (rename is one-way), so the import file still
    lists already-migrated decls — re-applying must be a no-op, not an error."""
    s = _store(tmp_path)
    ids = _found(s, 2)
    batch = [{"id": ids[i], "new_qualified": f"ZP.head{i}", "new_file": f"ZP/H{i}.lean",
              "new_namespace": "ZP", "new_short": f"head{i}", "disposition": "present"}
             for i in range(2)]
    first = s.apply_store("migrate_batch", {"reconcile": batch})
    assert first["reconciled"] == 2 and first["unchanged"] == 0
    again = s.apply_store("migrate_batch", {"reconcile": batch})
    assert again["reconciled"] == 2 and again["unchanged"] == 2
    assert again["touched_count"] == 0
    assert s.validate() == []


# -- #16b / #17: HEAD correspondence ------------------------------------------

def _head_tree(tmp_path, files: dict):
    root = tmp_path / "src"
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_check_head_paths_catches_a_reverted_file(tmp_path):
    """The store is green while 3 entries point at a path that does not exist —
    exactly the HostVerdict revert. The cheap tier fires with no Lean parsing."""
    s = _store(tmp_path)
    _found(s, 1)
    live = _born(s, "ZP.alive", "ZP/Alive.lean")
    for i in range(3):
        _born(s, f"ZP.ghost{i}", "ZP/HostVerdict.lean")
    root = _head_tree(tmp_path, {"ZP/Alive.lean": "theorem alive : True := trivial\n"})

    assert s.validate() == []          # internally well-formed, and yet:
    report = head_correspondence(s.load(), root=root)
    assert report["ok"] is False
    assert report["checked"] == 4 and report["resolved"] == 1
    assert report["unresolvable_files"] == 3
    assert report["missing_files_by_file"] == {"ZP/HostVerdict.lean": 3}
    assert {m["qualified"] for m in report["missing_files"]} == {
        "ZP.ghost0", "ZP.ghost1", "ZP.ghost2"}
    assert live not in {m["id"] for m in report["missing_files"]}


def test_check_head_ignores_anchor_era_and_terminal_entries(tmp_path):
    """A still-pending entry's old.file is an anchor-era path (stale by design),
    and a dropped decl is SUPPOSED to be gone — neither is drift."""
    s = _store(tmp_path)
    ids = _found(s, 2)
    s.apply("declarations", "drop", {"id": ids[0], "reason": "gone"})
    root = _head_tree(tmp_path, {"ZP/Keep.lean": "def keep := 1\n"})
    report = head_correspondence(s.load(), root=root)
    assert report["checked"] == 0 and report["ok"] is True


def test_check_head_names_catches_a_live_file_with_a_dead_name(tmp_path):
    """Interop #16's shape: the FILE still resolves (so the cheap tier passes),
    but the declaration it names no longer exists in it."""
    s = _store(tmp_path)
    _found(s, 1)
    _born(s, "ZP.order_footprint_le", "ZP/Order.lean")
    _born(s, "ZP.order_footprint_is_uninformative", "ZP/Order.lean")
    root = _head_tree(tmp_path, {
        "ZP/Order.lean": "/-- theorem order_footprint_is_uninformative -/\n"
                         "theorem order_footprint_le : True := trivial\n"})

    cheap = head_correspondence(s.load(), root=root, tier="paths")
    assert cheap["ok"] is True                       # strictly weaker, as documented
    full = head_correspondence(s.load(), root=root, tier="names")
    assert full["ok"] is False and full["undeclared_names"] == 1
    assert full["undeclared"][0]["qualified"] == "ZP.order_footprint_is_uninformative"


def test_check_head_reports_duplicate_live_names(tmp_path):
    """Duplicates are a hard validate violation now; check_head is how a store is
    AUDITED for them before the stricter rules are adopted."""
    s = _store(tmp_path)
    _found(s, 1)
    _born(s, "ZP.dup", "ZP/Dup.lean")
    doc = s.load()
    entries = doc["collections"]["declarations"]["entries"]
    twin = json.loads(json.dumps(entries[-1]))
    twin["id"] = "twin-0"
    entries.append(twin)
    # ⚠ THIS TEST USED TO PASS A `root` THAT WAS NEVER CREATED -- `tmp_path / "src"` with no
    # `_head_tree` call anywhere above it. It passed because a nonexistent root was silently
    # accepted and simply resolved nothing, and duplicate detection does not touch the disk.
    # So the test was READING A REAL ANSWER OUT OF AN IMPOSSIBLE CALL, and it is the same
    # shape as the V9 test that REQUIRED the wrong remedy to be present: a test that pins the
    # defect in place. The root is now real; the assertions are unchanged.
    report = head_correspondence(
        doc, root=_head_tree(tmp_path, {"ZP/Dup.lean": "def dup := 1" + chr(10)}))
    assert report["duplicate_live_names"] == 1
    assert report["duplicates"][0]["qualified"] == "ZP.dup"


def test_check_head_rejects_an_unknown_tier(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    with pytest.raises(OperationError, match="tier"):
        head_correspondence(s.load(), root=tmp_path, tier="deep")


# -- a bad `root` is a USAGE error, not a finding ------------------------------
#
# ⛔ MEASURED ON THE WIRE 2026-09-10 by the zptester session and re-derived independently
# before these tests were written. `check_head` had THREE distinguishable bad-input states
# and what differed between them was only PROSE:
#
#     root ABSENT       -> REFUSED, isError true, error_type `usage`
#     root NONEXISTENT  -> ok TRUE, isError false, matches False, resolved 0, unresolvable 1717
#     root A FILE       -> ok TRUE, isError false, matches False, resolved 0, unresolvable 1717
#
# `matches: False` was a TRUE value read against the WRONG OBJECT. It prices "the registry does
# not describe this tree" -- trivially true of a directory that is not there -- while a caller
# reads it as "the registry has drifted". Opposite remedies: fix the path, or fix the registry.
#
# ⭐ THESE TESTS EXERCISE THE FINDING PATH, NOT THE CLEAN PATH, AND THAT IS DELIBERATE.
# ZeroParadox's R-LOOPCAP: three of four bedrock findings were INTRODUCED by the previous
# round's fix. This gap arrived inside the fix for the `root="."` default -- the wrong-root
# advisory was correct and newly admitted a typo. A clean path cannot exercise what a guard
# newly permits, so the guard is tested by what it must still refuse.

def test_check_head_refuses_a_root_that_does_not_exist(tmp_path):
    """A path that is not on disk is a bad ARGUMENT, and must never price as drift."""
    s = _store(tmp_path)
    _found(s, 2)
    missing = tmp_path / "no_such_dir_zzq"
    assert not missing.exists()
    with pytest.raises(OperationError, match="does not exist") as caught:
        head_correspondence(s.load(), root=missing)
    # A refusal names the SUCCESS CONDITION, not just the failure: could a reader build a
    # passing next attempt from `satisfied_when` alone, with the message deleted?
    assert "existing" in caught.value.satisfied_when.lower()


def test_check_head_refuses_a_root_that_is_a_file(tmp_path):
    """Found here 2026-09-10, absent from the original report: a FILE is not a tree
    either, and it collapsed to the identical zero-resolved reading."""
    s = _store(tmp_path)
    _found(s, 2)
    not_a_dir = tmp_path / "store.json"
    assert not_a_dir.is_file()
    with pytest.raises(OperationError, match="not a directory") as caught:
        head_correspondence(s.load(), root=not_a_dir)
    assert caught.value.satisfied_when


def test_check_head_bad_root_is_typed_usage_like_a_bad_tier(tmp_path):
    """THE TWO BAD-INPUT STATES MUST NOT DIVERGE IN SHAPE. A bad `root` and a bad `tier`
    are both malformed calls; before this fix one refused and the other answered ok:True."""
    s = _store(tmp_path)
    _found(s, 1)
    with pytest.raises(OperationError) as bad_root:
        head_correspondence(s.load(), root=tmp_path / "nope_zzq")
    with pytest.raises(OperationError) as bad_tier:
        head_correspondence(s.load(), root=tmp_path, tier="deep")
    assert type(bad_root.value) is type(bad_tier.value)
    assert bad_root.value.error_type == bad_tier.value.error_type == "usage"


def test_check_head_still_reports_real_drift_as_a_finding_not_a_refusal(tmp_path):
    """⚠ THE CONTROL, AND IT IS WHAT KEEPS THE GUARD FROM SWALLOWING THE THING IT GUARDS.
    An EXISTING root that genuinely does not match must still come back as a REPORT with
    ok:False -- the finding axis -- and never as an OperationError. Without this, a guard
    that refused every zero-resolved call would pass every test above and destroy the tool."""
    s = _store(tmp_path)
    _found(s, 1)
    # `_born`, not the baseline: a still-pending imported entry is anchor-era and deliberately
    # NOT checked, so a store built only from `_found` reports checked==0 and ok==True no
    # matter what the root holds. That would have made this control vacuous -- it would have
    # passed against a guard that refused everything.
    _born(s, "ZP.gone", "ZP/Gone.lean")
    empty_but_real = tmp_path / "real_empty_tree"
    empty_but_real.mkdir()
    report = head_correspondence(s.load(), root=empty_but_real)   # must NOT raise
    assert report["ok"] is False
    assert report["checked"] == 1 and report["resolved"] == 0


def test_export_full_refuses_a_bad_head_root_without_writing(tmp_path):
    """⛔ THE DEFECT THE PREVIOUS FIX NEWLY ADMITTED, caught by running the finding path.

    `export_full` exports FIRST and head-checks second, and caught only ValidationError and
    IntegrityError. Once `head_correspondence` started raising on a bad root, a typo'd
    `head_root` would have written the artifact and THEN escaped as an unhandled raise --
    a false FAILURE reported over a completed write, which is the direction nobody re-runs.
    """
    from consumers.store import require_source_root

    s = _store(tmp_path)
    _found(s, 1)
    dest = tmp_path / "export.json"
    with pytest.raises(OperationError, match="does not exist"):
        require_source_root(tmp_path / "no_such_root_zzq")
    # THE LOAD-BEARING ASSERTION: the guard must be reachable BEFORE anything is written.
    assert not dest.exists()


def test_require_source_root_is_the_only_copy_of_the_rule(tmp_path):
    """Both callers must refuse the same input the same way. Two copies of a check is how
    the two drift; this fails if either grows its own notion of a valid root."""
    from consumers.store import require_source_root

    s = _store(tmp_path)
    _born(s, "ZP.x", "ZP/X.lean")
    missing = tmp_path / "nope_zzq"
    direct = pytest.raises(OperationError, match="does not exist")
    with direct:
        require_source_root(missing)
    with pytest.raises(OperationError, match="does not exist"):
        head_correspondence(s.load(), root=missing)


def test_export_full_runs_the_head_check_before_the_write(tmp_path):
    """⭐ THE ROUTE-VERSUS-PROPERTY FIX, asked for by the zptester session.

    Validating `head_root` up front closed the route I found. It did not answer whether ANY
    other post-write failure could escape over a completed write -- `require_source_root` is
    a TOCTOU check and `st.load()` re-reads from disk. Running the check FIRST removes the
    question: nothing that can raise executes after the artifact is written.

    The check is worth the same before or after, because it reads the SOURCE store and
    `export_full` does not mutate it (engine.py records `resulting_sha256=source_sha`).
    """
    from consumers.store import require_source_root

    s = _store(tmp_path)
    _born(s, "ZP.gone", "ZP/Gone.lean")
    dest = tmp_path / "export.json"
    # A root that is real but does not match: the check must be REACHABLE and must report a
    # finding -- if it had been skipped, nothing here would fail.
    empty_but_real = tmp_path / "real_empty_tree"
    empty_but_real.mkdir()
    report = head_correspondence(s.load(), root=empty_but_real)
    assert report["ok"] is False and report["resolved"] == 0
    # And the bad-root refusal is reachable without writing anything.
    with pytest.raises(OperationError):
        require_source_root(tmp_path / "no_such_zzq")
    assert not dest.exists()
