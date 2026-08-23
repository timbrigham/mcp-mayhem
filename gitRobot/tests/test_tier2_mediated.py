"""Tier 2: the operations that run, with gitRobot owning how."""

import pytest

from core.errors import RefusalError, UsageError


# -- stage --------------------------------------------------------------------

def test_stage_named_paths(robot, repo):
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    result = robot.stage(["a.txt"])
    assert result["decision"] == "allowed"
    staged = robot.read("diff", ["--cached", "--name-only"])["output"]
    assert "a.txt" in staged and "b.txt" not in staged


@pytest.mark.parametrize("token", ["-A", "--all", ".", "-u", "--update", "*"])
def test_bulk_add_refused_on_main_repo(robot, repo, token):
    """Background agents write here concurrently, so -A stages files this session
    never touched. One scratch probe reached permanent history exactly that way."""
    (repo / "mine.txt").write_text("mine\n", encoding="utf-8")
    (repo / "someone_elses_probe.txt").write_text("probe\n", encoding="utf-8")
    with pytest.raises(RefusalError) as exc:
        robot.stage([token])
    assert "stage(paths=" in exc.value.alternative
    assert robot.read("diff", ["--cached", "--name-only"])["output"] == ""


def test_bulk_add_allowed_for_the_named_nested_repo(robot, repo):
    """`.claude-local` is exempt because bulk add is its documented flow — reached
    as a NAMED mode, never as a path, so the exception stays enumerable."""
    local = repo / ".claude-local"
    local.mkdir()
    import subprocess
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=str(local), check=True,
                       capture_output=True)
    (local / "note.md").write_text("note\n", encoding="utf-8")
    result = robot.stage(["-A"], repo_mode=".claude-local")
    assert result["decision"] == "allowed"


def test_stage_rejects_a_path_that_is_a_flag(robot):
    with pytest.raises(UsageError, match="looks like a flag"):
        robot.stage(["--no-verify"])


def test_stage_requires_a_path(robot):
    with pytest.raises(UsageError, match="at least one path"):
        robot.stage([])


def test_repo_mode_rejects_arbitrary_paths(robot):
    """gitRobot is an allow-list of one; a free-form path would make it a general
    git proxy for every checkout on the machine."""
    with pytest.raises(UsageError, match="does not accept repository paths"):
        robot.stage(["x.txt"], repo_mode="C:/Workspace/SomethingElse")


# -- commit -------------------------------------------------------------------

def _msg(tmp_path, text="a message\n\nwith a body\n"):
    path = tmp_path / "msg.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_commit_runs_the_gate_then_commits(robot, repo, tmp_path, fake_gate):
    fake_gate(0)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    robot.stage(["a.txt"])
    result = robot.commit(_msg(tmp_path), reason="adding a")
    assert result["decision"] == "allowed" and result["ok"]
    assert result["gates"][0]["phase"] == "pre-commit"
    assert result["gates"][0]["passed"] is True
    assert "a message" in robot.read("log", ["-1", "--pretty=%s"])["output"]


def test_a_failing_gate_means_no_commit_at_all(robot, repo, tmp_path, fake_gate):
    """The gate runs FIRST, so a failure costs a report rather than a half-made commit."""
    fake_gate(1, "BLOCK: check_prose failed")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    robot.stage(["a.txt"])
    head_before = robot.git.head()
    with pytest.raises(RefusalError, match="pre-commit gate did not pass"):
        robot.commit(_msg(tmp_path))
    assert robot.git.head() == head_before
    record = robot.audit.read()[-1]
    assert record["decision"] == "refused"
    assert record["gates"][0]["passed"] is False
    assert "check_prose" in record["gates"][0]["output"]


def test_a_missing_gate_pipeline_is_a_finding_not_a_pass(robot, repo, tmp_path):
    """Treating an absent pipeline as 'nothing to check' is how a gate becomes decorative."""
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    robot.stage(["a.txt"])
    with pytest.raises(RefusalError, match="gate did not pass"):
        robot.commit(_msg(tmp_path))
    assert "not found" in robot.audit.read()[-1]["gates"][0]["note"]


