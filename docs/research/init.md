\# \*\*Ontology as Code (OaC)\*\*



\## \*\*A Developer Framework for Building Operational Business Layers\*\*



Bản tổng hợp này hệ thống hóa toàn bộ những gì chúng ta đã thảo luận: từ động lực nghiên cứu Palantir Ontology, những hạn chế khi phát triển ontology bằng Semantic Web, ý tưởng Ontology as Code, đến kiến trúc framework, meta-model, Action Engine, governance, developer experience và định hướng R\&D.



Tôi sẽ coi đây là một \*\*Conceptual Architecture \& Research Foundation v0.1\*\* — tài liệu nền tảng của dự án, chưa phải một technical specification đã được chốt. Những phần chúng ta đã thống nhất sẽ được phân biệt với những giả thuyết thiết kế và các vấn đề cần nghiên cứu tiếp.



\# \*\*PHẦN I — PROJECT VISION\*\*



\## \*\*1. Bối cảnh và động lực\*\*



\### \*\*1.1. Điều đáng học hỏi nhất từ Palantir\*\*



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



Từng thành phần không nhất thiết mới. Điều đáng chú ý là \*\*chúng được tổ chức thành một architectural layer thống nhất\*\*, có thể được chia sẻ giữa con người, ứng dụng, automation và AI.



Palantir-inspired operational architecture



Human



Application



Automation



AI Agent



\## \*\*Operational Ontology\*\*



\*\*Semantic Layer\*\*



Objects



Properties



Links



Interfaces



Value Types



Identity



\*\*Kinetic Layer\*\*



Functions



Actions



State Changes



Events



Effects



Workflows



\*\*Governance\*\*



Permissions



Validation



Audit



Database



Datasets



ERP / CRM



APIs



Ontology trở thành một \*\*shared operational model\*\* của tổ chức.



Thay vì mỗi application tự định nghĩa Customer, Order, Supplier, Inventory và tự xây dựng các business operations tương ứng, các consumer có thể sử dụng chung một mô hình nghiệp vụ.



Đây là phần chúng ta muốn nghiên cứu và mang ra ngoài Palantir.



\## \*\*2. Vấn đề với cách xây dựng Ontology truyền thống\*\*



\### \*\*2.1. Semantic Web stack\*\*



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



\### \*\*2.2. Developer experience chưa phù hợp với bài toán operational\*\*



Giả sử cần mô hình hóa một `PurchaseOrder`.



Trong Semantic Web stack, developer có thể phải duy trì nhiều thành phần khác nhau:



```

purchase\_order/

├── ontology.ttl

├── properties.ttl

├── relationships.ttl

├── shapes.ttl

├── provenance.ttl

├── queries/

│   ├── find\_orders.sparql

│   └── get\_supplier.sparql

└── application/

&#x20;   ├── approval\_service.py

&#x20;   ├── authorization.py

&#x20;   └── repository.py

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



Vấn đề là \*\*chúng ta không nhất thiết phải chọn RDF làm abstraction trung tâm\*\*, nếu mục tiêu chính không phải formal reasoning trên knowledge graph mà là xây dựng một lớp nghiệp vụ có thể lập trình và vận hành.



\## \*\*3. Định nghĩa lại khái niệm Ontology\*\*



\### \*\*3.1. Knowledge Ontology và Operational Ontology\*\*



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



\### \*\*3.2. Semantic và Kinetic\*\*



Một operational ontology cần mô tả được cả hai khía cạnh:



\## \*\*Semantic\*\*



\*\*What exists?\*\*



Customer, Order, Product, Supplier, Budget.



Identity, properties, relations, state và meaning.



\## \*\*Kinetic\*\*



\*\*What can happen?\*\*



Approve Order, Reserve Budget, Cancel Shipment.



Business logic, operations, state transitions và effects.



Nếu semantic layer mô tả những gì tồn tại trong thế giới nghiệp vụ, kinetic layer mô tả những cách hợp lệ để tác động lên thế giới đó.



Governance xác định ai có thể quan sát hoặc thực hiện những thao tác này, trong điều kiện nào.



\### \*\*3.3. Working definition\*\*



Định nghĩa tạm thời của Operational Ontology:



> A typed, governed and executable representation of a business domain, independent of its underlying physical data representation.



Một mô hình nghiệp vụ:



\- \*\*Typed:\*\* Có hệ thống kiểu dữ liệu, Objects, Properties, Relations và Interfaces.

\- \*\*Governed:\*\* Có permissions, policies, constraints và audit semantics.

\- \*\*Executable:\*\* Có functions, actions và state transitions.

\- \*\*Storage-independent:\*\* Không bị ràng buộc vào RDF, relational database hay một storage model cụ thể.

\- \*\*Consumer-independent:\*\* Có thể được sử dụng bởi nhiều application, human và AI system.



\## \*\*4. Ontology không nhất thiết là Knowledge Graph\*\*



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



\*\*Graph là một đặc điểm của logical model, không nhất thiết là một quyết định về storage architecture.\*\*



\# \*\*PHẦN II — ONTOLOGY AS CODE\*\*



\## \*\*5. Ý tưởng Ontology as Code\*\*



Thay vì xây dựng ontology chủ yếu thông qua các ngôn ngữ biểu diễn tri thức, chúng ta muốn developer có thể định nghĩa ontology bằng một programming language quen thuộc như Python hoặc TypeScript.



Tư tưởng này tương tự:



| Paradigm               | Đối tượng được lập trình        |

| ---------------------- | ------------------------------- |

| Infrastructure as Code | Infrastructure                  |

| Policy as Code         | Authorization policies          |

| Configuration as Code  | Configuration                   |

| Data Models as Code    | Data transformations và models  |

| API as Code            | Service interfaces              |

| \*\*Ontology as Code\*\*   | \*\*Operational business models\*\* |



Tuy nhiên, Ontology as Code không đơn giản là lưu ontology vào file code.



Chúng ta phân biệt hai cấp độ:



\*\*Ontology stored as code:\*\* Schema được lưu trong Python, JSON, YAML hoặc TypeScript.



\*\*Ontology engineered as code:\*\* Ontology trở thành một software artifact có thể được định nghĩa, validate, test, inspect, compose, version, review, deploy và execute.



Cấp độ thứ hai mới là mục tiêu của dự án.



\## \*\*6. Tại sao OOP là một abstraction tự nhiên?\*\*



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

class Customer(ObjectType):    id: str    name: str    credit\_limit: Decimal    orders: LinkMany\["Order"]class Order(ObjectType):    id: str    amount: Decimal    status: OrderStatus    customer: LinkOne\[Customer]    items: LinkMany\["OrderItem"]

```



Một developer đã quen Python, typing và ORM có thể đọc và hiểu phần lớn nội dung mà không phải học một representation language hoàn toàn mới.



IDE cũng có thể hỗ trợ autocomplete, type checking, navigation và refactoring.



Tất cả API và syntax trong tài liệu này đều là \*\*conceptual DSL minh họa\*\*, chưa phải implementation chính thức hoặc code đã được kiểm thử.



\## \*\*7. Không nên đồng nhất Ontology với OOP\*\*



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



Chúng ta sử dụng OOP làm \*\*developer-facing language\*\*, đồng thời định nghĩa semantics riêng cho operational domain.



\## \*\*8. Code-first, nhưng không nhất thiết code-only\*\*



Một kiến trúc đáng nghiên cứu là sử dụng native programming language làm authoring surface và canonical metadata làm machine-readable representation.



\*\*Source of Truth\*\*



\## \*\*Ontology Source Code\*\*



Python / TypeScript



\*\*Compiler / Introspection\*\*



Extract · Resolve · Validate · Normalize



\*\*Canonical Intermediate Representation\*\*



\## \*\*JSON Metadata\*\*



Typed definitions + executable references



Engine



SDK



AI Tools



RDF Export



Ví dụ canonical representation của Object Type:



```

{

&#x20; "id": "sales.order",

&#x20; "kind": "objectType",

&#x20; "primaryKey": "id",

&#x20; "properties": {

&#x20;   "id": {

&#x20;     "type": "string"

&#x20;   },

&#x20;   "amount": {

&#x20;     "type": "decimal"

&#x20;   },

&#x20;   "status": {

&#x20;     "type": "OrderStatus"

&#x20;   }

&#x20; },

&#x20; "links": {

&#x20;   "customer": {

&#x20;     "target": "sales.customer",

&#x20;     "cardinality": "many-to-one"

&#x20;   }

&#x20; },

&#x20; "actions": \[

&#x20;   "sales.approve\_order",

&#x20;   "sales.cancel\_order"

&#x20; ]

}

```



Canonical IR có thể phục vụ introspection, semantic diff, visualization, documentation generation, SDK generation và AI discovery.



Nhưng cần lưu ý JSON metadata không thể tự động biểu diễn đầy đủ arbitrary executable Python code. Nó có thể biểu diễn operation contract và tham chiếu tới handler đã được quản lý version.



\### \*\*Separation of concerns\*\*



```

Declaration

&#x20;   Mô tả những gì ontology có.



Implementation

&#x20;   Định nghĩa logic nghiệp vụ cụ thể.



Execution

&#x20;   Quy định và điều phối cách logic được thực thi.

```



Ba phần này có thể cùng được viết bằng Python, nhưng không nên bị trộn lẫn về trách nhiệm.



Việc có bắt buộc compiler riêng, JSON IR ngay từ MVP hay chỉ sử dụng in-process metadata registry vẫn là quyết định mở.



\# \*\*PHẦN III — PROJECT SCOPE VÀ PRODUCT POSITIONING\*\*



\## \*\*9. Mục đích thực sự của dự án\*\*



Trong quá trình trao đổi, chúng ta đã điều chỉnh một điểm rất quan trọng.



Ban đầu, ý tưởng dễ bị mở rộng thành việc xây dựng một standalone ontology platform tương tự một phần Palantir Foundry.



Tuy nhiên, mục tiêu bạn xác định là:



> Giúp developer xây dựng ontology/business layer dễ dàng hơn trên bất kỳ platform nào, thay vì phát triển một sản phẩm chạy độc lập.



Do đó, dự án nên được định vị là một \*\*developer framework\*\*, không phải data platform hay enterprise ontology management platform.



Working definition của dự án:



> Ontology as Code is a code-first developer framework for defining, composing, validating and executing governed operational business models across existing applications, data platforms and AI systems.



