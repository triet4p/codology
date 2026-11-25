# Part XVI — Proof of Concept and MVP

*[← Part XV — Research Roadmap](15-research-roadmap.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part XVII — Evaluation and Success Criteria →](17-evaluation-and-success-criteria.md)*

<a id="sec-77"></a>

## 77. Mục đích của MVP

MVP không cần chứng minh rằng chúng ta có thể thay thế Palantir.

Nó cần chứng minh:

> Developer có thể định nghĩa một business domain bằng code, kết nối với infrastructure hiện có, rồi sử dụng chung business semantics và governed operations từ nhiều consumer với ít effort hơn.

Đây là tiêu chí quan trọng hơn số lượng features.

<a id="sec-78"></a>

## 78. Domain đề xuất: Procurement

Trong các ví dụ trước đó, Procurement là một domain tương đối phù hợp vì có đủ structural model, relationships, business logic, Actions, permissions, transaction và approval.

**Candidate Actions**

CreatePurchaseOrder

SubmitForApproval

ApprovePurchaseOrder

RejectPurchaseOrder

CancelPurchaseOrder

ReserveBudget

Business rules có thể bao gồm:

- PurchaseOrder chỉ được approve khi đang ở trạng thái pending.
- Principal phải có quyền phê duyệt theo department.
- Supplier phải đáp ứng các điều kiện nghiệp vụ.
- Budget còn đủ để reserve.
- Không được reserve budget hai lần cho cùng một approval.
- PurchaseOrder có giá trị cao có thể cần cấp phê duyệt bổ sung.
- Mọi operation cần execution record phù hợp.

Procurement chỉ là domain được đề xuất cho PoC. Chúng ta chưa chốt nó là benchmark domain chính thức.

<a id="sec-79"></a>

## 79. Một execution scenario hoàn chỉnh

Giả sử trạng thái ban đầu:

| Object               | Property  | Value   |
| -------------------- | --------- | ------- |
| PurchaseOrder:PO-001 | amount    | 50.000  |
| PurchaseOrder:PO-001 | status    | PENDING |
| Budget:B-001         | total     | 200.000 |
| Budget:B-001         | reserved  | 80.000  |
| Budget:B-001         | available | 120.000 |

Một principal có quyền approve yêu cầu thực hiện `ApprovePurchaseOrder`.

## Action Engine — Conceptual Simulation

Mô phỏng contract của ApprovePurchaseOrder, không kết nối với hệ thống thực tế.

PurchaseOrder amount

**50,000**

Principal roleManager

Order statePENDING

### Execution checks

Authorization

Principal được phép approve

Precondition

Order đang pending

Budget constraint

Available budget đáp ứng

Approval requirement

Không cần approval bổ sung

**Execution outcome**

COMMITTABLE

Current budget available

## 120,000

Projected available after commit

## 70,000

Existing reservations

New reservation

Available

**Proposed Mutation Plan**

PurchaseOrder.status: PENDING → APPROVED\

Budget.reserved: 80,000 → 130,000\

Event: purchase_order.approved

Mô phỏng trên minh họa điểm khác biệt giữa business Action và một function trực tiếp cập nhật `status`.

Một Action chỉ có thể commit khi thỏa mãn các contracts liên quan. Trong implementation thực tế còn cần kiểm soát concurrency, transaction, freshness và auditing.

<a id="sec-80"></a>

## 80. Minimal MVP Scope

Để không mở rộng quá mức, tôi đề xuất một vertical slice có đủ structural model và operational behavior.

### MVP — Candidate Capabilities

Authoring

Object Type và typed properties

Link Type

Function

Action Type

Basic Policy

Metadata

In-process registry

Introspection

Static validation

JSON metadata export

Engine

Object reference resolution

Basic ObjectSet query

Action invocation

Parameter validation

Authorization

Preconditions

Local transaction coordination

Execution records

Adapters

In-memory provider

SQLAlchemy reference provider

Basic policy provider

Consumer

Python SDK

Một application interface

Một AI tool interface

Những phần như full semantic diff, advanced approvals, distributed transactions, generic query federation, durable workflows và enterprise-scale authorization có thể nằm ngoài MVP.

Structured Mutation Plan tối giản đáng được thử nghiệm sớm vì nó liên quan trực tiếp đến khác biệt giữa Action và function.

<a id="sec-81"></a>

## 81. Proposed Reference Stack

Nếu chọn Python cho implementation đầu tiên, một stack tương đối gọn có thể là:

| Layer                 | Candidate                    |
| --------------------- | ---------------------------- |
| Authoring             | Python                       |
| Typing                | Python typing / Pydantic     |
| Metadata              | In-process registry          |
| Serialization         | JSON                         |
| Relational adapter    | SQLAlchemy                   |
| Development backend   | SQLite hoặc PostgreSQL       |
| Policy                | Python policy implementation |
| Testing               | pytest                       |
| Application interface | FastAPI                      |
| AI interface          | MCP adapter                  |
| Observability         | Structured logging           |

Tôi đề xuất Python vì phù hợp với background AI Engineering, cho phép nghiên cứu type annotations, decorators, introspection và tích hợp các thư viện hiện có.

Tuy nhiên, đây là quyết định tạm thời để giảm complexity của PoC, không phải yêu cầu nền tảng rằng ontology chỉ được viết bằng Python.

<a id="sec-82"></a>

## 82. Minimal package architecture

Một package structure có thể được hình dung như sau:

**Cập nhật:** Cây bên dưới là minh họa nền tảng được giữ lại; package Python gốc đã được thống nhất là `codology`, không phải `ontology`. Xem [thiết kế package hiện hành](design/evolution-and-cross-domain.md#46-ánh-xạ-vào-declarations-và-registry).

**ontology-framework/**

src/

ontology/

model/

objects.py

links.py

actions.py

functions.py

policies.py

types.py

registry/

engine/

context.py

query.py

action.py

validation.py

mutation.py

providers/

protocols.py

memory/

sqlalchemy/

integrations/

fastapi/

mcp/

tooling/

examples/

procurement/

tests/

docs/

pyproject.toml

Package structure không nên được chốt trước meta-model và engine contracts.

Đây chỉ là minh họa cách tách framework core, providers, consumer integrations và developer tooling.
