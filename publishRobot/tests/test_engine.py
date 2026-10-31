"""Controls for publishRobot. Each refusal is checked to refuse AND to leave GitHub untouched:
a refusal that still reached `gh` would read as a control that held."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

from publish_core.engine import ACTIONS, PAYLOAD_FIELDS, TRACKER_HEADING, Publisher
from publish_core.errors import ConfigError, RefusalError, UsageError

REPO = "timbrigham/ZeroParadox"
FAKE = Path(__file__).with_name("fake_gh.py")
# CRLF, a trailing newline, non-ASCII, quotes, a leading space, an @mention, a backslash: the
# bytes most likely to be "helpfully" changed somewhere between the queue and GitHub.
TRICKY = ' @a-reader, thank you.\r\n\r\n"ℕ → Part" \\ ✓\n'


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "publish.v1.json"
    cfg.write_text(json.dumps({"repos": [REPO]}), encoding="utf-8")
    tracker = tmp_path / "tracker.md"
    tracker.write_bytes(b"# Tracker\n\nexisting line\n")
    log = tmp_path / "gh.jsonl"
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    monkeypatch.delenv("FAKE_GH_FAIL", raising=False)
    pub = Publisher(tmp_path / "data", cfg, tracker_path=str(tracker))
    pub.gh_argv = [sys.executable, str(FAKE)]

    class E:
        pass
    e = E()
    e.pub, e.cfg, e.tracker, e.log, e.tmp = pub, cfg, tracker, log, tmp_path
    e.calls = lambda: ([json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
                       if log.exists() else [])
    return e


def _fields(queued: dict) -> dict:
    p = dict(queued["payload"])
    return {k: p[k] for k in PAYLOAD_FIELDS}


def _approve(pub, queued, **override):
    f = {**_fields(queued), **override}
    return pub.approve(queued["id"], f.pop("action"), f.pop("repo"), **f)


def _comment(pub, body=TRICKY, number=7):
    return pub.queue("issue_comment", REPO, "reply to a reader", number=number, body=body)


def _state(pub, qid):
    return pub._entries()[qid]["state"]


# -- the correct path -------------------------------------------------------------------------

def test_approved_bytes_are_the_bytes_posted(env):
    q = _comment(env.pub)
    assert env.calls() == []                                   # queue posts nothing
    out = _approve(env.pub, q)
    assert out["decision"] == "allowed"
    assert out["result"]["url"].endswith("/issues/7#issuecomment-1")
    calls = env.calls()
    assert len(calls) == 1 and calls[0]["method"] == "POST"
    sent = json.loads(base64.b64decode(calls[0]["body_b64"]).decode("utf-8"))
    assert sent == {"body": TRICKY}                            # byte-exact, CRLF and all
    assert _state(env.pub, q["id"]) == "posted"
    text = env.tracker.read_text(encoding="utf-8")
    assert text.startswith("# Tracker\n\nexisting line\n")    # appended, nothing rewritten
    assert TRACKER_HEADING in text and out["result"]["url"] in text
    assert out["tracker"]["written"] is True


def test_every_action_posts_on_approval(env):
    cases = [
        ("issue_create", dict(title="Erratum: ZP-B §3", body="x", labels=["erratum"])),
        ("issue_comment", dict(number=3, body="x")),
        ("issue_close", dict(number=3, body="fixed", state_reason="completed")),
        ("issue_label", dict(number=3, labels=["erratum"], remove_labels=["triage"])),
        ("discussion_create", dict(title="t", body="b", category="Errata")),
        ("discussion_comment", dict(number=142, body="b", reply_to="DC_abc")),
    ]
    assert {c[0] for c in cases} == set(ACTIONS)
    for action, kw in cases:
        q = env.pub.queue(action, REPO, "test", **kw)
        out = _approve(env.pub, q)
        assert out["decision"] == "allowed", (action, out)
        assert out["result"].get("url"), action
    lines = [ln for ln in env.tracker.read_text(encoding="utf-8").splitlines()
             if "publishRobot q-" in ln]
    assert len(lines) == len(cases)
    assert env.tracker.read_text(encoding="utf-8").count(TRACKER_HEADING) == 1


# -- control 1: edited after queueing ---------------------------------------------------------

@pytest.mark.parametrize("override", [
    {"body": TRICKY + " "},
    {"body": TRICKY.replace("\r\n", "\n")},
    {"number": 8},
    {"repo": "timbrigham/other"},
    {"action": "issue_close"},
])
def test_approval_differing_from_the_queue_is_refused(env, override):
    q = _comment(env.pub)
    with pytest.raises(RefusalError) as ei:
        _approve(env.pub, q, **override)
    assert ei.value.refusal_class == "policy"
    assert env.calls() == []
    assert _state(env.pub, q["id"]) == "queued"


def test_tampered_queue_file_is_refused(env):
    q = _comment(env.pub, body="original")
    qf = env.pub.queue_file
    qf.write_bytes(qf.read_bytes().replace(b'"original"', b'"swapped"'))
    with pytest.raises(RefusalError, match="hash"):
        _approve(env.pub, q, body="swapped")
    assert env.calls() == []


# -- control 3: no approval -------------------------------------------------------------------

def test_queue_alone_never_posts(env):
    for n in range(1, 4):
        _comment(env.pub, number=n)
    env.pub.pending()
    env.pub.history()
    assert env.calls() == []
    assert env.pub.pending()["count"] == 3


# -- control 4: a repo off the allow-list ------------------------------------------------------

def test_foreign_repo_is_refused_at_queue(env):
    with pytest.raises(RefusalError):
        env.pub.queue("issue_comment", "GuardianEngineAI/corpus", "x", number=8, body="b")
    assert env.calls() == []


def test_repo_removed_from_allow_list_after_queueing_is_refused(env):
    q = _comment(env.pub)
    env.cfg.write_text(json.dumps({"repos": ["timbrigham/other"]}), encoding="utf-8")
    with pytest.raises(RefusalError):
        _approve(env.pub, q)
    assert env.calls() == []


@pytest.mark.parametrize("content", [None, "not json", '{"repos": []}', '{"repos": "x"}', "{}"])
def test_unreadable_allow_list_refuses(env, content):
    q = _comment(env.pub)
    if content is None:
        env.cfg.unlink()
    else:
        env.cfg.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError):
        _approve(env.pub, q)
    with pytest.raises(ConfigError):
        _comment(env.pub, number=99)
    assert env.calls() == []


# -- control 5: repo-level writes do not exist ------------------------------------------------

def test_the_verb_list_is_exactly_these():
    """A ratchet: adding a verb fails here, so widening the surface is a decision, not a drift."""
    assert set(ACTIONS) == {"issue_create", "issue_comment", "issue_close", "issue_label",
                            "discussion_create", "discussion_comment"}


@pytest.mark.parametrize("verb", ["commit", "push", "pr_create", "pr_merge", "release_create",
                                  "branch_delete", "repo_delete", "issue_delete"])
def test_repo_write_verbs_are_refused(env, verb):
    with pytest.raises(UsageError):
        env.pub.queue(verb, REPO, "x", body="b")
    assert env.calls() == []


# -- once, and only once ----------------------------------------------------------------------

def test_an_entry_posts_once(env):
    q = _comment(env.pub)
    _approve(env.pub, q)
    with pytest.raises(RefusalError):
        _approve(env.pub, q)
    assert len(env.calls()) == 1


def test_requeueing_the_same_bytes_returns_the_same_entry(env):
    a, b = _comment(env.pub), _comment(env.pub)
    assert a["id"] == b["id"] and b["decision"] == "skipped"
    assert env.pub.pending()["count"] == 1


def test_withdrawn_entry_cannot_be_approved(env):
    q = _comment(env.pub)
    env.pub.withdraw(q["id"], "changed my mind")
    with pytest.raises(RefusalError):
        _approve(env.pub, q)
    assert env.calls() == []


def test_stuck_posting_entry_is_not_retried(env):
    q = _comment(env.pub)
    env.pub._append(env.pub.queue_file, {"event": "posting", "id": q["id"], "at": "x"})
    with pytest.raises(RefusalError, match="posting"):
        _approve(env.pub, q)
    assert env.calls() == []
    assert env.pub.pending()["entries"][0]["state"] == "posting"


# -- failures ---------------------------------------------------------------------------------

def test_missing_tracker_refuses_before_posting(env):
    q = _comment(env.pub)
    env.tracker.unlink()
    with pytest.raises(ConfigError):
        _approve(env.pub, q)
    assert env.calls() == [] and _state(env.pub, q["id"]) == "queued"


def test_unconfigured_tracker_refuses_before_posting(env):
    q = _comment(env.pub)
    env.pub.tracker = None
    with pytest.raises(ConfigError):
        _approve(env.pub, q)
    assert env.calls() == []


def test_github_failure_is_failed_and_not_retryable(env, monkeypatch):
    q = _comment(env.pub)
    monkeypatch.setenv("FAKE_GH_FAIL", "comments")
    out = _approve(env.pub, q)
    assert out["decision"] == "failed" and "422" in out["result"]["error"]
    assert out["tracker"] is None
    assert "publishRobot" not in env.tracker.read_text(encoding="utf-8")
    monkeypatch.delenv("FAKE_GH_FAIL")
    with pytest.raises(RefusalError):
        _approve(env.pub, q)
    assert len(env.calls()) == 1


def test_close_reports_the_comment_that_landed_when_the_close_fails(env, monkeypatch):
    q = env.pub.queue("issue_close", REPO, "x", number=5, body="fixed")
    monkeypatch.setenv("FAKE_GH_FAIL", "PATCH")
    out = _approve(env.pub, q)
    assert out["decision"] == "failed"
    assert out["result"]["url"].endswith("#issuecomment-1")
    assert "close FAILED" in out["result"]["error"]


def test_unknown_discussion_category_fails_without_posting(env):
    q = env.pub.queue("discussion_create", REPO, "x", title="t", body="b", category="Nope")
    out = _approve(env.pub, q)
    assert out["decision"] == "failed" and "Errata" in out["result"]["error"]
    assert not any("createDiscussion" in base64.b64decode(c["body_b64"]).decode()
                   for c in env.calls() if c["body_b64"])


# -- shape of a queue call --------------------------------------------------------------------

@pytest.mark.parametrize("action,kw", [
    ("issue_comment", dict(body="b")),                         # no number
    ("issue_comment", dict(number=1, body="  ")),              # blank body
    ("issue_comment", dict(number=1, body="b", title="t")),    # stray field
    ("issue_create", dict(title="t", body="b", labels=[])),    # empty labels
    ("issue_label", dict(number=1)),                           # changes nothing
    ("issue_close", dict(number=1, body="b", state_reason="wontfix")),
    ("issue_comment", dict(number=0, body="b")),
    ("issue_comment", dict(number=1, body="x" * 65537)),
])
def test_malformed_queue_calls_are_refused(env, action, kw):
    with pytest.raises(UsageError):
        env.pub.queue(action, REPO, "x", **kw)
    assert env.pub.pending()["count"] == 0


def test_body_file_is_read_as_utf8_without_bom(env):
    f = env.tmp / "draft.md"
    f.write_bytes(b"\xef\xbb\xbf" + TRICKY.encode("utf-8"))
    q = env.pub.queue("issue_comment", REPO, "x", number=1, body_file=str(f))
    assert q["payload"]["body"] == TRICKY


# -- the queue is shared by two processes -----------------------------------------------------

_HOLDER = """
import sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from publish_core.engine import Publisher
p = Publisher(sys.argv[2], sys.argv[3])
with p._locked():
    Path(sys.argv[4]).write_text("held")
    time.sleep(float(sys.argv[5]))