Hoặc ngắn gọn hơn:



> A framework for building business layers as code.



\## \*\*10. Platform và Framework khác nhau thế nào?\*\*



Hai hướng phát triển khác nhau



\*\*Standalone Platform\*\*



Apps / AI Agents



Ontology Platform



Admin UI



Ontology Server



Storage



IAM



Execution Service



Monitoring



Deployment



External Systems



Doanh nghiệp sử dụng một platform mới.



\*\*Developer Framework\*\*



Existing System



Apps / AI Agents



Business Layer



Developer's Ontology



OaC Framework



Embedded Engine



Adapters



Existing DB, IAM, APIs, Events, Workflows



Developer sử dụng framework trong hệ thống hiện tại.



Framework không sở hữu toàn bộ hệ thống. Developer sở hữu hệ thống và quyết định infrastructure, deployment architecture cũng như integration strategy.



\## \*\*11. Framework có cần Runtime không?\*\*



Chúng ta đã đi qua ba hướng suy nghĩ:



| Hướng                             | Đánh giá                                            |

| --------------------------------- | --------------------------------------------------- |

| Chỉ xây modeling library          | Có giá trị nhưng chưa chuẩn hóa execution semantics |

| Xây full-fledged Ontology Runtime | Quá lớn nếu bao gồm toàn bộ infrastructure          |

| Xây embeddable Ontology Engine    | Hướng hiện tại chúng ta thống nhất                  |



Điểm quan trọng là không đánh đồng engine với platform.



Engine cần tồn tại để framework có thể đảm bảo ontology không chỉ được định nghĩa thống nhất mà còn được sử dụng theo những semantic contracts thống nhất.



Tuy nhiên, engine không cần tự xây database, IAM, workflow infrastructure, distributed transaction manager hay một hệ thống lưu trữ riêng.



\*\*Nguyên tắc kiến trúc: Own the semantics, delegate the infrastructure.\*\*



\## \*\*12. Scope và Non-goals\*\*



\### \*\*In scope\*\*



Ontology meta-model



Code-first authoring



Typed primitives



Business semantics



Object / Action contracts



Embeddable engine



Governance enforcement



Adapter interfaces



Metadata introspection



Validation \& testing



Developer tooling



Consumer integration



\### \*\*Non-goals\*\*



Thay thế Palantir Foundry



Xây database mới



Xây data warehouse



Xây IAM platform



Xây workflow platform



Bắt buộc graph database



Bắt buộc sử dụng RDF



Bắt buộc central server



Distributed engine từ đầu



Enterprise admin platform



Full AI agent framework



Thay thế toàn bộ application



Framework phải hỗ trợ developer xây business layer phù hợp với hệ thống của họ, không ép hệ thống phải tái cấu trúc theo toàn bộ một platform mới.



\# \*\*PHẦN IV — SYSTEM ARCHITECTURE\*\*



\## \*\*13. High-level Reference Architecture\*\*



Đây là kiến trúc tổng hợp phù hợp nhất với những gì chúng ta đã thống nhất cho đến thời điểm hiện tại.



Ontology as Code — Reference Architecture v0.1



\### \*\*Consumer Layer\*\*



Application



Human



AI Agent



Automation



\*\*Consumer Interfaces\*\*



Python SDK



REST API



GraphQL



MCP



\## \*\*Operational Ontology Layer\*\*



\*\*Developer-defined Domain\*\*



Objects



Properties



Relations



Interfaces



Actions



Functions



Policies



Constraints



Mappings



\*\*Ontology Meta-model \& Registry\*\*



Type system



Definitions



Dependency graph



Canonical metadata



\*\*Embeddable Ontology Engine\*\*



Object resolution



Query orchestration



Action lifecycle



Function execution



Policy enforcement



Validation



Mutation coordination



Audit \& effects



Execution Context · Identity · Lifecycle Hooks



\*\*Provider / Adapter Contracts\*\*



Data



Identity



Policy



Transaction



Effects



Audit



\### \*\*Existing Infrastructure\*\*



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



\## \*\*14. Kiến trúc tĩnh và kiến trúc động\*\*



\### \*\*14.1. Static architecture\*\*



Kiến trúc tĩnh quan tâm tới việc ontology được định nghĩa, tổ chức và biểu diễn như thế nào.



```

Source Code

&#x20;   │

&#x20;   ├── Object Definitions

&#x20;   ├── Relation Definitions

&#x20;   ├── Interface Definitions

&#x20;   ├── Function Definitions

&#x20;   ├── Action Definitions

&#x20;   ├── Policy Definitions

&#x20;   └── Data Bindings

&#x20;   │

&#x20;   ▼

Meta-model / Introspection

&#x20;   │

&#x20;   ▼

Validated Registry

&#x20;   │

&#x20;   ├── Canonical Metadata

&#x20;   ├── Dependency Graph

&#x20;   ├── Type Information

&#x20;   └── Execution Contracts

```



Static architecture cần trả lời được:



\- Có những Object Types nào?

\- Mỗi Object Type có properties và relations nào?

\- Các Actions nhận những parameter types nào?

\- Action phụ thuộc vào những Objects, Functions hoặc Actions nào?

\- Policy nào được áp dụng?

\- Ontology có thay đổi breaking contract không?

\- Backend cần những capabilities nào?



\### \*\*14.2. Dynamic architecture\*\*



Kiến trúc động quan tâm tới cách ontology hoạt động tại runtime.



Simplified action execution sequence. Các bước approval, retries, auditing và external effects chưa được biểu diễn đầy đủ.



Runtime sử dụng metadata và executable contracts để resolve object, kiểm tra quyền, xác thực input, thực thi nghiệp vụ và điều phối backend.



Điều này tạo ra sự liên kết giữa static model và operational behavior.



\## \*\*15. Logical planes\*\*



Có thể phân chia Ontology Layer thành hai plane nội bộ.



| Plane           | Nội dung                                                                         |

| --------------- | -------------------------------------------------------------------------------- |

| Control Plane   | Definitions, type system, registry, metadata, dependencies, policies, versioning |

| Execution Plane | Object resolution, query, action, function, authorization, mutation, audit       |



Cách phân chia này hữu ích cho research và thiết kế module.



Tuy nhiên, chúng ta không mặc định phải triển khai control plane và execution plane thành các distributed services.



\## \*\*16. Phân chia trách nhiệm giữa Framework và Developer\*\*



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



\# \*\*PHẦN V — ONTOLOGY META-MODEL\*\*



\## \*\*17. Meta-model là gì và tại sao quan trọng?\*\*



Meta-model định nghĩa những thành phần hợp lệ mà developer có thể sử dụng để xây dựng ontology.



Ví dụ:



```

Ontology Meta-model

&#x20;   định nghĩa ObjectType là gì.



Enterprise Ontology

&#x20;   định nghĩa PurchaseOrder là một ObjectType.



Runtime Object

&#x20;   PurchaseOrder:PO-001 là một instance.

```



Đây là ba cấp độ cần phân biệt.



M2 — Meta-model



\*\*ObjectType · LinkType · ActionType · Policy\*\*



Framework định nghĩa các primitive và semantics.



instantiated by



M1 — Domain Model



\*\*PurchaseOrder · Supplier · ApproveOrder\*\*



Developer định nghĩa nghiệp vụ của tổ chức.



instantiated by



M0 — Operational World



\*\*PO-001 · Supplier-032 · Execution-102\*\*



Dữ liệu và execution instances thực tế.



Nếu thiết kế meta-model không tốt, developer-facing API có thể rất đẹp nhưng framework vẫn gặp vấn đề khi mở rộng, composition hoặc execution.



Do đó, chúng ta nên thiết kế \*\*semantics trước syntax\*\*.



\## \*\*18. Candidate ontology primitives\*\*



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



\## \*\*19. Object Type\*\*



Object Type mô tả một loại thực thể trong thế giới nghiệp vụ.



Ví dụ:



```

class PurchaseOrder(ObjectType):    id: str    supplier\_id: str    amount: Decimal    currency: Currency    status: PurchaseOrderStatus    created\_at: datetime    department\_id: str    supplier: LinkOne\["Supplier"]    budget: LinkOne\["Budget"]    items: LinkMany\["PurchaseOrderItem"]

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



\## \*\*20. Object Identity và Object Reference\*\*



Object identity là vấn đề cốt lõi khi abstraction nằm trên nhiều datasource.



Một `Customer` có thể tồn tại trong CRM, ERP và một ML feature store dưới các identifiers khác nhau.



\*\*CRM\*\*



CUST-102



Name, contact



\*\*ERP\*\*



ACCOUNT-87



Revenue, balance



\*\*ML Store\*\*



ENTITY-52



Churn score



\*\*Identity Resolution \& Data Binding\*\*



\*\*Customer: canonical-001\*\*



name



CRM



contact



CRM



revenue



ERP



balance



ERP



churn\_score



ML Store



Framework nên cung cấp một abstraction cho object identity và resolution. Tuy nhiên, nó không nhất thiết phải tự giải quyết toàn bộ entity matching và record linkage. Developer có thể cung cấp canonical identity hoặc sử dụng một upstream data integration process.



Một Object Reference có thể được hình dung như:



```

ObjectRef\[Customer]("canonical-001")

```



Canonical representation có thể là:



```

{

&#x20; "objectType": "sales.customer",

&#x20; "objectId": "canonical-001"

}

```



ObjectRef khác với Object instance đã được load. Nó có thể chỉ là một typed handle dùng để resolve object khi cần.



\## \*\*21. Property và Value Type\*\*



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



\## \*\*22. Link Type\*\*



Relationship nên là first-class concept thay vì chỉ là object attribute.



Ví dụ:



```

@link\_type(    source=PurchaseOrder,    target=Supplier,    cardinality="many-to-one")class PurchaseOrderSupplier:    source\_key = "supplier\_id"    target\_key = "id"

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



\## \*\*23. Interface\*\*



Interface cho phép nhiều Object Types chia sẻ một semantic contract.



Ví dụ:



```

class Approveable(Interface):    status: ApprovalStatusclass PurchaseOrder(ObjectType, Approveable):    id: str    status: ApprovalStatusclass ExpenseRequest(ObjectType, Approveable):    id: str    status: ApprovalStatus

```



Điều này có thể hỗ trợ shared functions, generic queries hoặc Actions trên các nhóm objects.



