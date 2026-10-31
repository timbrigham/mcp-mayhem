"""What the two servers share: where the queue lives, and how a call becomes a result.

publishRobot (queue/pending/history/withdraw) and publishApprove (approve) are separate
processes over ONE queue. They must read the same environment variables, or approvals would
look in a different directory from the one entries were queued in.
"""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path

import anyio.to_thread

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from publish_core.engine import Publisher  # noqa: E402
from publish_core.errors import PublishError, RefusalError  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
DATA = os.environ.get("PUBLISHROBOT_DATA", str(HERE / "data"))
CONFIG = os.environ.get("PUBLISHROBOT_CONFIG", str(HERE / "config" / "publish.v1.json"))
TRACKER = os.environ.get("PUBLISHROBOT_TRACKER") or None
ACTOR = os.environ.get("PUBLISHROBOT_ACTOR", "mcp")


def publisher() -> Publisher:
    return Publisher(DATA, CONFIG, tracker_path=TRACKER, actor=ACTOR)


async def guard(tool: str, *args, **kwargs) -> dict:
    """Off the event loop (a blocking `gh` call must not stall the supervisor's health probe),
    and every deliberate failure turned into a result with its success condition."""
    try:
        fn = getattr(publisher(), tool)
        return {"ok": True, **await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))}
    except RefusalError as exc:
        return {"ok": False, "error_type": exc.error_type, "error": str(exc),
                "satisfied_when": exc.satisfied_when, "refusal_class": exc.refusal_class}
    except PublishError as exc:
        return {"ok": False, "error_type": exc.error_type, "error": str(exc),
                "satisfied_when": exc.satisfied_when}
