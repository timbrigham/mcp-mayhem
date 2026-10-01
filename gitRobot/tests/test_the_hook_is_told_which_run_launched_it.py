"""The consumer hook is told WHICH gitRobot run launched it — provenance, never a match key.

Added 2026-09-30 for ZeroParadox's `tooling-prepush-pipeline-rerun-necessity` (Tim's option (b)):
their hook may skip ADVISORY legs when a passing preflight exists for the IDENTICAL push_refs,
and must print which run it matched. The skip and the match live in THEIR hook, keyed on git's
own stdin refs; gitRobot supplies only the run id so the printout can name it.

⚠ The first test asserts the VALUE, not presence: a hook that saw `GITROBOT_RUN_ID` set to
anything would pass a presence check while naming the wrong run, which is the whole defect this
codebase exists to remove.
"""

import os

from core import gates as gates_mod


def _hook_recording_env(repo):
    entry = repo / "tools" / "verify" / "hooks.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_bytes(
        b"import os, sys, pathlib\n"
        b"sys.stdin.read()\n"
        b"pathlib.Path('env_seen.txt').write_text(\n"
        b"    os.environ.get('GITROBOT_OP', '<absent>') + ' ' +\n"
        b"    os.environ.get('GITROBOT_RUN_ID', '<absent>') + ' ' +\n"
        b"    os.environ.get('ZZ_SERVER_ENV_PROBE', '<absent>'), encoding='utf-8')\n"
        b"sys.exit(0)\n")
    return repo / "env_seen.txt"


def test_preflight_hands_the_hook_its_own_run_id(robot, repo, monkeypatch):
    monkeypatch.setenv("ZZ_SERVER_ENV_PROBE", "inherited")
    seen = _hook_recording_env(repo)
    out = robot.preflight(wait=True)
    assert out["passed"] is True
    op, run_id, probe = seen.read_text(encoding="utf-8").split()
    assert probe == "inherited", "provenance must be ADDED to the environment, not replace it"
    assert op == "preflight"
    assert run_id == out["run_id"], "the hook must be told THIS run, not merely a run"


def test_no_env_extra_inherits_the_server_environment_unchanged(robot, repo, monkeypatch):
    """⚠ ADDITIVE, NEVER A REPLACEMENT. A gate run that passes nothing must see exactly the
    server's environment — `env={}` would strip PATH and every git variable.

    ⚠ THE SENTINEL IS THE CONTROL. Asserting only that the two GITROBOT_ variables are absent
    SURVIVED the `env={}` mutation on 2026-09-30 — an emptied environment lacks them too. A
    variable the server HAS and the hook must still SEE is what separates the two."""
    monkeypatch.delenv("GITROBOT_OP", raising=False)
    monkeypatch.delenv("GITROBOT_RUN_ID", raising=False)
    monkeypatch.setenv("ZZ_SERVER_ENV_PROBE", "inherited")
    seen = _hook_recording_env(repo)
    res = robot.gates.run("pre-push", stdin="")
    assert res.passed
    assert seen.read_text(encoding="utf-8") == "<absent> <absent> inherited"


def test_git_run_env_extra_reaches_the_git_subprocess(robot):
    """The push leg goes through `Git.run`, where git — not gitRobot — launches the hook. Prove
    the variables reach the git process itself, using a variable git reports back."""
    res = robot.git.run(["var", "GIT_COMMITTER_IDENT"],
                        env_extra={"GIT_COMMITTER_NAME": "provenance-probe"})
    assert res.ok and res.stdout.startswith("provenance-probe "), res.stdout
    plain = robot.git.run(["var", "GIT_COMMITTER_IDENT"])
    assert not plain.stdout.startswith("provenance-probe "), "env_extra leaked into a later call"


def test_push_hands_git_its_own_run_id(robot, repo, tmp_path, fake_gate, monkeypatch):
    """⚠ The push leg had NO test until a mutation removing it SURVIVED (2026-09-30). git, not
    gitRobot, launches the hook here, so what is asserted is what reached `git push`."""
    from core import ledger as ledger_client
    fake_gate(0)
    (repo / "p.txt").write_bytes(b"p")
    robot.stage(["p.txt"])
    msg = tmp_path / "m.txt"
    msg.write_bytes(b"m\n")
    robot.commit(str(msg))
    monkeypatch.setattr(ledger_client, "can_push", lambda *a, **k: {
        "ok": True, "allowed": True, "range": "origin/illustrated..illustrated",
        "commits_in_range": 1, "blocking_count": 0, "tip": robot.git.head(),
        "admitted": ["build"], "admission_state": "SET", "not_gating": [],
        "config_sha": "p", "commits": [], "line": "ALLOWED"})
    real, seen = robot.git.run, []

    def spy(args, **kw):
        if args and args[0] == "push":
            seen.append(kw.get("env_extra"))
        return real(args, **kw)

    monkeypatch.setattr(robot.git, "run", spy)
    out = robot.push("illustrated", reason="provenance reaches git push", wait=True)
    assert len(seen) == 1, f"expected exactly one `git push`, saw {len(seen)}"
    assert seen[0] == {"GITROBOT_OP": "push", "GITROBOT_RUN_ID": out["run_id"]}


def test_the_helper_names_both_variables_and_leaves_os_environ_alone(monkeypatch):
    monkeypatch.delenv("GITROBOT_RUN_ID", raising=False)
    assert gates_mod.hook_provenance_env("push", "abc") == {
        "GITROBOT_OP": "push", "GITROBOT_RUN_ID": "abc"}
    assert "GITROBOT_RUN_ID" not in os.environ
