"""Project-agnostic SSOT registry core.

This package is the real deliverable: a schema-enforced flat-file registry with
operation-based writes, an append-only audit + hash-drift log, and a projection
reader. It knows nothing about any particular consumer's data shape; a consumer
(see ``consumers/``) supplies a schema, business rules, operations, and views.
"""

from core.engine import Registry
from core.errors import IntegrityError, OperationError, ValidationError

__all__ = ["Registry", "IntegrityError", "OperationError", "ValidationError"]