Tuy nhiên, cần xác định rõ interface chỉ mô tả structural contract hay còn có behavioral contract. Khả năng inheritance, composition và polymorphic querying cũng chưa được chốt.



Không nên mang toàn bộ inheritance model của OOP sang ontology một cách máy móc.



\## \*\*24. Object Set và Query Model\*\*



Một Object Set có thể đại diện cho một tập records rất lớn, không phải một Python list đã được load vào memory.



```

orders = (    PurchaseOrder.objects    .filter(status=Status.PENDING)    .filter(amount\_\_gt=100\_000)    .order\_by("-created\_at")    .limit(100))result = orders.fetch()

```



Framework có thể biểu diễn query bằng một query specification hoặc expression tree rồi chuyển cho data provider.



\*\*ObjectSet Query\*\*



Filter · Sort · Traverse · Aggregate



\*\*Query Specification\*\*



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



\## \*\*25. Functions\*\*



Functions biểu diễn logic, computation hoặc business rules có thể tái sử dụng.



Ví dụ:



```

@functiondef calculate\_credit\_risk(customer: Customer) -> float:    exposure = (        customer.orders        .filter(status=OrderStatus.PENDING)        .sum("amount")    )    return float(exposure / customer.credit\_limit)

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



\# \*\*PHẦN VI — ACTION MODEL: HẠT NHÂN CỦA OPERATIONAL ONTOLOGY\*\*



\## \*\*26. Tại sao Action không đơn giản là Function?\*\*



Đây là một trong những phần quan trọng nhất của toàn bộ dự án.



Một function thông thường có thể được mô tả bằng contract:



```

Input → Computation → Output

```



Một operational Action có contract rộng hơn:



```

Principal

\+ Intent

\+ Parameters

\+ Current World State

\+ Business Policies

&#x20;       │

&#x20;       ▼

Governed State Transition

&#x20;       │

&#x20;       ▼

New World State

\+ Effects

\+ Execution Record

```



Action mô tả một cách hợp lệ để tác động lên operational world.



Ví dụ `ApprovePurchaseOrder` không đơn thuần là:



```

order.status = "APPROVED"

```



Nó có thể phải kiểm tra budget, supplier, role, approval requirements, current state, concurrency, transaction boundaries và các external side effects.



\## \*\*27. Anatomy of an Action\*\*



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



\## \*\*28. Action Definition, Implementation và Engine\*\*



Ba thành phần này cần được phân biệt rõ.



\### \*\*Action Definition\*\*



Declarative contract



Parameters, permission, constraints, write scope, execution requirements.



\### \*\*Action Engine\*\*



Framework responsibility



Authorization, validation, lifecycle, execution context, commit coordination, audit.



\### \*\*Action Implementation\*\*



Developer responsibility



Domain-specific decisions, calculations and proposed state changes.



Developer nên tập trung vào nghiệp vụ thay vì phải tự viết lặp lại các cross-cutting concerns như authorization, transaction management và audit trong từng Action.



Một conceptual DSL:



```

@action(    name="Approve Purchase Order",    permission="purchase\_order.approve",    transaction=Transaction.atomic(),    idempotency=Idempotency.required(),    approval=Approval.conditional(        when=Param("order").amount > 100\_000,        role="finance\_director"    ))class ApprovePurchaseOrder(Action):    order: ObjectRef\[PurchaseOrder]    reason: str    reads = \[PurchaseOrder, Budget, Supplier]    writes = \[PurchaseOrder, Budget]    def validate(self, ctx):        order = ctx.resolve(self.order)        ctx.require(            order.status == Status.PENDING        )        ctx.require(            order.budget.available >= order.amount        )    def execute(self, ctx):        order = ctx.resolve(self.order)        ctx.update(            order,            status=Status.APPROVED        )

```



Trong ví dụ này, `ctx.update()` và `ctx.increment()` có thể tạo Mutation Plan thay vì cập nhật dữ liệu ngay lập tức.



Việc Action được biểu diễn bằng class, decorated function hay một declarative workflow vẫn là quyết định về language design. Chúng ta chưa chốt syntax nào.



\## \*\*29. Action Lifecycle\*\*



Action có thể có lifecycle riêng, đặc biệt khi liên quan tới approval, asynchronous operations hoặc external systems.



Candidate lifecycle. Trạng thái, transition rules và failure semantics cần được thiết kế chính thức.



Một Action đơn giản có thể thực thi đồng bộ trong một transaction.



Một Action phức tạp có thể cần chờ phê duyệt, thực thi lại hoặc chuyển sang workflow backend.



Điều framework nên chuẩn hóa là lifecycle contract, không nhất thiết tự hiện thực hóa một durable workflow engine.



\## \*\*30. ActionExecution như một thực thể có identity\*\*



Mỗi lần gọi Action có thể tạo một execution instance.



```

execution = ontology.actions.invoke(    action="procurement.approve\_purchase\_order",    parameters={        "order": "PO-001",        "reason": "Supplier verified"    })

```



Kết quả:



```

{

&#x20; "executionId": "exec-001",

&#x20; "action": "procurement.approve\_purchase\_order",

&#x20; "actionVersion": "1.2.0",

&#x20; "ontologyVersion": "2.1.0",

&#x20; "principal": "employee-123",

&#x20; "status": "AWAITING\_APPROVAL",

&#x20; "requiredApproval": {

&#x20;   "role": "finance\_director"

&#x20; }

}

```



Execution record có thể được sử dụng cho tracking, cancellation nếu được hỗ trợ, approval, error inspection, retries và audit.



Một ý tưởng đáng nghiên cứu là `ActionExecution` cũng có thể trở thành một Object trong system ontology.



Khi đó, developer và AI có thể sử dụng chính ontology để truy vấn những gì đã xảy ra trong hệ thống.



```

ActionExecution.objects.filter(    action="procurement.approve\_purchase\_order",    status="FAILED")

```



Nhưng việc hỗ trợ persistent execution instances cho mọi Action có thể tạo thêm overhead. Framework có thể cho phép execution modes đơn giản hơn.



\## \*\*31. Mutation Plan\*\*



Mutation Plan là một abstraction đặc biệt có giá trị đối với operational ontology.



Thay vì cho handler trực tiếp thực hiện mọi state change, handler mô tả các thay đổi dự kiến dưới dạng structured operations.



Ví dụ:



```

{

&#x20; "mutations": \[

&#x20;   {

&#x20;     "operation": "update",

&#x20;     "object": "PurchaseOrder:PO-001",

&#x20;     "expectedVersion": 12,

&#x20;     "changes": {

&#x20;       "status": "APPROVED"

&#x20;     }

&#x20;   },

&#x20;   {

&#x20;     "operation": "increment",

&#x20;     "object": "Budget:B-001",

&#x20;     "property": "reserved",

&#x20;     "value": 50000

&#x20;   }

&#x20; ],

&#x20; "effects": \[

&#x20;   {

&#x20;     "type": "event",

&#x20;     "name": "purchase\_order.approved"

&#x20;   }

&#x20; ]

}

```



\*\*Action Handler\*\*



Domain logic



\## \*\*Mutation Plan\*\*



Proposed changes and external effects



Preview



Validate



Approve



Audit



\*\*Commit Coordination\*\*



Revalidation · Concurrency · Transaction · Effects



Structured Mutation Plan tạo điều kiện cho các khả năng như dry run, preview, approval, change inspection, write scope validation, audit và AI safety.



Tuy nhiên, Mutation Plan không tự động đảm bảo execution thành công.



Giữa thời điểm lập plan và commit, world state có thể thay đổi. Runtime phải revalidate những assumptions liên quan hoặc sử dụng phù hợp các concurrency guarantees của backend.



Ngoài ra, không phải mọi external operation đều có thể biểu diễn một cách đầy đủ dưới dạng mutation trên Objects. Vì vậy, Mutation Plan nên được nghiên cứu như một execution model quan trọng, chưa nhất thiết là cách duy nhất để implement mọi Action.



\## \*\*32. Transaction và Consistency\*\*



Một Action có thể thay đổi nhiều Objects:



```

ApprovePurchaseOrder

&#x20;   ├── Update PurchaseOrder.status

&#x20;   ├── Reserve Budget

&#x20;   └── Create ApprovalRecord

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



\## \*\*33. Effects và Failure Handling\*\*



State mutation và external side effects nên được phân biệt.



```

State mutation:

&#x20;   Order.status = APPROVED



External effects:

&#x20;   Send notification

&#x20;   Publish event

&#x20;   Notify ERP

```



Nếu notification thất bại sau khi database đã commit, việc đánh dấu toàn bộ Action là chưa xảy ra có thể gây hiểu nhầm.



Execution model nên có khả năng phân biệt business state đã commit với effects chưa hoàn thành.



Những vấn đề cần nghiên cứu gồm retry safety, idempotency keys, delivery semantics, failure records, cancellation và compensation.



Một Action không nên bị retry toàn bộ một cách mù quáng nếu một số side effects đã xảy ra.



\## \*\*34. Action Composition\*\*



Khi Action này gọi Action khác, complexity tăng lên đáng kể.



```

Procurement Domain

&#x20;   ApprovePurchaseOrder

&#x20;           │

&#x20;           ├── ValidateSupplier

&#x20;           │

&#x20;           └── ReserveBudget

&#x20;                   │

&#x20;                   ▼

Finance Domain

&#x20;   Budget

&#x20;   Reservation

&#x20;   FinancialPolicy

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



Đây là vấn đề \*\*governed operation composition\*\*, không chỉ là function composition.



Chúng ta chưa cần giải quyết toàn bộ composition semantics trong MVP, nhưng meta-model và engine contracts không nên loại bỏ khả năng này.



\# \*\*PHẦN VII — GOVERNANCE VÀ SECURITY MODEL\*\*



\## \*\*35. Governance là thành phần nội tại của Ontology\*\*



Trong một kiến trúc truyền thống, authorization có thể được triển khai riêng ở từng application hoặc API endpoint.



Điều đó dễ dẫn tới tình trạng cùng một nghiệp vụ có nhiều implementation về permission và validation.



Operational ontology muốn chuyển authorization boundary về gần business objects và business operations hơn.



Application-centric governance



Web App



Own authorization



Own validation



Mobile App



Own authorization



Own validation



AI Agent



Own authorization



Own validation



Data \& Services



Ontology-centric governance



Web App



Mobile App



AI Agent



\*\*Shared Ontology Boundary\*\*



Object permissions



Action permissions



Business constraints



Audit / provenance



Data \& Services



Cùng một Action được gọi từ Web App hoặc AI Agent phải tuân thủ cùng business semantics và authorization rules.



Điều này chỉ được đảm bảo đối với các operations đi qua enforcement boundary. Framework không thể ngăn một application có direct database credentials bypass ontology nếu hệ thống không được cấu hình để ngăn chặn điều đó.



\## \*\*36. Principal và Execution Context\*\*



Mỗi operation cần có thông tin về actor đang thực hiện.



Principal có thể là human user, service account, application, automation worker hoặc AI Agent.



Một conceptual execution context:



```

