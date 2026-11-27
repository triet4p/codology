"""Compose the access-control and security-audit groups through Load and Link."""

from __future__ import annotations

from codology import (
    DefinitionKey,
    LinkedDeclarations,
    LoadedDeclarations,
    ModuleDeclarations,
    Snapshot,
    link,
    load,
    snapshot,
)
from examples.break_glass_access.access_control import (
    DEFINITIONS as ACCESS_CONTROL_DEFINITIONS,
)
from examples.break_glass_access.access_control import AccessControl
from examples.break_glass_access.security_audit import DEFINITIONS as AUDIT_DEFINITIONS
from examples.break_glass_access.security_audit import SecurityAudit

ACCESS_GROUP = ModuleDeclarations(AccessControl, ACCESS_CONTROL_DEFINITIONS)
AUDIT_GROUP = ModuleDeclarations(SecurityAudit, AUDIT_DEFINITIONS)

GRANT_ACCESS_KEY = DefinitionKey("access_control.grant_access", "1.0.0")
RECORD_SESSION_KEY = DefinitionKey("security_audit.record_session", "1.0.0")


def load_model() -> LoadedDeclarations:
    """Load both ownership groups; no reference is resolved yet."""
    return load(ACCESS_GROUP, AUDIT_GROUP)


def link_model() -> LinkedDeclarations:
    """Resolve references, export boundaries, and handler shapes."""
    return link(load_model())


def build_snapshot() -> Snapshot:
    """Publish the linked graph as an immutable, version-explicit snapshot."""
    return snapshot(link_model())


__all__ = [
    "ACCESS_GROUP",
    "AUDIT_GROUP",
    "GRANT_ACCESS_KEY",
    "RECORD_SESSION_KEY",
    "build_snapshot",
    "link_model",
    "load_model",
]
