"""The CLI surface. `core` must be usable with no MCP installed — if the server is
down the rules still exist, and a human still needs to be able to apply them.

These also pin the argparse behaviour that a smoke test caught: a flag-shaped
argument has to reach the OPERATION so it produces a refusal that explains itself,
rather than dying in the parser as "unrecognized arguments".
"""

import json

import pytest

from core import cli


def _run(capsys, repo, log, *argv):
    code = cli.main(["--repo", str(repo), "--data", str(log), *argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_read_passes_flags_through_to_the_allow_list(capsys, repo, tmp_path):
    code, out, _ = _run(capsys, repo, tmp_path / "ops.jsonl",
                        "read", "log", "-1", "--oneline")
    assert code == 0
    assert json.loads(out)["ok"] is True


def test_bulk_stage_reaches_the_refusal_not_an_argparse_error(capsys, repo, tmp_path):
    """Exit 1 (a refusal that explains itself), not exit 2 (a usage error)."""
    code, _, err = _run(capsys, repo, tmp_path / "ops.jsonl", "stage", "-A")
    assert code == 1
    assert "stages everything in the tree" in err
    assert "INSTEAD:" in err and "stage(paths=" in err


def test_a_refusal_prints_its_id_for_explain(capsys, repo, tmp_path):
    log = tmp_path / "ops.jsonl"
    code, _, err = _run(capsys, repo, log, "read", "push")
    assert code == 1 and "refusal id" in err
    rid = err.rsplit("refusal id ", 1)[1].strip().rstrip(")")
    code, out, _ = _run(capsys, repo, log, "explain", rid)
    assert code == 0 and json.loads(out)["op"] == "read"


def test_status_exits_zero_and_reports_blockers(capsys, repo, tmp_path):
    code, out, _ = _run(capsys, repo, tmp_path / "ops.jsonl", "status")
    assert code == 0
    assert json.loads(out)["would_block_push"]


def test_unknown_global_arguments_still_error(capsys, repo, tmp_path):
    """The leftovers-merge must not become a catch-all that swallows typos."""
    with pytest.raises(SystemExit) as exc:
        _run(capsys, repo, tmp_path / "ops.jsonl", "status", "--wat")
    assert exc.value.code == 2


def test_push_requires_a_reason_at_the_parser(capsys, repo, tmp_path):
    with pytest.raises(SystemExit) as exc:
        _run(capsys, repo, tmp_path / "ops.jsonl", "push", "illustrated")
    assert exc.value.code == 2


def test_core_imports_without_mcp_installed(monkeypatch):
    """The separation the sibling registry keeps: enforcement does not depend on
    the transport being importable."""
    import builtins
    import importlib

    real_import = builtins.__import__

    def no_mcp(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("mcp is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_mcp)
    for module in ("core.engine", "core.cli", "core.tiers", "core.gates"):
        importlib.reload(importlib.import_module(module))
