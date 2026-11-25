# Part VI — Action Model: The Core of Operational Ontology

*[← Part V — Ontology Meta-Model](05-ontology-meta-model.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part VII — Governance and Security Model →](07-governance-and-security-model.md)*

<a id="sec-26"></a>

## 26. Tại sao Action không đơn giản là Function?

Đây là một trong những phần quan trọng nhất của toàn bộ dự án.

Một function thông thường có thể được mô tả bằng contract:

```
Input → Computation → Output
```

Một operational Action có contract rộng hơn:

```
Principal
+ Intent
+ Parameters
+ Current World State
+ Business Policies
        │
        ▼
Governed State Transition
        │
        ▼
New World State
+ Effects
+ Execution Record
```

Action mô tả một cách hợp lệ để tác động lên operational world.

Ví dụ `ApprovePurchaseOrder` không đơn thuần là:

```
order.status = "APPROVED"
```

Nó có thể phải kiểm tra budget, supplier, role, approval requirements, current state, concurrency, transaction boundaries và các external side effects.

<a id="sec-27"></a>

## 27. Anatomy of an Action

| Thành phần        | Câu hỏi cần giải quyết                             |
| ----------------- | -------------------------------------------------- |
| Identity          | Action được gọi bằng ID nào?                       |
| Description       | Ý nghĩa nghiệp vụ của Action?                      |
| Parameters        | Input types và required values?                    |
| Target Objects    | Action tác động vào đối tượng nào?                 |
| Principal         | Ai hoặc hệ thống nào thực thi?                     |
| Authorization     | Principal có quyền gọi Action không?               |
| Preconditions     | Những điều kiện nào phải đúng trước execution?     |
| Invariants        | Những điều kiện nào luôn phải được duy trì?        |
| Read Scope        | Action được phép đọc dữ liệu nào?                  |
| Write Scope       | Action được phép sửa những objects nào?            |
| Handler           | Business logic cụ thể nằm ở đâu?                   |
| Mutation Plan     | Những state changes dự kiến là gì?                 |
| Approval          | Có yêu cầu human approval không?                   |
| Transaction       | Thay đổi nào phải atomic?                          |
| Concurrency       | Xử lý simultaneous execution ra sao?               |
| Idempotency       | Nếu request bị gửi nhiều lần thì sao?              |
| Effects           | Có gọi API, gửi event hoặc notification không?     |
| Failure Semantics | Nếu một phần execution thất bại thì sao?           |
| Retry Policy      | Khi nào có thể thực thi lại an toàn?               |
| Postconditions    | Trạng thái cuối cùng phải đáp ứng điều kiện gì?    |
| Audit             | Ai đã làm gì, khi nào và kết quả thế nào?          |
| Provenance        | Quyết định dựa vào dữ liệu và logic nào?           |
| Versioning        | Action definition version nào được sử dụng?        |
| Discoverability   | Human và AI tìm thấy Action bằng cách nào?         |
| Presentation      | Input form hoặc tool schema được biểu diễn ra sao? |

Không phải mọi Action đều cần sử dụng toàn bộ các thành phần trên.

Framework nên có defaults hợp lý cho Action đơn giản và extension points cho Action phức tạp.

<a id="sec-28"></a>

## 28. Action Definition, Implementation và Engine

Ba thành phần này cần được phân biệt rõ.

### Action Definition

Declarative contract

Parameters, permission, constraints, write scope, execution requirements.

### Action Engine

Framework responsibility

Authorization, validation, lifecycle, execution context, commit coordination, audit.

### Action Implementation

Developer responsibility

Domain-specific decisions, calculations and proposed state changes.

Developer nên tập trung vào nghiệp vụ thay vì phải tự viết lặp lại các cross-cutting concerns như authorization, transaction management và audit trong từng Action.

Một conceptual DSL:

