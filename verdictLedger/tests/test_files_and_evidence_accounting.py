"""Two defects found by the FIRST REAL RECORD through the new plumbing, 2026-08-25.

⚠⚠ NEITHER WAS REACHABLE FROM THE EXISTING SUITE, AND THAT IS THE POINT OF THIS FILE.
Every inventory test passes a `files` dict straight in, so `server._files` — the one
function that BUILDS that dict in production — had no coverage at all. And every
mechanical step's evidence files were already among its subjects, so evidence being
double-counted as coverage was invisible until a step arrived whose subjects and
evidence were disjoint.

`pdf_coupling` was that step: 40 root-level PDFs, evidence `batch.py` + `common.py`.
It reported `subjects_covered: 42` against `scope: 40`, and `STALE, covered 0` over
subjects that matched the index EXACTLY.
"""

import subprocess

import pytest

from conftest import good
from core import inventory as inventory_mod


def _git(repo, *args):
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture
def tiny_repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@e.invalid")
    _git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("alpha\n", encoding="utf-8")
    (r / "b.txt").write_text("beta\n", encoding="utf-8")
    _git(r, "add", "a.txt", "b.txt")
    _git(r, "commit", "-q", "-m", "one")
    return r


# -- ⭐⭐ the staged basis returned the STAGE column, not the blob ---------------

def test_staged_returns_blob_ids_not_the_stage_column(tiny_repo, monkeypatch):
    """⭐⭐ `git ls-files -s` prints `<mode> <blob> <stage> TAB <path>` and
    `git ls-tree -r` prints `<mode> blob <sha> TAB <path>`. The blob is field 1 in one
    and field 2 in the other. Reading field 2 for both returned the STAGE — `0` for
    every unconflicted entry — so `ref="staged"` mapped all 503 tracked files to "0",
    no subject could ever match, and EVERY key at the staged basis read STALE for
    ever.

    ⚠ It failed CLOSED, which is exactly why it survived: an unsatisfiable gate and a
    correctly-blocking gate are indistinguishable from outside.
    """
    from ledger_server import server
    monkeypatch.setattr(server, "REPO", str(tiny_repo))

    staged = server._files("staged")
    assert set(staged) == {"a.txt", "b.txt"}
    assert len(set(staged.values())) == 2, f"stage column leaked: {staged}"
    for path, blob in staged.items():
        assert blob == _git(tiny_repo, "hash-object", "--", path).strip()
        assert blob not in ("0", "100644")


def test_staged_and_head_agree_when_nothing_is_staged(tiny_repo, monkeypatch):
    """⚠ THE CROSS-CHECK. Two commands, two layouts, one answer — a clean tree must
    give identical maps or one of the two parsers is wrong."""
    from ledger_server import server
    monkeypatch.setattr(server, "REPO", str(tiny_repo))
    assert server._files("staged") == server._files("HEAD")


def test_a_staged_edit_shows_the_new_blob_not_the_committed_one(tiny_repo, monkeypatch):
    """⭐ The whole reason the staged basis exists: it must describe what a commit
    WOULD carry, not what HEAD already does."""
    from ledger_server import server
    monkeypatch.setattr(server, "REPO", str(tiny_repo))
    (tiny_repo / "a.txt").write_text("changed\n", encoding="utf-8")
    _git(tiny_repo, "add", "a.txt")
    assert server._files("staged")["a.txt"] != server._files("HEAD")["a.txt"]


# -- ⭐⭐ evidence is not coverage ----------------------------------------------

def _pdfish(ledger, files, subjects, evidence):
    rec = good(step="pdf_coupling", verdict="PASS",
               basis={"kind": "tree", "value": "t", "resolved_from": "explicit"},
               subjects=[{"path": p, "git_blob_id": b} for p, b in subjects],
               evidence=[{"path": p, "git_blob_id": b} for p, b in evidence])
    rec["id"] = "pdf_coupling@t#0"
    return inventory_mod.build(config=ledger.config, records=[rec], action="push",
                               files=files, ref="t", admission=["pdf_coupling"])


def test_evidence_paths_are_never_counted_as_covered_subjects(ledger):
    """⭐⭐ FOUND BY ZEROPARADOX FROM ARITHMETIC ALONE: 40 subjects + 2 evidence
    reported `subjects_covered: 42` against `scope: 40`.

    ⚠ `covered > scope` should be impossible, and it rendered as a LARGER number —
    coverage looking better than it is, which is the direction that matters.

    ⚠ It hid everywhere else because for almost every mechanical step the evidence
    files are ALREADY subjects (`check_encoding` covers all tracked text files,
    `batch.py` and `common.py` among them), so the two deduped and the double count
    was invisible. This fixture is the disjoint case on purpose.
    """
    files = {"one.pdf": "p1", "two.pdf": "p2",
             "tools/verify/batch.py": "e1", "tools/verify/common.py": "e2"}
    inv = _pdfish(ledger, files,
                  subjects=[("one.pdf", "p1"), ("two.pdf", "p2")],
                  evidence=[("tools/verify/batch.py", "e1"),
                            ("tools/verify/common.py", "e2")])
    row = next(r for r in inv["rows"] if r["step"] == "pdf_coupling")
    assert row["subjects_covered"] == 2
    assert row["subjects_covered"] <= row["scope"]
    assert row["status"] == "SATISFIED"


def test_evidence_is_not_reported_as_an_unscoped_subject(ledger):
    """⚠ The symmetric error: having removed evidence from `covered`, it must not
    reappear as "examined but unscoped" — a signal that fires on every mechanical
    record is one people scroll past."""
    files = {"one.pdf": "p1", "tools/verify/batch.py": "e1"}
    inv = _pdfish(ledger, files, subjects=[("one.pdf", "p1")],
                  evidence=[("tools/verify/batch.py", "e1")])
    assert inv["unscoped"] == []


# -- ⭐ the producer moving is a different fact from the corpus moving ----------

def test_a_moved_producer_stales_the_key_and_says_so(ledger):
    """⭐⭐ ZEROPARADOX'S EXACT QUESTION: does editing `common.py` stale a step via its
    EVIDENCE (correct — it is what V16/V17 are for) or via a phantom SUBJECT (wrong,
    and it misreports which content moved)? Merged in one bucket they were
    indistinguishable in the row."""
    files = {"one.pdf": "p1", "tools/verify/common.py": "MOVED"}
    inv = _pdfish(ledger, files, subjects=[("one.pdf", "p1")],
                  evidence=[("tools/verify/common.py", "e2")])
    row = next(r for r in inv["rows"] if r["step"] == "pdf_coupling")

    assert row["status"] == "STALE"
    assert row["subjects_stale"] == 0, "no subject moved; the producer did"
    assert row["evidence_stale"] == 1
    assert row["evidence_moved"] == ["tools/verify/common.py"]
    assert "the producer changed" in row["why"]
    assert "re-run the step" in row["why"]


def test_a_moved_subject_is_not_blamed_on_the_producer(ledger):
    """⚠ THE CONTROL, in the other direction: when the CORPUS moves, the row must not
    say the producer did."""
    files = {"one.pdf": "MOVED", "tools/verify/common.py": "e2"}
    inv = _pdfish(ledger, files, subjects=[("one.pdf", "p1")],
                  evidence=[("tools/verify/common.py", "e2")])
    row = next(r for r in inv["rows"] if r["step"] == "pdf_coupling")
    assert row["status"] == "STALE"
    assert row["evidence_stale"] == 0
    assert "producer changed" not in (row["why"] or "")
