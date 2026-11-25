"""Load phase: collect declarations into an immutable, owned model.

Load answers only the first static question: are the definitions readable,
uniquely identified, and made of valid declaration fields? It does not resolve
references, check exports, call a handler, or touch a backend. Those belong to
Link and later phases.

Ownership comes from the explicit groups supplied by the author, never from a
Python import path or a host class name. Identity is read from the declared
``identity`` field only: a definition without one stays anonymous instead of
silently acquiring its host class name.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, cast

from codology.declarations import DECLARATION_FIELDS, Declaration, Link, Module

_ANONYMOUS: Final = "<anonymous>"


class LoadError(ValueError):
    """A declaration set cannot be loaded because of an authoring mistake."""

    def __init__(self, message: str, *, module: str, identity: str | None, field: str) -> None:
        label = identity if identity is not None else _ANONYMOUS
        super().__init__(f"module {module!r}, identity {label!r}, field {field!r}: {message}")
        self.module = module
        self.identity = identity
        self.field = field


class DuplicateIdentity(LoadError):
    """Two declarations in one load set claim the same identity."""

    def __init__(
        self,
        identity: str,
        *,
        module: str,
        declaration: type[Declaration],
        other_module: str,
        other_declaration: type[Declaration],
    ) -> None:
        super().__init__(
            f"identity {identity!r} is declared twice: "
            f"{declaration.__qualname__} in module {module!r} and "
            f"{other_declaration.__qualname__} in module {other_module!r}. "
            "Remove one declaration or give it a distinct identity.",
            module=module,
            identity=identity,
            field="identity",
        )
        self.declaration = declaration
        self.conflicting_module = other_module
        self.conflicting_declaration = other_declaration


class UnknownDeclarationKey(LoadError):
    """A declaration body contains a field the static layer does not know."""

    def __init__(
        self,
        *,
        module: str,
        identity: str | None,
        declaration: type[Declaration],
        field: str,
    ) -> None:
        super().__init__(
            f"{declaration.__qualname__} declares unknown field {field!r}; expected a typed "
            "property annotation or a declaration field: "
            f"{', '.join(sorted(DECLARATION_FIELDS))}.",
            module=module,
            identity=identity,
            field=field,
        )
        self.declaration = declaration


@dataclass(frozen=True, slots=True)
class ModuleDeclarations:
    """One ownership group: a module and every definition it owns, exported or not."""

    module: type[Module]
    definitions: Sequence[type[Declaration]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "definitions", tuple(self.definitions))


@dataclass(frozen=True, slots=True)
class LoadedDefinition:
    """A definition with the identity, version, and owner captured at Load."""

    declaration: type[Declaration]
    identity: str | None
    version: str | None
    owner: str
    module: type[Module]


@dataclass(frozen=True, slots=True)
class LoadedModule:
    """An ownership boundary with its definitions in the order they were loaded."""

    declaration: type[Module]
    identity: str
    version: str
    exports: tuple[type[Declaration], ...]
    definitions: tuple[LoadedDefinition, ...]


@dataclass(frozen=True, slots=True)
class LoadedDeclarations:
    """The result of Load: definitions indexed by declared identity."""

    modules: Mapping[str, LoadedModule]
    definitions: Mapping[str, LoadedDefinition]

    def __post_init__(self) -> None:
        object.__setattr__(self, "modules", MappingProxyType(dict(self.modules)))
        object.__setattr__(self, "definitions", MappingProxyType(dict(self.definitions)))


def load(*groups: ModuleDeclarations) -> LoadedDeclarations:
    """Collect and validate declaration groups without resolving any reference.

    Repeated groups for the same module are merged; two different module
    classes sharing a module identity are rejected. Every definition must have
    exactly one owner, and every non-anonymous identity must be unique across
    the whole load set.
    """
    owned: dict[str, tuple[type[Module], list[type[Declaration]]]] = {}
    for index, candidate in enumerate(groups):
        group = _check_group(candidate, index)
        module = group.module
        module_identity = cast(str, module.identity)
        existing = owned.get(module_identity)
        if existing is None:
            owned[module_identity] = (module, list(group.definitions))
            continue
        owner, collected = existing
        if owner is not module:
            raise DuplicateIdentity(
                module_identity,
                module=owner.__qualname__,
                declaration=owner,
                other_module=module.__qualname__,
                other_declaration=module,
            )
        collected.extend(group.definitions)

    modules: dict[str, LoadedModule] = {}
    definitions: dict[str, LoadedDefinition] = {}
    owners: dict[type[Declaration], str] = {}
    for module_identity, (module, declaration_classes) in owned.items():
        loaded_here: list[LoadedDefinition] = []
        for declaration in declaration_classes:
            if issubclass(declaration, Module):
                raise LoadError(
                    "a module is an ownership boundary, not a definition.",
                    module=module_identity,
                    identity=None,
                    field="definitions",
                )
            identity = _declared_text(declaration, "identity")
            version = _declared_text(declaration, "version")
            _check_fields(declaration, module_identity, identity)

            previous_owner = owners.get(declaration)
            if previous_owner is not None:
                raise LoadError(
                    f"{declaration.__qualname__} is listed in module {module_identity!r} "
                    f"but is already owned by module {previous_owner!r}; "
                    "a definition belongs to exactly one module.",
                    module=module_identity,
                    identity=identity,
                    field="owner",
                )
            owners[declaration] = module_identity

            item = LoadedDefinition(declaration, identity, version, module_identity, module)
            loaded_here.append(item)
            if identity is None:
                continue
            clash = definitions.get(identity)
            if clash is not None:
                raise DuplicateIdentity(
                    identity,
                    module=clash.owner,
                    declaration=clash.declaration,
                    other_module=module_identity,
                    other_declaration=declaration,
                )
            definitions[identity] = item

        modules[module_identity] = LoadedModule(
            declaration=module,
            identity=module_identity,
            version=cast(str, module.version),
            exports=tuple(module.exports),
            definitions=tuple(loaded_here),
        )
    return LoadedDeclarations(modules=modules, definitions=definitions)


def _check_group(value: object, index: int) -> ModuleDeclarations:
    if not isinstance(value, ModuleDeclarations):
        raise TypeError(f"load() argument {index} must be a ModuleDeclarations group.")
    group = value
    module = group.module
    if module is Module:
        raise LoadError(
            "the base Module is not a concrete ownership boundary.",
            module=module.__qualname__,
            identity=None,
            field="module",
        )
    if not _declared_text(module, "identity") or not _declared_text(module, "version"):
        raise LoadError(
            "a module needs an explicit identity and version.",
            module=module.__qualname__,
            identity=None,
            field="identity",
        )
    return group


def _check_fields(declaration: type[Declaration], module: str, identity: str | None) -> None:
    annotations = cast(Mapping[str, object], getattr(declaration, "__annotations__", {}))
    own = cast(Mapping[str, object], declaration.__dict__)
    for name in sorted(own):
        if name.startswith("__") and name.endswith("__"):
            continue
        if name == "_frozen" or name in DECLARATION_FIELDS or name in annotations:
            continue
        value = own[name]
        if inspect.isfunction(value) and value.__name__ == name:
            continue
        if isinstance(value, type) and issubclass(value, Link):
            continue
        raise UnknownDeclarationKey(
            module=module,
            identity=identity,
            declaration=declaration,
            field=name,
        )


def _declared_text(declaration: type[Declaration], field: str) -> str | None:
    value: object = getattr(declaration, field, None)
    if isinstance(value, str) and value.strip():
        return value
    return None
