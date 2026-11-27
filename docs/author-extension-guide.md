# Hướng dẫn author mở rộng nghiệp vụ ngoài duyệt đơn

Tài liệu này là điểm vào cho một developer **không tham gia viết lõi** cần thêm một nghiệp vụ mới bằng API công khai của `codology`. Đọc từ đầu tới cuối, làm theo thứ tự pha, rồi dùng các lệnh ở cuối để tự kiểm chứng. Sau khi đọc xong, developer khác có thể dựng declaration/handler, link graph, bind một session vật lý và chạy trên SQLite thật mà không cần hỏi tác giả tài liệu.

## 0. Nguồn sự thật và giới hạn của tài liệu

- **Ưu tiên API đang chạy và bằng chứng thực thi:** `examples/conditional_approval/` (mốc Sprint 5, chạy được trên SQLite thật) và `examples/atomic_approval/` (đường đồng bộ nấc 2, regression). Mọi chữ ký trong tài liệu này được đối chiếu với source dưới `src/codology/` và với các ví dụ đó.
- [Developer Contract](official/design/developer-contract.md), [Consumer Contract](official/design/consumer-contract.md) và [Evolution & Cross-Domain Validation](official/design/evolution-and-cross-domain.md) §3 là **mô tả thiết kế**. Chúng giải thích tại sao, không định nghĩa tên import hay chữ ký runtime. Bảng ở mục 8 chỉ rõ chỗ pseudocode thiết kế khác API đang chạy.
- Không sửa `src/codology/`, không monkey-patch, không nới grant, không bỏ qua binding, không dùng API private để làm ca mới chạy. Nếu thiếu capability dùng chung, ghi blocker với ca tối thiểu; không thay bằng demo giả hay âm thầm hạ tiêu chí.
- Phạm vi chạy được: SQLite file-backed một session vật lý, effect chỉ là thông báo vào sink local. Không có HTTP/service/SDK/MCP, IAM/PKI hay broker thật, scheduler/escalation, registry/publish pipeline, chuyển đổi đơn vị tùy ý, FX, hay exactly-once ngoài DB local. Không có gate latency/throughput/coverage.

## 1. Setup

Từ gốc repo, trên môi trường Python/uv sạch:

```bash
uv sync
uv run python -c "import codology; print(codology.__version__)"
```

Để tái lập mà không đổi `.venv` hiện có, đặt `UV_PROJECT_ENVIRONMENT` trước `uv sync` và giữ nó cho mọi `uv run` (ví dụ trỏ vào `.tmp/verify/venv` trong workspace). `.tmp/` đã được git-ignore.

`pyproject.toml` khóa `requires-python = ">=3.13"`, pin `.python-version` = `3.13`; dùng `uv` cho mọi lệnh Python. Cấu trúc đề xuất cho nghiệp vụ mới (không đụng `src/codology/`):

```text
examples/<domain>/
    model.py          # declaration: ObjectType/Value/Link/Action/Effect/Module + handler
    database.py       # duy nhất nơi viết SQL/schema/seed của host
    wiring.py         # DefinitionKey, graph, Deployment, provider/adapter, principal/grant/authority
    consumer.py       # chỉ gọi API công khai; không policy, không SQL
    __main__.py       # kịch bản chạy thử, in và assert kết quả
tests/test_<domain>.py
```

Với hai owner, tách declaration theo module rồi compose ở `model.py`: xem `examples/break_glass_access/access_control.py`, `security_audit.py` và `model.py`. Cách chia tệp là lựa chọn của ví dụ, không phải API bắt buộc.

Mọi module phải có `identity` và `version` **tường minh**; không suy từ tên class. Declaration là class bất biến: gán lại thuộc tính sau khi định nghĩa bị từ chối. Mọi `Action`/`Function` có đúng một instance method tên `handler(self, ctx, ...)`; `@staticmethod def handle(...)` không được hỗ trợ.

## 2. Ranh giới: developer, host, handler

