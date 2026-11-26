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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol, cast

from codology.binding import BoundAction, BoundCall, BoundDelegation, SessionPlan
from codology.declarations import Action, ObjectRef
from codology.ledger import (
    EXECUTION_READ_PERMISSION,
    DuplicateRequest,
    LedgerEntry,
    LedgerProvider,
    LedgerUnitOfWork,
    RequestScope,
    StoredChange,
    StoredResult,
    decode_result,
    encode_result,
)
from codology.ledger import (
    intent_fingerprint as compute_intent_fingerprint,
)
from codology.linking import LinkedDeclarations, LinkedDefinition
from codology.money import MinorMoney
from codology.ports import (
    ApplyResult,
    Assignment,
    Condition,
    GuardedWrite,
    SetOp,
    StalePlan,
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
from codology.snapshot import DefinitionKey
from codology.uow import UnboundWriteAttempt, commit_guarded_writes

InvokeCode = Literal["COMMITTED", "DENIED", "REJECTED", "StalePlan", "UNKNOWN"]
ExecutionStatus = Literal["COMMITTED", "REJECTED"]

_DENIED_DETAIL = "invoke request was refused by the engine gate."
_STALE_DETAIL = "the resolved world changed; re-read and recompute before retrying."
_KEY_MISUSE_DETAIL = "the request key and intent do not match the stored result."
_UNKNOWN_DETAIL = "no authoritative result is available for this request."
_SEAL = object()


class InvokeDenied(ValueError):
    """A request, ref, or context capability failed a closed engine gate."""


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
class AttemptOutcome:
    """What the caller may know about one invoke attempt."""

    code: InvokeCode
    detail: str | None
    request_key: str | None = None
    intent_fingerprint: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CommittedChange:
    """One accepted mutation plan, without exposing handler internals."""

    resource: str
    key: str
    version: int
    changes: tuple[Assignment, ...]


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """The authoritative outcome of one accepted execution, replayable from the ledger."""

    execution_id: str
    status: ExecutionStatus
    action: DefinitionKey
    requester: Principal
    committed: tuple[CommittedChange, ...] = ()
    children: tuple[DefinitionKey, ...] = ()
    deduplicated: bool = False


@dataclass(frozen=True, slots=True)
class ActionResult:
    """An attempt outcome plus an execution only when one was actually created."""

    attempt: AttemptOutcome
    execution: ExecutionRecord | None = None
    writes: tuple[ApplyResult, ...] = ()


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
        target = next(
            (bound for bound in self._calls if bound.callee.identity == action),
            None,
        )
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
            reads=_defined_keys(self._execution.linked, declaration.reads),
            writes=_declared_writes(self._execution.linked, declaration.writes),
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
) -> ActionResult:
    """Run one declared handler and its declared children, committing at most once."""
    execution: _Execution | None = None
    unit: UnitOfWork | None = None
    scope: RequestScope | None = None
    fingerprint: str | None = None
    try:
        entry = _entry(linked, action, bound)
        declaration = cast(type[Action], entry.definition.declaration)
        if declaration.permission not in principal.permissions:
            raise InvokeDenied("the requester lacks the action's invoke permission.")
        if declaration.approval is not None or declaration.effects:
            raise InvokeDenied(
                "this declaration needs governance a synchronous invoke cannot honor."
            )
        if request_key is not None:
            scope = _request_scope(principal, action)
            fingerprint = compute_intent_fingerprint(action, parameters)
            if intent_fingerprint is not None and intent_fingerprint != fingerprint:
                raise InvokeDenied(_KEY_MISUSE_DETAIL)
            unit = provider.begin(_session(bound))
            stored = cast(LedgerUnitOfWork, unit).lookup(scope, request_key)
            if stored is not None:
                if stored.intent_fingerprint != fingerprint:
                    raise InvokeDenied(_KEY_MISUSE_DETAIL)
                replayed = _replay(stored)
                if replayed is None:
                    raise InvokeDenied("the stored execution cannot be verified.")
                return replayed
        arguments = _arguments(entry, action, parameters, provider, principal, grants)
        columns = {identity: tuple(spec.columns) for identity, spec in provider.resources.items()}
        allowed_writes = _declared_writes(linked, declaration.writes)
        _require_plan_writes(bound, allowed_writes)
        execution = _Execution(linked, bound, provider, grants, columns, [], [])
        ctx = HandlerCtx(
            principal=principal,
            reads=_defined_keys(linked, declaration.reads),
            writes=allowed_writes,
            calls=bound.calls,
            delegations=bound.delegations,
            execution=execution,
        )
        handler = cast(Callable[..., object], vars(declaration)["handler"])
        handler(declaration(), ctx, **arguments)

        registrations = tuple(execution.registrations)
        if not registrations:
            raise InvokeDenied("a write-declaring action registered no mutation.")
        writes = _guarded(registrations, bound, provider, principal, grants)
        record = ExecutionRecord(
            execution_id=uuid.uuid4().hex,
            status="COMMITTED",
            action=action,
            requester=principal,
            committed=tuple(
                CommittedChange(
                    item.target.definition.identity,
                    item.target.key,
                    item.target.version,
                    item.changes,
                )
                for item in registrations
            ),
            children=tuple(execution.children),
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
            provider, _session(bound), writes, entry=ledger_entry, unit=unit
        )
    except BusinessRejected as exc:
        _discard(unit)
        return _rejected(action, principal, str(exc), _children(execution))
    except DuplicateRequest:
        _discard(unit)
        return _duplicate_outcome(provider, scope, request_key, fingerprint)
    except (InvokeDenied, UnboundWriteAttempt, ValueError, PermissionError) as exc:
        _discard(unit)
        detail = str(exc) if isinstance(exc, InvokeDenied) else _DENIED_DETAIL
        return _outcome(
            "DENIED",
            detail,
            reason="KEY_MISUSE" if detail == _KEY_MISUSE_DETAIL else None,
            request_key=request_key,
            intent_fingerprint=fingerprint,
        )
    except (_Stale, StalePlan):
        _discard(unit)
        return _outcome(
            "StalePlan", _STALE_DETAIL, request_key=request_key, intent_fingerprint=fingerprint
        )

    return ActionResult(
        attempt=AttemptOutcome("COMMITTED", None, request_key, fingerprint),
        execution=record,
        writes=tuple(results),
    )


