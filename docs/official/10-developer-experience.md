# Part X — Developer Experience

*[← Part IX — Adapter Architecture and Platform Independence](09-adapter-architecture.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part XI — AI Agent Integration →](11-ai-agent-integration.md)*

<a id="sec-50"></a>

## 50. Developer Experience là mục tiêu cốt lõi

Một phần động lực ban đầu đến từ trải nghiệm khó phát triển và khó theo dõi ontology bằng TTL, SHACL và PROV-O.

Do đó, developer experience không nên được xem là một tính năng bổ sung sau khi framework đã hoàn thành.

Nó phải là một architectural requirement ngay từ đầu.

Framework cần giúp developer:

- Đọc và hiểu business domain từ source code.
- Navigate từ Object sang Links, Actions và Policies liên quan.
- Tận dụng IDE, type checking và autocomplete.
- Viết business logic bằng programming language quen thuộc.
- Test business rules mà không cần deploy toàn bộ hệ thống.
- Review ontology changes thông qua Git.
- Phát hiện breaking changes và dependencies.
- Inspect runtime behavior và debug execution.
- Sinh metadata, documentation và diagrams tự động.

Nếu framework buộc developer duy trì hàng chục files, schemas và mappings cho một Object Type đơn giản, chúng ta sẽ tái tạo chính vấn đề ban đầu.

<a id="sec-51"></a>

## 51. Developer-facing API

Developer experience mà chúng ta hình dung có thể bắt đầu bằng:

```
pip install ontology-framework
```

Định nghĩa business domain:

```
from ontology import (    ObjectType,    Action,    ObjectRef,    LinkOne,    Ontology,    Runtime)
```

```
class Customer(ObjectType):    id: str    name: strclass Order(ObjectType):    id: str    customer_id: str    amount: Decimal    status: OrderStatus    customer: LinkOne[Customer]
```

```
class ApproveOrder(Action):    order: ObjectRef[Order]    reason: str    permission = "order.approve"    def validate(self, ctx):        order = ctx.resolve(self.order)        ctx.require(            order.status == OrderStatus.PENDING        )    def execute(self, ctx):        order = ctx.resolve(self.order)        ctx.update(            order,            status=OrderStatus.APPROVED        )
```

Đăng ký definitions:

```
ontology = Ontology("sales")ontology.register(    Customer,    Order,    ApproveOrder)
```

Bind infrastructure:

```
runtime = Runtime(    ontology=ontology,    data=SQLAlchemyDataProvider(...),    authorization=PolicyProvider(...),    transaction=SQLAlchemyTransactionProvider(...),    audit=AuditProvider(...))
```

Expose consumer interfaces:

```
runtime.to_fastapi()runtime.to_mcp()runtime.to_sdk()
```

Toàn bộ API trên là minh họa cho developer experience mong muốn. Package, methods và adapters chưa tồn tại như một implementation chính thức của dự án.

<a id="sec-52"></a>

## 52. Repository Organization

Một repository enterprise ontology có thể được tổ chức theo domain.

