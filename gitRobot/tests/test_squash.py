"""`squash` — because `can_push` walks EVERY commit, and intermediates are the problem.

⭐⭐ THE MEASUREMENT THAT REQUIRED THIS, taken on the convergence run 2026-08-29:

    can_push(origin/illustrated..HEAD)       REFUSED  short 31/31
    can_push(origin/illustrated..<squashed>) REFUSED  short  1/1

All 31 recorded nothing (`admission_state: UNSET, required: 0`) — they were intermediate
states of one remediation. `can_push` is right to refuse them; they are just as published
as the tip. The two honest exits are to certify 31 commits after the fact, which `crossref`
correctly flags BACKFILLED, or to stop creating 31 published commits. This is the second,
and it RELAXES NO GATE: it makes the published history equal to the tree that passed.

⚠⚠ commit-tree, NOT `reset --soft` + commit. The ordinary idiom rebuilds the commit FROM
THE INDEX, so its result depends on index state when it runs. This reuses HEAD's tree
OBJECT by id and gives it a new parent — nothing reads or writes the index or the working
tree, which is why it is reachable where §3 Tier 1's `reset --hard` is not.
"""

import subprocess

import pytest

from core.errors import RefusalError, UsageError


def _git(repo, *args):
    p = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr
    return p.stdout


def _msg(repo, text):
    """⚠ THE MESSAGE TRAVELS AS A FILE, never as an argument — see `squash`'s docstring.

    ⚠⚠ WRITTEN OUTSIDE THE REPO, and that is not tidiness. `_require_clean` counts an
    UNTRACKED file as dirty, so a message file dropped in the working tree makes every
    squash refuse — and it would have masked the empty-range refusal with a dirty-tree
    one, since the clean check runs first. Callers hit this too: put the message
    somewhere outside the checkout."""
    f = repo.parent / "_squash_msg.txt"
    f.write_text(text, encoding="utf-8")
    return str(f)


def _commits(repo, rng):
    return int(_git(repo, "rev-list", "--count", rng).strip())


def _make(repo, robot, n):
    """n local commits on top of origin/illustrated, none of them published."""
    for i in range(n):
        (repo / f"f{i}.txt").write_text(f"content {i}\n", encoding="utf-8")
        robot.stage([f"f{i}.txt"])
        _git(repo, "commit", "-q", "-m", f"local {i}")


# -- ⭐⭐ the thing that could not be done ------------------------------------

def test_many_commits_collapse_to_one_with_the_same_tree(robot, repo):
    """⭐⭐ THE HEADLINE, and both halves matter. The COUNT drops so `can_push` has one
    commit to judge instead of N; the TREE is byte-identical so every content-keyed
    verdict recorded against it still applies."""
    _make(repo, robot, 5)
    assert _commits(repo, "origin/illustrated..HEAD") == 5
    tree_before = _git(repo, "rev-parse", "HEAD^{tree}").strip()

    out = robot.squash(onto="origin/illustrated", message_file=_msg(repo, "one convergence run"),
                       reason="31 intermediates recorded nothing; can_push walks each")

    assert out["decision"] == "allowed"
    assert _commits(repo, "origin/illustrated..HEAD") == 1
    assert _git(repo, "rev-parse", "HEAD^{tree}").strip() == tree_before


def test_the_tree_is_reused_by_id_not_recomputed(robot, repo):
    """⚠⚠ THE SAFETY ARGUMENT, PINNED. The receipt names the tree it carried, and it is
    HEAD's existing tree object — not a tree rebuilt from the index."""
    _make(repo, robot, 3)
    tree_before = _git(repo, "rev-parse", "HEAD^{tree}").strip()

    out = robot.squash(onto="origin/illustrated", message_file=_msg(repo, "m"), reason="r")

    assert out["tree"] == tree_before
    assert _git(repo, "rev-parse", f"{out['new_sha']}^{{tree}}").strip() == tree_before


