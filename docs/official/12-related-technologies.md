# Part XII — Related Technologies and Design References

*[← Part XI — AI Agent Integration](11-ai-agent-integration.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part XIII — Design Principles →](13-design-principles.md)*

<a id="sec-63"></a>

## 63. Không cần phát minh lại từng thành phần

Một nhận định rất quan trọng của bạn là từng phần riêng lẻ của ý tưởng có thể đã được những framework khác làm tốt.

SQLAlchemy chẳng hạn rất mạnh ở object mapping, query abstraction, relationships và database transactions.

Nhưng abstraction của SQLAlchemy chủ yếu nằm giữa database và application. Ontology Layer mà chúng ta hình dung cần bao quát business semantics, governance và operational behavior ở cấp độ cao hơn.

Phạm vi abstraction

**Applications / AI Agents**

**Ontology as Code Framework**

Business objects · Actions · Policies · Governance

SQLAlchemy

Data access

Policy tools

Authorization

Workflow tools

Execution

**Data & Infrastructure**

OaC không cần thay thế những công nghệ này. Nó có thể kết hợp chúng dưới một operational ontology contract.

<a id="sec-64"></a>

## 64. Các design references

| Technology / Pattern | Điều đáng học hỏi                                       |
| -------------------- | ------------------------------------------------------- |
| Pydantic             | Code-first typing, validation, serialization            |
| SQLAlchemy           | Object mapping, lazy query, relationships, Unit of Work |
| Pulumi               | Sử dụng programming language để định nghĩa resources    |
| dbt                  | Models as code, dependencies, testing, lineage          |
| FastAPI              | Type-driven API contracts và schema generation          |
| Prisma               | Typed data model và client generation                   |
| Strawberry GraphQL   | Code-first API schema và introspection                  |
| Kubernetes           | Declarative contracts, validation, resource semantics   |
| OPA / Cedar          | Policy definition và authorization                      |
| OpenFGA              | Relationship-based authorization                        |
| Temporal             | Durable execution và orchestration                      |
| Apache Kafka         | Event-based integration                                 |
| Ibis                 | Backend-independent query expressions                   |
| OpenTelemetry        | Execution observability và tracing                      |
| RDF / OWL            | Formal semantic modeling và interoperability            |
| SHACL                | Structured constraint modeling                          |
| PROV-O               | Provenance semantics                                    |
| DDD                  | Entity, Aggregate, Value Object, bounded context        |
| CQRS                 | Phân biệt query model và command model                  |
| MCP                  | Consumer interface và tool discovery                    |

Đây là danh sách các công nghệ và patterns đáng nghiên cứu, chưa phải tech stack chính thức.

Chúng ta cũng chưa thực hiện một systematic landscape review để xác định có framework nào đã kết hợp đầy đủ những khả năng này hay chưa.

Do đó, chưa thể kết luận ý tưởng OaC là hoàn toàn mới.

<a id="sec-65"></a>

## 65. Điều chúng ta thực sự cần thiết kế

Nếu tận dụng những công nghệ hiện có, phần giá trị riêng của framework sẽ tập trung vào:

| Thành phần                  | Giá trị                                                   |
| --------------------------- | --------------------------------------------------------- |
| Unified ontology meta-model | Thống nhất structural, behavioral và governance semantics |
| Code-first authoring        | Developer experience tự nhiên                             |
| Object contracts            | Shared identity, typing, relations                        |
| Action contracts            | Governed business operations                              |
| Execution semantics         | Cách operations được thực thi nhất quán                   |
| Adapter protocols           | Infrastructure independence                               |
| Metadata representation     | Human và machine introspection                            |
| Cross-component governance  | Policy, validation, execution cùng một boundary           |
| Developer tooling           | Test, diff, inspect, visualize                            |
| Consumer integration        | Reuse business semantics cho apps và AI                   |

Tính mới tiềm năng của dự án nằm ở **sự thống nhất abstraction và lifecycle**, không nhất thiết ở việc phát minh ra từng subsystem.