| Vai | Viết/cấp | Không viết/cấp |
| --- | --- | --- |
| **Author (developer)** | `identity`/`version`, property, `Link`, `ObjectRef[T]`, `reads`/`writes`/`calls`, `permission`, `commitRequirement`, `approval`, `effects`, payload `Value`, nội dung `handler`, `Module.exports` | SQL, connection, transaction, credential, quyết định duyệt, gửi thông báo, import adapter/backend |
| **Host (developer tích hợp)** | Schema/seed SQLite, `ResourceBinding`, `SQLiteProvider`/`ResumeSQLiteProvider`, `Deployment`/`Enlistment`/`DelegationGrant`, `Principal`, `ReadGrant`, `ApprovalAuthorityProvider`, `RelayStore`/`LocalReceiver`, tham số request và `request_key` | Luật nghiệp vụ của author (ngưỡng, role, trạng thái đơn), tự tính fingerprint hay callback key |
| **Consumer (developer gọi API)** | `query`, `row.as_ref()`, `invoke`, `approve`/`reject`, `resume`, `reconcile`, `deliver_committed`, `read_effect_status`; diễn giải `ActionResult` | SQL, tự kiểm policy, tự dựng fingerprint/key, import handler hay module nghiệp vụ để lấy luật |
| **Handler** | `ctx.require`, `ctx.resolve`, `ctx.call`, `ctx.uow.register_mutation`, `ctx.uow.enqueue_effect`, đọc `ctx.principal`/`ctx.reads`/`ctx.writes`/`ctx.calls` | Mở connection/SQL/driver, credential hoặc ambient identity, `commit()`/`rollback()`, clock/random/network/file/socket, global state, đọc/ghi bỏ qua engine, gọi effect trực tiếp |

`ctx` là in-process trust boundary, **không phải sandbox**: Load/Link/binding không đọc thân handler và không phát hiện import lén, `getattr` động hay I/O ẩn. Bù lại là review, test và DB role bị giới hạn ngoài phạm vi đã khai báo.

## 3. Pha 1 — declaration và handler

Import đúng (đối chiếu `examples/conditional_approval/declarations.py`):

```python
from __future__ import annotations

from typing import cast

from codology import payload_of
from codology.declarations import (
    Action,
    CommitRequirement,
    Effect,
    Module,
    ObjectRef,
    ObjectType,
    Value,
    any_of,
)
from codology.declarations.behavior import Approval, Param
from codology.engine import HandlerCtx, ResolvedObject
```

Mẫu dưới đây là **hình dạng** cho miền giả lập (thời lượng là `int` phút, role và ngưỡng là literal của miền, effect chỉ ghi sink local). Thay identity/tên/field bằng nghiệp vụ của bạn; đừng import module Procurement/Finance hay copy handler của chúng.

```python
class GrantRequest(ObjectType):
    identity = "access_control.grant_request"
    version = "1.0.0"
    keyType = "AGR"

    status: str
    duration_minutes: int       # số nguyên phút ở runtime; không viết Duration/comparisonUnit
    sensitivity: str


class AuditSession(ObjectType):
    identity = "security_audit.session"
    version = "1.0.0"
    keyType = "AS"

    status: str


class RecordSession(Action):
    identity = "security_audit.record_session"
    version = "1.0.0"

    session: ObjectRef[AuditSession]
    reason: str

    reads = (AuditSession,)
    writes = (AuditSession,)
    permission = "session.record"

    def handler(self, ctx: HandlerCtx, session: AuditSession, reason: str) -> None:
        ctx.require(session.status == "NEW", reason="session_not_new")
        ctx.uow.register_mutation(session, status="OPEN", expectedVersion=session.version)


class NotificationPayload(Value):
    identity = "access_control.notification_payload"
    version = "1.0.0"

    request: ObjectRef[GrantRequest]
    session: ObjectRef[AuditSession]
    duration_minutes: int


class NotifyLocalSink(Effect):
    identity = "access_control.notify_local_sink"
    version = "1.0.0"
    payload = NotificationPayload
    dedupKey = ("request",)      # path trên payload, không phải SQL hay fingerprint tự dựng


class GrantAccess(Action):
    identity = "access_control.grant_access"
    version = "1.0.0"

    request: ObjectRef[GrantRequest]
    session: ObjectRef[AuditSession]
    reason: str

    reads = (GrantRequest, AuditSession)
    writes = (GrantRequest,)
    calls = ("security_audit.record_session",)
    permission = "access.grant"
    commitRequirement = CommitRequirement.ATOMIC
    effects = (NotifyLocalSink,)
    approval = Approval.conditional(
        when=any_of(
            Param("request").duration_minutes >= 60,
            Param("request").sensitivity == "CRITICAL",
        ),
        role="security_officer",
        self_approval=False,
    )

    def handler(
        self, ctx: HandlerCtx, request: GrantRequest, session: AuditSession, reason: str
    ) -> None:
        ctx.require(request.status == "PENDING", reason="request_not_pending")
        ctx.require(bool(reason.strip()), reason="reason_required")
        ctx.call("security_audit.record_session", session=session, reason=reason)
        ctx.uow.register_mutation(request, status="GRANTED", expectedVersion=request.version)
        ctx.uow.enqueue_effect(
            NotifyLocalSink,
            payload=payload_of(
                NotificationPayload,
                request=cast(ResolvedObject[GrantRequest], request).ref,
                session=cast(ResolvedObject[AuditSession], session).ref,
                duration_minutes=request.duration_minutes,
            ),
        )
```

