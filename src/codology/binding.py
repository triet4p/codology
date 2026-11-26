"""Deployment binding: validate a deployment plan against a published graph.

Binding is a separate artifact from declarations. It answers whether a chosen
deployment can honour one action's commit contract: the provider claims the
required capability, every write the action can reach (its own ``writes`` and,
transitively, the writes of the actions and functions in its ``calls`` closure)
is enlisted, and those enlistments name one physical session. Delegation grants
are checked against the declared ``calls`` and ``permission`` contract; a grant
may match that contract but never widen it.

This is a plan check. It does not call a handler, open a transaction, or prove
that a runtime session is really shared. Execution still has to confirm the
physical transaction.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from codology.declarations import CommitRequirement
from codology.snapshot import DefinitionKey, Dependency, Snapshot, SnapshotEntry


class Capability(StrEnum):
    """A capability a provider can claim for deployment binding."""

    ATOMIC_TRANSACTION = "atomic_transaction"
    OUTBOX = "outbox"


class DelegationPrincipal(StrEnum):
    """The identity a delegated child call runs under."""

    REQUESTER = "requester"
    SERVICE = "service"


class BindingError(ValueError):
    """A deployment cannot satisfy one action's binding contract."""

    def __init__(self, message: str, *, action: DefinitionKey, field: str) -> None:
        super().__init__(
            f"binding action {action.identity!r} at version {action.version!r}, "
            f"field {field!r}: {message}"
        )
        self.action = action
        self.field = field


class NotAnAction(BindingError):
    """Deployment binding was asked to bind a definition that is not an Action."""


class MissingCapability(BindingError):
    """A provider hosting a required write does not claim the needed capability."""


class UnknownProvider(BindingError):
    """An enlistment names a provider the deployment does not declare."""


class AmbiguousEnlistment(BindingError):
    """One resource is enlisted more than once, so its session is ambiguous."""


class UnboundWrite(BindingError):
    """A required write, including one reached through ``calls``, has no enlistment."""


class NoSharedTransaction(BindingError):
    """Required writes span independent sessions instead of one physical session."""


class EffectSessionMismatch(BindingError):
    """A declared effect's outbox is enlisted outside the business session."""


class InconsistentSession(BindingError):
    """One session label is claimed by two providers, so it cannot be trusted."""


class DelegationError(BindingError):
    """A delegation grant does not fit the declared call contract."""


class AmbientServiceIdentity(DelegationError):
    """A grant would run a child under an ambient service identity."""


class UndeclaredCall(DelegationError):
    """A grant names a call the caller does not declare as a delegatable Action."""


class PermissionBroadened(DelegationError):
    """A grant's permission does not equal the child action's declared permission."""


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value


@dataclass(frozen=True, slots=True)
class Provider:
    """One physical provider that a deployment may enlist."""

    name: str
    kind: str
    capabilities: frozenset[Capability] = frozenset()
    effect_dedup: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "Provider.name")
        _require_text(self.kind, "Provider.kind")
        capabilities = frozenset(self.capabilities)
        for capability in capabilities:
            if not isinstance(cast(object, capability), Capability):
                raise ValueError(
                    f"Provider.capabilities must contain Capability members; found {capability!r}."
                )
        if self.effect_dedup is not None:
            _require_text(self.effect_dedup, "Provider.effect_dedup")
        object.__setattr__(self, "capabilities", capabilities)


@dataclass(frozen=True, slots=True)
class Enlistment:
    """One resource's placement in a provider session.

    ``session`` is an opaque physical identity. Two resources share a
    transaction only when their session identities are identical; matching
    provider kinds or labels do not make separate sessions atomic.
    """

    resource: str
    provider: str
    session: str

    def __post_init__(self) -> None:
        _require_text(self.resource, "Enlistment.resource")
        _require_text(self.provider, "Enlistment.provider")
        _require_text(self.session, "Enlistment.session")


@dataclass(frozen=True, slots=True)
class DelegationGrant:
    """A deployment mapping for one declared cross-module call edge."""

    caller: str
    call: str
    permission: str
    principal: DelegationPrincipal = DelegationPrincipal.REQUESTER

    def __post_init__(self) -> None:
        _require_text(self.caller, "DelegationGrant.caller")
        _require_text(self.call, "DelegationGrant.call")
        _require_text(self.permission, "DelegationGrant.permission")
        if not isinstance(cast(object, self.principal), DelegationPrincipal):
            raise ValueError("DelegationGrant.principal must be a DelegationPrincipal member.")


