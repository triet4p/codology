# Part XV — Research Roadmap

*[← Part XIV — Research Questions and Open Problems](14-research-questions.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part XVI — Proof of Concept and MVP →](16-proof-of-concept-and-mvp.md)*

<a id="sec-71"></a>

## 71. Hướng nghiên cứu tổng thể

Tôi nghĩ chưa nên bắt đầu bằng việc tạo package, chọn database hay implement hàng loạt decorators.

Nên nghiên cứu theo first principles, đồng thời sử dụng các concrete use cases để tránh meta-model trở thành một mô hình lý thuyết xa rời nhu cầu thực tế.

01

**Foundations & Landscape**

Operational ontology, existing frameworks, design references.

02

**Ontology Meta-model**

Primitives, types, references, relations, composition.

03

**Object & Data Semantics**

Identity, state, ObjectSet, logical-to-physical mapping.

04

**Action Semantics**

Contracts, lifecycle, mutation, effects, failure behavior.

05

**Governance Model**

Principal, permissions, validation, audit, delegation.

06

**Authoring Language**

Code-first DSL, typing, readability, introspection.

07

**Engine & Adapter Contracts**

Execution context, providers, capability requirements.

08

**Reference Implementation**

Lightweight local engine and one backend.

09

**Developer Tooling**

Testing, validation, metadata, visualization, diff.

10

**Consumer Integration**

Python SDK, application API and AI tools.

11

**Evaluation**

Correctness, portability, maintainability, DX.

Đây là proposed roadmap, không phải lịch triển khai đã cam kết.

Các tracks sẽ có tính iterative. Ví dụ nghiên cứu Action semantics có thể dẫn tới thay đổi Meta-model, và thử nghiệm developer-facing API có thể làm lộ ra những abstraction không cần thiết.

<a id="sec-72"></a>

## 72. Research Track 1 — Ontology Landscape

Mục tiêu là xác định chính xác project nằm ở đâu trong hệ sinh thái hiện tại.

Cần nghiên cứu những nhóm sau:

| Nhóm                | Câu hỏi                                                              |
| ------------------- | -------------------------------------------------------------------- |
| Palantir Ontology   | Primitive nào tạo ra operational value?                              |
| Semantic Web        | Semantic concepts nào nên giữ lại?                                   |
| ORM / Data Mapper   | Object resolution và relationship abstractions được thiết kế ra sao? |
| DDD                 | Domain model, business invariant, bounded context                    |
| Command frameworks  | Action và command lifecycle                                          |
| Policy frameworks   | Permission semantics và enforcement                                  |
| Model-as-Code       | Authoring, compilation, metadata extraction                          |
| Workflow frameworks | Durable operations và failures                                       |
| Agent tooling       | Dynamic discovery và governed invocation                             |

Deliverable mong muốn là một comparative architecture matrix và xác định research gap.

Chưa nên kết luận rằng không có ai xây một layer tương tự cho đến khi research track này được thực hiện.

<a id="sec-73"></a>

## 73. Research Track 2 — Ontology Meta-model

Đây nên là phần nghiên cứu trung tâm đầu tiên sau khi đã định hình problem statement.

Các câu hỏi quan trọng:

Object Type khác Entity Type như thế nào? Property là primitive riêng hay một phần của Object Type? Relation có identity riêng không? Action có thể không gắn với một Object Type cụ thể không? Function và Action khác nhau về guarantees nào? Policy là primitive hay extension? Interface có hỗ trợ structural và behavioral polymorphism không?

Deliverable nên bao gồm:

```
Meta-model Specification
├── Terminology
├── Primitive Definitions
├── Primitive Relationships
├── Type Rules
├── Identity Rules
├── Constraints
├── Composition Rules
└── Worked Examples
```

Mục tiêu chưa phải viết production code mà là xây dựng một model đủ rõ để đánh giá correctness.

<a id="sec-74"></a>

## 74. Research Track 3 — Action Semantics

Tôi sẽ ưu tiên nghiên cứu Action song song với Object và Relation thay vì để Action tới cuối.

Nếu chỉ nghiên cứu structural ontology, rất dễ vô tình thiết kế ra một ORM hoặc schema library không phù hợp với operational requirements.

| Chủ đề            | Deliverable                                           |
| ----------------- | ----------------------------------------------------- |
| Action Contract   | Formalized inputs, outputs, permissions, requirements |
| Action Lifecycle  | State transition model                                |
| Execution Context | Principal, provider, dependency propagation           |
| Mutation Model    | Structured hoặc direct mutation strategy              |
| Transaction Model | Atomicity requirements và capability checks           |
| Failure Model     | Error taxonomy, retry và partial failure              |
| Effect Model      | Event và external side effects                        |
| Approval Model    | Validation, approval, revalidation                    |
| Composition       | Nested Actions và domain boundaries                   |
| Audit Model       | Execution records và provenance                       |

Đây có thể là một research document riêng vì độ phức tạp và vai trò của nó trong project.

<a id="sec-75"></a>

## 75. Research Track 4 — Authoring Language và Developer Experience

Khi đã hiểu semantic requirements, cần thử nhiều cách biểu diễn bằng code.

Ví dụ cùng một Action có thể được viết dưới dạng class:

```
class ApproveOrder(Action):    order: ObjectRef[Order]    permission = "order.approve"    def execute(self, ctx):        ...
```

Decorated function:

```
@action(permission="order.approve")def approve_order(    order: ObjectRef[Order],    ctx: ActionContext):    ...
```

Hoặc explicit definition:

```
approve_order = ActionDefinition(    name="approve_order",    parameters=ApproveOrderParameters,    permission="order.approve",    handler=approve_order_handler)
```

Không có lý do phải quyết định ngay class-based DSL là lựa chọn tốt nhất.

Cần đánh giá từng hướng về readability, boilerplate, native typing, IDE support, static analysis, introspection, testability, extensibility và portability.

Developer experience là tiêu chí quan trọng hơn việc syntax trông giống Palantir.

<a id="sec-76"></a>

## 76. Research Track 5 — Engine Contracts

Sau khi meta-model và operation semantics đủ rõ, mới nghiên cứu engine interfaces.

Các deliverables có thể gồm:

```
Engine Specification
├── Runtime initialization
├── Registry lifecycle
├── Object resolution protocol
├── Query specification
├── Action invocation protocol
├── Execution context
├── Policy enforcement points
├── Validation protocol
├── Mutation coordination
├── Provider contracts
└── Error model
```

Mục tiêu là xây engine đủ khả năng điều phối một operational business layer, không phải xây toàn bộ infrastructure.
