# Developer Contract

*Đặc tả bề mặt author cho OaC: author phải khai báo gì, mặc định cái gì là nội bộ, engine bảo đảm điều gì, và lỗi nào bị chặn trước khi chạy. Phạm vi tài liệu: Nấc 1 (action đồng bộ đơn module) và Nấc 2 (liên module nguyên tử + ủy quyền thu hẹp). Mọi code là đặc tả contract minh họa, chưa phải syntax cuối.*

## 1. Tổng quan

Hợp đồng author trả lời ba câu hỏi, theo đúng thứ tự engine kiểm tra:

1. **Khai báo gì?** Chỉ những phụ thuộc mà static layer kiểm tra được: tham số có kiểu, `reads`, `writes`, `calls`, `permission`, và (khi cần) `commitRequirement`.
2. **Mặc định ai thấy?** Mọi definition là nội bộ module sở hữu; chỉ identity nằm trong `Module.exports` mới được module khác reference.
3. **Engine bảo đảm gì?** Một cửa invoke duy nhất cho authorization, resolve, revalidate và commit; handler không tự quản transaction, không giữ credential.

Nguyên tắc xuyên suốt là **progressive disclosure**: mỗi nấc chỉ **cộng thêm thuộc tính khai báo**. Không đổi kiểu tham số, không đổi tên identity, không đổi vị trí `handler`, không thêm boilerplate vào ca đơn giản.

| Nấc | Khai báo thêm | Engine đảm nhiệm | Trạng thái |
| --- | --- | --- | --- |
| 1 | `ObjectType`, `Action` (`params`, `reads`, `writes`, `permission`, `handler`) | Một UoW trên một resource, authorization live, audit | Đặc tả trong tài liệu này (mục 3.1) |
| 2 | `+ reads` liên module, `calls`, `commitRequirement = ATOMIC`; `Module.exports` | Link cross-module, ủy quyền thu hẹp, một enlisted session vật lý | Đặc tả trong tài liệu này (mục 3.2) |
| 3 | `approval`, `effects` | Treo/tiếp tục execution, revalidate khi resume, outbox cùng session | Ngoài phạm vi: chỉ cộng thêm, không sửa mục 2–5 ở đây |
| 4 | Không thêm primitive; chỉ đổi version/ngữ nghĩa | Semantic diff, pin manifest, compat | Ngoài phạm vi: quy tắc versioning thuộc tài liệu tiến hóa |

Ví dụ xuyên suốt: `procurement.approve_purchase_order` (viết tắt `ApprovePurchaseOrder`) leo từ `1.0.0` lên `1.1.0` khi cần giữ ngân sách thuộc `finance`. Hợp đồng người gọi (`query`/`invoke`/`approve`/`reconcile`) không thuộc tài liệu này.

## 2. Nguyên thủy khai báo và mặc định sở hữu

### 2.1 Module và luật export

Module là ranh giới sở hữu: ai quyết định ý nghĩa của khái niệm và hành vi đã hứa với bên khác.

```python
# procurement/module.py
class ProcurementModule(Module):
    """Ranh giới sở hữu của nghiệp vụ mua hàng."""

    identity = "procurement"
    version = "1.0.0"
    exports = [PurchaseOrder, ApprovePurchaseOrder]
```

Luật, theo thứ tự ưu tiên:

- **Mặc định nội bộ.** Không có cờ `private`/`public`; mọi definition không nằm trong `exports` là nội bộ module. `exports` là ngoại lệ duy nhất.
- **Chỉ exported mới reference được từ ngoài.** `ObjectRef[T]`, `Link.target`, `reads`, `writes`, `calls` của module khác chỉ hợp lệ khi identity đích nằm trong `exports` của module sở hữu. Đây là kiểm tra pha Link, không phải quy ước.
- **Export là ranh giới sở hữu, không phải ranh giới quyền.** Export không cấp quyền cho user nào; `permission` và authorization live quyết định ở invoke-time. Finance export `ReserveBudget` không đồng nghĩa mọi người dùng được giữ ngân sách.
- **Identity ổn định, không chứa version.** Dạng `<domain>.<snake_name>` (`finance.reserve_budget`); version là trường riêng. Host name (`ReserveBudget` trong `finance/actions.py`) và display name được refactor tự do miễn identity không đổi.
- **Phụ thuộc phải tường minh.** Nếu Finance không export `FinancialPolicy`, Procurement không reference trực tiếp được; muốn dùng phải đi qua action đã export.

