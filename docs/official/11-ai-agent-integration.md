# Part XI — AI Agent Integration

*[← Part X — Developer Experience](10-developer-experience.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part XII — Related Technologies and Design References →](12-related-technologies.md)*

<a id="sec-58"></a>

## 58. AI là consumer tự nhiên của Ontology

Một điểm chúng ta đã thống nhất là ontology không nên tồn tại chỉ vì LLM hay AI Agent.

Ngay cả khi không có AI, developer vẫn có lý do để sử dụng framework nhằm tổ chức business logic, semantics và governance.

Nhưng khi có AI Agent, ontology tạo ra một interface đặc biệt hữu ích.

### Không có Ontology Layer

```
AI Agent
    ├── Database schemas
    ├── SQL queries
    ├── Service APIs
    ├── Application code
    ├── Business documents
    └── Permission rules
```

Agent phải tự hiểu physical schema, mapping, business semantics và cách thực hiện từng operation.

Ví dụ:

```
trx_ord_hdr.status = 3
3 nghĩa là gì?
Agent có được UPDATE status không?
Có cần cập nhật Budget không?
Approve có cần thông báo ERP không?
Ai được phép approve?
```

### Có Ontology Layer

```
AI Agent
    ├── Discover PurchaseOrder
    ├── Query pending orders
    ├── Traverse supplier and budget
    ├── Calculate risk
    ├── Inspect ApprovePurchaseOrder
    └── Invoke governed Action
```

AI Agent sử dụng cùng operational semantics như các consumer khác.

<a id="sec-59"></a>

## 59. Ontology như một Contract cho AI

**AI Agent**

Understand · Reason · Decide · Act

**Discover**

Schema, relationships, capabilities

**Read**

Query, traverse, aggregate

**Act**

Functions, validate, execute

**Governed Ontology Interface**

Principal · Authorization · Validation · Audit

**Operational Domain Model**

Objects · Functions · Actions · Policies

Ontology cung cấp structured context về business domain, đồng thời cung cấp operational capabilities.

Điều này khác với chỉ sinh schema description cho AI, chỉ xây knowledge graph RAG, hoặc chỉ expose SQL tools.

Ontology cần có contract cho cả understanding và execution.

<a id="sec-60"></a>

## 60. Dynamic Tool Discovery

Nếu một enterprise ontology có hàng nghìn Actions, việc đưa tất cả Action schemas vào agent context sẽ không hiệu quả.

Một hướng đáng nghiên cứu là cung cấp một tập generic meta-tools để agent khám phá ontology.

```
search_object_types(query)describe_object_type(type_id)search_actions(query)describe_action(action_id)query_objects(type_id, filters)traverse_links(object_ref, link_type)aggregate_objects(object_set, metric)validate_action(action_id, parameters)execute_action(action_id, parameters)
```

Agent có thể khám phá domain, tìm relevant Actions, lấy parameter schemas và invoke operations theo nhu cầu.

Metadata registry trở thành một nguồn dynamic capabilities cho agent harness.

Điểm này liên hệ trực tiếp với hướng nghiên cứu AI FDE của chúng ta: agent không nhất thiết phải được cung cấp mọi domain-specific capability ngay từ đầu, mà có thể discover các capabilities liên quan trong quá trình xử lý task.

Tuy nhiên, thiết kế OaC không phụ thuộc vào giả thuyết rằng Palantir AI FDE sử dụng chính cơ chế discovery này. Đây là đề xuất của chúng ta.

<a id="sec-61"></a>

## 61. Ontology-based MCP Integration

Một hướng integration tiềm năng:

```
AI Agent / MCP Client
        │
        ▼
Ontology MCP Adapter
        │
        ├── Metadata discovery
        ├── Object query
        ├── Function invocation
        ├── Action validation
        └── Action execution
        │
        ▼
OaC Engine
        │
        ▼
Existing Business Systems
```

MCP chỉ nên là một consumer adapter, không phải nền móng của ontology.

Framework vẫn có thể expose cùng semantics qua Python SDK, REST API hoặc GraphQL.

Nếu chỉ xây một MCP server chứa các business tools, chúng ta chưa giải quyết đầy đủ vấn đề ontology modeling, shared metadata, dependencies và execution semantics.

<a id="sec-62"></a>

## 62. AI Safety tại Action Boundary

Agent có thể hiểu sai intent, truyền sai parameters hoặc lập kế hoạch không phù hợp.

Ontology không đảm bảo rằng quyết định của AI luôn đúng. Nhưng nó có thể giới hạn những operations agent được phép yêu cầu và enforce business rules.

Ví dụ:

```
Agent proposes:
    Approve all pending purchase orders
```

Runtime có thể kiểm tra từng operation theo principal, target object, business constraints, transaction requirements và approval policy.

Mutation Plan cũng tạo cơ hội để human review dự kiến state changes trước commit.

Các cơ chế này có ích cho AI governance, nhưng không thay thế risk assessment, human oversight hoặc các biện pháp bảo mật của hệ thống.