def test_the_working_tree_and_index_are_untouched(robot, repo):
    """⚠ WHY THIS IS NOT TIER 1. `reset --hard` is refused because it destroys
    uncommitted working-tree state that exists nowhere else. This cannot reach it.

    ⚠⚠ NOTE HOW THE PROPERTY IS ACTUALLY ESTABLISHED, because the obvious test is not
    writable: `_require_clean` counts an UNTRACKED file as dirty, so there is no way to
    enter this call with uncommitted state at all. The guarantee is the precondition
    plus the fact that nothing here writes — so what is checkable afterwards is that
    the tree is byte-identical and `status` is STILL clean. A squash that rebuilt from
    the index could leave phantom staged entries here; this cannot."""
    _make(repo, robot, 2)
    before = {p: (repo / p).read_text(encoding="utf-8") for p in ("f0.txt", "f1.txt")}

    robot.squash(onto="origin/illustrated", message_file=_msg(repo, "m"), reason="r")

    for p, content in before.items():
        assert (repo / p).read_text(encoding="utf-8") == content
    assert _git(repo, "status", "--porcelain").strip() == ""


# -- ⚠ recoverability, because the old commits become unreferenced ------------

def test_the_receipt_names_the_old_tip_so_the_history_is_findable(robot, repo):
    """⚠⚠ THE OLD COMMITS ARE NOT GONE, THEY ARE UNREFERENCED — git keeps them until
    gc, and the receipt is how a person finds them. An irreversible-LOOKING operation
    that records no way back is how §7's audit stops being an audit."""
    _make(repo, robot, 4)
    old_tip = _git(repo, "rev-parse", "HEAD").strip()

    out = robot.squash(onto="origin/illustrated", message_file=_msg(repo, "m"), reason="r")

    assert out["old_tip"] == old_tip
    assert out["commits_squashed"] == 4
    # still reachable by sha, which is the whole point of recording it
    assert _git(repo, "cat-file", "-t", old_tip).strip() == "commit"


def test_it_is_audited_like_every_other_mutating_call(robot, repo):
    """⚠ §7: every mutating call leaves a record, including the clean path."""
    _make(repo, robot, 2)
    robot.squash(onto="origin/illustrated", message_file=_msg(repo, "m"), reason="collapsing intermediates")
    last = robot.audit.read()[-1]
    assert last["op"] == "squash"
    assert last["decision"] == "allowed"
    assert last["reason"] == "collapsing intermediates"


# -- ⚠ the refusals ----------------------------------------------------------

def test_published_commits_are_refused(robot, repo):
    """⚠⚠ THE GUARD THAT MATTERS, shared with `rebase`. Once the remote has them,
    rewriting breaks every checkout that pulled, and the damage surfaces later."""
    _make(repo, robot, 3)
    _git(repo, "push", "-q", "origin", "illustrated")  # now they ARE published

    with pytest.raises(RefusalError) as exc:
        robot.squash(onto="origin/illustrated~3", message_file=_msg(repo, "m"), reason="r")
    assert "already on the remote" in str(exc.value)


def test_a_dirty_tree_is_refused(robot, repo):
    """⚠ Carrying uncommitted work across a branch move ends with it committed on a
    branch it was never written for. Same guard `rebase` and `merge` use."""
    _make(repo, robot, 2)
    (repo / "f0.txt").write_text("modified after commit\n", encoding="utf-8")
    robot.stage(["f0.txt"])

    with pytest.raises(RefusalError):
        robot.squash(onto="origin/illustrated", message_file=_msg(repo, "m"), reason="r")


def test_an_empty_range_is_refused(robot, repo):
    """⚠ Nothing to squash is a mistake about the base ref, not a no-op to swallow."""
    with pytest.raises(RefusalError) as exc:
        robot.squash(onto="origin/illustrated", message_file=_msg(repo, "m"), reason="r")
    assert "nothing to squash" in str(exc.value)


def test_a_detached_head_is_refused(robot, repo):
    """⚠⚠ THERE IS NO BRANCH TO MOVE, so the squashed commit would be created and
    immediately unreferenced — which looks like success and loses the work."""
    _make(repo, robot, 2)
    _git(repo, "checkout", "-q", "--detach", "HEAD")

    with pytest.raises(RefusalError) as exc:
        robot.squash(onto="origin/illustrated", message_file=_msg(repo, "m"), reason="r")
    assert "detached" in str(exc.value)