Action cha khai `commitRequirement = CommitRequirement.ATOMIC`: `bind_action()` chỉ chấp nhận plan có `Capability.ATOMIC_TRANSACTION` cho action kiểu này. Bỏ dòng này thì Load/Link vẫn qua, nhưng binding runtime từ chối — đây là chỗ dễ đoán sai khi chỉ đọc mẫu declaration.

Quy tắc cứng của pha này:

- Annotation trong thân class là **contract** (`ObjectRef[T]`); annotation trên `handler` là kiểu đã resolve (`T`). Tên và thứ tự tham số handler phải khớp đúng thứ tự property đã khai báo. `Link` viết kiểu `Link[Target, "one"|"many", "navigable"|"internal"]` (xem `examples/procurement_finance/`); target là class `ObjectType` hoặc chuỗi identity.
- Predicate duyệt chỉ dùng `Comparison`/`all_of`/`any_of`/`not_` và `Param("...").field...` với toán tử `> >= < <= == !=`. Literal được đóng băng; lambda, method call, số học, subscript, `getattr` đều bị từ chối ngay lúc khai báo (`UnsupportedApprovalExpression`). Mọi tên param trong predicate phải tồn tại trong `params`.
- Child action qua `calls` không được có `approval` hay `effects`; engine gọi thẳng handler con trong cùng UoW. `ctx.call` nhận **identity chuỗi**, không nhận class hay ref.
- Handler nhận object đã resolve qua engine, thực chất là `ResolvedObject[T]`. Dùng `.ref` khi cần truyền typed ref vào payload/child; `expectedVersion` phải lấy từ `obj.version` (số nguyên hàng đang resolve). Mutation phải nằm trong `writes` đã khai báo và cột phải được adapter map.
- `Function` là read-only: khai báo `result`/`reads`/`calls`, không được có `writes`/`approval`/`effects`. Không có API runtime cho truy vấn `Function` kiểu pseudocode; đừng thiết kế handler phụ thuộc vào nó.

## 4. Pha 2 — ownership và export

```python
class AccessControl(Module):
    identity = "access_control"
    version = "1.0.0"
    exports = (GrantRequest, GrantAccess, NotificationPayload, NotifyLocalSink)


class SecurityAudit(Module):
    identity = "security_audit"
    version = "1.0.0"
    exports = (AuditSession, RecordSession)
```

- `exports` là tuple các **class declaration có identity**, không phải chuỗi. Export theo identity: cùng identity ở module khác được coi là cùng definition.
- Tham chiếu liên module (`ObjectRef`, `reads`, `writes`, `calls`, `effects`, `payload`, link target) chỉ hợp lệ khi definition đích nằm trong `exports` của owner. Cùng owner thì không cần export. `Value` không có identity dùng được làm property type, nhưng không thể được naming liên module.
- Để tránh import vòng, dùng chuỗi identity cho `calls = ("security_audit.record_session",)` và forward annotation `"AuditSession"`/`Link["security_audit.session", ...]`. Link compose namespace từ **mọi module tham gia link**; không import module kia lúc chạy.
- Lỗi cố tình để kiểm chứng ở pha Link: bỏ `AuditSession` khỏi `SecurityAudit.exports` rồi link → `NotExported` kèm `module`, `identity`, `field`. Đây là ca T2 yêu cầu; không sửa lõi để lỗi biến mất.