class ExecutionContext:    principal: Principal    request\_id: str    execution\_id: str    ontology\_version: str    data: DataProvider    authorization: PolicyProvider    transaction: TransactionProvider    audit: AuditProvider    effects: EffectProvider

```



Execution Context là nơi truyền identity, dependencies và operation context xuyên suốt quá trình thực thi.



Nó cũng giúp Action handler không cần hard-code các infrastructure clients.



Principal propagation cần đặc biệt được nghiên cứu đối với AI Agent. Agent thực hiện thay người dùng khác với agent tự chạy dưới service identity.



Framework không nên cho phép một Action vô tình nâng quyền chỉ vì nó gọi một service bên ngoài.



\## \*\*37. Permission Model\*\*



Permission có thể xuất hiện ở nhiều cấp độ:



| Cấp độ            | Ví dụ                                      |

| ----------------- | ------------------------------------------ |

| Ontology          | Có quyền khám phá domain Finance           |

| Object Type       | Có quyền truy cập PurchaseOrder            |

| Object Instance   | Chỉ xem đơn hàng thuộc department của mình |

| Property          | Không được đọc supplier bank account       |

| Link              | Không được traverse tới salary records     |

| Function          | Có quyền gọi risk calculation              |

| Action Type       | Có quyền thực hiện approve\_order           |

| Action Parameters | Chỉ được approve cho warehouse phụ trách   |

| Mutation          | Chỉ được thay đổi các fields được cho phép |

| Metadata          | Chỉ được discover capabilities phù hợp     |



Framework có thể cung cấp policy contracts và enforcement points, còn policy implementation có thể được thực hiện bằng Python hoặc tích hợp OPA, Cedar, OpenFGA hay enterprise authorization provider phù hợp.



Ví dụ:



```

@policy(    resource=PurchaseOrder,    operation="read")def read\_purchase\_order(    principal: Principal,    order: PurchaseOrder) -> bool:    return (        principal.has\_role("admin")        or principal.department\_id == order.department\_id    )

```



Điều quan trọng là permission không chỉ được kiểm tra tại UI.



Nó phải được enforce tại runtime execution boundary, bao gồm cả query, traversal và mutation.



\## \*\*38. Authorization và Business Validation là hai khái niệm khác nhau\*\*



Ví dụ một nhân viên có quyền approve PurchaseOrder, nhưng PurchaseOrder đã bị cancel.



| Kiểm tra              | Kết quả  |

| --------------------- | -------- |

| Authorization         | Allowed  |

| Business precondition | Failed   |

| Action execution      | Rejected |



Ngược lại, một PurchaseOrder đang ở trạng thái hoàn toàn hợp lệ để approve, nhưng principal không có quyền thực hiện.



| Kiểm tra              | Kết quả   |

| --------------------- | --------- |

| Business precondition | Satisfied |

| Authorization         | Denied    |

| Action execution      | Rejected  |



Framework cần phân biệt các loại validation:



| Validation type        | Mục đích                                      |

| ---------------------- | --------------------------------------------- |

| Schema validation      | Kiểm tra cấu trúc và types                    |

| Parameter validation   | Kiểm tra Action inputs                        |

| Referential validation | Kiểm tra object references                    |

| Authorization          | Kiểm tra quyền thực hiện                      |

| Preconditions          | Kiểm tra state trước operation                |

| Invariants             | Đảm bảo business consistency                  |

| Postconditions         | Kiểm tra state sau operation                  |

| Capability validation  | Kiểm tra backend có hỗ trợ guarantees yêu cầu |

| Static validation      | Kiểm tra ontology definitions trước runtime   |



Điều này giúp developer debugging và giúp AI Agent hiểu tại sao một operation không được phép thực hiện.



Error response cũng cần tránh làm lộ dữ liệu mà principal không được quyền biết.



\## \*\*39. Query-time security\*\*



Authorization ở cấp Object Set không thể mặc định được giải quyết bằng cách load toàn bộ dữ liệu rồi filter bằng Python.



Ví dụ:



```

orders = PurchaseOrder.objects.filter(    status=Status.PENDING)

```



Query engine nên chuyển những security constraints phù hợp xuống backend khi có thể.



Điều này quan trọng đối với pagination, aggregation, counts, joins và relation traversal.



Một principal không được đọc 1.000 PurchaseOrders thì không nên suy ra thông tin nhạy cảm của chúng thông qua unrestricted aggregation.



Thiết kế cụ thể của policy pushdown là một vấn đề research riêng. Đây là một trong những phần có thể khó hơn đáng kể so với xây dựng type system hoặc metadata registry.



\## \*\*40. Audit và Provenance\*\*



Audit trả lời câu hỏi:



> Ai đã làm gì, vào thời điểm nào và kết quả ra sao?



Provenance trả lời câu hỏi:



> Dữ liệu hoặc quyết định này bắt nguồn từ đâu và dựa trên những dữ liệu, logic hay execution nào?



Ví dụ audit record:



```

{

&#x20; "executionId": "exec-001",

&#x20; "action": "procurement.approve\_purchase\_order",

&#x20; "actionVersion": "1.2.0",

&#x20; "principal": "employee-123",

&#x20; "target": "PurchaseOrder:PO-001",

&#x20; "result": "COMMITTED",

&#x20; "changes": {

&#x20;   "status": {

&#x20;     "before": "PENDING",

&#x20;     "after": "APPROVED"

&#x20;   }

&#x20; }

}

```



Provenance có thể bổ sung thông tin về datasource version, model version, input object references, policy decision và các execution dependencies.



Chúng ta có thể học từ PROV-O để xây provenance semantics mà không bắt buộc lưu provenance dưới dạng RDF.



Audit và provenance cũng cần policies riêng về dữ liệu nhạy cảm, access control và retention. Không phải mọi input, intermediate value hay property đều nên được ghi nguyên văn vào log.



\# \*\*PHẦN VIII — ONTOLOGY ENGINE\*\*



\## \*\*41. Vai trò của Engine\*\*



Sau quá trình thảo luận và điều chỉnh scope, chúng ta thống nhất rằng một Ontology Engine nên tồn tại trong framework.



Nếu chỉ có class definitions, decorators và metadata, OaC rất dễ trở thành schema modeling library.



Developer vẫn phải tự quyết định cách resolve object, execute Action, áp dụng permission, thực hiện validation và ghi audit.



Engine giúp biến những definitions thành operational behavior nhất quán.



Tuy nhiên, nó nên là \*\*embeddable engine\*\*, không phải một standalone enterprise execution platform.



\## \*\*42. Các logical engine modules\*\*



| Module            | Trách nhiệm                                          |

| ----------------- | ---------------------------------------------------- |

| Object Engine     | Resolve identity, materialize objects, data mapping  |

| Query Engine      | Query abstraction, filtering, aggregation, traversal |

| Function Runtime  | Thực thi functions với execution context             |

| Action Engine     | Điều phối Action lifecycle                           |

| Policy Engine     | Policy evaluation và enforcement coordination        |

| Validation Engine | Kiểm tra schema, constraints, invariants             |

| Mutation Engine   | Điều phối structured state changes                   |

| Effect Engine     | Điều phối events, external effects                   |

| Audit Engine      | Chuẩn hóa execution records                          |



Không nhất thiết mỗi module phải là một class, service hoặc package độc lập. Có thể tổ chức chúng thành các subsystem logic bên trong một lightweight runtime.



\## \*\*43. Engine chịu trách nhiệm gì và không chịu trách nhiệm gì?\*\*



| Engine          | Nên sở hữu                             | Delegate cho infrastructure       |

| --------------- | -------------------------------------- | --------------------------------- |

| Object Engine   | Logical identity, resolution contract  | Physical data storage             |

| Query Engine    | ObjectSet query semantics              | SQL execution, search indexes     |

| Policy Engine   | Enforcement boundary                   | IAM và policy evaluation backend  |

| Action Engine   | Lifecycle, invocation, context         | Durable workflow infrastructure   |

| Mutation Engine | Mutation contract, commit requirements | Native transaction implementation |

| Effect Engine   | Effect coordination, status semantics  | Message delivery infrastructure   |

| Audit Engine    | Audit schema và operation hooks        | Audit storage và log platform     |



Framework không cần cạnh tranh với SQLAlchemy, Temporal, Kafka, PostgreSQL hoặc enterprise IAM.



Nó cần điều phối những thành phần đó theo ontology semantics.



\## \*\*44. Ví dụ một Action Engine tối giản\*\*



Đây là một implementation sketch để minh họa engine responsibility:



```

def invoke(action\_type, raw\_params, context):    action = registry.resolve\_action(action\_type)    params = validate\_parameters(        action.parameters,        raw\_params    )    authorize\_invocation(        action,        params,        context    )    validate\_capabilities(        action.requirements,        context.providers    )    with context.transaction():        resolved\_params = resolve\_references(            params,            context        )        validate\_preconditions(            action,            resolved\_params,            context        )        result = execute\_handler(            action,            resolved\_params,            context        )        validate\_postconditions(            action,            result,            context        )        record\_success(            action,            result,            context        )    return result

