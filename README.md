# Codology

Codology (Ontology as Code) là framework khai báo thực thể, quan hệ và hành vi nghiệp vụ bằng Python. Mô hình được kiểm tra trước khi kết nối backend; engine nhúng chạy lát cắt thực thi nguyên tử đầu tiên trên SQLite. Package Python gốc là `codology`; OaC là tên khái niệm, không phải tên package.

## Trạng thái

Sprint 4 đã hoàn tất với lát cắt thực thi nguyên tử đồng bộ. [Sprint 5](docs/sprint-plans/sprint-5.md) mới ở giai đoạn lập kế hoạch cho chờ/resume approval và thông báo sau commit. Các phần đã có:

- `codology` import được từ môi trường sạch, không cần database, credential hay backend SDK.
- `codology.declarations` cung cấp primitive cấu trúc bất biến `Module`, `ObjectType`, `Value`, `Link` và `ObjectRef[T]`: identity/version tường minh, property có kiểu, link có target/cardinality/traversal và `exports` đóng băng.
- `codology.declarations` cung cấp `Action`, `Function`, `Effect` và predicate approval cấu trúc: `params`, `reads`/`writes`/`calls`, `permission`, `commitRequirement`, `approval` và `effects` được đóng băng lúc khai báo; không chạy handler hay đánh giá predicate.
- Load, Link và `snapshot()` đã được triển khai; snapshot công bố graph đã link dưới dạng bất biến, tra cứu tường minh theo identity/version.
- Ví dụ Procurement/Finance chạy được trên API thật (`examples/procurement_finance/`) cùng kiểm thử tích hợp và kiểm tra typing cho cả đường thành công lẫn lỗi tĩnh.
- Ví dụ thực thi (`examples/atomic_approval/`) chạy đường consumer `query → row.as_ref() → invoke` nấc 2 trên adapter SQLite thật: commit đơn và giữ ngân sách trong một transaction, replay theo `request_key`, cùng các nhánh read/invoke denial và split binding. Kiểm thử tích hợp đọc lại dữ liệu bằng connection độc lập.
- `bind_action()` kiểm tra deployment plan cho action `ATOMIC`: capability của provider, write set bắc cầu qua `calls`, một session enlist chung và mapping ủy quyền không rộng hơn contract; không gọi handler và không mở transaction.
- `codology.adapter` mở đúng một transaction SQLite vật lý cho mọi write đã bind; `commit_guarded_writes()` là biên commit do engine/port sở hữu, rollback sạch trước commit và chỉ coi `rowcount == 1` là thành công. Mỗi unit đóng connection khi transaction kết thúc (sau commit, rollback hoặc `close()`), và `SQLiteProvider` nhận `timeout` giây cho việc acquire lock. Tiền được biểu diễn bằng số nguyên đơn vị nhỏ (`MinorMoney`) với một currency cố định, không FX.
- Cửa `engine.query` (hàm `query()`) authorize principal/grant trước khi đọc, chỉ nhận predicate có pushdown đã kiểm chứng, áp tenant/scope ở adapter trước phân trang/count và phát hành ref có type/version từ row. `invoke()` chạy một handler đã khai báo sau khi kiểm quyền ghi live, resolve lại ref theo scope hiện tại, cấp `HandlerCtx` hẹp, revalidate rồi commit một transaction duy nhất cùng bản ghi ledger; publish artifact **chưa được triển khai**.

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
uv run python -m examples.atomic_approval
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
  query.py          # Đọc có policy: authorize, pushdown, cursor, count, typed ref
  engine.py         # Invoke: authorize, scoped resolve, HandlerCtx, scoped UoW
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
  __main__.py        # entry point của ví dụ tĩnh
  runtime.py         # contract nấc 2 riêng cho child action, không approval/effect
