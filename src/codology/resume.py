"""Resume gate: recompute pinned logic on a fresh UoW and finish atomically.

A stored approve decision is only an input. Before anything is written, resume
resolves the manifest pinned with the waiting execution, runs the root and its
children again on the current world, rechecks both authorities and compares the
material intent. A valid decision commits business writes, the ledger transition
and the decision outcome in one guarded transaction. Expiry, revocation and a
changed intent mint a new approval instead of authorizing the old one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol, cast

from codology.binding import BoundAction
from codology.decision import (
    ApprovalAuthorityProvider,
    AuthorityUnavailable,
    AuthorityVerdict,
    DecisionRecord,
    ExecutionSnapshot,
    authority_verdict,
    live_authority,
)
from codology.declarations import Action
from codology.engine import (
    BusinessRejected,
    InvokeDenied,
    RecomputedPlan,
    ResolvedObject,
    ScopedEngineProvider,
    guard_recomputed,
    recompute_action,
)
from codology.ledger import (
    EXECUTION_READ_PERMISSION,
    LedgerEntry,
    LedgerStatus,
    encode_result,
)
from codology.linking import LinkedDeclarations
from codology.manifest import (
    ManifestError,
    ResolvedManifest,
    decode_manifest,
    manifest_digest,
    resolve_manifest,
)
from codology.ports import (
    ApplyResult,
    CommitOutcomeUnknown,
    GuardedWrite,
    StalePlan,
    TransactionUnavailable,
)
from codology.query import Principal, ReadGrant
from codology.results import (
    UNKNOWN_DETAIL,
    ActionResult,
    AttemptOutcome,
    CommittedChange,
    ExecutionRecord,
    outcome,
    replay,
    stored_result,
)
from codology.snapshot import DefinitionKey
from codology.waiting import (
    AwaitingExecution,
    ComparisonValue,
    MaterialIntent,
    ObjectVersion,
    approval_deadline,
    build_material_intent,
    decode_awaiting,
    encode_awaiting,
    evaluate_predicate,
    new_approval,
)

ResumeOutcomeCode = Literal["COMMITTED", "REAPPROVAL", "REJECTED"]

_UNAVAILABLE_DETAIL = "the resume could not complete; reconcile before retrying."
_DENIED_DETAIL = "the resume attempt was refused by the engine gate."
_MISUSE_DETAIL = "the callback key and intent do not authorize this resume."
_STALE_DETAIL = "the resolved world changed; re-read and recompute before retrying."


class _Raced(Exception):
    """Another writer changed the execution while this resume held the unit."""


@dataclass(frozen=True, slots=True)
class ResumeOutcome:
    """The outcome recorded beside the ledger transition it completed."""

    callback_key: str
    execution_id: str
    outcome: ResumeOutcomeCode
    detail: str | None
    recorded_at: str

    def document(self) -> dict[str, object]:
        return {
            "callback_key": self.callback_key,
            "execution_id": self.execution_id,
            "outcome": self.outcome,
            "detail": self.detail,
            "recorded_at": self.recorded_at,
        }


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value


def stored_outcome(document: object) -> ResumeOutcome | None:
    """Decode one persisted resume outcome, failing closed on malformed content."""
    if not isinstance(document, dict):
        return None
    items = cast(Mapping[str, object], document)
    if set(items) != {
        "callback_key",
        "execution_id",
        "outcome",
        "detail",
        "recorded_at",
    }:
        return None
    try:
        code = _text(items["outcome"], "outcome")
        if code not in ("COMMITTED", "REAPPROVAL", "REJECTED"):
            return None
        detail = items["detail"]
        if detail is not None and not isinstance(detail, str):
            return None
        return ResumeOutcome(
            _text(items["callback_key"], "callback_key"),
            _text(items["execution_id"], "execution_id"),
            code,  # type: ignore[arg-type]
            detail,
            _text(items["recorded_at"], "recorded_at"),
        )
    except (KeyError, TypeError, ValueError):
        return None


class ResumeUnitOfWork(Protocol):
    """The one transaction that owns resume guards, ledger and decision outcome."""

    def find_execution(self, execution_id: str) -> ExecutionSnapshot | None: ...

    def find_decision(self, callback_key: str) -> DecisionRecord | None: ...

    def find_outcome(self, callback_key: str) -> ResumeOutcome | None: ...

    def apply(self, write: GuardedWrite) -> ApplyResult: ...

    def transition_committed(
        self, execution_id: str, fingerprint: str, action_version: str, payload: str
    ) -> bool: ...

    def transition_reapproval(self, execution_id: str, fingerprint: str, payload: str) -> bool: ...

    def transition_rejected(self, execution_id: str) -> bool: ...

    def record_outcome(self, record: ResumeOutcome) -> bool: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


class ResumeProvider(ScopedEngineProvider, Protocol):
    """Adapter ports: durable lookups plus the single resume transaction."""

    def find_execution(self, execution_id: str) -> ExecutionSnapshot | None: ...

    def read_decision(self, callback_key: str) -> DecisionRecord | None: ...

    def resume_unit(self) -> ResumeUnitOfWork: ...


@dataclass(frozen=True, slots=True)
class _Context:
    """Verified inputs for one resume attempt; never caller-supplied business state."""

    provider: ResumeProvider
    bound: BoundAction
    principal: Principal
    grants: Mapping[DefinitionKey, ReadGrant]
    authority_provider: ApprovalAuthorityProvider
    approval_expires_at: str | None
    execution_id: str
    callback_key: str
    snapshot: ExecutionSnapshot
    waiting: AwaitingExecution
    decision: DecisionRecord
    resolved: ResolvedManifest
    plan: RecomputedPlan
    comparisons: tuple[ComparisonValue, ...]
    versions: tuple[ObjectVersion, ...]
    intent: MaterialIntent
    verdict: AuthorityVerdict
    moment: datetime

    @property
    def action(self) -> DefinitionKey:
        return self.resolved.manifest.root.key


@dataclass(slots=True)
class _UnitState:
    committed: bool = False


def _denied(detail: str, *, reason: str | None = None) -> ActionResult:
    return outcome("DENIED", detail, reason=reason)


def _unavailable() -> ActionResult:
    return outcome("UNKNOWN", _UNAVAILABLE_DETAIL)


def _stale() -> ActionResult:
    return outcome("StalePlan", _STALE_DETAIL)


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _ledger_entry(snapshot: ExecutionSnapshot) -> LedgerEntry:
    return LedgerEntry(
        snapshot.scope,
        snapshot.request_key,
        snapshot.intent_fingerprint,
        snapshot.execution_id,
        snapshot.action_version,
        cast(LedgerStatus, snapshot.status),
        snapshot.payload,
    )


def _finished(
    snapshot: ExecutionSnapshot, principal: Principal, decision: DecisionRecord
) -> ActionResult:
    """Replay a terminal or waiting record only to the requester it belongs to."""
    requester = decision.approval.requester
    if principal.identity != requester.identity or principal.tenant != requester.tenant:
        return _denied("the resume caller is not the requester of this execution.")
    replayed = replay(_ledger_entry(snapshot))
    return replayed if replayed is not None else _denied("the stored execution cannot be verified.")


def _waiting_result(
    waiting: AwaitingExecution,
    status: Literal["AWAITING_APPROVAL", "REJECTED"],
    *,
    request_key: str,
    fingerprint: str,
    deduplicated: bool,
    detail: str | None = None,
    reason: str | None = None,
) -> ActionResult:
    intent = waiting.material_intent
    record = ExecutionRecord(
        waiting.execution_id,
        status,
        waiting.action,
        waiting.requester,
        (),
        intent.child_keys,
        deduplicated,
        waiting.pinned_manifest,
        intent,
        waiting.required_approval,
        waiting.canonical_input,
    )
    return ActionResult(AttemptOutcome(status, detail, request_key, fingerprint, reason), record)


def _fresh_intent(ctx: _Context, cycle: int) -> MaterialIntent:
    return build_material_intent(
        canonical_input=ctx.waiting.canonical_input,
        comparisons=ctx.comparisons,
        object_versions=ctx.versions,
        pinned=ctx.resolved.manifest,
        cycle=cycle,
    )


def _verdict_at_commit(ctx: _Context) -> AuthorityVerdict | ActionResult:
    """Recheck live approver authority immediately before any guarded write."""
    try:
        authority = live_authority(
            ctx.authority_provider, ctx.decision.principal, ctx.decision.approval
        )
    except AuthorityUnavailable:
        return _unavailable()
    return authority_verdict(
        authority, ctx.decision.principal, ctx.decision.approval, now=ctx.moment
    )


def _recorded(
    principal: Principal,
    record: ResumeOutcome,
    snapshot: ExecutionSnapshot | None,
    decision: DecisionRecord | None,
) -> ActionResult:
    """Replay an outcome already recorded with a committed transition."""
    if snapshot is None or decision is None:
        raise _Raced()
    expected = {
        "COMMITTED": "COMMITTED",
        "REAPPROVAL": "AWAITING_APPROVAL",
        "REJECTED": "REJECTED",
    }
    if snapshot.status != expected[record.outcome]:
        return _unavailable()
    if record.outcome != "REAPPROVAL":
        return _finished(snapshot, principal, decision)
    waiting = decode_awaiting(snapshot.payload)
    if waiting is None:
        return _unavailable()
    return _waiting_result(
        waiting,
        "AWAITING_APPROVAL",
        request_key=snapshot.request_key,
        fingerprint=snapshot.intent_fingerprint,
        deduplicated=True,
        detail=record.detail,
        reason="REAPPROVAL_REQUIRED",
    )


def _commit_body(ctx: _Context, unit: ResumeUnitOfWork, state: _UnitState) -> ActionResult:
    snapshot = unit.find_execution(ctx.execution_id)
    decision = unit.find_decision(ctx.callback_key)
    stored = unit.find_outcome(ctx.callback_key)
    if stored is not None:
        return _recorded(ctx.principal, stored, snapshot, decision)
    if (
        snapshot is None
        or decision is None
        or snapshot.status != "AWAITING_APPROVAL"
        or decision.decision != "APPROVE"
    ):
        raise _Raced()
    verdict = _verdict_at_commit(ctx)
    if isinstance(verdict, ActionResult):
        return verdict
    if verdict.detail is not None:
        return _denied(verdict.detail)
    if verdict.expired or verdict.revoked:
        return _reapprove_body(
            ctx,
            unit,
            state,
            "the approval has expired." if verdict.expired else "the approval was revoked.",
        )

    writes = guard_recomputed(
        ctx.plan.registrations, ctx.bound, ctx.provider, ctx.principal, ctx.grants
    )
    changes = tuple(
        CommittedChange(
            item.target.definition.identity,
            item.target.key,
            item.target.version,
            item.changes,
        )
        for item in ctx.plan.registrations
    )
    record = ExecutionRecord(
        ctx.execution_id,
        "COMMITTED",
        ctx.action,
        ctx.waiting.requester,
        changes,
        ctx.plan.children,
        False,
        ctx.waiting.pinned_manifest,
        ctx.intent,
        ctx.decision.approval,
        ctx.waiting.canonical_input,
    )
    payload = encode_result(stored_result(record))
    applied: list[ApplyResult] = []
    for write in writes:
        applied.append(unit.apply(write))
    if not unit.transition_committed(
        ctx.execution_id, ctx.snapshot.intent_fingerprint, ctx.action.version, payload
    ):
        raise _Raced()
    if not unit.record_outcome(
        ResumeOutcome(ctx.callback_key, ctx.execution_id, "COMMITTED", None, _timestamp(ctx.moment))
    ):
        raise _Raced()
    unit.commit()
    state.committed = True
    return ActionResult(
        AttemptOutcome(
            "COMMITTED", None, ctx.snapshot.request_key, ctx.snapshot.intent_fingerprint
        ),
        record,
        tuple(applied),
    )


@dataclass(frozen=True, slots=True)
class _RejectInput:
    """The verified inputs a business rejection needs to become terminal."""

    provider: ResumeProvider
    principal: Principal
    execution_id: str
    callback_key: str
    snapshot: ExecutionSnapshot
    waiting: AwaitingExecution
    moment: datetime
    reason: str


def _reject_body(
    rejection: _RejectInput, unit: ResumeUnitOfWork, state: _UnitState
) -> ActionResult:
    snapshot = unit.find_execution(rejection.execution_id)
    decision = unit.find_decision(rejection.callback_key)
    stored = unit.find_outcome(rejection.callback_key)
    if stored is not None:
        return _recorded(rejection.principal, stored, snapshot, decision)
    if snapshot is None or snapshot.status != "AWAITING_APPROVAL":
        raise _Raced()
    if not unit.transition_rejected(rejection.execution_id):
        raise _Raced()
    if not unit.record_outcome(
        ResumeOutcome(
            rejection.callback_key,
            rejection.execution_id,
            "REJECTED",
            rejection.reason,
            _timestamp(rejection.moment),
        )
    ):
        raise _Raced()
    unit.commit()
    state.committed = True
    return _waiting_result(
        rejection.waiting,
        "REJECTED",
        request_key=snapshot.request_key,
        fingerprint=snapshot.intent_fingerprint,
        deduplicated=False,
        detail=rejection.reason,
    )


def _reapprove_body(
    ctx: _Context, unit: ResumeUnitOfWork, state: _UnitState, detail: str
) -> ActionResult:
    snapshot = unit.find_execution(ctx.execution_id)
    decision = unit.find_decision(ctx.callback_key)
    stored = unit.find_outcome(ctx.callback_key)
    if stored is not None:
        return _recorded(ctx.principal, stored, snapshot, decision)
    if snapshot is None or snapshot.status != "AWAITING_APPROVAL":
        raise _Raced()
    intent = _fresh_intent(ctx, ctx.waiting.material_intent.cycle + 1)
    approval = new_approval(
        role=ctx.waiting.required_approval.role,
        tenant=ctx.waiting.required_approval.tenant,
        scope=ctx.waiting.required_approval.scope,
        requester=ctx.waiting.required_approval.requester,
        expires_at=approval_deadline(ctx.approval_expires_at, now=ctx.moment),
        self_approval=ctx.waiting.required_approval.self_approval,
        intent_fingerprint=intent.fingerprint,
        execution_id=ctx.execution_id,
        permission=ctx.waiting.required_approval.permission,
    )
    updated = replace(ctx.waiting, material_intent=intent, required_approval=approval)
    if not unit.transition_reapproval(
        ctx.execution_id, ctx.snapshot.intent_fingerprint, encode_awaiting(updated)
    ):
        raise _Raced()
    if not unit.record_outcome(
        ResumeOutcome(
            ctx.callback_key, ctx.execution_id, "REAPPROVAL", detail, _timestamp(ctx.moment)
        )
    ):
        raise _Raced()
    unit.commit()
    state.committed = True
    return _waiting_result(
        updated,
        "AWAITING_APPROVAL",
        request_key=snapshot.request_key,
        fingerprint=snapshot.intent_fingerprint,
        deduplicated=False,
        detail=detail,
        reason="REAPPROVAL_REQUIRED",
    )


def _transact(
    provider: ResumeProvider,
    principal: Principal,
    execution_id: str,
    callback_key: str,
    body: Callable[[ResumeUnitOfWork, _UnitState], ActionResult],
) -> ActionResult:
    """Own the unit lifecycle so no denied or raced attempt leaves a claim behind."""
    try:
        unit = provider.resume_unit()
    except (TransactionUnavailable, CommitOutcomeUnknown):
        return _unavailable()
    state = _UnitState()
    try:
        return body(unit, state)
    except StalePlan:
        return _stale()
    except _Raced:
        snapshot = provider.find_execution(execution_id)
        decision = provider.read_decision(callback_key)
        if snapshot is None or decision is None:
            return _unavailable()
        return _finished(snapshot, principal, decision)
    except (TransactionUnavailable, CommitOutcomeUnknown, AuthorityUnavailable):
        return _unavailable()
    finally:
        if not state.committed:
            unit.rollback()
        unit.close()


def _preflight(
    *,
    provider: ResumeProvider,
    revisions: LinkedDeclarations | Sequence[LinkedDeclarations],
    bound: BoundAction,
    principal: Principal,
    grants: Mapping[DefinitionKey, ReadGrant],
    execution_id: str,
    callback_key: str,
    authority_provider: ApprovalAuthorityProvider,
    now: datetime | None,
    approval_expires_at: str | None,
) -> _Context | ActionResult:
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    snapshot = provider.find_execution(execution_id)
    if snapshot is None:
        return _denied("no execution matches this callback.")
    decision = provider.read_decision(callback_key)
    if decision is None:
        return _denied("no approval decision matches this resume.")
    if decision.execution_id != execution_id or decision.decision != "APPROVE":
        return _denied("this callback did not approve this execution.")
    if snapshot.status in ("COMMITTED", "REJECTED"):
        return _finished(snapshot, principal, decision)
    if snapshot.status != "AWAITING_APPROVAL":
        return _denied("the execution is not awaiting a decision.")

    waiting = decode_awaiting(snapshot.payload)
    if waiting is None or waiting.execution_id != execution_id:
        return _denied("the waiting execution cannot be verified.")
    approval = waiting.required_approval
    if (
        approval.callback_key != callback_key
        or approval.approval_id != decision.approval_id
        or decision.intent_fingerprint != approval.intent_fingerprint
    ):
        return _denied(_MISUSE_DETAIL, reason="KEY_MISUSE")
    if (
        principal.identity != waiting.requester.identity
        or principal.tenant != waiting.requester.tenant
    ):
        return _denied("the resume caller is not the requester of this execution.")
    scopes = {
        name
        for grant in grants.values()
        if grant.tenant == principal.tenant
        for name in grant.scopes
    }
    if not approval.scope or not set(approval.scope) <= scopes:
        return _denied("the resume has no live read grant in the approval scope.")

    try:
        manifest = decode_manifest(waiting.pinned_manifest)
        if manifest_digest(manifest) != waiting.material_intent.manifest_digest:
            return _denied("the pinned manifest digest does not match its bytes.")
        resolved = resolve_manifest(manifest, revisions)
    except (ManifestError, ValueError):
        return _denied("the pinned artifact set cannot be resolved safely.")

    if bound.action != resolved.manifest.root.key or waiting.action != bound.action:
        return _denied("the bound plan is not the pinned root revision.")
    declaration = resolved.root.definition.declaration
    if not issubclass(declaration, Action):
        return _denied("the pinned root is not an Action.")
    if declaration.approval is None or declaration.effects:
        return _denied("the pinned root needs governance this resume cannot honor.")
    if declaration.permission not in principal.permissions:
        return _denied("the requester lacks the action's live invoke permission.")

    try:
        authority = live_authority(authority_provider, decision.principal, decision.approval)
    except AuthorityUnavailable:
        return _unavailable()
    verdict = authority_verdict(authority, decision.principal, decision.approval, now=moment)
    if verdict.detail is not None:
        return _denied(verdict.detail)

    try:
        plan = recompute_action(
            linked=resolved.source,
            action=bound.action,
            bound=bound,
            provider=provider,
            principal=principal,
            grants=grants,
            parameters=waiting.canonical_input,
            allow_version_change=True,
        )
    except BusinessRejected as exc:
        rejection = _RejectInput(
            provider, principal, execution_id, callback_key, snapshot, waiting, moment, str(exc)
        )
        return _transact(
            provider,
            principal,
            execution_id,
            callback_key,
            lambda unit, state: _reject_body(rejection, unit, state),
        )
    except StalePlan:
        return _stale()
    except (InvokeDenied, ValueError, PermissionError) as exc:
        return _denied(str(exc) if isinstance(exc, InvokeDenied) else _DENIED_DETAIL)
    except (TransactionUnavailable, CommitOutcomeUnknown):
        return _unavailable()

    rule = plan.declaration.approval
    if rule is None:
        return _denied("the pinned root has no approval declaration.")
    comparisons = evaluate_predicate(rule.when, plan.arguments).comparisons
    versions = tuple(
        ObjectVersion(item.definition.identity, item.key, item.version)
        for item in plan.arguments.values()
        if isinstance(item, ResolvedObject)
    )
    intent = build_material_intent(
        canonical_input=waiting.canonical_input,
        comparisons=comparisons,
        object_versions=versions,
        pinned=resolved.manifest,
        cycle=waiting.material_intent.cycle,
    )
    return _Context(
        provider=provider,
        bound=bound,
        principal=principal,
        grants=grants,
        authority_provider=authority_provider,
        approval_expires_at=approval_expires_at,
        execution_id=execution_id,
        callback_key=callback_key,
        snapshot=snapshot,
        waiting=waiting,
        decision=decision,
        resolved=resolved,
        plan=plan,
        comparisons=comparisons,
        versions=versions,
        intent=intent,
        verdict=verdict,
        moment=moment,
    )


def resume(
    *,
    provider: ResumeProvider,
    revisions: LinkedDeclarations | Sequence[LinkedDeclarations],
    bound: BoundAction,
    principal: Principal,
    grants: Mapping[DefinitionKey, ReadGrant],
    execution_id: str,
    callback_key: str,
    authority_provider: ApprovalAuthorityProvider,
    now: datetime | None = None,
    approval_expires_at: str | None = None,
) -> ActionResult:
    """Finish one approved execution on current data, or return a safe retry outcome.

    ``COMMITTED`` means one transaction applied the recomputed guarded writes,
    the ledger transition and the decision outcome. ``AWAITING_APPROVAL`` means a
    new approval was minted because the old intent or its validity window no
    longer holds. ``DENIED``, ``StalePlan`` and ``UNKNOWN`` never claim a decision.
    """
    result = _preflight(
        provider=provider,
        revisions=revisions,
        bound=bound,
        principal=principal,
        grants=grants,
        execution_id=execution_id,
        callback_key=callback_key,
        authority_provider=authority_provider,
        now=now,
        approval_expires_at=approval_expires_at,
    )
    if isinstance(result, ActionResult):
        return result
    ctx = result

    if ctx.verdict.expired or ctx.verdict.revoked:
        detail = "the approval has expired." if ctx.verdict.expired else "the approval was revoked."

        def reapprove(unit: ResumeUnitOfWork, state: _UnitState) -> ActionResult:
            return _reapprove_body(ctx, unit, state, detail)

        return _transact(ctx.provider, ctx.principal, ctx.execution_id, ctx.callback_key, reapprove)
    if ctx.intent.fingerprint != ctx.waiting.material_intent.fingerprint:

        def changed(unit: ResumeUnitOfWork, state: _UnitState) -> ActionResult:
            return _reapprove_body(ctx, unit, state, "the material intent changed before commit.")

        return _transact(ctx.provider, ctx.principal, ctx.execution_id, ctx.callback_key, changed)

    def commit(unit: ResumeUnitOfWork, state: _UnitState) -> ActionResult:
        return _commit_body(ctx, unit, state)

    return _transact(ctx.provider, ctx.principal, ctx.execution_id, ctx.callback_key, commit)


def reconcile_execution(
    *, provider: ResumeProvider, principal: Principal, execution_id: str
) -> ActionResult:
    """Read an authoritative result by execution id under record authority."""
    if EXECUTION_READ_PERMISSION not in principal.permissions:
        return outcome("DENIED", "the caller has no execution read authority.")
    snapshot = provider.find_execution(execution_id)
    if snapshot is None:
        return outcome("UNKNOWN", UNKNOWN_DETAIL)
    replayed = replay(_ledger_entry(snapshot))
    return replayed if replayed is not None else outcome("UNKNOWN", UNKNOWN_DETAIL)


__all__ = [
    "AuthorityVerdict",
    "ResumeOutcome",
    "ResumeOutcomeCode",
    "ResumeProvider",
    "ResumeUnitOfWork",
    "reconcile_execution",
    "resume",
    "stored_outcome",
]