### 2.2 ObjectType, Value, Link

Object biểu diễn thực thể có danh tính ổn định. Value biểu diễn khái niệm không có vòng đời riêng. Link biểu diễn quan hệ giữa hai thực thể thay đổi độc lập.

```python
class Money(Value):
    """Số tiền kèm đơn vị; không có vòng đời riêng, không phải ObjectType."""

    amount: Decimal
    currency: Currency                  # ISO-4217


class PurchaseOrder(ObjectType):
    """Đơn mua; cùng một đơn vẫn là cùng một đơn dù đổi trạng thái."""

    identity = "procurement.purchase_order"
    version = "1.0.0"
    keyType = "PO"                      # canonical key dạng "PO-001", không phải ID của definition

    status: Literal["PENDING", "APPROVED", "CANCELLED"]
    amount: Money                       # comparisonUnit khai báo khi dùng để so sánh ngưỡng

    supplier: Link[Supplier, "one", "navigable"]
    lines: Link[PurchaseOrderLine, "many", "navigable"]
    approval_note: Link[ApprovalNote, "many", "internal"]
    budget: Link[Budget, "one", "navigable"]   # cạnh có kiểu sang Finance
```

- `keyType` cố định cách sinh canonical key; ID definition không phải key instance. `ObjectRef` mang type ID + canonical key, adapter ánh xạ key logic sang nguồn vật lý.
- Property luôn có kiểu; `required` và `comparisonUnit` chỉ khai báo khi contract cần. Core không hard-code ngưỡng tiền, vai trò Finance hay quy tắc Procurement.
- `Link` gồm `name`, `target`, `cardinality` (`one` | `many`), `traversal` (`navigable` | `internal`). Chỉ `navigable` mới đi qua query boundary; `internal` không lộ ra ngoài module.
- Khai báo link hoặc export **không** cấp quyền đọc. Cạnh `budget` tồn tại từ `1.0.0` nhưng Nấc 1 không đọc được `Budget` vì `reads` của action không chứa nó.
- Thêm property/link là thay đổi khai báo; xếp hạng PATCH/MINOR/MAJOR thuộc tài liệu tiến hóa (Nấc 4), không quyết định ở đây.

### 2.3 ObjectRef và Function

```python
class RemainingBudget(Function):
    """Read-only derived view; không mutation, không approval, không effect."""

    identity = "finance.remaining_budget"
    version = "1.0.0"
    budget: ObjectRef[Budget]
    result = Money

    def evaluate(self, ctx, budget: Budget) -> Money:
        return budget.limit - budget.reserved
```

- `ObjectRef[T]` là tham chiếu có kiểu: engine kiểm tra `T` tồn tại và resolve đúng type ở invoke-time, trả handle kèm `version`. Tham số kiểu `str` trần bị từ chối ở pha Link vì mất toàn bộ khả năng kiểm tra.
- `Function` chỉ đọc: không `writes`, không `approval`, không `effects`; chạy dưới read authorization của principal và không ghi gì. Dùng cho derived/normalized view như `normalized_amount` hay `remaining_budget`.
- Cả hai đều là definition có `identity` + `version`, chịu cùng luật export như Action.

### 2.4 Action: trường nào thuộc nấc nào

| Trường | Nấc 1 | Nấc 2 | Ý nghĩa |
| --- | --- | --- | --- |
| `identity` | Bắt buộc | Không đổi | `<domain>.<snake_name>`; đổi là breaking |
| `version` | Bắt buộc | `1.0.0 → 1.1.0` | SemVer của definition đã publish |
| `params` | Bắt buộc | Không đổi | Tham số có kiểu: `ObjectRef[T]`, Value, scalar |
| `reads` | Bắt buộc | `+ Budget` | ObjectType định đọc; kiểm tra export/kiểu, cấp quyền chạm |
| `writes` | Bắt buộc | Không đổi | ObjectType định ghi; mọi ghi đi qua UoW |
| `permission` | Bắt buộc | Không đổi | Permission string, kiểm tra live mỗi lần invoke |
| `handler` | Bắt buộc | Thân đổi | Nghiệp vụ thuần trên object đã resolve |
| `calls` | Không có | `["finance.reserve_budget"]` | Cạnh phụ thuộc liên module tường minh |
| `commitRequirement` | Không khai báo | `CommitRequirement.ATOMIC` | Bảo đảm commit trên nhiều resource |
| `approval`, `effects` | Không có | Không có | Thuộc Nấc 3 |

