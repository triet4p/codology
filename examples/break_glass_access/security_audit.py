"""Security-audit declarations: the privileged session and its recording action.

This module does not import ``access_control``: the child action receives the
session it owns plus a free-text reason, and the parent names it by declared
identity. That keeps the dependency one-way and leaves the link to compose the
namespace.
"""

from __future__ import annotations

from codology.declarations import (
    Action,
    Declaration,
    Module,
    ObjectRef,
    ObjectType,
)
from codology.engine import HandlerCtx


class AuditSession(ObjectType):
    """A privileged audit session reserved for one break-glass request."""

    identity = "security_audit.session"
    version = "1.0.0"
    keyType = "AS"

    status: str


class RecordSession(Action):
    """Record one privileged session; callable from another module once exported."""

    identity = "security_audit.record_session"
    version = "1.0.0"

    session: ObjectRef[AuditSession]
    reason: str

    reads = (AuditSession,)
    writes = (AuditSession,)
    permission = "session.record"

    def handler(self, ctx: HandlerCtx, session: AuditSession, reason: str) -> None:
        ctx.require(session.status == "NEW", reason="session_not_new")
        ctx.uow.register_mutation(session, status="OPEN", expectedVersion=session.version)


class SecurityAudit(Module):
    """Ownership boundary for the audit definitions above."""

    identity = "security_audit"
    version = "1.0.0"
    exports = (AuditSession, RecordSession)


DEFINITIONS: tuple[type[Declaration], ...] = (AuditSession, RecordSession)

__all__ = ["DEFINITIONS", "AuditSession", "RecordSession", "SecurityAudit"]
