"""Pure checks shared by the invoke gate and its waiting path.

These helpers hold no execution state and open no transaction. They check a
bound plan, a linked graph and a principal against the same closed rules in
both the synchronous and the approval path, so the gate cannot apply a weaker
check when it parks an execution.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from codology.binding import BoundAction, SessionPlan
from codology.declarations import Action
from codology.ledger import RequestScope
from codology.linking import LinkedDeclarations, LinkedDefinition
from codology.ports import UnitOfWork
from codology.query import Principal
from codology.snapshot import DefinitionKey


class InvokeDenied(ValueError):
    """A request, ref, or context capability failed a closed engine gate."""


def request_scope(principal: Principal, action: DefinitionKey) -> RequestScope:
    """Scope a request key to the caller's tenant, identity and action identity."""
    return RequestScope(principal.tenant, principal.identity, action.identity)


def discard_unit(unit: UnitOfWork | None) -> None:
    """End an uncommitted unit without leaving a connection or lock behind."""
    if unit is None:
        return
    try:
        unit.rollback()
    finally:
        unit.close()


def bound_session(bound: BoundAction) -> SessionPlan:
    """Return the single session plan bound to an action, or fail closed."""
    if bound.session is None:
        raise InvokeDenied("no session plan is bound to this action.")
    return bound.session


def linked_action(
    linked: LinkedDeclarations,
    action: DefinitionKey,
    bound: BoundAction,
) -> LinkedDefinition:
    """Find the exact linked Action revision named by a bound plan."""
    if bound.action != action or bound.session is None:
        raise InvokeDenied("the bound plan does not name this exact action and session.")
    found = linked.definitions.get(action.identity)
    if (
        found is None
        or found.definition.version != action.version
        or not issubclass(found.definition.declaration, Action)
    ):
        raise InvokeDenied("no linked action exists at this exact identity and version.")
    return found


def ref_target(hint: type[object]) -> DefinitionKey:
    """Read the version-explicit target of a typed ObjectRef annotation."""
    target = cast(object, getattr(hint, "target", None))
    identity = getattr(target, "identity", None)
    version = getattr(target, "version", None)
    if not isinstance(identity, str) or not identity or not isinstance(version, str) or not version:
        raise InvokeDenied("the declared ref target is not version-explicit.")
    return DefinitionKey(identity, version)


def defined_keys(linked: LinkedDeclarations, raw: Sequence[object]) -> frozenset[DefinitionKey]:
    """Resolve declared reads to exact linked definition keys."""
    keys: set[DefinitionKey] = set()
    for value in raw:
        identity = cast(object, getattr(value, "identity", value))
        if not isinstance(identity, str) or not identity:
            raise InvokeDenied("a declared read has no identity.")
        item = linked.definitions.get(identity)
        if item is None or item.definition.version is None:
            raise InvokeDenied("a declared read is not in the linked graph.")
        keys.add(DefinitionKey(identity, item.definition.version))
    return frozenset(keys)


def declared_writes(linked: LinkedDeclarations, raw: Sequence[object]) -> frozenset[str]:
    """Intersect declared write identities with the linked graph."""
    identities = {getattr(item, "identity", item) for item in raw}
    return frozenset(
        identity
        for identity in (item.definition.identity for item in linked.all_definitions)
        if identity is not None and identity in identities
    )


def require_writes(bound: BoundAction, allowed: frozenset[str]) -> None:
    """Check every declared write has a session enlistment before any handler runs."""
    writable = {item.identity for item in bound_session(bound).writes}
    for bound_write in bound.writes:
        if bound_write.resource.identity not in writable:
            raise InvokeDenied("the bound session does not contain a declared write.")
    for identity in allowed:
        if identity not in writable:
            raise InvokeDenied("a declared write has no enlistment in the bound session.")


__all__ = [
    "InvokeDenied",
    "bound_session",
    "declared_writes",
    "defined_keys",
    "discard_unit",
    "linked_action",
    "ref_target",
    "request_scope",
    "require_writes",
]
