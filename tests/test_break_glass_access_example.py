"""Static checks for the documented break-glass example.

The tests import the example package itself, so the runnable script and the
assertions cannot drift apart. No test starts a server, opens a database, or
builds an engine: the whole path is Load, Link, and Snapshot.
"""

from __future__ import annotations

import pytest

from codology import (
    AnyOfExpr,
    ComparisonExpr,
    FieldPath,
    LiteralValue,
    NotExported,
    UnknownDefinition,
)
from examples.break_glass_access.__main__ import main
from examples.break_glass_access.access_control import (
    AccessControl,
    GrantAccess,
    GrantRequest,
    NotificationPayload,
)
from examples.break_glass_access.model import (
    GRANT_ACCESS_KEY,
    build_snapshot,
    link_model,
    load_model,
)
from examples.break_glass_access.scenarios import (
    PROBE_IDENTITY,
    handler_is_not_executed,
    missing_export,
)
from examples.break_glass_access.security_audit import (
    AuditSession,
    SecurityAudit,
)

_GRANT = "access_control.grant_request"
_AUDIT = "security_audit.session"
_GRANT_ACCESS = "access_control.grant_access"
_RECORD = "security_audit.record_session"
_PAYLOAD = "access_control.notification_payload"
_SINK = "access_control.notify_local_sink"


def test_load_records_identity_version_and_owner_for_both_modules() -> None:
    loaded = load_model()

    assert set(loaded.definitions) == {
        _GRANT,
        _GRANT_ACCESS,
        _PAYLOAD,
        _SINK,
        _AUDIT,
        _RECORD,
    }
    for identity in (_GRANT, _GRANT_ACCESS, _PAYLOAD, _SINK, _AUDIT, _RECORD):
        assert loaded.definitions[identity].version == "1.0.0"

    assert loaded.definitions[_GRANT].owner == "access_control"
    assert loaded.definitions[_GRANT_ACCESS].owner == "access_control"
    assert loaded.definitions[_PAYLOAD].owner == "access_control"
    assert loaded.definitions[_SINK].owner == "access_control"
    assert loaded.definitions[_AUDIT].owner == "security_audit"
    assert loaded.definitions[_RECORD].owner == "security_audit"
    assert loaded.definitions[_GRANT_ACCESS].declaration is GrantAccess


def test_module_exports_limit_cross_module_visibility() -> None:
    assert AccessControl.identity == "access_control"
    assert SecurityAudit.identity == "security_audit"
    assert tuple(entry.identity for entry in AccessControl.exports) == (
        _GRANT,
        _GRANT_ACCESS,
        _PAYLOAD,
        _SINK,
    )
    assert tuple(entry.identity for entry in SecurityAudit.exports) == (_AUDIT, _RECORD)

    assert AccessControl.is_exported(GrantRequest)
    assert AccessControl.is_exported(NotificationPayload)
    assert SecurityAudit.is_exported(AuditSession)
    assert not SecurityAudit.is_exported(GrantRequest)


def test_link_resolves_typed_refs_child_and_effect_edges() -> None:
    linked = link_model()

    parent_edges = {
        (reference.field, reference.target.identity)
        for reference in linked.definitions[_GRANT_ACCESS].references
    }
    assert parent_edges == {
        ("params.request", _GRANT),
        ("params.session", _AUDIT),
        ("reads", _GRANT),
        ("reads", _AUDIT),
        ("writes", _GRANT),
        ("calls", _RECORD),
        ("effects", _SINK),
    }

    child_edges = {
        (reference.field, reference.target.identity)
        for reference in linked.definitions[_RECORD].references
    }
    assert child_edges == {
        ("params.session", _AUDIT),
        ("reads", _AUDIT),
        ("writes", _AUDIT),
    }

    payload_edges = {
        (reference.field, reference.target.identity)
        for reference in linked.definitions[_PAYLOAD].references
    }
    assert payload_edges == {
        ("params.request", _GRANT),
        ("params.session", _AUDIT),
    }

    sink_edges = {
        (reference.field, reference.target.identity)
        for reference in linked.definitions[_SINK].references
    }
    assert sink_edges == {("payload", _PAYLOAD)}

    handler_hints = linked.definitions[_GRANT_ACCESS].handler_hints
    assert handler_hints["request"] is GrantRequest
    assert handler_hints["session"] is AuditSession
    assert handler_hints["reason"] is str


