"""Evidence currency, end to end, on a throwaway git repository.

Run from the `verdictLedger/` directory of a checkout:

    python examples/evidence-currency/run_example.py

Requires Python 3.11+ and git on PATH. Everything is created under a new temporary directory
(printed at the start) and nothing outside it is touched. Each verdict is recorded through the
ledger's own command line (`python -m core.cli append`), so it passes the same validation as
any real record.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER_DIR = HERE.parents[1]                 # verdictLedger/
CONFIG = HERE / "config"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def blob(repo: Path, ref: str, path: str) -> str:
    return git(repo, "rev-parse", f"{ref}:{path}")


def ledger(env: dict, *args: str) -> str:
    r = subprocess.run([sys.executable, "-m", "core.cli", *args], cwd=LEDGER_DIR, env=env,
                       capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise SystemExit(f"ledger command failed ({r.returncode}): {' '.join(args)}\n{r.stdout}{r.stderr}")
    return r.stdout + (r.stderr if r.returncode else "")


def record(env: dict, repo: Path, ref: str, step: str, checker: str, paths: list[str],
           work: Path) -> None:
    """Record a PASS for `step` over `paths` at `ref`, as a checker run would."""
    rec = {
        "schema": "zp.record.v1",
        "step": step,
        "tier": "A",
        "verdict": "PASS",
        "reason": None,
        "basis": {"kind": "ref", "value": ref, "resolved_from": "explicit"},
        # each subject is bound to the exact bytes it was checked at: path + git blob id
        "subjects": [{"path": p, "git_blob_id": blob(repo, ref, p)} for p in paths],
        # the checker that produced the verdict, also by content
        "evidence": [{"path": checker, "git_blob_id": blob(repo, ref, checker)}],
        "decided": {"how": "mechanical", "passes": 1, "agreed": 1, "who": None},
        "inputs": [],
        "revision": 0,
        # a duration must say what it measures; here, the checker's own run
        "cost": {"seconds": 0.1, "seconds_prices": "the checker's run, from its start to its end",
                 "usd": 0.0},
        "run": {"id": f"example-{step}", "started": datetime.now(timezone.utc).isoformat(),
                "config_sha": None, "env": {}},
    }
    f = work / f"{step}-{ref[:8]}.json"
    f.write_bytes(json.dumps(rec).encode("utf-8"))
    out = ledger(env, "append", str(f))
    if '"appended": true' not in out and '"appended":true' not in out:
        raise SystemExit(f"append refused for {step}:\n{out}")


def show(env: dict, title: str) -> None:
    print(f"\n=== {title}")
    print(ledger(env, "evidence-currency", "--ref", "HEAD").rstrip())


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="evidence-currency-"))
    repo = work / "repo"
    repo.mkdir()
    print(f"working directory: {work}")
    env = dict(os.environ,
               ZPLEDGER_REPO=str(repo),
               ZPLEDGER_DATA=str(work / "records.jsonl"),
               ZPLEDGER_POLICY=str(CONFIG / "policy.example.json"),
               ZPLEDGER_REQUIRED=str(CONFIG / "required.example.json"),
               ZPLOG_ENABLED="0")

    # 1. A small repository: two documentation files, two source files, and the two checkers.
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "example@example.invalid")
    git(repo, "config", "user.name", "example")
    git(repo, "config", "commit.gpgsign", "false")
    write(repo, "docs/intro.md", "# Introduction\n\nA small example project.\n")
    write(repo, "docs/usage.md", "# Usage\n\nRun the program.\n")
    write(repo, "src/app.py", "# License: MIT\nprint('hello')\n")
    write(repo, "src/util.py", "# License: MIT\ndef helper():\n    return 1\n")
    write(repo, "tools/check_spelling.py", "# spell-checks docs/*.md\n")
    write(repo, "tools/check_license_header.py", "# checks src/*.py for a license header\n")
    head = commit(repo, "initial")

    # 2. Both checkers run and pass; their verdicts are recorded against the files' current bytes.
    record(env, repo, head, "spelling", "tools/check_spelling.py",
           ["docs/intro.md", "docs/usage.md"], work)
    record(env, repo, head, "license_header", "tools/check_license_header.py",
           ["src/app.py", "src/util.py"], work)
    show(env, "1. every in-scope file has a verdict at its current content")

    # 3. Edit one documentation file. Its old verdict no longer describes its bytes: STALE.
    write(repo, "docs/usage.md", "# Usage\n\nRun the program with --help for options.\n")
    commit(repo, "edit usage")
    show(env, "2. after editing docs/usage.md: one spelling subject is stale")

    # 4. Add a new source file that no checker has run on: NEVER EXAMINED.
    write(repo, "src/extra.py", "# License: MIT\nVALUE = 2\n")
    commit(repo, "add extra")
    show(env, "3. after adding src/extra.py: one license_header subject was never examined")

    # 5. Re-run the spelling check on the edited file: it becomes current again.
    head = git(repo, "rev-parse", "HEAD")
    record(env, repo, head, "spelling", "tools/check_spelling.py", ["docs/usage.md"], work)
    show(env, "4. after re-checking docs/usage.md: spelling is current again")

    print("\nmachine-readable form of the last result:")
    print(ledger(env, "evidence-currency", "--ref", "HEAD", "--json").rstrip())
    print(f"\n(everything above lives under {work}; delete it when done)")


if __name__ == "__main__":
    main()
