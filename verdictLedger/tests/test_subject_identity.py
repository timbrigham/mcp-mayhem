"""`subjects[].git_blob_id` carries GIT'S BLOB ID, and nothing else can ever satisfy a key.

⚠⚠ THIS FILE EXISTS BECAUSE OF A MEASURED FAILURE (2026-08-23). The field was named
`sha256`, so the ZeroParadox client computed a sha256 digest of the file bytes — the
obvious reading of the name. `inventory` compares against what `git ls-tree` prints,
which is git's object id: SHA-1 over ``b"blob <len>\\0" + data``. A different hash
function over a different byte string.

The consequence was not a loud failure. The record APPENDED CLEANLY and then read
STALE forever, which is indistinguishable from a staleness bug — the ZP session spent
an afternoon (correctly) verifying that its sha256 matched disk byte-for-byte and
concluding the ledger's staleness logic was broken. It was not. Nothing was wrong
except that the two sides were hashing different things.

Two halves to the fix, both tested here:
  * the field is named `git_blob_id` (12-0-quater: "name the field for what it
    holds"), so it stops instructing writers to compute the wrong thing, and
    `client.record.blob_id()` removes the choice entirely by asking git;
  * a subject that CANNOT match is refused at append. A record that can never be
    satisfied is not a valid record — it is a claim to have examined something,
    expressed in a form the system can never confirm. Letting it rot to STALE is the
    same fail-open shape as absence rendering as success.

Tim's rule, and the reason the value is git's: "there should be exactly one hash
value in use, the signature hash for git itself."
"""

import hashlib
import subprocess

import pytest

from core import validate as validate_mod
from core.errors import ValidationFailure
from client.record import blob_id, blobs_at


GIT_BLOB = "a" * 40          # a plausible sha1 object id
SHA256 = "b" * 64            # what a content digest looks like


@pytest.fixture(autouse=True)
def _sha1_repo(monkeypatch):
    """Pin the object format so these tests do not depend on a real repo."""
    monkeypatch.setattr(validate_mod, "_OBJECT_FORMAT", 40)


def _subject(blob):
    return {"path": "x.lean", "git_blob_id": blob}


# -- ⭐ the helper produces exactly what git produces --------------------------

def test_blob_id_matches_git_exactly(tmp_path):
    """⭐ THE LOAD-BEARING EQUIVALENCE. If this drifts, every key silently stops
    being satisfiable — which is precisely how the defect presented."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    f = tmp_path / "x.lean"
    f.write_bytes(b"theorem foo : True := trivial\n")
    subprocess.run(["git", "add", "x.lean"], cwd=tmp_path, check=True, capture_output=True)

    from_git = subprocess.run(["git", "hash-object", "x.lean"], cwd=tmp_path,
                              capture_output=True, text=True).stdout.strip()
    assert blob_id("x.lean", repo=str(tmp_path)) == from_git


def test_a_sha256_of_the_same_file_is_a_different_value(tmp_path):
    """⚠ Names the trap explicitly: these are not two encodings of one number."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    data = b"theorem foo : True := trivial\n"
    (tmp_path / "x.lean").write_bytes(data)
    assert blob_id("x.lean", repo=str(tmp_path)) != hashlib.sha256(data).hexdigest()


