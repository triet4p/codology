"""Engine invoke gate: live authorization, scoped resolution, one scoped UoW.

A consumer never supplies a connection, a handler result, or its own mutation
plan. The engine takes a linked graph and the deployment plan bound from that
same graph, checks invoke authority and the current read scope, resolves every
typed ref through the read port, runs one declared handler with a narrow context,
and dispatches declared child handlers at their linked revisions into that same
unit of work. It then revalidates the world and commits one guarded transaction
or changes nothing. A scoped request key binds the authoritative local result to
that commit, so a replay returns the stored answer instead of running handlers.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, cast

from codology.binding import BoundAction, BoundCall, BoundDelegation, SessionPlan
from codology.declarations import Action, ObjectRef
from codology.gate_support import (
    InvokeDenied,
    bound_session,
    declared_writes,
    defined_keys,
    discard_unit,
    linked_action,
    ref_target,
    request_scope,
    require_writes,
)
from codology.ledger import (
    DuplicateRequest,
    LedgerEntry,
    LedgerUnitOfWork,
    RequestScope,
    canonicalize,
    encode_result,
)
from codology.ledger import intent_fingerprint as compute_intent_fingerprint
from codology.linking import LinkedDeclarations, LinkedDefinition
from codology.money import MinorMoney
from codology.ports import (
    Assignment,
    CommitOutcomeUnknown,
    Condition,
    GuardedWrite,
    StalePlan,
    TransactionUnavailable,
    UnitOfWork,
)
from codology.query import (
    Principal,
    QueryRow,
    ReadGrant,
    VersionedRef,
    authorize_read,
    is_issued_ref,
)
from codology.results import (
    KEY_MISUSE_DETAIL as _KEY_MISUSE_DETAIL,
)
from codology.results import (
    ActionResult,
    AttemptOutcome,
    CommittedChange,
    ExecutionRecord,
    reconcile,
)
from codology.results import (
    duplicate_outcome as _duplicate_outcome,
)
from codology.results import (
    outcome as _outcome,
)
from codology.results import (
    replay as _replay,
)
from codology.results import (
    stored_replay as _stored_replay,
)
from codology.results import (
    stored_result as _stored_result,
)
from codology.snapshot import DefinitionKey
from codology.uow import UnboundWriteAttempt, commit_guarded_writes
from codology.waiting import ObjectVersion, build_awaiting, claim_awaiting_key

_DENIED_DETAIL = "invoke request was refused by the engine gate."
_STALE_DETAIL = "the resolved world changed; re-read and recompute before retrying."
_UNAVAILABLE_DETAIL = "the bound transaction did not complete; no commit was confirmed."
_SEAL = object()


class BusinessRejected(ValueError):
    """A handler's ``ctx.require`` failed; this is a business outcome."""


class WriteNotDeclared(InvokeDenied):
    """A mutation targets an object the action did not declare as writable."""


class _Stale(Exception):
    """A resolved version no longer matches the current world."""


class ResourceSpec(Protocol):
    """The mapped columns an engine needs to check a registration."""

    @property
    def columns(self) -> tuple[str, ...]: ...


class ScopedEngineProvider(Protocol):
    """Read-port resolution plus the bound transaction port, owned by an adapter."""

    @property
    def resources(self) -> Mapping[str, ResourceSpec]: ...

    def resolve(self, ref: VersionedRef[object], grant: ReadGrant) -> QueryRow[object] | None: ...

    def begin(self, plan: SessionPlan) -> UnitOfWork: ...

    def lookup(self, scope: RequestScope, request_key: str) -> LedgerEntry | None: ...


@dataclass(frozen=True, slots=True)
class ResolvedObject[T]:
    """A row handle issued by scoped resolution; it carries no authority itself."""

    definition: DefinitionKey
    key: str
    version: int
    values: Mapping[str, object]
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _SEAL:
            raise ValueError("resolved objects are issued by the engine only.")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    @property
    def ref(self) -> VersionedRef[T]:
        return cast(VersionedRef[T], VersionedRef.issue(self.definition, self.key, self.version))

    @property
    def instance_version(self) -> int:
        """The row version carried by the ref this handle came from."""
        return self.version

    def __getattr__(self, name: str) -> object:
        values = object.__getattribute__(self, "values")
        if name in values:
            return values[name]
        raise AttributeError(f"{type(self).__name__} has no field {name!r}.")


@dataclass(frozen=True, slots=True)
class _Registration:
    target: ResolvedObject[object]
    changes: tuple[Assignment, ...]
    guards: tuple[Condition, ...]


