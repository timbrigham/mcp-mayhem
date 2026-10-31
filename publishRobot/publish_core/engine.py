"""Queue a public GitHub post, and send it only when Tim approves those exact bytes.

⭐ Tim, 2026-10-30/31. The ZeroParadox session is hard-denied every public GitHub write, cut
2026-08-22 because a raw `issue_write` lets an agent skip review. Tim then decided the open
ordinary defects get filed as public `erratum` issues, and expects a lot of follow-up traffic on
them, so pasting each reply by hand does not scale. This server is the sanctioned route.

THE WHOLE CONTROL IS TWO TOOLS AND ONE PERMISSION RULE:

    queue     any agent may call it. Stores the exact payload (target, title, body, labels) and
              its sha256. Posts NOTHING.
    approve   restates the ENTIRE payload as arguments, so the permission prompt Tim sees shows
              exactly what will be posted. The server compares every field with the queued
              copy and refuses on any difference, then posts the stored bytes.
              ⛔ Its protection is NOT in this file. `approve` is served by a SEPARATE server,
              publishApprove, registered `--scope local` for the approving instance only, so a
              drafting session has no such tool at all; and an `ask` rule there makes every call
              prompt Tim. Measured 2026-10-31: an ask rule still prompts in auto mode.
              ⚠ First built on the shared server with "deny it in the drafting sessions". Tim,
              2026-10-31, asked why it was registered device-wide at all: a fence that needs a
              deny rule in every other session is one someone forgets to put up.

⚠ WHY approve TAKES THE PAYLOAD AND NOT JUST THE ID. A prompt that reads `approve(id='q-3f…')`
asks Tim to approve an opaque handle. Taking every field makes the prompt the review surface, and
the equality check makes the prompt honest: an agent that shows him one body and stored another
is refused, because the server compares against the stored copy rather than trusting either.

⛔ OUT OF SCOPE, PERMANENTLY: repo-level writes (commits, branches, PRs, merges, releases),
account writes, and any repository not on the allow-list. Not refused by a check — the verbs do
not exist here. `ACTIONS` is the complete list.

⚠ NOT YET HERE: email (the same queue/approve shape, a later version), and an adversary-review
PASS bound to the bytes. Tim, 2026-10-31: "only thinking approval of the bytes at first."
Adversarial review stays a process rule (his global CLAUDE.md), not a server gate.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from publish_core.errors import ConfigError, RefusalError, UnavailableError, UsageError

if os.name == "nt":
    import msvcrt
else:
    import fcntl

# action -> (fields it REQUIRES, fields it may carry). Every other payload field must be None.
# The complete verb list: a verb absent from this table cannot be queued, approved or posted.
ACTIONS: dict[str, tuple[frozenset, frozenset]] = {
    "issue_create": (frozenset({"title", "body"}), frozenset({"labels"})),
    "issue_comment": (frozenset({"number", "body"}), frozenset()),
    "issue_close": (frozenset({"number", "body"}), frozenset({"state_reason"})),
    "issue_label": (frozenset({"number"}), frozenset({"labels", "remove_labels"})),
    "discussion_create": (frozenset({"title", "body", "category"}), frozenset()),
    "discussion_comment": (frozenset({"number", "body"}), frozenset({"reply_to"})),
}
PAYLOAD_FIELDS = ("action", "repo", "number", "title", "body", "labels", "remove_labels",
                  "category", "reply_to", "state_reason")
STATE_REASONS = ("completed", "not_planned")
# GitHub caps an issue or comment body at 65536 characters.
MAX_BODY = 65536
TRACKER_HEADING = "## Posted via publishRobot"

# ⛔ TWO PROCESSES SHARE THE QUEUE: publishRobot writes `queued`/`withdrawn`, publishApprove
# writes `posting`/`posted`/`failed`. A thread lock covers neither the other process nor a
# withdraw racing an approve, so every read-decide-write runs under an OS file lock as well.
_THREAD_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(payload: dict) -> bytes:
    """The bytes the hash prices: every payload field, sorted keys, no whitespace, UTF-8."""
    return json.dumps({k: payload.get(k) for k in PAYLOAD_FIELDS}, sort_keys=True,
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def digest(payload: dict) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


class Publisher:
    # argv PREFIX for the GitHub CLI; a test points it at a fake. Never a shell string.
    gh_argv: list = ["gh"]

    def __init__(self, data_dir, config_path, tracker_path: Optional[str] = None,
                 actor: str = "mcp"):
        self.data = Path(data_dir)
        self.config_path = Path(config_path)
        self.tracker = Path(tracker_path) if tracker_path else None
        self.actor = actor
        self.queue_file = self.data / "queue.jsonl"
        self.audit_file = self.data / "audit.jsonl"

    # -- config -------------------------------------------------------------------------------

    def allowed_repos(self) -> list:
        """⛔ ABSENT, UNREADABLE OR EMPTY REFUSES. This posts as the owner's account, and "no
        list" must never read as "any repo"."""
        try:
            doc = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            repos = doc["repos"]
            if not (isinstance(repos, list) and all(isinstance(r, str) for r in repos)):
                raise TypeError("`repos` must be a list of owner/name strings")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ConfigError(f"the repo allow-list is unreadable at {self.config_path}: {exc}",
                              f"{self.config_path} must be JSON with `repos`: a non-empty list "
                              f"of owner/name strings")
        if not repos:
            raise ConfigError(f"the repo allow-list at {self.config_path} names no repo",
                              f"add at least one owner/name to `repos` in {self.config_path}")
        return repos

    def _require_tracker(self) -> Path:
        """The tracker is checked BEFORE posting: a post the tracker cannot record is refused
        up front rather than made and then lost from the record."""
        if self.tracker is None:
            raise ConfigError("no outreach tracker is configured, so a post could not be recorded",
                              "set PUBLISHROBOT_TRACKER to the tracker file's path and restart")
        if not self.tracker.is_file():
            raise ConfigError(f"the outreach tracker {self.tracker} does not exist",
                              "point PUBLISHROBOT_TRACKER at an existing file and restart")
        return self.tracker

    # -- storage ------------------------------------------------------------------------------

    # Long enough to wait out an approve that is mid-post (several `gh` calls of up to 60s).
    lock_timeout: float = 180.0

    @contextlib.contextmanager
    def _locked(self):
        self.data.mkdir(parents=True, exist_ok=True)
        with _THREAD_LOCK:
            fh = open(self.data / "queue.lock", "a+b")
            try:
                deadline = time.monotonic() + self.lock_timeout
                while True:
                    try:
                        fh.seek(0)
                        if os.name == "nt":
                            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise UnavailableError(
                                f"the queue has been locked by another process for over "
                                f"{self.lock_timeout:.0f}s",
                                "retry: the other server is most likely mid-post. If it "
                                "persists, check which process holds queue.lock")
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    fh.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()

    def _append(self, path: Path, row: dict) -> None:
        self.data.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")

    def _rows(self, path: Path) -> list:
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_bytes().decode("utf-8").splitlines()
                if line.strip()]

    def _audit(self, op: str, decision: str, *, reason: Optional[str] = None,
               refusal_class: Optional[str] = None, **fields) -> None:
        self._append(self.audit_file, {"at": _now(), "actor": self.actor, "op": op,
                                       "decision": decision, "refusal_class": refusal_class,
                                       "reason": reason, **fields})

    def _entries(self) -> dict:
        """id -> {payload, sha256, state, ...}, folded from the event stream in order."""
        out: dict = {}
        for ev in self._rows(self.queue_file):
            qid = ev["id"]
            if ev["event"] == "queued":
                out[qid] = {"id": qid, "sha256": ev["sha256"], "payload": ev["payload"],
                            "queued_at": ev["at"], "reason": ev.get("reason"),
                            "state": "queued"}
            elif qid in out:
                out[qid]["state"] = ev["event"]
                out[qid][f"{ev['event']}_at"] = ev["at"]
                if "result" in ev:
                    out[qid]["result"] = ev["result"]
        return out

    # -- queue --------------------------------------------------------------------------------

    def _build_payload(self, action, repo, number, title, body, body_file, labels,
                       remove_labels, category, reply_to, state_reason) -> dict:
        if action not in ACTIONS:
            raise UsageError(f"unknown action {action!r}",
                             f"action is one of {sorted(ACTIONS)}. There is no repo-level "
                             f"write (commit, branch, PR, merge, release) by design")
        if body is not None and body_file is not None:
            raise UsageError("both body and body_file were given",
                             "pass exactly one of body or body_file")
        if body_file is not None:
            path = Path(body_file)
            try:
                body = path.read_bytes().decode("utf-8-sig")
            except (OSError, UnicodeDecodeError) as exc:
                raise UsageError(f"body_file {path} could not be read as UTF-8: {exc}",
                                 "pass an existing UTF-8 file, or the text as body")
        payload = {"action": action, "repo": repo, "number": number, "title": title,
                   "body": body, "labels": labels, "remove_labels": remove_labels,
                   "category": category, "reply_to": reply_to, "state_reason": state_reason}
        required, optional = ACTIONS[action]
        for field in required:
            value = payload[field]
            if value is None or (isinstance(value, str) and not value.strip()):
                raise UsageError(f"{action} requires {field}",
                                 f"{action} needs {sorted(required)}; it may also carry "
                                 f"{sorted(optional) or 'nothing else'}")
        stray = [f for f in PAYLOAD_FIELDS[2:]
                 if payload[f] is not None and f not in required | optional]
        if stray:
            raise UsageError(f"{action} does not take {stray}",
                             f"{action} takes {sorted(required | optional)} only")
        if number is not None and not (isinstance(number, int) and number > 0):
            raise UsageError(f"number must be a positive integer, got {number!r}",
                             "pass the issue or discussion number as an integer")
        for name in ("labels", "remove_labels"):
            v = payload[name]
            if v is not None and not (isinstance(v, list) and v
                                      and all(isinstance(x, str) and x.strip() for x in v)):
                raise UsageError(f"{name} must be a non-empty list of label names",
                                 f"pass {name} as a list of strings, or leave it out")
        if action == "issue_label" and not (labels or remove_labels):
            raise UsageError("issue_label changes nothing without labels or remove_labels",
                             "pass labels to add, remove_labels to remove, or both")
        if state_reason is not None and state_reason not in STATE_REASONS:
            raise UsageError(f"state_reason must be one of {STATE_REASONS}",
                             f"pass state_reason as one of {STATE_REASONS}, or leave it out")
        if body is not None and len(body) > MAX_BODY:
            raise UsageError(f"body is {len(body)} characters; GitHub caps it at {MAX_BODY}",
                             f"shorten the body to at most {MAX_BODY} characters")
        return payload

    def _check_repo(self, op: str, repo: str, **audit_fields) -> None:
        allowed = self.allowed_repos()
        if repo not in allowed:
            exc = RefusalError(f"{repo!r} is not on the allow-list in {self.config_path.name}",
                               f"target one of {allowed}. Adding a repo is an edit to "
                               f"{self.config_path.name}, which is the owner's decision",
                               refusal_class="policy")
            self._audit(op, "refused", refusal_class="policy", repo=repo, detail=str(exc),
                        **audit_fields)
            raise exc

    def queue(self, action: str, repo: str, reason: str, *, number: Optional[int] = None,
              title: Optional[str] = None, body: Optional[str] = None,
              body_file: Optional[str] = None, labels: Optional[list] = None,
              remove_labels: Optional[list] = None, category: Optional[str] = None,
              reply_to: Optional[str] = None, state_reason: Optional[str] = None) -> dict:
        """Store the payload and its hash. Posts nothing."""
        if not (isinstance(reason, str) and reason.strip()):
            raise UsageError("queue requires a reason",
                             "pass reason: why this post is being made")
        payload = self._build_payload(action, repo, number, title, body, body_file, labels,
                                      remove_labels, category, reply_to, state_reason)
        with self._locked():
            self._check_repo("queue", repo, action=action)
            sha = digest(payload)
            qid = "q-" + sha[:16]
            existing = self._entries().get(qid)
            if existing is not None:
                # The same bytes again. Return the existing entry rather than a second one, so a
                # retried queue call can never become two posts.
                self._audit("queue", "skipped", reason=reason, id=qid, action=action, repo=repo,
                            detail=f"already in the queue as {existing['state']}")
                return {"op": "queue", "decision": "skipped", "id": qid, "sha256": sha,
                        "state": existing["state"], "payload": existing["payload"]}
            self._append(self.queue_file, {"event": "queued", "id": qid, "sha256": sha,
                                           "payload": payload, "at": _now(), "reason": reason})
            self._audit("queue", "allowed", reason=reason, id=qid, action=action, repo=repo,
                        sha256=sha)
        return {"op": "queue", "decision": "allowed", "id": qid, "sha256": sha,
                "state": "queued", "payload": payload,
                "next": "approve(...) with this id and every payload field exactly as shown"}

    # -- approve ------------------------------------------------------------------------------

    def approve(self, id: str, action: str, repo: str, *, number: Optional[int] = None,
                title: Optional[str] = None, body: Optional[str] = None,
                labels: Optional[list] = None, remove_labels: Optional[list] = None,
                category: Optional[str] = None, reply_to: Optional[str] = None,
                state_reason: Optional[str] = None) -> dict:
        """Post the queued payload, if and only if every field given here equals it."""
        shown = {"action": action, "repo": repo, "number": number, "title": title, "body": body,
                 "labels": labels, "remove_labels": remove_labels, "category": category,
                 "reply_to": reply_to, "state_reason": state_reason}
        with self._locked():
            entry = self._entries().get(id)
            if entry is None:
                self._audit("approve", "refused", refusal_class="operational", id=id,
                            detail="unknown id")
                raise UsageError(f"no queued entry {id!r}",
                                 "approve an id that queue() returned and pending() lists")
            if entry["state"] != "queued":
                where = (entry.get("result") or {}).get("url")
                exc = RefusalError(
                    f"{id} is {entry['state']}, not queued" + (f" ({where})" if where else ""),
                    "an entry is approved once. A `posting` entry did not resolve: check GitHub "
                    "for the post before queueing it again. A `failed` or `withdrawn` one is "
                    "re-queued as a new entry",
                    refusal_class="operational")
                self._audit("approve", "refused", refusal_class="operational", id=id,
                            detail=str(exc))
                raise exc
            stored = entry["payload"]
            differ = [f for f in PAYLOAD_FIELDS if shown.get(f) != stored.get(f)]
            if differ:
                exc = RefusalError(
                    f"the approved {differ} differ from what {id} queued",
                    "approve exactly what was queued: pending() shows every field. To post "
                    "something different, queue it as a new entry and approve that",
                    refusal_class="policy")
                self._audit("approve", "refused", refusal_class="policy", id=id,
                            fields_differing=differ, detail=str(exc))
                raise exc
            if digest(stored) != entry["sha256"]:
                exc = RefusalError(
                    f"{id}'s stored payload no longer matches its queued hash",
                    f"the queue file was edited out of band. Inspect {self.queue_file}; "
                    f"re-queue the post rather than approving this entry",
                    refusal_class="policy")
                self._audit("approve", "refused", refusal_class="policy", id=id, detail=str(exc))
                raise exc
            self._check_repo("approve", stored["repo"], id=id, action=stored["action"])
            tracker = self._require_tracker()
            # `posting` BEFORE the network call. A crash between here and `posted` leaves an
            # entry no approve will touch again, so it cannot become two posts.
            self._append(self.queue_file, {"event": "posting", "id": id, "at": _now()})
            self._audit("approve", "started", id=id, action=stored["action"],
                        repo=stored["repo"], sha256=entry["sha256"])
            ok, result = self._post(stored)
            self._append(self.queue_file, {"event": "posted" if ok else "failed", "id": id,
                                           "at": _now(), "result": result})
            self._audit("approve", "allowed" if ok else "failed", id=id,
                        action=stored["action"], repo=stored["repo"], result=result)
        tracked = self._track(tracker, id, stored, result) if ok else None
        return {"op": "approve", "decision": "allowed" if ok else "failed", "id": id,
                "sha256": entry["sha256"], "result": result, "tracker": tracked}

    def withdraw(self, id: str, reason: str) -> dict:
        if not (isinstance(reason, str) and reason.strip()):
            raise UsageError("withdraw requires a reason", "pass reason: why it is withdrawn")
        with self._locked():
            entry = self._entries().get(id)
            if entry is None or entry["state"] != "queued":
                state = entry["state"] if entry else "unknown"
                self._audit("withdraw", "refused", refusal_class="operational", id=id,
                            reason=reason, detail=state)
                raise UsageError(f"{id!r} is {state}, so there is nothing to withdraw",
                                 "withdraw an id that pending() lists as queued")
            self._append(self.queue_file, {"event": "withdrawn", "id": id, "at": _now(),
                                           "reason": reason})
            self._audit("withdraw", "allowed", id=id, reason=reason)
        return {"op": "withdraw", "decision": "allowed", "id": id}

    # -- reads --------------------------------------------------------------------------------

    def pending(self) -> dict:
        entries = [e for e in self._entries().values() if e["state"] in ("queued", "posting")]
        return {"entries": entries, "count": len(entries)}

    def history(self, limit: int = 20) -> dict:
        rows = self._rows(self.audit_file)
        return {"rows": rows[-limit:] if limit > 0 else rows, "total": len(rows)}

    # -- GitHub -------------------------------------------------------------------------------

    def _gh(self, args: list, request: Optional[dict] = None,
            timeout: int = 60) -> tuple[bool, Any, str]:
        """Run `gh api`, sending `request` as the JSON body from a file of exact bytes.

        ⚠ A FILE, NOT `-f body=...`. `-F` coerces values that look like numbers or booleans,
        and argv on Windows re-quotes; a body file is the only route that sends the stored bytes
        unchanged."""
        tmp = None
        argv = [*self.gh_argv, "api", *args]
        try:
            if request is not None:
                fd, tmp = tempfile.mkstemp(prefix="publishrobot-", suffix=".json")
                with os.fdopen(fd, "wb") as fh:
                    fh.write(json.dumps(request, ensure_ascii=False).encode("utf-8"))
                argv += ["--input", tmp]
            env = {**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
            res = subprocess.run(argv, capture_output=True, timeout=timeout, env=env,
                                 shell=False)
        except FileNotFoundError:
            return False, None, "the GitHub CLI (`gh`) is not installed or not on PATH"
        except subprocess.TimeoutExpired:
            return False, None, f"gh api {args[:1]} timed out after {timeout}s"
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        out = res.stdout.decode("utf-8", "replace")
        err = res.stderr.decode("utf-8", "replace")
        if res.returncode != 0:
            return False, None, (err or out)[-800:]
        try:
            return True, (json.loads(out) if out.strip() else None), ""
        except ValueError:
            return False, None, f"gh returned non-JSON: {out[-300:]}"

    def _graphql(self, query: str, variables: dict) -> tuple[bool, Any, str]:
        ok, data, err = self._gh(["graphql"], {"query": query, "variables": variables})
        if ok and isinstance(data, dict) and data.get("errors"):
            return False, None, json.dumps(data["errors"])[-800:]
        return ok, (data or {}).get("data") if ok else None, err

    def _post(self, p: dict) -> tuple[bool, dict]:
        """Perform the post. Returns (ok, result); result always says what happened, including
        the half of a two-step action that DID land when the second half failed."""
        repo, n, action = p["repo"], p["number"], p["action"]
        if action == "issue_create":
            req = {"title": p["title"], "body": p["body"]}
            if p["labels"]:
                req["labels"] = p["labels"]
            ok, data, err = self._gh(["-X", "POST", f"repos/{repo}/issues"], req)
            if not ok:
                return False, {"error": err}
            return True, {"url": data["html_url"], "number": data["number"]}

        if action in ("issue_comment", "issue_close"):
            ok, data, err = self._gh(["-X", "POST", f"repos/{repo}/issues/{n}/comments"],
                                     {"body": p["body"]})
            if not ok:
                return False, {"error": err}
            result = {"url": data["html_url"], "number": n, "comment_id": data["id"]}
            if action == "issue_comment":
                return True, result
            req = {"state": "closed"}
            if p["state_reason"]:
                req["state_reason"] = p["state_reason"]
            ok, _, err = self._gh(["-X", "PATCH", f"repos/{repo}/issues/{n}"], req)
            if not ok:
                return False, {**result, "error": f"comment posted, close FAILED: {err}"}
            return True, {**result, "closed": True}

        if action == "issue_label":
            result: dict = {"url": f"https://github.com/{repo}/issues/{n}", "number": n}
            if p["labels"]:
                ok, _, err = self._gh(["-X", "POST", f"repos/{repo}/issues/{n}/labels"],
                                      {"labels": p["labels"]})
                if not ok:
                    return False, {**result, "error": err}
                result["added"] = p["labels"]
            for name in p["remove_labels"] or []:
                ok, _, err = self._gh(["-X", "DELETE", f"repos/{repo}/issues/{n}/labels/"
                                       + urllib.parse.quote(name, safe="")])
                if not ok:
                    return False, {**result, "error": f"removing {name!r} failed: {err}"}
                result.setdefault("removed", []).append(name)
            return True, result

        owner, name = repo.split("/", 1)
        if action == "discussion_create":
            ok, data, err = self._graphql(
                "query($o:String!,$n:String!){repository(owner:$o,name:$n){id "
                "discussionCategories(first:50){nodes{id name}}}}", {"o": owner, "n": name})
            if not ok:
                return False, {"error": err}
            cats = {c["name"]: c["id"]
                    for c in data["repository"]["discussionCategories"]["nodes"]}
            if p["category"] not in cats:
                return False, {"error": f"no discussion category {p['category']!r}; "
                                        f"{repo} has {sorted(cats)}"}
            ok, data, err = self._graphql(
                "mutation($r:ID!,$c:ID!,$t:String!,$b:String!){createDiscussion(input:"
                "{repositoryId:$r,categoryId:$c,title:$t,body:$b}){discussion{number url}}}",
                {"r": data["repository"]["id"], "c": cats[p["category"]], "t": p["title"],
                 "b": p["body"]})
            if not ok:
                return False, {"error": err}
            d = data["createDiscussion"]["discussion"]
            return True, {"url": d["url"], "number": d["number"]}

        # discussion_comment
        ok, data, err = self._graphql(
            "query($o:String!,$n:String!,$d:Int!){repository(owner:$o,name:$n)"
            "{discussion(number:$d){id}}}", {"o": owner, "n": name, "d": n})
        if not ok or not (data.get("repository") or {}).get("discussion"):
            return False, {"error": err or f"no discussion #{n} in {repo}"}
        variables = {"d": data["repository"]["discussion"]["id"], "b": p["body"]}
        if p["reply_to"]:
            variables["r"] = p["reply_to"]
            mutation = ("mutation($d:ID!,$b:String!,$r:ID!){addDiscussionComment(input:"
                        "{discussionId:$d,body:$b,replyToId:$r}){comment{url}}}")
        else:
            mutation = ("mutation($d:ID!,$b:String!){addDiscussionComment(input:"
                        "{discussionId:$d,body:$b}){comment{url}}}")
        ok, data, err = self._graphql(mutation, variables)
        if not ok:
            return False, {"error": err}
        return True, {"url": data["addDiscussionComment"]["comment"]["url"], "number": n}

    # -- tracker ------------------------------------------------------------------------------

    def _track(self, tracker: Path, qid: str, p: dict, result: dict) -> dict:
        """Append one line to the outreach tracker. The post has ALREADY happened here, so a
        failure is reported, never raised: raising would turn a successful post into an error
        the caller retries, and a retry is a second post."""
        line = (f"- {_now()} {p['action']} {p['repo']}#{result.get('number')}: "
                f"{result.get('url')} (publishRobot {qid})\n")
        try:
            text = tracker.read_bytes().decode("utf-8")
            add = ""
            if TRACKER_HEADING not in text:
                add += ("" if text.endswith("\n") else "\n") + f"\n{TRACKER_HEADING}\n\n"
            with tracker.open("ab") as fh:
                fh.write((add + line).encode("utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            self._audit("track", "failed", id=qid, detail=str(exc), line=line)
            return {"written": False, "error": str(exc), "line": line}
        return {"written": True, "path": str(tracker), "line": line}
