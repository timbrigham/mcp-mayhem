"""The handler library: operation-mediated writes with pre/post validation.

The :class:`Registry` is project-agnostic. A consumer wires it up with a schema,
a business validator, a set of operations (verbs), and views. Every write:

  1. verifies file integrity against the audit log (drift → halt);
  2. runs the operation on a deep copy of the current document;
  3. validates the *result* (structural + business) as a postcondition;
  4. atomically writes only if valid;
  5. appends an audit record with the resulting SHA-256.

No raw field edits ever reach the file — only verbs do (spec §2 principle 3).
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Callable, Optional

from core import audit, query, store
from core.errors import IntegrityError, OperationError, ValidationError
from core.schema import structural_violations

# An operation takes the current document (or None when bootstrapping) plus typed
# params, and returns (resulting_document, list_of_touched_ids).
Operation = Callable[..., tuple[dict, list[str]]]
BusinessValidator = Callable[[dict], list[str]]
View = Callable[[dict], str]

# A write receipt echoes touched ids only up to this many; beyond it the caller
# gets just a count (the full list stays in the audit log). Keeps bulk-op
# returns from blowing an agent's token budget (interop issue #6).
_MAX_TOUCHED_ECHO = 25


class Registry:
    def __init__(
        self,
        *,
        data_path: str | os.PathLike,
        schema: dict,
        business_validator: BusinessValidator,
        operations: dict[str, Operation],
        views: Optional[dict[str, View]] = None,
        entries_key: str = "entries",
        id_key: str = "id",
        audit_path: Optional[str | os.PathLike] = None,
        vocab_path: Optional[str | os.PathLike] = None,
        actor: str = "cli",
    ):
        self.data_path = Path(data_path)
        self.schema = schema
        self.business_validator = business_validator
        self.operations = dict(operations)
        self.views = dict(views or {})
        self.entries_key = entries_key
        self.id_key = id_key
        self.audit_path = Path(audit_path) if audit_path else audit.default_audit_path(data_path)
        # Default location for the caller-owned ontology vocab config: alongside
        # the registry in the same data folder (interop tag-vocab work item).
        self.vocab_path = Path(vocab_path) if vocab_path else self.data_path.parent / "tag_vocab.json"
        self.actor = actor

    # -- helpers ---------------------------------------------------------------

    def exists(self) -> bool:
        return self.data_path.exists()

    def load(self) -> dict:
        return store.read_json(self.data_path)

    def _entries(self, document: dict) -> list[dict]:
        return document.get(self.entries_key, [])

    def all_violations(self, document: dict) -> list[str]:
        """Structural violations followed by business-rule violations."""
        return structural_violations(document, self.schema) + list(
            self.business_validator(document)
        )

    def _audit_exists(self) -> bool:
        return self.audit_path.exists() and audit.last_record(self.audit_path) is not None

    # -- validation & integrity ------------------------------------------------

    def validate(self) -> list[str]:
        """Full-file conformance (structural + business). Never raises; returns
        the violation list so the CLI can print all and exit non-zero (spec §9)."""
        return self.all_violations(self.load())

    def verify_integrity(self) -> str:
        """Recompute file hash, compare to last audit hash; raise on drift."""
        return audit.verify_integrity(self.data_path, self.audit_path)

    # -- writes ----------------------------------------------------------------

    def seal(self, *, actor: Optional[str] = None) -> dict:
        """Adopt an existing (or freshly hand-written) file as the managed
        baseline: validate it, normalize its bytes, and record the first hash.
        Required before :meth:`apply` on a file not created via a bootstrap op.
        """
        document = self.load()
        violations = self.all_violations(document)
        if violations:
            raise ValidationError(violations)
        sha = store.atomic_write_json(self.data_path, document)
        return audit.append_record(
            self.audit_path,
            actor=actor or self.actor,
            op="seal",
            params={},
            entries_touched=[],
            resulting_sha256=sha,
        )

    def apply(self, op_name: str, params: dict[str, Any], *, actor: Optional[str] = None) -> dict:
        """Run a write operation end-to-end with full guarantees."""
        if op_name not in self.operations:
            raise OperationError(
                f"Unknown operation {op_name!r}. Known: {', '.join(sorted(self.operations))}"
            )
        op = self.operations[op_name]

        # (1) integrity gate — only meaningful once a baseline exists.
        if self._audit_exists():
            self.verify_integrity()
        current: Optional[dict] = self.load() if self.exists() else None

        # (2) run the operation on an isolated deep copy. An op returns either
        # (doc, touched) or (doc, touched, extra) — extra is merged into the
        # receipt (e.g. reconcile's drift summary).
        working = copy.deepcopy(current)
        try:
            op_result = op(working, **params)
        except TypeError as exc:
            raise OperationError(f"Bad parameters for {op_name!r}: {exc}") from exc
        if len(op_result) == 3:
            result_doc, touched, extra = op_result
        else:
            result_doc, touched = op_result
            extra = None

        # (3) postcondition: the result must fully conform.
        violations = self.all_violations(result_doc)
        if violations:
            raise ValidationError(violations)

        # (4) atomic write, then (5) audit append.
        sha = store.atomic_write_json(self.data_path, result_doc)
        audit.append_record(
            self.audit_path,
            actor=actor or self.actor,
            op=op_name,
            params=params,
            entries_touched=touched,  # audit keeps the full list regardless
            resulting_sha256=sha,
        )
        # Terse receipt, not the warehouse (interop issue #6): echo ids only for
        # small results so a bulk op (e.g. a 1k-entry import) can't blow the
        # caller's token budget. The full list is always in the audit log.
        result = {"op": op_name, "touched_count": len(touched), "resulting_sha256": sha}
        if len(touched) <= _MAX_TOUCHED_ECHO:
            result["entries_touched"] = touched
        if extra:
            result.update(extra)
        return result

    def export_full(self, dest_path: str | os.PathLike, *, actor: Optional[str] = None) -> dict:
        """Publish the COMPLETE registry as a deterministic, schema-valid artifact.

        This is the publication dump (distinct from :meth:`export_view`, which
        renders a lossy projection). ``sjv`` owns the (possibly hidden) source
        path; the caller only *triggers* this dump to a public path — e.g. inside
        a consuming repo — then commits that file with normal git. The caller
        never writes registry content directly.

        Guarantees:
          * validates first (structural + business) and REFUSES to dump an
            invalid registry;
          * refuses to dump a drifted source (integrity gate, when sealed);
          * deterministic bytes — entries sorted by id, keys sorted recursively,
            stable 2-space formatting — so git diffs are meaningful;
          * records the export (source state + artifact hash + dest) in the audit
            log, so a published artifact is traceable to the exact source state.

        The audit record's ``resulting_sha256`` stays equal to the (unchanged)
        source hash so the integrity chain over the *source* file is preserved;
        the exported artifact's own hash is recorded as ``export_sha256``.
        """
        document = self.load()

        # (1) refuse to publish anything that does not fully conform.
        violations = self.all_violations(document)
        if violations:
            raise ValidationError(violations)

        # (2) refuse to publish a source that drifted out of band (when sealed).
        if self._audit_exists():
            source_sha = self.verify_integrity()
        else:
            source_sha = store.hash_file(self.data_path)

        # (3) build the deterministic publication document and write it.
        export_doc = dict(document)
        entries = list(self._entries(document))
        export_doc[self.entries_key] = sorted(
            entries, key=lambda e: str(e.get(self.id_key, ""))
        )
        payload = store.canonical_export_bytes(export_doc)
        export_sha = store.atomic_write_bytes(dest_path, payload)

        # (4) record provenance. resulting_sha256 == source hash keeps the source
        # integrity chain intact (export does not mutate the source file).
        audit.append_record(
            self.audit_path,
            actor=actor or self.actor,
            op="export_full",
            params={"dest": str(dest_path), "export_sha256": export_sha},
            entries_touched=[],
            resulting_sha256=source_sha,
        )
        return {
            "op": "export_full",
            "dest": str(dest_path),
            "entries": len(entries),
            "export_sha256": export_sha,
            "source_sha256": source_sha,
        }

    # -- reads -----------------------------------------------------------------

    def get(self, entry_id: str) -> Optional[dict]:
        return query.get(self._entries(self.load()), self.id_key, entry_id)

    def find(self, **filters: Any) -> list[dict]:
        return query.find(self._entries(self.load()), **filters)

    def history(self, entry_id: Optional[str] = None) -> list[dict]:
        records = audit.read_records(self.audit_path)
        if entry_id is None:
            return records
        return [r for r in records if entry_id in r.get("entries_touched", [])]

    def export_view(self, kind: str, **params: Any) -> str:
        if kind not in self.views:
            raise OperationError(
                f"Unknown view {kind!r}. Known: {', '.join(sorted(self.views)) or '(none)'}"
            )
        return self.views[kind](self.load(), **params)


# =============================================================================
# Multi-collection store (interop issue #12, Option B) -------------------------
#
# The single physical file becomes an ENVELOPE of named, homogeneous collections
# (`declarations`, `claims`, …), each with its OWN schema/validator/ops/views but
# sharing ALL the same machinery: surrogate ids, operation-mediated writes, a
# whole-store hash-log, validate/verify_integrity/export_full, terse receipts,
# and config-driven vocab. Each collection's sub-document keeps the EXACT shape
# its existing single-collection code already expects, so a collection's ops and
# business validator are reused UNCHANGED — the Store is a dispatcher + envelope.
#
# Integrity is WHOLE-STORE (one hash chain over the envelope), not per-collection
# (interop #12 open question, decided): the killer invariant spans collections
# (a claim's validity depends on declaration state), so the atomic/validation
# unit must be the whole store. A single audit chain records every write, tagged
# with its collection.
# =============================================================================

# A cross-collection validator sees the WHOLE store document and returns
# violations that span collections (e.g. the claims witness invariant).
CrossValidator = Callable[[dict], list[str]]

STORE_VERSION = "2"


class CollectionSpec:
    """The per-collection wiring inside a :class:`Store` — the same four pieces a
    single-collection :class:`Registry` takes, plus an ``empty_doc`` factory for
    the pre-founding envelope."""

    def __init__(
        self,
        *,
        schema: dict,
        business_validator: BusinessValidator,
        operations: dict[str, Operation],
        views: Optional[dict[str, View]] = None,
        empty_doc: Callable[[], dict],
        entries_key: str = "entries",
        id_key: str = "id",
    ):
        self.schema = schema
        self.business_validator = business_validator
        self.operations = dict(operations)
        self.views = dict(views or {})
        self.empty_doc = empty_doc
        self.entries_key = entries_key
        self.id_key = id_key


class Store:
    """A collection-aware registry: one physical file holding many collections,
    one whole-store hash chain, cross-collection validation.

    Op signatures are identical to :class:`Registry`'s — an op takes a
    collection's sub-document and returns ``(sub_doc, touched[, extra])``. The
    Store extracts the sub-doc, runs the op, re-inserts it, then validates the
    WHOLE store (each collection's structural+business rules, then the
    cross-collection validators) as the postcondition. Nothing is written unless
    the whole store conforms.
    """

    def __init__(
        self,
        *,
        data_path: str | os.PathLike,
        collections: dict[str, CollectionSpec],
        cross_validators: Optional[list[CrossValidator]] = None,
        audit_path: Optional[str | os.PathLike] = None,
        vocab_dir: Optional[str | os.PathLike] = None,
        actor: str = "cli",
    ):
        self.data_path = Path(data_path)
        self.collections = dict(collections)
        self.cross_validators = list(cross_validators or [])
        self.audit_path = Path(audit_path) if audit_path else audit.default_audit_path(data_path)
        # Per-collection default vocab config lives next to the store file, named
        # <collection>_vocab.json (declarations keeps the legacy tag_vocab.json).
        self.vocab_dir = Path(vocab_dir) if vocab_dir else self.data_path.parent
        self.actor = actor

    STORE_VERSION = STORE_VERSION

    # -- helpers ---------------------------------------------------------------

    def exists(self) -> bool:
        return self.data_path.exists()

    def load(self) -> dict:
        return store.read_json(self.data_path)

    def empty_store(self) -> dict:
        return {
            "store_version": self.STORE_VERSION,
            "collections": {name: spec.empty_doc() for name, spec in self.collections.items()},
        }

    def _require_collection(self, name: str) -> CollectionSpec:
        if name not in self.collections:
            raise OperationError(
                f"Unknown collection {name!r}. Known: {', '.join(sorted(self.collections))}"
            )
        return self.collections[name]

    def vocab_path(self, collection: str) -> Path:
        """Default caller-owned vocab config path for a collection."""
        if collection == "declarations":
            return self.vocab_dir / "tag_vocab.json"
        return self.vocab_dir / f"{collection}_vocab.json"

    def _audit_exists(self) -> bool:
        return self.audit_path.exists() and audit.last_record(self.audit_path) is not None

    def _collection_doc(self, store_doc: dict, name: str) -> dict:
        return store_doc.get("collections", {}).get(name, {})

    def _entries(self, store_doc: dict, name: str) -> list[dict]:
        spec = self.collections[name]
        return self._collection_doc(store_doc, name).get(spec.entries_key, [])

    # -- validation & integrity ------------------------------------------------

    def all_violations(self, store_doc: dict) -> list[str]:
        """Every violation across the whole store: each collection's structural +
        business rules, then the cross-collection validators."""
        violations: list[str] = []
        colls = store_doc.get("collections")
        if not isinstance(colls, dict):
            return ["store: missing or malformed 'collections' object"]
        for name, spec in self.collections.items():
            sub = colls.get(name)
            if sub is None:
                violations.append(f"store: required collection {name!r} is missing")
                continue
            for v in structural_violations(sub, spec.schema):
                violations.append(f"[{name}] {v}")
            for v in spec.business_validator(sub):
                violations.append(f"[{name}] {v}")
        for name in colls:
            if name not in self.collections:
                violations.append(f"store: unknown collection {name!r}")
        for xv in self.cross_validators:
            violations.extend(xv(store_doc))
        return violations

    def validate(self) -> list[str]:
        return self.all_violations(self.load())

    def verify_integrity(self) -> str:
        return audit.verify_integrity(self.data_path, self.audit_path)

    # -- writes ----------------------------------------------------------------

    def seal(self, *, actor: Optional[str] = None) -> dict:
        """Adopt the current store file as the managed baseline (validate whole
        store, normalize bytes, record the first whole-store hash)."""
        store_doc = self.load()
        violations = self.all_violations(store_doc)
        if violations:
            raise ValidationError(violations)
        sha = store.atomic_write_json(self.data_path, store_doc)
        return audit.append_record(
            self.audit_path,
            actor=actor or self.actor,
            op="seal",
            params={},
            entries_touched=[],
            resulting_sha256=sha,
        )

    def apply(self, collection: str, op_name: str, params: dict[str, Any], *,
              actor: Optional[str] = None) -> dict:
        """Run a write op on ONE collection with whole-store guarantees."""
        spec = self._require_collection(collection)
        if op_name not in spec.operations:
            raise OperationError(
                f"Unknown operation {op_name!r} for collection {collection!r}. "
                f"Known: {', '.join(sorted(spec.operations))}"
            )
        op = spec.operations[op_name]

        # (1) whole-store integrity gate — only once a baseline exists.
        if self._audit_exists():
            self.verify_integrity()
        current = self.load() if self.exists() else self.empty_store()

        # (2) run the op on an isolated deep copy of the target collection.
        working = copy.deepcopy(current)
        sub = working.get("collections", {}).get(collection)
        if sub is None:  # collection absent in an older/partial store envelope
            sub = spec.empty_doc()
        try:
            op_result = op(sub, **params)
        except TypeError as exc:
            raise OperationError(f"Bad parameters for {op_name!r}: {exc}") from exc
        if len(op_result) == 3:
            result_sub, touched, extra = op_result
        else:
            result_sub, touched = op_result
            extra = None
        working.setdefault("collections", {})[collection] = result_sub

        # (3) whole-store postcondition (incl. cross-collection invariants).
        violations = self.all_violations(working)
        if violations:
            raise ValidationError(violations)

        # (4) atomic write, (5) audit append tagged with the collection.
        sha = store.atomic_write_json(self.data_path, working)
        audit.append_record(
            self.audit_path,
            actor=actor or self.actor,
            op=f"{collection}.{op_name}",
            params={**params, "_collection": collection},
            entries_touched=touched,
            resulting_sha256=sha,
        )
        result = {"op": op_name, "collection": collection,
                  "touched_count": len(touched), "resulting_sha256": sha}
        if len(touched) <= _MAX_TOUCHED_ECHO:
            result["entries_touched"] = touched
        if extra:
            result.update(extra)
        return result

    def export_full(self, dest_path: str | os.PathLike, *, actor: Optional[str] = None) -> dict:
        """Publish the COMPLETE store as a deterministic, schema-valid artifact.

        Spans all collections: refuses an invalid or drifted store, sorts each
        collection's entries by id, sorts keys recursively, and records the export
        (with the artifact hash) in the audit log without counting as a source
        mutation (resulting_sha256 stays the unchanged source hash)."""
        store_doc = self.load()
        violations = self.all_violations(store_doc)
        if violations:
            raise ValidationError(violations)
        if self._audit_exists():
            source_sha = self.verify_integrity()
        else:
            source_sha = store.hash_file(self.data_path)

        export_doc = copy.deepcopy(store_doc)
        total = 0
        for name, spec in self.collections.items():
            sub = export_doc.get("collections", {}).get(name)
            if not sub:
                continue
            entries = list(sub.get(spec.entries_key, []))
            total += len(entries)
            sub[spec.entries_key] = sorted(entries, key=lambda e: str(e.get(spec.id_key, "")))
        payload = store.canonical_export_bytes(export_doc)
        export_sha = store.atomic_write_bytes(dest_path, payload)
        audit.append_record(
            self.audit_path,
            actor=actor or self.actor,
            op="export_full",
            params={"dest": str(dest_path), "export_sha256": export_sha},
            entries_touched=[],
            resulting_sha256=source_sha,
        )
        return {"op": "export_full", "dest": str(dest_path), "entries": total,
                "export_sha256": export_sha, "source_sha256": source_sha}

    # -- reads -----------------------------------------------------------------

    def get(self, collection: str, entry_id: str) -> Optional[dict]:
        spec = self._require_collection(collection)
        return query.get(self._entries(self.load(), collection), spec.id_key, entry_id)

    def find(self, collection: str, **filters: Any) -> list[dict]:
        self._require_collection(collection)
        return query.find(self._entries(self.load(), collection), **filters)

    def history(self, entry_id: Optional[str] = None) -> list[dict]:
        records = audit.read_records(self.audit_path)
        if entry_id is None:
            return records
        return [r for r in records if entry_id in r.get("entries_touched", [])]

    def export_view(self, collection: str, kind: str, **params: Any) -> str:
        spec = self._require_collection(collection)
        if kind not in spec.views:
            raise OperationError(
                f"Unknown view {kind!r} for collection {collection!r}. "
                f"Known: {', '.join(sorted(spec.views)) or '(none)'}"
            )
        # Cross-collection views (e.g. the claim graph) need the whole store; a
        # view opts in by declaring a **store keyword. Plain views get their own
        # collection sub-document, exactly like the single-collection Registry.
        store_doc = self.load()
        view = spec.views[kind]
        if _view_wants_store(view):
            return view(self._collection_doc(store_doc, collection), store=store_doc, **params)
        return view(self._collection_doc(store_doc, collection), **params)


def _view_wants_store(view: View) -> bool:
    """True only if a view explicitly declares a ``store`` parameter — a
    cross-collection projection that needs the whole envelope (e.g. the claim
    graph joining declarations). Plain views must NOT receive it: their ``**_params``
    catch-all would silently swallow it."""
    import inspect

    try:
        return "store" in inspect.signature(view).parameters
    except (TypeError, ValueError):
        return False
