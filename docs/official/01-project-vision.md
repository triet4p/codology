# Part I — Project Vision

*[← Ontology as Code (OaC)](00-introduction.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part II — Ontology as Code →](02-ontology-as-code.md)*

<a id="sec-1"></a>

## 1. Bối cảnh và động lực

### 1.1. Điều đáng học hỏi nhất từ Palantir

Điểm đặc biệt của Palantir Foundry không chỉ nằm ở khả năng tích hợp dữ liệu, xây dựng pipeline, triển khai ứng dụng hay AI Agent, mà ở cách Palantir tổ chức toàn bộ các khả năng đó xoay quanh một Ontology chung.

Ontology của Palantir kết hợp nhiều yếu tố:

| Thành phần         | Vai trò                                             |
| ------------------ | --------------------------------------------------- |
| Object Types       | Định nghĩa các thực thể nghiệp vụ                   |
| Properties         | Mô tả đặc điểm và trạng thái của thực thể           |
| Link Types         | Biểu diễn quan hệ giữa các thực thể                 |
| Interfaces         | Chuẩn hóa những đặc điểm và khả năng chung          |
| Value Types        | Biểu diễn các kiểu dữ liệu mang ngữ nghĩa nghiệp vụ |
| Functions          | Biểu diễn logic và tính toán nghiệp vụ              |
| Action Types       | Định nghĩa các thao tác nghiệp vụ                   |
| Permissions        | Kiểm soát truy cập và thao tác                      |
| Datasource Mapping | Ánh xạ mô hình nghiệp vụ vào dữ liệu vật lý         |
| Object Edits       | Quản lý thay đổi trạng thái của Objects             |
| OSDK               | Cung cấp programmatic interface cho consumers       |
| AIP                | Cho phép AI sử dụng dữ liệu và thực hiện nghiệp vụ  |

Từng thành phần không nhất thiết mới. Điều đáng chú ý là **chúng được tổ chức thành một architectural layer thống nhất**, có thể được chia sẻ giữa con người, ứng dụng, automation và AI.

Palantir-inspired operational architecture

Human

Application

Automation

AI Agent

## Operational Ontology

**Semantic Layer**

Objects

Properties

Links

Interfaces

Value Types

Identity

**Kinetic Layer**

Functions

Actions

State Changes

Events

Effects

Workflows

**Governance**

Permissions

Validation

Audit

Database

Datasets

ERP / CRM

APIs

Ontology trở thành một **shared operational model** của tổ chức.

Thay vì mỗi application tự định nghĩa Customer, Order, Supplier, Inventory và tự xây dựng các business operations tương ứng, các consumer có thể sử dụng chung một mô hình nghiệp vụ.

Đây là phần chúng ta muốn nghiên cứu và mang ra ngoài Palantir.

<a id="sec-2"></a>

## 2. Vấn đề với cách xây dựng Ontology truyền thống

### 2.1. Semantic Web stack

Cách tiếp cận ontology truyền thống thường gắn với những công nghệ như:

| Công nghệ    | Vai trò                                |
| ------------ | -------------------------------------- |
| RDF          | Mô hình biểu diễn dữ liệu dạng triples |
| Turtle (TTL) | Serialization format cho RDF           |
| RDFS         | Schema và vocabulary                   |
| OWL          | Formal ontology và reasoning           |
| SHACL        | Validation trên RDF graphs             |
| SPARQL       | Truy vấn và cập nhật RDF graphs        |
| PROV-O       | Biểu diễn provenance                   |
| Triple Store | Lưu trữ và truy vấn RDF                |

Những công nghệ này có giá trị rõ ràng đối với knowledge representation, interoperability, formal semantics và reasoning.

Tuy nhiên, trải nghiệm thực tế của bạn khi phát triển ontology bằng TTL, SHACL và PROV-O cho thấy một số khó khăn, đặc biệt về khả năng phát triển, theo dõi và bảo trì.

### 2.2. Developer experience chưa phù hợp với bài toán operational

Giả sử cần mô hình hóa một `PurchaseOrder`.

Trong Semantic Web stack, developer có thể phải duy trì nhiều thành phần khác nhau:

```
purchase_order/
├── ontology.ttl
├── properties.ttl
├── relationships.ttl
├── shapes.ttl
├── provenance.ttl
├── queries/
│   ├── find_orders.sparql
│   └── get_supplier.sparql
└── application/
    ├── approval_service.py
    ├── authorization.py
    └── repository.py
```

Khi cần thay đổi một business rule, developer phải xác định thay đổi đó ảnh hưởng tới schema, constraints, queries, application logic và permissions như thế nào.

Các thành phần liên quan tới cùng một khái niệm nghiệp vụ có thể bị phân tán giữa nhiều representation và execution environment.

Những khó khăn chúng ta muốn giải quyết gồm:

