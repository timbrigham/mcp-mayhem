"""The stream is a FILE, and a file can be edited. This is what notices.

⛔⛔ THIS SERVER HAD NO TAMPER DETECTION OF ANY KIND UNTIL 2026-09-12. No hash chain, no
per-record digest, no file hash. `invalid_appends` counts REFUSED APPENDS, never edits. So an
out-of-band edit to `records.jsonl` was invisible here — while `sjv`, a JSON store sitting
beside it, has caught exactly that since it was built. The server whose entire value is an
append-only audit stream had less integrity checking than the store next door.

⭐ Tim, 2026-09-12, correcting a claim that an append could not be undone: "Append being
permanent is true only in so far as the logic itself goes... These are still json files and
editable outside the core tooling. Not something I suggest in general but for an emergency flaw
restoration, I'm not 100% opposed."

⚠ DETECTION, NOT PREVENTION, and that is the whole design. Nothing here stops a text editor.
Keeping the escape hatch open and making its use VISIBLE is a better trade than a lock nobody
can open in an emergency.
"""

import json

from core import store as store_mod


def _store(tmp_path):
    return store_mod.Store(tmp_path / "records.jsonl")


def _rec(step="guards"):
    return {"schema": "zp.record.v1", "step": step, "tier": "A", "verdict": "PASS",
            "reason": None, "basis": {"kind": "tree", "value": "t", "resolved_from": "explicit"},
            "subjects": [{"path": "a.py", "git_blob_id": "b1"}], "evidence": [],
            "decided": {"how": "mechanical", "passes": 1, "agreed": 1, "who": None},
            "inputs": [], "revision": 0, "cost": {"seconds": None, "usd": 0.0},
            "run": {"id": "t", "started": None, "config_sha": None, "env": {}},
            "id": "guards@t#0"}


def test_an_unstamped_stream_is_its_own_state_and_not_agreement(tmp_path):
    """⛔ ABSENCE MUST NOT RENDER AS SUCCESS. A stream predating the detector has no baseline;
    calling that 'matches' would be the exact defect this server exists to remove."""
    st = _store(tmp_path)
    st.path.parent.mkdir(parents=True, exist_ok=True)
    st.path.write_text(json.dumps(_rec()) + "\n", encoding="utf-8")   # written around the server

    out = st.verify_integrity()
    assert out["state"] == "unstamped"
    assert out["expected"] is None
    assert "NOT a statement" in out["note"], "it must refuse to be read as agreement"


def test_an_append_stamps_and_then_matches(tmp_path):
    st = _store(tmp_path)
    st.append(_rec())
    out = st.verify_integrity()
    assert out["state"] == "matches"
    assert out["sha256"] == out["expected"]
    assert out["stamped"].endswith("+00:00"), "every timestamp this fleet writes is UTC with offset"


def test_an_out_of_band_edit_is_DETECTED_and_breaks_health(tmp_path):
    """⭐⭐ THE ONE THAT MATTERS. Append through the server, then edit the file the way a person
    would, and the server must stop saying healthy."""
    st = _store(tmp_path)
    st.append(_rec())
    assert st.verify_integrity()["state"] == "matches"
    assert st.health()["healthy"] is True

    # A hand edit: append a row without going through the server at all.
    with open(st.path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(_rec(step="handwritten")) + "\n")

    out = st.verify_integrity()
    assert out["state"] == "MODIFIED", "an out-of-band edit must be detected"
    assert out["sha256"] != out["expected"]

    health = st.health()
    assert health["healthy"] is False, "a modified stream must break health, not sit beside it"
    assert any("other than this server" in p for p in health["problems"])


def test_unstamped_does_NOT_break_health(tmp_path):
    """⚠ THE COUNTER-CONTROL. 'I have no baseline' is not 'you were tampered with', and
    alarming on it would make every pre-existing stream report unhealthy forever."""
    st = _store(tmp_path)
    st.path.parent.mkdir(parents=True, exist_ok=True)
    st.path.write_text(json.dumps(_rec()) + "\n", encoding="utf-8")

    assert st.verify_integrity()["state"] == "unstamped"
    assert st.health()["healthy"] is True, "an unstamped stream is honest, not broken"


def test_a_stamp_failure_never_loses_an_accepted_record(tmp_path, monkeypatch):
    """⛔ THE VERDICT IS ALREADY FSYNCED WHEN THE STAMP RUNS. Raising there would discard a
    record the server had accepted — trading a durable verdict for a bookkeeping file."""
    st = _store(tmp_path)

    def boom(*_a, **_k):
        raise OSError("sidecar unwritable")
    monkeypatch.setattr(type(st._integrity_path), "write_text", boom, raising=False)

    st.append(_rec())                      # must not raise
    assert len(st.records()) == 1, "the record must survive a failed stamp"