def test_commit_message_comes_from_a_file_with_awkward_content(robot, repo, tmp_path,
                                                               fake_gate):
    """Prose contains quotes, backticks, newlines and non-ASCII — every one a quoting
    hazard on the way to a subprocess. A file has no such edge."""
    fake_gate(0)
    text = 'Fix "quoting" & `backticks`\n\nBody with ⊥, σ, c₀ and a $VAR; rm -rf /\n'
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    robot.stage(["a.txt"])
    robot.commit(_msg(tmp_path, text))
    body = robot.read("log", ["-1", "--pretty=%B"])["output"]
    assert "⊥, σ, c₀" in body and '"quoting"' in body and "$VAR" in body


def test_commit_with_nothing_staged_is_refused(robot, tmp_path, fake_gate):
    fake_gate(0)
    with pytest.raises(RefusalError, match="nothing is staged"):
        robot.commit(_msg(tmp_path))


def test_commit_requires_a_non_empty_message_file(robot, repo, tmp_path, fake_gate):
    fake_gate(0)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    robot.stage(["a.txt"])
    with pytest.raises(UsageError, match="empty"):
        robot.commit(_msg(tmp_path, "   \n"))
    with pytest.raises(UsageError, match="not found"):
        robot.commit(str(tmp_path / "nope.txt"))


# -- preflight + push ---------------------------------------------------------

def _commit(robot, repo, tmp_path, name="a.txt"):
    (repo / name).write_text(name, encoding="utf-8")
    robot.stage([name])
    robot.commit(_msg(tmp_path))


def test_push_consults_the_ledger_not_a_preflight_bit(robot, repo, tmp_path,
                                                      fake_gate, ledger_refuses):
    """⚠ THIS REPLACES `test_push_refuses_without_a_preflight`, and the swap is the
    correction rather than an accident of refactoring.

    push used to require a passing `preflight`: a pipeline run reduced to ONE BIT and
    stored in gitRobot's own log. The ledger holds that same fact properly — every
    requirement, per type, bound to the hash, with what it examined. Two mechanisms
    answering one question, and on 2026-08-23 the bit said pass while the ledger said
    0/19. The weaker one is always the one that lets things through.

    It was also gitRobot writing a VERDICT, which §12d forbids. Keeping it out of the
    ledger and putting it in git_ops.jsonl was the same defect in a different store.

    The response window §9 Q2 wanted is not lost: `inventory(hash)` is an instant read
    a caller can make at any time. Re-running a 155s pipeline to manufacture a bit was
    never what provided it.
    """
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    with pytest.raises(RefusalError, match="admission set is not satisfied"):
        robot.push("illustrated", reason="shipping")
    assert robot.read("log", ["origin/illustrated", "--oneline"])["output"].count("\n") == 0


def test_preflight_then_push(robot, repo, tmp_path, fake_gate, ledger_ok):
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    pre = robot.preflight(reason="pre-ship check", wait=True)
    assert pre["passed"] is True and pre["head"] == robot.git.head()
    result = robot.push("illustrated", reason="shipping the fix")
    assert result["decision"] == "allowed" and result["ok"]


def test_a_failing_preflight_does_not_authorise_a_push(robot, repo, tmp_path,
                                                       fake_gate, ledger_refuses):
    """⚠⚠ NAMES A REAL GAP, deliberately. A red pipeline is now blocked because the
    LEDGER reports the keys unsatisfied — not because preflight exited non-zero. That
    only holds once a checker RECORDS its failure. Until the emitters land (§9c step 3)
    a red pipeline that records nothing is indistinguishable from one that never ran,
    and the empty-admission-set refusal is what stands in the gap.
    """
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    fake_gate(1, "BLOCK: check_paths failed")   # the pipeline goes red after the commit
    assert robot.preflight(wait=True)["passed"] is False
    with pytest.raises(RefusalError, match="admission set is not satisfied"):
        robot.push("illustrated", reason="shipping anyway")