@dataclass(slots=True)
class _Execution:
    """State shared by one root handler and every declared child handler."""

    linked: LinkedDeclarations
    bound: BoundAction
    provider: ScopedEngineProvider
    grants: Mapping[DefinitionKey, ReadGrant]
    columns: Mapping[str, tuple[str, ...]]
    registrations: list[_Registration]
    children: list[DefinitionKey]


class ScopedUoW:
    """Mutation registration only; commit and rollback stay with the engine."""

    __slots__ = ("_allowed", "_columns", "_registrations")

    def __init__(
        self,
        allowed: frozenset[str],
        columns: Mapping[str, tuple[str, ...]],
        registrations: list[_Registration] | None = None,
    ) -> None:
        self._allowed = allowed
        self._columns = columns
        self._registrations = [] if registrations is None else registrations

    def register_mutation(self, obj: object, **fields: object) -> None:
        """Register one guarded intent on a resolved object the action may write."""
        if not isinstance(obj, ResolvedObject):
            raise InvokeDenied("mutations need an object resolved by this execution.")
        expected = fields.pop("expectedVersion", None)
        if type(expected) is not int:
            raise InvokeDenied("expectedVersion must be the integer version of the object.")
        if expected != obj.version:
            raise _Stale()
        if obj.definition.identity not in self._allowed or not fields:
            raise WriteNotDeclared("the mutation is outside the declared write set.")
        mapped = self._columns.get(obj.definition.identity, ())
        if any(name not in mapped for name in fields):
            raise InvokeDenied("the mutation names a column the adapter did not map.")

        guards = tuple(
            Condition(column, "==", value)
            for column in mapped
            if (value := obj.values.get(column)) is not None
            and isinstance(value, str | int | MinorMoney)
            and not isinstance(value, bool)
        )
        changes = tuple(Assignment(name, "set", value) for name, value in fields.items())
        self._registrations.append(
            _Registration(cast(ResolvedObject[object], obj), changes, guards)
        )

    @property
    def registrations(self) -> tuple[_Registration, ...]:
        return tuple(self._registrations)


class HandlerCtx:
    """The only surface a handler sees: principal, reads, writes, calls, require."""

    __slots__ = (
        "_calls",
        "_delegations",
        "_execution",
        "_principal",
        "_reads",
        "_uow",
        "_writes",
    )

    def __init__(
        self,
        *,
        principal: Principal,
        reads: frozenset[DefinitionKey],
        writes: frozenset[str],
        calls: tuple[BoundCall, ...],
        delegations: tuple[BoundDelegation, ...],
        execution: _Execution,
    ) -> None:
        self._principal = principal
        self._reads = reads
        self._writes = writes
        self._calls = calls
        self._delegations = delegations
        self._execution = execution
        self._uow = ScopedUoW(writes, execution.columns, execution.registrations)

    @property
    def principal(self) -> Principal:
        """The authenticated requester; never an approver or service identity."""
        return self._principal

    @property
    def reads(self) -> tuple[DefinitionKey, ...]:
        return tuple(sorted(self._reads))

    @property
    def writes(self) -> tuple[str, ...]:
        return tuple(sorted(self._writes))

    @property
    def calls(self) -> tuple[str, ...]:
        return tuple(sorted({bound.callee.identity for bound in self._calls}))

    @property
    def uow(self) -> ScopedUoW:
        return self._uow

    def require(self, condition: bool, *, reason: str) -> None:
        """Turn a false business condition into `REJECTED`, never `DENIED`."""
        if type(condition) is not bool or type(reason) is not str or not reason.strip():
            raise InvokeDenied("require needs a boolean condition and a reason.")
        if not condition:
            raise BusinessRejected(reason)

    def resolve(self, ref: object) -> ResolvedObject[object]:
        """Resolve an issued ref only inside the action's declared read set."""
        if not is_issued_ref(ref):
            raise InvokeDenied("only refs issued by an authorized query can be resolved.")
        typed = cast(VersionedRef[object], ref)
        if typed.definition not in self._reads:
            raise InvokeDenied("the ref type is outside the declared read set.")
        return _resolve_scoped(
            self._execution.provider, self._principal, self._execution.grants, typed
        )

    def call(self, action: object, **params: object) -> object:
        """Dispatch one declared child Action at its linked revision under narrowed authority."""
        if not isinstance(action, str):
            raise InvokeDenied("a call names an action identity.")
        target = next((bound for bound in self._calls if bound.callee.identity == action), None)
        if target is None:
            raise InvokeDenied("the call is not declared by this action.")
        delegation = next(
            (item for item in self._delegations if item.callee == target.callee),
            None,
        )
        if delegation is None:
            raise InvokeDenied("the call has no checked delegation grant.")
        entry = self._execution.linked.definitions.get(target.callee.identity)
        if entry is None or entry.definition.version != target.callee.version:
            raise InvokeDenied("the declared child revision is not in the linked graph.")
        raw = entry.definition.declaration
        if not issubclass(raw, Action):
            raise InvokeDenied("a declared call must target an Action.")
        declaration = raw
        if declaration.approval is not None or declaration.effects:
            raise InvokeDenied(
                "the child declaration needs governance a synchronous call cannot honor."
            )
        if declaration.permission != delegation.permission:
            raise InvokeDenied("the delegation does not match the child's declared permission.")
        if declaration.permission not in self._principal.permissions:
            raise InvokeDenied("the requester has no live delegated permission for this call.")

        arguments = _child_arguments(entry, params, self._execution, self._principal)
        child = HandlerCtx(
            principal=self._principal,
            reads=defined_keys(self._execution.linked, declaration.reads),
            writes=declared_writes(self._execution.linked, declaration.writes),
            calls=tuple(
                bound for bound in self._execution.bound.calls if bound.caller == target.callee
            ),
            delegations=tuple(
                item for item in self._execution.bound.delegations if item.caller == target.callee
            ),
            execution=self._execution,
        )
        self._execution.children.append(target.callee)
        handler = vars(declaration).get("handler")
        if not callable(handler):
            raise InvokeDenied("the linked child has no callable handler.")
        return handler(declaration(), child, **arguments)