@dataclass(frozen=True, slots=True)
class Deployment:
    """The chosen providers, enlistments, and delegation grants for a deployment."""

    providers: Sequence[Provider]
    enlistments: Sequence[Enlistment]
    delegations: Sequence[DelegationGrant] = ()

    def __post_init__(self) -> None:
        providers = tuple(self.providers)
        enlistments = tuple(self.enlistments)
        delegations = tuple(self.delegations)
        object.__setattr__(self, "providers", providers)
        object.__setattr__(self, "enlistments", enlistments)
        object.__setattr__(self, "delegations", delegations)
        seen: set[str] = set()
        for provider in providers:
            if provider.name in seen:
                raise ValueError(f"provider {provider.name!r} is declared twice.")
            seen.add(provider.name)


@dataclass(frozen=True, slots=True)
class BoundWrite:
    """One required write, the session it is enlisted in, and the call path."""

    resource: DefinitionKey
    provider: str
    session: str
    via: tuple[DefinitionKey, ...]


@dataclass(frozen=True, slots=True)
class BoundEffect:
    """One declared effect pinned to the durable dedup store and session."""

    definition: DefinitionKey
    provider: str
    session: str
    dedup: str


@dataclass(frozen=True, slots=True)
class BoundCall:
    """One declared call edge with the child contract it resolves to."""

    caller: DefinitionKey
    callee: DefinitionKey
    permission: str | None


@dataclass(frozen=True, slots=True)
class BoundDelegation:
    """A checked delegation grant that stays inside the declared call contract."""

    caller: DefinitionKey
    callee: DefinitionKey
    permission: str


@dataclass(frozen=True, slots=True)
class SessionPlan:
    """The single session every required write of one action is enlisted in."""

    provider: str
    session: str
    capabilities: frozenset[Capability]
    writes: tuple[DefinitionKey, ...]


@dataclass(frozen=True, slots=True)
class BoundAction:
    """One action version bound to a deployment plan."""

    action: DefinitionKey
    commit_requirement: str | None
    writes: tuple[BoundWrite, ...]
    calls: tuple[BoundCall, ...]
    delegations: tuple[BoundDelegation, ...]
    session: SessionPlan | None
    effects: tuple[BoundEffect, ...] = ()


OUTBOX_RESOURCE = "codology.outbox"


type _CallEdge = tuple[DefinitionKey, DefinitionKey, str]
type _WriteHit = tuple[DefinitionKey, tuple[DefinitionKey, ...]]


def bind_action(
    published: Snapshot,
    deployment: Deployment,
    action: DefinitionKey,
) -> BoundAction:
    """Validate ``deployment`` for one exact action version and return its plan.

    The write set is transitive: the action's own ``writes`` plus the writes of
    every action or function reachable through ``calls``. Each required write
    must be enlisted exactly once, all required writes must name the same
    session, and an ``ATOMIC`` action requires that provider to claim
    ``Capability.ATOMIC_TRANSACTION``. Delegation grants are optional, but any
    grant for a reachable caller must match a declared Action call and repeat
    the child's declared permission exactly.

    Raises:
        BindingError: the deployment cannot satisfy the action's contract.
        UnknownDefinition: ``action`` is not published at that exact version.
        TypeError: an argument is not the value produced by its own phase.
    """
    if not isinstance(cast(object, published), Snapshot):
        raise TypeError("bind_action() expects the Snapshot produced by snapshot().")
    if not isinstance(cast(object, deployment), Deployment):
        raise TypeError("bind_action() expects a Deployment.")
    if not isinstance(cast(object, action), DefinitionKey):
        raise TypeError("bind_action() expects a version-explicit DefinitionKey.")

    entry = published.lookup(action.identity, action.version)
    if entry.kind != "Action":
        raise NotAnAction(
            f"definition kind is {entry.kind!r}; deployment binding applies to Action only.",
            action=action,
            field="kind",
        )

    writes_found, call_edges, requires_atomic = _closure(published, action, entry)
    calls = _bind_calls(published, call_edges)
    delegations = _check_delegations(deployment, action, calls)
    writes, session = _plan_session(deployment, action, requires_atomic, writes_found)
    effects = _plan_effects(deployment, action, entry, session)
    return BoundAction(
        action=action,
        commit_requirement=entry.commit_requirement,
        writes=writes,
        calls=calls,
        delegations=delegations,
        session=session,
        effects=effects,
    )


