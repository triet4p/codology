"""Codology's import root.

The package ships the static declaration layer, Load, Link, and an immutable
snapshot view. Binding, engine, and adapter modules do not exist yet;
importing ``codology`` must never require a database, credentials, or a
backend SDK.
"""

from codology.linking import (
    HandlerMismatch,
    LinkedDeclarations,
    LinkedDefinition,
    LinkError,
    NotExported,
    ObjectRefMismatch,
    ResolvedReference,
    UnresolvedReference,
    WrongKind,
    link,
)
from codology.loading import (
    DuplicateIdentity,
    LoadedDeclarations,
    LoadedDefinition,
    LoadedModule,
    LoadError,
    ModuleDeclarations,
    UnknownDeclarationKey,
    load,
)
from codology.snapshot import (
    AllOfExpr,
    AnyOfExpr,
    ApprovalView,
    ComparisonExpr,
    DefinitionKey,
    Dependency,
    Expression,
    FieldPath,
    LiteralValue,
    NotExpr,
    Snapshot,
    SnapshotEntry,
    UnknownDefinition,
    snapshot,
)

__version__ = "0.1.0"

__all__ = [
    "AllOfExpr",
    "AnyOfExpr",
    "ApprovalView",
    "ComparisonExpr",
    "DefinitionKey",
    "Dependency",
    "DuplicateIdentity",
    "Expression",
    "FieldPath",
    "HandlerMismatch",
    "LinkError",
    "LinkedDeclarations",
    "LinkedDefinition",
    "LoadedDeclarations",
    "LoadedDefinition",
    "LoadedModule",
    "LoadError",
    "LiteralValue",
    "ModuleDeclarations",
    "NotExported",
    "NotExpr",
    "ObjectRefMismatch",
    "ResolvedReference",
    "Snapshot",
    "SnapshotEntry",
    "UnresolvedReference",
    "UnknownDeclarationKey",
    "UnknownDefinition",
    "WrongKind",
    "__version__",
    "link",
    "load",
    "snapshot",
]