```



Đoạn code này minh họa một synchronous execution path với một transaction boundary. Nó chưa xử lý approval, failed execution logging, concurrency races, external effects hoặc distributed execution.



Điểm quan trọng là các lời gọi như `context.transaction()` có thể sử dụng SQLAlchemy hoặc một transaction provider khác.



Framework định nghĩa orchestration contract; adapter cung cấp infrastructure-specific implementation.



\## \*\*45. Execution Modes\*\*



Cùng một Action contract có thể được hỗ trợ bởi nhiều execution mode.



\*\*Common Action Contract\*\*



Parameters · Policies · Preconditions · Effects



\*\*Local\*\*



In-process



Python application, synchronous execution.



\*\*Remote\*\*



Service / Worker



Execution thông qua API hoặc remote worker.



\*\*Durable\*\*



Workflow backend



Long-running, approval, persistent execution.



MVP chỉ cần ưu tiên local execution.



Remote và durable execution có thể được nghiên cứu sau, khi engine contracts đã đủ rõ.



Local execution cũng là runtime. Không có yêu cầu phải triển khai một Ontology Server chỉ để thực thi Actions.



\# \*\*PHẦN IX — ADAPTER ARCHITECTURE VÀ PLATFORM INDEPENDENCE\*\*



\## \*\*46. Core + Adapter\*\*



Để developer sử dụng framework trên nhiều hệ thống, OaC nên áp dụng kiến trúc Core + Adapter.



\*\*Developer's Domain Model\*\*



\### \*\*OaC Core\*\*



Type system



Metadata registry



Object contracts



Query contracts



Action contracts



Policy contracts



Execution context



Capability model



Data Adapter



SQL, Datasets, APIs



Policy Adapter



Python, OPA, Cedar



Transaction Adapter



SQLAlchemy, Native DB



Execution Adapter



Local, Remote, Workflow



Effect Adapter



Kafka, HTTP, Queue



Audit Adapter



Database, Logging, Tracing



\*\*Existing Platform Infrastructure\*\*



Core nên càng ít phụ thuộc infrastructure-specific details càng tốt.



Adapters dịch logical operations của ontology thành physical operations của từng backend.



\## \*\*47. Provider Contracts\*\*



Ví dụ một data provider có thể cung cấp các methods:



```

class DataProvider(Protocol):    def resolve(self, ref: ObjectRef):        ...    def query(self, query: ObjectQuery):        ...    def apply(self, plan: MutationPlan):        ...

```



Policy provider:



```

class PolicyProvider(Protocol):    def authorize(        self,        principal: Principal,        operation: Operation,        resource: ResourceRef,        context: ExecutionContext    ) -> PolicyDecision:        ...

```



Transaction provider:



```

class TransactionProvider(Protocol):    def begin(self):        ...    def commit(self):        ...    def rollback(self):        ...

```



Đây là interface sketches. Chúng chưa xác định đầy đủ async semantics, error model, resource lifecycle hoặc transaction propagation.



Mục tiêu là tạo ra common contracts để developer có thể sử dụng infrastructure hiện tại.



\## \*\*48. Capability Model\*\*



Platform-agnostic không có nghĩa tất cả backend đều cung cấp cùng khả năng.



Ví dụ một REST API có thể cho phép đọc PurchaseOrder nhưng không hỗ trợ transaction hoặc arbitrary filtering.



Một lakehouse dataset có thể thích hợp cho analytics nhưng không phù hợp với real-time state mutation.



Framework cần hiểu capabilities của từng provider.



| Capability         | SQL backend       | Read-only API | Dataset backend  |

| ------------------ | ----------------- | ------------- | ---------------- |

| Resolve object     | Có thể hỗ trợ     | Có thể hỗ trợ | Có thể hỗ trợ    |

| Filter             | Thường có         | Tùy API       | Tùy engine       |

| Aggregate          | Thường có         | Tùy API       | Thường khả thi   |

| Traverse relation  | Qua joins         | Qua resolver  | Qua query engine |

| Mutation           | Tùy cấu hình      | Không         | Tùy backend      |

| Native transaction | Tùy database      | Không         | Tùy engine       |

| Optimistic locking | Có thể triển khai | Tùy API       | Tùy backend      |

| Real-time updates  | Tùy backend       | Tùy API       | Không mặc định   |



Bảng trên chỉ minh họa sự khác biệt về capability, không xác định support matrix của một công nghệ cụ thể.



Action và query có thể khai báo requirements. Engine kiểm tra xem provider có đáp ứng hay không.



```

class ApprovePurchaseOrder(Action):    requires = {        Capability.WRITE,        Capability.ATOMIC\_TRANSACTION,        Capability.CONCURRENCY\_CONTROL    }

```



Nếu provider thiếu một capability bắt buộc, framework cần trả về lỗi rõ ràng hoặc yêu cầu cấu hình bổ sung.



Đây là cơ chế giúp platform independence không biến thành sự đánh đổi âm thầm về correctness.



\## \*\*49. Progressive Adoption\*\*



Framework nên được thiết kế để developer có thể áp dụng từng phần.



1



\*\*Typed Modeling\*\*



Object, Property, Relation và Value Type.



2



\*\*Data Binding\*\*



Ánh xạ business objects vào database hoặc API hiện có.



3



\*\*Governed Actions\*\*



Chuẩn hóa business operations, permissions và validation.



4



\*\*Shared Business Layer\*\*



Nhiều application sử dụng chung ontology.



5



\*\*AI Integration\*\*



Expose schema, queries, functions và actions cho agents.



6



\*\*Advanced Execution\*\*



Approval, asynchronous workflows, advanced auditing.



Một developer có thể bắt đầu bằng việc khai báo vài Object Types. Sau đó bổ sung Actions và governance khi cần.



Không bắt buộc doanh nghiệp phải chuyển dữ liệu hoặc thay toàn bộ architecture chỉ để sử dụng OaC.



Tuy nhiên, progressive adoption cần phân biệt với optional security. Khi một Action được định nghĩa là governed operation, các enforcement requirements của nó không nên bị bỏ qua chỉ vì developer chưa tích hợp đầy đủ provider.



\# \*\*PHẦN X — DEVELOPER EXPERIENCE\*\*



\## \*\*50. Developer Experience là mục tiêu cốt lõi\*\*



Một phần động lực ban đầu đến từ trải nghiệm khó phát triển và khó theo dõi ontology bằng TTL, SHACL và PROV-O.



Do đó, developer experience không nên được xem là một tính năng bổ sung sau khi framework đã hoàn thành.



Nó phải là một architectural requirement ngay từ đầu.



Framework cần giúp developer:



\- Đọc và hiểu business domain từ source code.

\- Navigate từ Object sang Links, Actions và Policies liên quan.

\- Tận dụng IDE, type checking và autocomplete.

\- Viết business logic bằng programming language quen thuộc.

\- Test business rules mà không cần deploy toàn bộ hệ thống.

\- Review ontology changes thông qua Git.

\- Phát hiện breaking changes và dependencies.

\- Inspect runtime behavior và debug execution.

\- Sinh metadata, documentation và diagrams tự động.



Nếu framework buộc developer duy trì hàng chục files, schemas và mappings cho một Object Type đơn giản, chúng ta sẽ tái tạo chính vấn đề ban đầu.



\## \*\*51. Developer-facing API\*\*



Developer experience mà chúng ta hình dung có thể bắt đầu bằng:



```

pip install ontology-framework

```



Định nghĩa business domain:



```

from ontology import (    ObjectType,    Action,    ObjectRef,    LinkOne,    Ontology,    Runtime)

```



```

class Customer(ObjectType):    id: str    name: strclass Order(ObjectType):    id: str    customer\_id: str    amount: Decimal    status: OrderStatus    customer: LinkOne\[Customer]

```



```

class ApproveOrder(Action):    order: ObjectRef\[Order]    reason: str    permission = "order.approve"    def validate(self, ctx):        order = ctx.resolve(self.order)        ctx.require(            order.status == OrderStatus.PENDING        )    def execute(self, ctx):        order = ctx.resolve(self.order)        ctx.update(            order,            status=OrderStatus.APPROVED        )

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

runtime.to\_fastapi()runtime.to\_mcp()runtime.to\_sdk()

```



Toàn bộ API trên là minh họa cho developer experience mong muốn. Package, methods và adapters chưa tồn tại như một implementation chính thức của dự án.



\## \*\*52. Repository Organization\*\*



Một repository enterprise ontology có thể được tổ chức theo domain.



\*\*enterprise-ontology/\*\*



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



value\_types.py



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



\## \*\*53. Ontology Development Lifecycle\*\*



1



\*\*Define\*\*



Viết Object, Link, Action và Policy bằng code.



2



\*\*Inspect\*\*



Extract metadata, types và dependencies.



3



\*\*Validate\*\*



Kiểm tra static model, references, capabilities.



4



\*\*Test\*\*



Test business semantics và execution behavior.



5



\*\*Review\*\*



Git pull request và semantic diff.



6



\*\*Publish\*\*



Đóng gói version của ontology và handlers.



7



\*\*Integrate\*\*



Generate hoặc expose SDK, API, agent tools.



8



\*\*Observe\*\*



Theo dõi runtime executions, audit và failures.



Ontology nên tham gia software development lifecycle tương tự application code, thay vì trở thành một collection metadata được chỉnh sửa thủ công mà khó quản lý dependencies.



\## \*\*54. Static Validation\*\*



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



\## \*\*55. Semantic Diff\*\*



Git diff chỉ cho biết source code đã thay đổi như thế nào.



Ontology semantic diff nên cho biết business contract đã thay đổi như thế nào.



Ví dụ:



```

Ontology: procurement

Version: 1.3.0 -> 1.4.0



\+ ObjectType: ApprovalRecord



\+ LinkType:

&#x20; PurchaseOrder.approvalRecords



\~ PurchaseOrder.amount

&#x20; Type: integer -> decimal



\~ ApprovePurchaseOrder

&#x20; Permission:

&#x20; procurement.employee -> procurement.manager



\+ ApprovePurchaseOrder

&#x20; Approval requirement for high-value orders



\- PurchaseOrder.legacyId



Potential breaking changes: 2

Security-related changes: 2

```



Semantic diff có thể được sử dụng cho code review, impact analysis, compatibility checks và migration planning.



Đây là một tính năng có giá trị lớn đối với maintainability.



Tuy nhiên, chỉ metadata và dependencies đã đăng ký mới có thể được phân tích một cách đáng tin cậy. Arbitrary executable code hoặc external consumers không khai báo dependency sẽ giới hạn khả năng impact analysis.



\## \*\*56. Ontology Visualization\*\*



Khi Objects, Links, Functions, Actions và Policies có metadata thống nhất, framework có thể tự động sinh visualization.



Không nhất thiết chỉ sinh knowledge graph truyền thống.



Object



Action



Policy



Các views khác nhau có thể gồm structural graph, Action dependency graph, policy graph, data binding lineage, domain composition graph và runtime execution trace.



Không nhất thiết phải phát triển một enterprise visual editor. Generated diagrams hoặc lightweight inspection tools có thể đủ giá trị ban đầu.



\## \*\*57. Testing\*\*



Một trong những lợi thế của code-first ontology là khả năng test theo software engineering practices.



Ví dụ:



```

