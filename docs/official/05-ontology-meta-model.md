# Part V — Ontology Meta-Model

*[← Part IV — System Architecture](04-system-architecture.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part VI — Action Model: The Core of Operational Ontology →](06-action-model.md)*

<a id="sec-17"></a>

## 17. Meta-model là gì và tại sao quan trọng?

Meta-model định nghĩa những thành phần hợp lệ mà developer có thể sử dụng để xây dựng ontology.

Ví dụ:

```
Ontology Meta-model
    định nghĩa ObjectType là gì.
Enterprise Ontology
    định nghĩa PurchaseOrder là một ObjectType.
Runtime Object
    PurchaseOrder:PO-001 là một instance.
```

Đây là ba cấp độ cần phân biệt.

M2 — Meta-model

**ObjectType · LinkType · ActionType · Policy**

Framework định nghĩa các primitive và semantics.

instantiated by

M1 — Domain Model

**PurchaseOrder · Supplier · ApproveOrder**

Developer định nghĩa nghiệp vụ của tổ chức.

instantiated by

M0 — Operational World

**PO-001 · Supplier-032 · Execution-102**

Dữ liệu và execution instances thực tế.

Nếu thiết kế meta-model không tốt, developer-facing API có thể rất đẹp nhưng framework vẫn gặp vấn đề khi mở rộng, composition hoặc execution.

Do đó, chúng ta nên thiết kế **semantics trước syntax**.

<a id="sec-18"></a>

## 18. Candidate ontology primitives

Danh sách dưới đây là tập hợp các khái niệm đã xuất hiện trong quá trình thảo luận. Chưa phải tất cả đều đã được quyết định là first-class primitives.

| Nhóm          | Candidate primitive | Trách nhiệm                                 |
| ------------- | ------------------- | ------------------------------------------- |
| Structural    | Ontology            | Root domain model                           |
| Structural    | Module              | Tổ chức domain definitions                  |
| Structural    | ObjectType          | Định nghĩa business entity                  |
| Structural    | Property            | Thuộc tính có kiểu và ngữ nghĩa             |
| Structural    | LinkType            | Quan hệ giữa objects                        |
| Structural    | Interface           | Shared semantic contract                    |
| Structural    | ValueType           | Domain-specific data type                   |
| Reference     | ObjectRef           | Typed reference tới object                  |
| Reference     | ObjectSet           | Tập objects có thể truy vấn                 |
| Behavioral    | Function            | Logic hoặc computation                      |
| Behavioral    | ActionType          | Governed business operation                 |
| Behavioral    | Constraint          | Điều kiện phải được đảm bảo                 |
| Behavioral    | Event               | Biểu diễn sự kiện nghiệp vụ                 |
| Governance    | Principal           | Identity của actor                          |
| Governance    | Policy              | Authorization decision rules                |
| Governance    | Permission          | Khả năng thực hiện operation                |
| Governance    | Approval            | Yêu cầu phê duyệt                           |
| Binding       | DataSource          | Nguồn dữ liệu                               |
| Binding       | DataBinding         | Logical-to-physical mapping                 |
| Execution     | ExecutionContext    | Context được truyền trong execution         |
| Execution     | ActionExecution     | Instance của một lần thực thi               |
| Execution     | MutationPlan        | Tập state changes dự kiến                   |
| Execution     | Effect              | Tác động lên external systems               |
| Observability | AuditRecord         | Lịch sử operation                           |
| Observability | Provenance          | Nguồn gốc và căn cứ của dữ liệu, quyết định |

Một trong những nhiệm vụ research quan trọng là giảm danh sách này thành một tập primitives đủ nhỏ, có orthogonality tốt và có khả năng composition.

Không phải cứ một khái niệm xuất hiện trong nghiệp vụ là cần biến thành một primitive riêng trong framework.

<a id="sec-19"></a>

## 19. Object Type