@pytest.mark.parametrize("bad", ["", "   "])
def test_a_missing_message_or_reason_is_refused(robot, repo, bad):
    _make(repo, robot, 1)
    with pytest.raises(UsageError, match="message"):
        robot.squash(onto="origin/illustrated", message_file=bad, reason="r")
    with pytest.raises(UsageError, match="reason"):
        robot.squash(onto="origin/illustrated", message_file=_msg(repo, "m"), reason=bad)


def test_a_ref_that_looks_like_a_flag_is_never_passed_as_one(robot, repo):
    with pytest.raises(UsageError, match="is not a ref"):
        robot.squash(onto="--hard", message_file=_msg(repo, "m"), reason="r")


def test_no_force_and_no_index_reads_in_the_call_it_builds(robot, repo):
    """⚠⚠ PINNED BY READING THE SOURCE, because the safety claim is about which git
    commands are reachable, not about what the happy path happened to do. §6 requires
    `force` / `allow_dirty` to stay ABSENT, and the index must never be involved.

    ⚠ THE DOCSTRING IS STRIPPED FIRST. The first version of this test asserted
    `"reset" not in src` and failed on the docstring's own explanation of why `reset
    --soft` was rejected — a source-pin that reads prose is checking the comment, not
    the code, and would pass or fail on wording."""
    import ast
    import inspect
    from core import engine
    tree = ast.parse(inspect.getsource(engine.GitRobot.squash).strip())
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]          # drop the docstring; keep only executable code
    code = ast.unparse(fn)

    assert "commit-tree" in code
    assert "--force" not in code and "--hard" not in code
    assert "reset" not in code
    assert "'add'" not in code and "write-tree" not in code


# -- ⭐⭐ the message is a FILE, and this is why -------------------------------

def test_a_message_with_prose_glyphs_and_newlines_survives_intact(robot, repo):
    """⭐⭐ THE REGRESSION FOR THE ARGV BUG. The first cut passed the message as
    `-m <message>` on argv, contradicting `commit`'s own rule for the one thing both
    tools produce. Raised by ZeroParadox 2026-08-29: a SQUASH message is strictly worse
    than a commit message on every axis the rule names — it summarises N commits, so it
    is longer, quotes more prose, and is likelier to carry a glyph. This corpus writes
    ε₀, ⊥ and p-adic notation into prose constantly.

    ⚠ Asserts the ROUND TRIP, not the call shape: what git stored must equal what was
    written. An encoding bug that mangles the message would still 'pass' a test that
    only checked the flag.

    ⚠⚠ WHAT THIS TEST DOES AND DOES NOT PROVE, corrected by ZeroParadox 2026-08-29 and
    worth stating because the first version of this docstring overclaimed. `gitio.run`
    passes a LIST to `subprocess`, so the process is spawned directly and NO SHELL IS
    INVOLVED — quotes, backticks and `$VAR` are inert through argv and were never at
    risk. They are kept below only as a negative control; **they would have passed
    before the fix too.** Of the three axes R-SHELL names, only two were live here:
    LENGTH (Windows caps argv near 32k — see the next test) and ENCODING (non-ASCII
    crossing the ANSI codepage). So it is the GLYPHS that earn this test, not the
    punctuation. A test whose stated justification is broader than the hazard it
    exercises is the same class as a source-pin that reads comments."""
    _make(repo, robot, 3)
    body = (
        "collapse ε₀ succession arc into one commit\n"
        "\n"
        "Covers ⊥-preservation and the p-adic valuation leg; \"quoted\" prose,\n"
        "an apostrophe's worth of trouble, a $VAR and a `backtick`.\n"
    )

    out = robot.squash(onto="origin/illustrated", message_file=_msg(repo, body), reason="r")

    stored = _git(repo, "log", "-1", "--format=%B").strip()
    assert stored == body.strip()
    assert "ε₀" in stored and "⊥" in stored
    assert out["decision"] == "allowed"