def _closure(
    published: Snapshot,
    action: DefinitionKey,
    entry: SnapshotEntry,
) -> tuple[tuple[_WriteHit, ...], tuple[_CallEdge, ...], bool]:
    """Walk ``calls`` from the root and collect every reachable write."""
    writes: dict[DefinitionKey, tuple[DefinitionKey, ...]] = {}
    calls: list[_CallEdge] = []
    requires_atomic = entry.commit_requirement == CommitRequirement.ATOMIC.value
    seen: set[DefinitionKey] = {action}
    queue: deque[tuple[DefinitionKey, tuple[DefinitionKey, ...], SnapshotEntry]] = deque(
        [(action, (action,), entry)]
    )
    while queue:
        caller, path, caller_entry = queue.popleft()
        for dependency in caller_entry.dependencies:
            if dependency.field == "writes":
                resource = _target(dependency, action, "writes")
                writes.setdefault(resource, path)
            elif dependency.field == "calls":
                callee = _target(dependency, action, "calls")
                calls.append((caller, callee, dependency.target_kind))
                if callee not in seen:
                    seen.add(callee)
                    callee_entry = published.lookup(callee.identity, callee.version)
                    if (
                        callee_entry.kind == "Action"
                        and callee_entry.commit_requirement == CommitRequirement.ATOMIC.value
                    ):
                        requires_atomic = True
                    queue.append((callee, (*path, callee), callee_entry))
    return tuple(writes.items()), tuple(calls), requires_atomic


def _target(dependency: Dependency, action: DefinitionKey, field: str) -> DefinitionKey:
    identity = dependency.target_identity
    version = dependency.target_version
    if identity is None or version is None:
        raise BindingError(
            f"a {field} edge has no versioned target; publish the target definition.",
            action=action,
            field=field,
        )
    return DefinitionKey(identity, version)


def _bind_calls(published: Snapshot, edges: tuple[_CallEdge, ...]) -> tuple[BoundCall, ...]:
    bound: list[BoundCall] = []
    for caller, callee, kind in edges:
        callee_entry = published.lookup(callee.identity, callee.version)
        permission = callee_entry.permission if kind == "Action" else None
        bound.append(BoundCall(caller=caller, callee=callee, permission=permission))
    return tuple(bound)


def _check_delegations(
    deployment: Deployment,
    action: DefinitionKey,
    calls: tuple[BoundCall, ...],
) -> tuple[BoundDelegation, ...]:
    for grant in deployment.delegations:
        if grant.principal is not DelegationPrincipal.REQUESTER:
            raise AmbientServiceIdentity(
                f"grant {grant.caller!r} -> {grant.call!r} uses the "
                f"{grant.principal.value!r} principal; a child call runs under the "
                "requester's narrowed authority, never an ambient service identity.",
                action=action,
                field="delegations",
            )

    edges = {(call.caller.identity, call.callee.identity): call for call in calls}
    callers = {call.caller.identity for call in calls} | {action.identity}
    bound: dict[tuple[str, str], BoundDelegation] = {}
    for grant in deployment.delegations:
        if grant.caller not in callers:
            continue
        edge = edges.get((grant.caller, grant.call))
        if edge is None:
            declared = ", ".join(
                sorted(f"{call.callee.identity}@{call.callee.version}" for call in calls)
            )
            listed = declared if declared else "none"
            raise UndeclaredCall(
                f"grant {grant.caller!r} -> {grant.call!r} does not match a declared "
                f"call; declared calls: {listed}.",
                action=action,
                field="delegations",
            )
        if edge.permission is None:
            raise UndeclaredCall(
                f"grant {grant.caller!r} -> {grant.call!r} targets a Function call; "
                "only Action calls carry a permission to delegate.",
                action=action,
                field="delegations",
            )
        if grant.permission != edge.permission:
            raise PermissionBroadened(
                f"grant {grant.caller!r} -> {grant.call!r} requests permission "
                f"{grant.permission!r}, but the child action contract declares "
                f"{edge.permission!r}; a grant must repeat the child permission exactly, "
                "so it cannot be broader than the declaration.",
                action=action,
                field="delegations",
            )
        bound[(grant.caller, grant.call)] = BoundDelegation(
            caller=edge.caller,
            callee=edge.callee,
            permission=grant.permission,
        )
    return tuple(bound.values())


