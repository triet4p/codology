"""Behavior of manifest-pinned revision resolution.

The resolver must pick the exact revisions a manifest pins from a host that
holds several revision sets, verify the bytes of the artifact each revision was
loaded from, and reject any missing, changed, or differently-composed revision
before a handler runs. Every fixture handler raises, so any accidental
execution during pinning or resolution fails the test.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

from codology import (
    ArtifactRevision,
    ClosureMismatch,
    DefinitionKey,
    DigestMismatch,
    InvalidManifest,
    KindMismatch,
    LinkedDeclarations,
    MissingArtifact,
    ModuleDeclarations,
    PinnedManifest,
    UnsupportedArtifact,
    decode_manifest,
    encode_manifest,
    link,
    load,
    manifest_digest,
    pin_manifest,
    resolve_manifest,
    snapshot,
)
from codology.declarations import (
    Action,
    Approval,
    CommitRequirement,
    Declaration,
    DeclarationMeta,
    Effect,
    Link,
    Module,
    ObjectRef,
    ObjectType,
    Param,
    Value,
)

_ROOT = "procurement.approve_purchase_order"
_CHILD = "finance.reserve_budget"
_ORDER = "procurement.purchase_order"
_BUDGET = "finance.budget"
_EFFECT = "procurement.warehouse_notified"
_LEDGER = "finance.ledger"


class Money(Value):
    amount: int


class Budget(ObjectType):
    identity = _BUDGET
    version = "1.0.0"
    keyType = "B"
    limit: Money


class PurchaseOrder(ObjectType):
    identity = _ORDER
    version = "1.0.0"
    keyType = "PO"
    amount: Money
    budget = Link["finance.budget", "one", "navigable"]


class Ledger(ObjectType):
    identity = _LEDGER
    version = "1.0.0"
    keyType = "L"


class OrderApprovedPayload(Value):
    order: ObjectRef[PurchaseOrder]
    approved_amount: Money


class NotifyWarehouse(Effect):
    identity = _EFFECT
    version = "1.0.0"
    payload = OrderApprovedPayload


class ReserveBudgetOne(Action):
    identity = _CHILD
    version = "1.0.0"
    budget: ObjectRef[Budget]
    amount: int
    reads = (Budget,)
    writes = (Budget,)
    permission = "budget.reserve"

    def handler(self, ctx: object, budget: Budget, amount: int) -> None:
        raise AssertionError("manifest resolution must never run a handler")


class ReserveBudgetTwo(Action):
    identity = _CHILD
    version = "2.0.0"
    budget: ObjectRef[Budget]
    amount: int
    reads = (Budget,)
    writes = (Budget,)
    permission = "budget.reserve"

    def handler(self, ctx: object, budget: Budget, amount: int) -> None:
        raise AssertionError("manifest resolution must never run a handler")


class ApprovePurchaseOrderOne(Action):
    identity = _ROOT
    version = "1.1.0"
    order: ObjectRef[PurchaseOrder]
    reason: str
    reads = (PurchaseOrder, Budget)
    writes = (PurchaseOrder,)
    calls = (_CHILD,)
    permission = "purchase_order.approve"
    commitRequirement = CommitRequirement.ATOMIC

    def handler(self, ctx: object, order: PurchaseOrder, reason: str) -> None:
        raise AssertionError("manifest resolution must never run a handler")


class ApprovePurchaseOrderTwo(Action):
    identity = _ROOT
    version = "2.0.0"
    order: ObjectRef[PurchaseOrder]
    reason: str
    reads = (PurchaseOrder, Budget)
    writes = (PurchaseOrder,)
    calls = (_CHILD,)
    permission = "purchase_order.approve"
    commitRequirement = CommitRequirement.ATOMIC
    approval = Approval.conditional(
        when=Param("order").amount >= 100_000,
        role="finance_director",
        self_approval=False,
    )
    effects = (NotifyWarehouse,)

    def handler(self, ctx: object, order: PurchaseOrder, reason: str) -> None:
        raise AssertionError("manifest resolution must never run a handler")


class ProcurementOne(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, Ledger, ApprovePurchaseOrderOne)


class FinanceOne(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudgetOne)


class ProcurementTwo(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, NotifyWarehouse, ApprovePurchaseOrderTwo)


class FinanceTwo(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudgetTwo)


class FinanceWithNewChild(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudgetTwo)


def _set_one() -> LinkedDeclarations:
    procurement = (PurchaseOrder, OrderApprovedPayload, Ledger, ApprovePurchaseOrderOne)
    return link(
        load(
            ModuleDeclarations(ProcurementOne, procurement),
            ModuleDeclarations(FinanceOne, (Money, Budget, ReserveBudgetOne)),
        )
    )


def _set_two() -> LinkedDeclarations:
    procurement = (
        PurchaseOrder,
        OrderApprovedPayload,
        NotifyWarehouse,
        ApprovePurchaseOrderTwo,
    )
    return link(
        load(
            ModuleDeclarations(ProcurementTwo, procurement),
            ModuleDeclarations(FinanceTwo, (Money, Budget, ReserveBudgetTwo)),
        )
    )


def _set_one_with_new_child() -> LinkedDeclarations:
    """The same pinned root revision linked against a newer child revision."""
    procurement = (PurchaseOrder, OrderApprovedPayload, Ledger, ApprovePurchaseOrderOne)
    return link(
        load(
            ModuleDeclarations(ProcurementOne, procurement),
            ModuleDeclarations(FinanceWithNewChild, (Money, Budget, ReserveBudgetTwo)),
        )
    )


def _old_manifest() -> PinnedManifest:
    return pin_manifest(_set_one(), DefinitionKey(_ROOT, "1.1.0"))


def _new_manifest() -> PinnedManifest:
    return pin_manifest(_set_two(), DefinitionKey(_ROOT, "2.0.0"))


def _revision(
    identity: str,
    version: str,
    kind: str,
    digest: str = "sha256:" + "0" * 64,
) -> ArtifactRevision:
    return ArtifactRevision(identity, version, kind, digest)


def _with(
    manifest: PinnedManifest,
    *,
    root: ArtifactRevision | None = None,
    children: tuple[ArtifactRevision, ...] | None = None,
    ontology: tuple[ArtifactRevision, ...] | None = None,
) -> PinnedManifest:
    return PinnedManifest(
        root=manifest.root if root is None else root,
        children=manifest.children if children is None else children,
        effects=manifest.effects,
        ontology=manifest.ontology if ontology is None else ontology,
    )


def test_pin_records_the_exact_reachable_revisions() -> None:
    manifest = _old_manifest()

    assert manifest.root == ArtifactRevision(_ROOT, "1.1.0", "Action", manifest.root.digest)
    assert [entry.key for entry in manifest.children] == [DefinitionKey(_CHILD, "1.0.0")]
    assert manifest.effects == ()
    assert [entry.key for entry in manifest.ontology] == [
        DefinitionKey(_BUDGET, "1.0.0"),
        DefinitionKey(_ORDER, "1.0.0"),
    ]
    for entry in manifest.entries:
        assert entry.digest.startswith("sha256:")
        assert len(entry.digest) == len("sha256:") + 64
        assert entry.digest not in {entry.identity, entry.version}
    assert manifest.find(_ORDER, "1.0.0") is not None
    assert manifest.find(_ORDER, "9.9.9") is None


def test_pin_includes_declared_effect_and_new_child_revisions() -> None:
    manifest = _new_manifest()

    assert manifest.root.version == "2.0.0"
    assert [entry.key for entry in manifest.children] == [DefinitionKey(_CHILD, "2.0.0")]
    assert [entry.key for entry in manifest.effects] == [DefinitionKey(_EFFECT, "1.0.0")]


def test_anonymous_values_are_not_given_a_durable_identity() -> None:
    manifest = _new_manifest()
    pinned = {entry.identity for entry in manifest.entries}

    assert "OrderApprovedPayload" not in pinned
    assert all(not identity.startswith("<") for identity in pinned)


def test_encode_decode_round_trip_is_canonical_and_content_addressed() -> None:
    manifest = _old_manifest()
    encoded = encode_manifest(manifest)

    assert decode_manifest(encoded) == manifest
    assert encode_manifest(decode_manifest(encoded)) == encoded
    assert manifest_digest(manifest).startswith("sha256:")
    assert manifest_digest(manifest) != manifest_digest(_new_manifest())

    reordered = PinnedManifest(
        root=manifest.root,
        children=tuple(reversed(manifest.children)),
        effects=manifest.effects,
        ontology=tuple(reversed(manifest.ontology)),
    )
    assert encode_manifest(reordered) == encoded


def test_resolution_takes_the_pinned_revision_set_not_a_default() -> None:
    old = _set_one()
    new = _set_two()
    manifest = pin_manifest(old, DefinitionKey(_ROOT, "1.1.0"))

    resolved = resolve_manifest(manifest, (new, old))

    assert resolved.source is old
    assert resolved.root.definition.version == "1.1.0"
    assert resolved.lookup(DefinitionKey(_CHILD, "1.0.0")).definition.version == "1.0.0"
    assert resolved.manifest == manifest

    newer = resolve_manifest(_new_manifest(), (old, new))
    assert newer.source is new
    assert newer.root.definition.version == "2.0.0"
    assert newer.lookup(DefinitionKey(_CHILD, "2.0.0")).definition.version == "2.0.0"


def test_a_persisted_manifest_resolves_on_freshly_loaded_revision_sets() -> None:
    persisted = encode_manifest(_old_manifest())

    fresh_old = _set_one()
    fresh_new = _set_two()
    resolved = resolve_manifest(decode_manifest(persisted), (fresh_new, fresh_old))

    assert resolved.source is fresh_old
    assert resolved.root.definition.version == "1.1.0"
    assert resolved.root.definition.declaration is ApprovePurchaseOrderOne


def test_resolution_skips_a_host_set_whose_composition_changed_the_child() -> None:
    old = _set_one()
    changed = _set_one_with_new_child()
    manifest = pin_manifest(old, DefinitionKey(_ROOT, "1.1.0"))

    resolved = resolve_manifest(manifest, (changed, old))

    assert resolved.source is old
    assert resolved.lookup(DefinitionKey(_CHILD, "1.0.0")).definition.version == "1.0.0"


def test_missing_root_artifact_is_rejected_before_logic() -> None:
    manifest = _old_manifest()

    with pytest.raises(MissingArtifact) as error:
        resolve_manifest(manifest, _set_two())

    assert error.value.identity == _ROOT
    assert error.value.version == "1.1.0"


def test_missing_child_artifact_is_rejected_even_when_the_root_is_loaded() -> None:
    manifest = _old_manifest()

    with pytest.raises(MissingArtifact) as error:
        resolve_manifest(manifest, _set_one_with_new_child())

    assert error.value.identity == _CHILD
    assert error.value.version == "1.0.0"


def test_changed_artifact_bytes_are_rejected() -> None:
    manifest = _old_manifest()
    tampered = _with(
        manifest,
        root=ArtifactRevision(
            manifest.root.identity,
            manifest.root.version,
            manifest.root.kind,
            "sha256:" + "f" * 64,
        ),
    )

    with pytest.raises(DigestMismatch) as error:
        resolve_manifest(tampered, _set_one())

    assert error.value.identity == _ROOT
    assert error.value.expected == "sha256:" + "f" * 64
    assert error.value.actual == manifest.root.digest


def test_changed_declaration_kind_at_a_pinned_revision_is_rejected() -> None:
    manifest = _old_manifest()
    child = manifest.children[0]
    tampered = _with(
        manifest,
        children=(ArtifactRevision(child.identity, child.version, "Function", child.digest),),
    )

    with pytest.raises(KindMismatch) as error:
        resolve_manifest(tampered, _set_one())

    assert error.value.identity == _CHILD
    assert error.value.version == "1.0.0"


def test_extra_pinned_revision_outside_the_root_closure_is_rejected() -> None:
    manifest = _old_manifest()
    unreachable = ArtifactRevision(_LEDGER, "1.0.0", "ObjectType", manifest.root.digest)
    tampered = _with(manifest, ontology=(*manifest.ontology, unreachable))

    with pytest.raises(ClosureMismatch) as error:
        resolve_manifest(tampered, _set_one())

    assert _LEDGER in str(error.value)


def test_unreadable_source_artifact_is_rejected(
    artifact: Callable[[str, str], tuple[ModuleType, Path]],
) -> None:
    module, path = artifact("manifest_deleted_artifact", _ARTIFACT_SOURCE.format(step=1))
    graph = _artifact_graph(module)
    manifest = pin_manifest(graph, DefinitionKey("artifact.act", "1.0.0"))

    path.unlink()

    with pytest.raises(MissingArtifact) as error:
        resolve_manifest(manifest, graph)
    assert error.value.identity == "artifact.act"


def test_a_declaration_without_a_source_file_cannot_be_pinned() -> None:
    def handler(self: object, ctx: object) -> None:
        raise AssertionError("manifest resolution must never run a handler")

    dynamic = cast(
        type[Declaration],
        DeclarationMeta(
            "DynamicAction",
            (Action,),
            {
                "identity": "dynamic.act",
                "version": "1.0.0",
                "permission": "dynamic.run",
                "handler": handler,
                "__module__": "manifest_module_without_a_file",
            },
        ),
    )
    with pytest.raises(UnsupportedArtifact):
        pin_manifest(_graph_with(dynamic), DefinitionKey("dynamic.act", "1.0.0"))


def test_resolution_rejects_a_published_snapshot() -> None:
    manifest = _old_manifest()
    with pytest.raises(TypeError):
        resolve_manifest(manifest, snapshot(_set_one()))  # pyright: ignore[reportArgumentType]


_ARTIFACT_SOURCE = """\
from __future__ import annotations