## 5. Pha 3 — Load / Link / snapshot / manifest

Host dựng graph (mẫu `wiring.current_graph()` của Sprint 5):

```python
from codology import DefinitionKey, LinkedDeclarations, ModuleDeclarations, link, load, snapshot

def current_graph() -> LinkedDeclarations:
    return link(
        load(
            ModuleDeclarations(
                d.AccessControl,
                (d.GrantRequest, d.GrantAccess, d.NotificationPayload, d.NotifyLocalSink),
            ),
            ModuleDeclarations(d.SecurityAudit, (d.AuditSession, d.RecordSession)),
        )
    )

GRANT_KEY = DefinitionKey("access_control.grant_access", "1.0.0")
published = snapshot(current_graph())
entry = published.lookup(GRANT_KEY.identity, GRANT_KEY.version)
```

- `load(*groups)` thu thập definition theo ownership; identity trùng hoặc field lạ → `DuplicateIdentity` / `UnknownDeclarationKey`. `link(loaded)` resolve annotation và kiểm reference; lỗi `UnresolvedReference`, `WrongKind`, `NotExported`, `ObjectRefMismatch`, `HandlerMismatch` đều kèm module/identity/field. `snapshot(linked)` là view bất biến, keyed bởi cặp `(identity, version)`; không có `latest`, không gọi handler, không mở DB.
- `DefinitionKey(identity, version)` luôn tường minh; `lookup` với version sai ném `UnknownDefinition`. `snapshot` không công bố digest handler.
- Khi có `approval`, engine ghim logic qua manifest: `pin_manifest(graph, action_key)` và `resolve_manifest(manifest, graph_or_revision_sets)` (`codology.manifest`). `resume` dùng manifest đã ghim, không lấy default version mới. Không tự dựng hash hay bỏ qua bước này.
- Muốn xem nhanh đường tĩnh và sáu lỗi mẫu: `uv run python -m examples.procurement_finance` (không cần backend; handler trong ví dụ đó chỉ raise để chứng minh không ai gọi).

## 6. Pha 4 — schema, binding và delegation (phía host)

Schema SQLite phải chứa bảng business với cột được map, `request_ledger`, `approval_decisions`, `approval_audit`, `approval_resume_outcomes`, `outbox`; relay thêm `effect_delivery`, `notification_inbox`, `local_notifications` qua `create_relay_schema(path)`. Xem `examples/conditional_approval/database.py` và `wiring.install()` để copy cấu trúc, **không copy luật nghiệp vụ**.

```python
from codology import (
    OUTBOX_RESOURCE, Capability, DelegationGrant, DelegationPrincipal,
    Deployment, Enlistment, Provider, bind_action,
)
from codology.adapter import ResourceBinding, SQLiteProvider

SESSION = "sqlite:access-control"

GRANT = "access_control.grant_request"
AUDIT = "security_audit.session"
ROOT = "access_control.grant_access"
CHILD = "security_audit.record_session"

def deployment() -> Deployment:
    return Deployment(
        providers=(
            Provider(
                "app-db", "sqlite",
                frozenset({Capability.ATOMIC_TRANSACTION, Capability.OUTBOX}),
                effect_dedup=SESSION,
            ),
        ),
        enlistments=(
            Enlistment(GRANT, "app-db", SESSION),
            Enlistment(AUDIT, "app-db", SESSION),   # write của child cũng phải enlisted
            Enlistment(OUTBOX_RESOURCE, "app-db", SESSION),
        ),
        delegations=(
            DelegationGrant(ROOT, CHILD, "session.record", DelegationPrincipal.REQUESTER),
        ),
    )

bound = bind_action(snapshot(graph), deployment(), GRANT_KEY)

provider = SQLiteProvider(
    path,
    SESSION,
    (
        ResourceBinding(GRANT, "1.0.0", "grant_requests", ("status", "duration_minutes", "sensitivity"),
                        tenant_column="tenant", scope_column="scope"),
        ResourceBinding(AUDIT, "1.0.0", "audit_sessions", ("status",),
                        tenant_column="tenant", scope_column="scope"),
    ),
    effect_dedup=SESSION,
)
```

