# Part XIV — Research Questions and Open Problems

*[← Part XIII — Design Principles](13-design-principles.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part XV — Research Roadmap →](15-research-roadmap.md)*

<a id="sec-67"></a>

## 67. Những gì chúng ta đã thống nhất

Lấy cảm hứng từ Palantir Operational Ontology.

Ontology không nhất thiết sử dụng RDF hoặc graph database.

Ontology là một business layer nằm giữa consumers và data/systems.

Code-first là hướng authoring phù hợp với developer.

OOP và DDD là những reference quan trọng.

Objects, Links và Actions là các khái niệm nền tảng.

Action không đơn giản là một function.

Governance là thành phần nội tại của layer.

Framework cần có engine thực thi và điều phối nhẹ.

Engine có thể delegate infrastructure cho providers.

Mục tiêu là developer framework, không phải standalone platform.

AI Agent là một consumer, không phải lý do duy nhất framework tồn tại.

Developer experience và maintainability là mục tiêu trọng tâm.

<a id="sec-68"></a>

## 68. Những gì chưa được quyết định

Đây là phần cần giữ rõ ràng để không vô tình biến các minh họa trước đó thành architectural commitments.

| Chủ đề               | Open question                                               |
| -------------------- | ----------------------------------------------------------- |
| Authoring Language   | Python, TypeScript hay hỗ trợ nhiều ngôn ngữ?               |
| Language Design      | Classes, decorators, descriptors, builder API hay hybrid?   |
| Meta-model           | Tập first-class primitives tối thiểu là gì?                 |
| Type System          | Tận dụng native types tới mức nào?                          |
| Canonical IR         | JSON schema riêng hay standard representation nào?          |
| Compilation          | Static AST analysis, introspection hay hybrid?              |
| Object Identity      | Composite keys, global IDs, canonical identity?             |
| Object State         | Live state, snapshot, materialized state hay nhiều mode?    |
| Data Binding         | Object-level mapping hay property-level mapping?            |
| Links                | Mapping declarative hay resolver functions?                 |
| Interfaces           | Structural hay behavioral contracts?                        |
| Query Model          | Expression tree riêng hay reuse query system?               |
| Functions            | Pure/read functions được phân loại thế nào?                 |
| Action Syntax        | Class, function hay command definition?                     |
| Action Lifecycle     | Minimal state machine gồm những trạng thái nào?             |
| Mutation             | Bắt buộc structured Mutation Plan hay optional?             |
| Authorization        | Policy-first hay object/action-first?                       |
| Permission Semantics | RBAC, ABAC, ReBAC hay composition?                          |
| Transactions         | Framework expose transaction contract thế nào?              |
| Approval             | Là primitive riêng hay execution extension?                 |
| Audit                | Audit đồng bộ, asynchronous hay transactional?              |
| Versioning           | Definition, runtime artifact và data schema version ra sao? |
| Composition          | Domain dependencies, namespaces, Action invocation?         |
| Portability          | Backend capability contract chi tiết thế nào?               |
| Deployment           | In-process library, remote engine hay cả hai?               |

Chúng ta chưa cần giải quyết tất cả các câu hỏi này ngay lập tức.

<a id="sec-69"></a>

## 69. Độ phức tạp của từng subsystem

Đánh giá định tính phục vụ research prioritization, không phải benchmark hoặc estimation đã kiểm chứng.

Basic code-first definitions

Thấp

Metadata extraction / registry

Vừa

Basic schema validation

Vừa

Visualization / documentation

Vừa

Basic ObjectSet abstraction

Khá cao

Data binding adapters

Khá cao

SDK / API / MCP generation

Khá cao

Semantic diff

Khá cao

Local Action Engine

Khá cao

Object-level authorization

Cao

Mutation & concurrency

Cao

Action lifecycle / approvals

Cao

Fine-grained query security

Rất cao

Cross-domain composition

Rất cao

Distributed consistency

Rất cao

Generic query federation

Rất cao

Những phần phức tạp nhất không nằm ở việc viết DSL đẹp.

Chúng nằm ở execution guarantees: authorization, transaction, concurrency, composition, distributed effects và portability giữa các backend có khả năng khác nhau.

<a id="sec-70"></a>

## 70. Những architectural risks cần tránh

| Risk                       | Hệ quả                                                        |
| -------------------------- | ------------------------------------------------------------- |
| Overengineering            | Xây quá nhiều subsystem trước khi kiểm chứng abstraction      |
| ORM duplication            | Biến OaC thành một SQLAlchemy khác                            |
| Schema-only framework      | Có definitions nhưng không chuẩn hóa behavior                 |
| Platform lock-in           | Adapter abstraction phụ thuộc một infrastructure              |
| False guarantees           | Khai báo atomic, secure nhưng runtime không thực sự đảm bảo   |
| Arbitrary execution        | Handler bypass policies và mutation boundary                  |
| Metadata drift             | Metadata không còn phản ánh executable code                   |
| Excessive magic            | Decorators, metaclasses làm code khó debug                    |
| Poor DX                    | Developer phải viết nhiều boilerplate                         |
| Unrestricted extensibility | Plugin hoặc adapter phá vỡ framework contracts                |
| Weak composition model     | Khó mở rộng qua nhiều domain                                  |
| AI-first overfitting       | Thiết kế chỉ hữu ích với LLM thay vì application thông thường |
| Universal abstraction      | Cố hỗ trợ mọi backend dẫn tới abstraction quá chung chung     |

Đặc biệt cần tránh việc hy sinh correctness để đạt developer-facing syntax đẹp.
