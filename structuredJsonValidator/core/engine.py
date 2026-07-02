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

        # (2) run the operation on an isolated deep copy.
        working = copy.deepcopy(current)
        try:
            result_doc, touched = op(working, **params)
        except TypeError as exc:
            raise OperationError(f"Bad parameters for {op_name!r}: {exc}") from exc

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

    def export_view(self, kind: str) -> str:
        if kind not in self.views:
            raise OperationError(
                f"Unknown view {kind!r}. Known: {', '.join(sorted(self.views)) or '(none)'}"
            )
        return self.views[kind](self.load())
