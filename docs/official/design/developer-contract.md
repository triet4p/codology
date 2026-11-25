# Developer Contract

*Đặc tả bề mặt author cho OaC: author phải khai báo gì, mặc định cái gì là nội bộ, engine bảo đảm điều gì, và lỗi nào bị chặn trước khi chạy. Phạm vi tài liệu: Nấc 1 (action đồng bộ đơn module), Nấc 2 (liên module nguyên tử + ủy quyền thu hẹp) và Nấc 3 (chờ duyệt, revalidation khi resume, effect sau commit). Mọi code là đặc tả contract minh họa, chưa phải syntax cuối.*

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
| 3 | `approval`, `effects`, `ctx.uow.enqueue_effect` | Treo/tiếp tục execution trên manifest ghim, revalidate live khi resume, outbox cùng enlisted session | Đặc tả trong tài liệu này (mục 4) |
| 4 | Không thêm primitive; chỉ đổi version/ngữ nghĩa | Semantic diff, pin manifest, compat | Ngoài phạm vi: quy tắc versioning thuộc tài liệu tiến hóa |

Ví dụ xuyên suốt: `procurement.approve_purchase_order` (viết tắt `ApprovePurchaseOrder`) leo `1.0.0 → 1.1.0` khi cần giữ ngân sách thuộc `finance`, rồi `1.1.0 → 2.0.0` khi cần người khác duyệt theo ngưỡng và phát effect sau commit. Hợp đồng người gọi (`query`/`invoke`/`approve`/`reconcile`) nằm ở [Consumer Contract](./consumer-contract.md); quy tắc versioning thuộc tài liệu tiến hóa.

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

| Trường | Nấc 1 | Nấc 2 | Nấc 3 | Ý nghĩa |
| --- | --- | --- | --- | --- |
| `identity` | Bắt buộc | Không đổi | Không đổi | `<domain>.<snake_name>`; đổi là breaking |
| `version` | Bắt buộc | `1.0.0 → 1.1.0` | `1.1.0 → 2.0.0` | SemVer của definition đã publish |
| `params` | Bắt buộc | Không đổi | Không đổi | Tham số có kiểu: `ObjectRef[T]`, Value, scalar |
| `reads` | Bắt buộc | `+ Budget` | Không đổi | ObjectType định đọc; kiểm tra export/kiểu, cấp quyền chạm |
| `writes` | Bắt buộc | Không đổi | Không đổi | ObjectType định ghi; mọi ghi đi qua UoW |
| `permission` | Bắt buộc | Không đổi | Không đổi | Permission string, kiểm tra live mỗi lần invoke |
| `handler` | Bắt buộc | Thân đổi | Thân thêm một lệnh `enqueue_effect` | Nghiệp vụ thuần trên object đã resolve |
| `calls` | Không có | `["finance.reserve_budget"]` | Không đổi | Cạnh phụ thuộc liên module tường minh |
| `commitRequirement` | Không khai báo | `CommitRequirement.ATOMIC` | Không đổi | Bảo đảm commit trên nhiều resource |
| `approval` | Không có | Không có | `Approval.conditional(...)` | Điều kiện chờ duyệt có cấu trúc (mục 4.2) |
| `effects` | Không có | Không có | `[NotifyWarehouseOrderApproved]` | Outbox intent phát sau commit (mục 4.5) |

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

Nấc 3 bổ sung `approval` và `effects`, đặc tả ở mục 4. Nấc 4 bổ sung quy tắc version và pin, ngoài phạm vi tài liệu này. Cả hai chỉ **thêm** khai báo (thuộc tính Action và declaration effect), không đổi cấu trúc cốt lõi: `params`, `reads`, `writes`, `calls`, `permission` và chữ ký `handler(ctx, ...)` của Nấc 1–2 giữ nguyên — mục 4.1 chứng minh bằng diff.

## 4. Nấc 3 — quản trị bất đồng bộ: `approval`, resume, `effects`

Nghiệp vụ đòi thêm hai thứ Nấc 2 không có: người khác requester duyệt đơn theo ngưỡng tiền, và thông báo kho/ERP sau khi đơn đã duyệt. Author thêm **hai thuộc tính khai báo** và **một câu lệnh** trong handler; engine nhận phần còn lại — treo execution, ghim manifest, mở lại UoW, revalidate live và giao effect sau commit.

