"""Shared helpers for the tests: build artifacts as bytes and run the CLI as a subprocess."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write(root: Path, files: dict) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def write_inventory(path: Path, active: dict, retired=()) -> bytes:
    raw = json.dumps({"active": [{"name": n, "sha256": s} for n, s in active.items()],
                      "retired": list(retired)}, indent=4).encode("utf-8")
    path.write_bytes(raw)
    return raw


def cli(*args, cwd=None) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(PROJECT))
    return subprocess.run([sys.executable, "-m", "inventory_fidelity", *map(str, args)],
                          cwd=cwd or PROJECT, env=env, capture_output=True, text=True, encoding="utf-8")
