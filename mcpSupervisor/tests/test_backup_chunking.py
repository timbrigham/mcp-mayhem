"""Split-McpLargeStream / Join-McpStreamParts: the backup survives GitHub's 100 MB file limit.

⛔ Measured 2026-09-15: verdictLedger/records.jsonl crossed 104,857,600 bytes between two backup
ticks, and every push after it was refused. Tim chose to back the stream up as parts: the live file
is untouched, full parts never change again, and a restore rebuilds the file and checks its hash.

These run the real module through Windows PowerShell 5.1, the host the supervisor runs under.
Thresholds are shrunk to kilobytes so the behaviour is exercised without 100 MB fixtures.
"""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "McpSupervisor.psm1"
pytestmark = pytest.mark.skipif(shutil.which("powershell") is None,
                                reason="Windows PowerShell is required")


def _ps(script: str) -> str:
    full = f"$ErrorActionPreference='Stop'; Import-Module '{MODULE}' -Force; {script}"
    proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", full],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr[-1500:]
    return proc.stdout


def _record(i: int, size: int = 300) -> bytes:
    return (json.dumps({"id": f"r{i}", "pad": "x" * size}) + "\n").encode()


def _split(repo: Path, threshold=2000, part=1000) -> None:
    _ps(f"$null = Split-McpLargeStream -RepoPath '{repo}' -ThresholdBytes {threshold} -PartBytes {part}")


def _repo(tmp_path: Path, n: int) -> Path:
    repo = tmp_path / "local"
    (repo / "verdictLedger").mkdir(parents=True)
    (repo / "verdictLedger" / "records.jsonl").write_bytes(b"".join(_record(i) for i in range(n)))
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def test_parts_rebuild_the_stream_byte_for_byte(tmp_path):
    """⭐ THE RESTORE. Parts concatenated in order equal the live file exactly, every part is under
    its budget, and each part is whole lines."""
    repo = _repo(tmp_path, 20)
    src = (repo / "verdictLedger" / "records.jsonl").read_bytes()
    _split(repo)

    parts = repo / "verdictLedger" / "records.jsonl.parts"
    manifest = json.loads((parts / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sha256"] == hashlib.sha256(src).hexdigest()
    assert len(manifest["parts"]) > 1
    for p in manifest["parts"]:
        data = (parts / p["name"]).read_bytes()
        assert len(data) <= 1000 and data.endswith(b"\n")

    out = tmp_path / "restored.jsonl"
    _ps(f"$null = Join-McpStreamParts -PartsDir '{parts}' -Destination '{out}'")
    assert out.read_bytes() == src


def test_full_parts_do_not_change_when_the_stream_grows(tmp_path):
    """⭐ WHY PARTS BEAT LFS. After an append only the LAST part may change, so git stores each full
    part once."""
    repo = _repo(tmp_path, 20)
    _split(repo)
    parts = repo / "verdictLedger" / "records.jsonl.parts"
    before = json.loads((parts / "manifest.json").read_text(encoding="utf-8"))["parts"]

    with open(repo / "verdictLedger" / "records.jsonl", "ab") as fh:
        fh.write(b"".join(_record(i) for i in range(20, 25)))
    _split(repo)
    after = json.loads((parts / "manifest.json").read_text(encoding="utf-8"))["parts"]

    assert after[:len(before) - 1] == before[:-1], "a full part changed after an append"


def test_a_torn_tail_is_left_for_the_next_tick(tmp_path):
    """⚠ Only complete lines are taken: a record still being written must not reach a part."""
    repo = _repo(tmp_path, 20)
    stream = repo / "verdictLedger" / "records.jsonl"
    whole = stream.read_bytes()
    with open(stream, "ab") as fh:
        fh.write(b'{"id": "torn", "pad": "xx')
    _split(repo)
    manifest = json.loads((repo / "verdictLedger" / "records.jsonl.parts" / "manifest.json")
                          .read_text(encoding="utf-8"))
    assert manifest["bytes"] == len(whole)
    assert manifest["sha256"] == hashlib.sha256(whole).hexdigest()


def test_the_original_is_ignored_and_untracked(tmp_path):
    """The whole file must never be committed again, even if it was tracked before the split."""
    repo = _repo(tmp_path, 20)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    _split(repo)
    _split(repo)                                     # idempotent: one ignore line, not two
    ignore = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ignore.count("/verdictLedger/records.jsonl") == 1
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True,
                             text=True, check=True).stdout.splitlines()
    assert "verdictLedger/records.jsonl" not in tracked
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True,
                             text=True, check=True).stdout.splitlines()
    assert "verdictLedger/records.jsonl" not in tracked
    assert any(t.startswith("verdictLedger/records.jsonl.parts/part-") for t in tracked)


def test_a_small_stream_is_left_alone(tmp_path):
    repo = _repo(tmp_path, 2)
    _split(repo, threshold=10_000_000)
    assert not (repo / "verdictLedger" / "records.jsonl.parts").exists()
    assert not (repo / ".gitignore").exists()


def test_a_tampered_part_fails_the_restore(tmp_path):
    """⛔ A restore that is not checked is not a restore: a changed part must throw, not rebuild."""
    repo = _repo(tmp_path, 20)
    _split(repo)
    parts = repo / "verdictLedger" / "records.jsonl.parts"
    first = parts / "part-0001.jsonl"
    data = bytearray(first.read_bytes())
    data[5] = ord("Z")
    first.write_bytes(bytes(data))
    full = (f"$ErrorActionPreference='Stop'; Import-Module '{MODULE}' -Force; "
            f"Join-McpStreamParts -PartsDir '{parts}' -Destination '{tmp_path / 'r.jsonl'}'")
    proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", full],
                          capture_output=True, text=True)
    assert proc.returncode != 0 and "manifest says" in proc.stderr