### 4.1 Leo thang cộng thêm `1.1.0 → 2.0.0`

```python
# procurement/actions.py — 2.0.0
class ApprovePurchaseOrder(Action):
    identity = "procurement.approve_purchase_order"
    version = "2.0.0"

    order: ObjectRef[PurchaseOrder]
    reason: str

    reads = [PurchaseOrder, Budget]
    writes = [PurchaseOrder]
    calls = ["finance.reserve_budget"]
    permission = "purchase_order.approve"
    commitRequirement = CommitRequirement.ATOMIC

    approval = Approval.conditional(                  # + Nấc 3
        when=Param("order").normalized_amount >= Money(100_000, "USD"),
        role="finance_director",
        self_approval=False,
    )
    effects = [NotifyWarehouseOrderApproved]          # + Nấc 3

    def handler(self, ctx, order: PurchaseOrder, reason: str):
        ctx.require(order.status == "PENDING", reason="purchase_order_not_pending")
        ctx.require(bool(reason.strip()), reason="reason_required")

        budget = ctx.resolve(order.budget)
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
        ctx.uow.enqueue_effect(                       # + Nấc 3
            NotifyWarehouseOrderApproved,
            payload=OrderApprovedPayload(order=order.ref, approved_amount=order.amount),
        )
        return {"order": order.ref, "status": "APPROVED"}
```

Ba thứ được thêm, không thứ nào sửa Nấc 1–2:

- `approval`: điều kiện chờ duyệt có cấu trúc để static layer và engine đọc được — không phải `if` trong handler.
- `effects`: danh sách effect đã khai báo; handler chỉ được enqueue đúng những effect này.
- Một lệnh `ctx.uow.enqueue_effect(...)` trong thân handler; chữ ký handler, `params`, `reads`, `writes`, `calls`, `permission` giữ nguyên.

Diff khai báo qua ba nấc:

| Khai báo | `1.0.0` | `1.1.0` | `2.0.0` | Loại thay đổi |
| --- | --- | --- | --- | --- |
| `version` | `1.0.0` | `1.1.0` | `2.0.0` | Tăng version |
| `params` | `order`, `reason` | Không đổi | Không đổi | Không đổi |
| `reads` | `[PurchaseOrder]` | `+ Budget` | Không đổi | Thêm ở Nấc 2 |
| `writes` | `[PurchaseOrder]` | Không đổi | Không đổi | Không đổi |
| `calls` | Không có | `["finance.reserve_budget"]` | Không đổi | Thêm ở Nấc 2 |
| `commitRequirement` | Không khai báo | `ATOMIC` | Không đổi | Thêm ở Nấc 2 |
| `permission` | `purchase_order.approve` | Không đổi | Không đổi | Không đổi |
| `approval` | Không có | Không có | `Approval.conditional(...)` | Thêm ở Nấc 3 |
| `effects` | Không có | Không có | `[NotifyWarehouseOrderApproved]` | Thêm ở Nấc 3 |
| Chữ ký `handler` | `(ctx, order, reason)` | Không đổi | Không đổi | Không đổi |
| Thân `handler` | Precondition + mutation + return | `+` resolve/call child | `+` một lệnh enqueue | Chỉ cộng thêm |

Phần thay đổi duy nhất của Nấc 3 trong thân handler:

```python
# 1.1.0
        ctx.uow.register_mutation(
            order,
            status="APPROVED",
            expectedVersion=order.version,
        )
        return {"order": order.ref, "status": "APPROVED"}

# 2.0.0 — thêm đúng một lệnh, không nhánh mới, không vòng lặp
        ctx.uow.register_mutation(
            order,
            status="APPROVED",
            expectedVersion=order.version,
        )
        ctx.uow.enqueue_effect(NotifyWarehouseOrderApproved, payload=...)
        return {"order": order.ref, "status": "APPROVED"}
```

Điều **không** xuất hiện ở bất kỳ nấc nào: `state`, `transition`, `while`, `await`, `sleep`, `retry`, node/edge của workflow graph, scheduler, job queue, hay bảng "pending approvals" do author tự quản. Handler vẫn là một hàm nghiệp vụ chạy từ đầu đến cuối.

Viết điều kiện duyệt trong handler là sai contract:

```python
# SAI — trạng thái do author quản, engine không kiểm tra được, consumer không đọc được requiredApproval
if order.amount >= 100_000:
    return {"status": "PENDING_APPROVAL"}
```