"""


def _hold_lock(env, seconds):
    import subprocess
    import time
    flag = env.tmp / "held.flag"
    child = subprocess.Popen([sys.executable, "-c", _HOLDER, str(Path(__file__).parents[1]),
                              str(env.pub.data), str(env.cfg), str(flag), str(seconds)])
    deadline = time.monotonic() + 20
    while not flag.exists():
        assert child.poll() is None and time.monotonic() < deadline, "holder never locked"
        time.sleep(0.02)
    return child


def test_another_process_holding_the_queue_blocks_a_write(env):
    from publish_core.errors import UnavailableError
    q = _comment(env.pub)
    child = _hold_lock(env, 5)
    try:
        env.pub.lock_timeout = 0.5
        with pytest.raises(UnavailableError):
            env.pub.withdraw(q["id"], "racing")
        with pytest.raises(UnavailableError):
            _approve(env.pub, q)
    finally:
        child.wait()
    assert env.calls() == [] and _state(env.pub, q["id"]) == "queued"


def test_a_write_waits_for_the_other_process_then_proceeds(env):
    q = _comment(env.pub)
    child = _hold_lock(env, 1)
    try:
        env.pub.lock_timeout = 20
        assert _approve(env.pub, q)["decision"] == "allowed"
    finally:
        child.wait()


# -- audit ------------------------------------------------------------------------------------

def test_every_attempt_is_audited(env):
    q = _comment(env.pub)
    with pytest.raises(RefusalError):
        _approve(env.pub, q, body="other")
    with pytest.raises(RefusalError):
        env.pub.queue("issue_comment", "a/b", "x", number=1, body="b")
    _approve(env.pub, q)
    rows = env.pub.history(0)["rows"]
    got = [(r["op"], r["decision"]) for r in rows]
    assert got == [("queue", "allowed"), ("approve", "refused"), ("queue", "refused"),
                   ("approve", "started"), ("approve", "allowed")]
    assert all(r["refusal_class"] for r in rows if r["decision"] == "refused")
