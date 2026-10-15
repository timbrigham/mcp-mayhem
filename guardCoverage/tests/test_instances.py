"""The unit is an agent instance (2026-10-15): resolving calls to instances, the HTTP-log
backfill, linking old refusals to their calls, and how measure() counts instances."""

import json
from datetime import timedelta

import pytest

from guard_coverage import instances as INST
from guard_coverage.core import measure as raw_measure
from guard_coverage.inputs import InputError
from helpers import (T0, VERS, guard, incident, manifest, measure, refusal, register, row,
                     sessions, ts)

GR = "gitrobot-mcp/cli"


def m(rows, reg=None, man=None, **kw):
    return measure(rows, reg or register(), man or manifest(), "1", **kw)


def call(h, session, cid, versions=VERS):
    """A call row (tool_calls.jsonl shape) without an audit row: a read, say."""
    r = {"ts": ts(h), "tool": "read", "surface": "mcp", "session": session,
         "client_call_id": cid}
    if versions is not None:
        r["versions"] = dict(versions)
    return r


# ------------------------------------------------------------------ measure: the unit
def test_two_instances_in_one_session_are_two_units():
    """The reason for the change: one MCP session carried hundreds of subagents."""
    rows = [row(1, session="S"), row(2, session="S"), row(3, session="S")]
    imap = {rows[0]["client_call_id"]: "main", rows[1]["client_call_id"]: "main/subagents/a",
            rows[2]["client_call_id"]: "main/subagents/b"}
    rep = m(rows, instance_map=imap)
    assert rep["inputs"]["agent_instances"] == 3 and rep["inputs"]["agent_sessions"] == 1
    assert rep["item4"]["windows"][0]["n"] == 3


def test_a_pattern_counts_once_per_instance_not_per_session():
    """Same session, two instances, one pattern each: Q2, not Q1."""
    a, b = refusal(1, session="S"), refusal(2, session="S")
    rows = sessions(3) + [a, b]
    imap = dict(measure_map(rows), **{a["client_call_id"]: "i-a", b["client_call_id"]: "i-b"})
    w = m(rows, instance_map=imap)["item4"]["windows"][0]
    assert (w["Q1"], w["Q2"]) == (0, 1)


def measure_map(rows):
    from helpers import instance_map
    return instance_map(rows)


def test_an_instance_that_only_reads_counts_toward_n():
    """Calls with no audit row (reads) still make an instance part of n."""
    calls = [call(10 + i, "S", "r%d" % i) for i in range(4)]
    rows = sessions(2)
    imap = dict(measure_map(rows), **{"r%d" % i: "reader%d" % i for i in range(4)})
    rep = m(rows, calls=calls, instance_map=imap)
    assert rep["inputs"]["agent_instances"] == 6
    assert rep["item4"]["windows"][0]["n"] == 6
    assert rep["inputs"]["call_rows"] == 4


def test_calls_with_no_id_or_no_mapping_are_skipped_and_counted():
    rows = sessions(2)
    calls = [call(5, "S", None), call(6, "S", "unmapped"), call(7, "S", "known"),
             call(8, "S", "forked")]
    imap = dict(measure_map(rows), known="k")
    rep = m(rows, calls=calls, instance_map=imap, ambiguous_ids=frozenset({"forked"}))
    why = {x["reason"]: x["count"] for x in rep["inputs"]["agent_rows_without_instance"]}
    assert why == {"call rows with no client call id: no instance": 1,
                   "call rows whose call id is in no transcript: no instance": 1,
                   "call rows whose call id is in several transcripts (a forked subagent's "
                   "copy of its parent's history): no instance": 1}
    assert rep["inputs"]["agent_instances"] == 3
    assert rep["inputs"]["ambiguous_call_ids"] == 1


def test_audit_rows_from_before_the_field_have_no_instance():
    r = row(1, session="S")
    del r["client_call_id"]
    rep = m([r] + sessions(2))
    assert {"count": 1, "reason": "audit rows lacking client_call_id (before it existed): "
                                  "no instance"} in rep["inputs"]["agent_rows_without_instance"]


def test_a_refusal_with_no_instance_counts_for_K_but_not_item4():
    r = refusal(5, session="S")
    r["client_call_id"] = None
    rep = m(sessions(3) + [r])
    assert rep["item1"]["K"] == 1
    assert {"count": 1, "reason": "refusal observation(s) with no known agent instance"} in \
        rep["item4"]["observations_excluded"]


