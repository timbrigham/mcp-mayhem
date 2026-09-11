"""A merge is a commit, so it is gated like one — and it was not.

⛔⛔ THE HOLE, PLAINLY. `commit` ran `pre-commit` and refused on failure. `merge` ran
`git merge --no-ff` and ran NOTHING. Both produce a commit; only one was gated. So the
mechanically enforced claim this whole server rests on — Tim, 2026-09-03, *"if we do this
right, the only way that you're ever going to have a commit done is inside of this dedicated
MCP server right?"* — was true about the door and false about the window beside it.

⚠⚠ AND THE MERGE COMMIT IS THE WORST ONE TO LEAVE UNGATED, because its tree can be content
NEITHER PARENT EVER HAD. Two branches that each pass every check can merge into a tree that
fails — that is what a semantic conflict IS. A gate that only ever sees the parents is
structurally incapable of catching it, so this was not merely an unguarded path; it was the
one path where the guard was the only thing that could have looked.

⚠ THE PUSH GATE IS NOT A SUBSTITUTE, and believing it was is what let this sit. `can_push`
does block a merge commit with no coverage — at push time, with the arc already polluted, and
under the `tip_green` bar a green tip can carry forgiven intermediates besides. "It gets caught
eventually" is the argument that makes every gate optional.

⭐ WHY `--no-commit` AND NOT A PRE-MERGE CHECK. Gating before the merge would verify the tree
the merge is about to REPLACE — the check and the act about different objects, which is the
defect class this project has spent a week removing and which `commit` itself had to be
corrected for once when `worktree` became targetable. The merge goes into the index, the gate
reads the RESULT, and the commit happens only if it passes.
"""

import subprocess

import pytest

from conftest import _git
from core.errors import RefusalError


POISON = "poison.txt"

# ⭐⭐ A GATE THAT ACTUALLY LOOKS AT THE TREE. `fake_gate`'s pass/fail switch cannot tell the
# two designs apart — it returns the same code whenever it runs, so a gate on the PRE-MERGE
# tree and a gate on the MERGED tree both "pass". This one is a function OF the content, which
# is the only thing that distinguishes them.
#
# ⚠ Resolved from `__file__`, not the cwd: the assertion must be about the tree, and a gate
# that silently checked the wrong directory would pass for a reason that has nothing to do
# with what is under test.
_CONTENT_GATE = (
    "import sys, pathlib\n"
    "repo = pathlib.Path(__file__).resolve().parents[2]\n"
    f"if (repo / {POISON!r}).exists():\n"
    "    print('BLOCK: the merged tree contains poison.txt')\n"
    "    sys.exit(1)\n"
    "print('gate ran, tree is clean')\n"
    "sys.exit(0)\n"
)


def _install_content_gate(repo):
    entry = repo / "tools" / "verify" / "hooks.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(_CONTENT_GATE, encoding="utf-8")
    # ⚠ COMMITTED, not left untracked — `merge` calls `_require_clean` first, and an
    # untracked gate script is dirt that would refuse the merge before any of this is
    # reached. The test would then pass while testing the wrong refusal.
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "install gate")


def _feature_branch(repo, files, name="feature"):
    """A branch carrying `files`, with the working tree returned to `illustrated`."""
    _git(repo, "checkout", "-q", "-b", name)
    for fname, content in files.items():
        (repo / fname).write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"work on {name}")
    _git(repo, "checkout", "-q", "illustrated")


def _head(robot):
    return robot.git.head()


def _is_clean(robot):
    return not robot.git.porcelain()


# -- ⭐⭐ the headline ---------------------------------------------------------