`approval` là khai báo cho static layer và engine; trạng thái `AWAITING_APPROVAL` do execution record của engine sinh ra, không phải giá trị `return` của handler.

### 4.2 `Approval` — điều kiện có cấu trúc, tiền tệ tường minh

```python
approval = Approval.conditional(
    when=Param("order").normalized_amount >= Money(100_000, "USD"),
    role="finance_director",
    self_approval=False,
)
```

| Trường | Bắt buộc | Ngữ nghĩa | Kiểm tra |
| --- | --- | --- | --- |
| `when` | Có | Predicate cấu trúc trên tham số/field có kiểu | Load: chỉ toán tử cấu trúc; ngoài tập → `UnsupportedApprovalExpression` |
| `role` | Có | Vai trò approver phải có, tách khỏi quyền invoke của requester | Load: string khai báo; callback: kiểm live |
| `self_approval` | Có | `False` = requester không được duyệt execution của chính mình | Load: boolean; callback: kiểm live; không có default ngầm |

Giới hạn của `when`:

- Chỉ toán tử cấu trúc trên field có kiểu: so sánh (`>`, `>=`, `<`, `<=`, `==`, `!=`) và `and`/`or`/`not`. Tập này serialize và diff được.
- Lambda, method call, `getattr`, biểu thức Python tuỳ ý bị từ chối ở pha Load — chúng không thể hiện được trong manifest, semantic diff hay audit.
- Ngưỡng tiền tệ phải tường minh đơn vị. Ba cách hợp lệ: property khai `comparisonUnit` rồi so trên `normalized_amount`; literal `Money(100_000, "USD")`; hoặc `Function` read-only trả `Money`.
- `normalized_amount` trong ví dụ là derived view read-only (property có `comparisonUnit` hoặc `Function` ở mục 2.3), không phải field do handler tự tính.

```python
class NormalizedAmount(Function):
    """Read-only view: quy đổi theo comparisonUnit, không mutation, không approval."""

    identity = "finance.normalized_amount"
    version = "1.0.0"
    order: ObjectRef[PurchaseOrder]
    result = Money

    def evaluate(self, ctx, order: PurchaseOrder) -> Money:
        ...
```

Quy tắc tiền tệ:

- Khi `source_currency != target_currency`, material intent và audit ghi `source_currency`, `target_currency`, `quote_version` — đủ để tái hiện phép so sánh.
- Không bắt buộc một FX subsystem toàn cục; bắt buộc là khai báo đủ nguồn/đích/phiên bản quy đổi.
- `100_000 VND` và `100_000 USD` không được đi cùng một luồng: so sánh tiền thiếu đơn vị là lỗi contract, không phải chi tiết implementation.

Hai authority tách biệt:

| Vai | Principal | Cần gì tại cửa của mình | Không được |
| --- | --- | --- | --- |
| Requester | người gọi `invoke` | `permission` của action + precondition nghiệp vụ | Tự duyệt khi `self_approval=False`; cấp cho mình quyền approver |
| Approver | người gọi callback `approve` | Role `finance_director` **và** permission còn hiệu lực tại thời điểm callback (live check) | Sửa material intent, đổi số tiền hay đối tượng |
| Engine | — | Kiểm tra cả hai authority, ghi audit cả hai principal | Hard-code ngưỡng, role hay `self_approval` |

Quy tắc authority:

1. **Hai authority, một execution record.** Requester tạo execution; approver thỏa `requiredApproval`. Audit ghi cả hai principal và mọi callback bị từ chối, tách khỏi lịch sử transition của execution.
2. **Callback sai thẩm quyền không kết thúc execution.** Callback bị `DENIED` chỉ ghi audit cho callback đó; execution vẫn `AWAITING_APPROVAL`.
3. **`self_approval=False` là policy khai báo của domain.** Engine từ chối callback của chính requester ở cửa callback. Đổi thành `self_approval=True` với cùng ngưỡng và cùng role thì callback đó thành công — chứng minh đây là khai báo domain, không phải luật core.
4. **Core chỉ có cơ chế.** Tách vai, kiểm live, ghi audit là core; ngưỡng tiền, tên role và lệnh cấm tự duyệt là policy của Procurement/Finance.

### 4.3 Tạm dừng `AWAITING_APPROVAL`: không transaction, manifest ghim, material intent