def invoke(
    *,
    linked: LinkedDeclarations,
    action: DefinitionKey,
    bound: BoundAction,
    provider: ScopedEngineProvider,
    principal: Principal,
    grants: Mapping[DefinitionKey, ReadGrant],
    parameters: Mapping[str, object],
    request_key: str | None = None,
    intent_fingerprint: str | None = None,
    approval_expires_at: str | None = None,
) -> ActionResult:
    """Run one declared handler and its declared children, committing at most once."""
    execution: _Execution | None = None
    unit: UnitOfWork | None = None
    scope: RequestScope | None = None
    fingerprint: str | None = None
    try:
        entry = linked_action(linked, action, bound)
        declaration = cast(type[Action], entry.definition.declaration)
        if declaration.permission not in principal.permissions:
            raise InvokeDenied("the requester lacks the action's invoke permission.")
        approval = declaration.approval
        if declaration.effects:
            raise InvokeDenied(
                "this declaration needs effect governance a synchronous invoke cannot honor."
            )
        if request_key is not None:
            scope = request_scope(principal, action)
            fingerprint = compute_intent_fingerprint(action, parameters)
            unit = provider.begin(bound_session(bound))
            stored = cast(LedgerUnitOfWork, unit).lookup(scope, request_key)
            if stored is not None:
                pinned = compute_intent_fingerprint(
                    DefinitionKey(action.identity, stored.action_version), parameters
                )
                if intent_fingerprint is not None and intent_fingerprint != pinned:
                    raise InvokeDenied(_KEY_MISUSE_DETAIL)
                if stored.intent_fingerprint != pinned:
                    raise InvokeDenied(_KEY_MISUSE_DETAIL)
                fingerprint = pinned
                replayed = _replay(stored)
                if replayed is None:
                    raise InvokeDenied("the stored execution cannot be verified.")
                discard_unit(unit)
                return replayed
            if intent_fingerprint is not None and intent_fingerprint != fingerprint:
                raise InvokeDenied(_KEY_MISUSE_DETAIL)
            if approval is not None:
                discard_unit(unit)
                unit = None
        arguments = _arguments(entry, action, parameters, provider, principal, grants)
        columns = {identity: tuple(spec.columns) for identity, spec in provider.resources.items()}
        allowed_writes = declared_writes(linked, declaration.writes)
        require_writes(bound, allowed_writes)
        execution = _Execution(linked, bound, provider, grants, columns, [], [])
        ctx = HandlerCtx(
            principal=principal,
            reads=defined_keys(linked, declaration.reads),
            writes=allowed_writes,
            calls=bound.calls,
            delegations=bound.delegations,
            execution=execution,
        )
        handler = cast(Callable[..., object], vars(declaration)["handler"])
        handler(declaration(), ctx, **arguments)

        if approval is not None:
            versions = tuple(
                ObjectVersion(value.definition.identity, value.key, value.version)
                for value in arguments.values()
                if isinstance(value, ResolvedObject)
            )
            scopes = tuple(sorted({name for grant in grants.values() for name in grant.scopes}))
            awaiting = build_awaiting(
                approval=approval,
                arguments=arguments,
                canonical_input=cast(Mapping[str, object], canonicalize(dict(parameters))),
                object_versions=versions,
                linked=linked,
                action=action,
                principal=principal,
                scopes=scopes,
                expires_at=approval_expires_at,
            )
            if awaiting is not None:
                if scope is None or request_key is None or fingerprint is None:
                    raise InvokeDenied("an approval wait needs a scoped request key.")
                existing = claim_awaiting_key(
                    provider,
                    bound_session(bound),
                    scope,
                    request_key,
                    fingerprint,
                    action.version,
                    awaiting,
                )
                if existing is not None:
                    return _stored_replay(existing, request_key, fingerprint)
                intent = awaiting.material_intent
                return ActionResult(
                    AttemptOutcome("AWAITING_APPROVAL", None, request_key, fingerprint),
                    ExecutionRecord(
                        awaiting.execution_id,
                        "AWAITING_APPROVAL",
                        awaiting.action,
                        awaiting.requester,
                        (),
                        intent.child_keys,
                        True,
                        awaiting.pinned_manifest,
                        intent,
                        awaiting.required_approval,
                        awaiting.canonical_input,
                    ),
                )
        registrations = tuple(execution.registrations)
        if not registrations:
            raise InvokeDenied("a write-declaring action registered no mutation.")
        writes = _guarded(registrations, bound, provider, principal, grants)
        changes = tuple(
            CommittedChange(
                item.target.definition.identity, item.target.key, item.target.version, item.changes
            )
            for item in registrations
        )
        record = ExecutionRecord(
            uuid.uuid4().hex, "COMMITTED", action, principal, changes, tuple(execution.children)
        )
        ledger_entry: LedgerEntry | None = None
        if request_key is not None and scope is not None and fingerprint is not None:
            ledger_entry = LedgerEntry(
                scope,
                request_key,
                fingerprint,
                record.execution_id,
                action.version,
                "COMMITTED",
                encode_result(_stored_result(record)),
            )
        results = commit_guarded_writes(
            provider, bound_session(bound), writes, entry=ledger_entry, unit=unit
        )
    except BusinessRejected as exc:
        discard_unit(unit)
        return _rejected(action, principal, str(exc), _children(execution))
    except DuplicateRequest:
        discard_unit(unit)
        return _duplicate_outcome(provider, scope, request_key, fingerprint)
    except (InvokeDenied, UnboundWriteAttempt, ValueError, PermissionError) as exc:
        discard_unit(unit)
        detail = str(exc) if isinstance(exc, InvokeDenied) else _DENIED_DETAIL
        return _outcome(
            "DENIED",
            detail,
            reason="KEY_MISUSE" if detail == _KEY_MISUSE_DETAIL else None,
            request_key=request_key,
            intent_fingerprint=fingerprint,
        )
    except (_Stale, StalePlan):
        discard_unit(unit)
        return _outcome(
            "StalePlan", _STALE_DETAIL, request_key=request_key, intent_fingerprint=fingerprint
        )
    except (TransactionUnavailable, CommitOutcomeUnknown):
        discard_unit(unit)
        return _outcome(
            "UNKNOWN", _UNAVAILABLE_DETAIL, request_key=request_key, intent_fingerprint=fingerprint
        )

    return ActionResult(
        attempt=AttemptOutcome("COMMITTED", None, request_key, fingerprint),
        execution=record,
        writes=tuple(results),
    )