- Write set là **transitive** theo `calls`: `writes` của root + `writes` của child. Mỗi resource phải có đúng một `Enlistment`; `ATOMIC` đòi provider có `Capability.ATOMIC_TRANSACTION`; effect đòi `Capability.OUTBOX`, `effect_dedup` và enlistment `OUTBOX_RESOURCE` **cùng provider và cùng session**.
- DelegationGrant phải khớp `caller` identity, `call` identity và **đúng** `permission` của child; `DelegationPrincipal.SERVICE` bị từ chối (`AmbientServiceIdentity`). Requester vẫn cần permission của child trong principal để `ctx.call` chạy.
- Lỗi binding thường gặp: `MissingCapability`, `UnboundWrite`, `NoSharedTransaction`, `EffectSessionMismatch`, `InconsistentSession`, `UndeclaredCall`, `PermissionBroadened`, `UnknownProvider`. Tách session (đổi `SESSION` của một enlistment) bị từ chối trước khi handler chạy — đây là ca bắt buộc của T3.
- `SQLiteProvider.begin` còn kiểm `SessionMismatch` nếu plan trỏ session khác; adapter map sai cột → `UnknownResource`/`InvalidColumn`. Dùng `ResumeSQLiteProvider(provider)` cho approve/resume và `SQLiteRelayStore`/`SQLiteLocalReceiver` cho relay như `wiring.open_host()`.

## 7. Pha 5 — API chạy thử và envelope

Chữ ký thật (đối chiếu trực tiếp bằng `inspect.signature`, xem mục 9):

```python
# codology (import root)
query(*, provider, principal, grant, from_, target, order, predicate=None,
      cursor=None, limit=20, count_requested=False, traverse=None) -> QueryPage[T]

# codology.engine
invoke(*, linked, action, bound, provider, principal, grants, parameters,
       request_key=None, intent_fingerprint=None, approval_expires_at=None) -> ActionResult
reconcile(*, provider, principal, action, request_key) -> ActionResult

# codology.decision
approve(*, provider, authority_provider, principal, execution_id, callback_key,
        expected_intent_fingerprint, reason="", now=None) -> DecisionResult
reject(*, ...)  # cùng chữ ký approve

# codology.resume
resume(*, provider, revisions, bound, principal, grants, execution_id, callback_key,
       authority_provider, now=None, approval_expires_at=None) -> ActionResult
reconcile_execution(*, provider, principal, execution_id) -> ActionResult

# codology.relay
deliver_committed(store, receiver, *, limit=20) -> tuple[Delivery, ...]
read_effect_status(store, principal, execution_id) -> tuple[EffectState, ...]
```

Đường gọi tối thiểu (mọi giá trị principal/grant/provider/authority do host cấp; consumer không tự tính key hay fingerprint):

```python
from codology import Comparison, OrderBy, Principal, ReadGrant, query
from codology.decision import approve
from codology.engine import invoke, reconcile
from codology.resume import resume
from codology.relay import deliver_committed, read_effect_status

page = query(
    provider=host.provider, principal=requester, grant=grants[GRANT_KEY],
    from_=GRANT_KEY, target=GrantRequest, order=OrderBy("id"),
    predicate=Comparison("id", "==", "AGR-1"), limit=1, count_requested=True,
)
ref = page.rows[0].as_ref()          # cách hợp pháp duy nhất để có VersionedRef

result = invoke(
    linked=graph, action=GRANT_KEY, bound=bound, provider=host.provider,
    principal=requester, grants=grants,
    parameters={"request": ref, "session": session_ref, "reason": "break-glass"},
    request_key="tenant-a:alice:grant-1:001",
)
if result.attempt.code == "AWAITING_APPROVAL":
    approval = result.execution.required_approval
    decision = approve(
        provider=host.provider, authority_provider=host.authority, principal=approver,
        execution_id=result.execution.execution_id,
        callback_key=approval.callback_key,
        expected_intent_fingerprint=approval.intent_fingerprint,
        reason="officer approved",
    )
    finished = resume(
        provider=host.provider, revisions=(graph,), bound=bound,
        principal=requester, grants=grants,
        execution_id=result.execution.execution_id,
        callback_key=approval.callback_key, authority_provider=host.authority,
    )
```

