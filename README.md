# Codology

Codology (Ontology as Code) là lớp mô hình tĩnh cho phép developer khai báo thực thể, quan hệ và hành vi nghiệp vụ bằng Python, rồi kiểm tra mô hình trước khi kết nối backend. Package Python gốc là `codology`; OaC là tên khái niệm, không phải tên package.

## Trạng thái

Repository đang ở Sprint 4 — Lát cắt thực thi nguyên tử. Phần đã có là project scaffold, hạ tầng khai báo tĩnh, deployment binding ở mức plan và adapter SQLite cho transaction vật lý với guarded write:

- `codology` import được từ môi trường sạch, không cần database, credential hay backend SDK.
- `codology.declarations` cung cấp primitive cấu trúc bất biến `Module`, `ObjectType`, `Value`, `Link` và `ObjectRef[T]`: identity/version tường minh, property có kiểu, link có target/cardinality/traversal và `exports` đóng băng.
- `codology.declarations` cung cấp `Action`, `Function`, `Effect` và predicate approval cấu trúc: `params`, `reads`/`writes`/`calls`, `permission`, `commitRequirement`, `approval` và `effects` được đóng băng lúc khai báo; không chạy handler hay đánh giá predicate.
- Load, Link và `snapshot()` đã được triển khai; snapshot công bố graph đã link dưới dạng bất biến, tra cứu tường minh theo identity/version.
- Ví dụ Procurement/Finance chạy được trên API thật (`examples/procurement_finance/`) cùng kiểm thử tích hợp và kiểm tra typing cho cả đường thành công lẫn lỗi tĩnh.
- `bind_action()` kiểm tra deployment plan cho action `ATOMIC`: capability của provider, write set bắc cầu qua `calls`, một session enlist chung và mapping ủy quyền không rộng hơn contract; không gọi handler và không mở transaction.
- `codology.adapter` mở đúng một transaction SQLite vật lý cho mọi write đã bind; `commit_guarded_writes()` là biên commit do engine/port sở hữu, rollback sạch trước commit và chỉ coi `rowcount == 1` là thành công. Tiền được biểu diễn bằng số nguyên đơn vị nhỏ (`MinorMoney`) với một currency cố định, không FX.
- Engine `query`/`invoke`, authorization runtime, sổ yêu cầu bền vững và publish artifact **chưa được triển khai**; các task sau trong sprint bổ sung dần.

## Yêu cầu

