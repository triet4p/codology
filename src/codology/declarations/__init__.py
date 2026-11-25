"""Static declaration surface.

Declarations are pure metadata. This package must not import
``codology.registry``, an engine, a binding, or an adapter: declarations are
loaded and linked later, without a provider or credential.
"""

from codology.declarations.annotations import raw_annotations, resolve_annotations
from codology.declarations.handler import (
    HANDLER_NAME,
    HandlerConventionError,
    handler_signature,
)

__all__ = [
    "HANDLER_NAME",
    "HandlerConventionError",
    "handler_signature",
    "raw_annotations",
    "resolve_annotations",
]