Diễn giải kết quả:

| Trường | Nghĩa |
| --- | --- |
| `result.attempt.code` | `COMMITTED`, `AWAITING_APPROVAL`, `DENIED`, `REJECTED`, `StalePlan`, `UNKNOWN` |
| `result.attempt.reason` | `KEY_MISUSE`, `REAPPROVAL_REQUIRED`…; `DENIED` là kết quả attempt, không tạo execution |
| `result.execution.execution_id` | execution có thật; replay cùng `request_key` **và cùng intent** trả cùng ID, `deduplicated=True`; nếu ref/intent đổi thì `DENIED`/`KEY_MISUSE`, dùng `reconcile` để tra cứu |
| `result.execution.required_approval` | `callback_key` + `intent_fingerprint` để approve; **không tự sinh** |
| `result.execution.committed` / `.children` / `.pinned_manifest` | bằng chứng đã commit, child đã chạy, revision đã ghim |
| `result.attempt.code == "UNKNOWN"` | commit không xác nhận; phải `reconcile`/`reconcile_execution` bằng key/id cũ, không tạo key mới |

`approve` chỉ ghi decision + audit và trả attempt `APPROVED` kèm `DecisionResult.decision`; nó **không** ghi business/outbox. `reject` hợp lệ là terminal `REJECTED`, không ghi nghiệp vụ. `resume` chạy lại handler trên logic đã ghim, dữ liệu hiện tại; nếu material intent đổi hoặc approval hết hạn/bị thu hồi thì trả `AWAITING_APPROVAL` kèm key/fingerprint mới. Relay `deliver_committed` chỉ lấy outbox đã commit; replay cùng dedup ID không gửi lại nghiệp vụ. `reconcile` cần `execution.read`, `read_effect_status` cần `effect.read` (`EXECUTION_READ_PERMISSION`, `EFFECT_READ_PERMISSION` ở `codology.ledger`/`codology.relay`).

Replay chỉ idempotent khi dữ liệu intent không đổi, kể cả instance version của mọi ref. Sau commit, caller tự query lại sẽ nhận ref version mới nên `invoke` cùng key bị từ chối; `reconcile`/`reconcile_execution` với key/id gốc vẫn trả execution đã lưu. `examples/break_glass_access/consumer.py` giữ ref gốc để chứng minh replay; CLI ở đoạn dưới không làm vậy, nên sau commit phải dùng `reconcile`.

Consumer mẫu đầy đủ là `examples/conditional_approval/consumer.py`; dùng các hàm đó làm mốc để viết CLI của riêng bạn, nhưng **không import** consumer mẫu trong sản phẩm mới. [`examples/purchase_order_cli/`](../examples/purchase_order_cli/README.md) là CLI độc lập đã chạy được: dùng lại host contract của ví dụ Sprint 5, gọi trực tiếp các cổng công khai ở trên và in một JSON envelope cho mỗi lệnh; `callback_key`/`intent_fingerprint` chỉ được chuyển tiếp, không tự sinh.

## 8. Đối chiếu thiết kế pseudocode với runtime

