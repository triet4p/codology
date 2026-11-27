"""Access-control declarations for the simulated break-glass domain.

The cross-module edge to ``security_audit`` is written as a declared identity
in ``reads`` and as a forward annotation on the handler; the defining module is
imported only for type checking, so no runtime import joins the two modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from codology import payload_of
from codology.declarations import (
    Action,
    CommitRequirement,
    Declaration,
    Effect,
    Module,
    ObjectRef,
    ObjectType,
    Value,
    any_of,
)
from codology.declarations.behavior import Approval, Param
from codology.engine import HandlerCtx, ResolvedObject

if TYPE_CHECKING:
    from examples.break_glass_access.security_audit import AuditSession


class GrantRequest(ObjectType):
    """A break-glass request; the duration is an integer number of minutes."""

    identity = "access_control.grant_request"
    version = "1.0.0"
    keyType = "AGR"

    status: str
    duration_minutes: int
    sensitivity: str


class NotificationPayload(Value):
    """Typed snapshot carried by the post-commit local notification."""

    identity = "access_control.notification_payload"
    version = "1.0.0"

    request: ObjectRef[GrantRequest]
    session: ObjectRef[AuditSession]
    duration_minutes: int


class NotifyLocalSink(Effect):
    """Outbox intent shape; it writes a local notification and grants nothing."""

    identity = "access_control.notify_local_sink"
    version = "1.0.0"
    payload = NotificationPayload
    dedupKey = ("request",)


class GrantAccess(Action):
    """Grant a break-glass request, recording the audit session via a child."""

    identity = "access_control.grant_access"
    version = "1.0.0"

    request: ObjectRef[GrantRequest]
    session: ObjectRef[AuditSession]
    reason: str

    reads = (GrantRequest, "security_audit.session")
    writes = (GrantRequest,)
    calls = ("security_audit.record_session",)
    permission = "access.grant"
    commitRequirement = CommitRequirement.ATOMIC
    effects = (NotifyLocalSink,)
    approval = Approval.conditional(
        when=any_of(
            Param("request").duration_minutes >= 60,
            Param("request").sensitivity == "CRITICAL",
        ),
        role="security_officer",
        self_approval=False,
    )

    def handler(
        self,
        ctx: HandlerCtx,
        request: GrantRequest,
        session: AuditSession,
        reason: str,
    ) -> None:
        ctx.require(request.status == "PENDING", reason="request_not_pending")
        ctx.require(bool(reason.strip()), reason="reason_required")
        ctx.call("security_audit.record_session", session=session, reason=reason)
        ctx.uow.register_mutation(request, status="GRANTED", expectedVersion=request.version)
        ctx.uow.enqueue_effect(
            NotifyLocalSink,
            payload=payload_of(
                NotificationPayload,
                request=cast(ResolvedObject[GrantRequest], request).ref,
                session=cast(ResolvedObject[object], session).ref,
                duration_minutes=request.duration_minutes,
            ),
        )


class AccessControl(Module):
    """Ownership boundary for the access-control definitions above."""

    identity = "access_control"
    version = "1.0.0"
    exports = (GrantRequest, GrantAccess, NotificationPayload, NotifyLocalSink)


DEFINITIONS: tuple[type[Declaration], ...] = (
    GrantRequest,
    GrantAccess,
    NotificationPayload,
    NotifyLocalSink,
)

__all__ = [
    "DEFINITIONS",
    "AccessControl",
    "GrantAccess",
    "GrantRequest",
    "NotificationPayload",
    "NotifyLocalSink",
]