def test_a_mapped_call_without_versions_is_an_instance_in_no_window():
    """Item 3 needs no version, so a call the map places counts as an instance; item 4 cannot
    window it, and says so rather than reading 0."""
    rows = sessions(3, start=100)
    early = call(1, "S", "e1", versions=None)
    rep = m(rows, calls=[early], instance_map=dict(measure_map(rows), e1="early-agent"))
    assert rep["inputs"]["agent_instances"] == 4
    assert rep["item3"]["instances"] == 4
    assert rep["item4"]["instances_in_no_window"] == 1
    assert sum(w["n"] for w in rep["item4"]["windows"]) == 3


def test_an_unmapped_row_without_versions_is_still_not_an_agent_row():
    c = call(1, "S", "zz", versions=None)
    rows = sessions(2)
    rep = m(rows, calls=[c], instance_map=measure_map(rows))
    assert rep["inputs"]["agent_instances"] == 2


def test_a_window_holding_a_refusal_with_no_instance_withholds_U_hat():
    """Its pattern cannot be placed in an instance, so Q1 is incomplete: an unknown must not
    make the estimate look better."""
    r = refusal(5, session="S")
    r["client_call_id"] = None
    w = m(sessions(120) + [r])["item4"]["windows"][0]
    assert w["n"] == 120 and w["U_hat"] is None and "no known agent instance" in w["withheld"]
    w = m(sessions(120) + [refusal(5, session="s0001")])["item4"]["windows"][0]
    assert w["U_hat"] is not None


def test_an_instance_map_listing_an_id_as_both_mapped_and_ambiguous_is_refused():
    from guard_coverage.inputs import validate_instance_map
    assert validate_instance_map({"map": {"a": "i"}, "ambiguous": ["b"]}) == ({"a": "i"},
                                                                             frozenset({"b"}))
    with pytest.raises(InputError, match="both"):
        validate_instance_map({"map": {"a": "i"}, "ambiguous": ["a"]})


def test_the_instance_map_is_required():
    with pytest.raises(InputError, match="instance map"):
        raw_measure(sessions(2), register(), manifest(), "1")


def test_instance_source_must_be_a_declared_agent_client():
    man = manifest()
    man["instance_source"] = {"client": "not-an-agent"}
    with pytest.raises(InputError, match="not a declared agent client"):
        m(sessions(2), man=man)


def test_no_instance_source_means_no_instances():
    man = manifest()
    del man["instance_source"]
    rep = m(sessions(3), man=man)
    assert rep["inputs"]["agent_instances"] == 0 and rep["item4"]["windows"] == []
    assert rep["inputs"]["agent_sessions"] == 3


def test_an_agent_row_with_no_recorded_client_is_not_an_agent_row():
    c = call(5, "S", "x", versions=dict(VERS, client_name=None))
    rows = sessions(2)
    rep = m(rows, calls=[c], instance_map=measure_map(rows))
    assert {"count": 1, "reason": "call rows with no recorded client: not agent rows"} in \
        rep["skipped"]


def test_incident_instance_places_it_in_item4():
    rows = sessions(120)
    inc = incident("I1", "p.a", session=None, commit="ca", guarded=24)
    inc["instance"] = "s0007"
    rep = m(rows, register(inc))
    assert rep["item4"]["windows"][0]["Q1"] == 1


def test_call_rows_restate_audit_rows_and_are_never_observations():
    # shaped to pass every refusal filter, were it an audit row
    c = dict(call(5, "S", "x"), decision="refused", tool="push", op="push",
             refusal_class="policy", args={"branch": "+x"})
    rep = m(sessions(2), calls=[c], instance_map=dict(measure_map(sessions(2)), x="i"))
    assert rep["item1"]["K"] == 0


