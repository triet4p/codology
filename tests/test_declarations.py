from __future__ import annotations

from decimal import Decimal
from typing import Literal, cast

import pytest

from codology.declarations import (
    Declaration,
    DeclarationError,
    DeclarationMeta,
    Link,
    Module,
    ObjectRef,
    ObjectType,
    Value,
)


class Money(Value):
    amount: Decimal
    currency: str


class Budget(ObjectType):
    identity = "finance.budget"
    version = "1.0.0"
    keyType = "B"

    limit: Money
    reserved: Money


class PurchaseOrder(ObjectType):
    identity = "procurement.purchase_order"
    version = "1.0.0"
    keyType = "PO"

    status: Literal["PENDING", "APPROVED"]
    amount: Money
    budget = Link[Budget, "one", "navigable"]


class Procurement(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder,)


def make_budget(identity: str) -> type[ObjectType]:
    return cast(
        type[ObjectType],
        DeclarationMeta(
            "Budget",
            (ObjectType,),
            {"identity": identity, "version": "1.0.0"},
        ),
    )


def test_purchase_order_budget_and_money_are_constructible_without_a_backend() -> None:
    assert Budget.identity == "finance.budget"
    assert Budget.version == "1.0.0"
    assert Budget.keyType == "B"
    assert Budget.properties == {"limit": "Money", "reserved": "Money"}
    assert Money.properties == {"amount": "Decimal", "currency": "str"}
    assert set(PurchaseOrder.properties) == {"status", "amount"}
    assert PurchaseOrder.properties["amount"] == "Money"

    budget_link = PurchaseOrder.links["budget"]
    assert budget_link.target is Budget
    assert budget_link.cardinality == "one"
    assert budget_link.traversal == "navigable"

    assert Procurement.exports == (PurchaseOrder,)
    assert Procurement.is_exported(PurchaseOrder)
    assert not Procurement.is_exported(Budget)


def test_object_ref_carries_a_typed_target_and_is_frozen() -> None:
    reference = ObjectRef[Budget]
    forward_reference = ObjectRef["Budget"]

    assert reference.target is Budget
    assert forward_reference.target == "Budget"
    with pytest.raises(AttributeError):
        reference.target = Money


def test_declaration_classes_reject_post_creation_mutation() -> None:
    with pytest.raises(AttributeError):
        Budget.identity = "finance.other_budget"
    with pytest.raises(AttributeError):
        Budget.version = "2.0.0"
    with pytest.raises(AttributeError):
        Budget.extra = True
    with pytest.raises(AttributeError):
        delattr(Budget, "identity")
    with pytest.raises(TypeError):
        cast(dict[str, object], Budget.properties)["amount"] = str
    with pytest.raises(TypeError):
        cast(dict[str, object], PurchaseOrder.links)["other"] = Link[Budget, "many", "internal"]


def test_mutating_input_collections_does_not_change_declarations() -> None:
    exported_definitions: list[type[Declaration]] = [PurchaseOrder]
    input_links: dict[str, type[Link]] = {"budget": Link[Budget, "one", "navigable"]}

    class LocalOrder(ObjectType):
        identity = "procurement.local_order"
        version = "1.0.0"
        amount: Money
        links = input_links

    module = cast(
        type[Module],
        DeclarationMeta(
            "LocalModule",
            (Module,),
            {"identity": "local", "version": "1.0.0", "exports": exported_definitions},
        ),
    )

    exported_definitions.append(Budget)
    input_links["extra"] = Link[Budget, "one", "navigable"]
    LocalOrder.__annotations__["amount"] = str

    assert module.exports == (PurchaseOrder,)
    assert set(LocalOrder.links) == {"budget"}
    assert LocalOrder.properties["amount"] == "Money"


def test_same_host_class_name_with_different_identity_does_not_collide() -> None:
    finance = make_budget("finance.budget")
    procurement = make_budget("procurement.budget")
    module = cast(
        type[Module],
        DeclarationMeta(
            "FinanceModule",
            (Module,),
            {"identity": "finance", "version": "1.0.0", "exports": (finance,)},
        ),
    )

    assert finance.__name__ == procurement.__name__ == "Budget"
    assert finance.identity != procurement.identity
    assert len({finance.identity, procurement.identity}) == 2
    assert module.is_exported(finance)
    assert not module.is_exported(procurement)


def test_invalid_declarations_are_rejected_with_context() -> None:
    with pytest.raises(DeclarationError, match="identity"):
        DeclarationMeta("MissingIdentity", (ObjectType,), {"version": "1.0.0"})
    with pytest.raises(DeclarationError, match="cardinality"):
        Link[Budget, "some", "navigable"]
    with pytest.raises(DeclarationError, match="traversal"):
        Link[Budget, "one", "hidden"]
    with pytest.raises(DeclarationError, match="target"):
        Link[str, "one", "navigable"]
    with pytest.raises(DeclarationError, match="exports"):
        DeclarationMeta(
            "BadModule",
            (Module,),
            {"identity": "bad", "version": "1.0.0", "exports": ["finance.budget"]},
        )
