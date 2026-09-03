"""A worktree is the project root; the instance acting inside it IS the arc.

⭐⭐ TIM'S DESIGN, 2026-09-02: *"a git tree and then change directory into the child folder and
treat that like the project root. the instance that acts inside of that child directory is the arc.
simple and clean."*

That makes the review-round counter per-arc BY CONSTRUCTION rather than by convention: it lives at
the arc's own root and dies with the worktree, which is right, because the arc is over. It also
dissolves a defect found on the way — `gate_round.py`'s caps read a SCALAR `round`, so three rounds
of code work plus two on the corpus tripped the BEDROCK cap at 5 when neither line of work had done
five. Separate arcs, separate roots, separate counters.

⚠⚠ THE FILE IS TRACKED AND COMMITTED AT `round: 0`, so a fresh worktree OPENS with the known-good
state — Tim: *"literally just be opening what's supposed to be there by default."* That removes a
guess: a gitignored file is ABSENT in a fresh worktree, and `gate_round.py` has to treat missing as
`{'round': 0, 'fresh': True}` and announce it, "because deleting the file is otherwise an unlogged
`reset`". **Nine bypass routes have been found and closed on that one counter.** A tracked default
is not one more guard on it; it removes the question.

⭐ AND `--skip-worktree` MAKES THE MISTAKE UNAVAILABLE RATHER THAN MERELY UNLIKELY. Git treats local
modifications to such a file as nonexistent, so `git add` on it is a no-op and a bumped round cannot
be staged even deliberately. Tim: *"the only way that you're ever going to have a commit done is
inside of this dedicated MCP server right? the main agent is never even going to be able to touch
this stuff."* Correct — and this is the mechanism that makes it true of the FILE and not only of the
path to it.
"""

import json
import subprocess
from pathlib import Path

import pytest

from core.errors import RefusalError


ARC = "gate_round.json"


def _msg(tmp_path, text="m\n"):
    """A commit message travels as a FILE, never an argument — prose contains newlines,
    quotes and non-ASCII, and every one is a quoting hazard on the way to a subprocess."""
    p = tmp_path / "msg.txt"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _write_arc(repo: Path, round_value):
    (repo / ARC).write_text(json.dumps({"round": round_value, "arc_base": "a" * 40}) + "\n",
                            encoding="utf-8")


def _track_arc(repo: Path, round_value=0):
    """Commit the handshake at its default, the way the real tree will carry it."""
    _write_arc(repo, round_value)
    subprocess.run(["git", "add", ARC], cwd=repo, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-qm", "arc handshake default"], cwd=repo,
                   capture_output=True, text=True)


def _skip_flag(repo: Path, path=ARC) -> bool:
    """True when the index carries the skip-worktree bit (`S` in ls-files -v)."""
    out = subprocess.run(["git", "ls-files", "-v", path], cwd=repo,
                         capture_output=True, text=True).stdout
    return bool(out) and out[0] == "S"


# -- ⭐⭐ the arc opens sealed -------------------------------------------------

def test_worktree_add_seals_the_arc_handshake(robot, repo):
    """⭐⭐ CREATING THE WORKTREE IS ENTERING THE ARC, so the handshake is sealed at that moment.
    One place, and the only place that makes worktrees — which matters because the index flag is
    PER WORKTREE (each has its own index), so it cannot be set once centrally."""
    _track_arc(repo)

    out = robot.worktree("add", ref="HEAD")
    wt = Path(out["path"])

    assert out["arc_state"]["sealed"] is True, f"handshake not sealed: {out['arc_state']}"
    assert _skip_flag(wt), "skip-worktree is not set in the new worktree's index"


def test_a_bumped_round_cannot_be_staged_in_a_sealed_worktree(robot, repo):
    """⭐⭐ THE PROPERTY THE WHOLE DESIGN RESTS ON. With the bit set, git treats local edits as
    nonexistent — so the arc bumps its counter freely and `git add` simply does nothing. The
    mistake is not caught, it is unavailable."""
    _track_arc(repo)
    wt = Path(robot.worktree("add", ref="HEAD")["path"])

    _write_arc(wt, 5)                                   # the arc does its rounds
    add = subprocess.run(["git", "add", ARC], cwd=wt, capture_output=True, text=True)

    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=wt,
                            capture_output=True, text=True).stdout
    assert ARC not in staged, "a bumped round reached the index — skip-worktree is not holding"

    # ⭐⭐ AND IT IS REFUSED LOUDLY, NOT SILENTLY SKIPPED — measured by ZeroParadox on the real
    # tree and stronger than this test originally assumed. git says:
    #     "The following paths ... matched paths that exist outside of your sparse-checkout
    #      definition, so will not be updated in the index: gate_round.json"
    # ⚠ A silent no-op and an explicit refusal are the same OUTCOME and very different
    # EVIDENCE, and only the second tells a caller why. Asserting outcome alone would let git
    # regress to silence without this suite noticing.
    assert add.returncode != 0, (
        "the stage was silently skipped rather than refused — same outcome, no evidence")
    assert ARC in (add.stdout + add.stderr), "the refusal does not name the file it refused"


