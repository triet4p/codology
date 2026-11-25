"""Link phase: resolve and check references across the composed Load model.

Link answers the second static question: does every declared reference point
to a loaded definition of the right kind, visible across its owning module's
export boundary, with a handler whose parameters match the declared contract?

Nothing here imports another declaration module at runtime. Forward names are
resolved against a namespace composed from the definitions handed to Link, so
two modules may reference each other's types without an import cycle. Handlers
are inspected, never called, and dependencies are read only from declarations.
"""

from __future__ import annotations

import collections.abc
import re
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, cast

import codology.declarations as declarations
from codology.declarations import (
    HANDLER_NAME,
    Action,
    Declaration,
    Effect,
    Function,
    HandlerConventionError,
    Link,
    ObjectRef,
    ObjectType,
    Value,
    handler_signature,
    raw_annotations,
    resolve_annotations,
)
from codology.loading import LoadedDeclarations, LoadedDefinition

_ANONYMOUS: Final = "<anonymous>"
_NAME_TOKEN: Final = re.compile(r"[A-Za-z_]\w*")


class LinkError(ValueError):
    """A composed model cannot be linked because a reference is invalid."""

    def __init__(self, message: str, *, module: str, identity: str | None, field: str) -> None:
        label = identity if identity is not None else _ANONYMOUS
        super().__init__(f"module {module!r}, identity {label!r}, field {field!r}: {message}")
        self.module = module
        self.identity = identity
        self.field = field


class UnresolvedReference(LinkError):
    """A reference names no definition in the composed link set."""


class NotExported(LinkError):
    """A cross-module reference targets a definition its owner did not export."""


class WrongKind(LinkError):
    """A reference resolves to a definition of a different declared kind."""


class ObjectRefMismatch(LinkError):
    """An ``ObjectRef[T]`` target or its handler parameter does not match."""


class HandlerMismatch(LinkError):
    """A handler's convention or parameters disagree with the declaration."""


@dataclass(frozen=True, slots=True)
class ResolvedReference:
    """One checked edge from a definition to a loaded target."""

    owner: str
    identity: str | None
    field: str
    target: LoadedDefinition
    raw: object


@dataclass(frozen=True, slots=True)
class LinkedDefinition:
    """A definition with resolved contract/handler types and checked edges."""

    definition: LoadedDefinition
    hints: Mapping[str, object]
    handler_hints: Mapping[str, object]
    references: tuple[ResolvedReference, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "hints", MappingProxyType(dict(self.hints)))
        object.__setattr__(self, "handler_hints", MappingProxyType(dict(self.handler_hints)))


@dataclass(frozen=True, slots=True)
class LinkedDeclarations:
    """The immutable result of Link over a composed Load model."""

    source: LoadedDeclarations
    definitions: Mapping[str, LinkedDefinition]
    all_definitions: tuple[LinkedDefinition, ...]
    references: tuple[ResolvedReference, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "definitions", MappingProxyType(dict(self.definitions)))


def link(loaded: LoadedDeclarations) -> LinkedDeclarations:
    """Resolve every reference in ``loaded`` and return the linked model.

    The input is the output of :func:`codology.loading.load`. Repeated calls
    build a fresh result; neither the load model nor any declaration is
    mutated, and no handler body is executed.
    """
    if not isinstance(cast(object, loaded), LoadedDeclarations):
        raise TypeError("link() expects the LoadedDeclarations produced by load().")

    namespace, ambiguous = _compose_namespace(loaded)
    owners = _owners(loaded)
    definitions: dict[str, LinkedDefinition] = {}
    all_definitions: list[LinkedDefinition] = []
    references: list[ResolvedReference] = []
    for module in loaded.modules.values():
        for item in module.definitions:
            linked = _link_definition(item, loaded, namespace, ambiguous, owners)
            all_definitions.append(linked)
            references.extend(linked.references)
            if item.identity is not None:
                definitions[item.identity] = linked
    return LinkedDeclarations(
        source=loaded,
        definitions=definitions,
        all_definitions=tuple(all_definitions),
        references=tuple(references),
    )


def _compose_namespace(
    loaded: LoadedDeclarations,
) -> tuple[dict[str, object], dict[str, tuple[str, ...]]]:
    """Build a name/identity lookup without importing any declaration module."""
    namespace: dict[str, object] = {**vars(typing), **vars(collections.abc)}
    namespace.update({name: getattr(declarations, name) for name in declarations.__all__})
    named: dict[str, LoadedDefinition] = {}
    ambiguous: dict[str, list[str]] = {}
    for module in loaded.modules.values():
        for item in module.definitions:
            name = item.declaration.__name__
            previous = named.get(name)
            if previous is not None and previous.declaration is not item.declaration:
                ambiguous.setdefault(name, [_label(previous)]).append(_label(item))
                continue
            named[name] = item
    namespace.update({name: item.declaration for name, item in named.items()})
    for identity, item in loaded.definitions.items():
        namespace[identity] = item.declaration
    ambiguous_names = {name: tuple(identities) for name, identities in ambiguous.items()}
    return namespace, ambiguous_names


