"""End-to-end checks for the documented Procurement/Finance example.

These tests import the example package itself, so the runnable script and the
assertions cannot drift apart. No test starts a server, opens a database, or
builds an engine: the whole path is Load, Link, and Snapshot.
"""

from __future__ import annotations

import pytest

from codology import (
    AllOfExpr,
    ComparisonExpr,
    DuplicateIdentity,
    HandlerMismatch,
    NotExported,
    ObjectRefMismatch,
    UnresolvedReference,
)
from codology.declarations import UnsupportedApprovalExpression
from examples.procurement_finance.__main__ import main
from examples.procurement_finance.finance import Budget
from examples.procurement_finance.model import (
    build_snapshot,
    link_model,
    load_model,
)
from examples.procurement_finance.scenarios import (
    approval_lambda,
    duplicate_identity,
    handler_signature_mismatch,
    missing_export,
    object_ref_type_mismatch,
    unresolved_reference,
)

_APPROVE = "procurement.approve_purchase_order"
_ORDER = "procurement.purchase_order"
_BUDGET = "finance.budget"
_RESERVE = "finance.reserve_budget"


def test_example_composes_load_link_and_snapshot_without_a_backend() -> None:
    loaded = load_model()
    assert loaded.definitions[_BUDGET].owner == "finance"
    assert loaded.definitions[_BUDGET].version == "1.0.0"
    assert loaded.definitions[_APPROVE].owner == "procurement"
    assert loaded.definitions[_APPROVE].version == "2.0.0"

    linked = link_model()
    approve_edges = {
        (reference.field, reference.target.identity)
        for reference in linked.definitions[_APPROVE].references
    }
    assert approve_edges == {
        ("params.order", _ORDER),
        ("reads", _ORDER),
        ("reads", _BUDGET),
        ("writes", _ORDER),
        ("calls", _RESERVE),
        ("effects", "procurement.warehouse_order_approved"),
    }
    order_edges = {
        (reference.field, reference.target.identity)
        for reference in linked.definitions[_ORDER].references
    }
    assert ("links.budget", _BUDGET) in order_edges

    published = build_snapshot()
    entry = published.lookup(_APPROVE, "2.0.0")
    assert entry.owner == "procurement"
    assert entry.kind == "Action"
    assert entry.permission == "purchase_order.approve"
    assert entry.commit_requirement == "ATOMIC"
    assert entry.approval is not None
    assert entry.approval.role == "finance_director"
    assert entry.approval.self_approval is False
    when = entry.approval.when
    assert isinstance(when, AllOfExpr)
    operators = {part.operator for part in when.parts if isinstance(part, ComparisonExpr)}
    assert operators == {">=", "!="}
    assert published.versions_of(_BUDGET) == ("1.0.0",)


def test_duplicate_identity_is_rejected_at_load_with_both_declarations() -> None:
    error = duplicate_identity()

    assert isinstance(error, DuplicateIdentity)
    assert error.module == "finance"
    assert error.identity == _BUDGET
    assert error.field == "identity"
    assert error.declaration is Budget
    assert error.conflicting_declaration.__name__ == "DuplicateBudget"
    assert "finance.budget" in str(error)


def test_missing_export_is_rejected_at_link_for_the_call_edge() -> None:
    error = missing_export()

    assert isinstance(error, NotExported)
    assert error.module == "procurement"
    assert error.identity == _APPROVE
    assert error.field == "calls"
    assert _RESERVE in str(error)
    assert "exports" in str(error)


def test_unresolved_reference_is_rejected_at_link_with_the_typo() -> None:
    error = unresolved_reference()

    assert isinstance(error, UnresolvedReference)
    assert error.module == "procurement"
    assert error.identity == "procurement.typo_action"
    assert error.field == "calls"
    assert "finance.reserve_budgett" in str(error)


def test_handler_type_mismatch_is_rejected_at_link() -> None:
    error = object_ref_type_mismatch()

    assert isinstance(error, ObjectRefMismatch)
    assert error.module == "procurement"
    assert error.identity == "procurement.mismatched_handler_type"
    assert error.field == "handler"
    assert "PurchaseOrder" in str(error)
    assert "Budget" in str(error)


def test_handler_signature_mismatch_is_rejected_at_link() -> None:
    error = handler_signature_mismatch()

    assert isinstance(error, HandlerMismatch)
    assert error.module == "procurement"
    assert error.identity == "procurement.mismatched_handler_name"
    assert error.field == "handler"
    assert "wrong_name" in str(error)


def test_approval_lambda_is_rejected_at_declaration() -> None:
    error = approval_lambda()

    assert isinstance(error, UnsupportedApprovalExpression)
    assert "approval predicates" in str(error)
    assert "lambda" in str(error)


def test_documented_entrypoint_prints_success_and_every_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main() == 0
    output = capsys.readouterr().out

    assert f"{_APPROVE}@2.0.0" in output
    assert "calls -> finance.reserve_budget" in output
    assert "kind=Action" in output
    for label in (
        "duplicate identity",
        "missing export",
        "unresolved reference",
        "handler type mismatch",
        "handler signature mismatch",
        "approval lambda",
    ):
        assert f"  {label}: " in output
    for error_name in (
        "DuplicateIdentity",
        "NotExported",
        "UnresolvedReference",
        "ObjectRefMismatch",
        "HandlerMismatch",
        "UnsupportedApprovalExpression",
    ):
        assert error_name in output