- Python 3.13 (pin trong `.python-version`).
- [uv](https://docs.astral.sh/uv/) để quản lý môi trường và dependency.

## Cài đặt và tái lập

```bash
uv sync
```

Lệnh trên tạo `.venv`, cài package ở chế độ editable và cài nhóm dependency `dev` (pytest, Pyright, Ruff).

## Chạy kiểm tra

```bash
uv run python -c "import codology; print(codology.__version__)"
uv run python -m examples.procurement_finance
uv run pytest
uv run pyright
uv run ruff check .
uv run ruff format --check .
```

## Cấu trúc

```text
src/codology/
  __init__.py
  py.typed
  loading.py        # Load: thu thập definition, kiểm tra identity và field
  linking.py        # Link: resolve reference, export, kind và chữ ký handler
  snapshot.py       # Snapshot: graph đã link bất biến, lookup identity/version
  binding.py        # Deployment binding: capability, write set, enlistment plan
  money.py          # MinorMoney: số nguyên đơn vị nhỏ, một currency
  ports.py          # Port lõi: guarded write, transaction, kết quả apply
  uow.py            # Biên commit do engine/port sở hữu
  adapter.py        # Adapter SQLite: một session, một transaction vật lý
  declarations/
    __init__.py
    annotations.py   # giữ annotation thô, resolve ở pha Link
    behavior.py      # Action/Function/Effect và governance metadata
    handler.py       # quy ước handler duy nhất
    primitives.py    # Module/ObjectType/Value/Link/ObjectRef bất biến
examples/procurement_finance/
  common.py          # Money, Value cấu trúc dùng chung
  finance.py         # Budget, ReserveBudget, Finance
  procurement.py     # PurchaseOrder, effect, ApprovePurchaseOrder, Procurement
  model.py           # ghép nhóm, load/link/snapshot
  scenarios.py       # sáu ca lỗi tĩnh có thể chạy
  __main__.py        # entry point của ví dụ
tests/
  test_annotations.py
  test_behavior.py
  test_binding.py
  test_transaction.py # rollback, guard/version, rowcount, tranh chấp hai connection
  test_declarations.py
  test_handler.py
  test_linking.py
  test_loading.py
  test_package.py
  test_procurement_finance_integration.py
  test_snapshot.py
  typing/
    valid_api.py     # assert_type cho bề mặt công khai
    invalid_api.py   # lỗi kiểu có chủ đích, mỗi ignore phải cần thiết
```

## Khai báo cấu trúc

```python
from decimal import Decimal

from codology.declarations import Link, Module, ObjectRef, ObjectType, Value


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
    budget = Link[Budget, "one", "navigable"]


class Procurement(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder,)


order_ref = ObjectRef[PurchaseOrder]
```

Identity và version phải được khai báo tường minh, không suy từ tên class. Class khai báo và các collection đầu vào (`exports`, `links`, annotation) được sao chép và đóng băng lúc tạo; sửa chúng sau đó không làm đổi declaration. `exports` là ranh giới sở hữu, không phải quyền truy cập; việc kiểm tra reference liên module thuộc pha Link (chưa triển khai).

## Khai báo hành vi và governance

`Action` khai báo `params` (annotation có kiểu), `reads`, `writes`, `permission` và `handler(self, ctx, ...)`; `Function` là view chỉ đọc có `result`. Các nấc sau chỉ **thêm** thuộc tính: `calls` và `commitRequirement = CommitRequirement.ATOMIC` (liên module), rồi `approval` và `effects` (duyệt có điều kiện, effect sau commit). `Effect` khai `payload` (một `Value`) và `dedupKey` tùy chọn.

```python
from codology.declarations import (
    Action,
    Approval,
    Effect,
    ObjectRef,
    Param,
    Value,
)


class OrderApprovedPayload(Value):
    order: ObjectRef[PurchaseOrder]
    approved_amount: Money


class NotifyWarehouseOrderApproved(Effect):
    identity = "procurement.warehouse_order_approved"
    version = "1.0.0"
    payload = OrderApprovedPayload
    dedupKey = ("order",)


class ApprovePurchaseOrder(Action):
    identity = "procurement.approve_purchase_order"
    version = "1.0.0"
    order: ObjectRef[PurchaseOrder]
    reason: str
    reads = (PurchaseOrder,)
    writes = (PurchaseOrder,)
    permission = "purchase_order.approve"

    def handler(self, ctx, order: PurchaseOrder, reason: str) -> None: ...


approval = Approval.conditional(
    when=Param("order").normalized_amount >= 100_000,
    role="finance_director",
    self_approval=False,
)
```

`when` chỉ nhận predicate cấu trúc: so sánh `>`, `>=`, `<`, `<=`, `==`, `!=` và `all_of`/`any_of`/`not_` (hoặc `.and_`/`.or_`/`.not_`). Lambda, phép toán số học và method call bị từ chối ngay lúc khai báo, kèm tên biểu thức không được hỗ trợ. `>` và `>=` là hai toán tử khác nhau trong predicate. Khai báo không đánh giá predicate trên dữ liệu thật, không gọi handler và không giao effect.

## Load: thu thập và kiểm tra declaration

`load` nhận một hoặc nhiều `ModuleDeclarations`: mỗi nhóm gồm một `Module` và mọi definition mà module đó sở hữu, kể cả definition không nằm trong `exports`. Kết quả là `LoadedDeclarations` bất biến với ánh xạ module và definition theo identity đã khai báo.

```python
from codology import ModuleDeclarations, load

loaded = load(
    ModuleDeclarations(Procurement, [PurchaseOrder, ApprovePurchaseOrder]),
    ModuleDeclarations(Finance, [Budget, ReserveBudget]),
)
reserved = loaded.definitions["finance.reserve_budget"]
assert reserved.owner == "finance" and reserved.version == "1.0.0"
```

Load từ chối identity trùng (`DuplicateIdentity`) và field khai báo không hợp lệ (`UnknownDeclarationKey`). Cả hai lỗi đều kèm module, identity và field để author sửa; một field gõ nhầm trong thân class bị từ chối thay vì bị bỏ qua. Identity luôn lấy từ `identity` đã khai báo, không suy từ tên class: hai class cùng tên `Budget` nhưng identity khác nhau load được bình thường, và `Value` không khai identity giữ `identity = None`. Collection đầu vào được sao chép tại Load; sửa chúng sau đó không làm đổi kết quả.

Load **không** resolve reference, kiểm tra export hay gọi handler; các việc đó thuộc Link.

## Link: resolve và kiểm tra ranh giới module

`link` nhận `LoadedDeclarations` từ Load và trả `LinkedDeclarations` bất biến: mỗi definition có annotation đã resolve, chữ ký handler đã đối chiếu và các cạnh reference đã kiểm tra. Namespace được compose từ mọi definition tham gia link, nên hai module có thể tham chiếu kiểu của nhau bằng forward annotation mà không import vòng lúc chạy.

```python
from codology import ModuleDeclarations, link, load

linked = link(
    load(
        ModuleDeclarations(Procurement, [PurchaseOrder, ApprovePurchaseOrder]),
        ModuleDeclarations(Finance, [Budget, ReserveBudget]),
    )
)
approve = linked.definitions["procurement.approve_purchase_order"]
assert approve.hints["order"].target is PurchaseOrder
```

Link từ chối reference không tồn tại (`UnresolvedReference`), đích sai loại (`WrongKind`), definition liên module chưa export (`NotExported`), `ObjectRef[T]` không khớp (`ObjectRefMismatch`) và handler sai quy ước/tham số (`HandlerMismatch`). Mỗi lỗi kèm module, identity và field để author sửa. Link chỉ đọc annotation và chữ ký: không gọi handler, không suy dependency từ thân handler và không cần provider hay credential.

## Snapshot: graph đã link dưới dạng bất biến

`snapshot()` nhận `LinkedDeclarations` và trả `Snapshot` bất biến, tách khỏi class khai báo. Sửa collection đầu vào hoặc collection lấy ra từ snapshot không làm đổi dữ liệu đã công bố. Tra cứu luôn cần identity **và** version; không có `latest` hay fallback theo identity.

```python
from codology import DefinitionKey, link, load, snapshot

published = snapshot(
    link(
        load(
            ModuleDeclarations(Procurement, [PurchaseOrder, Money, ApprovePurchaseOrder]),
            ModuleDeclarations(Finance, [Budget, ReserveBudget]),
        )
    )
)
entry = published.lookup("finance.reserve_budget", "1.0.0")
assert entry.owner == "finance" and entry.kind == "Action"
assert published.versions_of("finance.reserve_budget") == ("1.0.0",)
assert DefinitionKey("finance.reserve_budget", "1.0.0") in published.entries
```

Mỗi `SnapshotEntry` có `dependencies` (cạnh `calls`/`reads`/`writes`/`params`/`links`/`effects` kèm identity, version và owner của đích) và `approval` dạng cây biểu thức bất biến. `ComparisonExpr.operator` giữ nguyên toán tử nên consumer phân biệt được `>` và `>=`, kể cả trong `all_of`/`any_of`/`not_`. Key tra cứu lấy từ identity đã khai báo: đổi tên class host không làm đổi identity hay lookup.

Snapshot **không** công bố handler digest: sprint này chưa định nghĩa bytes và phạm vi của digest, nên không có hash tùy ý nào được gọi là digest artifact publish. Snapshot không kéo theo engine, authorization hay execution.

## Deployment binding: kiểm tra plan cho `ATOMIC`

`bind_action()` ghép một action version cụ thể trong `Snapshot` với `Deployment` gồm `Provider`, `Enlistment` và `DelegationGrant`. Đây là kiểm tra **plan**: không gọi handler, không mở transaction và không chứng minh session vật lý đang mở. Runtime vẫn phải xác nhận transaction thật trước khi commit.

```python
from codology import (
    Capability,
    DefinitionKey,
    DelegationGrant,
    Deployment,
    Enlistment,
    Provider,
    bind_action,
)

deployment = Deployment(
    providers=(Provider("orders-db", "sqlite", frozenset({Capability.ATOMIC_TRANSACTION})),),
    enlistments=(
        Enlistment("procurement.purchase_order", "orders-db", "sqlite:main"),
        Enlistment("finance.budget", "orders-db", "sqlite:main"),
    ),
    delegations=(
        DelegationGrant(
            caller="procurement.approve_purchase_order",
            call="finance.reserve_budget",
            permission="budget.reserve",
        ),
    ),
)
bound = bind_action(
    published,
    deployment,
    DefinitionKey("procurement.approve_purchase_order", "2.0.0"),
)
assert bound.session is not None
assert bound.session.session == "sqlite:main"
assert {write.resource.identity for write in bound.writes} == {
    "procurement.purchase_order",
    "finance.budget",
}
```

Binding kiểm tra bốn điều:

- Provider của mọi write bắt buộc phải khai báo `Capability.ATOMIC_TRANSACTION` khi action hoặc một child reachable qua `calls` có `commitRequirement = CommitRequirement.ATOMIC`; thiếu thì `MissingCapability`.
- Write set là **bắc cầu**: `writes` của action cộng `writes` của mọi action/function reachable qua `calls`. Resource chưa enlist bị `UnboundWrite`, kể cả write chỉ do child khai báo.
- Mọi write bắt buộc phải cùng một `Enlistment.session`. Hai enlistment độc lập — dù cùng provider kind hay cùng nhãn DB — bị `NoSharedTransaction`; cùng session label do hai provider khai báo bị `InconsistentSession`.
- `DelegationGrant` là tùy chọn, nhưng nếu có cho một caller reachable thì phải khớp một call `Action` đã khai báo (`UndeclaredCall`), dùng principal `requester` chứ không phải service identity (`AmbientServiceIdentity`), và lặp đúng `permission` của child (`PermissionBroadened`). Không có grant nghĩa là engine dùng quyền live của requester; grant không thể mở rộng quyền.

`BoundAction` trả `writes` kèm `via` (đường đi từ root qua `calls`), `calls`, `delegations` và `session` — plan một session dùng cho UoW. Metadata `ATOMIC` đã bind **không** chứng minh backend đáp ứng atomicity; phần đó thuộc adapter và kiểm chứng runtime.

## Transaction vật lý và guarded write

`SQLiteProvider` là adapter file-backed cho đúng một session đã bind. `commit_guarded_writes()` mở một `BEGIN IMMEDIATE` trên một connection, áp dụng mọi `GuardedWrite` trên connection đó rồi commit **một lần**; bất kỳ lỗi nào trước commit đều rollback. Handler không nhận được `commit`/`rollback` và không thấy connection.

```python
from decimal import Decimal

from codology import bind_action  # plan = SessionPlan từ bind_action()
from codology.adapter import ResourceBinding, SQLiteProvider
from codology.money import MinorMoney
from codology.ports import Assignment, Condition, GuardedWrite
from codology.uow import commit_guarded_writes

amount = MinorMoney.from_decimal(Decimal("40000"), "VND")
provider = SQLiteProvider(
    "orders.sqlite3",
    "sqlite:main",
    (
        ResourceBinding("finance.budget", "budgets", ("balance",), currency="VND"),
        ResourceBinding(
            "procurement.purchase_order", "purchase_orders",
            ("status", "approved_amount"), currency="VND",
        ),
    ),
)
results = commit_guarded_writes(
    provider,
    plan,
    (
        GuardedWrite(
            "finance.budget", "B-001", 1,
            (Assignment("balance", "add", -amount),),
            (Condition("balance", ">=", amount),),
        ),
        GuardedWrite(
            "procurement.purchase_order", "PO-001", 1,
            (
                Assignment("status", "set", "APPROVED"),
                Assignment("approved_amount", "set", amount),
            ),
            (Condition("status", "==", "PENDING_APPROVAL"),),
        ),
    ),
)
assert all(result.rowcount == 1 for result in results)
```

Mỗi guarded write gồm `expected_version`, phép gán và điều kiện; adapter thêm guard `version = expected_version` và tăng version trong cùng một `UPDATE`. `rowcount != 1` ném `StalePlan` và không ghi đè. Adapter chỉ nhận `int`, `str`, `bytes`, `None` và `MinorMoney` — `float`/`Decimal` thô bị từ chối; `MinorMoney` được kiểm currency theo resource. Tiền lưu dưới dạng số nguyên đơn vị nhỏ, một currency cho ví dụ; không quy đổi, không FX. Tên bảng và cột phải là identifier thường, được khai báo trong `ResourceBinding`.

Đây là bằng chứng cơ chế trên SQLite file và **một** interleaving có điều khiển, không phải chứng minh mọi lịch chạy hay hành vi PostgreSQL/ERP. Session được xác nhận lúc mở transaction (`SessionMismatch` nếu plan trỏ session khác); ledger, authorize và handler vẫn thuộc task sau.

## Ví dụ Procurement/Finance

`examples/procurement_finance/` là ví dụ chạy được trên chính API công khai ở trên: hai module Procurement và Finance, `ApprovePurchaseOrder` gọi `finance.reserve_budget`, kèm approval và effect metadata. Chạy từ gốc repo:

```bash
uv run python -m examples.procurement_finance
```

Ví dụ in đường Load → Link → Snapshot rồi sáu lỗi tĩnh: `DuplicateIdentity` (Load), `NotExported`, `UnresolvedReference`, `ObjectRefMismatch`, `HandlerMismatch` (Link) và `UnsupportedApprovalExpression` (declaration). `tests/test_procurement_finance_integration.py` kiểm tra lại toàn bộ đường đi và output của entry point; `tests/typing/valid_api.py` ghim kiểu công khai, còn `tests/typing/invalid_api.py` đảm bảo Pyright vẫn bắt các lỗi kiểu có chủ đích.

Không cần backend: handler chỉ là metadata và không được gọi. Hướng dẫn chạy, lỗi và non-claims chi tiết nằm ở [`examples/procurement_finance/README.md`](examples/procurement_finance/README.md).

## Quyết định đã chốt

- **Một quy ước handler duy nhất:** `def handler(self, ctx, ...)` trên class khai báo. `@staticmethod def handle(...)` không được hỗ trợ; không có API thứ hai để giữ đồng bộ. `self` không mang execution state.
- **Forward reference không import vòng:** annotation được giữ nguyên dạng viết lúc tạo class và chỉ resolve ở pha Link bằng namespace đã compose từ mọi module tham gia link. Hai module có thể tham chiếu kiểu của nhau mà không import nhau lúc chạy.
- **Layout và công cụ:** source đặt trong `src/codology/`, đóng gói bằng Hatchling, quản lý bằng uv; kiểm thử bằng pytest; type-check bằng Pyright strict; lint/format bằng Ruff.
- **Adapter và tiền chính xác:** SQLite file-backed, một session vật lý cho mọi write đã bind; `MinorMoney` lưu số nguyên đơn vị nhỏ với một currency, không float và không FX.
- Chi tiết và hệ quả cho các task sau: [`docs/official/design/implementation-baseline.md`](docs/official/design/implementation-baseline.md).

## Giới hạn

- Đây vẫn là lớp mô hình tĩnh, deployment binding plan-check và adapter transaction có guarded write. Chưa có engine `query`/`invoke`, authorization, UoW cho handler, sổ yêu cầu/kết quả hay effect delivery.
- Load đã thu thập definition và kiểm tra identity/field; Link đã resolve reference, kiểm tra export/kind và chữ ký handler; snapshot đã công bố graph bất biến với lookup tường minh; `bind_action()` đã kiểm tra capability, write set và enlistment plan trên snapshot. Adapter transaction thật đã có; registry bền vững và publish artifact thuộc các task kế tiếp.
- Predicate approval chỉ được lưu dạng cấu trúc; chưa có đánh giá ngưỡng, callback duyệt hay giao effect. `Function` dùng cùng quy ước `handler(self, ctx, ...)` với `Action` theo implementation baseline.
- Không có tuyên bố engine `query`/`invoke`, authorization hay execution đã hoạt động. Adapter chứng minh một transaction vật lý và guard trên SQLite; binding vẫn chỉ là plan-check, không thay cho runtime proof trên backend khác. Bằng chứng chỉ phủ các interleaving đã kiểm (rollback, guard, tranh chấp hai connection), không phải mọi lịch chạy, PostgreSQL/ERP hay mất phản hồi sau commit (sổ kết quả thuộc task sau).
- Static validation không phát hiện truy cập ẩn trong thân handler (import lén, `getattr` động, đọc file/socket). Binding chỉ kiểm tra mapping khai báo; nó không phát hiện host code tự mở connection hoặc dùng credential ambient ngoài plan và không sandbox handler. Đó là rủi ro đã ghi nhận, xử lý bằng review và test.

## Tài liệu

- [Sprint 4 plan](docs/sprint-plans/sprint-4.md)
- [Implementation baseline](docs/official/design/implementation-baseline.md)
- [Developer Contract](docs/official/design/developer-contract.md)
- [Framework Design v0.1](docs/official/design/framework-design-v0.1.md)
