"""Structural validation against a declared JSON Schema (2020-12).

Structural enforcement only: types, enums, required-ness, additionalProperties
(spec §5). Cross-field / conditional / uniqueness rules live in the consumer's
business validator, not here. The validator reports *every* violation (spec §9).
"""

from __future__ import annotations

import json
import os
from typing import Any

from jsonschema import Draft202012Validator


def load_schema(path: str | os.PathLike) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _format_path(error) -> str:
    """Render a jsonschema error's location as a dotted/indexed path."""
    parts: list[str] = []
    for token in error.absolute_path:
        if isinstance(token, int):
            parts.append(f"[{token}]")
        else:
            parts.append(f".{token}" if parts else token)
    return "".join(parts) or "<root>"


def structural_violations(document: Any, schema: dict) -> list[str]:
    """Return all structural violations of ``document`` against ``schema``.

    Empty list means structurally valid. Never raises for validation failures;
    it collects and returns them so the caller controls exit behavior.
    """
    validator = Draft202012Validator(schema)
    violations: list[str] = []
    for error in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path)):
        violations.append(f"{_format_path(error)}: {error.message}")
    return violations