| Trong design doc | API/evidence đang chạy |
| --- | --- |
| `engine.query(...)` | import root `from codology import query`; provider SQLite thật |
| `ObjectRef[T]` như giá trị runtime | `ObjectRef[T]` là annotation contract; caller nhận `VersionedRef` từ `row.as_ref()`, handler nhận `ResolvedObject[T]` (dùng `.ref` khi cần typed ref) |
| `Duration(value, "min")`, `comparisonUnit`, FX/quote | Không có API runtime; dùng `int` phút trong property và literal trong predicate; không hứa chuyển đổi đơn vị |
| `Link[...]` traversal `internal`, `Function` query | `Link` chỉ là metadata tĩnh; `query(traverse=...)` của SQLite adapter từ chối traversal chưa có conformance; không có runtime Function lookup |
| `ctx.delegation` descriptor | Không có thuộc tính này; `HandlerCtx` có `principal`, `reads`, `writes`, `calls`, `uow`, `require`, `resolve`, `call` |
| `EffectContractUnsupported` | Binding ném `MissingCapability` / `EffectSessionMismatch` khi thiếu outbox hoặc dedup |
| `result.execution.requiredApproval.role` | Field runtime là `required_approval`; đọc `callback_key`, `intent_fingerprint`, `role` từ dataclass `RequiredApproval` |
| `BastionCertPayload(...)` làm payload | Dùng `payload_of(PayloadValue, **fields)` rồi `ctx.uow.enqueue_effect(Effect, payload=...)` |

Bảng [§3.7 của cross-domain design](official/design/evolution-and-cross-domain.md) chứng minh **hình dạng khai báo** tái dùng được; nó không chứng minh mọi pseudocode ở §3 là API runtime. Ca mới chỉ được dùng các API có trong mục 3–7 ở trên.

## 9. Chẩn đoán theo pha và lệnh kiểm chứng

| Triệu chứng | Pha | Nguyên nhân / sửa |
| --- | --- | --- |
| `UnknownDeclarationKey`, `DuplicateIdentity` | Load | Field lạ trong thân class, identity trùng hoặc thiếu identity/version của module; sửa declaration |
| `UnresolvedReference`, `WrongKind`, `NotExported`, `ObjectRefMismatch`, `HandlerMismatch` | Link | Sai tên/kind, definition không export, handler sai kiểu/param; error kèm `module`, `identity`, `field` |
| `UnsupportedApprovalExpression` | Declaration | Predicate có lambda/method call/số học; viết lại bằng `Param` + comparison + `all_of`/`any_of`/`not_` |
| `MissingCapability`, `UnboundWrite`, `NoSharedTransaction`, `EffectSessionMismatch` | Binding | Provider thiếu capability, quên enlist child write/outbox, hoặc session khác nhau; sửa `Deployment` |
| `SessionMismatch`, `UnknownResource`, `InvalidColumn` | Runtime adapter | Provider mở session khác plan, resource chưa map, cột không tồn tại; sửa wiring/schema |
| `DENIED` / `KEY_MISUSE` | Invoke/callback | Thiếu permission live, grant tenant/scope, key/fingerprint lệch; không đổi execution đang chờ |
| `StalePlan` | Invoke/resume | Version/guard đã đổi; đọc lại và recompute, không ghi đè |
| `UNKNOWN` | Invoke/resume | Commit không xác nhận; đối soát bằng `reconcile`/`reconcile_execution` trước khi retry |

Lệnh kiểm trọng điểm (chạy từ gốc repo; các lệnh bên dưới phải exit 0, riêng Pyright toàn repo xem ghi chú sau khối lệnh):

```bash
uv run python -m examples.procurement_finance
uv run python -m examples.atomic_approval
uv run python -m examples.conditional_approval
uv run python -m examples.break_glass_access
uv run python -m examples.break_glass_access --runtime
uv run pytest -q tests/test_loading.py tests/test_linking.py tests/test_manifest.py tests/test_binding.py
uv run pytest -q tests/test_atomic_approval_example.py tests/test_conditional_approval_example.py
uv run pytest -q tests/test_break_glass_access_example.py tests/test_break_glass_access_runtime.py tests/test_purchase_order_cli.py
uv run pyright examples/break_glass_access examples/purchase_order_cli \
  tests/test_break_glass_access_example.py tests/test_break_glass_access_runtime.py tests/test_purchase_order_cli.py
# uv run pyright  # toàn repo còn 22 lỗi cũ, không dùng làm gate; xem ghi chú dưới
uv run ruff check .
uv run ruff format --check .
```

