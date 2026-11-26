"""Positive typing checks for the Load -> Link -> Snapshot surface.

This module is not collected by pytest; ``uv run pyright`` checks it in strict
mode. ``assert_type`` calls fail the type-check if a public return type drifts.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import assert_type, cast

from codology import (
    AllOf,
    ApprovalAuthority,
    ApprovalAuthorityProvider,
    ArtifactRevision,
    Assignment,
    AwaitingExecution,
    Comparison,
    ComparisonValue,
    Condition,
    DecisionProvider,
    DecisionResult,
    DefinitionKey,
    Dependency,
    GuardedWrite,
    LinkedDeclarations,
    LinkedDefinition,
    LoadedDeclarations,
    LoadedDefinition,
    LoadedModule,
    MaterialIntent,
    MinorMoney,
    ObjectVersion,
    OrderBy,
    PinnedManifest,
    PredicateEvaluation,
    Principal,
    QueryPage,
    QueryRow,
    ReadGrant,
    RequiredApproval,
    ResolvedManifest,
    Snapshot,
    SnapshotEntry,
    VersionedRef,
    approval_deadline,
    approve,
    authorize_read,
    build_material_intent,
    decode_awaiting,
    decode_manifest,
    encode_awaiting,
    encode_manifest,
    evaluate_predicate,
    is_issued_ref,
    link,
    load,
    manifest_digest,
    new_approval,
    pin_manifest,
    reject,
    resolve_manifest,
    snapshot,
)
from codology.decision import decode_principal, encode_principal
from codology.declarations import ObjectRef
from codology.engine import ActionResult, AttemptOutcome
from examples.procurement_finance.finance import Budget
from examples.procurement_finance.model import FINANCE_GROUP, PROCUREMENT_GROUP
from examples.procurement_finance.procurement import ApprovePurchaseOrder

loaded = load(PROCUREMENT_GROUP, FINANCE_GROUP)
assert_type(loaded, LoadedDeclarations)
assert_type(loaded.modules["finance"], LoadedModule)
assert_type(loaded.definitions["finance.budget"], LoadedDefinition)
assert_type(loaded.definitions["finance.budget"].identity, str | None)
assert_type(loaded.definitions["finance.budget"].owner, str)

linked = link(loaded)
assert_type(linked, LinkedDeclarations)
assert_type(linked.definitions["finance.budget"], LinkedDefinition)
assert_type(linked.definitions["finance.budget"].hints, Mapping[str, object])
assert_type(linked.definitions["finance.budget"].handler_hints, Mapping[str, object])

published = snapshot(linked)
assert_type(published, Snapshot)
entry = published.lookup("finance.budget", "1.0.0")
assert_type(entry, SnapshotEntry)
assert_type(entry.dependencies, tuple[Dependency, ...])
assert_type(published.versions_of("finance.budget"), tuple[str, ...])
assert_type(DefinitionKey("finance.budget", "1.0.0"), DefinitionKey)

pinned = pin_manifest(linked, DefinitionKey("procurement.approve_purchase_order", "2.0.0"))
assert_type(pinned, PinnedManifest)
assert_type(pinned.root, ArtifactRevision)
assert_type(encode_manifest(pinned), str)
assert_type(decode_manifest(encode_manifest(pinned)), PinnedManifest)
assert_type(manifest_digest(pinned), str)
resolved = resolve_manifest(pinned, linked)
assert_type(resolved, ResolvedManifest)
assert_type(resolved.root, LinkedDefinition)
assert_type(resolved.definitions, Mapping[DefinitionKey, LinkedDefinition])

assert_type(ObjectRef[Budget], type[ObjectRef])
assert_type(MinorMoney.from_decimal(Decimal("12.34"), "VND", exponent=2), MinorMoney)
assert_type(Assignment("balance", "add", -1), Assignment)
assert_type(Condition("balance", ">=", 1), Condition)
assert_type(
    GuardedWrite("finance.budget", "B-001", 1, (Assignment("balance", "add", -1),)),
    GuardedWrite,
)
assert_type(Principal("alice", "A", frozenset({"purchase_order.read"})), Principal)
assert_type(
    ReadGrant("alice", DefinitionKey("finance.budget", "1.0.0"), "A", ("team1",), "read"),
    ReadGrant,
)
assert_type(Comparison("status", "==", "PENDING_APPROVAL"), Comparison)
assert_type(AllOf((Comparison("status", "==", "PENDING_APPROVAL"),)), AllOf)
assert_type(OrderBy("created_at", "asc"), OrderBy)
row: QueryRow[Budget] = cast(
    QueryRow[Budget],
    QueryRow.issue(DefinitionKey("finance.budget", "1.0.0"), "B-001", 1, {"balance": 100}),
)
assert_type(row.as_ref(), VersionedRef[Budget])
assert_type(
    VersionedRef.issue(DefinitionKey("finance.budget", "1.0.0"), "B-001", 1),
    VersionedRef[object],
)
assert_type(QueryPage((row,), 1, None), QueryPage[Budget])
assert_type(
    authorize_read(
        Principal("alice", "A", frozenset({"read"})),
        ReadGrant(
            "alice",
            DefinitionKey("finance.budget", "1.0.0"),
            "A",
            ("team1",),
            "read",
        ),
        DefinitionKey("finance.budget", "1.0.0"),
    ),
    None,
)
assert_type(is_issued_ref(None), bool)
assert_type(AttemptOutcome("COMMITTED", None), AttemptOutcome)
assert_type(ActionResult(AttemptOutcome("DENIED", None)), ActionResult)

assert_type(ComparisonValue("order", ("amount",), 100_000), ComparisonValue)
assert_type(ObjectVersion("procurement.purchase_order", "PO-1", 1), ObjectVersion)
assert_type(approval_deadline("2030-01-01T00:00:00Z"), str)
assert_type(AttemptOutcome("AWAITING_APPROVAL", None), AttemptOutcome)
intent = build_material_intent(
    canonical_input={"order": {"amount": 120_000}},
    comparisons=(ComparisonValue("order", ("amount",), 120_000),),
    object_versions=(ObjectVersion("procurement.purchase_order", "PO-1", 1),),
    pinned=pinned,
)
assert_type(intent, MaterialIntent)
requester = Principal("alice", "A", frozenset({"purchase_order.read"}))
required = new_approval(
    role="finance_director",
    tenant="A",
    scope=("team1",),
    requester=requester,
    expires_at="2030-01-01T00:00:00Z",
    self_approval=False,
    intent_fingerprint=intent.fingerprint,
    execution_id="EX-1",
)
assert_type(required, RequiredApproval)
awaiting = AwaitingExecution(
    "EX-1",
    DefinitionKey("procurement.approve_purchase_order", "2.0.0"),
    requester,
    {"order": "PO-1"},
    encode_manifest(pinned),
    intent,
    required,
    "2026-01-01T00:00:00Z",
)
assert_type(awaiting, AwaitingExecution)
assert_type(encode_awaiting(awaiting), str)
assert_type(decode_awaiting(encode_awaiting(awaiting)), AwaitingExecution | None)
approval = ApprovePurchaseOrder.approval
assert approval is not None
assert_type(
    evaluate_predicate(approval.when, {"order": object(), "reason": "x"}),
    PredicateEvaluation,
)

gate_authority = ApprovalAuthority(
    frozenset({"finance_director"}),
    frozenset({"purchase_order.approve"}),
    "A",
    ("team1",),
)
assert_type(gate_authority, ApprovalAuthority)
assert_type(encode_principal(requester), str)
assert_type(decode_principal(encode_principal(requester)), Principal | None)
gate_provider = cast(DecisionProvider, None)
gate_source = cast(ApprovalAuthorityProvider, None)
assert_type(
    approve(
        provider=gate_provider,
        authority_provider=gate_source,
        principal=requester,
        execution_id="EX-1",
        callback_key="EX-1:AP-1",
        expected_intent_fingerprint=required.intent_fingerprint,
    ),
    DecisionResult,
)
assert_type(
    reject(
        provider=gate_provider,
        authority_provider=gate_source,
        principal=requester,
        execution_id="EX-1",
        callback_key="EX-1:AP-1",
        expected_intent_fingerprint=required.intent_fingerprint,
        reason="budget withdrawn",
    ),
    DecisionResult,
)