def test_a_verdict_does_not_survive_a_later_commit(robot, repo, tmp_path, fake_gate,
                                                   monkeypatch):
    """Bound to the HASH it was recorded against, or one clean run would authorise
    everything that came after it.

    The property is unchanged; it is now enforced by the ledger keying on the hash
    instead of by preflight staleness — which is strictly stricter. It survives a
    restart, and it cannot be satisfied by a run against a DIFFERENT tree that
    happened to leave a green row behind.
    """
    from core import ledger as ledger_client
    fake_gate(0)
    _commit(robot, repo, tmp_path, "a.txt")
    good = robot.git.head()

    def only_good(ref, action, admission=None):
        ok = ref == good
        return {"ok": True, "complete": ok, "ref": ref, "action": action,
                "admitted": ["build"], "admission_state": "SET", "policy_sha": "p",
                "required": 1, "satisfied": 1 if ok else 0,
                "line": "ALLOWED" if ok else "REFUSED  push  0/1 admission keys"}

    monkeypatch.setattr(ledger_client, "inventory", only_good)
    _commit(robot, repo, tmp_path, "b.txt")
    with pytest.raises(RefusalError, match="admission set is not satisfied"):
        robot.push("illustrated", reason="shipping")


def test_push_requires_a_reason(robot, repo, tmp_path, fake_gate):
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    with pytest.raises(RefusalError, match="requires a reason"):
        robot.push("illustrated", reason="")


def test_private_branches_never_reach_a_remote(robot, repo, tmp_path, fake_gate):
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    with pytest.raises(RefusalError, match="not a pushable branch"):
        robot.push("private/scratch", reason="oops")


def test_push_records_what_authorised_it_on_the_clean_path(robot, repo, tmp_path,
                                                           fake_gate, ledger_ok):
    """The whole point of the audit: 'judged clean' and 'never ran' must not be
    indistinguishable afterwards.

    What gets recorded changed with the enforcement point. It used to be the gate
    exit code; it is now the INVENTORY that authorised the push — the hash judged,
    the policy it was judged under, and the admission set in force. That is strictly
    more: a bar that moves later cannot re-interpret a past action, which an exit
    code could never rule out.
    """
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    robot.push("illustrated", reason="shipping")
    record = robot.audit.read()[-1]
    assert record["op"] == "push" and record["decision"] == "allowed"
    assert record["reason"] == "shipping"
    assert record["args"]["inventory_ref"] == robot.git.head()
    assert record["args"]["policy_sha"] == "policy-sha"
    assert record["args"]["admission"] == ["build"]


# -- worktree: the sanctioned escape ------------------------------------------

def test_worktree_add_gives_an_isolated_tree(robot, repo, dirty):
    """The alternative every Tier 1 refusal names actually works, and the caller's
    uncommitted work is untouched by using it."""
    result = robot.worktree("add", ref="HEAD")
    assert result["decision"] == "allowed", result
    from pathlib import Path
    wt = Path(result["path"])
    assert wt.exists() and (wt / "tracked.txt").read_text(encoding="utf-8") == "original\n"
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "PRECIOUS EDIT\n"
    assert (repo / "untracked.txt").exists()

    assert "worktree" in robot.worktree("list")["output"]
    assert robot.worktree("remove", name=str(wt))["decision"] == "allowed"


def test_worktree_remove_refuses_the_main_checkout(robot, repo):
    """The main checkout is the thing every other guard here exists to protect."""
    with pytest.raises(RefusalError, match="main checkout"):
        robot.worktree("remove", name=str(repo))


def test_worktree_remove_refuses_a_path_git_does_not_list(robot, tmp_path):
    stranger = tmp_path / "not-a-worktree"
    stranger.mkdir()
    with pytest.raises(RefusalError, match="not a worktree of this repository"):
        robot.worktree("remove", name=str(stranger))


def test_worktree_lands_outside_the_repository(robot):
    """A worktree inside the tree shows up as untracked content and invites exactly
    the clean/reset reflex Tier 1 refuses."""
    from pathlib import Path
    result = robot.worktree("add", ref="HEAD")
    assert robot.repo not in Path(result["path"]).resolve().parents
