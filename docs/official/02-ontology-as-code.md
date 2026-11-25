# Part II — Ontology as Code

*[← Part I — Project Vision](01-project-vision.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part III — Project Scope and Product Positioning →](03-scope-and-product-positioning.md)*

<a id="sec-5"></a>

## 5. Ý tưởng Ontology as Code

Thay vì xây dựng ontology chủ yếu thông qua các ngôn ngữ biểu diễn tri thức, chúng ta muốn developer có thể định nghĩa ontology bằng một programming language quen thuộc như Python hoặc TypeScript.

Tư tưởng này tương tự:

| Paradigm               | Đối tượng được lập trình        |
| ---------------------- | ------------------------------- |
| Infrastructure as Code | Infrastructure                  |
| Policy as Code         | Authorization policies          |
| Configuration as Code  | Configuration                   |
| Data Models as Code    | Data transformations và models  |
| API as Code            | Service interfaces              |
| **Ontology as Code**   | **Operational business models** |

Tuy nhiên, Ontology as Code không đơn giản là lưu ontology vào file code.

Chúng ta phân biệt hai cấp độ:

**Ontology stored as code:** Schema được lưu trong Python, JSON, YAML hoặc TypeScript.

**Ontology engineered as code:** Ontology trở thành một software artifact có thể được định nghĩa, validate, test, inspect, compose, version, review, deploy và execute.

Cấp độ thứ hai mới là mục tiêu của dự án.

<a id="sec-6"></a>

## 6. Tại sao OOP là một abstraction tự nhiên?

Operational ontology có nhiều điểm tương đồng với Object-Oriented Programming và Domain-Driven Design.

| Ontology concept   | Software engineering concept |
| ------------------ | ---------------------------- |
| Object Type        | Class / Entity definition    |
| Object             | Instance / Entity            |
| Property           | Typed attribute              |
| Link Type          | Association / Relationship   |
| Interface          | Interface / Protocol         |
| Value Type         | Value Object                 |
| Object Set         | Queryable collection         |
| Function           | Method / Domain service      |
| Action Type        | Command / Business operation |
| Precondition       | Business constraint          |
| Invariant          | Domain invariant             |
| Datasource Mapping | Repository / Data mapper     |
| Permission         | Authorization policy         |
| Object Reference   | Typed entity reference       |
| Ontology Module    | Domain module                |
| Ontology SDK       | Typed consumer interface     |

Ví dụ, developer có thể định nghĩa một domain bằng code:

```
class Customer(ObjectType):    id: str    name: str    credit_limit: Decimal    orders: LinkMany["Order"]class Order(ObjectType):    id: str    amount: Decimal    status: OrderStatus    customer: LinkOne[Customer]    items: LinkMany["OrderItem"]
```

Một developer đã quen Python, typing và ORM có thể đọc và hiểu phần lớn nội dung mà không phải học một representation language hoàn toàn mới.

IDE cũng có thể hỗ trợ autocomplete, type checking, navigation và refactoring.

Tất cả API và syntax trong tài liệu này đều là **conceptual DSL minh họa**, chưa phải implementation chính thức hoặc code đã được kiểm thử.

<a id="sec-7"></a>

## 7. Không nên đồng nhất Ontology với OOP

Mặc dù OOP là một authoring abstraction rất phù hợp, ontology có những semantics rộng hơn OOP thông thường.

| OOP thông thường                           | Operational Ontology                                           |
| ------------------------------------------ | -------------------------------------------------------------- |
| Object thường nằm trong application memory | Object có thể là logical representation của dữ liệu bên ngoài  |
| Class thường thuộc application code        | Object Type có thể được nhiều application chia sẻ              |
| Relationship có thể chỉ là attribute       | Relationship có metadata, cardinality và traversal semantics   |
| Method có thể trực tiếp thay đổi state     | Action cần execution boundary và governance                    |
| Collection thường đã được load             | Object Set có thể là lazy query trên hàng triệu records        |
| Access modifier thuộc programming language | Permission phụ thuộc vào runtime principal và business context |
| Object identity thuộc application          | Identity phải ổn định qua datasource và consumer               |
| Exception thường là runtime error          | Action failure có thể có lifecycle, audit và compensation      |

Do đó, chúng ta không xây một lớp OOP wrapper đơn giản trên database.

Chúng ta sử dụng OOP làm **developer-facing language**, đồng thời định nghĩa semantics riêng cho operational domain.

<a id="sec-8"></a>

## 8. Code-first, nhưng không nhất thiết code-only

Một kiến trúc đáng nghiên cứu là sử dụng native programming language làm authoring surface và canonical metadata làm machine-readable representation.

**Source of Truth**

## Ontology Source Code

Python / TypeScript

**Compiler / Introspection**

Extract · Resolve · Validate · Normalize

**Canonical Intermediate Representation**

## JSON Metadata

Typed definitions + executable references

Engine

SDK

AI Tools

RDF Export

Ví dụ canonical representation của Object Type:

```
{
  "id": "sales.order",
  "kind": "objectType",
  "primaryKey": "id",
  "properties": {
    "id": {
      "type": "string"
    },
    "amount": {
      "type": "decimal"
    },
    "status": {
      "type": "OrderStatus"
    }
  },
  "links": {
    "customer": {
      "target": "sales.customer",
      "cardinality": "many-to-one"
    }
  },
  "actions": [
    "sales.approve_order",
    "sales.cancel_order"
  ]
}
```

Canonical IR có thể phục vụ introspection, semantic diff, visualization, documentation generation, SDK generation và AI discovery.

Nhưng cần lưu ý JSON metadata không thể tự động biểu diễn đầy đủ arbitrary executable Python code. Nó có thể biểu diễn operation contract và tham chiếu tới handler đã được quản lý version.

### Separation of concerns

```
Declaration
    Mô tả những gì ontology có.
Implementation
    Định nghĩa logic nghiệp vụ cụ thể.
Execution
    Quy định và điều phối cách logic được thực thi.
```

Ba phần này có thể cùng được viết bằng Python, nhưng không nên bị trộn lẫn về trách nhiệm.

Việc có bắt buộc compiler riêng, JSON IR ngay từ MVP hay chỉ sử dụng in-process metadata registry vẫn là quyết định mở.