# ------------------------------------------------------------------ transcripts
def _transcript(path, ids, version="9.9.9"):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "user", "message": {"content": "hello"}})]
    for i in ids:
        lines.append(json.dumps({"type": "assistant", "version": version, "message": {
            "content": [{"type": "text", "text": "x"},
                        {"type": "tool_use", "id": i, "name": "mcp__gitRobot__read"}]}}))
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def test_index_maps_an_id_to_the_one_file_holding_it(tmp_path):
    _transcript(tmp_path / "conv1.jsonl", ["t1"])
    _transcript(tmp_path / "conv1" / "subagents" / "agent-a.jsonl", ["t2", "t3"], "2.0")
    m_, amb, stats = INST.index_transcripts([tmp_path])
    assert amb == set()
    assert m_ == {"t1": {"instance": "conv1", "client_version": "9.9.9"},
                  "t2": {"instance": "conv1/subagents/agent-a", "client_version": "2.0"},
                  "t3": {"instance": "conv1/subagents/agent-a", "client_version": "2.0"}}
    assert stats["transcript_files"] == 2


def test_an_id_in_two_files_is_left_out_and_counted(tmp_path):
    """Forked subagents copy the parent's history, call ids included: the caller cannot be told
    from the copies, so the id is not assigned to any of them."""
    _transcript(tmp_path / "c" / "subagents" / "agent-a.jsonl", ["dup", "a-only"])
    _transcript(tmp_path / "c" / "subagents" / "agent-b.jsonl", ["dup"])
    m_, amb, stats = INST.index_transcripts([tmp_path])
    assert set(m_) == {"a-only"} and amb == {"dup"} and stats["ids_in_more_than_one_file"] == 1


def test_wanted_limits_the_map_and_text_mentions_are_not_tool_uses(tmp_path):
    _transcript(tmp_path / "c.jsonl", ["t1", "t2"])
    p = tmp_path / "d.jsonl"
    p.write_bytes((json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "id": "t1",
         "source": "tool_use"}]}}) + "\n").encode())
    m_, _, _ = INST.index_transcripts([tmp_path], wanted={"t1"})
    assert m_ == {"t1": {"instance": "c", "client_version": "9.9.9"}}


def test_a_missing_transcript_directory_is_refused(tmp_path):
    with pytest.raises(InputError):
        INST.index_transcripts([tmp_path / "nope"])


# ------------------------------------------------------------------ backfill from the HTTP log
def _http(ts_, cid, session="S", body=None, is_error=False, rpc_id=1, ms=50.0, name="read"):
    req = {"method": "tools/call", "params": {"name": name, "arguments": {}}}
    if cid is not None:
        req["params"]["_meta"] = {INST.CLIENT_CALL_ID_KEY: cid, "progressToken": rpc_id}
    result = {"content": [{"type": "text", "text": json.dumps(body or {"ok": True})}],
              "isError": is_error}
    if not is_error:
        result["structuredContent"] = body or {"ok": True}
    resp = "event: message\r\ndata: " + json.dumps({"jsonrpc": "2.0", "id": rpc_id,
                                                    "result": result}) + "\r\n\r\n"
    return {"ts": ts_, "rpc_method": "tools/call", "tool": name, "session": session,
            "rpc_id": rpc_id, "ms": ms, "req": json.dumps(req), "resp": resp}


def _audit(ts_, pid=7, commit="abc", **kw):
    return dict({"ts": ts_, "op": "status", "decision": "allowed", "pid": pid,
                 "versions": dict(VERS, gitrobot_commit=commit, client_name="claude-code")},
                **kw)


def test_call_outcome_reads_the_body_and_never_guesses():
    assert INST.call_outcome(_http("t", "c")["resp"]) == ("allowed", None, None)
    refused = _http("t", "c", body={"ok": False, "error_type": "refusal", "refusal_id": "r1",
                                    "error": "no"}, is_error=True)
    assert INST.call_outcome(refused["resp"]) == ("refused", "refusal", "r1")
    usage = _http("t", "c", body={"ok": False, "error_type": "usage"}, is_error=True)
    assert INST.call_outcome(usage["resp"]) == ("failed", "usage", None)
    assert INST.call_outcome("event: message\r\ndata: {trunc") == (None, None, None)
    assert INST.call_outcome('data: {"jsonrpc":"2.0","id":1,"error":{"code":-1}}') == \
        ("failed", None, None)