def test_the_message_content_never_appears_on_argv(robot, repo):
    """⚠⚠ THE RULE ITSELF, not just its happy path. R-SHELL: "CONTENT NEVER TRAVELS ON
    A COMMAND LINE — argv breaks on LENGTH (Windows caps at ~32k), QUOTING and
    ENCODING." Only the PATH may go on argv."""
    seen = []
    real = robot.git.run
    robot.git.run = lambda args, **kw: (seen.append(list(args)), real(args, **kw))[1]
    try:
        _make(repo, robot, 2)
        body = "a distinctive sentinel ε₀ that must never be an argument\n"
        robot.squash(onto="origin/illustrated", message_file=_msg(repo, body), reason="r")
    finally:
        robot.git.run = real

    flat = [tok for argv in seen for tok in argv]
    assert not any("sentinel" in tok for tok in flat), "message content reached argv"

    # ⚠ SCOPED TO THE commit-tree CALL, and the first version of this test was not —
    # it asserted `-m` appeared nowhere and failed on `update-ref -m "squash: <reason>"`,
    # which is a REFLOG note, not the commit message. `reason` travels as a string on
    # every mediated op (rebase, merge, unstage); it is short operator text, not prose.
    # The rule being pinned is about the MESSAGE, so pin it where the message is used.
    ct = [argv for argv in seen if argv and argv[0] == "commit-tree"]
    assert len(ct) == 1, f"expected exactly one commit-tree call, got {len(ct)}"
    assert "-F" in ct[0], "commit-tree must read the message from a file"
    assert "-m" not in ct[0], "-m puts the commit message on argv"


# -- ⚠ the detector for the class ZeroParadox named ---------------------------

def test_a_source_pin_reads_CODE_not_COMMENTS(robot, repo):
    """⚠⚠ A DETECTOR FOR A CLASS THAT HIT THREE TIMES IN ONE DAY ACROSS TWO CODEBASES.
    The pin above initially matched the word `reset` inside the docstring's own
    explanation of why `reset` was rejected — so it was checking the comment, not the
    code, and would flip on a wording change while a real `reset` call slipped past.
    Same shape as `check_checkers`'s own finding ("a manifest row is not a call") and
    ZeroParadox's truncation hook matching a MENTION rather than an INVOCATION, twice.

    ZeroParadox's formulation, which is the right one: **the pin must fail when the CODE
    changes and hold when only the COMMENT does.** Both directions are asserted here,
    because a pin that only satisfies one of them is the bug it is meant to catch."""
    import ast
    import inspect
    from core import engine

    def _code_of(src):
        fn = ast.parse(src.strip()).body[0]
        if (fn.body and isinstance(fn.body[0], ast.Expr)
                and isinstance(fn.body[0].value, ast.Constant)):
            fn.body = fn.body[1:]
        return ast.unparse(fn)

    src = inspect.getsource(engine.GitRobot.squash)

    # (1) HOLDS when only the comment changes: rewrite the docstring to say "reset"
    #     many times over. The extracted code must be unaffected.
    doctored = src.replace("Replace ``onto..HEAD``",
                           "reset reset reset -- Replace ``onto..HEAD``", 1)
    assert _code_of(doctored) == _code_of(src)
    assert "reset" not in _code_of(doctored)

    # (2) FAILS when the code changes: inject a real call the pin must catch.
    broken = src.replace('made = self.git.run(["commit-tree"',
                         'self.git.run(["reset", "--hard"]) or None\n        '
                         'made = self.git.run(["commit-tree"', 1)
    assert broken != src, "injection anchor missing — the detector itself has rotted"
    assert "reset" in _code_of(broken)


def test_a_message_far_past_the_argv_cap_survives(robot, repo):
    """⚠⚠ THE AXIS THAT WAS ACTUALLY LIVE, and the one a quoting test cannot reach.
    Windows caps a command line near 32k; `-m <message>` on argv puts the whole message
    under that ceiling, and a squash message summarising a long remediation is exactly
    the thing that approaches it. `-F <path>` puts only the path on argv, so the message
    has no such limit.

    ⚠ Sized WELL past the cap on purpose: at ~40k this fails outright under the old
    argv form rather than landing near a boundary where it might pass by luck."""
    _make(repo, robot, 2)
    body = "squash of a long remediation\n\n" + "\n".join(
        f"paragraph {i}: " + "detail " * 40 for i in range(160))
    assert len(body.encode("utf-8")) > 40_000, "the test must exceed the argv cap"

    out = robot.squash(onto="origin/illustrated", message_file=_msg(repo, body), reason="r")

    assert out["decision"] == "allowed"
    assert _git(repo, "log", "-1", "--format=%B").strip() == body.strip()