from codology.declarations import Action, Module, ObjectRef, ObjectType


class Order(ObjectType):
    identity = "artifact.order"
    version = "1.0.0"


class Act(Action):
    identity = "artifact.act"
    version = "1.0.0"
    order: ObjectRef[Order]
    writes = (Order,)
    permission = "artifact.run"

    def handler(self, ctx, order: Order):
        return {{"step": {step}}}


class Group(Module):
    identity = "artifact.group"
    version = "1.0.0"
    exports = (Order, Act)
"""


def _artifact_graph(module: ModuleType) -> LinkedDeclarations:
    group = cast(type[Module], vars(module)["Group"])
    order = cast(type[Declaration], vars(module)["Order"])
    action = cast(type[Declaration], vars(module)["Act"])
    return link(load(ModuleDeclarations(group, (order, action))))


def _graph_with(declaration: type[Declaration]) -> LinkedDeclarations:
    class DynamicGroup(Module):
        identity = "dynamic"
        version = "1.0.0"
        exports = (declaration,)

    return link(load(ModuleDeclarations(DynamicGroup, (declaration,))))


@pytest.fixture
def artifact(
    tmp_path: Path,
) -> Iterator[Callable[[str, str], tuple[ModuleType, Path]]]:
    names: list[str] = []

    def write(name: str, source: str) -> tuple[ModuleType, Path]:
        path = tmp_path / f"{name}.py"
        path.write_bytes(source.encode("utf-8"))
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        names.append(name)
        spec.loader.exec_module(module)
        return module, path

    yield write
    for name in names:
        sys.modules.pop(name, None)


def test_digest_covers_the_loaded_source_bytes(
    artifact: Callable[[str, str], tuple[ModuleType, Path]],
) -> None:
    first, _ = artifact("manifest_artifact_first", _ARTIFACT_SOURCE.format(step=1))
    second, _ = artifact("manifest_artifact_second", _ARTIFACT_SOURCE.format(step=2))
    graph_first = _artifact_graph(first)
    graph_second = _artifact_graph(second)
    manifest = pin_manifest(graph_first, DefinitionKey("artifact.act", "1.0.0"))

    assert resolve_manifest(manifest, graph_first).root.definition.version == "1.0.0"
    with pytest.raises(DigestMismatch) as error:
        resolve_manifest(manifest, graph_second)
    assert error.value.identity == "artifact.act"


def test_digest_normalizes_line_endings(
    artifact: Callable[[str, str], tuple[ModuleType, Path]],
) -> None:
    source = _ARTIFACT_SOURCE.format(step=3)
    unix, _ = artifact("manifest_artifact_unix", source)
    windows, _ = artifact("manifest_artifact_windows", source.replace("\n", "\r\n"))
    manifest = pin_manifest(_artifact_graph(unix), DefinitionKey("artifact.act", "1.0.0"))

    resolved = resolve_manifest(manifest, _artifact_graph(windows))

    assert resolved.root.definition.version == "1.0.0"


def test_manifest_documents_with_unknown_or_missing_fields_are_rejected() -> None:
    manifest = _old_manifest()
    round_tripped = decode_manifest(encode_manifest(manifest))

    with pytest.raises(InvalidManifest):
        decode_manifest("not json")
    with pytest.raises(InvalidManifest):
        decode_manifest(encode_manifest(round_tripped).replace('"format"', '"unknown"'))
    with pytest.raises(InvalidManifest):
        decode_manifest(encode_manifest(manifest).replace("sha256:", "sha512:"))
    with pytest.raises(InvalidManifest):
        PinnedManifest(root=_revision(_ROOT, "1.1.0", "Effect"))
    with pytest.raises(InvalidManifest):
        PinnedManifest(
            root=manifest.root,
            children=(_revision(_ORDER, "1.0.0", "ObjectType"),),
        )
    with pytest.raises(InvalidManifest):
        PinnedManifest(
            root=manifest.root,
            children=(_revision(_ORDER, "1.0.0", "Action"),),
            ontology=(_revision(_ORDER, "1.0.0", "ObjectType"),),
        )
