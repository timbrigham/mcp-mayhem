"""preflight must feed the hook BYTE-FOR-BYTE the ref line git itself feeds it at push.

⭐ Asked by ZeroParadox 2026-09-30 and left by them as "not yet verified end to end". Their
advisory-leg skip (Tim's option (b)) matches a green PREFLIGHT receipt against the ref tuples the
hook reads from stdin at PUSH. Those two stdins come from different authors: preflight's is
`Gates.push_refs`, which gitRobot synthesises; push's is written by git. If they ever differ the
receipt never matches — safe, but the skip is then dead code that reads as live.

⚠ So the comparison is made against REAL git: a real `.git/hooks/pre-push` shim, a real bare
remote, a real `git push` through `robot.push`. A test comparing `push_refs` against a string
this file wrote would be the proxy defect this repo keeps finding.
"""

import json
import sys
from pathlib import Path


def _install_recording_pipeline(repo: Path, log: Path):
    """The consumer's shape: a thin `.git/hooks/pre-push` shim that execs tools/verify/hooks.py.

    The recorder writes OUTSIDE the repo so the tree stays clean for push's own checks."""
    entry = repo / "tools" / "verify" / "hooks.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_bytes((
        "import json, os, sys\n"
        "data = sys.stdin.read()\n"
        f"with open({str(log)!r}, 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps({'op': os.environ.get('GITROBOT_OP', '<absent>'),\n"
        "                        'phase': sys.argv[1], 'stdin': data}) + '\\n')\n"
        "sys.exit(0)\n").encode())
    shim = repo / ".git" / "hooks" / "pre-push"
    py = Path(sys.executable).as_posix()
    shim.write_bytes(f'#!/bin/sh\nexec "{py}" tools/verify/hooks.py pre-push\n'.encode())
    shim.chmod(0o755)


def _commit(robot, repo, tmp_path, name):
    (repo / name).write_bytes(name.encode())
    robot.stage(["tools", name])
    msg = tmp_path / "m.txt"
    msg.write_bytes(b"m\n")
    robot.commit(str(msg))


def test_preflight_and_push_feed_the_hook_identical_stdin(robot, repo, tmp_path, ledger_ok):
    log = tmp_path / "hook_stdin.jsonl"
    _install_recording_pipeline(repo, log)
    _commit(robot, repo, tmp_path, "c.txt")

    assert robot.preflight(wait=True)["passed"] is True
    robot.push("illustrated", reason="compare preflight stdin with git's", wait=True)

    # commit's pre-commit run lands in the same log, launched without provenance; keep pre-push
    rows = [r for r in map(json.loads, log.read_text(encoding="utf-8").splitlines())
            if r["phase"] == "pre-push"]
    by_op = {r["op"]: r["stdin"] for r in rows}
    # ⚠ A FLOOR, so a hook that never fired cannot pass by comparing nothing with nothing.
    assert set(by_op) == {"preflight", "push"}, f"hook runs seen: {[r['op'] for r in rows]}"
    assert by_op["preflight"].strip(), "preflight fed the hook an EMPTY scope"
    assert by_op["preflight"] == by_op["push"], (
        f"preflight fed {by_op['preflight']!r}, git fed {by_op['push']!r} — the consumer's "
        f"green receipt can never match")


def test_a_stale_tracking_ref_makes_them_differ_and_that_is_the_safe_direction(
        robot, repo, tmp_path, ledger_ok):
    """⚠ THE KNOWN DIVERGENCE, PINNED SO NOBODY DISCOVERS IT AS A SURPRISE. preflight reads the
    remote sha from the LOCAL tracking ref `origin/<branch>`; git reads it from the remote's own
    advertisement. When someone else has pushed and nobody has fetched, they differ — and the
    consumer's receipt then does not match, so every leg runs. Fail toward running."""
    import subprocess
    log = tmp_path / "hook_stdin.jsonl"
    _install_recording_pipeline(repo, log)
    _commit(robot, repo, tmp_path, "d.txt")

    # move the remote behind gitRobot's back, from a second clone, without fetching here
    other = tmp_path / "other"
    remote = robot.git.run(["remote", "get-url", "origin"]).stdout.strip()
    subprocess.run(["git", "clone", "-q", "-b", "illustrated", remote, str(other)], check=True, capture_output=True)
    for args in (["config", "user.email", "o@o"], ["config", "user.name", "o"],
                 ["commit", "-q", "--allow-empty", "-m", "elsewhere"],
                 ["push", "-q", "origin", "illustrated"]):
        subprocess.run(["git", *args], cwd=str(other), check=True, capture_output=True)

    robot.preflight(wait=True)
    robot.push("illustrated", reason="remote moved; push is rejected non-fast-forward", wait=True)

    rows = [r for r in map(json.loads, log.read_text(encoding="utf-8").splitlines())
            if r["phase"] == "pre-push"]
    by_op = {r["op"]: r["stdin"] for r in rows}
    # ⚠ UNCONDITIONAL. git runs pre-push AFTER reading the remote's advertisement and BEFORE the
    # non-fast-forward rejection, so the hook does fire here — measured, not assumed. An `if`
    # around this would let a hook that never ran pass the test.
    assert set(by_op) == {"preflight", "push"}, f"hook runs seen: {sorted(by_op)}"
    assert by_op["preflight"] != by_op["push"]
    # and the difference is EXACTLY the remote sha — the field preflight reads from a tracking ref
    pre, at_push = by_op["preflight"].split(), by_op["push"].split()
    assert pre[:3] == at_push[:3] and pre[3] != at_push[3], (pre, at_push)