Object Type mô tả một loại thực thể trong thế giới nghiệp vụ.

Ví dụ:

```
class PurchaseOrder(ObjectType):    id: str    supplier_id: str    amount: Decimal    currency: Currency    status: PurchaseOrderStatus    created_at: datetime    department_id: str    supplier: LinkOne["Supplier"]    budget: LinkOne["Budget"]    items: LinkMany["PurchaseOrderItem"]
```

Object Type cần cân nhắc các semantics sau:

| Thành phần          | Ý nghĩa                           |
| ------------------- | --------------------------------- |
| Type identity       | ID ổn định của Object Type        |
| Namespace           | Phân biệt objects giữa các domain |
| Primary key         | Xác định một object instance      |
| Properties          | Typed attributes                  |
| Required / Optional | Nullability và required fields    |
| Derived properties  | Thuộc tính được tính toán         |
| Relationships       | Các links được expose             |
| Interfaces          | Shared structural contract        |
| Data bindings       | Mapping tới datasource            |
| Constraints         | Điều kiện hợp lệ                  |
| Security metadata   | Read/write policy references      |
| Description         | Business meaning cho human và AI  |

Cần phân biệt Object Type với table schema.

Một table schema mô tả cấu trúc dữ liệu vật lý. Object Type mô tả cấu trúc logic của một thực thể nghiệp vụ.

Hai thứ có thể gần giống nhau trong hệ thống đơn giản, nhưng không nhất thiết ánh xạ một-một.

<a id="sec-20"></a>

## 20. Object Identity và Object Reference

Object identity là vấn đề cốt lõi khi abstraction nằm trên nhiều datasource.

Một `Customer` có thể tồn tại trong CRM, ERP và một ML feature store dưới các identifiers khác nhau.

**CRM**

CUST-102

Name, contact

**ERP**

ACCOUNT-87

Revenue, balance

**ML Store**

ENTITY-52

Churn score

**Identity Resolution & Data Binding**

**Customer: canonical-001**

name

CRM

contact

CRM

revenue

ERP

balance

ERP

churn_score

ML Store

Framework nên cung cấp một abstraction cho object identity và resolution. Tuy nhiên, nó không nhất thiết phải tự giải quyết toàn bộ entity matching và record linkage. Developer có thể cung cấp canonical identity hoặc sử dụng một upstream data integration process.

Một Object Reference có thể được hình dung như:

```
ObjectRef[Customer]("canonical-001")
```

Canonical representation có thể là:

```
{
  "objectType": "sales.customer",
  "objectId": "canonical-001"
}
```

ObjectRef khác với Object instance đã được load. Nó có thể chỉ là một typed handle dùng để resolve object khi cần.

<a id="sec-21"></a>

## 21. Property và Value Type

Property không đơn thuần là một column.

Ví dụ `amount` có thể mang những đặc điểm:

```
amount: Decimalcurrency: Currency
```

Hoặc được đóng gói thành một Value Type:

```
class Money(ValueType):    amount: Decimal    currency: Currency
```

Value Type giúp tái sử dụng các business semantics và validation.

Những ví dụ phù hợp gồm `Money`, `EmailAddress`, `GeoCoordinate`, `EmployeeId`, `DateRange` và `Percentage`.

Cần nghiên cứu thêm property-level metadata như units, descriptions, sensitivity, writable/read-only, derivation và provenance.

Một property computed từ ML model không nhất thiết có cùng freshness hay source authority với property được nhập trực tiếp từ ERP.

<a id="sec-22"></a>

## 22. Link Type

Relationship nên là first-class concept thay vì chỉ là object attribute.

Ví dụ:

```
@link_type(    source=PurchaseOrder,    target=Supplier,    cardinality="many-to-one")class PurchaseOrderSupplier:    source_key = "supplier_id"    target_key = "id"
```

Framework cần hiểu relationship ở cấp metadata để hỗ trợ:

