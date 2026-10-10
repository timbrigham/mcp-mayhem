"""The command line: exit codes, output, and that the inventory file is never written."""

import json

from helpers import cli, write, write_inventory

HEX = "0123456789abcdef" * 4


def _artifact(tmp_path):
    art = tmp_path / "art"
    write(art, {"prompts/s.md": "hello\n", "tools/t.json": '{"a": 1}'})
    return art


def _registered(tmp_path, art):
    out = cli("register", "--root", art, "prompts/s.md", "tools/t.json")
    assert out.returncode == 0, out.stderr
    return {e["name"]: e["sha256"] for e in json.loads(out.stdout)}


def test_exit_0_when_measured_and_the_inventory_file_is_byte_identical_after(tmp_path):
    art = _artifact(tmp_path)
    inv = tmp_path / "inventory.json"
    # Indented with 4 spaces and keys unsorted, so any rewrite by the tool would change bytes.
    before = write_inventory(inv, {"tools/t.json": _registered(tmp_path, art)["tools/t.json"], "x/gone.md": "c" * 64},
                             retired=["old"])
    mtime = inv.stat().st_mtime_ns
    for extra in ([], ["--json"]):
        out = cli("measure", "--inventory", inv, "--artifact", art, *extra)
        assert out.returncode == 0, out.stderr
    assert inv.read_bytes() == before
    assert inv.stat().st_mtime_ns == mtime


def test_json_output_has_counts_names_ratios_and_errors(tmp_path):
    art = _artifact(tmp_path)
    inv = tmp_path / "inv.json"
    write_inventory(inv, _registered(tmp_path, art))
    report = json.loads(cli("measure", "--inventory", inv, "--artifact", art, "--json").stdout)
    assert report["measured"] is True
    assert report["counts"]["matched"] == 2 and report["names"]["matched"] == ["prompts/s.md", "tools/t.json"]
    assert report["precision"] == {"numerator": 2, "denominator": 2, "value": 1.0}
    assert report["errors"] == [] and len(report["locations"]) == 4


def test_text_output_shows_null_for_an_undefined_ratio(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    inv = tmp_path / "inv.json"
    write_inventory(inv, {})
    out = cli("measure", "--inventory", inv, "--artifact", art)
    assert out.returncode == 0
    assert "0/0 = null" in out.stdout


def test_exit_2_when_the_inventory_is_missing(tmp_path):
    out = cli("measure", "--inventory", tmp_path / "none.json", "--artifact", _artifact(tmp_path), "--json")
    assert out.returncode == 2
    assert json.loads(out.stdout)["measured"] is False


def test_exit_2_when_the_artifact_is_missing(tmp_path):
    inv = tmp_path / "inv.json"
    write_inventory(inv, {})
    assert cli("measure", "--inventory", inv, "--artifact", tmp_path / "none").returncode == 2


def test_exit_2_when_the_inventory_is_refused(tmp_path):
    inv = tmp_path / "inv.json"
    raw = write_inventory(inv, {"x": "a" * 64}, retired=["x"])
    out = cli("measure", "--inventory", inv, "--artifact", _artifact(tmp_path))
    assert out.returncode == 2
    assert "both active and retired" in out.stderr and out.stdout == ""
    assert inv.read_bytes() == raw


def test_exit_3_when_measured_with_scan_errors(tmp_path):
    art = _artifact(tmp_path)
    write(art, {"models.json": json.dumps({"references": [{"name": "chat", "ref": "llama3:latest"}]})})
    inv = tmp_path / "inv.json"
    write_inventory(inv, {"chat": HEX})
    out = cli("measure", "--inventory", inv, "--artifact", art, "--json")
    assert out.returncode == 3
    report = json.loads(out.stdout)
    assert report["errors"][0]["kind"] == "no-digest" and report["withheld"] == ["chat"]
    assert report["counts"]["vanished"] == 0


def test_exit_64_on_a_malformed_command_line_not_2():
    assert cli("measure", "--inventory").returncode == 64
    assert cli("frobnicate").returncode == 64


def test_register_prints_entries_and_exits_3_on_a_tag_only_reference(tmp_path):
    write(tmp_path, {"models.json": json.dumps({"references": [{"name": "ok", "ref": f"sha256:{HEX}"},
                                                               {"name": "bad", "ref": "llama3:latest"}]})})
    out = cli("register", "--root", tmp_path, "models.json")
    assert out.returncode == 3
    assert json.loads(out.stdout) == [{"name": "ok", "sha256": HEX}]
    assert "bad" in out.stderr