def _arguments(
    entry: LinkedDefinition,
    action: DefinitionKey,
    parameters: Mapping[str, object],
    provider: ScopedEngineProvider,
    principal: Principal,
    grants: Mapping[DefinitionKey, ReadGrant],
) -> dict[str, object]:
    declaration = cast(type[Action], entry.definition.declaration)
    if set(parameters) != set(declaration.properties):
        raise InvokeDenied("parameters must match the declared parameter names exactly.")
    arguments: dict[str, object] = {}
    for name in declaration.properties:
        hint = entry.hints[name]
        value = parameters[name]
        if isinstance(hint, type) and issubclass(hint, ObjectRef):
            expected = ref_target(hint)
            if not is_issued_ref(value):
                raise InvokeDenied(
                    "a typed ref parameter needs a ref issued by an authorized query."
                )
            typed = cast(VersionedRef[object], value)
            if typed.definition != expected:
                raise InvokeDenied("the ref does not match the declared parameter type.")
            arguments[name] = _resolve_scoped(provider, principal, grants, typed)
            continue
        if isinstance(hint, type) and not isinstance(value, hint):
            raise InvokeDenied("a parameter has the wrong declared type.")
        if hint is int and isinstance(value, bool):
            raise InvokeDenied("a boolean is not an integer parameter.")
        arguments[name] = value
    return arguments