| Khía cạnh          | Ý nghĩa                                      |
| ------------------ | -------------------------------------------- |
| Source và Target   | Hai Object Types tham gia                    |
| Cardinality        | One-to-one, one-to-many, many-to-many        |
| Direction          | Hướng traversal                              |
| Inverse link       | Quan hệ ngược                                |
| Mapping            | Foreign key, association table, API resolver |
| Constraints        | Referential integrity                        |
| Link authorization | Có được traverse relationship không          |
| Documentation      | Ý nghĩa nghiệp vụ của relationship           |

Link logical có thể được resolve bằng nhiều backend khác nhau.

Framework không nhất thiết phải xây một graph traversal engine cấp thấp; nó cần cung cấp semantics và query contract để adapter xử lý.

<a id="sec-23"></a>

## 23. Interface

Interface cho phép nhiều Object Types chia sẻ một semantic contract.

Ví dụ:

```
class Approveable(Interface):    status: ApprovalStatusclass PurchaseOrder(ObjectType, Approveable):    id: str    status: ApprovalStatusclass ExpenseRequest(ObjectType, Approveable):    id: str    status: ApprovalStatus
```

Điều này có thể hỗ trợ shared functions, generic queries hoặc Actions trên các nhóm objects.

Tuy nhiên, cần xác định rõ interface chỉ mô tả structural contract hay còn có behavioral contract. Khả năng inheritance, composition và polymorphic querying cũng chưa được chốt.

Không nên mang toàn bộ inheritance model của OOP sang ontology một cách máy móc.

<a id="sec-24"></a>

## 24. Object Set và Query Model

Một Object Set có thể đại diện cho một tập records rất lớn, không phải một Python list đã được load vào memory.

```
orders = (    PurchaseOrder.objects    .filter(status=Status.PENDING)    .filter(amount__gt=100_000)    .order_by("-created_at")    .limit(100))result = orders.fetch()
```

Framework có thể biểu diễn query bằng một query specification hoặc expression tree rồi chuyển cho data provider.

**ObjectSet Query**

Filter · Sort · Traverse · Aggregate

**Query Specification**

Logical types, expressions, authorization context

SQL Adapter

SQLAlchemy

Graph Adapter

Graph query

API Adapter

Remote request

SQLAlchemy là một ứng viên rất tốt để hiện thực hóa một relational backend.

Tuy nhiên, OaC không nên trở thành một ORM khác. Nó cần đặt abstraction ở mức Object Type, logical relationship, semantic query và governed access.

Các bài toán query optimization, distributed joins và query federation tổng quát có thể được delegate cho backend hoặc để ngoài scope ban đầu.

<a id="sec-25"></a>

## 25. Functions

Functions biểu diễn logic, computation hoặc business rules có thể tái sử dụng.

Ví dụ:

```
@functiondef calculate_credit_risk(customer: Customer) -> float:    exposure = (        customer.orders        .filter(status=OrderStatus.PENDING)        .sum("amount")    )    return float(exposure / customer.credit_limit)
```

Function model cần cân nhắc input/output types, object dependencies, context, permissions và side-effect semantics.

Một hướng thiết kế phù hợp là phân biệt:

| Loại             | Đặc điểm                                          |
| ---------------- | ------------------------------------------------- |
| Pure Function    | Tính toán từ input, không thay đổi external state |
| Read Function    | Có thể đọc Objects hoặc datasource                |
| Derived Function | Tính toán derived property                        |
| Action Helper    | Logic được gọi bên trong một Action               |

Đây là candidate classification, chưa phải type hierarchy đã được thống nhất.

Về nguyên tắc, nếu Function trực tiếp thay đổi trạng thái nghiệp vụ mà không đi qua Action boundary, framework có thể mất khả năng kiểm soát write permissions và audit.

Do đó, cần nghiên cứu rõ sự phân biệt giữa Functions và Actions.
