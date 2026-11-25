# Part IV — System Architecture

*[← Part III — Project Scope and Product Positioning](03-scope-and-product-positioning.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part V — Ontology Meta-Model →](05-ontology-meta-model.md)*

<a id="sec-13"></a>

## 13. High-level Reference Architecture

Đây là kiến trúc tổng hợp phù hợp nhất với những gì chúng ta đã thống nhất cho đến thời điểm hiện tại.

Ontology as Code — Reference Architecture v0.1

### Consumer Layer

Application

Human

AI Agent

Automation

**Consumer Interfaces**

Python SDK

REST API

GraphQL

MCP

## Operational Ontology Layer

**Developer-defined Domain**

Objects

Properties

Relations

Interfaces

Actions

Functions

Policies

Constraints

Mappings

**Ontology Meta-model & Registry**

Type system

Definitions

Dependency graph

Canonical metadata

**Embeddable Ontology Engine**

Object resolution

Query orchestration

Action lifecycle

Function execution

Policy enforcement

Validation

Mutation coordination

Audit & effects

Execution Context · Identity · Lifecycle Hooks

**Provider / Adapter Contracts**

Data

Identity

Policy

Transaction

Effects

Audit

### Existing Infrastructure

DB / Lakehouse

IAM / Policy

ERP / Services

Event Bus

Workflow Engine

Audit Storage

Developer Tooling hoạt động xuyên suốt: CLI, compilation, validation, testing, visualization, semantic diff và code generation.

Kiến trúc này có năm boundary chính.

| Boundary       | Trách nhiệm                                                                |
| -------------- | -------------------------------------------------------------------------- |
| Authoring      | Developer định nghĩa business domain                                       |
| Meta-model     | Chuẩn hóa ý nghĩa và metadata của definitions                              |
| Execution      | Thực thi operation theo các semantics đã định nghĩa                        |
| Infrastructure | Cung cấp cơ chế truy vấn, lưu trữ, identity, transaction, workflow thực tế |
| Consumer       | Cung cấp interfaces cho application, human, AI                             |

Các boundary là logical boundaries. Không nhất thiết chúng phải tương ứng với năm services khác nhau.

Một implementation nhỏ hoàn toàn có thể nằm trong một Python package và chạy trong một application process.

<a id="sec-14"></a>

## 14. Kiến trúc tĩnh và kiến trúc động

### 14.1. Static architecture

Kiến trúc tĩnh quan tâm tới việc ontology được định nghĩa, tổ chức và biểu diễn như thế nào.

```
Source Code
    │
    ├── Object Definitions
    ├── Relation Definitions
    ├── Interface Definitions
    ├── Function Definitions
    ├── Action Definitions
    ├── Policy Definitions
    └── Data Bindings
    │
    ▼
Meta-model / Introspection
    │
    ▼
Validated Registry
    │
    ├── Canonical Metadata
    ├── Dependency Graph
    ├── Type Information
    └── Execution Contracts
```

Static architecture cần trả lời được:

- Có những Object Types nào?
- Mỗi Object Type có properties và relations nào?
- Các Actions nhận những parameter types nào?
- Action phụ thuộc vào những Objects, Functions hoặc Actions nào?
- Policy nào được áp dụng?
- Ontology có thay đổi breaking contract không?
- Backend cần những capabilities nào?

### 14.2. Dynamic architecture

Kiến trúc động quan tâm tới cách ontology hoạt động tại runtime.

Simplified action execution sequence. Các bước approval, retries, auditing và external effects chưa được biểu diễn đầy đủ.

Runtime sử dụng metadata và executable contracts để resolve object, kiểm tra quyền, xác thực input, thực thi nghiệp vụ và điều phối backend.

Điều này tạo ra sự liên kết giữa static model và operational behavior.

<a id="sec-15"></a>

## 15. Logical planes

Có thể phân chia Ontology Layer thành hai plane nội bộ.

| Plane           | Nội dung                                                                         |
| --------------- | -------------------------------------------------------------------------------- |
| Control Plane   | Definitions, type system, registry, metadata, dependencies, policies, versioning |
| Execution Plane | Object resolution, query, action, function, authorization, mutation, audit       |

Cách phân chia này hữu ích cho research và thiết kế module.

Tuy nhiên, chúng ta không mặc định phải triển khai control plane và execution plane thành các distributed services.

<a id="sec-16"></a>

## 16. Phân chia trách nhiệm giữa Framework và Developer

Đây là boundary rất quan trọng để kiểm soát scope.

| Thành phần   | Framework sở hữu                  | Developer / Platform sở hữu    |
| ------------ | --------------------------------- | ------------------------------ |
| Object Types | Type system và semantics          | Định nghĩa business objects    |
| Properties   | Typed property contracts          | Properties cụ thể              |
| Relations    | Link model, cardinality           | Logical và physical mappings   |
| Identity     | Object reference protocol         | Canonical key strategy         |
| Queries      | Query abstraction                 | Backend thực hiện query        |
| Actions      | Lifecycle, invocation contract    | Business operation logic       |
| Functions    | Invocation và execution context   | Domain computation             |
| Policies     | Enforcement points                | Business rules và provider     |
| Transactions | Transaction contract              | Database transaction mechanism |
| Effects      | Effect model, orchestration hooks | External systems               |
| Audit        | Execution records và audit schema | Storage và retention strategy  |
| Metadata     | Registry, validation              | Ontology configuration         |
| Deployment   | Runtime integration contract      | Deployment environment         |
| APIs / SDK   | Consumer contract generation      | Application architecture       |

Framework không được chỉ đơn thuần khai báo rằng một operation là transactional hay secure rồi để developer tự hiểu.

Nó cần định nghĩa ý nghĩa chính xác của các requirements, kiểm tra adapter capabilities và thực thi những guarantees mà nó thực sự có thể cung cấp.
