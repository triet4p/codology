"""Host configuration for the simulated break-glass runtime slice.

This module owns the deployment plan, SQLite resource mapping, principals,
read grants, live approver authority and the real adapters. It repeats no
business rule: duration, sensitivity, approval role and state transitions stay
in the declarations under ``access_control`` and ``security_audit``. The
requester and the approver are separate principals, and the outbox is enlisted
in the same physical session as both business writes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from codology import (
    OUTBOX_RESOURCE,
    ApprovalAuthority,
    BoundAction,
    Capability,
    DefinitionKey,
    DelegationGrant,
    DelegationPrincipal,
    Deployment,
    Enlistment,
    LinkedDeclarations,
    LocalReceiver,
    Principal,
    Provider,
    ReadGrant,
    RelayStore,
    Snapshot,
    bind_action,
    snapshot,
)
from codology.adapter import ResourceBinding, SQLiteProvider
from codology.relay_adapter import SQLiteLocalReceiver, SQLiteRelayStore, create_relay_schema
from codology.resume_adapter import ResumeSQLiteProvider
from codology.waiting import RequiredApproval
from examples.break_glass_access import model
from examples.break_glass_access.access_control import GrantAccess, GrantRequest
from examples.break_glass_access.database import SCOPE, TENANT, build_database
from examples.break_glass_access.security_audit import AuditSession, RecordSession

SESSION = "sqlite:break-glass"
PROVIDER = "break-glass-db"

GRANT_READ = "grant_request.read"
AUDIT_READ = "audit_session.read"
GRANT_PERMISSION = "access.grant"
SESSION_PERMISSION = "session.record"
APPROVAL_ROLE = "security_officer"
AUTHORITY_REVISION = "host-policy-1"

REQUESTER = "alice"
APPROVER = "dana"
OUTSIDER = "mallory"
REASON = "incident INC-42 needs privileged access"

GRANT_KEY = DefinitionKey(cast(str, GrantRequest.identity), cast(str, GrantRequest.version))
AUDIT_KEY = DefinitionKey(cast(str, AuditSession.identity), cast(str, AuditSession.version))
ROOT_KEY = DefinitionKey(cast(str, GrantAccess.identity), cast(str, GrantAccess.version))
CHILD_KEY = DefinitionKey(cast(str, RecordSession.identity), cast(str, RecordSession.version))


def current_graph() -> LinkedDeclarations:
    """The revision set every scenario binds and invokes."""
    return model.link_model()


def published_snapshot(graph: LinkedDeclarations | None = None) -> Snapshot:
    """Publish the linked graph; binding looks the root up at its exact version."""
    return snapshot(graph or current_graph())


def deployment() -> Deployment:
    """One physical session hosts both writes, the ledger and the outbox."""
    return Deployment(
        providers=(
            Provider(
                PROVIDER,
                "sqlite",
                frozenset({Capability.ATOMIC_TRANSACTION, Capability.OUTBOX}),
                effect_dedup=SESSION,
            ),
        ),
        enlistments=(
            Enlistment(GRANT_KEY.identity, PROVIDER, SESSION),
            Enlistment(AUDIT_KEY.identity, PROVIDER, SESSION),
            Enlistment(OUTBOX_RESOURCE, PROVIDER, SESSION),
        ),
        delegations=(
            DelegationGrant(
                ROOT_KEY.identity,
                CHILD_KEY.identity,
                SESSION_PERMISSION,
                DelegationPrincipal.REQUESTER,
            ),
        ),
    )


def split_deployment() -> Deployment:
    """A misconfiguration whose look-alike sessions cannot share a transaction."""
    return Deployment(
        providers=(
            Provider(
                "grant-db",
                "sqlite",
                frozenset({Capability.ATOMIC_TRANSACTION, Capability.OUTBOX}),
                effect_dedup=SESSION,
            ),
            Provider("audit-db", "sqlite", frozenset({Capability.ATOMIC_TRANSACTION})),
        ),
        enlistments=(
            Enlistment(GRANT_KEY.identity, "grant-db", SESSION),
            Enlistment(AUDIT_KEY.identity, "audit-db", "sqlite:audit"),
            Enlistment(OUTBOX_RESOURCE, "grant-db", SESSION),
        ),
        delegations=(
            DelegationGrant(
                ROOT_KEY.identity,
                CHILD_KEY.identity,
                SESSION_PERMISSION,
                DelegationPrincipal.REQUESTER,
            ),
        ),
    )


def bound_root(graph: LinkedDeclarations | None = None) -> BoundAction:
    """Bind the root action against the shared-session plan."""
    return bind_action(published_snapshot(graph), deployment(), ROOT_KEY)


def sqlite_provider(path: Path) -> SQLiteProvider:
    """Open the example session through the real adapter, never a mock."""
    return SQLiteProvider(
        path,
        SESSION,
        (
            ResourceBinding(
                GRANT_KEY.identity,
                GRANT_KEY.version,
                "grant_requests",
                ("status", "duration_minutes", "sensitivity"),
                tenant_column="tenant",
                scope_column="scope",
            ),
            ResourceBinding(
                AUDIT_KEY.identity,
                AUDIT_KEY.version,
                "audit_sessions",
                ("status",),
                tenant_column="tenant",
                scope_column="scope",
            ),
        ),
        effect_dedup=SESSION,
    )


class HostAuthority:
    """Live host authority for the security officer role."""

    def __init__(
        self,
        *,
        roles: tuple[str, ...] = (APPROVAL_ROLE,),
        permissions: tuple[str, ...] = (GRANT_PERMISSION,),
        scopes: tuple[str, ...] = (SCOPE,),
        revoked: set[str] | None = None,
    ) -> None:
        self.roles = roles
        self.permissions = permissions
        self.scopes = scopes
        self.revoked: set[str] = revoked if revoked is not None else set()

    def authorize(self, principal: Principal, approval: RequiredApproval) -> ApprovalAuthority:
        """Report current role, permission, scope and revocation for one callback."""
        return ApprovalAuthority(
            frozenset(self.roles),
            frozenset(self.permissions),
            TENANT,
            self.scopes,
            approval.approval_id in self.revoked,
            AUTHORITY_REVISION,
        )


def requester() -> Principal:
    """The principal that requests access and later resumes the approval."""
    return Principal(
        REQUESTER,
        TENANT,
        frozenset({GRANT_READ, AUDIT_READ, GRANT_PERMISSION, SESSION_PERMISSION}),
    )


def approver() -> Principal:
    """A different principal holding the live security-officer role."""
    return Principal(APPROVER, TENANT, frozenset({GRANT_PERMISSION}))


def outsider() -> Principal:
    """A principal with no authority to decide this approval."""
    return Principal(OUTSIDER, TENANT, frozenset())


def grants() -> dict[DefinitionKey, ReadGrant]:
    """Host-issued read grants scoped to this tenant and team."""
    return {
        GRANT_KEY: ReadGrant(REQUESTER, GRANT_KEY, TENANT, (SCOPE,), GRANT_READ),
        AUDIT_KEY: ReadGrant(REQUESTER, AUDIT_KEY, TENANT, (SCOPE,), AUDIT_READ),
    }


@dataclass(slots=True)
class Host:
    """Everything a caller receives from the host for one database file."""

    path: Path
    provider: ResumeSQLiteProvider
    store: RelayStore
    receiver: LocalReceiver
    authority: HostAuthority
    grants: Mapping[DefinitionKey, ReadGrant]
    requester: Principal
    approver: Principal
    outsider: Principal
    graph: LinkedDeclarations
    bound: BoundAction


def open_host(
    path: Path,
    *,
    authority: HostAuthority | None = None,
    store: RelayStore | None = None,
    receiver: LocalReceiver | None = None,
    graph: LinkedDeclarations | None = None,
) -> Host:
    """Open a host over an already seeded database with real SQLite adapters."""
    revisions = graph or current_graph()
    return Host(
        path=Path(path),
        provider=ResumeSQLiteProvider(sqlite_provider(path)),
        store=store or SQLiteRelayStore(path),
        receiver=receiver or SQLiteLocalReceiver(path),
        authority=authority or HostAuthority(),
        grants=grants(),
        requester=requester(),
        approver=approver(),
        outsider=outsider(),
        graph=revisions,
        bound=bound_root(revisions),
    )


def install(path: Path, **seed: object) -> Path:
    """Create a fresh seeded database including the relay's durable tables."""
    database = build_database(path, **seed)  # type: ignore[arg-type]
    create_relay_schema(database)
    return database


__all__ = [
    "APPROVAL_ROLE",
    "APPROVER",
    "AUDIT_KEY",
    "AUDIT_READ",
    "AUTHORITY_REVISION",
    "CHILD_KEY",
    "GRANT_KEY",
    "GRANT_PERMISSION",
    "GRANT_READ",
    "Host",
    "HostAuthority",
    "OUTSIDER",
    "PROVIDER",
    "REASON",
    "REQUESTER",
    "ROOT_KEY",
    "SESSION",
    "SESSION_PERMISSION",
    "SCOPE",
    "TENANT",
    "approver",
    "bound_root",
    "current_graph",
    "deployment",
    "grants",
    "install",
    "open_host",
    "outsider",
    "published_snapshot",
    "requester",
    "split_deployment",
    "sqlite_provider",
]
