# Part IX — Adapter Architecture and Platform Independence

*[← Part VIII — Ontology Engine](08-ontology-engine.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part X — Developer Experience →](10-developer-experience.md)*

<a id="sec-46"></a>

## 46. Core + Adapter

Để developer sử dụng framework trên nhiều hệ thống, OaC nên áp dụng kiến trúc Core + Adapter.

**Developer's Domain Model**

### OaC Core

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

**Existing Platform Infrastructure**

Core nên càng ít phụ thuộc infrastructure-specific details càng tốt.

Adapters dịch logical operations của ontology thành physical operations của từng backend.

<a id="sec-47"></a>

## 47. Provider Contracts

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

<a id="sec-48"></a>

## 48. Capability Model

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
class ApprovePurchaseOrder(Action):    requires = {        Capability.WRITE,        Capability.ATOMIC_TRANSACTION,        Capability.CONCURRENCY_CONTROL    }
```

Nếu provider thiếu một capability bắt buộc, framework cần trả về lỗi rõ ràng hoặc yêu cầu cấu hình bổ sung.

Đây là cơ chế giúp platform independence không biến thành sự đánh đổi âm thầm về correctness.

<a id="sec-49"></a>

## 49. Progressive Adoption

Framework nên được thiết kế để developer có thể áp dụng từng phần.

1

**Typed Modeling**

Object, Property, Relation và Value Type.

2

**Data Binding**

Ánh xạ business objects vào database hoặc API hiện có.

3

**Governed Actions**

Chuẩn hóa business operations, permissions và validation.

4

**Shared Business Layer**

Nhiều application sử dụng chung ontology.

5

**AI Integration**

Expose schema, queries, functions và actions cho agents.

6

**Advanced Execution**

Approval, asynchronous workflows, advanced auditing.

Một developer có thể bắt đầu bằng việc khai báo vài Object Types. Sau đó bổ sung Actions và governance khi cần.

Không bắt buộc doanh nghiệp phải chuyển dữ liệu hoặc thay toàn bộ architecture chỉ để sử dụng OaC.

Tuy nhiên, progressive adoption cần phân biệt với optional security. Khi một Action được định nghĩa là governed operation, các enforcement requirements của nó không nên bị bỏ qua chỉ vì developer chưa tích hợp đầy đủ provider.
