# publishRobot

Public GitHub posts — issues, comments, labels, close-with-comment, discussions — on
allow-listed repositories, queued by an agent and **sent only when a human approves the exact
bytes**.

## Why

The ZeroParadox session is denied every public GitHub write, deliberately: a raw `issue_write`
lets an agent publish without review. Once its open defects were to be filed as public
`erratum` issues, with real follow-up traffic expected, pasting every reply by hand stopped
scaling. This server is the sanctioned route.

## The flow

    queue(action, repo, ..., body | body_file, reason)   any agent. Stores payload + sha256.
                                                         POSTS NOTHING.
    pending()                                            every queued entry, full payload.
    approve(id, action, repo, ...every field...)         publishApprove only. Posts, if every
                                                         field equals the queued copy. Once.
    withdraw(id, reason)                                 a queued entry can never be approved.
    history(limit)                                       one audit row per attempt.

`approve` restates the whole payload because **its arguments are what the approving human
reads in the permission prompt**. The server compares each one with the stored copy and
refuses on any difference, so what is shown is what is posted. Changed text is a new queue
entry and a new approval, never an old approval reused.

Actions: `issue_create`, `issue_comment`, `issue_close`, `issue_label`, `discussion_create`,
`discussion_comment`. That is the complete list; there are no repo-level writes (commits,
branches, PRs, merges, releases) and a test fails if a verb is added.

## Two servers, one queue

    publishRobot     :8012   queue, pending, withdraw, history   registered DEVICE-WIDE
    publishApprove   :8013   approve                             registered for ONE instance

Approval lives on its own server so that drafting sessions simply do not have it. The first
version served `approve` from the shared server and relied on a `deny` rule in every drafting
session; a fence that each other session must remember to put up is one that gets forgotten.

Both read the same `PUBLISHROBOT_*` environment, so they share one queue directory, and every
queue read-decide-write runs under an OS file lock (`queue.lock`) so a withdraw cannot race an
approve across the two processes.

## What makes approval hold — and it is not in this repository

- **registration scope:** `claude mcp add --transport http --scope local publishApprove
  http://127.0.0.1:8013/mcp`, run from the approving instance's project only.
- **an `ask` rule** for `mcp__publishApprove__approve` there, so every call prompts the human.
  Measured 2026-10-31: an ask rule still prompts while that session is in auto mode.

HTTP rather than stdio, deliberately: stdio has been unreliable here. The port is reachable by
local processes, which this fleet's threat model does not defend against.

## Fails closed

Each of these refuses before anything reaches GitHub, and the refusal says what would satisfy
it: an allow-list that is absent, unreadable or empty; a repo not on it (checked at queue
and again at approve); approved fields that differ from the queue; a queue file edited out of
band (hash mismatch); an entry already posted, withdrawn, failed, or stuck mid-post; no
tracker configured, or the file missing.

A GitHub failure is recorded as `failed` and the entry cannot be re-approved: re-queue it. A
two-step action reports the half that landed (`issue_close` whose comment posted and whose
close did not).

## Configuration

    PUBLISHROBOT_TRACKER   the outreach tracker; one line is appended per post. Required.
    PUBLISHROBOT_DATA      queue.jsonl + audit.jsonl (default ./data, gitignored)
    PUBLISHROBOT_CONFIG    the allow-list (default ./config/publish.v1.json)
    PUBLISHROBOT_PORT      default 8012 (publishRobot)
    PUBLISHAPPROVE_PORT    default 8013 (publishApprove)

Posts go through `gh api` as the account `gh` is logged in as, with the request body sent
from a file so the stored bytes are the bytes sent.

## Not yet

- email, on the same queue/approve shape;
- a server-checked adversary-review PASS bound to the bytes (review is a process rule today).

## Tests

    python -m pytest -q
