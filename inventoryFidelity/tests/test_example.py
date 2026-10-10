"""The published example must print exactly the numbers its README states."""

import json
import subprocess
import sys

from helpers import PROJECT

SCRIPT = PROJECT / "examples" / "inventory-fidelity" / "run_example.py"


def _run(tmp_path, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), "--workdir", str(tmp_path / "work"), *extra],
                          capture_output=True, text=True, encoding="utf-8")


def test_the_example_gives_exactly_the_stated_numbers(tmp_path):
    out = _run(tmp_path, "--json")
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout)
    assert r["counts"] == {"matched": 2, "modified": 1, "vanished": 1, "phantom": 1,
                           "resurrected": 1, "retired-absent": 0}
    assert r["names"] == {"matched": ["tools/lookup.json", "tools/search.json"],
                          "modified": ["prompts/system.md"],
                          "vanished": ["guardrails/policy.yaml"],
                          "phantom": ["tools/browse.json"],
                          "resurrected": ["tools/legacy.json"],
                          "retired-absent": []}
    assert r["precision"] == {"numerator": 2, "denominator": 4, "value": 0.5}
    assert r["recall"] == {"numerator": 2, "denominator": 5, "value": 0.4}
    assert r["errors"] == [] and r["withheld"] == []


def test_the_example_text_output_shows_fractions_and_values(tmp_path):
    out = _run(tmp_path)
    assert out.returncode == 0, out.stderr
    assert "2/4 = 0.5" in out.stdout and "2/5 = 0.4" in out.stdout


def test_the_example_registers_from_the_original_files(tmp_path):
    _run(tmp_path)
    inv = json.loads((tmp_path / "work" / "inventory.json").read_bytes())
    assert [e["name"] for e in inv["active"]] == [
        "guardrails/policy.yaml", "prompts/system.md", "tools/lookup.json", "tools/search.json"]
    assert inv["retired"] == ["tools/legacy.json"]


def test_the_readme_shows_the_actual_output(tmp_path):
    """The README's output block is compared line by line with a real run, so it cannot drift."""
    out = _run(tmp_path)
    assert out.returncode == 0, out.stderr
    readme = (SCRIPT.parent / "README.md").read_bytes().decode("utf-8")
    fence = "`" * 3
    block = readme.split("measures it. Output:")[1].split(fence)[1].strip().splitlines()
    run = out.stdout.strip().splitlines()
    assert len(run) > 15
    assert [l.rstrip() for l in run] == [l.rstrip() for l in block]