"""`read(op='show')` must return bytes a caller can hash back to git's own blob id.

⛔⛔ IT COULD NOT, AND THAT IS A DATA-INTEGRITY BUG IN A CONTENT-ADDRESSED SYSTEM. Measured
2026-09-27 on a real file:

    git blob                       167,794 bytes    7dbd4741a92477c3
    what read(op='show') returned  167,793 bytes    370c225c633e580d

One byte — the trailing newline. `read` returned `GitResult.output`, whose own docstring is
*"stdout and stderr joined — hooks write their verdict to both"* and which calls `.strip()`. A
DISPLAY accessor on a CONTENT path, losing bytes three ways: whitespace stripped, stderr
concatenated into the content, and `text=True` translating CRLF to LF.

⚠⚠ THE CONSUMER LOST A TEST RUN TO IT AND APOLOGISED FOR A BUG THEY DID NOT HAVE. They substituted
an approved checker build into a worktree through this op, computed `370c225c`, and reported *"some
transcoding artifact in how I copied the bytes"* — on their side. Their hash matched the
measurement to the character. **They flagged it anyway, against their own interest in the argument
they were making, which is the only reason it was found.**

⭐ AND I NEARLY SHIPPED A FALSE CLAIM FIXING IT. The first patch stopped stripping and added
`byte_faithful: True` — while `text=True` was still translating newlines. A CRLF fixture proved it:
a 20-byte blob `cf9b2a85` came back as 18 bytes hashing `e5c5c558`. **The flag would have asserted
a property the code did not have**, which is the defect class this whole file belongs to. Caught by
testing the assertion rather than the original symptom.
"""

import hashlib
import subprocess

import pytest

from core import tiers


def _blob_id(data: bytes) -> str:
    """git's own object id for a blob — the only arbiter that matters here."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _commit_file(repo, name, content: bytes):
    (repo / name).write_bytes(content)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", name], cwd=repo, check=True, capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD:" + name], cwd=repo,
                          capture_output=True, text=True).stdout.strip()


# ⭐ THE FIXTURES ARE THE DELIVERABLE. An LF file exposed the original bug; only a CRLF file
# exposes the newline translation, and only a non-UTF-8 file exposes the decode. Each finds a
# different one of the three losses, and the first patch passed the first and failed the others.
CASES = {
    "lf": b"alpha\nbeta\ngamma\n",
    "crlf": b"line one\r\nline two\r\n",
    "no_trailing_newline": b"no newline at the end",
    "leading_whitespace": b"\n\n  indented start\nrest\n",
    "binary": b"\x00\xff\xfe payload\r\nsecond\x00\n",
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_content_read_reproduces_the_git_blob_exactly(robot, repo, name):
    """⭐⭐ THE HEADLINE, AND THE ARBITER IS GIT. Not "looks the same" — the same blob id."""
    want = _commit_file(repo, name + ".dat", CASES[name])
    out = robot.read(op="show", args=["HEAD:" + name + ".dat"])
    assert out["byte_faithful"] is True
    got = out["output"].encode("utf-8", "surrogateescape")
    assert _blob_id(got) == want, (
        f"{name}: read(op='show') returned {len(got)} bytes hashing {_blob_id(got)[:12]}, "
        f"git's blob is {len(CASES[name])} bytes hashing {want[:12]}")


def test_stderr_is_split_off_rather_than_joined_into_the_content(robot, repo):
    """⛔ THE WORST OF THE THREE LOSSES, because it CORRUPTS rather than truncates. `output` joins
    stderr, so anything git writes there lands inside what a caller reads as file content.

    ⚠ Asserted as a SEPARATE FIELD existing rather than by provoking stderr: a `show` that writes
    to stderr usually also fails, and the property under test is the shape of a successful read.
    Dropping stderr entirely would trade corruption for blindness — a half-failed show returning
    truncated content with nothing to say so.
    """
    _commit_file(repo, "plain.txt", b"content\n")
    out = robot.read(op="show", args=["HEAD:plain.txt"])
    assert "stderr" in out, "stderr has nowhere to go but into the content"
    assert out["output"] == "content\n"


def test_a_transcript_op_is_untouched(robot, repo):
    """⚠ THE BLAST RADIUS CONTROL. `output`'s stripping and joining are CORRECT for a gate
    transcript — every mutating receipt in `engine.py` uses that accessor — so the fix had to be
    per-op. A non-content read must be exactly as it was, and must NOT claim byte fidelity."""
    _commit_file(repo, "x.txt", b"x\n")
    out = robot.read(op="log", args=["-1", "--oneline"])
    assert out["ok"] is True
    assert "byte_faithful" not in out, (
        "a transcript op claims byte fidelity it does not have — its output is stripped and "
        "joined, which is right for a transcript and a false claim on this field")
    assert out["output"] == out["output"].strip(), "the transcript path stopped stripping"


def test_every_content_op_is_covered_by_the_flag():
    """⛔⛔ THE CLASS GUARD. `CONTENT_OPS` and the read allow-list live in one file so a newly
    allow-listed op that returns file content cannot quietly inherit the transcript path.

    ⚠ If someone adds `archive` or `cat-file --batch` to READ_OPS, this fails until they decide
    which side of the line it is on. That decision is the whole point: the bug was not a missing
    strip, it was nobody having drawn the line.
    """
    assert tiers.CONTENT_OPS <= set(tiers.READ_OPS), (
        "CONTENT_OPS names an op that is not even readable")
    assert tiers.CONTENT_OPS == {"show", "cat-file"}, (
        f"the content-op set changed to {sorted(tiers.CONTENT_OPS)}. Every op here returns raw "
        f"bytes and every op NOT here returns a stripped, stderr-joined transcript — confirm the "
        f"new member returns content before widening this.")