`when` trả `True` và execution chưa có approval hợp lệ thì engine **không** commit và **không** giữ transaction:

1. **Authorize + resolve.** Requester qua cửa permission; tham số và `reads` resolve dưới policy hiện tại.
2. **Chạy handler trong UoW preview.** `ctx.require` rớt → `REJECTED` ngay, không ghi gì. Mutation và effect chỉ được *đăng ký*, chưa apply.
3. **Đánh giá ngưỡng.** Engine so `approval.when` trên material intent. Sai → đi tiếp đường Nấc 2 (revalidate rồi commit).
4. **Treo.** Đúng → engine hủy UoW preview (không commit, không giữ session, row lock hay connection), persist execution record cùng manifest và material intent, trả `AWAITING_APPROVAL` kèm `requiredApproval`.
5. **Không có gì chờ trong RAM.** Worker chết, deploy mới hay vài giờ trôi qua đều không mất execution: trạng thái nằm trong record bền, không trong transaction.

Bốn thứ được persist khi treo:

| Thành phần | Nội dung | Vì sao phải ghim |
| --- | --- | --- |
| Root manifest | `actionVersion=2.0.0`, `ontologyVersion`, handler artifact digest, `finance.reserve_budget@1.0.0#<digest>`, revision của `effects` | Resume nạp đúng bytes đã được duyệt, không lấy "latest" ngầm định |
| Material intent | `normalized_amount`, `source_currency`, `target_currency`, `quote_version`, `expectedVersion` của `PurchaseOrder`, phạm vi child (`Budget:B-001`, số tiền, `budget.reserve`) | Approval duyệt đúng thứ sẽ commit; đổi material là duyệt lại |
| Required approval | `approvalId`, role, requester principal, hạn hiệu lực | Callback key, kiểm hạn/thu hồi, audit |
| Execution | `executionId`, status `AWAITING_APPROVAL`, request key, input đã canonical | Idempotency, `reconcile`, audit |

Mutation plan của lần invoke đầu **không** phải nguồn sự thật: nó bị hủy cùng UoW preview và được tính lại khi resume. Chỉ material intent và manifest là cam kết bền. Outbox row enqueue trong preview cũng bị hủy — không effect nào rời hệ thống từ một execution chưa commit.

### 4.4 Tiếp tục: callback, UoW mới, recompute trên logic ghim, revalidate live

1. **Cửa callback.** `approve`/`reject` mang `executionId` + `approvalId` (callback key riêng, không dùng request key của `invoke`). Engine kiểm role, permission live và policy `self_approval`; callback rớt → `DENIED` cho callback đó, execution không đổi trạng thái.
2. **Hiệu lực approval.** Hết hạn hoặc bị thu hồi → không commit; execution quay về `AWAITING_APPROVAL` (chờ duyệt lại) hoặc `DENIED`/`REJECTED` tùy cửa rớt, audit ghi approval nào, version nào và vì sao.
3. **UoW mới.** Engine mở một scoped UoW **mới** trên enlisted session đã bind; không tái sử dụng session cũ (không còn session nào để tái sử dụng).
4. **Recompute, không replay plan.** Handler chạy lại từ đầu bằng đúng handler artifact digest và đúng child revision trong manifest; `ctx.require`, `ctx.resolve`, `ctx.call` được đánh giá lại trên world hiện tại.
5. **Revalidate live.** Requester và approver còn quyền không; đơn còn `PENDING` và đúng `version` không; budget còn đủ và đúng balance version không.
6. **So material intent.** Trùng khớp → apply guarded mutation + outbox row + execution record, commit **một lần**. Khác material → không commit: execution quay lại `AWAITING_APPROVAL` với intent mới để duyệt lại, hoặc `REJECTED`/`DENIED` nếu cửa tương ứng rớt.
7. **Child có approval riêng.** Nếu `finance.reserve_budget` cũng khai báo `approval`, parent vẫn `AWAITING_APPROVAL` cho tới khi child được duyệt; approval của child không thay thế approval của parent và ngược lại.

