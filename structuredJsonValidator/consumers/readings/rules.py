"""Business rules for ``blind_readings``. The schema checks shapes; these check
that the fields AGREE with each other, because ``key_kind`` is the caller's claim
about which key applies and is never trusted on its own.

The cross-collection rule (a non-null ``registry_id`` must name a real declaration)
is store-level: :func:`consumers.store.readings_reference_integrity`.
"""

from __future__ import annotations


def _key_violations(where: str, e: dict) -> list[str]:
    out: list[str] = []
    kk, rid, reason = e.get("key_kind"), e.get("registry_id"), e.get("registry_id_reason")
    line = e.get("line")
    if kk == "registry_id":
        if not rid:
            out.append(f"{where}: key_kind 'registry_id' with a null registry_id; use "
                       f"'decl_name' with a registry_id_reason when no entry exists")
    elif rid is not None:
        out.append(f"{where}: registry_id is set but key_kind is {kk!r}; an entry that "
                   f"has a registry id is keyed on it")
    if kk == "decl_name" and not (reason or "").strip():
        out.append(f"{where}: key_kind 'decl_name' needs registry_id_reason saying why "
                   f"there is no registry entry")
    if kk in ("example_line", "prose_line") and not isinstance(line, int):
        out.append(f"{where}: key_kind {kk!r} keys on (path, blob, line) and line is "
                   f"{line!r}")
    if kk == "example_line" and e.get("kind") == "reading" and e.get("is_example") is not True:
        out.append(f"{where}: key_kind 'example_line' on a reading that is not an example")
    if e.get("kind") == "reading" and e.get("is_example") is True and kk != "example_line":
        out.append(f"{where}: an example reading must use key_kind 'example_line'")
    return out


def validate(document: dict) -> list[str]:
    out: list[str] = []
    runs = document.get("runs", [])
    by_run: dict = {}
    for i, r in enumerate(runs):
        rid = r.get("run_id")
        if rid in by_run:
            out.append(f"runs[{i}]: duplicate run_id {rid!r}")
        by_run[rid] = r
    seen: dict = {}
    diff1_per_run: dict = {}
    for i, e in enumerate(document.get("entries", [])):
        where = f"entries[{i}] ({e.get('id')!r})"
        if e.get("id") in seen:
            out.append(f"{where}: duplicate id (first at entries[{seen[e.get('id')]}])")
        seen.setdefault(e.get("id"), i)
        run = by_run.get(e.get("run_id"))
        if run is None:
            out.append(f"{where}: run_id {e.get('run_id')!r} names no indexed run")
        else:
            examined = {(x.get("path"), x.get("git_blob_id")) for x in run.get("examined", [])}
            if (e.get("path"), e.get("git_blob_id")) not in examined:
                out.append(f"{where}: ({e.get('path')}, {e.get('git_blob_id')}) is not in "
                           f"its run's `examined`; a run reports findings only on bytes it "
                           f"says it read")
        out.extend(_key_violations(where, e))
        if e.get("kind") == "diff1":
            diff1_per_run[e.get("run_id")] = diff1_per_run.get(e.get("run_id"), 0) + 1
            evs = e.get("dispositions") or []
            if not evs:
                out.append(f"{where}: a DIFF-1 item with no disposition")
            for j, ev in enumerate(evs):
                if ev.get("disposition") != "open" and not (
                        (ev.get("reason") or "").strip() and (ev.get("decided_by") or "").strip()):
                    out.append(f"{where}: dispositions[{j}] is {ev.get('disposition')!r} "
                               f"with no reason or decided_by; only 'open' may be "
                               f"unattributed")
            for k in ("prose", "signature", "diff_kind"):
                if k not in e:
                    out.append(f"{where}: a DIFF-1 item without {k!r}")
        elif e.get("kind") == "reading":
            if "dispositions" in e or "prose" in e:
                out.append(f"{where}: a reading carries DIFF-1 fields")
    for rid, r in by_run.items():
        have = diff1_per_run.get(rid, 0)
        if r.get("diff1_count") != have:
            out.append(f"run {rid!r}: diff1_count says {r.get('diff1_count')} and "
                       f"{have} DIFF-1 item(s) are indexed")
    return out