```
@action(    name="Approve Purchase Order",    permission="purchase_order.approve",    transaction=Transaction.atomic(),    idempotency=Idempotency.required(),    approval=Approval.conditional(        when=Param("order").amount > 100_000,        role="finance_director"    ))class ApprovePurchaseOrder(Action):    order: ObjectRef[PurchaseOrder]    reason: str    reads = [PurchaseOrder, Budget, Supplier]    writes = [PurchaseOrder, Budget]    def validate(self, ctx):        order = ctx.resolve(self.order)        ctx.require(            order.status == Status.PENDING        )        ctx.require(            order.budget.available >= order.amount        )    def execute(self, ctx):        order = ctx.resolve(self.order)        ctx.update(            order,            status=Status.APPROVED        )
```

Trong ví dụ này, `ctx.update()` và `ctx.increment()` có thể tạo Mutation Plan thay vì cập nhật dữ liệu ngay lập tức.

Việc Action được biểu diễn bằng class, decorated function hay một declarative workflow vẫn là quyết định về language design. Chúng ta chưa chốt syntax nào.

<a id="sec-29"></a>

## 29. Action Lifecycle

Action có thể có lifecycle riêng, đặc biệt khi liên quan tới approval, asynchronous operations hoặc external systems.

Candidate lifecycle. Trạng thái, transition rules và failure semantics cần được thiết kế chính thức.

Một Action đơn giản có thể thực thi đồng bộ trong một transaction.

Một Action phức tạp có thể cần chờ phê duyệt, thực thi lại hoặc chuyển sang workflow backend.

Điều framework nên chuẩn hóa là lifecycle contract, không nhất thiết tự hiện thực hóa một durable workflow engine.

<a id="sec-30"></a>

## 30. ActionExecution như một thực thể có identity

Mỗi lần gọi Action có thể tạo một execution instance.

```
execution = ontology.actions.invoke(    action="procurement.approve_purchase_order",    parameters={        "order": "PO-001",        "reason": "Supplier verified"    })
```

Kết quả:

```
{
  "executionId": "exec-001",
  "action": "procurement.approve_purchase_order",
  "actionVersion": "1.2.0",
  "ontologyVersion": "2.1.0",
  "principal": "employee-123",
  "status": "AWAITING_APPROVAL",
  "requiredApproval": {
    "role": "finance_director"
  }
}
```

Execution record có thể được sử dụng cho tracking, cancellation nếu được hỗ trợ, approval, error inspection, retries và audit.

Một ý tưởng đáng nghiên cứu là `ActionExecution` cũng có thể trở thành một Object trong system ontology.

Khi đó, developer và AI có thể sử dụng chính ontology để truy vấn những gì đã xảy ra trong hệ thống.

```
ActionExecution.objects.filter(    action="procurement.approve_purchase_order",    status="FAILED")
```

Nhưng việc hỗ trợ persistent execution instances cho mọi Action có thể tạo thêm overhead. Framework có thể cho phép execution modes đơn giản hơn.

<a id="sec-31"></a>

## 31. Mutation Plan

Mutation Plan là một abstraction đặc biệt có giá trị đối với operational ontology.

Thay vì cho handler trực tiếp thực hiện mọi state change, handler mô tả các thay đổi dự kiến dưới dạng structured operations.

Ví dụ:

```
{
  "mutations": [
    {
      "operation": "update",
      "object": "PurchaseOrder:PO-001",
      "expectedVersion": 12,
      "changes": {
        "status": "APPROVED"
      }
    },
    {
      "operation": "increment",
      "object": "Budget:B-001",
      "property": "reserved",
      "value": 50000
    }
  ],
  "effects": [
    {
      "type": "event",
      "name": "purchase_order.approved"
    }
  ]
}
```

**Action Handler**

Domain logic

## Mutation Plan

Proposed changes and external effects

Preview

Validate

Approve

Audit

**Commit Coordination**

Revalidation · Concurrency · Transaction · Effects

Structured Mutation Plan tạo điều kiện cho các khả năng như dry run, preview, approval, change inspection, write scope validation, audit và AI safety.

Tuy nhiên, Mutation Plan không tự động đảm bảo execution thành công.

