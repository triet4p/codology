from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest

from codology.declarations import (
    Action,
    Declaration,
    DeclarationMeta,
    Link,
    Module,
    ObjectType,
    Value,
)
from codology.loading import (
    DuplicateIdentity,
    LoadError,
    ModuleDeclarations,
    UnknownDeclarationKey,
    load,
)


class Money(Value):
    amount: Decimal
    currency: str


class Budget(ObjectType):
    identity = "finance.budget"
    version = "1.0.0"
    keyType = "B"


class PurchaseOrder(ObjectType):
    identity = "procurement.purchase_order"
    version = "1.0.0"
    keyType = "PO"


class LocalOrder(ObjectType):
    identity = "procurement.local_order"
    version = "1.0.0"
    amount: Decimal
    budget = Link[Budget, "one", "navigable"]


class ApprovePurchaseOrder(Action):
    identity = "procurement.approve_purchase_order"
    version = "1.0.0"
    order: ObjectType
    reads = (PurchaseOrder,)
    writes = (PurchaseOrder,)
    permission = "purchase_order.approve"

    def handler(self, ctx: object, order: PurchaseOrder) -> None:
        raise AssertionError("Load must never call a handler")


class ReserveBudget(Action):
    identity = "finance.reserve_budget"
    version = "1.0.0"
    budget: ObjectType
    reads = (Budget,)
    writes = (Budget,)
    permission = "budget.reserve"

    def handler(self, ctx: object, budget: Budget) -> None:
        raise AssertionError("Load must never call a handler")


class Procurement(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApprovePurchaseOrder)


class Finance(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudget)


def test_load_collects_owned_definitions_with_identity_and_version() -> None:
    loaded = load(
        ModuleDeclarations(Procurement, [PurchaseOrder, ApprovePurchaseOrder, Money, LocalOrder]),
        ModuleDeclarations(Finance, [Budget, ReserveBudget]),
    )

    assert tuple(loaded.modules) == ("procurement", "finance")
    assert loaded.modules["procurement"].declaration is Procurement
    assert loaded.modules["procurement"].version == "1.0.0"
    assert loaded.modules["procurement"].exports == (PurchaseOrder, ApprovePurchaseOrder)
    assert loaded.modules["finance"].declaration is Finance
    assert [item.identity for item in loaded.modules["procurement"].definitions] == [
        "procurement.purchase_order",
        "procurement.approve_purchase_order",
        None,
        "procurement.local_order",
    ]

    assert set(loaded.definitions) == {
        "procurement.purchase_order",
        "procurement.approve_purchase_order",
        "procurement.local_order",
        "finance.budget",
        "finance.reserve_budget",
    }
    reserved = loaded.definitions["finance.reserve_budget"]
    assert reserved.declaration is ReserveBudget
    assert reserved.version == "1.0.0"
    assert reserved.owner == "finance"
    assert reserved.module is Finance
    assert loaded.definitions["procurement.purchase_order"].declaration is PurchaseOrder


def test_load_rejects_duplicate_identity_with_both_owners() -> None:
    legacy = cast(
        type[Action],
        DeclarationMeta(
            "ApprovePurchaseOrderLegacy",
            (Action,),
            {
                "identity": ApprovePurchaseOrder.identity,
                "version": "2.0.0",
                "permission": "purchase_order.approve",
            },
        ),
    )
    legacy_module = cast(
        type[Module],
        DeclarationMeta(
            "LegacyProcurement",
            (Module,),
            {"identity": "legacy", "version": "1.0.0", "exports": ()},
        ),
    )

    with pytest.raises(DuplicateIdentity) as error:
        load(
            ModuleDeclarations(Procurement, [ApprovePurchaseOrder]),
            ModuleDeclarations(legacy_module, [legacy]),
        )

    assert error.value.identity == "procurement.approve_purchase_order"
    assert error.value.module == "procurement"
    assert error.value.field == "identity"
    assert error.value.conflicting_module == "legacy"
    assert "legacy" in str(error.value)
    assert "distinct identity" in str(error.value)


def test_load_rejects_unknown_declaration_key_with_module_identity_and_field() -> None:
    invalid = cast(
        type[Action],
        DeclarationMeta(
            "PrivilegedAction",
            (Action,),
            {
                "identity": "procurement.privileged_action",
                "version": "1.0.0",
                "permission": "purchase_order.approve",
                "privileged": True,
            },
        ),
    )

    with pytest.raises(UnknownDeclarationKey) as error:
        load(ModuleDeclarations(Procurement, [invalid]))

    assert error.value.module == "procurement"
    assert error.value.identity == "procurement.privileged_action"
    assert error.value.field == "privileged"
    assert "privileged" in str(error.value)
    assert "typed property annotation" in str(error.value)


def test_load_never_derives_identity_from_host_class_name() -> None:
    finance_budget = cast(
        type[ObjectType],
        DeclarationMeta(
            "Budget",
            (ObjectType,),
            {"identity": "finance.alternate_budget", "version": "1.0.0"},
        ),
    )
    procurement_budget = cast(
        type[ObjectType],
        DeclarationMeta(
            "Budget",
            (ObjectType,),
            {"identity": "procurement.alternate_budget", "version": "1.0.0"},
        ),
    )

    loaded = load(
        ModuleDeclarations(Finance, [finance_budget]),
        ModuleDeclarations(Procurement, [procurement_budget, Money]),
    )

    assert finance_budget.__name__ == procurement_budget.__name__ == "Budget"
    assert set(loaded.definitions) == {
        "finance.alternate_budget",
        "procurement.alternate_budget",
    }
    assert loaded.definitions["finance.alternate_budget"].declaration is finance_budget
    assert loaded.definitions["procurement.alternate_budget"].declaration is procurement_budget
    assert "Budget" not in loaded.definitions
    anonymous = loaded.modules["procurement"].definitions[1]
    assert anonymous.declaration is Money
    assert anonymous.identity is None
    assert "Money" not in loaded.definitions


def test_load_copies_group_input_and_freezes_its_indexes() -> None:
    definitions: list[type[Declaration]] = [PurchaseOrder]
    groups: list[ModuleDeclarations] = [ModuleDeclarations(Procurement, definitions)]
    loaded = load(*groups)

    definitions.append(ReserveBudget)
    groups.clear()

    assert tuple(loaded.definitions) == ("procurement.purchase_order",)
    assert len(loaded.modules["procurement"].definitions) == 1
    with pytest.raises(TypeError):
        cast(dict[str, object], loaded.modules)["other"] = object()
    with pytest.raises(TypeError):
        cast(dict[str, object], loaded.definitions)["other"] = object()


def test_load_rejects_a_definition_claimed_by_two_modules() -> None:
    with pytest.raises(LoadError, match="exactly one module") as error:
        load(
            ModuleDeclarations(Procurement, [PurchaseOrder]),
            ModuleDeclarations(Finance, [PurchaseOrder]),
        )

    assert error.value.field == "owner"
    assert error.value.module == "finance"
    assert error.value.identity == "procurement.purchase_order"