def test_the_gate_sees_the_MERGED_tree_not_the_pre_merge_one(robot, repo):
    """⭐⭐⭐ THE TEST THAT DISTINGUISHES THE TWO DESIGNS, and the reason `--no-commit` is
    load-bearing rather than stylistic.

    `poison.txt` exists ONLY on the feature branch. Before the merge, `illustrated` is clean
    and the gate passes — so a pre-merge check would wave this through. After the merge the
    file is present and the gate fails. The refusal below is therefore proof that the gate ran
    on the RESULT, which no pass/fail stub could have established.
    """
    _install_content_gate(repo)
    _feature_branch(repo, {POISON: "bad\n"})

    # the control: on this tree, right now, the gate is GREEN.
    assert robot.gates.run("pre-commit").passed, (
        "the premise is broken — if the gate already fails on the pre-merge tree, the "
        "refusal below proves nothing about which tree it read")

    with pytest.raises(RefusalError, match="did not pass on the RESULT"):
        robot.merge("feature", reason="bringing feature in")


def test_a_failing_gate_leaves_no_merge_commit_and_a_clean_tree(robot, repo):
    """⛔ A REFUSAL THAT LEAVES A MESS IS NOT A REFUSAL. `--no-commit` means a failing gate
    has a half-applied merge sitting in the index, and every branch-moving op in this server
    requires a clean tree — so failing to abort would brick commit, switch, merge, rebase and
    squash alike, each reporting "the tree is dirty" and none naming the cause."""
    _install_content_gate(repo)
    _feature_branch(repo, {POISON: "bad\n"})
    before = _head(robot)

    with pytest.raises(RefusalError):
        robot.merge("feature", reason="bringing feature in")

    assert _head(robot) == before, "the merge commit must not exist"
    assert _is_clean(robot), (
        "the working tree must be restored — a refused merge that leaves the index half "
        "applied blocks every subsequent operation with an unrelated message")
    assert not (repo / POISON).exists(), "the merged content must be gone too"


def test_the_refusal_is_audited_with_the_gate_record(robot, repo):
    """⚠ A GUARD THAT ONLY WRITES A ROW WHEN IT LETS SOMETHING THROUGH CANNOT ANSWER "DID
    THIS EVER FIRE?" — the question that matters after an incident. The gate's own output is
    carried, so a reader learns WHY without re-running anything."""
    _install_content_gate(repo)
    _feature_branch(repo, {POISON: "bad\n"})

    with pytest.raises(RefusalError):
        robot.merge("feature", reason="bringing feature in")

    row = robot.audit.read()[-1]
    assert row["op"] == "merge" and row["decision"] == "refused"
    assert row["gates"][0]["passed"] is False
    assert "poison.txt" in row["gates"][0]["output"], (
        "the gate's finding must reach the audit, or the row records that something failed "
        "without recording what")


def test_a_passing_gate_produces_a_real_merge_commit(robot, repo):
    """⭐ THE GATE MUST NOT BECOME A WALL. The whole point is that clean merges still work,
    and `--no-ff` still means a merge commit with two parents rather than a fast-forward."""
    _install_content_gate(repo)
    _feature_branch(repo, {"harmless.txt": "fine\n"})

    result = robot.merge("feature", reason="bringing feature in")

    assert result["decision"] == "allowed" and result["ok"]
    assert result["gates"][0]["phase"] == "pre-commit"
    assert result["gates"][0]["passed"] is True
    assert result["merged"] is True
    parents = _git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()
    assert len(parents) == 3, f"--no-ff must give the merge commit two parents, got {parents}"
    assert (repo / "harmless.txt").exists()
    assert _is_clean(robot)


# -- the paths that are not a gate failure ------------------------------------