def reconcile(
    *,
    provider: LedgerProvider,
    principal: Principal,
    action: DefinitionKey,
    request_key: str,
) -> ActionResult:
    """Return a stored authoritative result only to a reader with record authority."""
    if EXECUTION_READ_PERMISSION not in principal.permissions:
        return _outcome("DENIED", "read authority for execution records is required.")
    if not request_key.strip():
        return _outcome("UNKNOWN", _UNKNOWN_DETAIL)
    stored = provider.lookup(_request_scope(principal, action), request_key)
    if stored is None:
        return _outcome("UNKNOWN", _UNKNOWN_DETAIL)
    replayed = _replay(stored)
    if replayed is None:
        return _outcome("UNKNOWN", _UNKNOWN_DETAIL)
    return replayed


def _request_scope(principal: Principal, action: DefinitionKey) -> RequestScope:
    return RequestScope(principal.tenant, principal.identity, action.identity)


def _discard(unit: UnitOfWork | None) -> None:
    if unit is None:
        return
    try:
        unit.rollback()
    finally:
        unit.close()


def _duplicate_outcome(
    provider: ScopedEngineProvider,
    scope: RequestScope | None,
    request_key: str | None,
    fingerprint: str | None,
) -> ActionResult:
    if scope is not None and request_key is not None and fingerprint is not None:
        stored = provider.lookup(scope, request_key)
        if stored is not None and stored.intent_fingerprint == fingerprint:
            replayed = _replay(stored)
            if replayed is not None:
                return replayed
        return _outcome(
            "DENIED",
            _KEY_MISUSE_DETAIL,
            reason="KEY_MISUSE",
            request_key=request_key,
            intent_fingerprint=fingerprint,
        )
    return _outcome("DENIED", _DENIED_DETAIL)