def test_blobs_at_agrees_with_blob_id(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "m", str(tmp_path)], check=True,
                   capture_output=True)
    for args in (["config", "user.email", "t@t"], ["config", "user.name", "t"],
                 ["config", "commit.gpgsign", "false"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "x.lean").write_bytes(b"content\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "c"], cwd=tmp_path, check=True,
                   capture_output=True)
    assert blobs_at("HEAD", repo=str(tmp_path))["x.lean"] == blob_id("x.lean",
                                                                    repo=str(tmp_path))


# -- ⭐ a subject that can never match is refused at the door ------------------

def test_a_sha256_subject_is_refused_not_appended(ledger):
    """⭐⭐ THE HEADLINE REGRESSION. Before this, the record appended and rotted."""
    with pytest.raises(ValidationFailure) as exc:
        ledger.append({"schema": "zp.record.v1", "step": "check_invariants", "verdict": "PASS",
                       "tier": "M", "basis": {"kind": "tree", "value": "a" * 40,
                                              "resolved_from": "explicit"},
                       "decided": {"how": "signature", "who": "t", "passes": 1, "agreed": 1},
                       "subjects": [_subject(SHA256)], "run": {"id": "r"}})
    msg = str(exc.value)
    assert "64 hex characters" in msg and "40" in msg
    # ⚠ It must NAME the likely cause and the remedy. "invalid subject" would have
    # sent the reader back to re-verifying their sha256, which is where the
    # afternoon went.
    assert "sha256 of the file contents" in msg
    assert "blob_id" in msg


def test_a_real_blob_id_validates(ledger):
    out = ledger.append({"schema": "zp.record.v1", "step": "check_invariants", "verdict": "PASS",
                         "tier": "M", "basis": {"kind": "tree", "value": "a" * 40,
                                                "resolved_from": "explicit"},
                         "decided": {"how": "signature", "who": "t", "passes": 1,
                                     "agreed": 1},
                         "subjects": [_subject(GIT_BLOB)], "run": {"id": "r"}})
    assert out["id"].startswith("check_invariants@")


@pytest.mark.parametrize("bad,why", [
    ("A" * 40, "uppercase"),
    ("g" * 40, "non-hex"),
    (" " + "a" * 39, "whitespace"),
    (12345, "not a string"),
])
def test_malformed_blob_ids_are_refused(ledger, bad, why):
    with pytest.raises(ValidationFailure):
        ledger.append({"schema": "zp.record.v1", "step": "check_invariants", "verdict": "PASS",
                       "tier": "M", "basis": {"kind": "tree", "value": "a" * 40,
                                              "resolved_from": "explicit"},
                       "decided": {"how": "signature", "who": "t", "passes": 1,
                                   "agreed": 1},
                       "subjects": [{"path": "x.lean", "git_blob_id": bad}], "run": {"id": "r"}})


def test_an_unresolvable_repo_fails_CLOSED_not_open(ledger, monkeypatch):
    """⭐ REVERSES AN EARLIER CHOICE OF MINE, and the reversal is the point.

    The first build SKIPPED this check when no repo could be resolved, reasoning that
    the length could not be known so it should not be guessed. That is the fail-open
    shape this whole server exists to end: the one environment where the format is
    unknown is exactly the environment where a wrong value goes unnoticed. 40 is
    git's default object format, and a sha256 repo overrides it when it can be read.
    """
    monkeypatch.setattr(validate_mod, "_OBJECT_FORMAT", 0)
    with pytest.raises(ValidationFailure):
        ledger.append({"schema": "zp.record.v1", "step": "check_invariants",
                       "verdict": "PASS", "tier": "M",
                       "basis": {"kind": "tree", "value": "a" * 40,
                                 "resolved_from": "explicit"},
                       "decided": {"how": "signature", "who": "t", "passes": 1,
                                   "agreed": 1},
                       "subjects": [_subject(SHA256)], "run": {"id": "r"}})


def test_a_crlf_working_tree_still_yields_gits_stored_blob(tmp_path):
    """⭐⭐ 12-0-quater: "It names what git STORED, which is post-normalization
    content." A helper that hashes the bytes on disk agrees with git only where the
    checkout happens to be LF -- it passes on the machine it was written on and is
    silently wrong elsewhere, which is the worst shape a defect can take.

    Here the repo normalizes on add, so the stored object is LF while the working
    file is CRLF. blob_id() must report what GIT STORED.
    """
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / ".gitattributes").write_bytes(b"*.lean text eol=crlf\n")
    (tmp_path / "x.lean").write_bytes(b"line one\r\nline two\r\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)

    stored = subprocess.run(["git", "ls-files", "-s", "x.lean"], cwd=tmp_path,
                            capture_output=True, text=True).stdout.split()[1]
    naive = hashlib.sha1(b"blob %d\0" % len((tmp_path / "x.lean").read_bytes())
                         + (tmp_path / "x.lean").read_bytes()).hexdigest()

    assert blob_id("x.lean", repo=str(tmp_path)) == stored
    assert naive != stored, "the fixture must actually exercise normalization"


# -- ⭐ legacy records are NOT stale ------------------------------------------

def test_a_legacy_sha256_record_reads_LEGACY_IDENTITY_not_stale(ledger):
    """⭐ 12-0-quater: "recorded under a superseded identity scheme" and "the content
    moved" are DIFFERENT FACTS WITH DIFFERENT REMEDIES. Re-running a checker fixes
    STALE and does nothing here; this one has to be re-recorded.

    Rendering them the same is the FAIL/STALE conflation of this morning wearing a
    different hat — a reader sent to the wrong remedy, by a status that looked
    informative.
    """
    from core import inventory as inventory_mod
    legacy = [{"id": "check_invariants@old#0", "step": "check_invariants", "verdict": "PASS",
               "revision": 0,
               "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
               "subjects": [{"path": "x.lean", "sha256": "b" * 64}],
               "basis": {"kind": "tree", "value": "a" * 40}}]
    inv = inventory_mod.build(config=ledger.config, records=legacy, action="push",
                              files={"x.lean": "c" * 40}, ref="deadbeef",
                              admission=["check_invariants"])
    row = next(r for r in inv["rows"] if r["step"] == "check_invariants")
    assert row["status"] == "LEGACY_IDENTITY"
    assert row["status"] != "STALE"
    assert "superseded" in row["why"]


def test_a_legacy_record_still_blocks_the_gate(ledger):
    """⚠ Distinguishing it must not EXCUSE it. An unusable record is not a passing
    one, and `complete` has to stay false."""
    from core import inventory as inventory_mod
    legacy = [{"id": "check_invariants@old#0", "step": "check_invariants", "verdict": "PASS",
               "revision": 0,
               "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
               "subjects": [{"path": "x.lean", "sha256": "b" * 64}],
               "basis": {"kind": "tree", "value": "a" * 40}}]
    inv = inventory_mod.build(config=ledger.config, records=legacy, action="push",
                              files={"x.lean": "c" * 40}, ref="deadbeef",
                              admission=["check_invariants"])
    assert inv["complete"] is False
    assert inv["legacy_identity"] == 1


def test_the_legacy_remedy_says_re_record_not_re_run(ledger):
    from core import inventory as inventory_mod, render as render_mod
    legacy = [{"id": "check_invariants@old#0", "step": "check_invariants", "verdict": "PASS",
               "revision": 0,
               "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
               "subjects": [{"path": "x.lean", "sha256": "b" * 64}],
               "basis": {"kind": "tree", "value": "a" * 40}}]
    inv = inventory_mod.build(config=ledger.config, records=legacy, action="push",
                              files={"x.lean": "c" * 40}, ref="deadbeef",
                              admission=["check_invariants"])
    line = render_mod.render_inventory(inv)
    assert "LEGACY_IDENTITY" in line
    assert "re-record" in line