Ghi chú thuật ngữ: `commitRequirement` là tên trường trong meta-model v0.1; các tài liệu trước dùng ký hiệu `Transaction.atomic()`. Chúng mô tả cùng một cam kết — mọi write bắt buộc phải nằm trong **một** transaction vật lý.

## 3. Nấc thang authoring

### 3.1 Nấc 1 — action đồng bộ đơn module

Khai báo tối thiểu: danh tính, version, tham số có kiểu, phạm vi đọc/ghi, permission và handler nghiệp vụ. Không workflow, không approval, không outbox, không transaction code.

```python
# procurement/actions.py
class ApprovePurchaseOrder(Action):
    """Duyệt một đơn mua đang chờ."""

    identity = "procurement.approve_purchase_order"
    version = "1.0.0"

    order: ObjectRef[PurchaseOrder]
    reason: str

    reads = [PurchaseOrder]
    writes = [PurchaseOrder]
    permission = "purchase_order.approve"

    def handler(self, ctx, order: PurchaseOrder, reason: str):
        ctx.require(order.status == "PENDING", reason="purchase_order_not_pending")
        ctx.require(bool(reason.strip()), reason="reason_required")

        ctx.uow.register_mutation(
            order,
            status="APPROVED",
            expectedVersion=order.version,
        )
        return {"order": order.ref, "status": "APPROVED"}
```

Phần author **không** viết ở Nấc 1:

- Không mở transaction, không commit, không rollback, không retry.
- Không kiểm tra permission thủ công — `permission` đã khai báo, engine kiểm tra live trước khi handler chạy.
- Không dựng state machine, approval, outbox hay cross-module wiring.
- Không tự map exception thành trạng thái; `ctx.require` là cách duy nhất author tạo `REJECTED`.

Kết quả quan sát được của Nấc 1, tách biệt theo cơ chế:

| Kết quả | Cơ chế sinh ra | Author viết? |
| --- | --- | --- |
| `COMMITTED` | Engine commit UoW sau revalidate | Không |
| `REJECTED` | `ctx.require` trả `False`, mang `reason` nghiệp vụ | Có |
| `DENIED` | Thiếu `purchase_order.approve`, key misuse, principal không hợp lệ | Không |
| `UNKNOWN` | Timeout sau commit — trạng thái hiểu biết của caller, cần reconcile | Không |

Gộp `DENIED` với `REJECTED` là sai contract: consumer không còn biết phải xin quyền hay sửa nghiệp vụ. `UNKNOWN` không phải `FAILED` và không được retry mù.

### 3.2 Nấc 2 — liên module nguyên tử và ủy quyền thu hẹp

Finance công bố Object `Budget` và Action `ReserveBudget`; Procurement gọi nghiệp vụ đã công bố thay vì tự sửa số dư.

```python
# finance/module.py
class FinanceModule(Module):
    identity = "finance"
    version = "1.0.0"
    exports = [Budget, ReserveBudget, RemainingBudget]


class Budget(ObjectType):
    identity = "finance.budget"
    version = "1.0.0"
    keyType = "B"

    limit: Money
    reserved: Money
    cost_center: str


class ReserveBudget(Action):
    """Giữ ngân sách cho một lần chi; Finance sở hữu mutation trên Budget."""

    identity = "finance.reserve_budget"
    version = "1.0.0"

    budget: ObjectRef[Budget]
    amount: Money
    expectedVersion: int

    reads = [Budget]
    writes = [Budget]
    permission = "budget.reserve"

    def handler(self, ctx, budget: Budget, amount: Money, expectedVersion: int):
        ctx.require(budget.limit.currency == amount.currency, reason="currency_mismatch")
        available = budget.limit - budget.reserved
        ctx.require(available >= amount, reason="budget_insufficient")

        ctx.uow.register_mutation(
            budget,
            reserved=budget.reserved + amount,
            expectedVersion=expectedVersion,
        )
        return {"budget": budget.ref, "reserved": amount}
```