def test_backfill_takes_versions_from_the_server_span_and_the_transcript():
    audit = [_audit("2026-10-01T00:00:00+00:00"), _audit("2026-10-01T02:00:00+00:00")]
    http = [_http("2026-10-01T01:00:00", "t1"), _http("2026-10-01T01:00:05", None, rpc_id=2),
            _http("2026-10-01T03:00:00", "t1", rpc_id=3)]
    tmap = {"t1": {"instance": "c", "client_version": "2.1"}}
    rows, stats = INST.calls_from_http(http, audit, tmap)
    assert [r["ts"] for r in rows] == ["2026-10-01T01:00:00+00:00", "2026-10-01T01:00:05+00:00",
                                       "2026-10-01T03:00:00+00:00"]
    assert rows[0]["versions"] == {"gitrobot_commit": "abc", "gitrobot_dirty": False,
                                   "client_name": "claude-code", "client_version": "2.1",
                                   "consumer_hook_commit": None}
    assert rows[1]["client_call_id"] is None and rows[1]["versions"]["client_name"] is None
    assert "versions" not in rows[2], "outside every server span: nothing is assumed"
    assert stats["outside every audit-row server span: no versions"] == 1


def test_backfill_prefers_the_sessions_own_client_and_counts_a_disagreement():
    """The session's audit rows carry the client's own handshake; that wins over the transcript
    line, and a difference between them is counted, never hidden."""
    audit = [_audit("2026-10-01T00:00:00+00:00", session="S"),
             _audit("2026-10-01T02:00:00+00:00", session="H",
                    versions=dict(VERS, gitrobot_commit="abc", client_name="zp-record"))]
    http = [_http("2026-10-01T01:00:00", "t1", session="S"),
            _http("2026-10-01T01:00:01", None, session="H", rpc_id=2)]
    rows, stats = INST.calls_from_http(http, audit,
                                       {"t1": {"instance": "c", "client_version": "2.1"}})
    assert (rows[0]["versions"]["client_name"], rows[0]["versions"]["client_version"]) ==         ("claude-code", "1")
    assert rows[1]["versions"]["client_name"] == "zp-record"
    assert stats["client differs between session audit rows and transcript"] == 1
    assert stats["client from the session's audit rows"] == 2


def test_a_call_floored_before_the_spans_first_row_is_in_the_span():
    """The call that wrote a process's first row started up to 1 s before its floored ts."""
    audit = [_audit("2026-10-01T00:00:00.300+00:00"), _audit("2026-10-01T02:00:00+00:00")]
    rows, stats = INST.calls_from_http([_http("2026-10-01T00:00:00", "t1")], audit, {})
    assert rows[0]["versions"]["gitrobot_commit"] == "abc", stats


def test_a_call_after_a_spans_last_row_is_not_given_that_spans_version():
    audit = [_audit("2026-10-01T00:00:00+00:00"), _audit("2026-10-01T01:00:00+00:00"),
             _audit("2026-10-01T01:00:01.500+00:00", pid=8, commit="NEW"),
             _audit("2026-10-01T02:00:00+00:00", pid=8, commit="NEW")]
    rows, _ = INST.calls_from_http([_http("2026-10-01T01:00:01", "t1")], audit, {})
    assert rows[0]["versions"]["gitrobot_commit"] == "NEW"


def test_a_call_whose_start_could_be_in_two_spans_gets_no_version():
    audit = [_audit("2026-10-01T00:00:00+00:00"), _audit("2026-10-01T01:00:00.200+00:00"),
             _audit("2026-10-01T01:00:00.800+00:00", pid=8, commit="NEW")]
    rows, stats = INST.calls_from_http([_http("2026-10-01T01:00:00", "t1")], audit, {})
    assert "versions" not in rows[0]
    assert stats["start could be in two server spans: no versions"] == 1


def test_cli_rows_are_not_server_processes():
    audit = [_audit("2026-10-01T00:00:00+00:00"), _audit("2026-10-01T02:00:00+00:00"),
             _audit("2026-10-01T01:00:00+00:00", pid=99, surface="cli")]
    assert [s[2] for s in INST.server_spans(audit)] == [7]


def test_a_session_whose_audit_rows_name_several_clients_gets_a_null_client():
    audit = [_audit("2026-10-01T00:00:00+00:00", session="S"),
             _audit("2026-10-01T02:00:00+00:00", session="S",
                    versions=dict(VERS, gitrobot_commit="abc", client_name="other"))]
    rows, stats = INST.calls_from_http([_http("2026-10-01T01:00:00", "t1", session="S")], audit,
                                       {"t1": {"instance": "c", "client_version": "2.1"}})
    assert rows[0]["versions"]["client_name"] is None
    assert stats["session's audit rows name several clients: client null"] == 1


