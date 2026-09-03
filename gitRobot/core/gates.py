"""Running the consumer project's gate pipeline — by INVOKING it, never by reimplementing it.

⚠ There is exactly one implementation of the pipeline and gitRobot must not
become a second. The consumer project previously had two partial implementations
(shell and Python) which measurably disagreed three ways while checking disjoint
things; the shell half was retired for that reason. A gitRobot that re-derived
"which legs block" would be the third, and it would drift the same way.

So this module shells out to the project's own entry point and reports its exit
code. What gitRobot adds is not a better pipeline — it is that the pipeline
cannot be skipped with a flag, and that its verdict is RECORDED whether it passes
or fails.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# The project's single pipeline entry point, relative to the repo root, and the
# phases it accepts. If this path moves, gitRobot must fail loudly rather than
# silently skip the gate — see `available()`.
HOOKS_ENTRY = Path("tools") / "verify" / "hooks.py"
PHASES = ("pre-commit", "pre-push")

# The pre-push pipeline is slow and, depending on configuration, can make paid
# LLM calls. Generous, but bounded: a hung gate must not hang the server.
PHASE_TIMEOUT = {"pre-commit": 300, "pre-push": 1800}

_MAX_OUTPUT = 8000     # gate output echoed back to the caller, capped (receipt, not warehouse)
# ⚠⚠ A FAILING PIPELINE PUTS ITS REASON AT THE END, SO KEEPING THE HEAD DISCARDS THE ONE
# PART ANYBODY NEEDS. This was `self.output[:_MAX_OUTPUT]` — the first 8000 characters — and
# the pre-push pipeline prints ~20 plan rows and hundreds of `ok` lines before it reaches the
# failure. Measured 2026-08-30 on preflight `025a6f16`: exit 1, stored output ends mid-line at
# `ok   prose ext ` with **no FAIL row anywhere in it**. The cause was unrecoverable from the
# audit record of the run that produced it.
#
# ⚠ IT HAS COST THE SAME READER TWICE. ZeroParadox, opening this arc: *"preflight_status
# truncated the output before the failing row, so I reproduced the pipeline myself."* A receipt
# that forces you to re-run a 25-minute pipeline to learn why it failed is not a receipt.
#
# ⭐ SO: KEEP THE TAIL, AND SAY THE MIDDLE WAS DROPPED. A head slice is right for a passing
# run (the plan is the interesting part) and wrong for a failing one. Keeping both ends with an
# EXPLICIT elision marker means the truncation is visible rather than silent — a cut output that
# renders like a complete one is the defect this project keeps finding, and it would be
# especially poor here, in the record of why something was refused.
_HEAD_KEEP = 2000
_TAIL_KEEP = _MAX_OUTPUT - _HEAD_KEEP


def _clip(output: str) -> str:
    """Head + tail with a visible marker, never a silent cut."""
    if len(output) <= _MAX_OUTPUT:
        return output
    dropped = len(output) - _HEAD_KEEP - _TAIL_KEEP
    return (output[:_HEAD_KEEP]
            + f"\n\n… [{dropped} characters elided by gitRobot — head and TAIL kept, because a "
              f"failing gate states its reason at the end] …\n\n"
            + output[-_TAIL_KEEP:])


@dataclass(frozen=True)
class GateResult:
    phase: str
    ran: bool
    exit_code: Optional[int]
    output: str
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.ran and self.exit_code == 0

    def record(self) -> dict:
        """The shape stored in the audit log."""
        return {"phase": self.phase, "ran": self.ran, "exit_code": self.exit_code,
                "passed": self.passed, "note": self.note,
                "output": _clip(self.output)}


class Gates:
    def __init__(self, repo: str | os.PathLike, *, python: Optional[str] = None):
        self.repo = Path(repo)
        self.python = python or sys.executable or "python"

    def available(self) -> bool:
        return (self.repo / HOOKS_ENTRY).exists()

    def run(self, phase: str) -> GateResult:
        if phase not in PHASES:
            raise ValueError(f"unknown gate phase {phase!r}; expected one of {PHASES}")
        if not self.available():
            # NOT a silent pass. A missing pipeline is a finding: it means the
            # repo is not what gitRobot was configured for, and treating that as
            # "nothing to check" is how a gate becomes decorative.
            return GateResult(phase=phase, ran=False, exit_code=None, output="",
                              note=f"gate pipeline not found at {HOOKS_ENTRY} — "
                                   f"cannot vouch for this tree")
        argv = [self.python, str(HOOKS_ENTRY), phase]
        try:
            proc = subprocess.run(
                argv, cwd=str(self.repo), capture_output=True, text=True,
                encoding="utf-8", errors="replace", shell=False,
                timeout=PHASE_TIMEOUT.get(phase, 600),
            )
        except subprocess.TimeoutExpired:
            return GateResult(phase=phase, ran=True, exit_code=124, output="",
                              note=f"gate timed out after "
                                   f"{PHASE_TIMEOUT.get(phase, 600)}s")
        output = "\n".join(p for p in (proc.stdout or "", proc.stderr or "") if p.strip())
        return GateResult(phase=phase, ran=True, exit_code=proc.returncode, output=output)