def _child_arguments(
    entry: LinkedDefinition,
    parameters: Mapping[str, object],
    execution: _Execution,
    principal: Principal,
) -> dict[str, object]:
    """Resolve child parameters against the child's own linked contract and live scope."""
    declaration = cast(type[Action], entry.definition.declaration)
    if set(parameters) != set(declaration.properties):
        raise InvokeDenied("child parameters must match the declared parameter names exactly.")
    arguments: dict[str, object] = {}
    for name in declaration.properties:
        hint = entry.hints[name]
        value = parameters[name]
        if isinstance(hint, type) and issubclass(hint, ObjectRef):
            if isinstance(value, ResolvedObject):
                handle = cast(ResolvedObject[object], value)
                value = handle.ref
            expected = ref_target(hint)
            if not is_issued_ref(value):
                raise InvokeDenied("a typed child ref needs a ref issued by an authorized query.")
            typed = cast(VersionedRef[object], value)
            if typed.definition != expected:
                raise InvokeDenied("the child ref does not match the declared parameter type.")
            arguments[name] = _resolve_scoped(
                execution.provider, principal, execution.grants, typed
            )
            continue
        if isinstance(hint, type) and not isinstance(value, hint):
            raise InvokeDenied("a child parameter has the wrong declared type.")
        if hint is int and isinstance(value, bool):
            raise InvokeDenied("a boolean is not an integer child parameter.")
        arguments[name] = value
    return arguments


def _resolve_scoped(
    provider: ScopedEngineProvider,
    principal: Principal,
    grants: Mapping[DefinitionKey, ReadGrant],
    ref: VersionedRef[object],
) -> ResolvedObject[object]:
    grant = grants.get(ref.definition)
    if grant is None:
        raise InvokeDenied("no current read grant covers this ref's definition.")
    authorize_read(principal, grant, ref.definition)
    row = provider.resolve(ref, grant)
    if row is None:
        raise InvokeDenied("the ref is outside the current tenant or scope.")
    if row.instance_version != ref.instance_version:
        raise _Stale()
    return _resolved(row)


def _resolved(row: QueryRow[object]) -> ResolvedObject[object]:
    return ResolvedObject(row.definition, row.key, row.instance_version, row.values, _SEAL)


def _guarded(
    registrations: tuple[_Registration, ...],
    bound: BoundAction,
    provider: ScopedEngineProvider,
    principal: Principal,
    grants: Mapping[DefinitionKey, ReadGrant],
) -> tuple[GuardedWrite, ...]:
    session = bound_session(bound)
    for registration in registrations:
        target = registration.target
        ref = target.ref
        row = _resolve_scoped(provider, principal, grants, ref)
        if row.version != target.version:
            raise _Stale()
        if target.definition.identity not in {item.identity for item in session.writes}:
            raise WriteNotDeclared("the write is not enlisted in the bound session.")
    return tuple(
        GuardedWrite(
            item.target.definition.identity,
            item.target.key,
            item.target.version,
            item.changes,
            item.guards,
        )
        for item in registrations
    )


def _children(execution: _Execution | None) -> tuple[DefinitionKey, ...]:
    return () if execution is None else tuple(execution.children)


def _rejected(
    action: DefinitionKey,
    principal: Principal,
    detail: str,
    children: tuple[DefinitionKey, ...] = (),
) -> ActionResult:
    record = ExecutionRecord(uuid.uuid4().hex, "REJECTED", action, principal, (), children)
    return ActionResult(AttemptOutcome("REJECTED", detail), record)


__all__ = [
    "ActionResult",
    "AttemptOutcome",
    "BusinessRejected",
    "CommittedChange",
    "ExecutionRecord",
    "HandlerCtx",
    "InvokeDenied",
    "ResolvedObject",
    "ScopedEngineProvider",
    "ScopedUoW",
    "WriteNotDeclared",
    "invoke",
    "reconcile",
]
