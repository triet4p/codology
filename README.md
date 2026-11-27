# Codology

Codology (Ontology as Code) là framework khai báo thực thể, quan hệ và hành vi nghiệp vụ bằng Python. Mô hình được kiểm tra trước khi kết nối backend; engine nhúng chạy lát cắt thực thi nguyên tử đầu tiên trên SQLite. Package Python gốc là `codology`; OaC là tên khái niệm, không phải tên package.

## Trạng thái

Sprint 4 đã hoàn tất với lát cắt thực thi nguyên tử đồng bộ. [Sprint 5](docs/sprint-plans/sprint-5.md) đã phủ manifest ghim revision, trạng thái chờ ở cửa `invoke`, cửa quyết định duyệt, resume, ghi outbox cùng transaction, relay local và consumer mẫu nấc 3 chạy trên SQLite thật. Các phần đã có:

Sprint 6 bàn giao thêm [hướng dẫn author](docs/author-extension-guide.md), một lát cắt đa miền chạy được và CLI consumer thứ hai; hành vi đã kiểm chứng và giới hạn thực tế được tách riêng trong [ma trận bàn giao](#ma-trận-hỗ-trợ-đã-kiểm-chứng).


- `codology` import được từ môi trường sạch, không cần database, credential hay backend SDK.
- `codology.declarations` cung cấp primitive cấu trúc bất biến `Module`, `ObjectType`, `Value`, `Link` và `ObjectRef[T]`: identity/version tường minh, property có kiểu, link có target/cardinality/traversal và `exports` đóng băng.
- `codology.declarations` cung cấp `Action`, `Function`, `Effect` và predicate approval cấu trúc: `params`, `reads`/`writes`/`calls`, `permission`, `commitRequirement`, `approval` và `effects` được đóng băng lúc khai báo; không chạy handler hay đánh giá predicate.
- Load, Link và `snapshot()` đã được triển khai; snapshot công bố graph đã link dưới dạng bất biến, tra cứu tường minh theo identity/version.
- `pin_manifest()` / `resolve_manifest()` định nghĩa một manifest bền vững cho logic của execution: root Action, child Action/Function, effect và ontology revision đã khai báo, mỗi revision kèm digest SHA-256 của source module thực sự nạp. Host giữ nhiều revision set vẫn phân giải đúng revision đã ghim, không dùng default/latest; artifact thiếu, byte đổi, kind đổi hoặc closure khác bị từ chối trước khi chạy handler. Chưa có publish pipeline hay registry.
- `engine.invoke()` đã ghi trạng thái chờ bền: declaration có `approval` chạy handler trong preview rồi bỏ preview, trả `AWAITING_APPROVAL` kèm execution ID, manifest đã pin, `material_intent` và `required_approval`; sổ yêu cầu giữ một key duy nhất, không giữ transaction hay write đơn/ngân sách/outbox. Dưới ngưỡng đi tiếp đường nguyên tử; effect đã khai báo được snapshot vào outbox trong cùng commit, chưa giao ra ngoài.

- `engine.approve()` / `engine.reject()` kiểm callback key gắn execution và approval hiện hành, fingerprint của material intent, role/permission live do host cung cấp, tenant/scope và `self_approval`; decision được ghi riêng và audit mọi attempt. `reject` hợp lệ chỉ chuyển execution sang `REJECTED` không ghi nghiệp vụ; approve hợp lệ là đầu vào cho resume, chưa phải commit.
- `engine.resume()` mở UoW mới, phân giải đúng manifest đã ghim, chạy lại root và child ở revision đó trên dữ liệu hiện tại, kiểm lại quyền requester/approver, scope, hạn/thu hồi và so `material_intent` trước khi commit. Một transaction chứa guarded write, chuyển ledger, outcome của decision và outbox intent; hết hạn, thu hồi hoặc material đổi thì cấp approval/fingerprint mới, còn guard lệch thì `StalePlan` và rollback. `codology.resume_adapter.ResumeSQLiteProvider` là adapter thật cho đường này.

- `codology.outbox` snapshot payload có kiểu của effect đã khai báo, sinh dedup ID ổn định từ `dedupKey` (mặc định gồm execution ID) và ghi intent `PENDING` trong cùng transaction với đơn, ngân sách và ledger; handler chỉ đăng ký intent, không gọi backend hay gửi thông báo.
- `codology.relay` giao lại outbox đã commit qua relay local at-least-once, dùng dedup ID bền ở bên nhận để ghi một thông báo địa phương; trạng thái effect (`PENDING`/`PENDING_RETRY`/`DELIVERED`/`FAILED`) được đọc qua cửa `effect.read` riêng, execution vẫn `COMMITTED`. `codology.relay_adapter` cung cấp store và receiver SQLite cùng bảng inbox bền cho host; không có broker hay cam kết exactly-once ngoài DB local.

- Ví dụ Procurement/Finance chạy được trên API thật (`examples/procurement_finance/`) cùng kiểm thử tích hợp và kiểm tra typing cho cả đường thành công lẫn lỗi tĩnh.
- Ví dụ thực thi (`examples/atomic_approval/`) chạy đường consumer `query → row.as_ref() → invoke` nấc 2 trên adapter SQLite thật: commit đơn và giữ ngân sách trong một transaction, replay theo `request_key`, cùng các nhánh read/invoke denial và split binding. Kiểm thử tích hợp đọc lại dữ liệu bằng connection độc lập.
- Ví dụ thực thi nấc 3 (`examples/conditional_approval/`) chạy đường `query → ref → invoke → approve/reject → resume → relay` trên adapter SQLite thật: ngưỡng chờ, replay ghim revision sau restart, callback bị từ chối/trùng, duyệt lại, tranh ngân sách, mất ack và relay lỗi; đối chiếu order/budget/ledger/outbox bằng connection độc lập.
- Ví dụ CLI consumer độc lập (`examples/purchase_order_cli/`) gọi cùng `procurement.approve_purchase_order@2.0.0` qua các cổng công khai từ một tiến trình CLI: đọc theo scope, lấy ref từ row, xử lý chờ/deny/commit, approve bằng callback key và fingerprint do engine phát hành, resume, replay/reconcile theo key gốc và relay. Nó không import consumer mẫu và không chứa ngưỡng, bảng role/quyền, SQL hay hàm dựng fingerprint; kiểm thử chạy CLI bằng subprocess và đối chiếu DB bằng connection độc lập.
- Ví dụ miền cấp quyền hạ tầng giả lập (`examples/break_glass_access/`) khai báo hai module `access_control` và `security_audit` bằng API công khai: object, typed refs, action cha/con, predicate `any_of` theo thời lượng hoặc mức nhạy cảm, role/permission và effect payload có kiểu. Load/Link/Snapshot kiểm cạnh child/effect và export; phần host bind hai phần ghi cùng outbox vào một session SQLite, chạy `query → ref → invoke → approve → resume → relay`, và test đối chiếu business/version/ledger/outbox bằng connection độc lập.
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

Để tái lập trong môi trường tách biệt mà không thay `.venv` hiện có, đặt `UV_PROJECT_ENVIRONMENT` trước `uv sync` và giữ nó cho mọi `uv run` tiếp theo, ví dụ `UV_PROJECT_ENVIRONMENT=.tmp/verify/venv uv sync`. `.tmp/` đã được git-ignore; đây là cách gói bàn giao được chạy lại độc lập.

## Chạy kiểm tra

```bash
uv run python -c "import codology; print(codology.__version__)"
uv run python -m examples.procurement_finance
uv run python -m examples.break_glass_access
uv run python -m examples.break_glass_access --runtime
uv run python -m examples.atomic_approval
uv run python -m examples.conditional_approval
uv run pytest
uv run pyright
uv run ruff check .
uv run ruff format --check .
```

`uv run pyright` toàn repo hiện báo **22 lỗi có từ trước** trong `src/codology/` và các test cũ, nên không dùng làm gate cho gói bàn giao; dùng lệnh Pyright giới hạn phía dưới cho ví dụ và test mới. Hai lệnh Ruff ở trên phải exit 0, kể cả với code block Python trong tệp Markdown.

Hồi quy trọng điểm và kiểm phạm vi mới:

```bash
uv run pytest -q tests/test_atomic_approval_example.py tests/test_conditional_approval_example.py
uv run pytest -q tests/test_break_glass_access_example.py tests/test_break_glass_access_runtime.py tests/test_purchase_order_cli.py
uv run pyright examples/break_glass_access examples/purchase_order_cli \
  tests/test_break_glass_access_example.py tests/test_break_glass_access_runtime.py tests/test_purchase_order_cli.py
```

## Cấu trúc

```text
src/codology/
  __init__.py
  py.typed
  loading.py        # Load: thu thập definition, kiểm tra identity và field
  linking.py        # Link: resolve reference, export, kind và chữ ký handler
  snapshot.py       # Snapshot: graph đã link bất biến, lookup identity/version
  manifest.py       # Manifest ghim: digest artifact, resolve revision chính xác
  waiting.py        # Trạng thái chờ: canonical input, material intent, approval bền
  gate_support.py   # Kiểm tra plan/graph thuần dùng chung cho hai nhánh invoke
  decision.py       # Cửa quyết định: authority live, callback key, audit, terminal reject
  resume.py        # Resume: recompute pinned, live checks, guarded finish, reapproval
  outbox.py        # Effect intent: typed snapshot, stable dedup, bound session
  relay.py         # Relay local: outbox đã commit, at-least-once, trạng thái effect riêng
  relay_adapter.py # Store/receiver SQLite, inbox bền theo dedup ID
  results.py        # Attempt/execution record, replay có quyền và reconcile
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
examples/break_glass_access/
  access_control.py  # GrantRequest, effect payload, GrantAccess, AccessControl
  security_audit.py  # AuditSession, RecordSession, SecurityAudit
  model.py           # ghép hai module, load/link/snapshot
  scenarios.py       # lỗi không export và handler probe
  database.py        # schema SQLite, seed và helper đọc độc lập
  wiring.py          # deployment một session, adapter, principal, grant, authority
  consumer.py        # query -> ref -> invoke/approve/resume/relay, không policy hay SQL
  __main__.py        # entry point tĩnh và chế độ --runtime trên DB thật
examples/atomic_approval/
  database.py        # schema SQLite và dữ liệu seed hai tenant
  wiring.py          # graph, deployment plan, adapter, principal và read grant
  consumer.py        # query -> row.as_ref() -> invoke, không chép luật nghiệp vụ
  __main__.py        # entry point chạy consumer trên DB thật
examples/conditional_approval/
  declarations.py    # runtime nấc 3: approval, child, effect, revision set mới
  database.py        # schema SQLite và seed, helper đọc độc lập
  wiring.py          # deployment, adapter, principal và authority live
  consumer.py        # query/refs/invoke/callback/resume/reconcile/relay, không policy hay SQL
  __main__.py        # entry point chạy mọi kịch bản có assert
examples/purchase_order_cli/
  host.py            # host wiring: caller/resource do host cấp, không policy
  envelopes.py       # ActionResult/DecisionResult/page/relay sang JSON + bước kế tiếp
  __main__.py        # CLI query/invoke/approve/resume/reconcile/relay
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
  test_break_glass_access_example.py # Load/Link/Snapshot hai module miền giả lập
  test_break_glass_access_runtime.py # host SQLite, waiting/deny/approve/resume/relay, split binding
  test_atomic_approval_example.py # commit, denial, split binding, rollback, race, replay
  test_conditional_approval_example.py # consumer nấc 3, đối chiếu DB độc lập
  test_purchase_order_cli.py # CLI consumer thứ hai chạy subprocess, đối chiếu DB độc lập
  test_snapshot.py
  test_manifest.py   # pin/resolve revision chính xác, digest byte đã nạp, fail closed
  test_waiting.py    # Ngưỡng chờ, replay, không lock/write, tenant và KEY_MISUSE
  test_invoke.py     # DENIED/REJECTED/StalePlan, ref scope, ctx hẹp, commit/rollback
  resume_support.py  # graph, schema, provider và hook dùng chung cho resume
  test_resume_adapter.py # race, lost ack, commit bị ngắt, pin sai fail closed
  test_outbox.py     # outbox cùng commit, preview/reject không row, dedup, payload fail closed
  test_relay.py     # relay chỉ đọc committed, retry/permanent/lost ack, dedup receiver
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

`Snapshot` không công bố digest của handler: nó là view của graph đã link và không nạp artifact nào. Digest artifact được định nghĩa ở lớp manifest ngay dưới, nơi bytes thực sự nạp và phạm vi pin được xác định; không có hash tùy ý nào trong snapshot được gọi là digest. Snapshot không kéo theo engine, authorization hay execution.

## Manifest: ghim và phân giải đúng revision logic

`pin_manifest(linked, action)` nhận graph đã link và một `DefinitionKey` của root Action, rồi trả `PinnedManifest` bất biến. Manifest liệt kê đúng closure đã khai báo, chia bốn nhóm:

- `root`: Action gốc.
- `children`: mọi Action/Function reachable qua `calls` bắc cầu.
- `effects`: mọi `Effect` được khai báo bởi root hoặc child reachable.
- `ontology`: mọi `ObjectType`/`Value` có identity mà các declaration trên tham chiếu qua `params`, `reads`, `writes`, `links`, `result` hoặc `payload`.

Mỗi `ArtifactRevision` giữ `identity`, `version`, `kind` và `digest`. Digest là SHA-256 trên bytes của **source module thực sự định nghĩa declaration**, với line ending chuẩn hóa về LF. Hash cả module bao gồm thân handler và mọi helper cùng file, nên sửa logic tại chỗ làm đổi digest; handler bị gán từ module khác bị từ chối là artifact không hỗ trợ. Logic ở module khác được phủ gián tiếp vì mọi revision reachable đều được pin riêng. Import/helper từ module không nằm trong graph và `Value` anonymous nằm ngoài phạm vi pin đã hỗ trợ; `Value` anonymous chỉ được phủ bởi digest của module khai báo nó. Digest không phải intent fingerprint, identity hay version label.

Source module lúc host import là artifact được pin; sửa code đã import trong cùng tiến trình nằm ngoài biên tin cậy in-process, giống các cửa khác của package. Một host khởi động lại sẽ nạp lại đúng file và digest được kiểm trên bytes đó.

```python
from codology import (
    DefinitionKey,
    decode_manifest,
    encode_manifest,
    link,
    load,
    pin_manifest,
    resolve_manifest,
)

linked = link(load(*groups))
manifest = pin_manifest(linked, DefinitionKey("procurement.approve_purchase_order", "2.0.0"))
payload = encode_manifest(manifest)  # JSON canonical, lưu được vào record
restored = decode_manifest(payload)  # từ chối field lạ, digest sai, kind sai

# Host có thể giữ nhiều revision set; manifest chọn đúng set đã ghim.
resolved = resolve_manifest(restored, (linked_new, linked_old))
assert resolved.root.definition.version == "2.0.0"
```

`resolve_manifest()` không có default/latest. Với một hoặc nhiều `LinkedDeclarations` của host, nó chỉ chấp nhận set mà: mọi revision đã pin có mặt đúng version; closure `calls`/`effects`/ontology từ root khớp chính xác manifest; kind và digest của artifact khớp. Thiếu artifact, byte đổi, kind đổi hoặc composition trỏ sang revision khác đều raise `MissingArtifact`, `DigestMismatch`, `KindMismatch` hay `ClosureMismatch` trước khi bất kỳ handler nào chạy. `manifest_digest()` định danh chính manifest bằng bytes canonical của nó.

Đây là pin local trên graph đã link: không có registry, build artifact hay publish pipeline, và manifest không tự cấp quyền chạy logic. Approval có nhánh chờ ở cửa invoke, cửa quyết định và cửa resume; effect đã khai báo được ghi vào outbox trong commit của resume hoặc invoke dưới ngưỡng.


## Invoke chờ duyệt: ghi trạng thái bền, không giữ transaction

Với declaration có `approval`, `invoke()` chạy handler trong một UoW preview rồi đánh giá `approval.when` trên các giá trị đã resolve. `ctx.require` rớt → `REJECTED` ngay, không ghi gì. Predicate đúng → hủy preview, ghi một bản ghi ledger duy nhất và trả `AWAITING_APPROVAL` với `execution_id`, manifest đã pin, `material_intent` và `required_approval`; không có write đơn/ngân sách/outbox và không giữ session hay lock. Predicate sai → đi tiếp đường nguyên tử, không cần approver.

```python
result = invoke(..., request_key="tenant-a:alice:approve:PO-1:001")
if result.attempt.code == "AWAITING_APPROVAL":
    approval = result.execution.required_approval
    # approval.callback_key, .role, .scope, .expires_at, .self_approval
    # result.execution.material_intent.fingerprint là nội dung đã trình duyệt
```

Cùng `request_key` và intent → replay trả đúng execution đã lưu, kể cả khi host đổi revision mặc định; intent khác với key cũ bị `KEY_MISUSE`. Đọc lại cần quyền `execution.read`; tenant/principal khác không thấy record. `approval_expires_at` do host cung cấp và có hạn mặc định; ngưỡng, role và `self_approval` vẫn thuộc declaration. Outbox intent chỉ được ghi khi execution thực sự commit, kể cả trên nhánh chờ/resume; xem phần tiếp theo.


## Cửa quyết định duyệt: đúng người, đúng intent, đúng một lần

`approve()` và `reject()` nhận `execution_id`, `callback_key` (`executionId:approvalId`) và `expected_intent_fingerprint` lấy từ `material_intent` đã trình duyệt, cùng một `ApprovalAuthorityProvider` do host cung cấp dữ liệu role/permission/scope/revocation **tại thời điểm gọi**. Engine kiểm khóa đang chờ, khóa callback còn là approval hiện hành, tenant/scope, `self_approval` theo declaration, hạn và thu hồi. Quyền invoke của requester không tự cấp quyền duyệt cho chính người đó.

```python
result = engine.approve(
    provider=sqlite_provider,
    authority_provider=host_authority,
    principal=approver,
    execution_id=waiting.execution.execution_id,
    callback_key=waiting.execution.required_approval.callback_key,
    expected_intent_fingerprint=waiting.execution.material_intent.fingerprint,
    reason="budget confirmed",
)
```

Decision được ghi dưới khóa callback riêng trong cùng transaction với audit của attempt. Outsider, sai tenant/scope, mất role hoặc permission, tự duyệt bị cấm, approval hết hạn/bị thu hồi hay bị thay đều trả `DENIED` **cho callback đó**: execution vẫn `AWAITING_APPROVAL`, không có decision nào chiếm khóa, và audit ghi attempt bị từ chối tách khỏi lịch sử execution. Cùng khóa với decision/fingerprint/reason đã lưu là replay có kiểm lại authority; đổi payload với khóa cũ là `KEY_MISUSE`. `approve` hợp lệ trả attempt `AWAITING_APPROVAL` kèm `DecisionResult.decision` làm đầu vào cho resume; nó không ghi đơn, ngân sách hay outbox. `reject` hợp lệ trả `REJECTED`, chuyển đúng một lần sang terminal `REJECTED` và không ghi nghiệp vụ; replay sau đó không thêm transition. Provider SQLite dùng hai bảng `approval_decisions` và `approval_audit` cạnh `request_ledger`; xóa hoặc sửa payload decision làm callback fail closed.

## Resume: tính lại trên logic ghim, hoàn tất nguyên tử

`resume()` nhận `execution_id`, `callback_key` của decision `APPROVE` đã lưu, principal requester đang có quyền, read grant do host phát, bound plan của revision đã ghim và các revision set host đang nạp. Engine phân giải manifest đã pin, chạy lại handler root/child trên dữ liệu hiện tại, kiểm lại authority, scope, hạn/thu hồi và so `material_intent` trước khi viết. Chỉ khi mọi thứ khớp, một transaction áp dụng guarded write, chuyển ledger sang `COMMITTED` và lưu outcome của decision; guard lệch trả `StalePlan` với rollback sạch, mất ack trả `UNKNOWN` rồi đối soát bằng `reconcile()` hoặc `reconcile_execution()`.

```python
from codology.resume import reconcile_execution, resume
from codology.resume_adapter import ResumeSQLiteProvider

provider = ResumeSQLiteProvider(sqlite_provider)
result = resume(
    provider=provider,
    revisions=(graph_default, graph_pinned),
    bound=bound_pinned,
    principal=alice_with_live_permissions,
    grants=grants,
    execution_id=waiting.execution.execution_id,
    callback_key=approved.decision.callback_key,
    authority_provider=host_authority,
)
```

Approval hết hạn/bị thu hồi hoặc material đổi thì resume trả `AWAITING_APPROVAL` với approval ID, callback key và fingerprint mới; khóa cũ không commit được nữa. Decision outcome và outbox intent được lưu cùng transition tương ứng trong một transaction, nên replay hay commit bị ngắt không tạo lần ghi thứ hai. Giao effect (cùng dedup ID, trạng thái `PENDING_RETRY`/`DELIVERED`/`FAILED`) là bước tiếp theo, tách khỏi execution.


## Outbox: effect intent trong cùng transaction, giao sau commit

`Effect` khai `payload` là một `Value` có kiểu và `dedupKey` tùy chọn. Handler chỉ gọi `ctx.uow.enqueue_effect(Effect, payload=...)`: engine kiểm effect có trong `effects` của action, snapshot từng field payload thành giá trị bền (`ObjectRef`/`MinorMoney` được canonical hóa, không giữ handle sống) và tính dedup ID từ identity/version của effect cộng các field `dedupKey`; không khai `dedupKey` thì dùng execution ID. Payload sai kiểu, field ngoài khai báo, giá trị không canonical được hoặc effect ngoài `effects` bị `DENIED` trước khi có write nào.

`bind_action()` chặn declaration có `effects` trước handler nếu provider không khai `Capability.OUTBOX`, không có `effect_dedup` hoặc nếu resource `OUTBOX_RESOURCE` không enlist đúng provider/session với các write nghiệp vụ. Khi commit, `commit_guarded_writes()` ghi mỗi intent như một row `PENDING` trên **cùng unit của work** chứa guarded write và ledger; rollback hay lỗi trước commit không để lại row có thể giao. Preview `AWAITING_APPROVAL`, callback bị từ chối, `reject` hợp lệ và replay đều không tạo row mới. Relay/chạy effect là concerns riêng, không có API gửi trong `HandlerCtx`.

```python
from codology import OUTBOX_RESOURCE, Capability, Enlistment, Provider

provider = Provider(
    "orders-db",
    "sqlite",
    frozenset({Capability.ATOMIC_TRANSACTION, Capability.OUTBOX}),
    "sqlite:outbox",  # effect_dedup bền
)
enlistments = (
    Enlistment("procurement.purchase_order", "orders-db", "sqlite:main"),
    Enlistment(OUTBOX_RESOURCE, "orders-db", "sqlite:main"),  # cùng session
)
```

Adapter SQLite lưu row với `id` ổn định theo execution + effect, `dedup_id` và payload canonical; cùng dedup ID mà payload khác bị từ chối, còn dedup trùng payload thì không tạo row thứ hai. `execution.status` vẫn là `COMMITTED` bất kể trạng thái giao sau này.


## Relay local: giao sau commit, trạng thái effect riêng

`deliver_committed(store, receiver)` chỉ đọc các row outbox đã commit (ledger ghi `COMMITTED`) có trạng thái `PENDING` hoặc `PENDING_RETRY`; relay không gọi `invoke`, `resume`, handler hay mở lại transaction nghiệp vụ. Receiver local ghi thông báo và receipt dedup trong **một transaction SQLite**, nên cùng một `dedup_id` chỉ tạo một thông báo dù relay gửi lại sau khi mất ack. Đây là at-least-once có dedup ở phía nhận, không phải cam kết exactly-once cho broker hay hệ thống ngoài.

```python
from codology import EFFECT_READ_PERMISSION, deliver_committed, read_effect_status
from codology.relay_adapter import (
    SQLiteLocalReceiver,
    SQLiteRelayStore,
    create_relay_schema,
)

create_relay_schema("orders.sqlite3")  # bảng thuộc host, tạo một lần
store = SQLiteRelayStore("orders.sqlite3")
receiver = SQLiteLocalReceiver("orders.sqlite3")
deliveries = deliver_committed(store, receiver)
states = read_effect_status(store, reader, execution_id)  # reader có 'effect.read'
```

Giao thành công chuyển row sang `DELIVERED`. Lỗi tạm thời chuyển sang `PENDING_RETRY` và được retry cùng dedup ID; lỗi vĩnh viễn chuyển sang `FAILED` và relay không retry nữa. Nếu receiver đã ghi bền rồi mới mất ack, lần retry trả receipt `replayed=True` mà không thêm notification. Trong mọi nhánh, execution vẫn `COMMITTED`: đơn, ngân sách, ledger và outcome resume không đổi. Việc đọc trạng thái effect đi qua cửa riêng `read_effect_status()` với permission `effect.read` và scope tenant; không dùng quyền đọc execution để giao effect và không đọc execution để sửa effect.


## Deployment binding: kiểm tra plan cho `ATOMIC` và outbox


`bind_action()` ghép một action version cụ thể trong `Snapshot` với `Deployment` gồm `Provider`, `Enlistment` và `DelegationGrant`. Đây là kiểm tra **plan**: không gọi handler, không mở transaction và không chứng minh session vật lý đang mở. Runtime vẫn phải xác nhận transaction thật trước khi commit.

```python
from codology import (
    OUTBOX_RESOURCE,
    Capability,
    DefinitionKey,
    DelegationGrant,
    Deployment,
    Enlistment,
    Provider,
    bind_action,
)


deployment = Deployment(
    providers=(
        Provider(
            "orders-db",
            "sqlite",
            frozenset({Capability.ATOMIC_TRANSACTION, Capability.OUTBOX}),
            "sqlite:outbox",
        ),
    ),
    enlistments=(
        Enlistment("procurement.purchase_order", "orders-db", "sqlite:main"),
        Enlistment("finance.budget", "orders-db", "sqlite:main"),
        Enlistment(OUTBOX_RESOURCE, "orders-db", "sqlite:main"),
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

Binding kiểm tra năm điều:


- Provider của mọi write bắt buộc phải khai báo `Capability.ATOMIC_TRANSACTION` khi action hoặc một child reachable qua `calls` có `commitRequirement = CommitRequirement.ATOMIC`; thiếu thì `MissingCapability`.
- Write set là **bắc cầu**: `writes` của action cộng `writes` của mọi action/function reachable qua `calls`. Resource chưa enlist bị `UnboundWrite`, kể cả write chỉ do child khai báo.
- Mọi write bắt buộc phải cùng một `Enlistment.session`. Hai enlistment độc lập — dù cùng provider kind hay cùng nhãn DB — bị `NoSharedTransaction`; cùng session label do hai provider khai báo bị `InconsistentSession`.
- `DelegationGrant` là tùy chọn, nhưng nếu có cho một caller reachable thì phải khớp một call `Action` đã khai báo (`UndeclaredCall`), dùng principal `requester` chứ không phải service identity (`AmbientServiceIdentity`), và lặp đúng `permission` của child (`PermissionBroadened`). Không có grant nghĩa là engine dùng quyền live của requester; grant không thể mở rộng quyền.
- Với action khai `effects`, provider phải có `Capability.OUTBOX` và `effect_dedup`, và resource `OUTBOX_RESOURCE` phải enlist đúng provider/session với write; thiếu capability hoặc lệch session bị `MissingCapability`/`EffectSessionMismatch` trước handler.


`BoundAction` trả `writes` kèm `via` (đường đi từ root qua `calls`), `calls`, `delegations`, `session` và `effects` (revision effect kèm dedup store) — plan một session dùng cho UoW. Metadata `ATOMIC` đã bind **không** chứng minh backend đáp ứng atomicity; phần đó thuộc adapter và kiểm chứng runtime.



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
            "procurement.purchase_order",
            "1.0.0",
            "purchase_orders",
            ("status", "approved_amount"),
            currency="VND",
        ),
    ),
)
results = commit_guarded_writes(
    provider,
    plan,
    (
        GuardedWrite(
            "finance.budget",
            "B-001",
            1,
            (Assignment("balance", "add", -amount),),
            (Condition("balance", ">=", amount),),
        ),
        GuardedWrite(
            "procurement.purchase_order",
            "PO-001",
            1,
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
            "procurement.purchase_order",
            "1.0.0",
            "purchase_orders",
            ("status", "approved_amount"),
            tenant_column="tenant",
            scope_column="scope",
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

`invoke()` là cửa ghi duy nhất: nó lấy graph đã Link, plan đã bind từ đúng graph đó, ref do `query()` phát hành và các grant đọc hiện tại. Trước khi chạy handler, engine kiểm quyền invoke live của principal, từ chối declaration có `approval` mà synchronous invoke không thực hiện được, đối chiếu ref với kiểu tham số đã khai báo rồi resolve lại từng row qua cửa đọc theo tenant/scope. Effect đã khai báo và có outbox binding thì được phép enqueue; ref tự dựng, ref sai kiểu, ref ngoài scope hoặc ref cũ đều không tới được handler.


```python
from codology import DefinitionKey, bind_action
from codology.engine import invoke

definition = DefinitionKey("procurement.purchase_order", "1.0.0")
ref = page.rows[0].as_ref()  # từ query() đã authorize ở trên
result = invoke(
    linked=linked,  # kết quả link() của cùng graph
    action=DefinitionKey("procurement.approve_order", "1.1.0"),
    bound=bound,  # bind_action(snapshot(linked), deployment, action)
    provider=provider,  # adapter vừa fetch/resolve vừa begin(plan)
    principal=principal,
    grants={definition: grant},
    parameters={"order": ref, "reason": "approved after budget check"},
)
assert result.attempt.code == "COMMITTED"
```

Handler chỉ nhận `HandlerCtx`: `principal` chỉ đọc, `reads`/`writes`/`calls` đúng khai báo, `require`, `resolve`, `call`, `uow.register_mutation` và `uow.enqueue_effect`. Không có connection, credential, SQL, `commit` hay `rollback` và cũng không có API gửi thông báo; mutation và effect chỉ được đăng ký, rồi nằm trong write set/outbox đã bind. Engine revalidate version/scope trước khi commit rồi gọi `commit_guarded_writes()` trên đúng session đã bind: mọi write và outbox intent trong execution dùng chung một transaction vật lý, guard không khớp thì rollback toàn bộ.


`ActionResult` gồm `attempt` (`code`: `COMMITTED`, `DENIED`, `REJECTED` hoặc `StalePlan`), `execution` và kết quả các write. `DENIED` và `StalePlan` không tạo execution record và không đổi DB; `REJECTED` do `ctx.require` là outcome nghiệp vụ có record terminal; `COMMITTED` mang record kèm các mutation đã chấp nhận, danh sách child revision đã chạy và outbox intent đã ghi cùng commit. `ctx.call` chỉ dispatch khi đích nằm trong `calls`, có delegation grant đúng quyền của requester và tồn tại ở đúng revision đã link; gọi ngoài khai báo fail closed. Sổ request/result bền vững, replay theo `request_key` không tạo row outbox thứ hai.


Lỗi hạ tầng ở cửa giao dịch — provider không mở đúng session đã bind, `BEGIN IMMEDIATE` không lấy được lock trong `timeout`, hay commit không xác nhận được — trả `attempt.code = "UNKNOWN"` với `execution = None` và không có write result. Port phân biệt `TransactionUnavailable` (không mở/dùng được transaction, chưa commit) với `CommitOutcomeUnknown` (đã thử commit nhưng không rõ kết quả); engine không gộp chúng vào `DENIED`/`REJECTED`/`StalePlan` và không tự nhận đã rollback. Caller phải `reconcile` hoặc lookup ledger trước khi retry cùng `request_key`; exception không thuộc lớp hạ tầng này vẫn propagate.

## Child Action qua ủy quyền thu hẹp

`ctx.call("finance.reserve_budget", ...)` chỉ dispatch tới Action đã khai báo trong `calls` và đã link ở đúng identity/version. Engine kiểm delegation grant của requester, quyền live của child (`budget.reserve`) và resolve lại ref qua grant hiện tại; child nhận `HandlerCtx` riêng với `reads`/`writes` của chính nó nhưng dùng chung registration list, nên mọi write của cha và con nằm trong một `commit_guarded_writes()` duy nhất. Child `REJECTED` hoặc `DENIED` làm toàn bộ execution không commit; write trực tiếp từ Procurement vào `Budget` và call không khai báo đều fail closed.

```python
result = invoke(
    linked=linked,  # graph nấc 2 của runtime.py
    action=DefinitionKey("procurement.approve_purchase_order", "1.1.0"),
    bound=bound,  # delegation grant REQUESTER + budget.reserve
    provider=provider,
    principal=principal,  # cần purchase_order.approve và budget.reserve
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

## Ví dụ consumer nấc 3: chờ duyệt và tiếp tục

`examples/conditional_approval/` bàn giao toàn bộ đường consumer trên adapter SQLite thật:

```bash
uv run python -m examples.conditional_approval
```

Consumer đọc đơn qua `query`, lấy `VersionedRef` từ `row.as_ref()`, `invoke` action có `approval`/`effects`, rồi dùng callback key và fingerprint do engine phát hành cho `approve`/`reject`, gọi `resume`, `reconcile` và `read_effect_status`, cuối cùng giao outbox qua `deliver_committed`. Không có policy hay SQL trong caller; ngưỡng, role và `self_approval` nằm ở declaration, authority live do host cung cấp.

Kết quả in ra gồm: dưới ngưỡng commit thẳng, tại ngưỡng chờ mà không ghi/không giữ transaction, replay sau restart dù revision mặc định đổi, callback outsider/`KEY_MISUSE` không chiếm key, duplicate idempotent, reject terminal, material đổi thì duyệt lại, hai resume tranh một budget chỉ ghi reservation một lần, mất ack commit vẫn reconcile được `COMMITTED`, và relay transient/permanent/lost ack giữ execution `COMMITTED` với đúng một thông báo địa phương. Mọi kỳ vọng được assert.

`tests/test_conditional_approval_example.py` chạy chính các hàm consumer này rồi đọc lại bằng connection độc lập cho 13 ca: entry point, commit dưới ngưỡng, chờ không ghi/không giữ lock, restart/pin, deny/duplicate, reject, duyệt lại, tranh chấp, mất ack commit, ba nhánh relay và cửa đọc effect theo quyền/tenant. Hướng dẫn và non-claims nằm ở [`examples/conditional_approval/README.md`](examples/conditional_approval/README.md).

## Ví dụ CLI consumer độc lập

`examples/purchase_order_cli/` là consumer thứ hai của đúng action `procurement.approve_purchase_order@2.0.0`: một tiến trình CLI gọi trực tiếp các cổng công khai, dùng lại host contract của ví dụ conditional-approval nhưng **không import** `examples/conditional_approval/consumer.py`. CLI chỉ chọn caller do host cấp (`requester`, `approver`, `outsider`) và resource mà host đã map; ngưỡng, bảng role/quyền, logic giữ ngân sách, SQL và hàm dựng fingerprint không có trong mã CLI.

```bash
uv run python -m examples.purchase_order_cli install --db .tmp/purchase-order-cli/orders.sqlite3
uv run python -m examples.purchase_order_cli query --db .tmp/purchase-order-cli/orders.sqlite3 --status PENDING
uv run python -m examples.purchase_order_cli invoke --db .tmp/purchase-order-cli/orders.sqlite3 \
  --order PO-1 --budget B-1 --reason "approved after budget check" \
  --request-key tenant-a:alice:approve:PO-1:001
```

`query` chỉ trả `PO-1` dù DB còn `PO-9` tenant khác. `invoke` trả envelope `AWAITING_APPROVAL` với ref lấy từ `row.as_ref()`, callback key/fingerprint do engine cấp và bước kế tiếp `approve`. Replay `invoke` cùng `request_key` **trong lúc execution còn chờ** trả cùng execution với `deduplicated=True` và không ghi thêm. Sau commit, CLI phải dùng `reconcile --request-key` (hoặc `--execution-id`) để lấy lại cùng execution: CLI luôn query lại nên ref mang version mới, intent vì thế khác và `invoke` cùng key trả `DENIED`/`KEY_MISUSE`, không tăng version hay giữ ngân sách thêm. `approve --as approver` dùng đúng giá trị engine cấp rồi `resume` mới commit execution, hai write, ledger và outbox; `approve --as outsider` trả `DENIED` mà execution vẫn chờ. Khi resume mất ack commit (`--simulate-lost-ack`, hook do host cung cấp), envelope `UNKNOWN` chỉ sang `reconcile` bằng id/key gốc thay vì sinh key mới.

Mỗi lệnh in một JSON object; exit 0 cho envelope hợp lệ (`AWAITING_APPROVAL`, `DENIED`, `UNKNOWN`), exit 2 cho lỗi dùng lệnh. `tests/test_purchase_order_cli.py` chạy CLI bằng subprocess trên fixture SQLite thật và đối chiếu order/budget/ledger/outbox/decision/effect bằng connection độc lập. Chi tiết lệnh, envelope và non-claims ở [`examples/purchase_order_cli/README.md`](examples/purchase_order_cli/README.md).

## Ví dụ Procurement/Finance

`examples/procurement_finance/` là ví dụ chạy được trên chính API công khai ở trên: hai module Procurement và Finance, `ApprovePurchaseOrder` gọi `finance.reserve_budget`, kèm approval và effect metadata. Chạy từ gốc repo:

```bash
uv run python -m examples.procurement_finance
```

Ví dụ in đường Load → Link → Snapshot rồi sáu lỗi tĩnh: `DuplicateIdentity` (Load), `NotExported`, `UnresolvedReference`, `ObjectRefMismatch`, `HandlerMismatch` (Link) và `UnsupportedApprovalExpression` (declaration). `tests/test_procurement_finance_integration.py` kiểm tra lại toàn bộ đường đi và output của entry point; `tests/typing/valid_api.py` ghim kiểu công khai, còn `tests/typing/invalid_api.py` đảm bảo Pyright vẫn bắt các lỗi kiểu có chủ đích.

Không cần backend: handler chỉ là metadata và không được gọi. Declaration nấc 2 trong `runtime.py` không thuộc đường tĩnh này; nó được dùng bởi ví dụ thực thi `examples/atomic_approval/` và các test invoke/child. Hướng dẫn chạy, lỗi và non-claims chi tiết nằm ở [`examples/procurement_finance/README.md`](examples/procurement_finance/README.md).

## Ví dụ miền cấp quyền hạ tầng

`examples/break_glass_access/` là lát cắt đa miền: hai module sở hữu hai phần ghi (`access_control`, `security_audit`), một action cha gọi action con đã export, approval `any_of` theo `duration_minutes >= 60` hoặc `sensitivity == "CRITICAL"`, role `security_officer`, và effect payload có kiểu. Thời lượng là `int` phút ở runtime; effect chỉ ghi một thông báo local, không cấp quyền hay phát hành chứng chỉ thật.

Đường tĩnh dựng Load → Link → Snapshot:

```bash
uv run python -m examples.break_glass_access
```

Ví dụ in Load → Link → Snapshot, cạnh `params`/`reads`/`writes`/`calls`/`effects` của hai action, rồi lỗi `NotExported` khi `AuditSession` bị bỏ khỏi export. `tests/test_break_glass_access_example.py` kiểm tra identity/version, edge child/effect, ownership/export, predicate và một handler probe chứng minh Load/Link/Snapshot không chạy handler.

Phần host bind `GrantAccess` (`ATOMIC`) cùng action con, hai phần ghi và `OUTBOX_RESOURCE` vào một session SQLite duy nhất, cấp `Principal`/`ReadGrant`/`LiveAuthority` riêng cho requester và security officer, và chạy trên DB file-backed:

```bash
uv run python -m examples.break_glass_access --runtime
```

Chế độ `--runtime` mở DB riêng cho từng ca và assert: request 30 phút không nhạy cảm đi thẳng (hai write, ledger và outbox commit cùng nhau); đúng ngưỡng 60 phút và ca `CRITICAL` 15 phút đều `AWAITING_APPROVAL` mà không ghi business/outbox; callback sai authority `DENIED` không kết thúc execution đang chờ; approve hợp lệ chưa commit cho tới `resume`, replay cùng key/ref không ghi lại; relay chỉ giao sau commit và không chạy lại handler. `tests/test_break_glass_access_runtime.py` đối chiếu từng kết quả API bằng connection SQLite độc lập và kiểm `bind_action()` từ chối deployment tách session.


## Ma trận hỗ trợ (đã kiểm chứng)

Bảng chỉ ghi hành vi có bằng chứng chạy lại; cột cuối là non-claim, không phải tính năng được hứa. Lệnh và kết quả thực tế nằm ở [bằng chứng bàn giao](artifacts/sprint-6/tasks/S6-T5-A1.md).

| Năng lực | Trạng thái | Bằng chứng | Non-claims / giới hạn |
| --- | --- | --- | --- |
| Author thêm nghiệp vụ ngoài duyệt đơn từ tài liệu | Đã kiểm chứng | [Hướng dẫn author](docs/author-extension-guide.md), [dấu vết author](artifacts/sprint-6/tasks/S6-T2-A1.md), `tests/test_break_glass_access_example.py` | Không sửa `src/codology/`, không xin API lõi mới; handler không được gọi lúc Load/Link |
| Hai phần ghi và outbox trong một session SQLite | Đã kiểm chứng | [Review T3 PASS](artifacts/sprint-6/reviews/S6-T3-C1.md), `uv run python -m examples.break_glass_access --runtime`, `tests/test_break_glass_access_runtime.py` | Chỉ SQLite file-backed một session; cấu hình tách session bị `NoSharedTransaction`, không có saga |
| Consumer thứ hai dùng lại hợp đồng duyệt đơn | Đã kiểm chứng | [Review T4 PASS](artifacts/sprint-6/reviews/S6-T4-C1.md), `tests/test_purchase_order_cli.py`, [CLI README](examples/purchase_order_cli/README.md) | Không HTTP/service/SDK/MCP; CLI không policy, SQL, role table hay fingerprint tự dựng |
| Hồi quy hai đường duyệt đơn | Đã kiểm chứng | `uv run pytest -q tests/test_atomic_approval_example.py tests/test_conditional_approval_example.py` → 24 passed | Không thay thế kiểm thử unit/lõi; không gate coverage hay hiệu năng |
| Cài đặt từ môi trường sạch | Đã kiểm chứng | `uv sync` vào venv riêng qua `UV_PROJECT_ENVIRONMENT`, `codology 0.1.0` | Không hỗ trợ Python < 3.13; không cam kết dependency ngoài `uv.lock` |
| Kiểm tĩnh cho sản phẩm bàn giao | Đã kiểm chứng có phạm vi | Pyright giới hạn ví dụ/test mới → 0 errors; `ruff check .` và `ruff format --check .` → sạch | `uv run pyright` toàn repo còn 22 lỗi cũ ngoài phạm vi bàn giao |

Replay chỉ idempotent khi cùng `request_key` **và cùng intent**. Sau commit, ref do CLI query lại có version mới nên `invoke` cùng key bị từ chối; dùng `reconcile` với key/id gốc. Đây là giới hạn đã kiểm chứng, không phải cam kết replay vô điều kiện.

## Quyết định đã chốt

- **Một quy ước handler duy nhất:** `def handler(self, ctx, ...)` trên class khai báo. `@staticmethod def handle(...)` không được hỗ trợ; không có API thứ hai để giữ đồng bộ. `self` không mang execution state.
- **Forward reference không import vòng:** annotation được giữ nguyên dạng viết lúc tạo class và chỉ resolve ở pha Link bằng namespace đã compose từ mọi module tham gia link. Hai module có thể tham chiếu kiểu của nhau mà không import nhau lúc chạy.
- **Layout và công cụ:** source đặt trong `src/codology/`, đóng gói bằng Hatchling, quản lý bằng uv; kiểm thử bằng pytest; type-check bằng Pyright strict; lint/format bằng Ruff.
- **Adapter và tiền chính xác:** SQLite file-backed, một session vật lý cho mọi write đã bind; `MinorMoney` lưu số nguyên đơn vị nhỏ với một currency, không float và không FX.
- **Đọc an toàn:** mọi row/count/cursor đi qua một cửa đã authorize; adapter SQLite chỉ nhận predicate có pushdown tương đương đã kiểm chứng, từ chối traversal `internal` và mọi traversal chưa có conformance thay vì lọc ngầm sau khi đọc.
- **Invoke một handler:** quyền ghi được kiểm live ở cửa engine, ref chỉ có giá trị khi resolve lại dưới grant hiện tại; `ctx.require` tạo `REJECTED`, xung đột version/guard tạo `StalePlan`, lỗi cửa tạo `DENIED` mà không tạo execution. Commit là quyết định của engine sau revalidate, không phải của handler.
- **Child action đã link:** `calls` và delegation grant được bind trước runtime; `ctx.call` chạy handler của đúng revision đã link với context thu hẹn theo `reads`/`writes` của child, dùng chung một UoW và một transaction. Child `REJECTED`/`DENIED` hủy toàn bộ execution; service identity và ref tự dựng không thay được requester.
- **Sổ yêu cầu bền vững:** scope key là `tenant / requester / action identity` (ổn định qua rollout version); dấu vân tay intent do engine recompute từ dữ liệu đã canonicalize, không phải digest handler. Key, intent và kết quả `COMMITTED` được ghi trong cùng transaction với mọi business write; replay trả kết quả cũ, còn tra cứu cần quyền đọc execution record. Bản ghi `AWAITING_APPROVAL` chiếm cùng key, kèm manifest đã pin, material intent và required approval; replay trả đúng execution đó. Lần chờ đầu trả `deduplicated=False`, còn replay cùng key trả `True` để caller phân biệt yêu cầu mới và bản ghi đã có.
- **Tách authority của callback:** requester và approver là hai vai; host cung cấp role/permission/scope/revocation live, engine kiểm khóa, fingerprint, hạn và `self_approval` từ khai báo. Attempt bị từ chối chỉ vào audit, không chiếm khóa và không kết thúc execution; `reject` hợp lệ là terminal duy nhất không ghi nghiệp vụ, còn `approve` chỉ là decision chờ resume.
- **Consumer mẫu trên adapter thật:** `examples/atomic_approval/` giữ phần caller chỉ ở `query`, `row.as_ref()` và `invoke`; quyền, ngân sách và write nằm trong declaration/handler và engine. Split binding nấc 2 (hai file cùng SQLite) vẫn bị từ chối trước runtime, không hạ xuống saga.
- **Consumer nấc 3 trên adapter thật:** `examples/conditional_approval/` giữ caller ở các cửa công khai (`query`, `invoke`, `approve`/`reject`, `resume`, `reconcile`, `deliver_committed`, `read_effect_status`); fingerprint lấy từ execution record, không tự dựng policy hay SQL. Ví dụ nấc 2 `examples/atomic_approval/` vẫn chỉ phủ đường đồng bộ và không được đọc như consumer nấc 3.
- **Consumer thứ hai dùng lại hợp đồng:** `examples/purchase_order_cli/` gọi đúng `procurement.approve_purchase_order@2.0.0` qua các cổng công khai và tự diễn giải envelope; `callback_key`/`intent_fingerprint` chỉ được chuyển tiếp từ engine, không import consumer mẫu, không chứa policy, SQL hay fingerprint tự dựng. Host vẫn giữ bind, principal và grant.
- Chi tiết và hệ quả cho các task sau: [`docs/official/design/implementation-baseline.md`](docs/official/design/implementation-baseline.md).

## Giới hạn

- Đây vẫn là lớp mô hình tĩnh, manifest pin local trên graph đã link, deployment binding plan-check, adapter transaction có guarded write, cửa đọc có policy, cửa ghi `invoke()` với child đã link, sổ yêu cầu/kết quả bền vững, trạng thái chờ, cửa quyết định, resume, outbox intent cùng commit, relay local và consumer mẫu nấc 3. `examples/atomic_approval/` giữ consumer nấc 2; `examples/conditional_approval/` là consumer nấc 3 trên SQLite một file; `examples/purchase_order_cli/` là CLI consumer độc lập dùng chung host contract đó. Chưa có publish artifact/registry.

- Load đã thu thập definition và kiểm tra identity/field; Link đã resolve reference, kiểm tra export/kind và chữ ký handler; snapshot đã công bố graph bất biến với lookup tường minh; `pin_manifest()`/`resolve_manifest()` đã pin và phân giải đúng revision kèm digest artifact; `bind_action()` đã kiểm tra capability, write set và enlistment plan trên snapshot; `waiting` lưu canonical input, material intent và approval dưới key duy nhất, `decision` giữ callback key, authority live và audit attempt, `gate_support` giữ kiểm tra thuần dùng chung, còn `results` tách representation và replay của execution. Adapter transaction thật đã có; chưa có registry bền vững hay publish artifact.
- Predicate approval được đánh giá có cấu trúc tại cửa `invoke` cho nhánh chờ, kèm fingerprint của material intent; callback, resume, outbox và relay/giao effect đã có bằng chứng chạy được qua consumer mẫu. `Function` dùng cùng quy ước `handler(self, ctx, ...)` với `Action` theo implementation baseline.

- Bằng chứng invoke và callback chỉ phủ handler đơn, một child đã link và sổ yêu cầu/kết quả trên adapter SQLite đã bind: từ chối quyền/scope/type/ref cũ, `REJECTED`, guard stale, ghi ngoài declaration, child sai revision/quyền/scope, key trùng intent khác, race cùng key và hai đơn tranh một budget, split binding và replay sau mất phản hồi; phần chờ kiểm ngưỡng dưới/tại/trên, precondition rớt, replay sau mở lại engine và đổi revision mặc định, connection khác ghi được lúc chờ, không có write đơn/ngân sách/outbox và phân quyền tenant/đọc; phần quyết định kiểm outsider, sai tenant/scope/key/fingerprint, mất role/quyền, tự duyệt theo declaration, hết hạn/thu hồi/thay approval, replay có kiểm quyền, `KEY_MISUSE` và reject terminal một lần không ghi nghiệp vụ; phần outbox đối soát row bền bằng connection độc lập trên cả hai nhánh commit, không có row lúc chờ/từ chối/rollback/replay, dedup ổn định và payload/declaration sai bị chặn. Phần relay kiểm committed-only, transient retry, permanent fail và lost ack với đúng một thông báo địa phương; consumer nấc 3 đối chiếu order/budget/ledger/outbox bằng connection độc lập. Không có tuyên bố về publish artifact, PostgreSQL/ERP, mọi lịch trình interleaving, crash/power-loss, exactly-once ngoài DB local hay sandbox handler trong-process.

- `uv run pyright` toàn repo chưa sạch: 22 lỗi có từ trước nằm ở `src/codology/engine.py`, `money.py`, `outbox.py`, `uow.py` và `tests/resume_support.py`, `tests/test_outbox.py`. Gói bàn giao dùng lệnh Pyright giới hạn ở mục "Chạy kiểm tra" (0 errors); không sửa lõi để che lỗi cũ.
- CLI query lại ref khi chạy `invoke`, nên sau commit cùng `request_key` mà intent đổi (version mới) trả `DENIED`/`KEY_MISUSE`; `reconcile --request-key` hoặc `--execution-id` mới là đường tra cứu sau commit. Xem chi tiết ở mục CLI và [ma trận bàn giao](#ma-trận-hỗ-trợ-đã-kiểm-chứng).

- Static validation không phát hiện truy cập ẩn trong thân handler (import lén, `getattr` động, đọc file/socket). Binding chỉ kiểm tra mapping khai báo; nó không phát hiện host code tự mở connection hoặc dùng credential ambient ngoài plan và không sandbox handler. Đó là rủi ro đã ghi nhận, xử lý bằng review và test.

## Tài liệu

- [Roadmap](docs/PLAN.md)
- [Sprint 4 — lát cắt đồng bộ đã hoàn tất](docs/sprint-plans/sprint-4.md)
- [Sprint 5 — kế hoạch chờ duyệt và tiếp tục](docs/sprint-plans/sprint-5.md)
- [Implementation baseline](docs/official/design/implementation-baseline.md)
- [Developer Contract](docs/official/design/developer-contract.md)
- [Framework Design v0.1](docs/official/design/framework-design-v0.1.md)
- [Hướng dẫn author mở rộng](docs/author-extension-guide.md) — điểm vào cho developer không viết lõi, có CLI link ở §7.
- [CLI consumer độc lập](examples/purchase_order_cli/README.md) — lệnh, envelope và non-claims.
- [Bằng chứng bàn giao S6-T5](artifacts/sprint-6/tasks/S6-T5-A1.md) — lệnh, kết quả và môi trường tái lập.