`ApprovePurchaseOrder` leo `1.1.0` bằng cách **chỉ thêm** thuộc tính khai báo:

```python
# procurement/actions.py — 1.1.0
class ApprovePurchaseOrder(Action):
    identity = "procurement.approve_purchase_order"
    version = "1.1.0"

    order: ObjectRef[PurchaseOrder]
    reason: str

    reads = [PurchaseOrder, Budget]              # + Budget
    writes = [PurchaseOrder]
    calls = ["finance.reserve_budget"]           # + cạnh phụ thuộc
    permission = "purchase_order.approve"
    commitRequirement = CommitRequirement.ATOMIC  # + cam kết commit

    def handler(self, ctx, order: PurchaseOrder, reason: str):
        ctx.require(order.status == "PENDING", reason="purchase_order_not_pending")
        ctx.require(bool(reason.strip()), reason="reason_required")

        budget = ctx.resolve(order.budget)       # ObjectRef[Budget], type-checked, policy-checked
        ctx.call(
            "finance.reserve_budget",
            budget=budget,
            amount=order.amount,
            expectedVersion=budget.version,
        )

        ctx.uow.register_mutation(
            order,
            status="APPROVED",
            expectedVersion=order.version,
        )
        return {"order": order.ref, "status": "APPROVED"}
```

`order.budget` trả `ObjectRef[Budget]` vì link là `navigable` và `Budget` đã export; `reads` phải chứa `Budget` thì `ctx.resolve` mới được phép chạm. Nếu Finance gỡ `Budget` khỏi `exports`, lỗi xuất hiện ở pha Link chứ không phải lúc chạy.

Diff khai báo, không có mục nào bị xóa hay đổi kiểu:

| Khai báo | `1.0.0` | `1.1.0` | Loại thay đổi |
| --- | --- | --- | --- |
| `version` | `1.0.0` | `1.1.0` | Tăng version |
| `params` | `order`, `reason` | Không đổi | Không đổi |
| `reads` | `[PurchaseOrder]` | `+ Budget` | Thêm |
| `writes` | `[PurchaseOrder]` | Không đổi | Không đổi |
| `calls` | Không có | `["finance.reserve_budget"]` | Thêm |
| `commitRequirement` | Không khai báo | `ATOMIC` | Thêm |
| `permission` | `purchase_order.approve` | Không đổi | Không đổi |

Hệ quả bắt buộc của Nấc 2:

- **Một session vật lý.** `PurchaseOrder` và `Budget` cùng enlisted trong một transaction đang mở duy nhất; engine commit một lần sau revalidate. Hai connection tới cùng brand database nhưng enlistment tách đôi vẫn không phải atomic.
- **Không có thoái lui âm thầm.** Provider không share transaction thì deployment binding từ chối `NoSharedTransaction`. Saga/outbox không phải cách thỏa `ATOMIC`; muốn trạng thái "đang chờ giữ ngân sách" phải công bố contract nghiệp vụ khác.
- **Child `REJECTED` hủy toàn bộ execution.** Ngân sách không đủ thì không đơn nào bị ghi; không tồn tại trạng thái "đã duyệt nhưng chưa giữ tiền".
- **Child được ghim phiên bản.** Root manifest ghim `finance.reserve_budget@1.0.0#<digest>`; resume/retry dùng đúng revision đã ghim, không lấy latest ngầm định.

#### Ủy quyền thu hẹp (narrowed delegation)

`ctx.delegation` là descriptor do engine sinh cho đúng lần gọi đã khai báo, không phải credential:

- Phạm vi gồm: execution cha, action đích `finance.reserve_budget`, instance `Budget:B-001`, permission `budget.reserve`, hạn hiệu lực và chuỗi principal.
- Engine kiểm tra lại descriptor **trước mỗi lần dùng**; descriptor không chuyển nhượng, không serialize ra ngoài, không dùng lại cho action khác.
- Child chạy dưới principal ủy quyền down-scoped từ requester: không kế thừa toàn bộ quyền của parent, không dùng admin/service identity.
- Quyền không tự tăng khi qua ranh giới module. Requester thiếu `budget.reserve` thì child bị `DENIED` và execution dừng trước commit — không ghi một phần, không nâng quyền.
- Deployment binding từ chối mapping ủy quyền rộng hơn `calls` + `permission` đã khai báo; ambient service identity là lỗi binding, không phải lựa chọn triển khai.