def test\_cannot\_approve\_cancelled\_order(runtime):    order = create\_order(        status=OrderStatus.CANCELLED    )    result = runtime.actions.validate(        ApproveOrder,        order=order.ref    )    assert not result.valid

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



\# \*\*PHẦN XI — AI AGENT INTEGRATION\*\*



\## \*\*58. AI là consumer tự nhiên của Ontology\*\*



Một điểm chúng ta đã thống nhất là ontology không nên tồn tại chỉ vì LLM hay AI Agent.



Ngay cả khi không có AI, developer vẫn có lý do để sử dụng framework nhằm tổ chức business logic, semantics và governance.



Nhưng khi có AI Agent, ontology tạo ra một interface đặc biệt hữu ích.



\### \*\*Không có Ontology Layer\*\*



```

AI Agent

&#x20;   ├── Database schemas

&#x20;   ├── SQL queries

&#x20;   ├── Service APIs

&#x20;   ├── Application code

&#x20;   ├── Business documents

&#x20;   └── Permission rules

```



Agent phải tự hiểu physical schema, mapping, business semantics và cách thực hiện từng operation.



Ví dụ:



```

trx\_ord\_hdr.status = 3



3 nghĩa là gì?



Agent có được UPDATE status không?



Có cần cập nhật Budget không?



Approve có cần thông báo ERP không?



Ai được phép approve?

```



\### \*\*Có Ontology Layer\*\*



```

AI Agent

&#x20;   ├── Discover PurchaseOrder

&#x20;   ├── Query pending orders

&#x20;   ├── Traverse supplier and budget

&#x20;   ├── Calculate risk

&#x20;   ├── Inspect ApprovePurchaseOrder

&#x20;   └── Invoke governed Action

```



AI Agent sử dụng cùng operational semantics như các consumer khác.



\## \*\*59. Ontology như một Contract cho AI\*\*



\*\*AI Agent\*\*



Understand · Reason · Decide · Act



\*\*Discover\*\*



Schema, relationships, capabilities



\*\*Read\*\*



Query, traverse, aggregate



\*\*Act\*\*



Functions, validate, execute



\*\*Governed Ontology Interface\*\*



Principal · Authorization · Validation · Audit



\*\*Operational Domain Model\*\*



Objects · Functions · Actions · Policies



Ontology cung cấp structured context về business domain, đồng thời cung cấp operational capabilities.



Điều này khác với chỉ sinh schema description cho AI, chỉ xây knowledge graph RAG, hoặc chỉ expose SQL tools.



Ontology cần có contract cho cả understanding và execution.



\## \*\*60. Dynamic Tool Discovery\*\*



Nếu một enterprise ontology có hàng nghìn Actions, việc đưa tất cả Action schemas vào agent context sẽ không hiệu quả.



Một hướng đáng nghiên cứu là cung cấp một tập generic meta-tools để agent khám phá ontology.



```

search\_object\_types(query)describe\_object\_type(type\_id)search\_actions(query)describe\_action(action\_id)query\_objects(type\_id, filters)traverse\_links(object\_ref, link\_type)aggregate\_objects(object\_set, metric)validate\_action(action\_id, parameters)execute\_action(action\_id, parameters)

```



Agent có thể khám phá domain, tìm relevant Actions, lấy parameter schemas và invoke operations theo nhu cầu.



Metadata registry trở thành một nguồn dynamic capabilities cho agent harness.



Điểm này liên hệ trực tiếp với hướng nghiên cứu AI FDE của chúng ta: agent không nhất thiết phải được cung cấp mọi domain-specific capability ngay từ đầu, mà có thể discover các capabilities liên quan trong quá trình xử lý task.



Tuy nhiên, thiết kế OaC không phụ thuộc vào giả thuyết rằng Palantir AI FDE sử dụng chính cơ chế discovery này. Đây là đề xuất của chúng ta.



\## \*\*61. Ontology-based MCP Integration\*\*



Một hướng integration tiềm năng:



```

AI Agent / MCP Client

&#x20;       │

&#x20;       ▼

Ontology MCP Adapter

&#x20;       │

&#x20;       ├── Metadata discovery

&#x20;       ├── Object query

&#x20;       ├── Function invocation

&#x20;       ├── Action validation

&#x20;       └── Action execution

&#x20;       │

&#x20;       ▼

OaC Engine

&#x20;       │

&#x20;       ▼

Existing Business Systems

```



MCP chỉ nên là một consumer adapter, không phải nền móng của ontology.



Framework vẫn có thể expose cùng semantics qua Python SDK, REST API hoặc GraphQL.



Nếu chỉ xây một MCP server chứa các business tools, chúng ta chưa giải quyết đầy đủ vấn đề ontology modeling, shared metadata, dependencies và execution semantics.



\## \*\*62. AI Safety tại Action Boundary\*\*



Agent có thể hiểu sai intent, truyền sai parameters hoặc lập kế hoạch không phù hợp.



Ontology không đảm bảo rằng quyết định của AI luôn đúng. Nhưng nó có thể giới hạn những operations agent được phép yêu cầu và enforce business rules.



Ví dụ:



```

Agent proposes:

&#x20;   Approve all pending purchase orders

```



Runtime có thể kiểm tra từng operation theo principal, target object, business constraints, transaction requirements và approval policy.



Mutation Plan cũng tạo cơ hội để human review dự kiến state changes trước commit.



Các cơ chế này có ích cho AI governance, nhưng không thay thế risk assessment, human oversight hoặc các biện pháp bảo mật của hệ thống.



\# \*\*PHẦN XII — RELATED TECHNOLOGIES VÀ DESIGN REFERENCES\*\*



\## \*\*63. Không cần phát minh lại từng thành phần\*\*



Một nhận định rất quan trọng của bạn là từng phần riêng lẻ của ý tưởng có thể đã được những framework khác làm tốt.



SQLAlchemy chẳng hạn rất mạnh ở object mapping, query abstraction, relationships và database transactions.



Nhưng abstraction của SQLAlchemy chủ yếu nằm giữa database và application. Ontology Layer mà chúng ta hình dung cần bao quát business semantics, governance và operational behavior ở cấp độ cao hơn.



Phạm vi abstraction



\*\*Applications / AI Agents\*\*



\*\*Ontology as Code Framework\*\*



Business objects · Actions · Policies · Governance



SQLAlchemy



Data access



Policy tools



Authorization



Workflow tools



Execution



\*\*Data \& Infrastructure\*\*



OaC không cần thay thế những công nghệ này. Nó có thể kết hợp chúng dưới một operational ontology contract.



\## \*\*64. Các design references\*\*



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



\## \*\*65. Điều chúng ta thực sự cần thiết kế\*\*



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



Tính mới tiềm năng của dự án nằm ở \*\*sự thống nhất abstraction và lifecycle\*\*, không nhất thiết ở việc phát minh ra từng subsystem.



\# \*\*PHẦN XIII — DESIGN PRINCIPLES\*\*



\## \*\*66. Các nguyên tắc thiết kế nền tảng\*\*



Từ toàn bộ cuộc thảo luận, tôi tổng hợp thành 20 design principles. Một số là định hướng chúng ta đã thống nhất, một số là hệ quả kiến trúc nên tiếp tục được kiểm chứng.



| #   | Principle                | Ý nghĩa                                                                 |

| --- | ------------------------ | ----------------------------------------------------------------------- |

| P01 | \*\*Code-first\*\*           | Developer định nghĩa ontology bằng programming language quen thuộc.     |

| P02 | \*\*Semantic-first\*\*       | Thiết kế ý nghĩa của primitives trước khi thiết kế syntax.              |

| P03 | \*\*Operational\*\*          | Ontology mô tả cả business state và behavior.                           |

| P04 | \*\*Storage-agnostic\*\*     | Không bắt buộc RDF, graph database hoặc relational database.            |

| P05 | \*\*Platform-agnostic\*\*    | Có thể tích hợp vào nhiều hệ thống hiện có.                             |

| P06 | \*\*Embeddable\*\*           | Không yêu cầu triển khai một standalone platform.                       |

| P07 | \*\*Typed\*\*                | Objects, properties, relations, actions và functions có type contracts. |

| P08 | \*\*Governed by design\*\*   | Authorization và validation là thành phần nội tại.                      |

| P09 | \*\*Controlled mutation\*\*  | Business state changes đi qua governed operations.                      |

| P10 | \*\*Introspectable\*\*       | Metadata có thể được khám phá bởi human và machine.                     |

| P11 | \*\*Composable\*\*           | Domains và definitions có thể được kết hợp.                             |

| P12 | \*\*Extensible\*\*           | Có extension points và custom adapters.                                 |

| P13 | \*\*Consumer-independent\*\* | Human, application, automation và AI sử dụng chung semantics.           |

| P14 | \*\*Infrastructure reuse\*\* | Tận dụng engine và systems đã tồn tại.                                  |

| P15 | \*\*Progressive adoption\*\* | Có thể áp dụng từng phần thay vì migration toàn bộ.                     |

| P16 | \*\*Versioned\*\*            | Definitions và executable contracts có thể quản lý version.             |

| P17 | \*\*Testable\*\*             | Business behavior và governance có thể kiểm thử.                        |

| P18 | \*\*Observable\*\*           | Runtime operations có execution records và tracing.                     |

| P19 | \*\*Interoperable\*\*        | Có thể expose SDK, API, MCP hoặc export RDF.                            |

| P20 | \*\*Developer-centric\*\*    | Giảm effort và complexity khi xây dựng business layer.                  |



Ba nguyên tắc có thể trở thành triết lý xuyên suốt dự án:



> \*\*Own the semantics, delegate the infrastructure.\*\*



Framework sở hữu semantic contracts và orchestration cần thiết, nhưng tận dụng infrastructure hiện có.



> \*\*Complexity belongs in the framework; simplicity belongs in the authoring layer.\*\*



