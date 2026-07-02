"""Shared fixtures: load the schema and a fresh copy of the sample dataset."""

import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SAMPLE_PATH = ROOT / "data" / "sample.json"
SCHEMA_PATH = ROOT / "consumers" / "lean" / "declaration.schema.json"


@pytest.fixture
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def sample() -> dict:
    """A fresh deep copy of the conforming sample document per test."""
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def sample_file(tmp_path, sample) -> Path:
    """Write the sample to a temp file and return its path (isolated per test)."""
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(sample, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def mutate(doc: dict, fn) -> dict:
    """Return a deep copy of doc with fn applied (fn mutates in place)."""
    clone = copy.deepcopy(doc)
    fn(clone)
    return clone