Giữa thời điểm lập plan và commit, world state có thể thay đổi. Runtime phải revalidate những assumptions liên quan hoặc sử dụng phù hợp các concurrency guarantees của backend.

Ngoài ra, không phải mọi external operation đều có thể biểu diễn một cách đầy đủ dưới dạng mutation trên Objects. Vì vậy, Mutation Plan nên được nghiên cứu như một execution model quan trọng, chưa nhất thiết là cách duy nhất để implement mọi Action.

<a id="sec-32"></a>

## 32. Transaction và Consistency

Một Action có thể thay đổi nhiều Objects:

```
ApprovePurchaseOrder
    ├── Update PurchaseOrder.status
    ├── Reserve Budget
    └── Create ApprovalRecord
```

Nếu tất cả Objects sử dụng cùng một transactional backend, framework có thể delegate atomic commit cho backend đó.

Nếu Budget nằm trong ERP còn PurchaseOrder nằm trong PostgreSQL, một database transaction đơn lẻ không thể đảm bảo atomicity cho cả hai.

| Trường hợp                 | Cơ chế có thể sử dụng                    |
| -------------------------- | ---------------------------------------- |
| Một relational database    | Native database transaction              |
| Concurrent updates         | Optimistic locking hoặc database locking |
| Database + event bus       | Transactional outbox                     |
| External API call          | Idempotency, retry, failure tracking     |
| Nhiều independent services | Saga hoặc compensation                   |
| Long-running operation     | Durable workflow provider                |

Đây là các implementation strategies có thể tích hợp, không phải những thứ framework buộc phải tự xây dựng.

Framework cần định nghĩa capabilities và requirements.

Ví dụ Action yêu cầu atomic mutation trên hai Objects, nhưng data provider không hỗ trợ shared transaction thì framework phải từ chối execution hoặc yêu cầu developer cấu hình một strategy phù hợp. Không nên silently downgrade guarantee.

<a id="sec-33"></a>

## 33. Effects và Failure Handling

State mutation và external side effects nên được phân biệt.

```
State mutation:
    Order.status = APPROVED
External effects:
    Send notification
    Publish event
    Notify ERP
```

Nếu notification thất bại sau khi database đã commit, việc đánh dấu toàn bộ Action là chưa xảy ra có thể gây hiểu nhầm.

Execution model nên có khả năng phân biệt business state đã commit với effects chưa hoàn thành.

Những vấn đề cần nghiên cứu gồm retry safety, idempotency keys, delivery semantics, failure records, cancellation và compensation.

Một Action không nên bị retry toàn bộ một cách mù quáng nếu một số side effects đã xảy ra.

<a id="sec-34"></a>

## 34. Action Composition

Khi Action này gọi Action khác, complexity tăng lên đáng kể.

```
Procurement Domain
    ApprovePurchaseOrder
            │
            ├── ValidateSupplier
            │
            └── ReserveBudget
                    │
                    ▼
Finance Domain
    Budget
    Reservation
    FinancialPolicy
```

Các câu hỏi cần giải quyết:

| Chủ đề                | Câu hỏi                                               |
| --------------------- | ----------------------------------------------------- |
| Authorization         | Action cha có quyền invoke Action con không?          |
| Principal propagation | Action con chạy dưới identity nào?                    |
| Delegation            | Có được sử dụng service identity thay user không?     |
| Transaction           | Các Actions có dùng chung transaction không?          |
| Approval              | Action con có thể yêu cầu approval riêng không?       |
| Failure               | Nếu Action con thất bại thì Action cha xử lý thế nào? |
| Audit                 | Parent-child execution được biểu diễn ra sao?         |
| Versioning            | Action cha tương thích với Action con version nào?    |
| Dependency            | Domain nào sở hữu operation và contract?              |

Đây là vấn đề **governed operation composition**, không chỉ là function composition.

Chúng ta chưa cần giải quyết toàn bộ composition semantics trong MVP, nhưng meta-model và engine contracts không nên loại bỏ khả năng này.