| Điều kiện khi resume | Kết quả | Ghi chú |
| --- | --- | --- |
| Approval hợp lệ, material không đổi, guard khớp | `COMMITTED` | Outbox row cùng transaction |
| Material đổi (số tiền, version object, phạm vi child) | `AWAITING_APPROVAL` với intent mới | Approval cũ hết hiệu lực; audit giữ cả hai |
| Approval hết hạn hoặc bị thu hồi | `AWAITING_APPROVAL` chờ duyệt lại; `DENIED`/`REJECTED` nếu cửa tương ứng rớt | Không commit trên approval đã chết |
| Precondition nghiệp vụ rớt | `REJECTED` | Không ghi gì |
| `expectedVersion` lệch, guard `rowcount != 1` | `StalePlan` | Re-read/recompute; không ghi đè |
| Approver mất quyền trước commit | `DENIED` | Không commit lặng lẽ |
| Callback không đủ thẩm quyền | `DENIED` cho callback | Execution vẫn `AWAITING_APPROVAL` |

Hệ quả bắt buộc cho author — handler chạy lại từ đầu, nhiều lần:

- Phải deterministic theo `params` + world: không đọc clock, random, biến môi trường, file hay network.
- Không giữ state giữa hai lần chạy; không tự đánh dấu "đã duyệt" trong biến, cache hay property.
- Không giả định mutation plan lần trước còn hiệu lực; engine tính lại từ đầu.
- Effect chỉ đi qua `ctx.uow.enqueue_effect`; gọi ERP/HTTP trực tiếp trong handler vi phạm cả Nấc 1.

### 4.5 `effects` — outbox intent trong cùng session, giao sau commit

Effect là phần tử của `effects[]` trong meta-model v0.1: một declaration có identity/version/payload, **không** có vòng đời riêng như `ObjectType`.

```python
class OrderApprovedPayload(Value):
    order: ObjectRef[PurchaseOrder]
    approved_amount: Money


class NotifyWarehouseOrderApproved(Effect):
    identity = "procurement.warehouse_order_approved"
    version = "1.0.0"
    payload = OrderApprovedPayload
    dedupKey = ("order",)          # tùy chọn; mặc định là (executionId, identity)
```

| Trường | Bắt buộc | Ngữ nghĩa | Kiểm tra |
| --- | --- | --- | --- |
| `identity` | Có | `<domain>.<snake_name>`, ổn định như Action | Load: duy nhất; phải export nếu module khác tham chiếu |
| `version` | Có | SemVer của payload + dedup contract | Pin trong manifest của execution |
| `payload` | Có | Value type có kiểu; chứa `ObjectRef`/Value, không chứa handle sống | Link: mọi type resolve và được export |
| `dedupKey` | Không (có mặc định) | Khóa chống trùng bền; khai báo khi effect phải dedup xuyên execution | Deployment binding phải cung cấp `effectDedup` |

Hợp đồng enqueue:

- `ctx.uow.enqueue_effect(effect, payload=...)` chỉ hợp lệ với effect nằm trong `effects`; effect không khai báo → fail closed ở invoke, giống `ctx.call` với action ngoài `calls`.
- Enqueue ghi **outbox intent row trong cùng enlisted session** với business state, execution record và uniqueness của idempotency key — cùng một transaction, không phải "gửi ngay".
- Payload chụp giá trị tại thời điểm commit (`ObjectRef` + Value), không phải object sống. Engine bổ sung envelope: `executionId`, `actionVersion`, approver khi có, và dedup id bền.
- Không network/HTTP/ERP trong handler; không `await notify()`; không tự retry.

Hợp đồng giao sau commit:

- Relay chạy **sau khi commit**, at-least-once. Broker ack không đồng nghĩa effect đã được xử lý; duplicate là bình thường và được chặn bằng dedup id bền hoặc inbox cùng transaction ở phía nhận.
- Trạng thái effect tách khỏi trạng thái execution: `PENDING` → `DELIVERED`, hoặc `PENDING_RETRY` → `FAILED` khi hết retention hoặc không retry được.

| Sự kiện | Execution | Effect | Được làm |
| --- | --- | --- | --- |
| Commit thành công | `COMMITTED` | `PENDING` → `DELIVERED` | Relay, retry có key |
| Relay lỗi tạm thời | `COMMITTED` | `PENDING_RETRY` | Retry effect, giữ execution |
| Relay lỗi vĩnh viễn | `COMMITTED` | `FAILED` | Compensation hoặc can thiệp tay theo effect |
| Handler ném lỗi trước commit | `FAILED`/`REJECTED` | Không tồn tại | Không effect nào được giao |

Đánh dấu execution `FAILED` vì một effect lỗi sau commit, hay chạy lại handler để "gửi lại" thông báo, đều sai contract: nó xóa ranh giới giữa cam kết nghiệp vụ và giao thông báo.

