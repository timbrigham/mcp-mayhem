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


# -- ⛔ the arc's own bookkeeping must not block the arc ------------------------

def test_a_bumped_round_does_not_block_a_merge(robot, repo, tmp_path):
    """⛔⛔ THE ARC FLOW WOULD HAVE BLOCKED ITSELF ON ITS OWN BOOKKEEPING. Measured 2026-09-03 on
    the live repo: `gate_round.json` sat at round 1 in the MAIN checkout, so the tree read dirty,
    and `_require_clean` guards `merge` — which is exactly what an arc does at the end.

    ⚠ Nothing seals the main checkout, because nothing CREATES it: `worktree add` sets
    `--skip-worktree`, and there is no equivalent moment for the tree you already have. So a round
    bump there is indistinguishable from uncommitted work unless the guard is told otherwise.

    ⭐ Counting it as dirt is the same category error as counting a build cache: a file whose whole
    contract is "differs locally, never commits" is not uncommitted WORK."""
    _track_arc(repo)
    subprocess.run(["git", "checkout", "-q", "-b", "side"], cwd=repo, capture_output=True)
    (repo / "feature.txt").write_text("arc work\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "arc work"], cwd=repo, capture_output=True)
    subprocess.run(["git", "checkout", "-q", "illustrated"], cwd=repo, capture_output=True)

    _write_arc(repo, 3)                      # the arc bumped its round; NOT staged

    out = robot.merge("side", reason="ending the arc")
    assert out["decision"] == "allowed", (
        f"a round bump blocked the merge that ends the arc: {out}")


def test_real_dirt_still_blocks_a_merge(robot, repo, tmp_path):
    """⚠ THE CONTROL, AND IT IS WHAT KEEPS THE EXEMPTION FROM BEING A HOLE. Only the arc-state
    file is exempt. Genuine uncommitted work must still refuse, or the narrowing has quietly
    removed the guard rather than corrected it."""
    from core.errors import RefusalError

    _track_arc(repo)
    subprocess.run(["git", "checkout", "-q", "-b", "side2"], cwd=repo, capture_output=True)
    subprocess.run(["git", "checkout", "-q", "illustrated"], cwd=repo, capture_output=True)

    _write_arc(repo, 3)                                          # exempt
    (repo / "tracked.txt").write_text("PRECIOUS EDIT\n", encoding="utf-8")   # NOT exempt

    with pytest.raises(RefusalError):
        robot.merge("side2", reason="should refuse")


def test_the_refusal_names_the_repo_and_never_claims_staged(robot, repo, tmp_path):
    """⚠⚠ MEASURED COST, 2026-09-03. `_staged_arc_round` reads `git show :<path>` — the INDEX
    copy, which equals HEAD whenever nothing is staged. So the old wording "is staged" was FALSE
    in the ordinary case, and it sent ZeroParadox to inspect a clean main checkout FOUR TIMES
    while the value came from a second `gate_round.json` inside `.claude-local` at round 5.

    ⭐ The refusal was correct; the message cost the diagnosis. §3's rule that a refusal must name
    the alternative has a sibling: **it must name the OBJECT it read.** A caller who checks the
    stated mechanism and finds it absent concludes the guard is stale — and a caller who thinks a
    guard is stale is a caller looking for a way around it."""
    _track_arc(repo)
    _write_arc(repo, 7)
    subprocess.run(["git", "add", "-f", ARC], cwd=repo, capture_output=True)

    with pytest.raises(RefusalError) as exc:
        robot.commit(_msg(tmp_path, "bump\n"), run_gate=False)
    msg = str(exc.value)

    assert "index copy" in msg, "the message must say WHAT it read"
    assert "main" in msg, "the message must name WHICH repo it read"
    assert "is staged carrying" not in msg, (
        "the message still asserts staging, which is false whenever the tracked copy alone "
        "carries the round — the exact claim that misdirected the diagnosis")


def test_the_refusal_never_tells_the_caller_to_hand_write_zero(robot, repo, tmp_path):
    """⛔⛔ THE GUARD USED TO INSTRUCT THE DESTRUCTION OF EVIDENCE. Reported by ZeroParadox
    2026-09-03: they hand-wrote `gate_round.json` back to 0 to satisfy this refusal, after an arc
    that had reached the BEDROCK CAP of five. The walk survived only because they chose to narrate
    it to Tim — and in their words, **"a permitted suppression that depends on the operator
    choosing to mention it is not a control."**

    ⚠⚠ THEY FRAMED IT AS THEIR CHOICE. IT WAS MY WORDING: the refusal read *"reset it to 0 and
    commit that"*. The guard was right to refuse and the remedy it named was the harmful one — a
    hand-written zero is byte-identical to a fresh arc, so nothing downstream can tell a walked cap
    from a clean start.

    ⭐ `gate_round.py reset` writes `reset_from`, so `show` announces that a cap was reached. The
    escape stays permitted and becomes VISIBLE, which is the shape a sanctioned bypass has to
    have — the same argument as the vendored allowlist."""
    _track_arc(repo)
    _write_arc(repo, 5)                       # an arc at the bedrock cap
    subprocess.run(["git", "add", "-f", ARC], cwd=repo, capture_output=True)

    with pytest.raises(RefusalError) as exc:
        robot.commit(_msg(tmp_path, "cap walked\n"), run_gate=False)
    msg = str(exc.value)

    assert "gate_round.py reset" in msg, "the refusal must name the route that stays visible"
    assert "reset it to 0 and commit that" not in msg, (
        "the refusal still instructs a hand-written zero, which erases that a cap was reached")
    assert "hand-writing 0" in msg or "hand-written zero" in msg, (
        "the refusal must say WHY a hand-written zero is wrong, not merely offer the alternative")
