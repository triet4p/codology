"""Static declaration surface.

Declarations are pure metadata. This package must not import
``codology.registry``, an engine, a binding, or an adapter: declarations are
loaded and linked later, without a provider or credential.
"""

from codology.declarations.annotations import raw_annotations, resolve_annotations
from codology.declarations.behavior import (
    Action,
    AllOf,
    AnyOf,
    Approval,
    CommitRequirement,
    Comparison,
    Effect,
    FieldRef,
    Function,
    Literal,
    Negate,
    Param,
    Predicate,
    UnsupportedApprovalExpression,
    all_of,
    any_of,
    not_,
    validate_predicate,
)
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
    "Action",
    "AllOf",
    "AnyOf",
    "Approval",
    "CommitRequirement",
    "Comparison",
    "Declaration",
    "DeclarationError",
    "DeclarationMeta",
    "Effect",
    "FieldRef",
    "Function",
    "HANDLER_NAME",
    "HandlerConventionError",
    "Link",
    "Literal",
    "Module",
    "Negate",
    "ObjectRef",
    "ObjectType",
    "Param",
    "Predicate",
    "UnsupportedApprovalExpression",
    "Value",
    "all_of",
    "any_of",
    "handler_signature",
    "not_",
    "raw_annotations",
    "resolve_annotations",
    "validate_predicate",
]