### 4.6 Ma trận trách nhiệm author và engine

| Pha | Author khai báo / viết | Engine bảo đảm | Author không được làm |
| --- | --- | --- | --- |
| Khai báo, load, link, binding | `approval`, `effects`, `Effect`/payload type, `calls`, `permission` | Kiểm cấu trúc predicate, export/kiểu của payload, capability outbox + `effectDedup` của binding | Lambda/biểu thức Python tuỳ ý; enqueue effect không khai báo; dựa vào default ngầm cho `self_approval` |
| Invoke lần đầu | Handler thuần: precondition, mutation intent, một lệnh `enqueue_effect` | Authorize requester, resolve theo policy, chạy UoW preview, đánh giá `when`, sinh execution record | Tự trả `PENDING_APPROVAL`; tự ghi trạng thái duyệt; gọi backend ngoài |
| Tạm dừng `AWAITING_APPROVAL` | Không viết gì | Hủy UoW preview, không giữ session/row lock, persist manifest + material intent + `requiredApproval` | Giữ transaction mở; lưu state duyệt vào biến toàn cục |
| Callback + resume | Không viết gì | Dedup callback key, kiểm role + permission live + policy `self_approval`; mở UoW mới, recompute trên manifest ghim, revalidate world, so material intent | Tự xử lý callback; giả định plan cũ còn hiệu lực; đọc clock/random/network trong handler |
| Commit nguyên tử | Nêu `expectedVersion` | Apply guarded mutation + outbox row + execution record trong một transaction, commit một lần; material đổi → reapproval | Commit/rollback tay; ghi đè khi guard fail |
| Relay sau commit | Không viết gì | Giao at-least-once với dedup bền; giữ execution `COMMITTED` khi effect lỗi | Rollback hay re-approve vì effect lỗi; gửi effect từ handler |

### 4.7 Ranh giới và seam mở

- **Không thêm primitive.** `approval` và `effects` là trường đã có trong meta-model v0.1 của Action; `Effect` chỉ là hình dạng phần tử `effects[]`, không có vòng đời riêng và không phải node mới.
- **Consumer contract tách riêng.** Cấu trúc `ActionResult`/`ExecutionRecord`, dữ liệu trả về ở `AWAITING_APPROVAL`, hợp đồng `query`/`invoke`/`approve`/`reconcile` và ma trận kết quả/lỗi thuộc [Consumer Contract](./consumer-contract.md); mục này chỉ chốt phần author nhìn thấy.
- **Versioning tách riêng.** Khi nào thêm `approval`/`effects` buộc MINOR hay MAJOR (ví dụ đổi action đồng bộ thành có `AWAITING_APPROVAL`) thuộc tài liệu tiến hóa.
- **Provider capability thuộc engine boundary.** Declaration có `effects` mà binding không cung cấp outbox cùng session và `effectDedup` thì deployment binding từ chối trước khi chạy (`EffectContractUnsupported`), không downgrade lặng lẽ.

## 5. HandlerCtx và scoped Unit of Work

`ctx` là bề mặt duy nhất author chạm trong handler. Mọi thứ khác — authorization, transaction, provider, audit — do engine sở hữu.

### 5.1 Bề mặt dương

| Thành phần | Dạng | Ngữ nghĩa | Khi vi phạm |
| --- | --- | --- | --- |
| `ctx.principal` | `Principal`, read-only | Principal đã xác thực của requester; không phải approver, không phải service identity | Không ghi được; không có setter |
| `ctx.delegation` | `Delegation`, read-only | Descriptor ủy quyền thu hẹp cho các `calls` đã khai báo: action đích, instance, permission, hạn | Engine kiểm lại mỗi lần dùng; hết hạn/không khớp → `DENIED` cho child |
| `ctx.resolve(ref)` | `ObjectRef[T] → T` | Resolve instance đúng type, chỉ trong `reads` đã khai báo; handle mang `version` | Ref sai type hoặc ngoài `reads` → lỗi invoke, fail closed |
| `ctx.call(action_id, **params)` | `str, ... → ChildResult` | Gọi child đã khai báo trong `calls`, cùng UoW, dưới delegation thu hẹp | Action không khai báo → fail closed ở invoke-time |
| `ctx.require(condition, reason=...)` | `bool, str → None` | Precondition nghiệp vụ; `False` → `REJECTED` mang `reason` | Không phải lỗi hệ thống; không tạo `DENIED` |
| `ctx.uow.register_mutation(obj, **fields, expectedVersion=...)` | Mutation plan entry | Đăng ký ý định ghi; engine revalidate rồi apply guarded trong một statement | `expectedVersion` lệch hoặc guard fail → `StalePlan`; không ghi đè |
| `ctx.uow.enqueue_effect(effect, payload=...)` | Outbox intent entry | Đăng ký effect đã khai báo trong `effects`; ghi outbox row cùng enlisted session khi commit | Effect không khai báo → fail closed ở invoke; effect lỗi sau commit không đổi execution (mục 4.5) |

