"""Build a toy agent repository in a fresh temporary directory and measure its inventory fidelity.

    python examples/inventory-fidelity/run_example.py [--json] [--workdir DIR]

Steps:
  1. write the ORIGINAL components to <work>/registered/;
  2. register them with the tool's own 'register' command, and write <work>/inventory.json
     with tools/legacy.json listed as retired;
  3. write the DEPLOYED artifact to <work>/deployed/: prompts/system.md edited, the two
     registered tools unchanged, tools/browse.json added, tools/legacy.json back again,
     guardrails/policy.yaml missing;
  4. run 'measure' and print its output.

Expected: matched 2, modified 1, vanished 1, phantom 1, resurrected 1, retired-absent 0;
precision 2/4 = 0.5, recall 2/5 = 0.4.

The temporary directory's path is printed on stderr. Nothing outside it is written.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]   # the inventoryFidelity/ directory

ORIGINAL = {
    "prompts/system.md": "You are a support assistant.\nAnswer only from the product knowledge base.\n",
    "tools/search.json": '{"name": "search", "description": "Search the product knowledge base.",'
                         ' "parameters": {"query": {"type": "string"}}}\n',
    "tools/lookup.json": '{"name": "lookup", "description": "Fetch one article by id.",'
                         ' "parameters": {"id": {"type": "string"}}}\n',
    "guardrails/policy.yaml": "blocked_topics:\n  - medical advice\n  - legal advice\nmax_output_tokens: 800\n",
}
RETIRED = ["tools/legacy.json"]

DEPLOYED = {
    "prompts/system.md": "You are a support assistant.\nAnswer from the product knowledge base or the web.\n",
    "tools/search.json": ORIGINAL["tools/search.json"],
    "tools/lookup.json": ORIGINAL["tools/lookup.json"],
    "tools/browse.json": '{"name": "browse", "description": "Open any web page.",'
                         ' "parameters": {"url": {"type": "string"}}}\n',
    "tools/legacy.json": '{"name": "legacy_search", "description": "Old keyword search.",'
                         ' "parameters": {"q": {"type": "string"}}}\n',
}


def write_tree(root: Path, files: dict) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        # Bytes, not text mode: text mode on Windows would write CRLF.
        path.write_bytes(text.encode("utf-8"))


def run_tool(work: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(PROJECT))
    return subprocess.run([sys.executable, "-m", "inventory_fidelity", *args],
                          cwd=work, env=env, capture_output=True, text=True, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the measurement as JSON")
    parser.add_argument("--workdir", help="use this empty directory instead of a new temporary one")
    args = parser.parse_args()

    if args.workdir:
        work = Path(args.workdir)
        work.mkdir(parents=True, exist_ok=True)
        if any(work.iterdir()):
            sys.stderr.write(f"--workdir {work} is not empty\n")
            return 2
    else:
        work = Path(tempfile.mkdtemp(prefix="inventory-fidelity-example-"))
    sys.stderr.write(f"working directory: {work}\n")

    write_tree(work / "registered", ORIGINAL)
    reg = run_tool(work, "register", "--root", "registered", *ORIGINAL)
    if reg.returncode != 0:
        sys.stderr.write(reg.stdout + reg.stderr)
        return reg.returncode
    inventory = {"active": json.loads(reg.stdout), "retired": RETIRED}
    (work / "inventory.json").write_bytes((json.dumps(inventory, indent=2) + "\n").encode("utf-8"))

    write_tree(work / "deployed", DEPLOYED)
    args_measure = ["measure", "--inventory", "inventory.json", "--artifact", "deployed"]
    result = run_tool(work, *args_measure, *(["--json"] if args.json else []))
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