def test_backfill_rows_use_the_forward_outcome_vocabulary_and_are_marked():
    rows, _ = INST.calls_from_http([_http("2026-10-01T01:00:00", "t1")], [], {})
    assert rows[0]["outcome"] == "returned" and rows[0]["source"] == INST.SOURCE
    assert "decision" not in rows[0]


def test_a_backfill_row_without_a_readable_ts_is_refused():
    bad = _http("2026-10-01T01:00:00", "t1")
    bad["ts"] = "yesterday"
    with pytest.raises(InputError):
        INST.calls_from_http([bad], [], {})


def test_two_server_processes_overlapping_in_time_are_refused():
    audit = [_audit("2026-10-01T00:00:00+00:00", pid=1), _audit("2026-10-01T02:00:00+00:00", pid=1),
             _audit("2026-10-01T01:00:00+00:00", pid=2)]
    with pytest.raises(InputError, match="overlap"):
        INST.server_spans(audit)


# ------------------------------------------------------------------ linking old refusals
def _refused_call(ts_, cid, rid="r1", ms=50.0, session="S", outcome="refused"):
    return {"ts": ts_, "session": session, "client_call_id": cid, "outcome": outcome,
            "refusal_id": rid, "duration_ms": ms, "tool": "read"}


def _refused_audit(ts_, rid="r1", session="S", op="worktree.target"):
    return {"ts": ts_, "op": op, "decision": "refused", "session": session,
            "detail": "[%s] git does not list it" % rid}


def _link(audit_ts, calls, **kw):
    out, stats = INST.link_refusals([_refused_audit(audit_ts, **kw)], calls)
    return out[0].get("client_call_id"), stats


def test_a_refusal_links_to_the_one_call_during_which_it_was_written():
    calls = [_refused_call("2026-10-01T00:00:10+00:00", "A", ms=8000)]
    assert _link("2026-10-01T00:00:17.900+00:00", calls) == ("A", {
        "refused rows without client_call_id": 1, "linked": 1})


@pytest.mark.parametrize("audit_ts,linked", [
    ("2026-10-01T00:00:09.600+00:00", True),     # 0.4 s before the floored start: slack
    ("2026-10-01T00:00:09.400+00:00", False),    # 0.6 s before: outside
    ("2026-10-01T00:00:11.400+00:00", True),     # floor (1 s) + 0 ms + 0.4 s slack
    ("2026-10-01T00:00:11.600+00:00", False),    # past floor + slack
])
def test_the_link_window_is_the_floored_start_plus_one_second_with_slack(audit_ts, linked):
    calls = [_refused_call("2026-10-01T00:00:10+00:00", "A", ms=0)]
    assert (_link(audit_ts, calls)[0] == "A") is linked


def test_no_link_on_a_different_refusal_id_or_session():
    calls = [_refused_call("2026-10-01T00:00:10+00:00", "A", ms=100)]
    assert _link("2026-10-01T00:00:10.5+00:00", calls, rid="other")[1] == {
        "refused rows without client_call_id": 1,
        "unlinked: the one call in progress is not this refusal": 1}
    assert _link("2026-10-01T00:00:10.5+00:00", calls, session="T")[1] == {
        "refused rows without client_call_id": 1, "unlinked: no calls in progress": 1}


def test_two_calls_in_progress_are_never_guessed_between():
    calls = [_refused_call("2026-10-01T00:00:10+00:00", "A"),
             _refused_call("2026-10-01T00:00:10+00:00", "B")]
    cid, stats = _link("2026-10-01T00:00:10.3+00:00", calls)
    assert cid is None and stats["unlinked: several calls in progress"] == 1


def test_a_concurrent_call_with_an_unreadable_body_still_makes_it_ambiguous():
    """Only one REFUSED call overlaps, but another call (outcome unknown) does too: it might be
    the refusal, so nothing links."""
    calls = [_refused_call("2026-10-01T00:00:10+00:00", "A"),
             _refused_call("2026-10-01T00:00:10+00:00", "B", outcome=None)]
    assert _link("2026-10-01T00:00:10.3+00:00", calls)[0] is None


def test_the_one_call_in_progress_must_be_a_refusal_with_an_id():
    for c in (_refused_call("2026-10-01T00:00:10+00:00", "A", outcome="returned"),
              _refused_call("2026-10-01T00:00:10+00:00", None)):
        assert _link("2026-10-01T00:00:10.3+00:00", [c])[0] is None