examples/atomic_approval/
  database.py        # schema SQLite và dữ liệu seed hai tenant
  wiring.py          # graph, deployment plan, adapter, principal và read grant
  consumer.py        # query -> row.as_ref() -> invoke, không chép luật nghiệp vụ
  __main__.py        # entry point chạy consumer trên DB thật
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
  test_atomic_approval_example.py # commit, denial, split binding, rollback, race, replay
  test_snapshot.py
  test_invoke.py     # DENIED/REJECTED/StalePlan, ref scope, ctx hẹp, commit/rollback
  test_child_action.py # child đã link, ủy quyền, scope, rollback, một transaction
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
        ResourceBinding("finance.budget", "1.0.0", "budgets", ("balance",), currency="VND"),
        ResourceBinding(
            "procurement.purchase_order", "1.0.0", "purchase_orders",
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

## Đọc có policy và typed ref

`query()` là cửa đọc duy nhất: kiểm grant của principal, từ chối predicate không có pushdown đã kiểm chứng, rồi giao cho adapter áp tenant/scope trong cùng `WHERE` dùng cho rows và count. Cursor là token mờ gắn với definition, grant, predicate và sort; dùng lại cursor ở tenant/key/intent khác bị từ chối. Order bằng một cột tường minh và luôn có khóa làm tie-break, nên phân trang ổn định. Không có `list_raw`, `count_unfiltered` hay đường đọc trực tiếp bỏ qua cửa này.

```python
from codology import (
    Comparison,
    DefinitionKey,
    OrderBy,
    Principal,
    ReadGrant,
    query,
)
from codology.adapter import ResourceBinding, SQLiteProvider
from examples.procurement_finance.procurement import PurchaseOrder

definition = DefinitionKey("procurement.purchase_order", "1.0.0")
provider = SQLiteProvider(
    "orders.sqlite3",
    "sqlite:main",
    (
        ResourceBinding(
            "procurement.purchase_order", "1.0.0", "purchase_orders",
            ("status", "approved_amount"),
            tenant_column="tenant", scope_column="scope",
        ),
    ),
)
principal = Principal("alice", "tenant-a", frozenset({"purchase_order.read"}))
grant = ReadGrant("alice", definition, "tenant-a", ("team-1",), "purchase_order.read")
page = query(
    provider=provider,
    principal=principal,
    grant=grant,
    from_=definition,
    target=PurchaseOrder,
    order=OrderBy("created_at"),
    predicate=Comparison("status", "==", "PENDING_APPROVAL"),
    limit=20,
    count_requested=True,
)
ref = page.rows[0].as_ref()  # VersionedRef[PurchaseOrder]: identity, version, instance_version
```

Tập được hỗ trợ trong adapter đầu: so sánh `==`, `!=`, `>`, `>=`, `<`, `<=` trên cột đã map và `all_of` của các so sánh đó; giá trị là `str`, `int`, `None` hoặc `MinorMoney`. Không hỗ trợ traversal (kể cả cạnh `internal`), predicate tổng quát, arithmetic hay postfilter không biên: mọi ca đó trả `UnsupportedSecureQuery` mà không trả row hay count. Đây là pushdown trung thực trên SQLite; chưa có nhánh bounded evaluation phía engine, chưa phải bằng chứng cho provider khác.

## Invoke đồng bộ và scoped UoW

`invoke()` là cửa ghi duy nhất: nó lấy graph đã Link, plan đã bind từ đúng graph đó, ref do `query()` phát hành và các grant đọc hiện tại. Trước khi chạy handler, engine kiểm quyền invoke live của principal, từ chối declaration có `approval`/`effects` mà synchronous invoke không thực hiện được, đối chiếu ref với kiểu tham số đã khai báo rồi resolve lại từng row qua cửa đọc theo tenant/scope. Ref tự dựng, ref sai kiểu, ref ngoài scope hoặc ref cũ đều không tới được handler.

```python
from codology import DefinitionKey, bind_action
from codology.engine import invoke

definition = DefinitionKey("procurement.purchase_order", "1.0.0")
ref = page.rows[0].as_ref()  # từ query() đã authorize ở trên
result = invoke(
    linked=linked,                 # kết quả link() của cùng graph
    action=DefinitionKey("procurement.approve_order", "1.1.0"),
    bound=bound,                   # bind_action(snapshot(linked), deployment, action)
    provider=provider,             # adapter vừa fetch/resolve vừa begin(plan)
    principal=principal,
    grants={definition: grant},
    parameters={"order": ref, "reason": "approved after budget check"},
)
assert result.attempt.code == "COMMITTED"
```

Handler chỉ nhận `HandlerCtx`: `principal` chỉ đọc, `reads`/`writes`/`calls` đúng khai báo, `require`, `resolve`, `call` và `uow.register_mutation`. Không có connection, credential, SQL, `commit` hay `rollback`; mutation chỉ được đăng ký trên object đã resolve và nằm trong write set đã bind. Engine revalidate version/scope trước khi commit rồi gọi `commit_guarded_writes()` trên đúng session đã bind: mọi write trong execution dùng chung một transaction vật lý, guard không khớp thì rollback toàn bộ.

`ActionResult` gồm `attempt` (`code`: `COMMITTED`, `DENIED`, `REJECTED` hoặc `StalePlan`), `execution` và kết quả các write. `DENIED` và `StalePlan` không tạo execution record và không đổi DB; `REJECTED` do `ctx.require` là outcome nghiệp vụ có record terminal; `COMMITTED` mang record kèm các mutation đã chấp nhận và danh sách child revision đã chạy. `ctx.call` chỉ dispatch khi đích nằm trong `calls`, có delegation grant đúng quyền của requester và tồn tại ở đúng revision đã link; gọi ngoài khai báo fail closed. Sổ request/result bền vững, replay theo `request_key` và effect vẫn nằm ngoài phạm vi cửa này.

Lỗi hạ tầng ở cửa giao dịch — provider không mở đúng session đã bind, `BEGIN IMMEDIATE` không lấy được lock trong `timeout`, hay commit không xác nhận được — trả `attempt.code = "UNKNOWN"` với `execution = None` và không có write result. Port phân biệt `TransactionUnavailable` (không mở/dùng được transaction, chưa commit) với `CommitOutcomeUnknown` (đã thử commit nhưng không rõ kết quả); engine không gộp chúng vào `DENIED`/`REJECTED`/`StalePlan` và không tự nhận đã rollback. Caller phải `reconcile` hoặc lookup ledger trước khi retry cùng `request_key`; exception không thuộc lớp hạ tầng này vẫn propagate.

## Child Action qua ủy quyền thu hẹp

`ctx.call("finance.reserve_budget", ...)` chỉ dispatch tới Action đã khai báo trong `calls` và đã link ở đúng identity/version. Engine kiểm delegation grant của requester, quyền live của child (`budget.reserve`) và resolve lại ref qua grant hiện tại; child nhận `HandlerCtx` riêng với `reads`/`writes` của chính nó nhưng dùng chung registration list, nên mọi write của cha và con nằm trong một `commit_guarded_writes()` duy nhất. Child `REJECTED` hoặc `DENIED` làm toàn bộ execution không commit; write trực tiếp từ Procurement vào `Budget` và call không khai báo đều fail closed.

```python
result = invoke(
    linked=linked,                    # graph nấc 2 của runtime.py
    action=DefinitionKey("procurement.approve_purchase_order", "1.1.0"),
    bound=bound,                      # delegation grant REQUESTER + budget.reserve
    provider=provider,
    principal=principal,              # cần purchase_order.approve và budget.reserve
    grants=grants,
    parameters={
        "order": order_ref,
        "budget": budget_ref,
        "reason": "approved after budget check",
        "amount": MinorMoney.from_decimal(Decimal("40000"), "USD"),
    },
)
assert result.attempt.code == "COMMITTED"
assert result.execution is not None
assert result.execution.children == (DefinitionKey("finance.reserve_budget", "1.0.0"),)
```

`examples/procurement_finance/runtime.py` là contract nấc 2 riêng, tách khỏi ví dụ tĩnh nấc 3 trong `procurement.py`: không `approval`, không `effects` và handler thật chạy được. `invoke` từ chối declaration nấc 3 thay vì bỏ qua metadata để chạy demo. `tests/test_child_action.py` kiểm revision đã link, export/call đã khai báo, quyền và scope của requester, rollback khi child từ chối và một transaction vật lý cho cả hai write.

## Sổ yêu cầu/kết quả đồng bộ bền

`invoke(..., request_key="...")` gắn một khóa có phạm vi `tenant / requester / action identity` với dấu vân tay intent do engine recompute từ action/version đã ghim và tham số đã canonicalize (ref mang type, definition version và row version; `MinorMoney` giữ currency và đơn vị nhỏ). Dấu vân tay không lấy thân handler. Engine mở transaction đã bind trước khi chạy handler để kiểm key ngay trong transaction đó: cùng key/intent thì trả kết quả đã lưu mà không chạy lại handler, còn key trùng nhưng intent khác bị `DENIED` với `reason="KEY_MISUSE"`. Bản ghi ledger, hai business write và ràng buộc duy nhất được commit cùng một lần; rollback không để lại hàng `COMMITTED`, và attempt bị từ chối không tạo execution record.

```python
result = invoke(..., request_key="tenant-A:alice:approve:PO-1:001")
replay = invoke(..., request_key="tenant-A:alice:approve:PO-1:001")
assert replay.execution is not None and replay.execution.deduplicated is True
```

Sau khi mất phản hồi, `reconcile(provider, principal, action, request_key)` đọc bản ghi bằng quyền `EXECUTION_READ_PERMISSION` trên một connection mới. Không có bản ghi đáng tin thì trả `UNKNOWN`, không suy `FAILED` và không gọi lại handler. Replay qua `invoke` vẫn kiểm quyền invoke live của requester; quyền đọc chỉ đủ để tra cứu. Khác tenant/principal/action không dùng chung kết quả.

`tests/test_request_ledger.py` kiểm một transaction cho ledger và hai write, rollback sạch, replay sau mất phản hồi không chạy handler lần hai, race cùng key, intent lệch, tách biệt scope và quyền đọc/ghi của bản ghi.

## Ví dụ thực thi query → ref → invoke

`examples/atomic_approval/` bàn giao đúng đường consumer trên adapter thật:

```bash
uv run python -m examples.atomic_approval
```

Ví dụ tạo một file SQLite mới, đọc đơn `PENDING_APPROVAL` qua `query`, lấy `VersionedRef[PurchaseOrder]` bằng `row.as_ref()`, rồi gọi `invoke` cho `ApprovePurchaseOrder@1.1.0`. Nó dùng contract nấc 2 trong `examples/procurement_finance/runtime.py`, không chạy declaration nấc 3. Handler của Procurement và Finance giữ toàn bộ luật nghiệp vụ; phần consumer chỉ có `query`, `as_ref` và `invoke`, không tự kiểm quyền, không tự tính ngân sách và không SQL.

Kết quả in ra gồm `COMMITTED` với hai write cùng một transaction id, replay cùng `request_key` với `deduplicated=True` và không giữ transaction sau replay, `reconcile` qua connection mới, và các nhánh `ReadDenied`, `UnsupportedSecureQuery`, invoke `DENIED` và `NoSharedTransaction`. Mọi kỳ vọng được assert, nên script thoát khác 0 nếu hành vi đổi.

`tests/test_atomic_approval_example.py` chạy chính các hàm consumer này rồi đọc lại DB bằng connection độc lập cho sáu nhóm: commit, read/invoke denial, split binding, rollback sau write đầu, hai đơn tranh một budget và replay sau mất phản hồi. Cách chạy, tập query được hỗ trợ và non-claims nằm ở [`examples/atomic_approval/README.md`](examples/atomic_approval/README.md).

## Ví dụ Procurement/Finance

`examples/procurement_finance/` là ví dụ chạy được trên chính API công khai ở trên: hai module Procurement và Finance, `ApprovePurchaseOrder` gọi `finance.reserve_budget`, kèm approval và effect metadata. Chạy từ gốc repo:

```bash
uv run python -m examples.procurement_finance
```

Ví dụ in đường Load → Link → Snapshot rồi sáu lỗi tĩnh: `DuplicateIdentity` (Load), `NotExported`, `UnresolvedReference`, `ObjectRefMismatch`, `HandlerMismatch` (Link) và `UnsupportedApprovalExpression` (declaration). `tests/test_procurement_finance_integration.py` kiểm tra lại toàn bộ đường đi và output của entry point; `tests/typing/valid_api.py` ghim kiểu công khai, còn `tests/typing/invalid_api.py` đảm bảo Pyright vẫn bắt các lỗi kiểu có chủ đích.

Không cần backend: handler chỉ là metadata và không được gọi. Declaration nấc 2 trong `runtime.py` không thuộc đường tĩnh này; nó được dùng bởi ví dụ thực thi `examples/atomic_approval/` và các test invoke/child. Hướng dẫn chạy, lỗi và non-claims chi tiết nằm ở [`examples/procurement_finance/README.md`](examples/procurement_finance/README.md).

## Quyết định đã chốt

- **Một quy ước handler duy nhất:** `def handler(self, ctx, ...)` trên class khai báo. `@staticmethod def handle(...)` không được hỗ trợ; không có API thứ hai để giữ đồng bộ. `self` không mang execution state.
- **Forward reference không import vòng:** annotation được giữ nguyên dạng viết lúc tạo class và chỉ resolve ở pha Link bằng namespace đã compose từ mọi module tham gia link. Hai module có thể tham chiếu kiểu của nhau mà không import nhau lúc chạy.
- **Layout và công cụ:** source đặt trong `src/codology/`, đóng gói bằng Hatchling, quản lý bằng uv; kiểm thử bằng pytest; type-check bằng Pyright strict; lint/format bằng Ruff.
- **Adapter và tiền chính xác:** SQLite file-backed, một session vật lý cho mọi write đã bind; `MinorMoney` lưu số nguyên đơn vị nhỏ với một currency, không float và không FX.
- **Đọc an toàn:** mọi row/count/cursor đi qua một cửa đã authorize; adapter SQLite chỉ nhận predicate có pushdown tương đương đã kiểm chứng, từ chối traversal `internal` và mọi traversal chưa có conformance thay vì lọc ngầm sau khi đọc.
- **Invoke một handler:** quyền ghi được kiểm live ở cửa engine, ref chỉ có giá trị khi resolve lại dưới grant hiện tại; `ctx.require` tạo `REJECTED`, xung đột version/guard tạo `StalePlan`, lỗi cửa tạo `DENIED` mà không tạo execution. Commit là quyết định của engine sau revalidate, không phải của handler.
- **Child action đã link:** `calls` và delegation grant được bind trước runtime; `ctx.call` chạy handler của đúng revision đã link với context thu hẹn theo `reads`/`writes` của child, dùng chung một UoW và một transaction. Child `REJECTED`/`DENIED` hủy toàn bộ execution; service identity và ref tự dựng không thay được requester.
- **Sổ yêu cầu bền vững:** scope key là `tenant / requester / action identity` (ổn định qua rollout version); dấu vân tay intent do engine recompute từ dữ liệu đã canonicalize, không phải digest handler. Key, intent và kết quả `COMMITTED` được ghi trong cùng transaction với mọi business write; replay trả kết quả cũ, còn tra cứu cần quyền đọc execution record.
- **Consumer mẫu trên adapter thật:** `examples/atomic_approval/` giữ phần caller chỉ ở `query`, `row.as_ref()` và `invoke`; quyền, ngân sách và write nằm trong declaration/handler và engine. Split binding nấc 2 (hai file cùng SQLite) vẫn bị từ chối trước runtime, không hạ xuống saga.
- Chi tiết và hệ quả cho các task sau: [`docs/official/design/implementation-baseline.md`](docs/official/design/implementation-baseline.md).

## Giới hạn

- Đây vẫn là lớp mô hình tĩnh, deployment binding plan-check, adapter transaction có guarded write, cửa đọc có policy, cửa ghi `invoke()` với child đã link và sổ yêu cầu/kết quả bền vững. `examples/atomic_approval/` chỉ là consumer mẫu trên SQLite một file; chưa có publish artifact, approval/effect hay effect delivery.
- Load đã thu thập definition và kiểm tra identity/field; Link đã resolve reference, kiểm tra export/kind và chữ ký handler; snapshot đã công bố graph bất biến với lookup tường minh; `bind_action()` đã kiểm tra capability, write set và enlistment plan trên snapshot. Adapter transaction thật đã có; chưa có registry bền vững hay publish artifact.
- Predicate approval chỉ được lưu dạng cấu trúc; chưa có đánh giá ngưỡng, callback duyệt hay giao effect. `Function` dùng cùng quy ước `handler(self, ctx, ...)` với `Action` theo implementation baseline.
- Bằng chứng invoke chỉ phủ handler đơn, một child đã link và sổ yêu cầu/kết quả trên adapter SQLite đã bind: từ chối quyền/scope/type/ref cũ, `REJECTED`, guard stale, ghi ngoài declaration, child sai revision/quyền/scope, key trùng intent khác, race cùng key và hai đơn tranh một budget, split binding và replay sau mất phản hồi. Không có tuyên bố về publish artifact, approval/effect, PostgreSQL/ERP, mọi lịch trình interleaving hay sandbox handler trong-process.
- Static validation không phát hiện truy cập ẩn trong thân handler (import lén, `getattr` động, đọc file/socket). Binding chỉ kiểm tra mapping khai báo; nó không phát hiện host code tự mở connection hoặc dùng credential ambient ngoài plan và không sandbox handler. Đó là rủi ro đã ghi nhận, xử lý bằng review và test.

## Tài liệu

- [Roadmap](docs/PLAN.md)
- [Sprint 4 — lát cắt đồng bộ đã hoàn tất](docs/sprint-plans/sprint-4.md)
- [Sprint 5 — kế hoạch chờ duyệt và tiếp tục](docs/sprint-plans/sprint-5.md)
- [Implementation baseline](docs/official/design/implementation-baseline.md)
- [Developer Contract](docs/official/design/developer-contract.md)
- [Framework Design v0.1](docs/official/design/framework-design-v0.1.md)