Developer nên tập trung mô tả nghiệp vụ, thay vì lặp lại infrastructure plumbing. Tuy nhiên, framework không nên che giấu các giới hạn consistency hoặc security mà developer cần biết.



> \*\*Model once, consume everywhere.\*\*



Một business domain được định nghĩa một lần và có thể được nhiều consumer sử dụng, trong phạm vi contracts và capabilities đã hỗ trợ.



\# \*\*PHẦN XIV — RESEARCH QUESTIONS VÀ OPEN PROBLEMS\*\*



\## \*\*67. Những gì chúng ta đã thống nhất\*\*



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



\## \*\*68. Những gì chưa được quyết định\*\*



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



\## \*\*69. Độ phức tạp của từng subsystem\*\*



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



Mutation \& concurrency



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



\## \*\*70. Những architectural risks cần tránh\*\*



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



\# \*\*PHẦN XV — RESEARCH ROADMAP\*\*



\## \*\*71. Hướng nghiên cứu tổng thể\*\*



Tôi nghĩ chưa nên bắt đầu bằng việc tạo package, chọn database hay implement hàng loạt decorators.



Nên nghiên cứu theo first principles, đồng thời sử dụng các concrete use cases để tránh meta-model trở thành một mô hình lý thuyết xa rời nhu cầu thực tế.



01



\*\*Foundations \& Landscape\*\*



Operational ontology, existing frameworks, design references.



02



\*\*Ontology Meta-model\*\*



Primitives, types, references, relations, composition.



03



\*\*Object \& Data Semantics\*\*



Identity, state, ObjectSet, logical-to-physical mapping.



04



\*\*Action Semantics\*\*



Contracts, lifecycle, mutation, effects, failure behavior.



05



\*\*Governance Model\*\*



Principal, permissions, validation, audit, delegation.



06



\*\*Authoring Language\*\*



Code-first DSL, typing, readability, introspection.



07



\*\*Engine \& Adapter Contracts\*\*



Execution context, providers, capability requirements.



08



\*\*Reference Implementation\*\*



Lightweight local engine and one backend.



09



\*\*Developer Tooling\*\*



Testing, validation, metadata, visualization, diff.



10



\*\*Consumer Integration\*\*



Python SDK, application API and AI tools.



11



\*\*Evaluation\*\*



Correctness, portability, maintainability, DX.



Đây là proposed roadmap, không phải lịch triển khai đã cam kết.



Các tracks sẽ có tính iterative. Ví dụ nghiên cứu Action semantics có thể dẫn tới thay đổi Meta-model, và thử nghiệm developer-facing API có thể làm lộ ra những abstraction không cần thiết.



\## \*\*72. Research Track 1 — Ontology Landscape\*\*



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



\## \*\*73. Research Track 2 — Ontology Meta-model\*\*



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



\## \*\*74. Research Track 3 — Action Semantics\*\*



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



\## \*\*75. Research Track 4 — Authoring Language và Developer Experience\*\*



Khi đã hiểu semantic requirements, cần thử nhiều cách biểu diễn bằng code.



Ví dụ cùng một Action có thể được viết dưới dạng class:



```

class ApproveOrder(Action):    order: ObjectRef\[Order]    permission = "order.approve"    def execute(self, ctx):        ...

```



Decorated function:



```

@action(permission="order.approve")def approve\_order(    order: ObjectRef\[Order],    ctx: ActionContext):    ...

```



Hoặc explicit definition:



```

approve\_order = ActionDefinition(    name="approve\_order",    parameters=ApproveOrderParameters,    permission="order.approve",    handler=approve\_order\_handler)

```



Không có lý do phải quyết định ngay class-based DSL là lựa chọn tốt nhất.



Cần đánh giá từng hướng về readability, boilerplate, native typing, IDE support, static analysis, introspection, testability, extensibility và portability.



Developer experience là tiêu chí quan trọng hơn việc syntax trông giống Palantir.



\## \*\*76. Research Track 5 — Engine Contracts\*\*



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



\# \*\*PHẦN XVI — PROOF OF CONCEPT VÀ MVP\*\*



\## \*\*77. Mục đích của MVP\*\*



MVP không cần chứng minh rằng chúng ta có thể thay thế Palantir.



Nó cần chứng minh:



> Developer có thể định nghĩa một business domain bằng code, kết nối với infrastructure hiện có, rồi sử dụng chung business semantics và governed operations từ nhiều consumer với ít effort hơn.



Đây là tiêu chí quan trọng hơn số lượng features.



\## \*\*78. Domain đề xuất: Procurement\*\*



Trong các ví dụ trước đó, Procurement là một domain tương đối phù hợp vì có đủ structural model, relationships, business logic, Actions, permissions, transaction và approval.



\*\*Candidate Actions\*\*



CreatePurchaseOrder



SubmitForApproval



ApprovePurchaseOrder



RejectPurchaseOrder



CancelPurchaseOrder



ReserveBudget



Business rules có thể bao gồm:



\- PurchaseOrder chỉ được approve khi đang ở trạng thái pending.

\- Principal phải có quyền phê duyệt theo department.

\- Supplier phải đáp ứng các điều kiện nghiệp vụ.

\- Budget còn đủ để reserve.

\- Không được reserve budget hai lần cho cùng một approval.

\- PurchaseOrder có giá trị cao có thể cần cấp phê duyệt bổ sung.

\- Mọi operation cần execution record phù hợp.



Procurement chỉ là domain được đề xuất cho PoC. Chúng ta chưa chốt nó là benchmark domain chính thức.



\## \*\*79. Một execution scenario hoàn chỉnh\*\*



Giả sử trạng thái ban đầu:



| Object               | Property  | Value   |

| -------------------- | --------- | ------- |

| PurchaseOrder:PO-001 | amount    | 50.000  |

| PurchaseOrder:PO-001 | status    | PENDING |

| Budget:B-001         | total     | 200.000 |

| Budget:B-001         | reserved  | 80.000  |

| Budget:B-001         | available | 120.000 |



Một principal có quyền approve yêu cầu thực hiện `ApprovePurchaseOrder`.



\## \*\*Action Engine — Conceptual Simulation\*\*



Mô phỏng contract của ApprovePurchaseOrder, không kết nối với hệ thống thực tế.



PurchaseOrder amount



\*\*50,000\*\*



Principal roleManager



Order statePENDING



\### \*\*Execution checks\*\*



Authorization



Principal được phép approve



Precondition



Order đang pending



Budget constraint



Available budget đáp ứng



Approval requirement



Không cần approval bổ sung



\*\*Execution outcome\*\*



COMMITTABLE



Current budget available



\# \*\*120,000\*\*



Projected available after commit



\# \*\*70,000\*\*



Existing reservations



New reservation



Available



\*\*Proposed Mutation Plan\*\*



PurchaseOrder.status: PENDING → APPROVED\\

Budget.reserved: 80,000 → 130,000\\

Event: purchase\_order.approved



Mô phỏng trên minh họa điểm khác biệt giữa business Action và một function trực tiếp cập nhật `status`.



Một Action chỉ có thể commit khi thỏa mãn các contracts liên quan. Trong implementation thực tế còn cần kiểm soát concurrency, transaction, freshness và auditing.



\## \*\*80. Minimal MVP Scope\*\*



Để không mở rộng quá mức, tôi đề xuất một vertical slice có đủ structural model và operational behavior.



\### \*\*MVP — Candidate Capabilities\*\*



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



\## \*\*81. Proposed Reference Stack\*\*



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



\## \*\*82. Minimal package architecture\*\*



Một package structure có thể được hình dung như sau:



\*\*ontology-framework/\*\*



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



\# \*\*PHẦN XVII — EVALUATION VÀ SUCCESS CRITERIA\*\*



\## \*\*83. Làm thế nào để chứng minh framework có giá trị?\*\*



Cần so sánh ít nhất ba cách xây dựng cùng một nghiệp vụ.



| Approach   | Nội dung                                                         |

| ---------- | ---------------------------------------------------------------- |

| Baseline A | Python application, SQLAlchemy và business services thông thường |

| Baseline B | Semantic Web-based ontology kết hợp application logic            |

| Proposed C | Ontology as Code Framework                                       |



Cả ba nên được đánh giá trên một business domain có functional requirements tương đương.



Không nên cố tình xây baseline kém chất lượng để làm cho OaC trông tốt hơn.



\## \*\*84. Evaluation Dimensions\*\*



| Dimension        | Câu hỏi đánh giá                                                 |

| ---------------- | ---------------------------------------------------------------- |

| Readability      | Developer có hiểu domain từ code dễ dàng không?                  |

| Authoring effort | Mất bao nhiêu effort để thêm Object hoặc Action?                 |

| Boilerplate      | Có phải lặp lại nhiều cross-cutting logic không?                 |

| Maintainability  | Thay đổi business rule cần sửa bao nhiêu nơi?                    |

| Traceability     | Theo dõi dependencies dễ đến đâu?                                |

| Correctness      | Business invariants có được đảm bảo không?                       |

| Security         | Unauthorized operation có bị chặn không?                         |

| Consistency      | State changes có đúng khi xảy ra failure hoặc concurrency không? |

| Testability      | Có thể test độc lập với full infrastructure không?               |

| Reusability      | Nhiều consumer có sử dụng chung semantics không?                 |

| Portability      | Thay adapter cần sửa domain definitions bao nhiêu?               |

| Introspection    | Human và AI có khám phá được model không?                        |

| Observability    | Có giải thích được execution failure không?                      |

| Runtime overhead | Framework tạo thêm chi phí execution bao nhiêu?                  |



\## \*\*85. Candidate Acceptance Tests\*\*



\*\*PoC Acceptance Checklist\*\*



0/12



\*\*Shared semantic model\*\*



Python SDK, Web API và AI Agent đều nhìn thấy cùng Object Type contract.



\*\*Shared action semantics\*\*



Cùng Action được invoke từ nhiều consumer nhưng sử dụng chung business logic.



\*\*Authorization enforcement\*\*



Principal không có quyền bị từ chối tại runtime.



\*\*Business validation\*\*



Order ở trạng thái không hợp lệ không thể được approve.



\*\*Transactional mutation\*\*



Khi mutation thứ hai thất bại, mutation đầu được rollback trên backend transactional.



\*\*Auditability\*\*



Có thể truy xuất execution record và kết quả Action.



\*\*Metadata introspection\*\*



Có thể lấy schema của Objects và Actions mà không đọc toàn bộ source code.



