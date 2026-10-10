"""Canonical forms, and that registration and scan share one hash routine."""

import hashlib

import pytest

from inventory_fidelity.canonical import CanonicalFormError, component_sha256, reference_digest
from inventory_fidelity.scan import register_items, scan_artifact

from helpers import write

LF = b"line one\nline two\n"
HEX = "0123456789abcdef" * 4


def test_crlf_hashes_the_same_as_lf():
    assert component_sha256("prompts/a.md", b"line one\r\nline two\r\n") == component_sha256("prompts/a.md", LF)


def test_lone_cr_hashes_the_same_as_lf():
    assert component_sha256("prompts/a.md", b"line one\rline two\r") == component_sha256("prompts/a.md", LF)


def test_the_text_hash_is_sha256_of_the_lf_bytes():
    assert component_sha256("g/p.yaml", b"a: 1\r\n") == hashlib.sha256(b"a: 1\n").hexdigest()


def test_a_leading_bom_is_stripped_and_a_real_edit_is_not():
    assert component_sha256("p.md", b"\xef\xbb\xbf" + LF) == component_sha256("p.md", LF)
    assert component_sha256("p.md", LF + b" ") != component_sha256("p.md", LF)


def test_yml_and_txt_use_the_text_form():
    assert component_sha256("g/a.yml", b"a\r\n") == component_sha256("g/a.txt", b"a\n")


def test_reordered_json_keys_hash_the_same():
    a = b'{"name": "search", "parameters": {"q": {"type": "string"}, "n": 3}}'
    b = b'{\r\n  "parameters": {"n": 3, "q": {"type": "string"}},\r\n  "name": "search"\r\n}\r\n'
    assert component_sha256("tools/s.json", a) == component_sha256("tools/s.json", b)


def test_the_json_hash_is_sha256_of_the_declared_dump():
    expected = hashlib.sha256('{"a":1,"b":"é"}'.encode("utf-8")).hexdigest()
    assert component_sha256("tools/x.json", '{"b": "é", "a": 1}'.encode("utf-8")) == expected


def test_a_json_value_change_changes_the_hash():
    assert component_sha256("t.json", b'{"a":1}') != component_sha256("t.json", b'{"a":2}')


@pytest.mark.parametrize("path,raw", [
    ("t.json", b'{"a": 1, "a": 2}'),     # duplicate key
    ("t.json", b'{"a": NaN}'),
    ("t.json", b"{not json"),
    ("p.md", b"\xff\xfe"),               # not UTF-8
    ("p.bin", b"x"),                     # no declared form
])
def test_bytes_without_a_canonical_form_are_refused(path, raw):
    with pytest.raises(CanonicalFormError):
        component_sha256(path, raw)


@pytest.mark.parametrize("ref", [f"sha256:{HEX}", f"llama3@sha256:{HEX}", f"reg.example/m:7b@sha256:{HEX.upper()}"])
def test_a_reference_with_a_digest_yields_the_digest(ref):
    assert reference_digest(ref) == HEX


@pytest.mark.parametrize("ref", ["llama3:latest", "llama3", "sha256:abc", f"md5:{HEX}", "", None])
def test_a_tag_only_or_malformed_reference_is_refused(ref):
    with pytest.raises(CanonicalFormError):
        reference_digest(ref)


def test_register_and_scan_give_the_same_hash_for_the_same_file(tmp_path):
    write(tmp_path, {"prompts/s.md": b"hi\r\n", "tools/t.json": b'{"b":1,"a":2}',
                     "guardrails/g.yaml": b"x: 1\n",
                     "models.json": f'{{"references": [{{"name": "m", "ref": "m@sha256:{HEX}"}}]}}'})
    registered, errors = register_items(tmp_path, ["prompts/s.md", "tools/t.json", "guardrails/g.yaml", "models.json"])
    assert errors == []
    assert registered == dict(scan_artifact(tmp_path).present)
    assert len(registered) == 4