def test_a_conflicting_merge_is_aborted_and_names_the_way_out(robot, repo):
    """⚠⚠ gitRobot HAS NO CONFLICT-RESOLUTION PATH, so it must not be the thing that leaves a
    conflicted checkout behind. Aborting is not a loss of information — the conflict is
    reproducible from the two refs at any time — and it keeps the server usable.

    ⚠ §3: the refusal must NAME THE ALTERNATIVE. A conflict is a decision about which content
    is correct; the honest answer is a private checkout, resolved by hand, committed through
    the gate."""
    _install_content_gate(repo)
    _feature_branch(repo, {"tracked.txt": "from the feature branch\n"})
    (repo / "tracked.txt").write_text("from illustrated\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "diverge")
    before = _head(robot)

    with pytest.raises(RefusalError) as exc:
        robot.merge("feature", reason="bringing feature in")

    assert "did not apply cleanly" in str(exc.value)
    assert "worktree(action='add'" in str(exc.value), (
        "a refusal that does not name the alternative is how a workaround gets invented")
    assert _head(robot) == before
    assert _is_clean(robot), "a conflicted index would refuse every later operation"


def test_an_up_to_date_merge_is_a_no_op_not_an_error(robot, repo):
    """⚠ `--no-commit` ON AN UP-TO-DATE BRANCH STAGES NOTHING, so a blind `git commit` after
    it would fail for a reason that has nothing to do with the merge — and the receipt would
    report `failed` for a merge that was simply unnecessary.

    ⚠ Detected via MERGE_HEAD rather than by matching "Already up to date." — that string is
    localised, and a guard that breaks under a different locale is a guard that fails where it
    is hardest to debug."""
    _install_content_gate(repo)
    _feature_branch(repo, {"harmless.txt": "fine\n"})
    robot.merge("feature", reason="first merge")
    after_first = _head(robot)

    result = robot.merge("feature", reason="merging again, nothing to do")

    assert result["decision"] == "allowed"
    assert result["merged"] is False
    assert _head(robot) == after_first, "an up-to-date merge must not create a commit"
    assert _is_clean(robot)


def test_merge_proceeds_on_a_dirty_tree_and_reports_what_it_carried(robot, repo, dirty):
    """⭐⭐ MERGE NO LONGER REFUSES A DIRTY TREE, AND GIT IS WHY IT DOES NOT NEED TO.

    Measured 2026-09-10 in a scratch repo rather than reasoned from the analogue:

        UNSTAGED change to an unrelated file -> git ALLOWS the merge
        STAGED   change to an unrelated file -> git REFUSES it ITSELF

    So the dangerous case -- a dirty INDEX, whose contents `--no-commit` would sweep into the
    merge commit -- is already refused by git, and the safe case was all the guard was still
    stopping. `_require_clean`'s own docstring conceded it: "Git already refuses the cases that
    would overwrite a file."

    ⚠ AND THE RATIONALE NEVER FIT MERGE. It is "carried across a branch change, so it ends up
    committed on a branch it was never written for" -- but a merge brings another branch INTO
    HEAD and leaves you where you were. A grouping error, not a relaxation; switch and rebase
    still refuse.

    ⭐ Tim, 2026-09-10: "maybe documentation when files are carried forward at most .. but
    blocking them... that's bad design."

    ⛔ THE DOCUMENT IS THE WHOLE BARGAIN. Replacing a refusal with a silent carry-forward would
    be strictly worse than the refusal, so this asserts the receipt NAMES the file.
    """
    _install_content_gate(repo)
    _feature_branch(repo, {"harmless.txt": "fine" + chr(10)})
    # ⚠ RE-DIRTY AFTER THE BRANCH SETUP, AND THE REASON IS ITSELF THE HAZARD UNDER TEST.
    # `_feature_branch` runs `git add -A` and commits, which SWEEPS the `dirty` fixture's
    # uncommitted work onto the feature branch -- the exact "committed where it was never
    # written" shape `stage` refuses bulk adds over. Without this line the tree is clean by
    # the time merge runs and the assertion below passes vacuously on an empty report.
    # ⚠ AND IT MUST BE DIFFERENT BYTES. Writing the SAME content back produces no diff, so the
    # tree is clean and this test passes vacuously on an empty report -- which is exactly what
    # it did on the first attempt. A fixture that restores the string but not the DIRTINESS is
    # a control that measures nothing.
    (repo / "tracked.txt").write_text("PRECIOUS EDIT, CARRIED" + chr(10), encoding="utf-8")

    receipt = robot.merge("feature", reason="a dirty tree must not block a merge")
    assert receipt["decision"] == "allowed"
    assert receipt["merged"] is True

    carried = receipt.get("carried_forward")
    assert carried, "a merge over a dirty tree must report what it carried forward"
    assert "tracked.txt" in set(carried["uncommitted_work"]), (
        "the modified file rode along uncommitted and the receipt did not name it: %r"
        % (carried["uncommitted_work"],))

    # ⚠ THE BYTES, NOT JUST THE DECISION. Carrying rather than blocking is only correct if the
    # work is still there afterwards.
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "PRECIOUS EDIT, CARRIED" + chr(10)
    assert (repo / "untracked.txt").exists()


def test_uncommitted_work_survives_a_merge_that_the_gate_rejects(robot, repo, dirty):
    """⛔⛔ THE OLD TEST HERE ASSERTED THE DIRTY-TREE REFUSAL, AND ITS DOCSTRING NAMED THE REAL
    WORRY: "because `--no-commit` now stages the merge, a dirty tree would also make 'restore
    on failure' impossible to define." The worry outlived the refusal, so this pins the
    PROPERTY rather than the guard that used to stand in for it.

    ⭐ GIT'S OWN PRECONDITION IS WHAT MAKES IT DEFINABLE, and it is why dropping the refusal was
    safe: git allows a merge over an UNSTAGED change to an unrelated file and REFUSES one over a
    STAGED change. So by the time gitRobot merges, the dirty paths are provably ones the merge
    does not touch, and `merge --abort` restores the index and the merged paths while leaving
    those alone. The overlapping case, where abort could destroy local work, is the case git
    never let start.

    ⚠ THE ASSERTION IS ON THE BYTES. A test that only checked "it refused" would still pass if
    the abort silently ate the file.
    """
    with pytest.raises(RefusalError):
        robot.merge("feature", reason="gate will reject this merge")
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "PRECIOUS EDIT" + chr(10), (
        "the uncommitted work did not survive the aborted merge")
    assert (repo / "untracked.txt").exists(), "the untracked file did not survive"


def test_a_missing_gate_pipeline_refuses_the_merge(robot, repo):
    """⛔ ABSENCE MUST NOT RENDER AS SUCCESS — the fail-open shape this codebase has paid for
    repeatedly. A merge into a repo with no pipeline is not a merge that passed its checks."""
    _feature_branch(repo, {"harmless.txt": "fine\n"})
    with pytest.raises(RefusalError):
        robot.merge("feature", reason="no pipeline here")
    assert _is_clean(robot)


# -- ⭐⭐ what the gate COSTS, which decides whether it is usable ---------------

def test_a_no_op_merge_does_not_run_the_gate_at_all(robot, repo):
    """⭐⭐⭐ THE COST QUESTION, MEASURED RATHER THAN ASSERTED — asked by the ZeroParadox
    session 2026-09-05 on reading that `merge` had become gated.

    That project's `CLAUDE.md` R-BRANCH mandates `fetch()` then `merge('origin/main')` at
    SESSION START, before any edit. If a no-op merge ran the pipeline, every session would pay
    a full gate run before doing anything — and the discipline that stops people editing
    against a stale base would become the most expensive move in the workflow. **The thing
    agents would route around is the session-start sync**, whose own cost line records that a
    file with unresolved conflict markers has committed silently and corrupted a document
    twice on that project.

    ⛔ THE GATE IS INSTALLED IN THE FAILING STATE HERE, ON PURPOSE. Asserting `merged is False`
    only shows no commit was made; it cannot show the pipeline was not consulted. A gate that
    REFUSES if it runs makes the two outcomes distinguishable — this merge can only succeed if
    nothing ever asked it.

    ⭐ SO: no commit, no gate. The cost lands only when the base actually moved, which is the
    case where a semantic conflict is possible in the first place.
    """
    _install_content_gate(repo)
    _feature_branch(repo, {"harmless.txt": "fine\n"})
    robot.merge("feature", reason="first merge")

    # now poison the tree so the gate would REFUSE if it were consulted
    (repo / POISON).write_text("bad\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "poison, committed so the tree is clean")
    assert not robot.gates.run("pre-commit").passed, (
        "the premise is broken — the gate must be RED for this to prove anything")

    result = robot.merge("feature", reason="already up to date")

    assert result["decision"] == "allowed" and result["merged"] is False, (
        "an up-to-date merge ran the gate — every session-start sync would pay a full "
        "pipeline run for a merge that does nothing")
    assert "gates" not in result or not result.get("gates"), (
        "no gate should have been recorded for a merge that produced no commit")


def test_the_arc_round_bump_survives_a_gated_merge_uncommitted(robot, repo):
    """⚠ THE SECOND THING ZeroParadox ASKED TO CONFIRM BEFORE SOMEONE MEETS IT AT SESSION
    START. `gate_round.json` is TRACKED, deliberately modified locally, and must never commit
    — `_require_clean` exempts it, and this path now ends in a `git commit`, which is a new
    opportunity to sweep it in.

    ⭐ It does not, and the reason is structural rather than lucky: `commit --no-edit` writes
    the INDEX, and an unstaged modification was never in it. Asserted anyway, because
    "structurally safe" is what the wide-FAIL and the tip-versus-range bugs both looked like
    from the inside."""
    _install_content_gate(repo)
    arc = repo / "gate_round.json"
    arc.write_text('{"round": 0}\n', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "arc handshake default")
    _feature_branch(repo, {"harmless.txt": "fine\n"})

    arc.write_text('{"round": 3}\n', encoding="utf-8")     # the arc bumped; NOT staged

    result = robot.merge("feature", reason="ending the arc")

    assert result["decision"] == "allowed" and result["merged"] is True, (
        f"a round bump blocked the gated merge that ends the arc: {result}")
    assert '"round": 3' in arc.read_text(encoding="utf-8"), "the local bump must survive"
    committed = _git(repo, "show", "HEAD:gate_round.json")
    assert '"round": 0' in committed, (
        "the merge commit swept in the local round bump — the arc file's whole contract is "
        "'differs locally, never commits'")


def test_an_unstaged_collision_is_not_reported_as_a_dirty_index(robot, repo):
    """⛔⛔ THE THIRD CASE, FOUND BY THE CONSUMER ~1h AFTER THE DIRTY-TREE BLOCK CAME OUT.

    They unstaged everything -- `staged: 0`, from a gitRobot receipt ONE CALL EARLIER -- merged,
    and were told "the INDEX is dirty" with the remedy "clear the index and merge again", which
    is the thing they had just done. A false cause and a no-op remedy that loops.

    ⚠ MY OWN CHANGE MADE IT REACHABLE. Relaxing the block invites merging with a dirty tree,
    which is exactly when this fires.

    THREE CASES SHARE ONE GIT MESSAGE and the first version of the classifier modelled two:

        STAGED change, unrelated path      diff --cached DIRTY   commit or unstage
        UNSTAGED change, path the merge    diff --cached CLEAN   unstaging is a NO-OP; the
        must update                                              collision is with the WORKING
                                                                 TREE, refused before starting
        real content conflict              MERGE_HEAD present    decide it in a checkout

    Both of the first two print "Your local changes ... would be overwritten by merge" and
    neither leaves a MERGE_HEAD, so reading the text cannot separate them. The INDEX can.
    """
    _install_content_gate(repo)
    _feature_branch(repo, {"shared.txt": "FROM FEATURE" + chr(10)})

    # An UNSTAGED edit to the very path the merge must update. Index stays clean.
    (repo / "shared.txt").write_text("LOCAL EDIT" + chr(10), encoding="utf-8")

    with pytest.raises(RefusalError) as caught:
        robot.merge("feature", reason="unstaged collision")

    msg = str(caught.value)
    alt = caught.value.alternative or ""
    assert "index is CLEAN" in msg, (
        "the refusal must not claim a dirty index when the index is clean: %s" % msg[:200])
    assert "INDEX is dirty" not in msg, "misclassified as the staged case"
    # ⛔ THE REMEDY MUST NOT BE THE THING THE CALLER ALREADY DID.
    assert "unstaging changes nothing" in msg.lower() or "does NOT help" in alt, (
        "the remedy must say unstaging is a no-op here, or a caller loops on it")
    assert "worktree" in alt and "commit" in alt, "the two real exits must be named"