`uv run pyright` toàn repo hiện trả **22 lỗi có từ trước** trong `src/codology/` (`engine.py`, `money.py`, `outbox.py`, `uow.py`) và `tests/resume_support.py`, `tests/test_outbox.py`; lệnh Pyright giới hạn ở trên trả 0 errors cho ví dụ và test mới. Không sửa lõi hay test cũ để che các lỗi này. `ruff check .` và `ruff format --check .` phải sạch, kể cả code block Python trong tệp Markdown.

`uv run python -m examples.conditional_approval` in `ALL CHECKS PASSED`; các mốc quan sát được gồm `COMMITTED` dưới ngưỡng, `AWAITING_APPROVAL` tại ngưỡng mà `outbox` vẫn 0 hàng, replay sau đổi default vẫn cùng execution, callback outsider/`KEY_MISUSE` không chiếm key, `resume` commit hai phần ghi + outbox, và relay chỉ giao sau commit. `tests/test_conditional_approval_example.py` đối chiếu từng kết quả API bằng connection SQLite độc lập — dùng cách đó cho nghiệp vụ mới.

Đối chiếu chữ ký trực tiếp khi nghi ngờ tài liệu lỗi thời:

```bash
uv run python - <<'PY'
import inspect
from codology import query
from codology.binding import bind_action
from codology.decision import approve
from codology.engine import invoke
from codology.resume import resume
for fn in (query, invoke, approve, resume, bind_action):
    print(fn.__module__ + "." + fn.__name__, inspect.signature(fn))
PY
```

## 10. Checklist bàn giao cho task kế

1. Tạo module nghiệp vụ mới theo mục 3–4; identity/version tường minh, role/ngưỡng/payload là literal của miền, effect chỉ ghi sink local. Không import nghiệp vụ Procurement/Finance, không sửa `src/codology/`.
2. Test tĩnh: `load` → `link` → `snapshot`, kiểm identity/version, cạnh child/effect, ownership/export, và một lỗi reference không export; handler không được gọi.
3. Host: schema/seed + `ResourceBinding` cho hai phần ghi, `Deployment` với một session chung cho hai write và outbox, delegation đúng `calls`/`permission`; test binding tách session bị từ chối.
4. Runtime: DB riêng mỗi ca, đi qua `query → as_ref → invoke → approve → resume → reconcile → relay`; đọc lại business/version/ledger/outbox bằng connection độc lập lúc chờ và sau commit.
5. Ghi lại mọi chỗ phải đoán, lệnh đã chạy và kết quả thực tế. Nếu capability dùng chung thiếu, dừng và báo blocker kèm ca tối thiểu — không tự thêm API lõi.
6. Nếu caller là CLI độc lập, dùng lại host contract và gọi thẳng các cổng công khai như `examples/purchase_order_cli/`; sau commit hãy `reconcile` bằng key/id gốc thay vì query lại ref rồi `invoke`.

## 11. Liên kết

- [README](../README.md) — api, ví dụ và non-claims tổng hợp.
- [Ví dụ Sprint 5 chạy được](../examples/conditional_approval/README.md) — mốc runtime cho mọi bước ở mục 5–7.
- [Ví dụ nấc 2](../examples/atomic_approval/README.md) — regression đường đồng bộ.
- [Ví dụ đa miền chạy được](../examples/break_glass_access/README.md) — Load/Link/Snapshot, binding một session và các nhánh runtime.
- [CLI consumer độc lập](../examples/purchase_order_cli/README.md) — hợp đồng `ApprovePurchaseOrder` từ tiến trình riêng.
- [Bằng chứng bàn giao](../artifacts/sprint-6/tasks/S6-T5-A1.md) — lệnh, kết quả và giới hạn đã kiểm chứng.
- [Ví dụ tĩnh Procurement/Finance](../examples/procurement_finance/README.md) — Load/Link/snapshot và sáu lỗi tĩnh.
- [Developer Contract](official/design/developer-contract.md), [Consumer Contract](official/design/consumer-contract.md), [Evolution & Cross-Domain Validation](official/design/evolution-and-cross-domain.md), [Implementation Baseline](official/design/implementation-baseline.md).