### 3.3 Ranh giới Nấc 3 và Nấc 4

Nấc 3 bổ sung `approval` và `effects`; Nấc 4 bổ sung quy tắc version và pin. Cả hai chỉ **thêm** thuộc tính khai báo: `params`, `reads`, `writes`, `calls`, `permission` và chữ ký `handler(ctx, ...)` của Nấc 1–2 giữ nguyên. Tài liệu này không đặc tả hành vi treo/tiếp tục, cấu trúc `Approval`, giao effect hay bảng SemVer.

## 4. HandlerCtx và scoped Unit of Work

`ctx` là bề mặt duy nhất author chạm trong handler. Mọi thứ khác — authorization, transaction, provider, audit — do engine sở hữu.

### 4.1 Bề mặt dương

| Thành phần | Dạng | Ngữ nghĩa | Khi vi phạm |
| --- | --- | --- | --- |
| `ctx.principal` | `Principal`, read-only | Principal đã xác thực của requester; không phải approver, không phải service identity | Không ghi được; không có setter |
| `ctx.delegation` | `Delegation`, read-only | Descriptor ủy quyền thu hẹp cho các `calls` đã khai báo: action đích, instance, permission, hạn | Engine kiểm lại mỗi lần dùng; hết hạn/không khớp → `DENIED` cho child |
| `ctx.resolve(ref)` | `ObjectRef[T] → T` | Resolve instance đúng type, chỉ trong `reads` đã khai báo; handle mang `version` | Ref sai type hoặc ngoài `reads` → lỗi invoke, fail closed |
| `ctx.call(action_id, **params)` | `str, ... → ChildResult` | Gọi child đã khai báo trong `calls`, cùng UoW, dưới delegation thu hẹp | Action không khai báo → fail closed ở invoke-time |
| `ctx.require(condition, reason=...)` | `bool, str → None` | Precondition nghiệp vụ; `False` → `REJECTED` mang `reason` | Không phải lỗi hệ thống; không tạo `DENIED` |
| `ctx.uow.register_mutation(obj, **fields, expectedVersion=...)` | Mutation plan entry | Đăng ký ý định ghi; engine revalidate rồi apply guarded trong một statement | `expectedVersion` lệch hoặc guard fail → `StalePlan`; không ghi đè |

`ctx.uow.enqueue_effect(...)` thuộc Nấc 3: nó chỉ xuất hiện khi declaration khai báo `effects`.

### 4.2 Ranh giới âm

Handler **không** có và không được tự tạo:

- Raw database connection, session, driver hay SQL client; không có `cursor`, không có connection string.
- Provider/IAM credential, service account, bearer token hay ambient service identity.
- `ctx.uow.commit()` hoặc `ctx.uow.rollback()` — commit là quyết định của engine sau revalidate.
- Đường đọc/ghi bỏ qua engine: không `list_raw`, không `count_unfiltered`, không duyệt link `internal`.
- Import adapter/backend hoặc gọi ERP/HTTP trực tiếp từ handler.

In-process trust boundary **không** phải sandbox: các bảo đảm đến từ khai báo + binding + revalidation + guard của backend, không từ việc handler bị cô lập.

### 4.3 Phân vai author và engine

| Việc | Author | Engine |
| --- | --- | --- |
| Khai báo phụ thuộc (`reads`, `writes`, `calls`) | Có | Kiểm tra kiểu/export, cấp đúng phạm vi chạm |
| Resolve object | Gọi `ctx.resolve` | Type check, policy check live, gắn version |
| Transaction | Không | Mở scoped UoW trên enlisted session, revalidate, commit một lần |
| Concurrency | Nêu `expectedVersion` | Guarded apply; `rowcount != 1` → `StalePlan` |
| Authorization | Khai `permission` | Kiểm tra live ở invoke, callback và mỗi lần dùng delegation |
| Audit | Không | Ghi decision, manifest đã ghim, `before/after` |

## 5. Ma trận kiểm tra tĩnh

### 5.1 Ba pha

| Pha | Câu hỏi duy nhất | Chạm dữ liệu? |
| --- | --- | --- |
| Load | Definition đọc được, identity duy nhất, cú pháp hợp lệ? | Không |
| Link | Mọi reference (`ObjectRef`, `reads`, `writes`, `calls`, link target) phân giải được, đúng kiểu, được export? | Không |
| Deployment binding | Provider đã bind có cung cấp đúng bảo đảm đã hứa (capability + enlistment plan)? | Không, chỉ đọc binding artifact |
| Invoke | Principal, world state và version hiện tại có cho phép không? | Có |

