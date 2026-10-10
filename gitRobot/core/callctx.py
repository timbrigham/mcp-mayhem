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

# "internal" is work the server starts itself, such as the hourly worktree reaper: the caller
# is known, so it must not read like an unknown library caller (null).
SURFACES = ("mcp", "cli", "internal")


def set_caller(surface: str, session: Optional[str] = None) -> None:
    if surface not in SURFACES:
        raise ValueError(f"unknown surface {surface!r}; expected one of {SURFACES}")
    SURFACE.set(surface)
    SESSION.set(session)


def current() -> dict:
    return {"surface": SURFACE.get(), "session": SESSION.get()}


def run_in_thread_context(target):
    """Wrap `target` so a thread runs it inside a copy of the caller's context."""
    ctx = contextvars.copy_context()
    return lambda *a, **kw: ctx.run(target, *a, **kw)
