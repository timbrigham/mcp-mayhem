"""The Lean Reservoir index, loaded once and searched in memory.

The data is a directory tree in leanprover/reservoir-index's format (the index's own README is the
authority on it):

    <owner>/<name>/metadata.json   flat object
    <owner>/<name>/versions.json   {"schemaVersion", "data": [...]}, NEWEST FIRST
    <owner>/<name>/builds.json     {"schemaVersion", "data": [...]}, may be empty
    <owner>/<name>                 a FILE, not a dir: {"alias": {"from", "to"}} for a rename

⚠ THE INDEX IS REPLACED IN PLACE. A partial index (959 packages, 2026-11-22) is due to be swapped
for a complete one in the same directory. So every answer carries `loaded_at` and the counts it was
computed from, a stale load is detected by a cheap stat fingerprint before each call, and a package
that fails to parse is reported in `skipped` rather than silently missing or fatal. Measured on the
first load: `katzenpost/crypt_walker` has no metadata.json, which one bad file must not turn into
an index that refuses to load.

⚠ "DEPENDS ON" IS RESOLVED BY URL FIRST. A dependency names its Lake package (`mathlib`) and a
scope (`leanprover-community`), which usually maps to `<scope>/<name>` on disk. The url is the
repository, which is what identifies the thing (mathlib's repo is `mathlib4`). 1,945 of 6,806
latest-version dependency entries carried no scope at all on the first load, so the url is the only
key for those. Urls arrive as `https://github.com/o/r`, `...r.git` and `git@github.com:o/r.git`,
normalised to `github.com/o/r`.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_ROOT = r"C:\Workspace\reservoir-index"
MAX_ALIAS_HOPS = 8


class ReservoirError(Exception):
    """A deliberate refusal: `what` failed, and `satisfied_when` says what would succeed."""

    def __init__(self, what: str, satisfied_when: str, error_type: str = "usage"):
        super().__init__(what)
        self.satisfied_when = satisfied_when
        self.error_type = error_type


def norm_url(url: Optional[str]) -> Optional[str]:
    """`https://GitHub.com/O/R.git/` and `git@github.com:o/r.git` -> `github.com/o/r`."""
    if not url or not isinstance(url, str):
        return None
    u = url.strip().lower()
    m = re.match(r"^[a-z0-9.+-]+@([^:/]+):(.*)$", u)          # scp-like git@host:path
    if m:
        u = f"{m.group(1)}/{m.group(2)}"
    u = re.sub(r"^[a-z][a-z0-9+.-]*://", "", u)              # scheme
    u = re.sub(r"^[^@/]+@", "", u)                            # user@ in a url
    u = u.rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    return u.rstrip("/") or None


def norm_toolchain(tc: Optional[str]) -> Optional[str]:
    """`leanprover/lean4:v4.35.0`, `v4.35.0` and `4.35.0` all -> `v4.35.0`. Exact, not a prefix:
    `v4.36.0-rc2` is a different toolchain from `v4.36.0`."""
    if not tc or not isinstance(tc, str):
        return None
    t = tc.strip().lower()
    if ":" in t:
        t = t.rsplit(":", 1)[1]
    if t and t[0].isdigit():
        t = "v" + t
    return t or None


def _read(path: Path):
    return json.loads(path.read_bytes().decode("utf-8-sig"))


def fingerprint(root: Path) -> tuple:
    """Cheap change detector: the root and every owner directory's mtime and entry count.

    ⚠ It sees entries added, removed or renamed at either level, which is what a swap does. It does
    NOT see a file rewritten in place inside an unchanged package dir (an NTFS dir mtime does not
    move for that). `reload` is the answer for that case, and `status` says so.
    """
    try:
        st = root.stat()
        parts = [(st.st_mtime_ns,)]
        with os.scandir(root) as it:
            for e in sorted(it, key=lambda e: e.name):
                if e.name.startswith("."):
                    continue
                # ⚠ os.stat, NOT DirEntry.stat(). On Windows the DirEntry's times come from the
                # parent's directory listing, which NTFS updates lazily: measured on a fresh test
                # fixture, an untouched directory's fingerprint changed between two consecutive
                # calls, and every call paid a full reload.
                s = os.stat(e.path)
                parts.append((e.name, s.st_mtime_ns, e.is_dir()))
        return tuple(parts)
    except OSError:
        return ("unreadable",)


class Index:
    """One immutable load. A reload builds a new Index and swaps the reference."""

    def __init__(self, root: Path):
        self.root = root
        self.packages: dict = {}          # "owner/name" (lowercase) -> package dict
        self.aliases: dict = {}           # "owner/name" (lowercase) -> target key
        self.by_repo: dict = {}           # normalised repo url -> key
        self.skipped: list = []           # {"entry", "error"}
        self.dependents: dict = {}        # target key -> [edge]
        self.unresolved_deps = 0
        self.loaded_at = None
        self.load_seconds = None
        self.fingerprint = None

    # -- load -------------------------------------------------------------------------------
    @classmethod
    def load(cls, root) -> "Index":
        root = Path(root)
        if not root.is_dir():
            raise ReservoirError(f"index directory {str(root)!r} does not exist",
                                 "set RESERVOIR_INDEX to a directory in reservoir-index format "
                                 "(<owner>/<name>/metadata.json), then call reload",
                                 error_type="config")
        t0 = time.perf_counter()
        idx = cls(root)
        idx.fingerprint = fingerprint(root)
        for owner in sorted(root.iterdir(), key=lambda p: p.name):
            if owner.name.startswith(".") or not owner.is_dir():
                continue
            for entry in sorted(owner.iterdir(), key=lambda p: p.name):
                key = f"{owner.name}/{entry.name}".lower()
                try:
                    if entry.is_file():
                        a = _read(entry)["alias"]
                        idx.aliases[key] = str(a["to"]).lower()
                    else:
                        idx._add_package(key, entry)
                except Exception as exc:                       # one bad entry, never the index
                    idx.skipped.append({"entry": key, "error": f"{type(exc).__name__}: {exc}"})
        idx._link()
        idx.loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        idx.load_seconds = round(time.perf_counter() - t0, 3)
        return idx

    def _add_package(self, key: str, d: Path) -> None:
        meta = _read(d / "metadata.json")
        versions = _read(d / "versions.json").get("data") or []
        bpath = d / "builds.json"
        builds = (_read(bpath).get("data") or []) if bpath.exists() else []
        latest = versions[0] if versions else {}
        repos = [norm_url(s.get("repoUrl")) for s in meta.get("sources") or []]
        repos += [norm_url(s.get("gitUrl")) for s in meta.get("sources") or []]
        repos = [r for r in dict.fromkeys(repos) if r]
        haystack = " ".join([str(meta.get("fullName") or key), str(meta.get("description") or ""),
                             " ".join(str(k) for k in meta.get("keywords") or [])]).lower()
        self.packages[key] = {
            "key": key, "meta": meta, "versions": versions, "builds": builds,
            "latest": latest, "toolchain": norm_toolchain(latest.get("toolchain")),
            "repos": repos, "haystack": haystack,
            "stars": meta.get("stars") if isinstance(meta.get("stars"), int) else 0,
        }
        for r in repos:
            self.by_repo.setdefault(r, key)

    def _link(self) -> None:
        for key, p in self.packages.items():
            for dep in p["latest"].get("dependencies") or []:
                target, how = self._resolve_dep(dep)
                if target is None:
                    self.unresolved_deps += 1
                    continue
                self.dependents.setdefault(target, []).append({
                    "dependent": key, "transitive": bool(dep.get("transitive")),
                    "matched_by": how, "rev": dep.get("rev"), "inputRev": dep.get("inputRev"),
                    "url": dep.get("url")})

    def _resolve_dep(self, dep: dict):
        u = norm_url(dep.get("url"))
        if u and u in self.by_repo:
            return self.by_repo[u], "url"
        if dep.get("scope") and dep.get("name"):
            k = self.resolve_key(f"{dep['scope']}/{dep['name']}")
            if k:
                return k, "scope/name"
        return None, None

    # -- lookups ----------------------------------------------------------------------------
    def resolve_key(self, name: str) -> Optional[str]:
        """owner/name, case-insensitive, following alias stubs. None if nothing matches."""
        k = (name or "").strip().strip("/").lower()
        for _ in range(MAX_ALIAS_HOPS):
            if k in self.packages:
                return k
            if k in self.aliases:
                k = self.aliases[k]
                continue
            return None
        return None

    def require(self, name: str) -> str:
        if not name or "/" not in name.strip().strip("/"):
            raise ReservoirError(f"{name!r} is not owner/name",
                                 "pass the package as owner/name, e.g. "
                                 "'leanprover-community/mathlib'; search(query) finds it by word")
        k = self.resolve_key(name)
        if k is None:
            raise ReservoirError(f"no package or alias {name!r} in this index ({len(self.packages)} "
                                 f"packages, loaded {self.loaded_at})",
                                 "pass an owner/name that search() returns; the index may also be "
                                 "partial, so absence here is not absence from Reservoir",
                                 error_type="not_found")
        return k

    def card(self, p: dict) -> dict:
        m = p["meta"]
        srcs = m.get("sources") or [{}]
        return {"fullName": m.get("fullName") or p["key"], "description": m.get("description"),
                "stars": p["stars"], "license": m.get("license"),
                "toolchain": p["latest"].get("toolchain"),
                "latest_version": p["latest"].get("version"), "latest_date": p["latest"].get("date"),
                "repoUrl": srcs[0].get("repoUrl"), "builds": len(p["builds"])}


def summary(idx: Index) -> dict:
    """What every answer was computed from: an index that is replaced in place must say which."""
    return {"loaded_at": idx.loaded_at, "packages": len(idx.packages),
            "aliases": len(idx.aliases), "skipped": len(idx.skipped)}


class Store:
    """Holds the current Index, reloading when the directory's fingerprint moves."""

    def __init__(self, root=None):
        self.root = Path(root or os.environ.get("RESERVOIR_INDEX") or DEFAULT_ROOT)
        self._lock = threading.Lock()
        self._idx: Optional[Index] = None
        self.reloads = 0

    def get(self) -> Index:
        idx = self._idx
        if idx is not None and fingerprint(self.root) == idx.fingerprint:
            return idx
        with self._lock:
            if self._idx is None or fingerprint(self.root) != self._idx.fingerprint:
                self._idx = Index.load(self.root)
                self.reloads += 1
            return self._idx

    def reload(self) -> Index:
        with self._lock:
            self._idx = Index.load(self.root)
            self.reloads += 1
            return self._idx

    # -- the tools --------------------------------------------------------------------------
    def search(self, query: str = "", toolchain: Optional[str] = None,
               license: Optional[str] = None, owner: Optional[str] = None,
               limit: int = 20) -> dict:
        idx = self.get()
        terms = [t for t in (query or "").lower().split() if t]
        tc = norm_toolchain(toolchain)
        lic = (license or "").strip().lower() or None
        own = (owner or "").strip().lower() or None
        if not (terms or tc or lic or own):
            raise ReservoirError("search needs a query or at least one filter",
                                 "pass query='<words>' (all must match name, description or "
                                 "keywords), or a toolchain / license / owner filter")
        hits = [p for p in idx.packages.values()
                if all(t in p["haystack"] for t in terms)
                and (tc is None or p["toolchain"] == tc)
                and (lic is None or str(p["meta"].get("license") or "").lower() == lic)
                and (own is None or p["key"].split("/", 1)[0] == own)]
        hits.sort(key=lambda p: (-p["stars"], p["key"]))
        limit = max(0, int(limit))
        return {"total": len(hits), "truncated": max(0, len(hits) - limit),
                "results": [idx.card(p) for p in hits[:limit]], "index": summary(idx)}

    def get_package(self, name: str, versions_limit: int = 20) -> dict:
        idx = self.get()
        key = idx.require(name)
        p = idx.packages[key]
        vs = [{k: v.get(k) for k in ("version", "revision", "date", "tag", "toolchain")}
              for v in p["versions"]]
        n = max(0, int(versions_limit))
        return {"requested": name, "key": key, "resolved_alias": key != name.strip().strip("/").lower(),
                "metadata": p["meta"], "latest": p["latest"],
                "versions_total": len(vs), "versions": vs[:n], "versions_truncated": max(0, len(vs) - n),
                "builds_total": len(p["builds"]), "builds_latest": p["builds"][:5],
                "readme_note": "readme text is not in the index; latest.readmeFile names the file "
                               "in the repo at latest.revision",
                "index": summary(idx)}

    def dependents(self, name: str, include_transitive: bool = False, limit: int = 100) -> dict:
        idx = self.get()
        key = idx.require(name)
        edges = idx.dependents.get(key, [])
        direct = sum(1 for e in edges if not e["transitive"])
        chosen = [e for e in edges if include_transitive or not e["transitive"]]
        chosen.sort(key=lambda e: (-idx.packages[e["dependent"]]["stars"], e["dependent"]))
        limit = max(0, int(limit))
        out = []
        for e in chosen[:limit]:
            card = idx.card(idx.packages[e["dependent"]])
            out.append({**card, "transitive": e["transitive"], "matched_by": e["matched_by"],
                        "rev": e["rev"], "inputRev": e["inputRev"]})
        return {"package": idx.packages[key]["meta"].get("fullName") or key, "key": key,
                "direct": direct, "transitive": len(edges) - direct,
                "total": len(chosen), "truncated": max(0, len(chosen) - limit),
                "results": out,
                "scope": "packages whose LATEST version lists this one as a dependency",
                "index": {**summary(idx), "unresolved_dependency_entries": idx.unresolved_deps}}

    def builds_on(self, toolchain: str, limit: int = 100) -> dict:
        idx = self.get()
        tc = norm_toolchain(toolchain)
        if tc is None:
            raise ReservoirError(f"{toolchain!r} is not a toolchain",
                                 "pass a Lean version such as 'v4.35.0', '4.35.0' or "
                                 "'leanprover/lean4:v4.35.0'")
        hits = sorted((p for p in idx.packages.values() if p["toolchain"] == tc),
                      key=lambda p: (-p["stars"], p["key"]))
        limit = max(0, int(limit))
        return {"toolchain": tc, "total": len(hits), "truncated": max(0, len(hits) - limit),
                "results": [idx.card(p) for p in hits[:limit]],
                "scope": "packages whose LATEST version targets exactly this toolchain",
                "index": summary(idx)}

    def toolchains(self) -> dict:
        idx = self.get()
        counts: dict = {}
        for p in idx.packages.values():
            counts[p["toolchain"] or "(none)"] = counts.get(p["toolchain"] or "(none)", 0) + 1
        rows = sorted(({"toolchain": k, "packages": v} for k, v in counts.items()),
                      key=lambda r: (-r["packages"], r["toolchain"]))
        return {"toolchains": rows, "index": summary(idx)}

    def status(self) -> dict:
        idx = self.get()
        return {"root": str(self.root), **summary(idx), "load_seconds": idx.load_seconds,
                "reloads": self.reloads, "skipped_entries": idx.skipped,
                "unresolved_dependency_entries": idx.unresolved_deps,
                "freshness": "reloaded automatically when an entry is added, removed or renamed at "
                             "the top two levels; a file rewritten in place inside an existing "
                             "package dir is NOT detected, so call reload() after such an edit"}