def test_a_call_links_to_at_most_one_audit_row_and_inputs_are_not_modified():
    calls = [_refused_call("2026-10-01T00:00:10+00:00", "A")]
    a1, a2 = (_refused_audit("2026-10-01T00:00:10.2+00:00"),
              _refused_audit("2026-10-01T00:00:10.4+00:00"))
    out, stats = INST.link_refusals([a1, a2], calls)
    assert [r.get("client_call_id") for r in out] == ["A", None]
    assert "client_call_id" not in a1


def test_rows_that_already_carry_the_id_are_left_alone():
    a = dict(_refused_audit("2026-10-01T00:00:10.2+00:00"), client_call_id="Z")
    out, stats = INST.link_refusals([a], [_refused_call("2026-10-01T00:00:10+00:00", "A")])
    assert out[0]["client_call_id"] == "Z" and "linked" not in stats


# ------------------------------------------------------------------ public fixture redaction
def test_make_fixture_refuses_a_raw_id_in_the_extract():
    import make_fixture
    rows = [{"session": "0123456789abcdef0123456789abcdef", "client_call_id": "toolu_01ABCDEFGH"}]
    imap = {"toolu_01ABCDEFGH": "conv-uuid/subagents/agent-abc"}
    assert make_fixture.scan_raw_ids({"x": "nothing raw"}, rows, [], imap) == []
    for leak in ("toolu_01ABCDEFGH", "conv-uuid/subagents/agent-abc",
                 "0123456789abcdef0123456789abcdef"):
        assert make_fixture.scan_raw_ids({"x": "..%s.." % leak}, rows, [], imap), leak


# ------------------------------------------------------------------ CLI
def test_cli_backfill_instances_and_measure_end_to_end(tmp_path):
    from guard_coverage.cli import main
    tr = tmp_path / "tr"
    _transcript(tr / "conv.jsonl", ["t1"])
    _transcript(tr / "conv" / "subagents" / "agent-a.jsonl", ["t2", "t3"])
    audit = [_audit("2026-10-01T00:00:00+00:00", surface="mcp", session="S",
                    refusal_class=None),
             dict(_audit("2026-10-01T00:00:02.4+00:00", surface="mcp", session="S",
                         refusal_class="policy"), op="push", decision="refused",
                  args={"branch": "+x"}, detail="[r9] refspec"),
             _audit("2026-10-01T02:00:00+00:00", surface="mcp", session="S",
                    refusal_class=None)]
    (tmp_path / "a.jsonl").write_bytes("".join(json.dumps(r) + "\n" for r in audit).encode())
    http = [_http("2026-10-01T00:00:00", "t1"),     # over by 00:00:01.55: not in progress
            _http("2026-10-01T00:00:02", "t2", rpc_id=2, name="push", is_error=True,
                  body={"ok": False, "error_type": "refusal", "refusal_id": "r9"}),
            _http("2026-10-01T00:00:03", "t3", rpc_id=3)]
    (tmp_path / "h.jsonl").write_bytes("".join(json.dumps(r) + "\n" for r in http * 2).encode())
    rc = main(["backfill", "--http", str(tmp_path / "h.jsonl"), "--audit",
               str(tmp_path / "a.jsonl"), "--transcripts", str(tr), "--out-calls",
               str(tmp_path / "c.jsonl"), "--out-audit", str(tmp_path / "al.jsonl")])
    assert rc == 0
    calls = [json.loads(x) for x in (tmp_path / "c.jsonl").read_text().splitlines()]
    assert len(calls) == 3, "a request in two copies of the log is kept once"
    linked = [json.loads(x) for x in (tmp_path / "al.jsonl").read_text().splitlines()]
    assert [r.get("client_call_id") for r in linked] == [None, "t2", None]
    assert main(["instances", "--calls", str(tmp_path / "c.jsonl"), "--audit",
                 str(tmp_path / "al.jsonl"), "--transcripts", str(tr), "--out",
                 str(tmp_path / "m.json")]) == 0
    imap = json.loads((tmp_path / "m.json").read_text())["map"]
    assert imap == {"t1": "conv", "t2": "conv/subagents/agent-a", "t3": "conv/subagents/agent-a"}
    man = manifest(guard("gitrobot", GR, {}, version_at=-1000))
    man["agent_clients"], man["instance_source"] = ["claude-code"], {"client": "claude-code"}
    (tmp_path / "man.json").write_text(json.dumps(man))
    (tmp_path / "reg.json").write_text(json.dumps(register()))
    base = ["measure", "--audit", str(tmp_path / "al.jsonl"), "--calls",
            str(tmp_path / "c.jsonl"), "--register", str(tmp_path / "reg.json"),
            "--manifest", str(tmp_path / "man.json"), "--json"]
    import io
    import contextlib
    outs = []
    for src in (["--instances", str(tmp_path / "m.json")], ["--transcripts", str(tr)]):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert main(base + src) == 0
        outs.append(json.loads(buf.getvalue()))
    assert outs[0] == outs[1]
    rep = outs[0]
    assert rep["inputs"]["agent_instances"] == 2
    assert rep["item1"]["K"] == 1 and rep["inputs"]["policy_refusal_observations"] == 1
    w = rep["item4"]["windows"][0]
    assert (w["n"], w["Q1"]) == (2, 1)