\*\*Backend capability checks\*\*



Write Action bị từ chối trên read-only provider.



\*\*Adapter substitution\*\*



Cùng domain contract có thể sử dụng memory và relational providers trong tập capabilities tương đương.



\*\*Business-rule evolution\*\*



Thay đổi approval rule chỉ cần sửa tại shared domain layer.



\*\*Developer tooling\*\*



Invalid definitions được phát hiện trước khi thực thi.



\*\*AI consumption\*\*



Agent có thể discover, validate và invoke một Action hợp lệ.



Đây là danh sách acceptance criteria dự kiến, chưa phải những tests đã được thực hiện.



\## \*\*86. North Star\*\*



Thước đo thành công của project không phải là framework có bao nhiêu features tương tự Palantir.



Cũng không phải số lượng adapters, độ phức tạp của compiler hay khả năng hỗ trợ hàng tỷ Objects ngay từ đầu.



Thước đo chính là:



> Developer có thể xây dựng một operational business layer đúng đắn, dễ đọc, dễ kiểm thử, dễ bảo trì và có thể chia sẻ giữa nhiều consumer với ít effort hơn bao nhiêu?



Mọi subsystem được bổ sung nên phục vụ mục tiêu này.



\# \*\*PHẦN XVIII — TỔNG KẾT PROJECT FOUNDATION\*\*



\## \*\*87. Project Charter v0.1\*\*



PROJECT CONCEPT · V0.1



\# \*\*Ontology as Code\*\*



A Developer Framework for Building Operational Business Layers



\*\*Problem\*\*



Các phương pháp xây dựng ontology truyền thống có thể khó phát triển và bảo trì khi business semantics, operational logic, governance và data mapping được phân tán giữa nhiều technologies và application layers.



\*\*Vision\*\*



Cho phép developer định nghĩa và vận hành một operational business domain bằng code, độc lập với physical storage và infrastructure cụ thể.



\*\*Core Idea\*\*



Thống nhất Objects, Relations, Functions, Actions, Policies và execution contracts trong một programmable ontology layer.



\*\*Architecture\*\*



Code-first authoring + Meta-model + Lightweight engine + Provider contracts + Developer tooling.



\*\*Target Users\*\*



Software engineers, data engineers, AI engineers và developers xây dựng enterprise business systems.



\*\*Primary Consumers\*\*



Applications, humans, automation và AI Agents.



\*\*Scope\*\*



Một embeddable developer framework, có thể tích hợp với hệ thống hiện tại.



\*\*Non-goal\*\*



Không xây dựng một standalone enterprise platform thay thế Palantir Foundry.



\*\*North Star\*\*



Giảm effort xây dựng và bảo trì business layer mà vẫn đảm bảo business semantics, correctness và governance.



\## \*\*88. Toàn bộ ý tưởng trong một sơ đồ\*\*



\## \*\*Developer\*\*



Defines the operational world



\### \*\*Ontology as Code\*\*



Object



Property



Relation



Interface



Value Type



Function



Action



Policy



Constraint



\*\*Meta-model \& Metadata Registry\*\*



Types · Semantics · Dependencies · Contracts



\## \*\*Ontology Engine\*\*



Resolve



Query



Compute



Authorize



Validate



Act



Mutate



Audit



Embeddable · Governed · Extensible



Infrastructure Adapters



Databases / Datasets



IAM / Policy



External APIs



Workflow / Events



Consumer Adapters



Python SDK



Applications



REST / GraphQL



AI Agent / MCP



\*\*Developer Tooling\*\*



Validate · Test · Inspect · Version · Visualize · Generate



\## \*\*89. Bản chất của thứ chúng ta muốn xây\*\*



Nếu phải giải thích project thông qua những framework quen thuộc, có thể nói:



```

SQLAlchemy

&#x20;   Abstraction cho database interaction.



Pydantic

&#x20;   Abstraction cho structured data models.



FastAPI

&#x20;   Abstraction cho API development.



Pulumi

&#x20;   Abstraction cho infrastructure as code.



dbt

&#x20;   Abstraction cho data transformation models.



Ontology as Code

&#x20;   Abstraction cho operational business layers.

```



OaC nằm ở cấp độ nghiệp vụ, cao hơn database access và không bị ràng buộc vào một consumer cụ thể.



Nó không chỉ trả lời:



```

Dữ liệu có cấu trúc thế nào?

```



Mà còn trả lời:



```

Dữ liệu đại diện cho thực thể nghiệp vụ nào?



Các thực thể liên hệ với nhau thế nào?



Có thể thực hiện những nghiệp vụ nào?



Ai được phép thực hiện?



Điều kiện để thực hiện là gì?



Những trạng thái nào sẽ thay đổi?



Operation được thực thi và theo dõi ra sao?



Application và AI sử dụng chung model thế nào?

```



Đó là lý do chúng ta cần nhiều hơn một ORM, nhiều hơn một knowledge graph, nhiều hơn một API schema và nhiều hơn một function registry.



\# \*\*PHẦN XIX — RECOMMENDED NEXT STEP\*\*



\## \*\*90. Bước nghiên cứu tiếp theo\*\*



Từ những gì đã thống nhất, tôi đề xuất tổ chức project research thành một repository tài liệu trước khi viết framework.



```

ontology-as-code/

│

├── docs/

│   ├── 00-project-vision.md

│   ├── 01-problem-statement.md

│   ├── 02-design-principles.md

│   ├── 03-related-work.md

│   ├── 04-terminology.md

│   ├── 05-meta-model.md

│   ├── 06-object-semantics.md

│   ├── 07-relation-semantics.md

│   ├── 08-action-semantics.md

│   ├── 09-governance-model.md

│   ├── 10-engine-contracts.md

│   ├── 11-adapter-architecture.md

│   ├── 12-language-design.md

│   ├── 13-developer-experience.md

│   └── 14-mvp-specification.md

│

├── research/

│   ├── palantir/

│   ├── semantic-web/

│   ├── orm/

│   ├── policy/

│   ├── workflow/

│   └── related-frameworks/

│

├── decisions/

│   └── architecture-decision-records/

│

├── experiments/

│

├── examples/

│

└── src/

```



Các nghiên cứu chi tiết nên bắt đầu từ Meta-model, nhưng không tách rời Action semantics.



Tôi sẽ xem Object, Relation và Action là ba nhóm trung tâm để bắt đầu khám phá, với Governance là concern xuyên suốt.



```

Object

&#x20;   Những gì tồn tại.



Relation

&#x20;   Những gì liên hệ với nhau.



Action

&#x20;   Những gì có thể xảy ra.



Governance

&#x20;   Những gì được phép xảy ra.



Engine

&#x20;   Những gì thực sự được thực thi.

```



Nếu những khái niệm này được định nghĩa đúng, các quyết định về syntax, JSON IR, providers, SDK và AI integration về sau sẽ có nền tảng vững chắc hơn.



\## \*\*91. Trạng thái hiện tại của dự án\*\*



| Hạng mục               | Trạng thái               |

| ---------------------- | ------------------------ |

| Problem Statement      | Đã định hình             |

| Project Vision         | Đã định hình             |

| Product Positioning    | Đã thống nhất            |

| Scope / Non-goals      | Đã định hình             |

| Design Principles      | Có bản tổng hợp          |

| Reference Architecture | Conceptual v0.1          |

| Meta-model             | Candidate primitives     |

| Action Model           | Conceptual design        |

| Governance Model       | Conceptual design        |

| Engine Architecture    | High-level design        |

| Adapter Contracts      | Chưa đặc tả              |

| Authoring Language     | Chưa quyết định          |

| Related Work Review    | Chưa nghiên cứu hệ thống |

| Prototype              | Chưa triển khai          |

| Technical Validation   | Chưa thực hiện           |

| MVP                    | Chưa chốt specification  |



\### \*\*Lưu ý về bản tổng hợp\*\*



Tài liệu này tổng hợp những nội dung chúng ta đã trao đổi và hệ thống hóa chúng thành một conceptual architecture thống nhất. Tôi có bổ sung cách phân loại, research tracks, acceptance criteria, capability contracts và một số ví dụ để làm rõ hệ quả kỹ thuật của các ý tưởng trước đó.



Những phần bổ sung này là đề xuất nghiên cứu, chưa phải quyết định đã được bạn phê duyệt. Các API minh họa, mức độ phức tạp, reference stack và MVP scope cũng chưa được kiểm chứng bằng implementation hoặc benchmark.



Chúng ta đã định hình được \*\*tính khả thi ở cấp kiến trúc\*\*, nhưng chưa chứng minh tính mới, hiệu quả thực tế hoặc production readiness của framework.



\# \*\*Kết luận\*\*



Điểm xuất phát của toàn bộ ý tưởng là muốn mang giá trị của Palantir Ontology ra ngoài Palantir, đồng thời giải quyết những khó khăn về developer experience khi xây dựng ontology bằng Semantic Web stack truyền thống.



Qua quá trình thảo luận, ý tưởng đã phát triển thành một hướng nghiên cứu rõ ràng hơn:



\*\*Ontology as Code — một code-first developer framework giúp developer xây dựng và vận hành một operational business layer trên infrastructure hiện có.\*\*



Framework này cung cấp:



\- Một ngôn ngữ và meta-model thống nhất để định nghĩa nghiệp vụ.

\- Một cách tổ chức Objects, Relations, Functions, Actions và Policies tự nhiên bằng code.

\- Một lightweight engine giúp thực thi các definitions theo semantics nhất quán.

\- Một adapter architecture giúp tận dụng infrastructure đã tồn tại.

\- Một tập developer tools hỗ trợ phát triển, kiểm thử, phân tích và bảo trì ontology.

\- Một shared operational contract cho application, human, automation và AI Agent.



Điểm quan trọng nhất mà tôi muốn giữ lại là chúng ta \*\*không xây ontology chỉ để biểu diễn tri thức, cũng không xây ontology chỉ để phục vụ AI\*\*.



Chúng ta muốn biến việc xây dựng business layer thành một quá trình phát triển software có abstraction, type system, governance và developer experience tốt hơn.



Nếu làm được điều đó, OaC sẽ có giá trị độc lập với Palantir, với Semantic Web và thậm chí với sự tồn tại của LLM.



\*\*Đó là nền tảng của project mà chúng ta đang hướng tới.\*\*

