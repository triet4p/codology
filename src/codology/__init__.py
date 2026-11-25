"""Codology's import root.

The package ships the static declaration layer, Load, and Link. Binding,
engine, and adapter modules do not exist yet; importing ``codology`` must
never require a database, credentials, or a backend SDK.
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

__version__ = "0.1.0"

__all__ = [
    "DuplicateIdentity",
    "HandlerMismatch",
    "LinkError",
    "LinkedDeclarations",
    "LinkedDefinition",
    "LoadedDeclarations",
    "LoadedDefinition",
    "LoadedModule",
    "LoadError",
    "ModuleDeclarations",
    "NotExported",
    "ObjectRefMismatch",
    "ResolvedReference",
    "UnresolvedReference",
    "UnknownDeclarationKey",
    "WrongKind",
    "__version__",
    "link",
    "load",
]
