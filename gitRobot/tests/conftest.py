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


@pytest.fixture(autouse=True)
def _never_a_live_ledger(monkeypatch):
    """⚠ NO TEST MAY REACH THE RUNNING LEDGER ON :8011.

    `status()` consults `inventory` and `push` consults `can_push`, so BOTH are
    stubbed. Patching only one would let the other reach the real server and make the
    suite pass or fail on the state of the actual ZeroParadox repo. The default is
    UNREACHABLE — the fail-closed answer; tests needing a verdict opt in below, and
    their monkeypatch lands after this one and wins.
    """
    from core import ledger as ledger_client

    def refuse(*a, **k):
        raise ledger_client.LedgerUnreachable(
            "no ledger in tests — opt in with the ledger_ok fixture")

    monkeypatch.setattr(ledger_client, "inventory", refuse)
    monkeypatch.setattr(ledger_client, "can_push", refuse)


def _range_answer(rev_range, *, allowed, commits=1, blocking=0, admission_state="SET",
                  admitted=("build",), line="", **extra):
    """The can_push payload shape, in one place so a change to it breaks once."""
    return {"ok": True, "allowed": allowed, "range": rev_range,
            "commits_in_range": commits, "blocking_count": blocking,
            "tip": extra.pop("tip", "deadbeef"), "admitted": list(admitted),
            "admission_state": admission_state, "not_gating": [],
            "config_sha": "policy-sha", "commits": [], "missing": [], "stale": [],
            "failed": [], "legacy": [], "line": line, **extra}


@pytest.fixture
def ledger_ok(monkeypatch, repo):
    """A ledger that says every commit in the range is green."""
    from core import ledger as ledger_client

    def fake_can_push(rev_range, admission=None, action="push"):
        # ⚠ admission_state SET, not EMPTY — an empty set REFUSES, so a fixture
        # standing for "the ledger is happy" must name a real requirement or every
        # allow-path test would silently exercise the fail-closed branch instead.
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                              capture_output=True, text=True).stdout.strip()
        return _range_answer(rev_range, allowed=True, tip=head,
                             line=f"ALLOWED  push  0/1 commit(s) short  @ {rev_range}")

    def fake_inventory(ref, action, admission=None):
        return {"ok": True, "complete": True, "ref": ref, "action": action,
                "admitted": ["build"], "admission_state": "SET",
                "config_sha": "policy-sha", "required": 1, "satisfied": 1,
                "registered_not_admitting": [], "line": "ALLOWED"}

    monkeypatch.setattr(ledger_client, "can_push", fake_can_push)
    monkeypatch.setattr(ledger_client, "inventory", fake_inventory)
    return fake_can_push


@pytest.fixture
def ledger_refuses(monkeypatch):
    """A ledger reporting the range short — the 2026-08-23 event."""
    from core import ledger as ledger_client

    def fake_can_push(rev_range, admission=None, action="push"):
        return _range_answer(
            rev_range, allowed=False, commits=2, blocking=2,
            missing=["build", "check_prose"],
            line=("REFUSED  push  2/2 commit(s) short\n"
                  "  MISSING  build, check_prose"))

    def fake_inventory(ref, action, admission=None):
        return {"ok": True, "complete": False, "ref": ref, "action": action,
                "admitted": ["build", "check_prose"], "admission_state": "SET",
                "config_sha": "policy-sha", "required": 2, "satisfied": 0,
                "registered_not_admitting": ["check_pov"],
                "line": "REFUSED  push  0/2 admission keys"}

    monkeypatch.setattr(ledger_client, "can_push", fake_can_push)
    monkeypatch.setattr(ledger_client, "inventory", fake_inventory)
    return fake_can_push


@pytest.fixture
def ledger_empty(monkeypatch):
    """The ledger answering fine, with NOTHING promoted to gate the action.

    ⭐ The state the whole system shipped in on 2026-08-23; it must refuse.
    """
    from core import ledger as ledger_client

    def fake_can_push(rev_range, admission=None, action="push"):
        return _range_answer(rev_range, allowed=True, admission_state="EMPTY",
                             admitted=(), not_gating=["build", "check_prose",
                                                      "check_pov"],
                             line=f"push  0 keys  @ {rev_range}")

    def fake_inventory(ref, action, admission=None):
        return {"ok": True, "complete": True, "ref": ref, "action": action,
                "admitted": [], "admission_state": "EMPTY", "config_sha": "policy-sha",
                "required": 0, "satisfied": 0,
                "registered_not_admitting": ["build", "check_prose", "check_pov"],
                "line": f"{action}  0/0 admission keys"}

    monkeypatch.setattr(ledger_client, "can_push", fake_can_push)
    monkeypatch.setattr(ledger_client, "inventory", fake_inventory)
    return fake_can_push


@pytest.fixture
def ledger_down(monkeypatch):
    from core import ledger as ledger_client

    def boom(*a, **k):
        raise ledger_client.LedgerUnreachable("verdictLedger is not answering")

    monkeypatch.setattr(ledger_client, "can_push", boom)
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