Mỗi pha từ chối lỗi thuộc về mình; không dồn xuống pha sau, không gộp Link với Deployment binding.

### 5.2 Lỗi bị chặn trước runtime

| Lỗi | Ví dụ kích hoạt | Pha | Hành vi | Cách sửa |
| --- | --- | --- | --- | --- |
| `DuplicateIdentity` | Module cũ còn import và khai báo lại `procurement.approve_purchase_order` | Load | Từ chối toàn bộ load, không vào Link | Xóa hoặc đổi identity của definition trùng |
| `UnresolvedReference` | `calls = ["finance.reserve_budget_typo"]`, `reads = [Budgett]` | Link | Từ chối bind | Sửa reference về identity có thật |
| `NotExported` | `calls = ["finance.internal_policy"]` hoặc `Link`/`reads` trỏ tới type Finance không export | Link | Từ chối bind | Export identity đó, hoặc đi qua action đã export |
| `NoSharedTransaction` | `PurchaseOrder@postgres` + `Budget@erp` với `commitRequirement = ATOMIC` | Deployment binding | Từ chối contract atomic **trước khi ghi** | Đổi provider có chung enlisted session, hoặc ký contract khác (saga/outbox) |

Ba lỗi đầu giải quyết được bằng sửa khai báo; lỗi thứ tư là bất khả thi của hạ tầng, không phải lỗi gõ. Trường hợp deployment binding còn phải từ chối: mapping ủy quyền rộng hơn `calls` + `permission` đã khai báo.

Những gì **không** thuộc kiểm tra tĩnh, phải chờ invoke: principal còn quyền không, đơn còn ở trạng thái duyệt được không, ngân sách còn đủ không, `expectedVersion` còn khớp không. Đây là các cửa `DENIED`, `REJECTED`, `StalePlan` — không thể dời lên Load/Link/binding vì chưa chạm dữ liệu.

### 5.3 Ranh giới trung thực

Static layer **chỉ tin khai báo**. Những đường sau vô hình với Load/Link/binding:

- Handler tự mở connection bằng driver, tự giữ credential lấy từ biến môi trường hoặc file.
- Import lén module khác, `getattr` động, gọi action theo chuỗi tính toán ở runtime.
- Đọc file/socket, gọi HTTP/ERP trực tiếp, dùng global state của host.

Không có tuyên bố "phát hiện toàn cục" cho các đường này. Biện pháp bù là review, test, quyền của database role/provider bị giới hạn ngoài phạm vi đã khai báo và audit ở tầng provider; AST scan nếu có chỉ là cảnh báo, không phải bảo đảm.

Bind cũng **không đọc thân handler**: đổi logic trong handler mà giữ nguyên contract không bị IR diff phát hiện. Vì vậy handler digest là một phần của artifact đã publish, và mọi thay đổi thân phải publish version mới kèm digest mới.

Ngoài phạm vi tài liệu này: an toàn đọc/query (`UnsupportedSecureQuery`), cấu trúc `ActionResult`/`ExecutionRecord`, và hợp đồng `query → invoke` phía consumer.

## 6. Liên kết

- [Architecture Direction](./architecture-direction.md) — nguyên tắc module sở hữu nghiệp vụ, quyền không tự tăng qua ranh giới module.
- [Framework Design v0.1](./framework-design-v0.1.md) — meta-model compact, `HandlerCtx`, scoped UoW, strict atomic và ma trận lỗi đầy đủ.
- [Static Architecture and Definition Lifecycle](../deep-dives/01-static-architecture-and-definition-lifecycle.md) — load/link/binding, identity vs host name, exports, undeclared dependency.
- [Action Contract and Business Workflow](../deep-dives/03-action-contract-and-business-workflow.md) — `DENIED`/`REJECTED`/`AWAITING_APPROVAL`, authority và ủy quyền thu hẹp.
- [Engine Boundary and Adapter Capabilities](../deep-dives/04-engine-boundary-and-adapter-capabilities.md) — enlistment plan, `NoSharedTransaction`, local atomic vs split backend.