`ctx.uow.enqueue_effect(...)` chỉ xuất hiện khi declaration khai báo `effects`; nó không phải đường gửi thông báo ngay và không mở transaction riêng.

### 5.2 Ranh giới âm

Handler **không** có và không được tự tạo:

- Raw database connection, session, driver hay SQL client; không có `cursor`, không có connection string.
- Provider/IAM credential, service account, bearer token hay ambient service identity.
- `ctx.uow.commit()` hoặc `ctx.uow.rollback()` — commit là quyết định của engine sau revalidate.
- Đường đọc/ghi bỏ qua engine: không `list_raw`, không `count_unfiltered`, không duyệt link `internal`.
- Import adapter/backend hoặc gọi ERP/HTTP trực tiếp từ handler.

In-process trust boundary **không** phải sandbox: các bảo đảm đến từ khai báo + binding + revalidation + guard của backend, không từ việc handler bị cô lập.

### 5.3 Phân vai author và engine

| Việc | Author | Engine |
| --- | --- | --- |
| Khai báo phụ thuộc (`reads`, `writes`, `calls`) | Có | Kiểm tra kiểu/export, cấp đúng phạm vi chạm |
| Resolve object | Gọi `ctx.resolve` | Type check, policy check live, gắn version |
| Transaction | Không | Mở scoped UoW trên enlisted session, revalidate, commit một lần |
| Concurrency | Nêu `expectedVersion` | Guarded apply; `rowcount != 1` → `StalePlan` |
| Authorization | Khai `permission` | Kiểm tra live ở invoke, callback và mỗi lần dùng delegation |
| Ngưỡng duyệt | Khai `approval` | Đánh giá `when` trên material intent, giữ execution khi treo (mục 4.3) |
| Effect | Khai `effects`, enqueue trong handler | Ghi outbox cùng session, relay sau commit (mục 4.5) |
| Audit | Không | Ghi decision, manifest đã ghim, approver, `before/after` |

## 6. Ma trận kiểm tra tĩnh

### 6.1 Ba pha

| Pha | Câu hỏi duy nhất | Chạm dữ liệu? |
| --- | --- | --- |
| Load | Definition đọc được, identity duy nhất, cú pháp hợp lệ? | Không |
| Link | Mọi reference (`ObjectRef`, `reads`, `writes`, `calls`, link target) phân giải được, đúng kiểu, được export? | Không |
| Deployment binding | Provider đã bind có cung cấp đúng bảo đảm đã hứa (capability + enlistment plan)? | Không, chỉ đọc binding artifact |
| Invoke | Principal, world state và version hiện tại có cho phép không? | Có |

Mỗi pha từ chối lỗi thuộc về mình; không dồn xuống pha sau, không gộp Link với Deployment binding.

### 6.2 Lỗi bị chặn trước runtime

| Lỗi | Ví dụ kích hoạt | Pha | Hành vi | Cách sửa |
| --- | --- | --- | --- | --- |
| `DuplicateIdentity` | Module cũ còn import và khai báo lại `procurement.approve_purchase_order` | Load | Từ chối toàn bộ load, không vào Link | Xóa hoặc đổi identity của definition trùng |
| `UnresolvedReference` | `calls = ["finance.reserve_budget_typo"]`, `reads = [Budgett]` | Link | Từ chối bind | Sửa reference về identity có thật |
| `NotExported` | `calls = ["finance.internal_policy"]` hoặc `Link`/`reads` trỏ tới type Finance không export | Link | Từ chối bind | Export identity đó, hoặc đi qua action đã export |
| `UnsupportedApprovalExpression` | `when=lambda order: order.amount > 100_000`, method call hay `getattr` trong predicate | Load | Từ chối load | Viết lại bằng toán tử cấu trúc trên field có kiểu (mục 4.2) |
| `NoSharedTransaction` | `PurchaseOrder@postgres` + `Budget@erp` với `commitRequirement = ATOMIC` | Deployment binding | Từ chối contract atomic **trước khi ghi** | Đổi provider có chung enlisted session, hoặc ký contract khác (saga/outbox) |
| `EffectContractUnsupported` | `effects = [NotifyWarehouseOrderApproved]` nhưng binding thiếu outbox cùng session hoặc `effectDedup` | Deployment binding | Từ chối declaration có `effects` trước khi chạy | Bổ sung capability provider, hoặc bỏ effect khỏi contract |