def test_snapshot_publishes_explicit_version_and_any_of_approval() -> None:
    published = build_snapshot()

    entry = published.lookup(GRANT_ACCESS_KEY.identity, GRANT_ACCESS_KEY.version)
    assert entry.owner == "access_control"
    assert entry.kind == "Action"
    assert entry.permission == "access.grant"
    assert entry.commit_requirement == "ATOMIC"

    approval = entry.approval
    assert approval is not None
    assert approval.role == "security_officer"
    assert approval.self_approval is False

    when = approval.when
    assert isinstance(when, AnyOfExpr)
    assert len(when.parts) == 2
    branches: set[tuple[str, str, tuple[str, ...], object]] = set()
    for part in when.parts:
        assert isinstance(part, ComparisonExpr)
        left = part.left
        right = part.right
        assert isinstance(left, FieldPath)
        assert isinstance(right, LiteralValue)
        branches.add((part.operator, left.parameter, left.path, right.value))
    assert branches == {
        (">=", "request", ("duration_minutes",), 60),
        ("==", "request", ("sensitivity",), "CRITICAL"),
    }

    dependency_edges = {
        (
            dependency.field,
            dependency.target_identity,
            dependency.target_owner,
            dependency.target_kind,
        )
        for dependency in entry.dependencies
    }
    assert ("calls", _RECORD, "security_audit", "Action") in dependency_edges
    assert ("effects", _SINK, "access_control", "Effect") in dependency_edges
    assert ("reads", _AUDIT, "security_audit", "ObjectType") in dependency_edges

    assert published.versions_of(_AUDIT) == ("1.0.0",)
    effect_entry = published.lookup(_SINK, "1.0.0")
    assert effect_entry.kind == "Effect"
    effect_edges = {
        (dependency.field, dependency.target_identity) for dependency in effect_entry.dependencies
    }
    assert effect_edges == {("payload", _PAYLOAD)}

    with pytest.raises(UnknownDefinition) as excinfo:
        published.lookup(_GRANT_ACCESS, "2.0.0")
    assert excinfo.value.identity == _GRANT_ACCESS
    assert excinfo.value.version == "2.0.0"
    assert excinfo.value.available == ("1.0.0",)


def test_missing_export_is_rejected_at_link_with_context() -> None:
    error = missing_export()

    assert isinstance(error, NotExported)
    assert error.module == "access_control"
    assert error.identity == _GRANT_ACCESS
    assert error.field == "params.session"
    assert _AUDIT in str(error)
    assert "exports" in str(error)


def test_static_phases_never_execute_a_handler() -> None:
    assert handler_is_not_executed() == PROBE_IDENTITY


def test_documented_entrypoint_prints_success_and_expected_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main() == 0
    output = capsys.readouterr().out

    assert f"{_GRANT}@1.0.0 owner=access_control" in output
    assert f"{_AUDIT}@1.0.0 owner=security_audit" in output
    assert f"{_GRANT_ACCESS}@1.0.0:" in output
    assert "params.session -> security_audit.session" in output
    assert "calls -> security_audit.record_session" in output
    assert "effects -> access_control.notify_local_sink" in output
    assert "kind=Action" in output
    assert "permission=access.grant" in output
    assert "commitRequirement=ATOMIC" in output
    assert "role='security_officer'" in output
    assert "any_of branches=" in output
    assert PROBE_IDENTITY in output
    assert "missing export: NotExported" in output
    assert "field='params.session'" in output