| Vấn đề                       | Hệ quả                                                       |
| ---------------------------- | ------------------------------------------------------------ |
| Verbose representation       | Khó đọc và phát triển nhanh                                  |
| Fragmented definitions       | Khó theo dõi đầy đủ một business concept                     |
| Limited IDE integration      | Refactoring và navigation kém tự nhiên hơn code thông thường |
| Separate execution logic     | Knowledge model và operational logic tách rời                |
| Cross-component dependencies | Khó đánh giá impact khi thay đổi                             |
| Governance fragmentation     | Permission, validation và audit cần nhiều integration riêng  |
| High learning curve          | Developer phải hiểu thêm Semantic Web stack                  |

Đây không phải khẳng định RDF hay OWL không phù hợp để xây dựng hệ thống nghiệp vụ. Hoàn toàn có thể xây operational systems trên RDF.

Vấn đề là **chúng ta không nhất thiết phải chọn RDF làm abstraction trung tâm**, nếu mục tiêu chính không phải formal reasoning trên knowledge graph mà là xây dựng một lớp nghiệp vụ có thể lập trình và vận hành.

<a id="sec-3"></a>

## 3. Định nghĩa lại khái niệm Ontology

### 3.1. Knowledge Ontology và Operational Ontology

Chúng ta đang sử dụng từ Ontology theo nghĩa rộng hơn cách nó thường được hiểu trong Semantic Web.

| Khía cạnh      | Knowledge Ontology                                   | Operational Ontology                                   |
| -------------- | ---------------------------------------------------- | ------------------------------------------------------ |
| Mục tiêu chính | Biểu diễn và suy luận tri thức                       | Mô hình hóa và vận hành nghiệp vụ                      |
| Thực thể       | Classes, individuals                                 | Business objects                                       |
| Quan hệ        | Semantic predicates                                  | Business relationships                                 |
| Constraints    | Logical axioms, shapes                               | Data constraints, business invariants                  |
| Behavior       | Thường do hệ thống bên ngoài bổ sung                 | Functions và Actions là thành phần cốt lõi             |
| State change   | Graph updates                                        | Governed business operations                           |
| Permissions    | Không phải thành phần bắt buộc của ontology language | Thành phần nội tại của business layer                  |
| Execution      | Reasoning, querying                                  | Querying, computation, mutation, orchestration         |
| Consumer       | Knowledge systems                                    | Human, application, automation, AI                     |
| Representation | Thường RDF/OWL trong Semantic Web                    | Không giới hạn format                                  |
| Storage        | Có thể là RDF store                                  | Database, datasets, APIs, graph store hoặc nhiều nguồn |

Sự phân biệt này mô tả hai trọng tâm thiết kế, không phải hai loại hệ thống loại trừ lẫn nhau.

### 3.2. Semantic và Kinetic

Một operational ontology cần mô tả được cả hai khía cạnh:

## Semantic

**What exists?**

Customer, Order, Product, Supplier, Budget.

Identity, properties, relations, state và meaning.

## Kinetic

**What can happen?**

Approve Order, Reserve Budget, Cancel Shipment.

Business logic, operations, state transitions và effects.

Nếu semantic layer mô tả những gì tồn tại trong thế giới nghiệp vụ, kinetic layer mô tả những cách hợp lệ để tác động lên thế giới đó.

Governance xác định ai có thể quan sát hoặc thực hiện những thao tác này, trong điều kiện nào.

### 3.3. Working definition

Định nghĩa tạm thời của Operational Ontology:

> A typed, governed and executable representation of a business domain, independent of its underlying physical data representation.

Một mô hình nghiệp vụ:

- **Typed:** Có hệ thống kiểu dữ liệu, Objects, Properties, Relations và Interfaces.
- **Governed:** Có permissions, policies, constraints và audit semantics.
- **Executable:** Có functions, actions và state transitions.
- **Storage-independent:** Không bị ràng buộc vào RDF, relational database hay một storage model cụ thể.
- **Consumer-independent:** Có thể được sử dụng bởi nhiều application, human và AI system.

<a id="sec-4"></a>

## 4. Ontology không nhất thiết là Knowledge Graph

Đây là một trong những quan điểm nền tảng chúng ta đã thống nhất.

Cần phân biệt giữa:

| Khái niệm        | Ý nghĩa                                               |
| ---------------- | ----------------------------------------------------- |
| Logical model    | Objects và quan hệ nghiệp vụ                          |
| Representation   | Cách serialize model thành Python, JSON, YAML, RDF... |
| Physical storage | Nơi lưu dữ liệu thực tế                               |
| Query model      | Cách consumer truy xuất dữ liệu                       |
| Execution model  | Cách nghiệp vụ được thực thi                          |

Một ontology có thể có logical graph mà không cần graph database hoặc RDF triples.

Ví dụ:

Logical business graph — minh họa quan hệ nghiệp vụ, không quy định physical storage.

Relational DB

Graph DB

APIs / Datasets

`Customer → Order → OrderItem → Product` có thể được hiện thực hóa bằng foreign keys trong PostgreSQL, edges trong Neo4j, joins trên lakehouse hoặc các API calls.

Ontology chỉ cần cung cấp logical semantics và contract để resolve các relationships đó.

RDF có thể vẫn tồn tại trong kiến trúc dưới dạng import/export adapter, interoperability format hoặc reasoning backend tùy nhu cầu.

**Graph là một đặc điểm của logical model, không nhất thiết là một quyết định về storage architecture.**
