"""Who is calling: the surface (MCP or CLI) and, over MCP, the session. Read by every audit row.

Added 2026-10-09 so audit rows can be attributed. Before this, a row said what happened but not
through which surface or in which client session, so two agents working at once could not be
told apart afterwards.

Both values are context variables, set once at the entry point (the MCP tool wrapper, the CLI's
`main`) and read by `AuditLog.append`, so no call site has to pass them. `None` is written
explicitly when a value is unknown (the CLI has no session; a library caller sets no surface):
an absent key and an unknown value are different facts.

Context variables do not follow a plain `threading.Thread`. Work handed to a background thread
must be started through `run_in_thread_context`, or its rows lose the attribution.
"""

from __future__ import annotations

import contextvars
from typing import Optional

SURFACE: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("gitrobot_surface",
                                                                         default=None)
SESSION: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("gitrobot_session",
                                                                         default=None)
# The MCP client's self-reported (name, version) from its initialize handshake; (None, None)
# for the CLI, the server's own work, or a client that did not say.
CLIENT: contextvars.ContextVar[tuple] = contextvars.ContextVar("gitrobot_client",
                                                              default=(None, None))

# The client's own id for the call being served, from the request's `_meta` (core/calls.py),
# so an audit row can be traced to the agent that made the call. Added 2026-10-15: one MCP
# session can carry hundreds of subagents, and the session id cannot tell them apart.
CALL_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("gitrobot_call_id",
                                                                         default=None)

# "internal" is work the server starts itself, such as the hourly worktree reaper: the caller
# is known, so it must not read like an unknown library caller (null).
SURFACES = ("mcp", "cli", "internal")


def set_caller(surface: str, session: Optional[str] = None,
               client: tuple = (None, None), call_id: Optional[str] = None) -> None:
    if surface not in SURFACES:
        raise ValueError(f"unknown surface {surface!r}; expected one of {SURFACES}")
    SURFACE.set(surface)
    SESSION.set(session)
    CLIENT.set(tuple(client))
    CALL_ID.set(call_id)


def current() -> dict:
    name, version = CLIENT.get()
    return {"surface": SURFACE.get(), "session": SESSION.get(),
            "client_call_id": CALL_ID.get(),
            "versions": {**_running(), "client_name": name, "client_version": version,
                         # Not observable from here: the consumer's hooks run in the agent's
                         # own tool calls, which never pass through gitRobot. Always null.
                         "consumer_hook_commit": None}}


_RUNNING: Optional[dict] = None


def _running() -> dict:
    """What code this process is running, read ONCE, when this module is first imported (see the
    call at the bottom of the module), so it describes the code that was loaded rather than the
    repository at the time of some later request.

      gitrobot_commit  HEAD of the repository gitRobot was loaded from (mcp-mayhem as a whole)
      gitrobot_dirty   whether gitRobot/ or mcpcommon/ (which it imports) differed from that
                       commit at load time, untracked files included: a process started from an
                       uncommitted tree runs code that exists in no revision
    Both null when git cannot say."""
    global _RUNNING
    if _RUNNING is None:
        from pathlib import Path
        _RUNNING = _probe(Path(__file__).resolve().parents[1])     # gitRobot/
    return dict(_RUNNING)


def _probe(here, scope=(".", "../mcpcommon")) -> dict:
    """The commit at `here` and whether the `scope` paths (relative to `here`) differ from it."""
    import os
    import subprocess
    # An inherited GIT_DIR / GIT_WORK_TREE would make git ignore `cwd` and describe a different
    # repository, so they are stripped: the answer must be about `here`.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    def git(*a):
        try:
            r = subprocess.run(["git", *a], cwd=here, capture_output=True, text=True,
                               timeout=30, env=env)
            return r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
            return None
    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--", *scope)
    return {"gitrobot_commit": commit,
            "gitrobot_dirty": None if commit is None or status is None else bool(status)}


def run_in_thread_context(target):
    """Wrap `target` so a thread runs it inside a copy of the caller's context."""
    ctx = contextvars.copy_context()
    return lambda *a, **kw: ctx.run(target, *a, **kw)


# Read at import, i.e. when the code is loaded. See `_running`.
_running()
