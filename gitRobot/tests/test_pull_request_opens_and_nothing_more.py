"""pull_request: OPEN, STATUS, UPDATE_BODY of our own — and nothing that merges, approves or closes.

⭐ Tim, 2026-10-03: agents had no route to open a PR (the consumer's hook denies `gh`; their GitHub
MCP is read-only), so promoting illustrated -> main meant pasting a draft by hand. This acts on
GitHub AS THE OWNER'S ACCOUNT, so every guard below is about what it must NOT do.

A FAKE `gh` records every argv it receives and answers from a state file, so these tests assert
what WOULD reach GitHub without ever touching it.
"""

import json
import subprocess
import sys

import pytest

from core.errors import ConfigError, RefusalError, UsageError

FAKE = r'''
import json, sys, pathlib
state = pathlib.Path(__file__).with_name("gh_state.json")
log = pathlib.Path(__file__).with_name("gh_calls.jsonl")
s = json.loads(state.read_text())
argv = sys.argv[1:]
with log.open("a") as f:
    f.write(json.dumps(argv) + "\n")
if argv[:2] == ["pr", "list"]:
    print(json.dumps(s.get("list", [])))
elif argv[:2] == ["pr", "create"]:
    print("https://github.com/o/r/pull/%d" % s.get("next", 7))
elif argv[:2] == ["pr", "edit"]:
    print("https://github.com/o/r/pull/%s" % argv[2])
elif argv[:2] == ["pr", "view"]:
    print(json.dumps(s.get("view", {})))
else:
    sys.exit(2)
'''


@pytest.fixture
def gh(robot, tmp_path, monkeypatch):
    fake = tmp_path / "fake_gh.py"
    fake.write_bytes(FAKE.encode())
    state = tmp_path / "gh_state.json"
    state.write_bytes(b"{}")
    monkeypatch.setattr(robot, "gh_argv", [sys.executable, str(fake)])
    monkeypatch.setattr(robot, "_gh_repo", lambda: "o/r")

    class G:
        def set(self, **kw):
            state.write_bytes(json.dumps(kw).encode())

        def calls(self):
            p = tmp_path / "gh_calls.jsonl"
            return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []
    return G()


def _body(tmp_path, text="Promote illustrated to main.\n"):
    p = tmp_path / "body.md"
    p.write_bytes(text.encode())
    return str(p)


def test_open_creates_one_pr_and_returns_its_number(robot, repo, tmp_path, gh):
    out = robot.pull_request("open", reason="promote", head="illustrated", base="main",
                             title="Promote illustrated", body_file=_body(tmp_path))
    assert out["decision"] == "allowed", out
    pr = out["pull_request"]
    assert (pr["number"], pr["url"], pr["opened_now"]) == (7, "https://github.com/o/r/pull/7", True)
    create = [c for c in gh.calls() if c[:2] == ["pr", "create"]]
    assert len(create) == 1
    c = create[0]
    # ⚠ the object: an explicit --repo, the exact head/base, the body from the FILE
    for flag, val in (("--repo", "o/r"), ("--head", "illustrated"), ("--base", "main"),
                      ("--body-file", _body(tmp_path))):
        assert c[c.index(flag) + 1] == val, (flag, c)
    row = [r for r in robot.audit.read() if r["op"] == "pull_request.open"][-1]
    assert row["decision"] == "allowed" and row["args"]["number"] == 7


def test_an_existing_open_pr_is_returned_never_duplicated(robot, repo, tmp_path, gh):
    gh.set(list=[{"number": 3, "url": "https://github.com/o/r/pull/3", "title": "t"}])
    out = robot.pull_request("open", reason="again", head="illustrated", base="main",
                             title="x", body_file=_body(tmp_path))
    assert out["decision"] == "skipped" and out["pull_request"]["number"] == 3
    assert out["pull_request"]["opened_now"] is False
    assert not [c for c in gh.calls() if c[:2] == ["pr", "create"]], "a second PR was created"


def test_a_pair_outside_the_policy_is_refused_before_github_is_asked(robot, repo, tmp_path, gh):
    with pytest.raises(RefusalError) as exc:
        robot.pull_request("open", reason="r", head="side", base="main", title="x",
                           body_file=_body(tmp_path))
    assert "not an allowed pull-request pair" in str(exc.value)
    assert gh.calls() == []


def test_an_unpushed_head_is_refused(robot, repo, tmp_path, gh):
    (repo / "u.txt").write_bytes(b"u")
    subprocess.run(["git", "add", "u.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "local only"], cwd=repo, check=True, capture_output=True)
    with pytest.raises(RefusalError) as exc:
        robot.pull_request("open", reason="r", head="illustrated", base="main", title="x",
                           body_file=_body(tmp_path))
    assert "push(" in str(exc.value)
    assert not [c for c in gh.calls() if c[:2] == ["pr", "create"]]


def test_a_missing_policy_refuses_rather_than_allowing_any_pair(robot, repo, tmp_path, gh,
                                                                monkeypatch):
    monkeypatch.setattr(type(robot), "_PR_CONFIG", tmp_path / "absent.json")
    with pytest.raises(ConfigError):
        robot.pull_request("open", reason="r", head="illustrated", base="main", title="x",
                           body_file=_body(tmp_path))
    assert gh.calls() == []


def test_update_body_only_for_a_pr_this_server_opened(robot, repo, tmp_path, gh):
    with pytest.raises(RefusalError) as exc:
        robot.pull_request("update_body", reason="r", number=99, body_file=_body(tmp_path))
    assert "not opened by this gitRobot" in str(exc.value)
    assert not [c for c in gh.calls() if c[:2] == ["pr", "edit"]]

    robot.pull_request("open", reason="promote", head="illustrated", base="main", title="t",
                       body_file=_body(tmp_path))
    out = robot.pull_request("update_body", reason="refresh", number=7,
                             body_file=_body(tmp_path, "Refreshed.\n"))
    assert out["decision"] == "allowed"
    edit = [c for c in gh.calls() if c[:2] == ["pr", "edit"]][-1]
    assert edit[2] == "7" and edit[edit.index("--repo") + 1] == "o/r"


def test_status_reports_whether_the_pr_head_is_the_local_branch(robot, repo, gh):
    head = robot.git.head()
    gh.set(view={"number": 7, "state": "OPEN", "headRefName": "illustrated",
                 "headRefOid": head, "mergeable": "MERGEABLE"})
    pr = robot.pull_request("status", reason="look", number=7)["pull_request"]
    assert pr["head_matches_local"] is True and pr["local_head"] == head


@pytest.mark.parametrize("verb", ["merge", "approve", "close", "edit"])
def test_there_is_no_merge_approve_close_or_edit(robot, repo, gh, verb):
    """⚠ The MESSAGE is asserted, not just the type: with `merge` admitted past the action check
    the call still raised UsageError — later, for a missing `head` — so a type-only assertion
    passed for the wrong reason (mutant survived 2026-10-03)."""
    with pytest.raises(UsageError) as exc:
        robot.pull_request(verb, reason="r", number=7, head="illustrated", base="main",
                           title="t", body_file="x.md")
    assert "by design" in str(exc.value), str(exc.value)
    assert gh.calls() == []


def test_the_body_must_come_from_a_file(robot, repo, gh):
    with pytest.raises(UsageError):
        robot.pull_request("open", reason="r", head="illustrated", base="main", title="x")
