"""Publish a linked declaration graph as a detached, immutable snapshot.

A snapshot is a value copy of :class:`codology.linking.LinkedDeclarations`. It
holds no live declaration class, so changing an author's input collections or
a collection handed back by the snapshot cannot change published data.

Lookup is deliberately version-explicit. ``lookup(identity, version)`` is the
only read path; there is no ``latest`` and no identity-only fallback. The
versions available for an identity are listed explicitly by ``versions_of``.
Dependencies and approval expressions are normalized into frozen value objects
so a consumer can compare, for example, ``>`` with ``>=`` without consulting a
declaration class.

No handler digest is published. The exact bytes and the scope a digest would
cover are not defined by this static layer, so no ad-hoc hash is presented as a
publish digest.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from codology.declarations import (
    Action,
    AllOf,
    AnyOf,
    Approval,
    CommitRequirement,
    Comparison,
    Declaration,
    Effect,
    FieldRef,
    Function,
    Literal,
    Module,
    Negate,
    ObjectType,
    Value,
)
from codology.linking import LinkedDeclarations, LinkedDefinition, ResolvedReference


@dataclass(frozen=True, slots=True, order=True)
class DefinitionKey:
    """A version-explicit handle to one definition; identity alone is not a key."""

    identity: str
    version: str


@dataclass(frozen=True, slots=True)
class FieldPath:
    """An immutable path from an action parameter into an approval comparison."""

    parameter: str
    path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LiteralValue:
    """A comparison operand captured by value, with nested collections frozen."""

    value: object


@dataclass(frozen=True, slots=True)
class ComparisonExpr:
    """A structured comparison; ``operator`` is preserved verbatim."""

    operator: str
    left: Expression
    right: Expression


@dataclass(frozen=True, slots=True)
class AllOfExpr:
    parts: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class AnyOfExpr:
    parts: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class NotExpr:
    operand: Expression


type Expression = FieldPath | LiteralValue | ComparisonExpr | AllOfExpr | AnyOfExpr | NotExpr


@dataclass(frozen=True, slots=True)
class ApprovalView:
    """The published shape of a structured approval rule."""

    when: Expression
    role: str
    self_approval: bool


@dataclass(frozen=True, slots=True)
class Dependency:
    """One checked edge from a published definition to a link target."""

    field: str
    target_identity: str | None
    target_version: str | None
    target_owner: str
    target_kind: str


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    """One definition as published, with no link back to the author's class."""

    identity: str
    version: str
    owner: str
    kind: str
    dependencies: tuple[Dependency, ...]
    approval: ApprovalView | None
    permission: str | None
    commit_requirement: str | None


class UnknownDefinition(LookupError):
    """No definition was published for an exact identity/version pair."""

    def __init__(self, identity: str, version: str, available: tuple[str, ...]) -> None:
        listed = ", ".join(available) if available else "none"
        super().__init__(
            f"no published definition for identity {identity!r} at version {version!r}; "
            f"available versions: {listed}."
        )
        self.identity = identity
        self.version = version
        self.available = available


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The immutable published graph, keyed by declared identity and version."""

    entries: Mapping[DefinitionKey, SnapshotEntry]
    versions: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", MappingProxyType(dict(self.entries)))
        object.__setattr__(self, "versions", MappingProxyType(dict(self.versions)))

    def lookup(self, identity: str, version: str) -> SnapshotEntry:
        """Return the entry for exactly ``identity`` at ``version``.

        An unknown pair raises :class:`UnknownDefinition`; this method never
        falls back to another version of the same identity.
        """
        key = DefinitionKey(identity, version)
        try:
            return self.entries[key]
        except KeyError as exc:
            raise UnknownDefinition(identity, version, self.versions.get(identity, ())) from exc

    def versions_of(self, identity: str) -> tuple[str, ...]:
        """List the versions published for ``identity``, or an empty tuple."""
        return self.versions.get(identity, ())


def snapshot(linked: LinkedDeclarations) -> Snapshot:
    """Freeze a linked graph into a publishable, independently immutable view."""
    if not isinstance(cast(object, linked), LinkedDeclarations):
        raise TypeError("snapshot() expects the LinkedDeclarations produced by link().")

    entries: dict[DefinitionKey, SnapshotEntry] = {}
    grouped: dict[str, list[str]] = {}
    for item in linked.all_definitions:
        definition = item.definition
        identity = definition.identity
        if identity is None:
            continue
        version = cast(str, definition.version)
        entries[DefinitionKey(identity, version)] = _entry(item, identity, version)
        grouped.setdefault(identity, []).append(version)

    versions = {identity: tuple(sorted(found)) for identity, found in grouped.items()}
    return Snapshot(entries=entries, versions=versions)


def _entry(item: LinkedDefinition, identity: str, version: str) -> SnapshotEntry:
    declaration = item.definition.declaration
    return SnapshotEntry(
        identity=identity,
        version=version,
        owner=item.definition.owner,
        kind=_kind(declaration),
        dependencies=tuple(_dependency(reference) for reference in item.references),
        approval=_approval(getattr(declaration, "approval", None)),
        permission=_text(getattr(declaration, "permission", None)),
        commit_requirement=_commit(getattr(declaration, "commitRequirement", None)),
    )


def _dependency(reference: ResolvedReference) -> Dependency:
    target = reference.target
    return Dependency(
        field=reference.field,
        target_identity=target.identity,
        target_version=target.version,
        target_owner=target.owner,
        target_kind=_kind(target.declaration),
    )


def _kind(declaration: type[Declaration]) -> str:
    for kind in (Module, ObjectType, Value, Action, Function, Effect):
        if issubclass(declaration, kind):
            return kind.__name__
    return "Declaration"


def _approval(value: object) -> ApprovalView | None:
    if not isinstance(value, Approval):
        return None
    return ApprovalView(
        when=_expression(value.when),
        role=value.role,
        self_approval=value.self_approval,
    )


def _expression(value: object) -> Expression:
    if isinstance(value, FieldRef):
        return FieldPath(value.parameter, value.path)
    if isinstance(value, Literal):
        return LiteralValue(_freeze(value.value))
    if isinstance(value, Comparison):
        return ComparisonExpr(value.operator, _expression(value.left), _expression(value.right))
    if isinstance(value, AllOf):
        return AllOfExpr(tuple(_expression(part) for part in value.parts))
    if isinstance(value, AnyOf):
        return AnyOfExpr(tuple(_expression(part) for part in value.parts))
    if isinstance(value, Negate):
        return NotExpr(_expression(value.operand))
    raise TypeError(f"unsupported approval expression node: {type(value).__name__}")


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        frozen = {key: _freeze(item) for key, item in cast(Mapping[object, object], value).items()}
        return MappingProxyType(frozen)
    if isinstance(value, str | bytes):
        return value
    if isinstance(value, Sequence):
        return tuple(_freeze(item) for item in cast(Sequence[object], value))
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in cast(set[object] | frozenset[object], value))
    return value


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _commit(value: object) -> str | None:
    return value.value if isinstance(value, CommitRequirement) else None
