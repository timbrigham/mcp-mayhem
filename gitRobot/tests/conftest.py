"""A real, disposable git repository per test.

Everything here runs against a throwaway tree — never the configured repository.
A test suite for a guard that could damage the thing it guards would be its own
worst defect.
"""

import subprocess
from pathlib import Path

import pytest

from core.engine import GitRobot


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    """An initialised repo with one commit, a remote, and a tracked file."""
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "illustrated")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "user.name", "test")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "tracked.txt").write_text("original\n", encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-q", "-m", "initial")

    bare = tmp_path / "remote.git"
    _git(path, "init", "-q", "--bare", str(bare))
    _git(path, "remote", "add", "origin", str(bare))
    _git(path, "push", "-q", "-u", "origin", "illustrated")
    return path


@pytest.fixture
def robot(repo, tmp_path) -> GitRobot:
    return GitRobot(repo, data_path=tmp_path / "git_ops.jsonl", actor="test",
                    scratch=tmp_path / "scratch")


@pytest.fixture
def dirty(repo):
    """Uncommitted work of both kinds — the thing Tier 1 exists to protect."""
    (repo / "tracked.txt").write_text("PRECIOUS EDIT\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("PRECIOUS NEW FILE\n", encoding="utf-8")
    return repo


@pytest.fixture
def fake_gate(repo):
    """Install a stand-in for the project's gate pipeline at the path gitRobot expects.

    Returns a setter: ``fake_gate(0)`` makes it pass, ``fake_gate(1)`` fail. The
    real pipeline is the consumer project's; what is under test here is that
    gitRobot invokes it, honours its exit code, and records the verdict.
    """
    entry = repo / "tools" / "verify" / "hooks.py"
    entry.parent.mkdir(parents=True, exist_ok=True)

    def _set(exit_code: int, message: str = "gate ran"):
        entry.write_text(
            "import sys\n"
            f"print({message!r} + ' phase=' + (sys.argv[1] if len(sys.argv) > 1 else '?'))\n"
            f"sys.exit({exit_code})\n",
            encoding="utf-8")
        return entry

    _set(0)
    return _set


@pytest.fixture
def ledger_ok(monkeypatch):
    """A ledger that says the admission set is satisfied.

    ⚠ Tests must never depend on a live server. The point of the fixture is that
    the REFUSAL paths get their own explicit tests below, rather than being
    whatever a real ledger happened to answer that day.
    """
    from core import ledger as ledger_client

    def fake(ref, action, admission=None):
        return {"ok": True, "complete": True, "ref": ref, "action": action,
                "admitted": [], "admission_state": "EMPTY", "policy_sha": "policy-sha",
                "required": 0, "satisfied": 0, "registered_not_admitting": [],
                "line": f"ALLOWED  {action}  0/0 admission keys  @ {ref[:12]}"}

    monkeypatch.setattr(ledger_client, "inventory", fake)
    return fake


@pytest.fixture
def ledger_refuses(monkeypatch):
    """A ledger reporting an incomplete admission set — the 2026-08-23 event."""
    from core import ledger as ledger_client

    def fake(ref, action, admission=None):
        return {"ok": True, "complete": False, "ref": ref, "action": action,
                "admitted": ["build", "check_prose"], "admission_state": "SET",
                "policy_sha": "policy-sha", "required": 2, "satisfied": 0,
                "missing": 2, "stale": 0, "undecided": 0, "failed": 0,
                "registered_not_admitting": ["check_pov"],
                "rows": [{"step": "build", "family": "mechanical",
                          "status": "MISSING", "gating": True}],
                "line": ("REFUSED  push  0/2 admission keys\n"
                         "  MISSING  mechanical  build, check_prose")}

    monkeypatch.setattr(ledger_client, "inventory", fake)
    return fake


@pytest.fixture
def ledger_down(monkeypatch):
    from core import ledger as ledger_client

    def boom(ref, action, admission=None):
        raise ledger_client.LedgerUnreachable("verdictLedger is not answering")

    monkeypatch.setattr(ledger_client, "inventory", boom)
    return boom


def _init(path):
    for args in (["init", "-q", "-b", "master"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["config", "commit.gpgsign", "false"]):
        subprocess.run(["git", *args], cwd=str(path), check=True, capture_output=True)


@pytest.fixture
def nested_local(repo, tmp_path):
    """`.claude-local` inside the main checkout, with its own remote — the real shape."""
    local = repo / ".claude-local"
    local.mkdir()
    _init(local)
    (local / "notes.md").write_text("private notes\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(local), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=str(local),
                   check=True, capture_output=True)

    bare = tmp_path / "ZeroParadoxLocal.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True,
                   capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=str(local),
                   check=True, capture_output=True)

    # prod ignores it, exactly as the real repo does
    (repo / ".gitignore").write_text(".claude-local/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=str(repo), check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "ignore local"], cwd=str(repo),
                   check=True, capture_output=True)
    return local


