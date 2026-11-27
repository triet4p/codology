"""Static failure and non-execution scenarios the tests and entry point assert.

Each function builds a small variant of the break-glass model and triggers the
one outcome it names. Nothing catches an unexpected error: a missing outcome is
an assertion failure, so the example cannot silently claim a check happened.
"""

from __future__ import annotations

from collections.abc import Callable

from codology import ModuleDeclarations, NotExported, link, load, snapshot
from codology.declarations import Action, Module, ObjectRef
from codology.engine import HandlerCtx
from examples.break_glass_access.access_control import (
    DEFINITIONS as ACCESS_CONTROL_DEFINITIONS,
)
from examples.break_glass_access.access_control import AccessControl
from examples.break_glass_access.security_audit import (
    DEFINITIONS as AUDIT_DEFINITIONS,
)
from examples.break_glass_access.security_audit import (
    AuditSession,
    RecordSession,
    SecurityAudit,
)

PROBE_IDENTITY = "security_audit.handler_probe"


class AuditWithoutSessionExport(Module):
    """security_audit that keeps ``AuditSession`` internal by omitting it."""

    identity = "security_audit"
    version = "1.0.0"
    exports = (RecordSession,)


def missing_export() -> NotExported:
    """Link refuses a cross-module reference to a definition that is not exported."""
    try:
        link(
            load(
                ModuleDeclarations(AccessControl, ACCESS_CONTROL_DEFINITIONS),
                ModuleDeclarations(AuditWithoutSessionExport, AUDIT_DEFINITIONS),
            )
        )
    except NotExported as error:
        return error
    raise AssertionError("Link accepted a reference to an unexported definition")


class HandlerProbe(Action):
    """An action whose handler raises if any static phase ever executes it."""

    identity = PROBE_IDENTITY
    version = "1.0.0"

    session: ObjectRef[AuditSession]

    reads = (AuditSession,)
    writes = (AuditSession,)
    permission = "probe.never_called"

    def handler(self, ctx: HandlerCtx, session: AuditSession) -> None:
        raise AssertionError("Load, Link and Snapshot must never execute a handler")


def handler_is_not_executed() -> str:
    """Load, Link, and Snapshot the probe; a handler call would raise."""
    groups = (
        ModuleDeclarations(AccessControl, ACCESS_CONTROL_DEFINITIONS),
        ModuleDeclarations(SecurityAudit, (*AUDIT_DEFINITIONS, HandlerProbe)),
    )
    published = snapshot(link(load(*groups)))
    return published.lookup(PROBE_IDENTITY, "1.0.0").identity


SCENARIOS: tuple[tuple[str, Callable[[], BaseException]], ...] = (
    ("missing export", missing_export),
)

__all__ = ["SCENARIOS", "handler_is_not_executed", "missing_export"]