def _owners(loaded: LoadedDeclarations) -> dict[type[Declaration], LoadedDefinition]:
    return {
        item.declaration: item for module in loaded.modules.values() for item in module.definitions
    }


def _link_definition(
    item: LoadedDefinition,
    loaded: LoadedDeclarations,
    namespace: Mapping[str, object],
    ambiguous: Mapping[str, tuple[str, ...]],
    owners: Mapping[type[Declaration], LoadedDefinition],
) -> LinkedDefinition:
    declaration = item.declaration
    hints = _resolve_hints(declaration, item, "params", namespace, ambiguous)
    references: list[ResolvedReference] = []
    ref_targets: dict[str, type[Declaration]] = {}

    for name in declaration.properties:
        field = f"params.{name}"
        contract = hints.get(name)
        if contract is None:
            raise UnresolvedReference(
                f"parameter {name!r} has no resolvable annotation.",
                module=item.owner,
                identity=item.identity,
                field=field,
            )
        if isinstance(contract, type) and issubclass(contract, ObjectRef):
            target = _resolve_target(contract.target, item, field, namespace, ambiguous, owners)
            _check_kind(target, (ObjectType,), item, field)
            _check_export(target, item, loaded, field)
            _add_reference(references, item, field, contract.target, target)
            hints[name] = ObjectRef[target.declaration]
            ref_targets[name] = target.declaration
        elif isinstance(contract, type) and issubclass(contract, Declaration):
            target = _resolve_target(contract, item, field, namespace, ambiguous, owners)
            if issubclass(target.declaration, ObjectType):
                raise ObjectRefMismatch(
                    f"parameter {name!r} names an object type directly; declare "
                    f"ObjectRef[{target.declaration.__name__}] instead.",
                    module=item.owner,
                    identity=item.identity,
                    field=field,
                )
            _check_export(target, item, loaded, field)
            _add_reference(references, item, field, contract, target)

    for field in ("reads", "writes"):
        for raw in cast(Sequence[object], getattr(declaration, field, ())):
            target = _resolve_target(raw, item, field, namespace, ambiguous, owners)
            _check_kind(target, (ObjectType,), item, field)
            _check_export(target, item, loaded, field)
            _add_reference(references, item, field, raw, target)

    for raw in cast(Sequence[object], getattr(declaration, "calls", ())):
        target = _resolve_target(raw, item, "calls", namespace, ambiguous, owners)
        _check_kind(target, (Action, Function), item, "calls")
        _check_export(target, item, loaded, "calls")
        _add_reference(references, item, "calls", raw, target)

    links = cast(Mapping[str, Link], getattr(declaration, "links", {}))
    for name, spec in links.items():
        field = f"links.{name}"
        target = _resolve_target(spec.target, item, field, namespace, ambiguous, owners)
        _check_kind(target, (ObjectType,), item, field)
        _check_export(target, item, loaded, field)
        _add_reference(references, item, field, spec.target, target)

    for field, kinds in (("result", (Value, ObjectType)), ("payload", (Value,))):
        raw = getattr(declaration, field, None)
        if isinstance(raw, str) or (isinstance(raw, type) and issubclass(raw, Declaration)):
            target = _resolve_target(raw, item, field, namespace, ambiguous, owners)
            _check_kind(target, kinds, item, field)
            _check_export(target, item, loaded, field)
            _add_reference(references, item, field, raw, target)

    for raw in cast(Sequence[object], getattr(declaration, "effects", ())):
        target = _resolve_target(raw, item, "effects", namespace, ambiguous, owners)
        _check_kind(target, (Effect,), item, "effects")
        _check_export(target, item, loaded, "effects")
        _add_reference(references, item, "effects", raw, target)

    handler_hints = _check_handler(declaration, item, hints, ref_targets, namespace, ambiguous)
    return LinkedDefinition(
        definition=item,
        hints=hints,
        handler_hints=handler_hints,
        references=tuple(references),
    )


def _check_handler(
    declaration: type[Declaration],
    item: LoadedDefinition,
    hints: Mapping[str, object],
    ref_targets: Mapping[str, type[Declaration]],
    namespace: Mapping[str, object],
    ambiguous: Mapping[str, tuple[str, ...]],
) -> Mapping[str, object]:
    if not issubclass(declaration, Action | Function):
        return MappingProxyType({})
    try:
        signature = handler_signature(declaration)
    except HandlerConventionError as exc:
        raise HandlerMismatch(
            str(exc),
            module=item.owner,
            identity=item.identity,
            field="handler",
        ) from exc

    handler = vars(declaration)[HANDLER_NAME]
    handler_hints = _resolve_hints(handler, item, "handler", namespace, ambiguous)
    expected = tuple(declaration.properties)
    actual = tuple(parameter.name for parameter in tuple(signature.parameters.values())[2:])
    if actual != expected:
        raise HandlerMismatch(
            f"handler parameters {actual} do not match declared params {expected}; "
            "use the same names in the same order.",
            module=item.owner,
            identity=item.identity,
            field="handler",
        )

    for name in expected:
        contract = hints[name]
        declared = handler_hints.get(name)
        if name in ref_targets:
            wanted = ref_targets[name]
            if declared is not wanted:
                raise ObjectRefMismatch(
                    f"handler parameter {name!r} must be annotated with the resolved type "
                    f"{wanted.__qualname__}, not {_display(declared)}.",
                    module=item.owner,
                    identity=item.identity,
                    field="handler",
                )
        elif declared != contract:
            raise HandlerMismatch(
                f"handler parameter {name!r} is annotated {_display(declared)} but the "
                f"declaration says {_display(contract)}.",
                module=item.owner,
                identity=item.identity,
                field="handler",
            )
    return handler_hints


