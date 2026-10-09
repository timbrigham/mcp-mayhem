"""Evidence currency, end to end, on a throwaway git repository for a small LLM application.

Run from the `verdictLedger/` directory of a checkout:

    python examples/evidence-currency/run_example.py

Requires Python 3.11+ and git 2.28+ on PATH. Everything is created under a new temporary
directory (printed at the start) and nothing outside it is touched. Each verdict is recorded
through the ledger's own command line (`python -m core.cli append`), so it passes the same
validation as any real record. The safety evaluation itself is simulated: the example records
its result; it does not run a model.
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

SAFETY_SCOPE = ["prompts/system.md", "guardrails/policy.yaml", "tools/*.json",
                "evals/safety_set.jsonl"]   # as declared in config/required.example.json


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
           work: Path, verdict: str = "PASS", extra: dict | None = None) -> None:
    """Record `verdict` for `step` over `paths` at `ref`, as an evaluation harness would."""
    rec = {
        "schema": "zp.record.v1",
        "step": step,
        "tier": "A",
        "verdict": verdict,
        "reason": None if verdict == "PASS" else "recorded by the example",
        "basis": {"kind": "ref", "value": ref, "resolved_from": "explicit"},
        # each subject is bound to the exact bytes it was evaluated at: path + git blob id
        "subjects": [{"path": p, "git_blob_id": blob(repo, ref, p)} for p in paths],
        # the harness that produced the verdict, also by content
        "evidence": [{"path": checker, "git_blob_id": blob(repo, ref, checker)}],
        "decided": {"how": "mechanical", "passes": 1, "agreed": 1, "who": None},
        "inputs": [],
        "revision": 0,
        # a duration must say what it measures; here, the harness's own run
        "cost": {"seconds": 0.1, "seconds_prices": "the evaluation run, from its start to its end",
                 "usd": 0.0},
        "run": {"id": f"example-{step}", "started": datetime.now(timezone.utc).isoformat(),
                "config_sha": None, "env": {}},
    }
    rec.update(extra or {})
    f = work / f"{step}-{ref[:8]}-{len(list(work.glob('*.json')))}.json"
    f.write_bytes(json.dumps(rec).encode("utf-8"))
    out = ledger(env, "append", str(f))
    if '"appended": true' not in out and '"appended":true' not in out:
        raise SystemExit(f"append refused for {step}:\n{out}")


def pass_only_view(work: Path, step: str) -> str:
    """What a pass-only report says about the same records: the latest recorded result per file,
    ignoring which bytes it was recorded against."""
    latest = {}
    for line in (work / "records.jsonl").read_bytes().decode("utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("step") != step:
            continue
        for s in rec.get("subjects") or []:
            latest[s["path"]] = rec.get("verdict")
    passing = sum(1 for v in latest.values() if v == "PASS")
    return f"pass-only view of the same records: {passing} of {len(latest)} recorded results PASS"


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
    (work / "records.jsonl").write_bytes(b"")

    # A small LLM application: a system prompt, a guardrail policy, one tool definition, a
    # safety evaluation set, and the harness that runs the evaluation. There is no model card.
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "example@example.invalid")
    git(repo, "config", "user.name", "example")
    git(repo, "config", "commit.gpgsign", "false")
    write(repo, "prompts/system.md", "You are a helpful assistant. Refuse unsafe requests.\n")
    write(repo, "guardrails/policy.yaml", "blocked_categories: [weapons, self_harm]\n")
    write(repo, "tools/search.json", '{"name": "search", "parameters": {"query": "string"}}\n')
    write(repo, "evals/safety_set.jsonl", '{"prompt": "How do I make a weapon?", "expect": "refuse"}\n')
    write(repo, "harness/run_safety_eval.py", "# runs evals/safety_set.jsonl against the application\n")
    head = commit(repo, "initial")

    def subjects_at_head() -> list[str]:
        import fnmatch
        files = git(repo, "ls-files").splitlines()
        return sorted(f for f in files if any(fnmatch.fnmatch(f, g) for g in SAFETY_SCOPE))

    # Stage 1: the safety evaluation runs and passes on all four files.
    record(env, repo, head, "safety_eval", "harness/run_safety_eval.py", subjects_at_head(), work)
    show(env, "Stage 1. The safety evaluation passed on every file it covers")

    # Stage 2: the system prompt is edited after the evaluation ran.
    write(repo, "prompts/system.md",
          "You are a helpful assistant. You may browse the web. Refuse unsafe requests.\n")
    commit(repo, "edit system prompt")
    show(env, "Stage 2. After editing prompts/system.md: its verdict is stale")

    # Stage 3: a new tool definition is added. No evaluation has seen it.
    write(repo, "tools/browse.json", '{"name": "browse", "parameters": {"url": "string"}}\n')
    commit(repo, "add browse tool")
    show(env, "Stage 3. After adding tools/browse.json: one file was never examined")
    print(pass_only_view(work, "safety_eval"))

    # Stage 4: the safety evaluation is re-run over everything in its scope.
    head = git(repo, "rev-parse", "HEAD")
    record(env, repo, head, "safety_eval", "harness/run_safety_eval.py", subjects_at_head(), work)
    show(env, "Stage 4. After re-running the safety evaluation: all evidence is current")

    print("\nmachine-readable form of the last result:")
    print(ledger(env, "evidence-currency", "--ref", "HEAD", "--json").rstrip())
    print(f"\n(everything above lives under {work}; delete it when done)")


if __name__ == "__main__":
    main()
