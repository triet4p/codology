"""Public-API driver for the simulated break-glass runtime slice.

Every call goes through a public engine port. The caller supplies the principal,
read grants, adapters and host-issued authority, and takes refs from authorized
query rows. It never copies the duration threshold, the sensitivity literal, the
approval role, business state names or SQL, and it never builds a fingerprint or
callback key itself.
"""

from __future__ import annotations

from codology import (
    ApprovalAuthorityProvider,
    Comparison,
    DefinitionKey,
    Delivery,
    OrderBy,
    Principal,
    RequiredApproval,
    VersionedRef,
    approve,
    deliver_committed,
    query,
)
from codology.decision import DecisionResult
from codology.engine import ActionResult, invoke
from codology.resume import resume
from examples.break_glass_access.access_control import GrantRequest
from examples.break_glass_access.security_audit import AuditSession
from examples.break_glass_access.wiring import AUDIT_KEY, GRANT_KEY, REASON, ROOT_KEY, Host


def _ref[T](host: Host, definition: DefinitionKey, target: type[T], key: str) -> VersionedRef[T]:
    """Take one typed ref from a row the requester is authorized to read."""
    page = query(
        provider=host.provider,
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


def grant_ref(host: Host, key: str = "AGR-1") -> VersionedRef[GrantRequest]:
    """The request row's typed ref, issued by the query gate."""
    return _ref(host, GRANT_KEY, GrantRequest, key)


def session_ref(host: Host, key: str = "AS-1") -> VersionedRef[AuditSession]:
    """The audit-session row's typed ref, issued by the same gate."""
    return _ref(host, AUDIT_KEY, AuditSession, key)


def request_access(
    host: Host,
    *,
    request_key: str,
    reason: str = REASON,
    request: VersionedRef[GrantRequest] | None = None,
    session: VersionedRef[AuditSession] | None = None,
) -> ActionResult:
    """Invoke the root action; a replay reuses the originally issued refs."""
    return invoke(
        linked=host.graph,
        action=ROOT_KEY,
        bound=host.bound,
        provider=host.provider,
        principal=host.requester,
        grants=host.grants,
        parameters={
            "request": request if request is not None else grant_ref(host),
            "session": session if session is not None else session_ref(host),
            "reason": reason,
        },
        request_key=request_key,
    )


def approve_access(
    host: Host,
    execution_id: str,
    approval: RequiredApproval,
    *,
    principal: Principal | None = None,
    authority: ApprovalAuthorityProvider | None = None,
    reason: str = "security officer approved",
) -> DecisionResult:
    """Approve with the key and fingerprint the engine issued for this wait."""
    return approve(
        provider=host.provider,
        authority_provider=authority or host.authority,
        principal=principal or host.approver,
        execution_id=execution_id,
        callback_key=approval.callback_key,
        expected_intent_fingerprint=approval.intent_fingerprint,
        reason=reason,
    )


def resume_access(host: Host, execution_id: str, callback_key: str) -> ActionResult:
    """Resume the approved execution on current data and pinned revisions."""
    return resume(
        provider=host.provider,
        revisions=(host.graph,),
        bound=host.bound,
        principal=host.requester,
        grants=host.grants,
        execution_id=execution_id,
        callback_key=callback_key,
        authority_provider=host.authority,
    )


def relay_once(host: Host) -> tuple[Delivery, ...]:
    """Deliver only committed outbox intents; no business handler runs."""
    return deliver_committed(host.store, host.receiver)


__all__ = [
    "approve_access",
    "grant_ref",
    "relay_once",
    "request_access",
    "resume_access",
    "session_ref",
]