def test_sealing_is_inert_when_the_file_is_not_tracked(robot, repo):
    """⚠ THE STATE TODAY, AND IT MUST NOT BE A FAILURE. `gate_round.json` still lives under
    `.claude-local/` and has not been migrated, so nothing is tracked at the root yet. Sealing
    must be silent and inert now, and start working the moment the file lands — a provisioning
    step that errors on a repo without the file is one that blocks every worktree."""
    out = robot.worktree("add", ref="HEAD")

    assert out["arc_state"]["sealed"] is False
    assert "not tracked" in out["arc_state"]["reason"]
    assert out["decision"] == "allowed", "an unmigrated repo must still get its worktree"


# -- ⛔⛔ the backstop: what the index flag cannot cover ------------------------

def test_a_commit_carrying_a_non_zero_round_is_refused(robot, repo, tmp_path):
    """⛔⛔ THE CASE `--skip-worktree` CANNOT REACH: the MAIN checkout, where nothing "creates"
    the arc and so nothing seals it. Also a worktree gitRobot did not make, or one whose index
    flag was lost.

    ⚠ WHY A SECOND CONTROL IS WORTH IT: one committed non-zero round is inherited by EVERY future
    arc, permanently, and it arrives from the TREE rather than from a stale local file — so
    `gate_round.py`'s "base recorded X, HEAD is now Y" warning never fires and the over-count it
    exists to catch becomes invisible."""
    _track_arc(repo)
    _write_arc(repo, 7)
    subprocess.run(["git", "add", "-f", ARC], cwd=repo, capture_output=True, text=True)

    with pytest.raises(RefusalError) as exc:
        robot.commit(_msg(tmp_path, "bumping the arc into history\n"), run_gate=False)
    msg = str(exc.value)
    assert "round=7" in msg
    assert "must stay at 0" in msg
    assert ARC in msg


def test_an_unreadable_round_is_refused_not_ignored(robot, repo, tmp_path):
    """⚠⚠ UNPARSEABLE IS NOT "NO ROUND". An unknown count next to a cap must fail closed — the
    same rule `gate_round.py` applies, arriving through the commit path. Measured there
    2026-08-10: one corrupted byte took the counter from "past the bedrock cap, refuse" to
    "round 1, proceed" with nothing said."""
    _track_arc(repo)
    (repo / ARC).write_text("{ not json at all", encoding="utf-8")
    subprocess.run(["git", "add", "-f", ARC], cwd=repo, capture_output=True, text=True)

    with pytest.raises(RefusalError) as exc:
        robot.commit(_msg(tmp_path, "committing a corrupt counter\n"), run_gate=False)
    assert "unreadable" in str(exc.value).lower()


def test_the_tracked_default_at_zero_commits_normally(robot, repo, tmp_path):
    """⚠ THE CONTROL, AND IT IS WHAT KEEPS THE GUARD FROM BEING AN OUTAGE. The handshake is
    SUPPOSED to be committed once, at its default. A guard that refused that would make the file
    unlandable and the whole design unreachable."""
    _write_arc(repo, 0)
    subprocess.run(["git", "add", ARC], cwd=repo, capture_output=True, text=True)

    out = robot.commit(_msg(tmp_path, "land the arc handshake default\n"), run_gate=False)
    assert out["decision"] == "allowed"


def test_an_unrelated_commit_is_unaffected(robot, repo, tmp_path):
    """⚠ THE GUARD READS THE INDEX, so it must be silent when the handshake is not part of this
    commit at all — including when a bumped copy sits in the WORKING TREE. That difference is
    exactly the local bump the design intends to allow."""
    _track_arc(repo)
    _write_arc(repo, 9)                                  # dirty in the tree, NOT staged
    (repo / "other.txt").write_text("unrelated work", encoding="utf-8")
    subprocess.run(["git", "add", "other.txt"], cwd=repo, capture_output=True, text=True)

    out = robot.commit(_msg(tmp_path, "unrelated work proceeds\n"), run_gate=False)
    assert out["decision"] == "allowed", "a local round bump blocked an unrelated commit"


def test_read_can_inspect_a_worktree(robot, repo):
    """⚠⚠ THE GAP THAT BLOCKED VERIFICATION FROM THE OTHER SIDE. `stage`, `unstage` and `commit`
    all took a worktree target; `read` did not. So an agent could WRITE to a worktree through
    gitRobot and had no sanctioned way to LOOK at it.

    ZeroParadox hit it verifying this very feature: *"`git ls-files -v` is denied to me and
    `read` has no worktree parameter, so I cannot see the `S` flag directly. I did not work
    around it."* Refusing to work around it was right; the gap was mine.

    ⭐ A MEDIATED SURFACE THAT CAN WRITE WHERE IT CANNOT READ PUSHES CALLERS TOWARD RAW GIT —
    the one outcome the design exists to prevent. This is the step-2 check, now reachable."""
    _track_arc(repo)
    wt = Path(robot.worktree("add", ref="HEAD")["path"])

    out = robot.read("ls-files", ["-v", ARC], worktree=str(wt))

    assert out["ok"], f"read against the worktree failed: {out}"
    assert out["output"].startswith("S"), (
        f"skip-worktree flag not visible via read: {out['output']!r}")


def test_read_refuses_an_unregistered_worktree(robot, repo, tmp_path):
    """⚠ A READ AIMED ANYWHERE IS A READ ABOUT A TREE gitRobot DOES NOT GUARD — the same reason
    `forbidden_token` refuses `--git-dir`. The target is validated against the registered set,
    exactly as the write paths are."""
    stranger = tmp_path / "not-a-worktree"
    stranger.mkdir()
    with pytest.raises(RefusalError):
        robot.read("status", [], worktree=str(stranger))
