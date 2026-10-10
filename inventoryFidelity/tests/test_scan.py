"""The scanner: naming, locations, and the items reported as errors instead of classified."""

import json

import pytest

from inventory_fidelity import CannotMeasure, scan_artifact
from inventory_fidelity.scan import register_items

from helpers import write

HEX = "0123456789abcdef" * 4


def models(*entries) -> str:
    return json.dumps({"references": list(entries)})


def test_names_are_repo_relative_with_forward_slashes(tmp_path):
    write(tmp_path, {"prompts/a.md": "a", "tools/t.json": "{}", "guardrails/g.yaml": "g", "guardrails/h.yml": "h"})
    assert sorted(scan_artifact(tmp_path).present) == [
        "guardrails/g.yaml", "guardrails/h.yml", "prompts/a.md", "tools/t.json"]


def test_reference_entries_use_their_declared_name_and_digest(tmp_path):
    write(tmp_path, {"models.json": models({"name": "chat-model", "ref": f"llama3@sha256:{HEX}"},
                                           {"name": "eval-set", "ref": f"sha256:{HEX[::-1]}"})})
    scan = scan_artifact(tmp_path)
    assert dict(scan.present) == {"chat-model": HEX, "eval-set": HEX[::-1]}
    assert scan.errors == ()


def test_every_location_is_listed_and_absent_differs_from_empty(tmp_path):
    (tmp_path / "prompts").mkdir()
    write(tmp_path, {"tools/t.json": "{}"})
    locs = {loc["location"]: loc for loc in scan_artifact(tmp_path).locations}
    assert set(locs) == {"prompts/*.md", "tools/*.json", "guardrails/*.yaml, guardrails/*.yml", "models.json"}
    assert (locs["prompts/*.md"]["status"], locs["prompts/*.md"]["items"]) == ("scanned", 0)
    assert locs["guardrails/*.yaml, guardrails/*.yml"]["status"] == "absent"
    assert locs["tools/*.json"]["items"] == 1


def test_unscanned_files_in_a_scanned_directory_are_listed(tmp_path):
    write(tmp_path, {"prompts/a.md": "a", "prompts/B.MD": "b", "prompts/sub/c.md": "c"})
    loc = scan_artifact(tmp_path).locations[0]
    assert loc["items"] == 1
    assert loc["not_scanned"] == ["prompts/B.MD", "prompts/sub"]


def test_duplicate_reference_names_are_an_error_and_never_present(tmp_path):
    write(tmp_path, {"models.json": models({"name": "m", "ref": f"sha256:{HEX}"},
                                           {"name": "m", "ref": f"sha256:{HEX[::-1]}"})})
    scan = scan_artifact(tmp_path)
    assert "m" not in scan.present
    assert [(e.kind, e.name) for e in scan.errors] == [("duplicate-name", "m")]


def test_a_reference_named_like_a_file_is_a_duplicate(tmp_path):
    write(tmp_path, {"tools/t.json": "{}", "models.json": models({"name": "tools/t.json", "ref": f"sha256:{HEX}"})})
    scan = scan_artifact(tmp_path)
    assert "tools/t.json" not in scan.present
    assert [e.kind for e in scan.errors] == ["duplicate-name"]


@pytest.mark.parametrize("entry", [{"ref": f"sha256:{HEX}"}, {"name": "", "ref": f"sha256:{HEX}"},
                                   {"name": "  ", "ref": f"sha256:{HEX}"}, "just a string"])
def test_an_unnamed_reference_is_an_error(tmp_path, entry):
    write(tmp_path, {"models.json": models(entry)})
    scan = scan_artifact(tmp_path)
    assert dict(scan.present) == {}
    assert [(e.kind, e.name) for e in scan.errors] == [("unnamed", None)]


@pytest.mark.parametrize("entry", [{"name": "chat", "ref": "llama3:latest"}, {"name": "chat"}])
def test_a_tag_only_reference_is_an_error_not_a_match(tmp_path, entry):
    write(tmp_path, {"models.json": models(entry)})
    scan = scan_artifact(tmp_path)
    assert "chat" not in scan.present
    assert [(e.kind, e.name) for e in scan.errors] == [("no-digest", "chat")]


def test_an_unparseable_file_component_is_an_error_naming_it(tmp_path):
    write(tmp_path, {"tools/bad.json": "{oops", "tools/ok.json": "{}"})
    scan = scan_artifact(tmp_path)
    assert list(scan.present) == ["tools/ok.json"]
    assert [(e.kind, e.name) for e in scan.errors] == [("not-canonical", "tools/bad.json")]


@pytest.mark.parametrize("content", ["{oops", "[]", '{"refs": []}'])
def test_an_unreadable_reference_file_means_nothing_is_measured(tmp_path, content):
    write(tmp_path, {"models.json": content})
    with pytest.raises(CannotMeasure):
        scan_artifact(tmp_path)


def test_a_missing_artifact_is_refused_never_an_empty_scan(tmp_path):
    with pytest.raises(CannotMeasure, match="does not exist"):
        scan_artifact(tmp_path / "nope")


def test_register_refuses_a_path_the_scanner_never_reads(tmp_path):
    write(tmp_path, {"docs/readme.md": "x", "prompts/a.md": "a"})
    present, errors = register_items(tmp_path, ["docs/readme.md", "prompts/a.md"])
    assert list(present) == ["prompts/a.md"]
    assert [(e.kind, e.name) for e in errors] == [("not-scannable", "docs/readme.md")]