def _stored_result(record: ExecutionRecord) -> StoredResult:
    return StoredResult(
        record.execution_id,
        "COMMITTED",
        record.action,
        record.requester,
        tuple(
            StoredChange(
                item.resource,
                item.key,
                item.version,
                tuple((c.column, c.op, c.value) for c in item.changes),
            )
            for item in record.committed
        ),
        record.children,
    )


def _replay(stored: LedgerEntry) -> ActionResult | None:
    result = decode_result(stored.payload)
    if result is None:
        return None
    return ActionResult(
        attempt=AttemptOutcome("COMMITTED", None, stored.request_key, stored.intent_fingerprint),
        execution=ExecutionRecord(
            result.execution_id,
            "COMMITTED",
            result.action,
            result.requester,
            tuple(
                CommittedChange(
                    item.resource,
                    item.key,
                    item.version,
                    tuple(
                        Assignment(column, cast(SetOp, op), value)
                        for column, op, value in item.changes
                    ),
                )
                for item in result.committed
            ),
            result.children,
            deduplicated=True,
        ),
    )


def _entry(
    linked: LinkedDeclarations,
    action: DefinitionKey,
    bound: BoundAction,
) -> LinkedDefinition:
    if bound.action != action or bound.session is None:
        raise InvokeDenied("the bound plan does not name this exact action and session.")
    entry = linked.definitions.get(action.identity)
    if (
        entry is None
        or entry.definition.version != action.version
        or not issubclass(entry.definition.declaration, Action)
    ):
        raise InvokeDenied("no linked action exists at this exact identity and version.")
    return entry


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
            expected = _ref_target(hint)
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
            expected = _ref_target(hint)
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


def _ref_target(hint: type[object]) -> DefinitionKey:
    target = cast(object, getattr(hint, "target", None))
    identity = getattr(target, "identity", None)
    version = getattr(target, "version", None)
    if not isinstance(identity, str) or not identity or not isinstance(version, str) or not version:
        raise InvokeDenied("the declared ref target is not version-explicit.")
    return DefinitionKey(identity, version)


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
    return ResolvedObject(
        row.definition,
        row.key,
        row.instance_version,
        row.values,
        _SEAL,
    )


def _defined_keys(linked: LinkedDeclarations, raw: Sequence[object]) -> frozenset[DefinitionKey]:
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


def _declared_writes(linked: LinkedDeclarations, raw: Sequence[object]) -> frozenset[str]:
    identities = {getattr(item, "identity", item) for item in raw}
    return frozenset(
        identity
        for identity in (item.definition.identity for item in linked.all_definitions)
        if identity is not None and identity in identities
    )


def _require_plan_writes(bound: BoundAction, allowed: frozenset[str]) -> None:
    session = _session(bound)
    writable = {item.identity for item in session.writes}
    for bound_write in bound.writes:
        if bound_write.resource.identity not in writable:
            raise InvokeDenied("the bound session does not contain a declared write.")
    for identity in allowed:
        if identity not in writable:
            raise InvokeDenied("a declared write has no enlistment in the bound session.")


def _session(bound: BoundAction) -> SessionPlan:
    if bound.session is None:
        raise InvokeDenied("no session plan is bound to this action.")
    return bound.session


def _guarded(
    registrations: tuple[_Registration, ...],
    bound: BoundAction,
    provider: ScopedEngineProvider,
    principal: Principal,
    grants: Mapping[DefinitionKey, ReadGrant],
) -> tuple[GuardedWrite, ...]:
    session = _session(bound)
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
    return ActionResult(
        attempt=AttemptOutcome("REJECTED", detail),
        execution=ExecutionRecord(
            execution_id=uuid.uuid4().hex,
            status="REJECTED",
            action=action,
            requester=principal,
            children=children,
        ),
    )


def _outcome(
    code: InvokeCode,
    detail: str | None,
    *,
    reason: str | None = None,
    request_key: str | None = None,
    intent_fingerprint: str | None = None,
) -> ActionResult:
    return ActionResult(
        attempt=AttemptOutcome(code, detail, request_key, intent_fingerprint, reason)
    )


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
