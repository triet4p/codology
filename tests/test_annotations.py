from __future__ import annotations

import pytest

from codology.declarations import raw_annotations, resolve_annotations


def test_raw_annotations_keep_forward_references_as_written() -> None:
    class FinanceBudget:
        pass

    class ProcurementAction:
        budget: FinanceBudget

    assert raw_annotations(ProcurementAction) == {"budget": "FinanceBudget"}


def test_annotations_resolve_through_the_link_time_namespace() -> None:
    class FinanceBudget:
        pass

    class ProcurementAction:
        budget: FinanceBudget

    resolved = resolve_annotations(ProcurementAction, {"FinanceBudget": FinanceBudget})

    assert resolved == {"budget": FinanceBudget}


def test_two_declarations_resolve_each_other_without_an_import_cycle() -> None:
    class ProcurementAction:
        target: FinanceAction

    class FinanceAction:
        origin: ProcurementAction

    namespace = {
        "ProcurementAction": ProcurementAction,
        "FinanceAction": FinanceAction,
    }

    procurement_hints = resolve_annotations(ProcurementAction, namespace)
    finance_hints = resolve_annotations(FinanceAction, namespace)

    assert procurement_hints == {"target": FinanceAction}
    assert finance_hints == {"origin": ProcurementAction}


def test_unresolvable_forward_reference_fails_at_resolution_time() -> None:
    procurement_action = type(
        "ProcurementAction",
        (),
        {"__annotations__": {"budget": "MissingBudget"}},
    )

    with pytest.raises(NameError):
        resolve_annotations(procurement_action, {})
