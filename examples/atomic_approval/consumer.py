"""The consumer path: authorized query, typed refs, one ``invoke`` call.

A caller owns a principal, host-issued read grants, a provider, the linked graph
and the bound deployment plan. It reads through ``query``, takes refs from the
returned rows with ``as_ref`` and hands them to ``invoke``. It does not check
permissions, inspect budgets, build SQL or resolve ids itself.
"""

from __future__ import annotations

from collections.abc import Mapping

from codology import (
    BoundAction,
    Comparison,
    DefinitionKey,
    LinkedDeclarations,
    MinorMoney,
    OrderBy,
    Principal,
    QueryPage,
    QueryRow,
    ReadGrant,
    SecureQueryProvider,
    VersionedRef,
    query,
)
from codology.engine import ActionResult, ScopedEngineProvider, invoke
from examples.atomic_approval.wiring import APPROVE_KEY, BUDGET_KEY, ORDER_KEY
from examples.procurement_finance import runtime


def find_orders(
    provider: SecureQueryProvider,
    principal: Principal,
    grants: Mapping[DefinitionKey, ReadGrant],
    *,
    status: str = "PENDING_APPROVAL",
    cursor: str | None = None,
    limit: int = 20,
) -> QueryPage[runtime.PurchaseOrder]:
    """Read one policy-filtered page of orders in the given status."""
    return query(
        provider=provider,
        principal=principal,
        grant=grants[ORDER_KEY],
        from_=ORDER_KEY,
        target=runtime.PurchaseOrder,
        order=OrderBy("created_at"),
        predicate=Comparison("status", "==", status),
        cursor=cursor,
        limit=limit,
        count_requested=True,
    )


def find_budget(
    provider: SecureQueryProvider,
    principal: Principal,
    grants: Mapping[DefinitionKey, ReadGrant],
    key: str = "B-1",
) -> QueryRow[runtime.Budget]:
    """Read one visible budget row; the key is a query predicate, not a bypass."""
    page = query(
        provider=provider,
        principal=principal,
        grant=grants[BUDGET_KEY],
        from_=BUDGET_KEY,
        target=runtime.Budget,
        order=OrderBy("id"),
        predicate=Comparison("id", "==", key),
        limit=1,
        count_requested=True,
    )
    if not page.rows:
        raise LookupError(f"budget {key!r} is not visible to {principal.identity!r}.")
    return page.rows[0]


def approve(
    *,
    provider: ScopedEngineProvider,
    linked: LinkedDeclarations,
    bound: BoundAction,
    principal: Principal,
    grants: Mapping[DefinitionKey, ReadGrant],
    order: VersionedRef[runtime.PurchaseOrder],
    budget: VersionedRef[runtime.Budget],
    reason: str,
    amount: MinorMoney,
    request_key: str,
) -> ActionResult:
    """Invoke the tier-2 action with refs taken from authorized query rows."""
    return invoke(
        linked=linked,
        action=APPROVE_KEY,
        bound=bound,
        provider=provider,
        principal=principal,
        grants=grants,
        parameters={
            "order": order,
            "budget": budget,
            "reason": reason,
            "amount": amount,
        },
        request_key=request_key,
    )


__all__ = ["approve", "find_budget", "find_orders"]