def _plan_session(
    deployment: Deployment,
    action: DefinitionKey,
    requires_atomic: bool,
    writes_found: tuple[_WriteHit, ...],
) -> tuple[tuple[BoundWrite, ...], SessionPlan | None]:
    if not writes_found:
        return (), None

    providers = {provider.name: provider for provider in deployment.providers}
    enlistments = _enlistment_index(deployment, action)
    bound: list[BoundWrite] = []
    sessions: dict[str, tuple[str, Provider]] = {}
    for resource, via in writes_found:
        enlistment = enlistments.get(resource.identity)
        if enlistment is None:
            writer = via[-1]
            raise UnboundWrite(
                f"write to {resource.identity!r} reached through {writer.identity!r} "
                "has no enlistment; every resource in the transitive write set needs one.",
                action=action,
                field="writes",
            )
        provider = providers.get(enlistment.provider)
        if provider is None:
            raise UnknownProvider(
                f"resource {resource.identity!r} is enlisted in provider "
                f"{enlistment.provider!r}, which the deployment does not declare.",
                action=action,
                field="enlistments",
            )
        previous = sessions.get(enlistment.session)
        if previous is not None and previous[0] != enlistment.provider:
            raise InconsistentSession(
                f"session {enlistment.session!r} is claimed by providers "
                f"{previous[0]!r} and {enlistment.provider!r}; a matching label cannot "
                "stand in for one physical session.",
                action=action,
                field="enlistments",
            )
        sessions.setdefault(enlistment.session, (enlistment.provider, provider))
        bound.append(
            BoundWrite(
                resource=resource,
                provider=enlistment.provider,
                session=enlistment.session,
                via=via,
            )
        )

    if len(sessions) > 1:
        listed = ", ".join(sorted(repr(session) for session in sessions))
        raise NoSharedTransaction(
            f"strict atomic refused: required writes span separate sessions [{listed}]. "
            "Two enlistments of the same database kind are not one physical session.",
            action=action,
            field="sessions",
        )

    session_name, (provider_name, provider) = next(iter(sessions.items()))
    if requires_atomic and Capability.ATOMIC_TRANSACTION not in provider.capabilities:
        raise MissingCapability(
            f"provider {provider.name!r} (kind {provider.kind!r}) does not declare "
            f"{Capability.ATOMIC_TRANSACTION.value!r}; an ATOMIC action cannot be bound.",
            action=action,
            field="capabilities",
        )
    plan = SessionPlan(
        provider=provider_name,
        session=session_name,
        capabilities=provider.capabilities,
        writes=tuple(one.resource for one in bound),
    )
    return tuple(bound), plan


def _enlistment_index(deployment: Deployment, action: DefinitionKey) -> dict[str, Enlistment]:
    index: dict[str, Enlistment] = {}
    for enlistment in deployment.enlistments:
        if enlistment.resource in index:
            raise AmbiguousEnlistment(
                f"resource {enlistment.resource!r} has more than one enlistment; "
                "a write must name exactly one session.",
                action=action,
                field="enlistments",
            )
        index[enlistment.resource] = enlistment
    return index


def _plan_effects(
    deployment: Deployment,
    action: DefinitionKey,
    entry: SnapshotEntry,
    session: SessionPlan | None,
) -> tuple[BoundEffect, ...]:
    """Bind declared effects to one outbox store inside the business session."""
    targets = tuple(
        _target(dependency, action, "effects")
        for dependency in entry.dependencies
        if dependency.field == "effects"
    )
    if not targets:
        return ()
    if session is None:
        raise EffectSessionMismatch(
            "declared effects need an enlisted outbox session; the action has no write session.",
            action=action,
            field="effects",
        )
    providers = {provider.name: provider for provider in deployment.providers}
    enlistments = _enlistment_index(deployment, action)
    enlistment = enlistments.get(OUTBOX_RESOURCE)
    if enlistment is None:
        raise EffectSessionMismatch(
            f"declared effects need an enlistment for {OUTBOX_RESOURCE!r} in session "
            f"{session.session!r}.",
            action=action,
            field="effects",
        )
    if enlistment.session != session.session or enlistment.provider != session.provider:
        raise EffectSessionMismatch(
            f"the outbox is enlisted in session {enlistment.session!r} on provider "
            f"{enlistment.provider!r}, but business writes use {session.session!r} on "
            f"{session.provider!r}; an effect must commit in the same transaction.",
            action=action,
            field="effects",
        )
    provider = providers.get(enlistment.provider)
    if provider is None:
        raise UnknownProvider(
            f"the outbox provider {enlistment.provider!r} is not declared by the deployment.",
            action=action,
            field="effects",
        )
    if Capability.OUTBOX not in provider.capabilities:
        raise MissingCapability(
            f"provider {provider.name!r} does not declare "
            f"{Capability.OUTBOX.value!r}; declared effects cannot be bound.",
            action=action,
            field="capabilities",
        )
    if not provider.effect_dedup:
        raise MissingCapability(
            f"provider {provider.name!r} declares no effect_dedup store; declared effects "
            "need durable dedup at binding time.",
            action=action,
            field="effect_dedup",
        )
    return tuple(
        BoundEffect(target, provider.name, enlistment.session, provider.effect_dedup)
        for target in targets
    )