def _resolve_hints(
    target: type[object] | object,
    item: LoadedDefinition,
    field: str,
    namespace: Mapping[str, object],
    ambiguous: Mapping[str, tuple[str, ...]],
) -> dict[str, object]:
    for name, annotation in raw_annotations(target).items():  # pyright: ignore[reportArgumentType]
        if isinstance(annotation, str):
            for token in _NAME_TOKEN.findall(annotation):
                if token in ambiguous:
                    raise UnresolvedReference(
                        f"annotation {name!r} uses ambiguous name {token!r} "
                        f"({', '.join(ambiguous[token])}); use a full identity instead.",
                        module=item.owner,
                        identity=item.identity,
                        field=field,
                    )
    try:
        return resolve_annotations(target, namespace)  # pyright: ignore[reportArgumentType]
    except (NameError, TypeError, AttributeError, SyntaxError) as exc:
        raise UnresolvedReference(
            f"annotations cannot be resolved ({exc}); check the name and the owning module.",
            module=item.owner,
            identity=item.identity,
            field=field,
        ) from exc


def _resolve_target(
    raw: object,
    item: LoadedDefinition,
    field: str,
    namespace: Mapping[str, object],
    ambiguous: Mapping[str, tuple[str, ...]],
    owners: Mapping[type[Declaration], LoadedDefinition],
) -> LoadedDefinition:
    if isinstance(raw, str):
        if raw in ambiguous:
            raise UnresolvedReference(
                f"name {raw!r} is ambiguous ({', '.join(ambiguous[raw])}); "
                "use the full identity instead.",
                module=item.owner,
                identity=item.identity,
                field=field,
            )
        candidate = namespace.get(raw)
        if candidate is None:
            raise UnresolvedReference(
                f"reference {raw!r} does not resolve; check the spelling and that the "
                "owning module takes part in the link.",
                module=item.owner,
                identity=item.identity,
                field=field,
            )
    elif isinstance(raw, type):
        candidate = raw
    else:
        raise WrongKind(
            f"reference {raw!r} is neither a declaration class nor a forward name.",
            module=item.owner,
            identity=item.identity,
            field=field,
        )

    target = owners.get(cast(type[Declaration], candidate))
    if target is None:
        raise UnresolvedReference(
            f"{getattr(candidate, '__qualname__', candidate)!r} is not a definition in "
            "the composed link set.",
            module=item.owner,
            identity=item.identity,
            field=field,
        )
    return target


def _check_kind(
    target: LoadedDefinition,
    kinds: tuple[type[Declaration], ...],
    item: LoadedDefinition,
    field: str,
) -> None:
    if issubclass(target.declaration, kinds):
        return
    expected = " or ".join(kind.__name__ for kind in kinds)
    raise WrongKind(
        f"reference to {_label(target)} resolves to a {target.declaration.__name__} "
        f"declaration; expected {expected}. Check the reference field.",
        module=item.owner,
        identity=item.identity,
        field=field,
    )


def _check_export(
    target: LoadedDefinition,
    item: LoadedDefinition,
    loaded: LoadedDeclarations,
    field: str,
) -> None:
    # Export is an identity boundary: a structural Value without an identity
    # is used as a property type and cannot be named across modules.
    if target.owner == item.owner or target.identity is None:
        return
    owner = loaded.modules[target.owner].declaration
    if owner.is_exported(target.declaration):
        return
    raise NotExported(
        f"cross-module reference to {_label(target)} owned by {target.owner!r} is not "
        f"exported; add it to {owner.__name__}.exports or call an exported definition.",
        module=item.owner,
        identity=item.identity,
        field=field,
    )


def _add_reference(
    references: list[ResolvedReference],
    item: LoadedDefinition,
    field: str,
    raw: object,
    target: LoadedDefinition,
) -> None:
    references.append(
        ResolvedReference(
            owner=item.owner,
            identity=item.identity,
            field=field,
            target=target,
            raw=raw,
        )
    )


def _label(item: LoadedDefinition) -> str:
    return item.identity if item.identity is not None else item.declaration.__qualname__


def _display(value: object) -> str:
    return getattr(value, "__qualname__", repr(value))