Bốn lỗi đầu giải quyết được bằng sửa khai báo; `NoSharedTransaction` và `EffectContractUnsupported` là bất khả thi của hạ tầng, không phải lỗi gõ. Trường hợp deployment binding còn phải từ chối: mapping ủy quyền rộng hơn `calls` + `permission` đã khai báo.

Những gì **không** thuộc kiểm tra tĩnh, phải chờ invoke: principal còn quyền không, đơn còn ở trạng thái duyệt được không, ngân sách còn đủ không, `expectedVersion` còn khớp không, `approval.when` có đúng trên dữ liệu thật không. Đây là các cửa `DENIED`, `REJECTED`, `AWAITING_APPROVAL`, `StalePlan` — không thể dời lên Load/Link/binding vì chưa chạm dữ liệu. Việc enqueue một effect không nằm trong `effects` cũng là lỗi invoke-time (fail closed): bind không đọc thân handler.

### 6.3 Ranh giới trung thực

Static layer **chỉ tin khai báo**. Những đường sau vô hình với Load/Link/binding:

- Handler tự mở connection bằng driver, tự giữ credential lấy từ biến môi trường hoặc file.
- Import lén module khác, `getattr` động, gọi action theo chuỗi tính toán ở runtime.
- Đọc file/socket, gọi HTTP/ERP trực tiếp, dùng global state của host.

Không có tuyên bố "phát hiện toàn cục" cho các đường này. Biện pháp bù là review, test, quyền của database role/provider bị giới hạn ngoài phạm vi đã khai báo và audit ở tầng provider; AST scan nếu có chỉ là cảnh báo, không phải bảo đảm.

Bind cũng **không đọc thân handler**: đổi logic trong handler mà giữ nguyên contract không bị IR diff phát hiện. Vì vậy handler digest là một phần của artifact đã publish, và mọi thay đổi thân phải publish version mới kèm digest mới.

Ngoài phạm vi tài liệu này: an toàn đọc/query (`UnsupportedSecureQuery`), cấu trúc `ActionResult`/`ExecutionRecord`, và hợp đồng `query → invoke` phía consumer — xem [Consumer Contract](./consumer-contract.md).

## 7. Liên kết

- [Architecture Direction](./architecture-direction.md) — nguyên tắc module sở hữu nghiệp vụ, quyền không tự tăng qua ranh giới module.
- [Framework Design v0.1](./framework-design-v0.1.md) — meta-model compact, `HandlerCtx`, scoped UoW, strict atomic, pin manifest và ma trận lỗi đầy đủ.
- [Consumer Contract](./consumer-contract.md) — bề mặt `query`/`invoke`/`approve`/`reconcile`, ba thực thể, envelope `COMMITTED`/`AWAITING_APPROVAL`, callback/re-approval và ma trận hành động consumer.
- [Static Architecture and Definition Lifecycle](../deep-dives/01-static-architecture-and-definition-lifecycle.md) — load/link/binding, identity vs host name, exports, undeclared dependency.
- [Developer Workflow and Model Evolution](../deep-dives/02-developer-workflow-and-model-evolution.md) — ngưỡng `>`/`>=`, tiền tệ và cách semantic diff phân loại thay đổi.
- [Action Contract and Business Workflow](../deep-dives/03-action-contract-and-business-workflow.md) — `DENIED`/`REJECTED`/`AWAITING_APPROVAL`, authority, material intent và ủy quyền thu hẹp.
- [Engine Boundary and Adapter Capabilities](../deep-dives/04-engine-boundary-and-adapter-capabilities.md) — enlistment plan, `NoSharedTransaction`, outbox/relay, local atomic vs split backend.