**enterprise-ontology/**

domains/

sales/

objects.py

links.py

actions.py

functions.py

policies.py

procurement/

objects.py

actions.py

finance/

objects.py

policies.py

shared/

interfaces.py

value_types.py

bindings/

adapters/

tests/

migrations/

generated/

ontology.json

sdk/

ontology.toml

Cách tổ chức này không cần bị framework áp đặt hoàn toàn. Một domain nhỏ có thể được định nghĩa trong một file duy nhất.

Framework nên hỗ trợ modularization mà không tạo boilerplate không cần thiết.

<a id="sec-53"></a>

## 53. Ontology Development Lifecycle

1

**Define**

Viết Object, Link, Action và Policy bằng code.

2

**Inspect**

Extract metadata, types và dependencies.

3

**Validate**

Kiểm tra static model, references, capabilities.

4

**Test**

Test business semantics và execution behavior.

5

**Review**

Git pull request và semantic diff.

6

**Publish**

Đóng gói version của ontology và handlers.

7

**Integrate**

Generate hoặc expose SDK, API, agent tools.

8

**Observe**

Theo dõi runtime executions, audit và failures.

Ontology nên tham gia software development lifecycle tương tự application code, thay vì trở thành một collection metadata được chỉnh sửa thủ công mà khó quản lý dependencies.

<a id="sec-54"></a>

## 54. Static Validation

Framework có thể phát hiện một số lỗi trước khi deploy.

| Validation                | Ví dụ lỗi                                           |
| ------------------------- | --------------------------------------------------- |
| Duplicate type IDs        | Hai Objects có cùng canonical name                  |
| Invalid property type     | Property tham chiếu Value Type không tồn tại        |
| Broken Link               | Target Object Type không tồn tại                    |
| Invalid mapping           | Source field không hợp lệ                           |
| Interface mismatch        | Object không implement required properties          |
| Action parameter mismatch | Handler và parameter schema không tương thích       |
| Unknown permission        | Action tham chiếu permission chưa đăng ký           |
| Dependency errors         | Tham chiếu domain hoặc function không tồn tại       |
| Capability mismatch       | Action yêu cầu write nhưng datasource chỉ read-only |
| Breaking changes          | Xóa property đang được consumer contract sử dụng    |

Không phải mọi business constraint hoặc arbitrary Python logic đều có thể được kiểm chứng statically.

Framework cần kết hợp static validation, runtime validation và automated tests.

<a id="sec-55"></a>

## 55. Semantic Diff

Git diff chỉ cho biết source code đã thay đổi như thế nào.

Ontology semantic diff nên cho biết business contract đã thay đổi như thế nào.

Ví dụ:

```
Ontology: procurement
Version: 1.3.0 -> 1.4.0
+ ObjectType: ApprovalRecord
+ LinkType:
  PurchaseOrder.approvalRecords
~ PurchaseOrder.amount
  Type: integer -> decimal
~ ApprovePurchaseOrder
  Permission:
  procurement.employee -> procurement.manager
+ ApprovePurchaseOrder
  Approval requirement for high-value orders
- PurchaseOrder.legacyId
Potential breaking changes: 2
Security-related changes: 2
```

Semantic diff có thể được sử dụng cho code review, impact analysis, compatibility checks và migration planning.

Đây là một tính năng có giá trị lớn đối với maintainability.

Tuy nhiên, chỉ metadata và dependencies đã đăng ký mới có thể được phân tích một cách đáng tin cậy. Arbitrary executable code hoặc external consumers không khai báo dependency sẽ giới hạn khả năng impact analysis.

<a id="sec-56"></a>

## 56. Ontology Visualization

Khi Objects, Links, Functions, Actions và Policies có metadata thống nhất, framework có thể tự động sinh visualization.

Không nhất thiết chỉ sinh knowledge graph truyền thống.

Object

Action

Policy

Các views khác nhau có thể gồm structural graph, Action dependency graph, policy graph, data binding lineage, domain composition graph và runtime execution trace.

Không nhất thiết phải phát triển một enterprise visual editor. Generated diagrams hoặc lightweight inspection tools có thể đủ giá trị ban đầu.

<a id="sec-57"></a>

## 57. Testing

Một trong những lợi thế của code-first ontology là khả năng test theo software engineering practices.

Ví dụ:

```
def test_cannot_approve_cancelled_order(runtime):    order = create_order(        status=OrderStatus.CANCELLED    )    result = runtime.actions.validate(        ApproveOrder,        order=order.ref    )    assert not result.valid
```

Các test categories có thể gồm:

| Test                         | Mục đích                                |
| ---------------------------- | --------------------------------------- |
| Definition tests             | Schema, type, link correctness          |
| Business logic tests         | Functions và Action handlers            |
| Authorization tests          | Allowed và denied principals            |
| Action lifecycle tests       | Validation, commit, failure             |
| Transaction tests            | Rollback, atomicity                     |
| Adapter contract tests       | Backend implementation đáp ứng contract |
| Concurrency tests            | Tránh state transitions không hợp lệ    |
| Consumer compatibility tests | SDK, API, tool schema                   |
| Ontology migration tests     | Schema evolution và data compatibility  |

In-memory providers có thể hỗ trợ local development và testing. Tuy nhiên, transaction và concurrency guarantees vẫn cần integration tests trên backend thực tế.
