"""Decision gate for approval callbacks.

A callback decision is bound to one pinned approval and its material intent. An
authorized approve records an input for resume; it never commits business state.
An authorized reject ends the waiting execution without any business write.
Denied attempts are audited on their own and never claim a callback key.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, cast

from codology.ledger import DuplicateRequest, RequestScope, deserialize, serialize
from codology.ports import CommitOutcomeUnknown, TransactionUnavailable
from codology.query import Principal
from codology.results import (
    ActionResult,
    AttemptOutcome,
    ExecutionRecord,
    ExecutionStatus,
    key_misuse,
    outcome,
)
from codology.waiting import (
    AwaitingExecution,
    RequiredApproval,
    decode_approval,
    decode_awaiting,
)

DecisionKind = Literal["APPROVE", "REJECT"]
DecisionCode = Literal["AWAITING_APPROVAL", "REJECTED", "DENIED", "UNKNOWN"]

_DENIED_DETAIL = "the approval decision was refused by the engine gate."
_UNAVAILABLE_DETAIL = "the decision store could not complete; reconcile before retrying."


class AuthorityUnavailable(Exception):
    """The live authority provider could not answer a callback gate check."""


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value


def encode_principal(principal: Principal) -> str:
    """Encode the approver identity recorded with a decision."""
    return serialize(
        {
            "identity": principal.identity,
            "tenant": principal.tenant,
            "permissions": sorted(principal.permissions),
        }
    )


def decode_principal(payload: str) -> Principal | None:
    """Decode a recorded approver, failing closed on an untrusted payload."""
    document = deserialize(payload)
    if document is None or set(document) != {"identity", "tenant", "permissions"}:
        return None
    try:
        raw_value = document["permissions"]
        if not isinstance(raw_value, Sequence) or isinstance(raw_value, (str, bytes)):
            return None
        raw = cast(Sequence[object], raw_value)
        permissions = tuple(raw)
        if not all(isinstance(item, str) and item.strip() for item in permissions):
            return None
        return Principal(
            _text(document["identity"], "identity"),
            _text(document["tenant"], "tenant"),
            frozenset(cast(tuple[str, ...], permissions)),
        )
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One accepted decision, stored under its own callback key."""

    callback_key: str
    execution_id: str
    approval_id: str
    decision: DecisionKind
    intent_fingerprint: str
    reason: str
    principal: Principal
    approval: RequiredApproval
    authority_revision: str | None
    recorded_at: str


@dataclass(frozen=True, slots=True)
class DecisionAttempt:
    """One callback attempt, audited apart from the execution's transitions."""

    attempt_id: str
    callback_key: str
    execution_id: str
    principal: Principal
    code: DecisionCode
    detail: str | None
    decision: DecisionKind | None
    intent_fingerprint: str | None
    recorded_at: str


@dataclass(frozen=True, slots=True)
class DecisionResult(ActionResult):
    """An attempt outcome plus the decision that an authorized callback stored."""

    decision: DecisionRecord | None = None


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    """The authoritative waiting record a callback resolves through its key."""

    scope: RequestScope
    request_key: str
    intent_fingerprint: str
    execution_id: str
    action_version: str
    status: str
    payload: str


@dataclass(frozen=True, slots=True)
class ApprovalAuthority:
    """Live host authority for one approver, supplied at the callback boundary."""

    roles: frozenset[str]
    permissions: frozenset[str]
    tenant: str
    scopes: tuple[str, ...]
    revoked: bool = False
    revision: str | None = None


class ApprovalAuthorityProvider(Protocol):
    """Returns current role, permission, scope and revocation for a callback."""

    def authorize(self, principal: Principal, approval: RequiredApproval) -> ApprovalAuthority: ...


class DecisionUnitOfWork(Protocol):
    """One transaction that claims a decision and audits its attempt together."""

    def find_decision(self, callback_key: str) -> DecisionRecord | None: ...

    def find_execution(self, execution_id: str) -> ExecutionSnapshot | None: ...

    def record_decision(self, record: DecisionRecord) -> bool: ...

    def record_attempt(self, attempt: DecisionAttempt) -> None: ...

    def transition_rejected(self, execution_id: str) -> bool: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


class DecisionProvider(Protocol):
    """Opens the transaction that owns callback idempotency and audit rows."""

    def decision_unit(self) -> DecisionUnitOfWork: ...


