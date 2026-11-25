"""Codology's import root.

The package ships the static declaration layer and the Load phase. Link,
binding, engine, and adapter modules do not exist yet; importing ``codology``
must never require a database, credentials, or a backend SDK.
"""

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
    "LoadError",
    "LoadedDeclarations",
    "LoadedDefinition",
    "LoadedModule",
    "ModuleDeclarations",
    "UnknownDeclarationKey",
    "__version__",
    "load",
]
