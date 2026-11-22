"""The GitHub source: a reservoir-index repo fetched as a tarball into a local cache.

Same route as Reservoir's own website workflow: `GET /repos/<repo>/tarball`, extract, read the
tree with the same loader as a local directory. Added 2026-11-22 on an addendum agreed with Tim,
so that anyone can run the server against the OFFICIAL index (leanprover/reservoir-index) with no
setup; a local directory is the optional "complete" mode.

⚠ CACHE LAYOUT, and why the swap is a rename: `<cache>/current/` is the extracted tree and
`<cache>/meta.json` says which repo and commit it is. A refresh extracts into a fresh sibling and
renames it over `current`, so a reader never sees a half-extracted tree. A failed refresh keeps
serving the old cache and says so in `status`; with no cache at all it refuses as `unavailable`,
because an empty index answering "no results" would read as a real answer.

⚠ Before downloading, the branch head is asked for (one small API call). If it equals the cached
commit, only `fetched_at` moves. The repo is ~700 MB of history; the tarball is HEAD only.
"""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

API = "https://api.github.com"
UA = "reservoirSearch (MCP server)"


def default_cache() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") \
        or str(Path.home() / ".cache")
    return Path(base) / "reservoirSearch"


def _headers(token: Optional[str], accept: str) -> dict:
    h = {"User-Agent": UA, "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


class GitHubSource:
    def __init__(self, repo: str, cache: Path, ttl_seconds: float, token: Optional[str] = None,
                 opener=None):
        self.repo = repo
        self.cache = Path(cache)
        self.ttl = ttl_seconds
        self.token = token
        self._open = opener or urllib.request.urlopen
        self.last_error: Optional[str] = None

    @property
    def current(self) -> Path:
        return self.cache / "current"

    def meta(self) -> dict:
        try:
            return json.loads((self.cache / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_meta(self, meta: dict) -> None:
        tmp = self.cache / "meta.json.tmp"
        tmp.write_bytes(json.dumps(meta, indent=1).encode("utf-8"))
        os.replace(tmp, self.cache / "meta.json")

    def due(self) -> bool:
        m = self.meta()
        if not self.current.is_dir() or m.get("repo") != self.repo:
            return True
        return (time.time() - float(m.get("fetched_epoch") or 0)) >= self.ttl

    def head(self) -> Optional[str]:
        req = urllib.request.Request(f"{API}/repos/{self.repo}/commits/HEAD",
                                     headers=_headers(self.token, "application/vnd.github.sha"))
        with self._open(req, timeout=30) as r:
            return r.read().decode("ascii").strip() or None

    def refresh(self, force: bool = False) -> bool:
        """Bring the cache up to date. True if the tree on disk changed. Raises on failure; the
        caller decides whether a stale cache may keep serving."""
        self.cache.mkdir(parents=True, exist_ok=True)
        m = self.meta()
        sha = None
        try:
            sha = self.head()
        except Exception:
            sha = None                     # fall through to a full fetch, which reports its error
        if (not force and sha and sha == m.get("commit") and m.get("repo") == self.repo
                and self.current.is_dir()):
            m["fetched_epoch"] = time.time()
            m["fetched_at"] = _now()
            self._write_meta(m)
            return False
        req = urllib.request.Request(f"{API}/repos/{self.repo}/tarball",
                                     headers=_headers(self.token, "application/vnd.github+json"))
        work = Path(tempfile.mkdtemp(prefix="fetch-", dir=self.cache))
        try:
            tgz = work / "index.tar.gz"
            with self._open(req, timeout=600) as r, open(tgz, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            out = work / "x"
            out.mkdir()
            with tarfile.open(tgz, "r:gz") as tf:
                tf.extractall(out, filter="data")      # refuses absolute paths and ../ escapes
            tops = [p for p in out.iterdir() if p.is_dir()]
            if len(tops) != 1:
                raise RuntimeError(f"tarball has {len(tops)} top-level dirs, expected 1")
            top = tops[0]
            commit = sha or top.name.rsplit("-", 1)[-1]   # <owner>-<repo>-<sha>
            old = self.cache / "old"
            if old.exists():
                shutil.rmtree(old, ignore_errors=True)
            if self.current.exists():
                os.replace(self.current, old)
            os.replace(top, self.current)
            shutil.rmtree(old, ignore_errors=True)
            self._write_meta({"repo": self.repo, "commit": commit, "fetched_at": _now(),
                              "fetched_epoch": time.time(),
                              "tarball_bytes": tgz.stat().st_size})
            return True
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def describe(self) -> dict:
        m = self.meta()
        return {"kind": "github", "repo": self.repo, "commit": m.get("commit"),
                "fetched_at": m.get("fetched_at"), "ttl_hours": round(self.ttl / 3600, 2),
                "cache": str(self.cache), "authenticated": bool(self.token),
                "last_refresh_error": self.last_error}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