def _live_authority(
    provider: ApprovalAuthorityProvider,
    principal: Principal,
    approval: RequiredApproval,
) -> ApprovalAuthority:
    try:
        return provider.authorize(principal, approval)
    except (TransactionUnavailable, CommitOutcomeUnknown) as exc:
        raise AuthorityUnavailable from exc


def _approval_id(execution_id: str, callback_key: str) -> str | None:
    prefix = execution_id + ":"
    if not callback_key.startswith(prefix):
        return None
    approval_id = callback_key[len(prefix) :]
    return approval_id if approval_id and ":" not in approval_id else None


def _authorize(
    authority: ApprovalAuthority,
    principal: Principal,
    approval: RequiredApproval,
    *,
    now: datetime,
    check_expiry: bool,
) -> str | None:
    """Return the first closed-gate reason, or None when the approver qualifies."""
    if principal.tenant != approval.tenant or authority.tenant != approval.tenant:
        return "the approver is outside the approval tenant."
    if authority.revoked:
        return "the approval was revoked."
    if not approval.permission or approval.permission not in authority.permissions:
        return "the approver lacks the live approval permission."
    if approval.role not in authority.roles:
        return "the approver lacks the live approval role."
    if not approval.scope or not set(approval.scope) <= set(authority.scopes):
        return "the approver is outside the approval scope."
    if not approval.self_approval and principal.identity == approval.requester.identity:
        return "self approval is not allowed by the declaration."
    if check_expiry:
        try:
            deadline = datetime.fromisoformat(approval.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return "the approval deadline cannot be verified."
        if deadline.tzinfo is None:
            return "the approval deadline is not time-zone aware."
        if now > deadline:
            return "the approval has expired."
    return None


def _execution_record(
    waiting: AwaitingExecution, *, status: ExecutionStatus, deduplicated: bool
) -> ExecutionRecord:
    intent = waiting.material_intent
    return ExecutionRecord(
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


def _denied(
    fingerprint: str | None, detail: str, *, reason: str | None = None
) -> tuple[AttemptOutcome, None, None]:
    return AttemptOutcome("DENIED", detail, None, fingerprint, reason), None, None


def _misuse(fingerprint: str | None) -> tuple[AttemptOutcome, None, None]:
    return key_misuse(None, fingerprint).attempt, None, None


def _accepted(
    record: DecisionRecord,
    waiting: AwaitingExecution,
    *,
    deduplicated: bool,
) -> tuple[AttemptOutcome, ExecutionRecord, DecisionRecord]:
    if record.decision == "REJECT":
        attempt = AttemptOutcome(
            "REJECTED", record.reason or "rejected by the approver", None, record.intent_fingerprint
        )
        status: ExecutionStatus = "REJECTED"
    else:
        attempt = AttemptOutcome(
            "AWAITING_APPROVAL", None, None, record.intent_fingerprint, "APPROVED"
        )
        status = "AWAITING_APPROVAL"
    return attempt, _execution_record(waiting, status=status, deduplicated=deduplicated), record


def _replay(
    stored: DecisionRecord,
    *,
    execution_id: str,
    approval_id: str,
    callback_key: str,
    expected_fingerprint: str,
    decision: DecisionKind,
    reason: str,
    authority_provider: ApprovalAuthorityProvider,
    principal: Principal,
    unit: DecisionUnitOfWork,
    now: datetime,
) -> tuple[AttemptOutcome, ExecutionRecord | None, DecisionRecord | None]:
    if (
        stored.callback_key != callback_key
        or stored.execution_id != execution_id
        or stored.approval_id != approval_id
        or stored.decision != decision
        or stored.intent_fingerprint != expected_fingerprint
        or stored.reason != reason
    ):
        return _misuse(expected_fingerprint)
    authority = _live_authority(authority_provider, principal, stored.approval)
    detail = _authorize(authority, principal, stored.approval, now=now, check_expiry=False)
    if detail is not None:
        return _denied(expected_fingerprint, detail)
    snapshot = unit.find_execution(execution_id)
    waiting = None if snapshot is None else decode_awaiting(snapshot.payload)
    if waiting is None:
        if stored.decision == "REJECT":
            return (
                AttemptOutcome(
                    "REJECTED",
                    stored.reason or "rejected by the approver",
                    None,
                    stored.intent_fingerprint,
                ),
                None,
                stored,
            )
        return (
            AttemptOutcome("AWAITING_APPROVAL", None, None, stored.intent_fingerprint, "APPROVED"),
            None,
            stored,
        )
    return _accepted(stored, waiting, deduplicated=True)


def _evaluate(
    *,
    provider_unit: DecisionUnitOfWork,
    authority_provider: ApprovalAuthorityProvider,
    principal: Principal,
    execution_id: str,
    callback_key: str,
    expected_fingerprint: str,
    decision: DecisionKind,
    reason: str,
    now: datetime,
) -> tuple[AttemptOutcome, ExecutionRecord | None, DecisionRecord | None]:
    if decision not in ("APPROVE", "REJECT"):
        return _denied(expected_fingerprint, "the decision is not a supported approval decision.")
    try:
        _text(execution_id, "execution_id")
        _text(callback_key, "callback_key")
        _text(expected_fingerprint, "expected_intent_fingerprint")
        _text(reason, "reason") if decision == "REJECT" else reason
    except ValueError:
        return _denied(expected_fingerprint, "the callback payload is malformed.")
    approval_id = _approval_id(execution_id, callback_key)
    if approval_id is None:
        return _denied(expected_fingerprint, "the callback key does not name this approval.")

    stored = provider_unit.find_decision(callback_key)
    if stored is not None:
        return _replay(
            stored,
            execution_id=execution_id,
            approval_id=approval_id,
            callback_key=callback_key,
            expected_fingerprint=expected_fingerprint,
            decision=decision,
            reason=reason,
            authority_provider=authority_provider,
            principal=principal,
            unit=provider_unit,
            now=now,
        )

    snapshot = provider_unit.find_execution(execution_id)
    if snapshot is None or snapshot.status != "AWAITING_APPROVAL":
        return _denied(expected_fingerprint, "no awaiting execution matches this callback.")
    waiting = decode_awaiting(snapshot.payload)
    if waiting is None or waiting.execution_id != execution_id:
        return _denied(expected_fingerprint, "the waiting execution cannot be verified.")
    approval = waiting.required_approval
    if approval.callback_key != callback_key:
        return _denied(expected_fingerprint, "the callback key is not the current approval.")
    authority = _live_authority(authority_provider, principal, approval)
    detail = _authorize(authority, principal, approval, now=now, check_expiry=True)
    if detail is not None:
        return _denied(expected_fingerprint, detail)
    if expected_fingerprint != approval.intent_fingerprint:
        return _misuse(expected_fingerprint)

    record = DecisionRecord(
        callback_key,
        execution_id,
        approval_id,
        decision,
        expected_fingerprint,
        reason,
        principal,
        approval,
        authority.revision,
        now.isoformat().replace("+00:00", "Z"),
    )
    if decision == "REJECT" and not provider_unit.transition_rejected(execution_id):
        return _denied(expected_fingerprint, "the execution is no longer awaiting a decision.")
    if not provider_unit.record_decision(record):
        raced = provider_unit.find_decision(callback_key)
        if raced is None:
            return _denied(expected_fingerprint, "the callback key was claimed concurrently.")
        return _replay(
            raced,
            execution_id=execution_id,
            approval_id=approval_id,
            callback_key=callback_key,
            expected_fingerprint=expected_fingerprint,
            decision=decision,
            reason=reason,
            authority_provider=authority_provider,
            principal=principal,
            unit=provider_unit,
            now=now,
        )
    return _accepted(record, waiting, deduplicated=False)


def _attempt(
    result: tuple[AttemptOutcome, ExecutionRecord | None, DecisionRecord | None],
    *,
    callback_key: str,
    execution_id: str,
    principal: Principal,
    decision: DecisionKind | None,
    now: datetime,
) -> DecisionAttempt:
    attempt = result[0]
    return DecisionAttempt(
        uuid.uuid4().hex,
        callback_key,
        execution_id,
        principal,
        attempt.code,  # type: ignore[arg-type]
        attempt.detail,
        decision,
        attempt.intent_fingerprint,
        now.isoformat().replace("+00:00", "Z"),
    )


def _decide(
    *,
    provider: DecisionProvider,
    authority_provider: ApprovalAuthorityProvider,
    principal: Principal,
    execution_id: str,
    callback_key: str,
    expected_intent_fingerprint: str,
    decision: DecisionKind,
    reason: str = "",
    now: datetime | None = None,
) -> DecisionResult:
    moment = (now or datetime.now(UTC)).astimezone(UTC)

    try:
        unit = provider.decision_unit()
    except (TransactionUnavailable, CommitOutcomeUnknown):
        return DecisionResult(outcome("UNKNOWN", _UNAVAILABLE_DETAIL).attempt)
    try:
        result = _evaluate(
            provider_unit=unit,
            authority_provider=authority_provider,
            principal=principal,
            execution_id=execution_id,
            callback_key=callback_key,
            expected_fingerprint=expected_intent_fingerprint,
            decision=decision,
            reason=reason,
            now=moment,
        )
        unit.record_attempt(
            _attempt(
                result,
                callback_key=callback_key,
                execution_id=execution_id,
                principal=principal,
                decision=decision if decision in ("APPROVE", "REJECT") else None,
                now=moment,
            )
        )
        unit.commit()
        return DecisionResult(attempt=result[0], execution=result[1], decision=result[2])
    except (TransactionUnavailable, CommitOutcomeUnknown, DuplicateRequest, AuthorityUnavailable):
        unit.rollback()
        return DecisionResult(outcome("UNKNOWN", _UNAVAILABLE_DETAIL).attempt)
    finally:
        unit.close()


def approve(
    *,
    provider: DecisionProvider,
    authority_provider: ApprovalAuthorityProvider,
    principal: Principal,
    execution_id: str,
    callback_key: str,
    expected_intent_fingerprint: str,
    reason: str = "",
    now: datetime | None = None,
) -> DecisionResult:
    """Record an authorized approval decision as input for a later resume."""
    return _decide(
        provider=provider,
        authority_provider=authority_provider,
        principal=principal,
        execution_id=execution_id,
        callback_key=callback_key,
        expected_intent_fingerprint=expected_intent_fingerprint,
        decision="APPROVE",
        reason=reason,
        now=now,
    )


def reject(
    *,
    provider: DecisionProvider,
    authority_provider: ApprovalAuthorityProvider,
    principal: Principal,
    execution_id: str,
    callback_key: str,
    expected_intent_fingerprint: str,
    reason: str = "",
    now: datetime | None = None,
) -> DecisionResult:
    """End a waiting execution as REJECTED without any business write."""
    return _decide(
        provider=provider,
        authority_provider=authority_provider,
        principal=principal,
        execution_id=execution_id,
        callback_key=callback_key,
        expected_intent_fingerprint=expected_intent_fingerprint,
        decision="REJECT",
        reason=reason,
        now=now,
    )


def stored_decision(document: object) -> DecisionRecord | None:
    """Decode one persisted decision row, failing closed on malformed content."""
    if not isinstance(document, dict):
        return None
    items = cast(Mapping[str, object], document)
    if set(items) != {
        "callback_key",
        "execution_id",
        "approval_id",
        "decision",
        "intent_fingerprint",
        "reason",
        "principal",
        "approval",
        "authority_revision",
        "recorded_at",
    }:
        return None
    try:
        approval_payload = _text(items["approval"], "approval")
        approval = decode_approval(approval_payload)
        principal = decode_principal(_text(items["principal"], "principal"))
        decision = _text(items["decision"], "decision")
        if approval is None or principal is None or decision not in ("APPROVE", "REJECT"):
            return None
        revision = items["authority_revision"]
        if revision is not None and not isinstance(revision, str):
            return None
        return DecisionRecord(
            _text(items["callback_key"], "callback_key"),
            _text(items["execution_id"], "execution_id"),
            _text(items["approval_id"], "approval_id"),
            decision,  # type: ignore[arg-type]
            _text(items["intent_fingerprint"], "intent_fingerprint"),
            _text(items["reason"], "reason"),
            principal,
            approval,
            revision,
            _text(items["recorded_at"], "recorded_at"),
        )
    except (KeyError, TypeError, ValueError):
        return None


__all__ = [
    "ApprovalAuthority",
    "ApprovalAuthorityProvider",
    "DecisionAttempt",
    "DecisionCode",
    "DecisionKind",
    "DecisionProvider",
    "DecisionRecord",
    "DecisionResult",
    "DecisionUnitOfWork",
    "ExecutionSnapshot",
    "approve",
    "decode_principal",
    "encode_principal",
    "reject",
    "stored_decision",
]
