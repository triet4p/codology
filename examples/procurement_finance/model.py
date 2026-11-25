"""Compose the Procurement and Finance groups through Load, Link, and Snapshot."""

from __future__ import annotations

from codology import (
    LinkedDeclarations,
    LoadedDeclarations,
    ModuleDeclarations,
    Snapshot,
    link,
    load,
    snapshot,
)
from examples.procurement_finance.finance import DEFINITIONS as FINANCE_DEFINITIONS
from examples.procurement_finance.finance import Finance
from examples.procurement_finance.procurement import DEFINITIONS as PROCUREMENT_DEFINITIONS
from examples.procurement_finance.procurement import Procurement

PROCUREMENT_GROUP = ModuleDeclarations(Procurement, PROCUREMENT_DEFINITIONS)
FINANCE_GROUP = ModuleDeclarations(Finance, FINANCE_DEFINITIONS)


def load_model() -> LoadedDeclarations:
    """Load both ownership groups; no reference is resolved yet."""
    return load(PROCUREMENT_GROUP, FINANCE_GROUP)


def link_model() -> LinkedDeclarations:
    """Resolve references, export boundaries, and handler shapes."""
    return link(load_model())


def build_snapshot() -> Snapshot:
    """Publish the linked graph as an immutable, version-explicit snapshot."""
    return snapshot(link_model())


__all__ = [
    "FINANCE_GROUP",
    "PROCUREMENT_GROUP",
    "build_snapshot",
    "link_model",
    "load_model",
]
