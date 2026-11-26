"""The consumer path: query, typed refs, invoke, callback, resume and relay.

Every call here goes through a public engine port. The caller supplies a
principal, grants, adapters and host-issued authority; it never copies the
threshold or role policy, builds SQL, computes a fingerprint itself or decides
business state. Approval keys and fingerprints come from the execution record.
"""

from __future__ import annotations

from codology import (
    ApprovalAuthorityProvider,
    Comparison,
    DefinitionKey,
    LocalReceiver,
    OrderBy,
    Principal,
    QueryPage,
    QueryRow,
    RelayStore,
    SecureQueryProvider,
    VersionedRef,
    query,
)
from codology.decision import DecisionResult, approve, reject
from codology.engine import ActionResult, ScopedEngineProvider, invoke, reconcile
from codology.ledger import LedgerProvider
from codology.relay import Delivery, EffectState, deliver_committed, read_effect_status
from codology.resume import ResumeProvider, resume
from codology.resume import reconcile_execution as reconcile_execution_port
from codology.waiting import RequiredApproval
from examples.conditional_approval import declarations as d
from examples.conditional_approval.wiring import BUDGET_KEY, ROOT_KEY, ROOT_NEXT_KEY, Host

_APPROVE = "APPROVE"
_REJECT = "REJECT"


def find_orders(
    host: Host, *, principal: Principal | None = None, status: str = "PENDING", limit: int = 20
) -> QueryPage[d.PurchaseOrder]:
    """Read one policy-filtered page of orders through the query gate."""
    who = principal or host.requester
    return query(
        provider=host.provider,
        principal=who,
        grant=host.grants[DefinitionKey(d.ORDER, "1.0.0")],
        from_=DefinitionKey(d.ORDER, "1.0.0"),
        target=d.PurchaseOrder,
        order=OrderBy("id"),
        predicate=Comparison("status", "==", status),
        limit=limit,
        count_requested=True,
    )


def find_budget(host: Host, *, key: str = "B-1") -> QueryRow[d.Budget]:
    """Read one visible budget row through the same authorized query gate."""
    page = query(
        provider=host.provider,
        principal=host.requester,
        grant=host.grants[BUDGET_KEY],
        from_=BUDGET_KEY,
        target=d.Budget,
        order=OrderBy("id"),
        predicate=Comparison("id", "==", key),
        limit=1,
        count_requested=True,
    )
    if not page.rows:
        raise LookupError(f"budget {key!r} is not visible to the requester")
    return page.rows[0]


def typed_ref(
    host: Host,
    definition: DefinitionKey,
    target: type[object],
    key: str,
    *,
    provider: SecureQueryProvider | None = None,
) -> VersionedRef[object]:
    """Take a typed ref from a query row; the key is a predicate, not a bypass."""
    page = query(
        provider=provider or host.provider,
        principal=host.requester,
        grant=host.grants[definition],
        from_=definition,
        target=target,
        order=OrderBy("id"),
        predicate=Comparison("id", "==", key),
        limit=1,
        count_requested=True,
    )
    if not page.rows:
        raise LookupError(f"{definition.identity}:{key} is not visible to the requester")
    return page.rows[0].as_ref()


def request_approval(
    host: Host,
    *,
    order: VersionedRef[d.PurchaseOrder],
    budget: VersionedRef[d.Budget],
    request_key: str,
    reason: str,
    provider: ScopedEngineProvider | None = None,
    expires_at: str | None = None,
) -> ActionResult:
    """Invoke the root action; below-threshold orders commit without a callback."""
    return invoke(
        linked=host.graphs[0],
        action=ROOT_KEY,
        bound=host.bound,
        provider=provider or host.provider,
        principal=host.requester,
        grants=host.grants,
        parameters={"order": order, "budget": budget, "reason": reason},
        request_key=request_key,
        approval_expires_at=expires_at,
    )


def replay_on_new_default(
    host: Host,
    *,
    order: VersionedRef[d.PurchaseOrder],
    budget: VersionedRef[d.Budget],
    request_key: str,
    reason: str,
    provider: ScopedEngineProvider | None = None,
) -> ActionResult:
    """Re-invoke after a default revision change; the pinned record still wins."""
    return invoke(
        linked=host.graphs[1],
        action=ROOT_NEXT_KEY,
        bound=host.bound_next,
        provider=provider or host.provider,
        principal=host.requester,
        grants=host.grants,
        parameters={"order": order, "budget": budget, "reason": reason},
        request_key=request_key,
    )


def decide(
    host: Host,
    execution_id: str,
    approval: RequiredApproval,
    *,
    decision: str = _APPROVE,
    principal: Principal | None = None,
    authority: ApprovalAuthorityProvider | None = None,
    reason: str = "budget confirmed",
    callback_key: str | None = None,
    fingerprint: str | None = None,
) -> DecisionResult:
    """Approve or reject with the key and fingerprint issued by the engine."""
    port = approve if decision == _APPROVE else reject
    return port(
        provider=host.provider,
        authority_provider=authority or host.authority,
        principal=principal or host.approver,
        execution_id=execution_id,
        callback_key=callback_key or approval.callback_key,
        expected_intent_fingerprint=fingerprint or approval.intent_fingerprint,
        reason=reason,
    )


def resume_execution(
    host: Host,
    execution_id: str,
    callback_key: str,
    *,
    provider: ResumeProvider | None = None,
    authority: ApprovalAuthorityProvider | None = None,
) -> ActionResult:
    """Resume on current data using the manifest pinned at the waiting gate."""
    return resume(
        provider=provider or host.provider,  # type: ignore[arg-type]
        revisions=host.graphs,
        bound=host.bound,
        principal=host.requester,
        grants=host.grants,
        execution_id=execution_id,
        callback_key=callback_key,
        authority_provider=authority or host.authority,
    )


def reconcile_execution(
    host: Host, execution_id: str, *, provider: ResumeProvider | None = None
) -> ActionResult:
    """Read an authoritative execution by id under the record-read gate."""
    return reconcile_execution_port(
        provider=provider or host.provider, principal=host.reader, execution_id=execution_id
    )


def reconcile_request(
    host: Host,
    action: DefinitionKey,
    request_key: str,
    *,
    provider: LedgerProvider | None = None,
) -> ActionResult:
    """Reconcile a lost invoke acknowledgement by its scoped request key."""
    return reconcile(
        provider=provider or host.provider,
        principal=host.reader,
        action=action,
        request_key=request_key,
    )


def relay_once(
    host: Host,
    *,
    store: RelayStore | None = None,
    receiver: LocalReceiver | None = None,
) -> tuple[Delivery, ...]:
    """Deliver only committed outbox intents; no business handler is run."""
    return deliver_committed(store or host.store, receiver or host.receiver)


def effect_status(
    host: Host, execution_id: str, *, store: RelayStore | None = None
) -> tuple[EffectState, ...]:
    """Observe effect state through the separate effect-read gate."""
    return read_effect_status(store or host.store, host.reader, execution_id)


def effect_status_for(
    host: Host,
    execution_id: str,
    *,
    principal: Principal,
    store: RelayStore | None = None,
) -> tuple[EffectState, ...]:
    """Read effect state under an explicitly supplied principal."""
    return read_effect_status(store or host.store, principal, execution_id)


__all__ = [
    "find_budget",
    "effect_status_for",
    "decide",
    "effect_status",
    "find_orders",
    "reconcile_execution",
    "reconcile_request",
    "relay_once",
    "replay_on_new_default",
    "request_approval",
    "resume_execution",
    "typed_ref",
]