def test_make_fixture_end_to_end_hashes_every_id_and_reproduces_the_report(tmp_path):
    import make_fixture
    rows = sessions(3) + [refusal(5, session="s0001")]
    calls = [dict(call(6, "s0002", "toolu_read_only"), source="http_calls backfill")]
    imap = dict(measure_map(rows), toolu_read_only="x")
    imap = {k: "conv/subagents/agent-" + v for k, v in imap.items()}
    files = {"a.jsonl": "".join(json.dumps(r) + "\n" for r in rows),
             "c.jsonl": "".join(json.dumps(r) + "\n" for r in calls),
             "m.json": json.dumps({"map": imap}),
             "r.json": json.dumps(register(incident("I1", "p.a", session="s0001",
                                                    commit="c1"))),
             "man.json": json.dumps(manifest())}
    for k, v in files.items():
        (tmp_path / k).write_bytes(v.encode())
    out = tmp_path / "out"
    rc = make_fixture.main(["--audit", str(tmp_path / "a.jsonl"), "--calls",
                            str(tmp_path / "c.jsonl"), "--instances", str(tmp_path / "m.json"),
                            "--register", str(tmp_path / "r.json"), "--manifest",
                            str(tmp_path / "man.json"), "--out", str(out), "--salt", "ab"])
    assert rc == 0
    text = "".join((out / n).read_bytes().decode() for n in make_fixture.FILES
                   if n != "manifest.json")
    for raw in list(imap) + list(imap.values()):
        assert raw not in text, raw
    red = json.loads((out / "instances.json").read_bytes())["map"]
    assert len(red) == len(imap) and all(len(k) == len(v) == 16 for k, v in red.items())
    c = json.loads((out / "calls.jsonl").read_bytes().decode().splitlines()[0])
    assert c["client_call_id"] == make_fixture.h("ab", "toolu_read_only", "call")
    assert c["source"] == "http_calls backfill"
    assert red[make_fixture.h("ab", "toolu_read_only", "call")] == make_fixture.h(
        "ab", "conv/subagents/agent-x", "instance")
    audit = [json.loads(x) for x in (out / "audit.jsonl").read_bytes().decode().splitlines()]
    assert all(r["client_call_id"] == make_fixture.h("ab", src["client_call_id"], "call")
               for r, src in zip(audit, rows))


def test_the_hash_namespaces_are_separate():
    import make_fixture
    v = "00000000-1111-4222-8333-444444444444"
    assert len({make_fixture.h("s", v), make_fixture.h("s", v, "call"),
                make_fixture.h("s", v, "instance")}) == 3


def test_make_fixture_scans_raw_register_ids():
    import make_fixture
    reg = [{"session": "conversation-uuid-1234", "instance": "conversation-uuid-1234/sub"}]
    assert make_fixture.scan_raw_ids({"x": "conversation-uuid-1234"}, [], [], {}, reg)
    assert make_fixture.scan_raw_ids({"x": ".. conversation-uuid-1234/sub .."}, [], [],
                                     {}, [{"instance": "conversation-uuid-1234/sub"}])
    assert make_fixture.scan_raw_ids({"x": "nothing"}, [], [], {}, reg) == []
