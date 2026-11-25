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
from codology.declarations.primitives import (
    Declaration,
    DeclarationError,
    DeclarationMeta,
    Link,
    Module,
    ObjectRef,
    ObjectType,
    Value,
)

__all__ = [
    "Declaration",
    "DeclarationError",
    "DeclarationMeta",
    "HANDLER_NAME",
    "HandlerConventionError",
    "Link",
    "Module",
    "ObjectRef",
    "ObjectType",
    "Value",
    "handler_signature",
    "raw_annotations",
    "resolve_annotations",
]
