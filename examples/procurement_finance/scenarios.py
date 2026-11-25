"""Failure scenarios the example demonstrates and the integration tests assert.

Each function builds a small variant of the Procurement/Finance model, triggers
one static error, and returns it. Nothing here catches *unexpected* errors: a
missing error is an assertion failure, so the example cannot silently claim a
check happened.
"""

from __future__ import annotations

from collections.abc import Callable

from codology import (
    DuplicateIdentity,
    HandlerMismatch,
    ModuleDeclarations,
    NotExported,
    ObjectRefMismatch,
    UnresolvedReference,
    link,
    load,
)
from codology.declarations import (
    Action,
    Approval,
    Module,
    ObjectRef,
    ObjectType,
    UnsupportedApprovalExpression,
)
from examples.procurement_finance.common import Money
from examples.procurement_finance.finance import Budget, Finance, ReserveBudget
from examples.procurement_finance.model import FINANCE_GROUP, PROCUREMENT_GROUP
from examples.procurement_finance.procurement import Procurement, PurchaseOrder


class DuplicateBudget(ObjectType):
    """A second Finance object claiming an identity that is already taken."""

    identity = "finance.budget"
    version = "1.0.0"


def duplicate_identity() -> DuplicateIdentity:
    """Load refuses two declarations claiming ``finance.budget``."""
    try:
        load(ModuleDeclarations(Finance, (Budget, DuplicateBudget)))
    except DuplicateIdentity as error:
        return error
    raise AssertionError("Load accepted a duplicate identity")


class InternalFinance(Module):
    """Finance that keeps ``ReserveBudget`` internal by omission from exports."""

    identity = "finance"
    version = "1.0.0"
    exports = (Budget,)


def missing_export() -> NotExported:
    """Link refuses a cross-module call to a definition that is not exported."""
    try:
        link(
            load(
                PROCUREMENT_GROUP,
                ModuleDeclarations(InternalFinance, (Money, Budget, ReserveBudget)),
            )
        )
    except NotExported as error:
        return error
    raise AssertionError("Link accepted a call to an unexported definition")


class TypoAction(Action):
    """Action whose ``calls`` entry misspells the Finance identity."""

    identity = "procurement.typo_action"
    version = "1.0.0"
    calls = ("finance.reserve_budgett",)
    permission = "local.act"

    def handler(self, ctx: object) -> None:
        raise AssertionError("static example: handlers are never executed")


def unresolved_reference() -> UnresolvedReference:
    """Link refuses a forward reference that names no loaded definition."""
    try:
        link(
            load(
                PROCUREMENT_GROUP,
                ModuleDeclarations(Procurement, (TypoAction,)),
                FINANCE_GROUP,
            )
        )
    except UnresolvedReference as error:
        return error
    raise AssertionError("Link accepted an unresolved reference")


class MismatchedHandlerType(Action):
    """Action whose handler annotates the budget where an order is declared."""

    identity = "procurement.mismatched_handler_type"
    version = "1.0.0"
    order: ObjectRef[PurchaseOrder]
    permission = "local.act"

    def handler(self, ctx: object, order: Budget) -> None:
        raise AssertionError("static example: handlers are never executed")


def object_ref_type_mismatch() -> ObjectRefMismatch:
    """Link refuses a handler annotation that contradicts ``ObjectRef[T]``."""
    try:
        link(
            load(
                PROCUREMENT_GROUP,
                ModuleDeclarations(Procurement, (MismatchedHandlerType,)),
                FINANCE_GROUP,
            )
        )
    except ObjectRefMismatch as error:
        return error
    raise AssertionError("Link accepted a mismatched handler type")


class MismatchedHandlerName(Action):
    """Action whose handler renames a declared parameter."""

    identity = "procurement.mismatched_handler_name"
    version = "1.0.0"
    order: ObjectRef[PurchaseOrder]
    permission = "local.act"

    def handler(self, ctx: object, wrong_name: PurchaseOrder) -> None:
        raise AssertionError("static example: handlers are never executed")


def handler_signature_mismatch() -> HandlerMismatch:
    """Link refuses handler parameters that do not match the declared names."""
    try:
        link(
            load(
                PROCUREMENT_GROUP,
                ModuleDeclarations(Procurement, (MismatchedHandlerName,)),
                FINANCE_GROUP,
            )
        )
    except HandlerMismatch as error:
        return error
    raise AssertionError("Link accepted a mismatched handler signature")


def _build_lambda_approval() -> type[Action]:
    """Build an action whose approval rule is a lambda; creation is the probe."""

    class LambdaApproval(Action):
        identity = "procurement.lambda_approval"
        version = "1.0.0"
        order: ObjectRef[PurchaseOrder]
        permission = "local.act"
        approval = Approval.conditional(
            when=lambda: True,
            role="finance_director",
            self_approval=False,
        )

        def handler(self, ctx: object, order: PurchaseOrder) -> None:
            raise AssertionError("static example: handlers are never executed")

    return LambdaApproval


def approval_lambda() -> UnsupportedApprovalExpression:
    """Declaration rejects a lambda literal in an approval predicate."""
    try:
        _build_lambda_approval()
    except UnsupportedApprovalExpression as error:
        return error
    raise AssertionError("Declaration accepted a lambda approval")


SCENARIOS: tuple[tuple[str, Callable[[], BaseException]], ...] = (
    ("duplicate identity", duplicate_identity),
    ("missing export", missing_export),
    ("unresolved reference", unresolved_reference),
    ("handler type mismatch", object_ref_type_mismatch),
    ("handler signature mismatch", handler_signature_mismatch),
    ("approval lambda", approval_lambda),
)

__all__ = ["SCENARIOS"]
