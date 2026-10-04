"""Get-McpRepairAction: a slow-but-listening server gets grace; a dead one restarts at once.

⛔ Measured 2026-10-04: verdictLedger was restarted TEN times in one day (1-4 on any earlier day),
three inside one consumer run, never because it crashed — each was ONE missed 5 s health GET while
~17 parallel clients kept it busy. Every restart killed in-flight calls and threw away the ledger's
in-memory cache. Tim: require 3 misses. Only a SLOW answer earns grace; nothing-listening does not.

Runs the real module through Windows PowerShell 5.1, the supervisor's host. The decision is a pure
function, so nothing is started or killed.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "McpSupervisor.psm1"
pytestmark = pytest.mark.skipif(shutil.which("powershell") is None,
                                reason="Windows PowerShell is required")


def _action(health: str, listening: bool, http_ok: bool, misses: int, threshold: int) -> str:
    h = (f"[PSCustomObject]@{{ Health = '{health}'; Listening = ${str(listening).lower()}; "
         f"HttpOk = ${str(http_ok).lower()} }}")
    script = (f"$ErrorActionPreference='Stop'; Import-Module '{MODULE}' -Force; "
              f"Get-McpRepairAction -Health ({h}) -Misses {misses} -Threshold {threshold}")
    proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr[-1500:]
    return proc.stdout.strip()


def test_healthy_is_ok():
    assert _action("Healthy", True, True, 0, 3) == "ok"


def test_a_slow_answer_gets_grace_until_the_threshold():
    assert _action("Down", True, False, 0, 3) == "grace"      # 1st miss
    assert _action("Down", True, False, 1, 3) == "grace"      # 2nd miss
    assert _action("Down", True, False, 2, 3) == "restart"    # 3rd consecutive miss


def test_nothing_listening_restarts_at_once():
    """A dead process is dead: no grace, whatever the threshold."""
    assert _action("Down", False, False, 0, 3) == "restart"


def test_a_dead_proxy_child_restarts_at_once():
    assert _action("ChildDead", True, False, 0, 3) == "restart"


def test_threshold_one_keeps_the_old_single_strike_behaviour():
    """The CLI and the startup sweep pass 1: a human or a cold start means it."""
    assert _action("Down", True, False, 0, 1) == "restart"
