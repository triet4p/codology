# Part VII — Governance and Security Model

*[← Part VI — Action Model: The Core of Operational Ontology](06-action-model.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part VIII — Ontology Engine →](08-ontology-engine.md)*

<a id="sec-35"></a>

## 35. Governance là thành phần nội tại của Ontology

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

Data & Services

Ontology-centric governance

Web App

Mobile App

AI Agent

**Shared Ontology Boundary**

Object permissions

Action permissions

Business constraints

Audit / provenance

Data & Services

Cùng một Action được gọi từ Web App hoặc AI Agent phải tuân thủ cùng business semantics và authorization rules.

Điều này chỉ được đảm bảo đối với các operations đi qua enforcement boundary. Framework không thể ngăn một application có direct database credentials bypass ontology nếu hệ thống không được cấu hình để ngăn chặn điều đó.

<a id="sec-36"></a>

## 36. Principal và Execution Context

Mỗi operation cần có thông tin về actor đang thực hiện.

Principal có thể là human user, service account, application, automation worker hoặc AI Agent.

Một conceptual execution context:

```
class ExecutionContext:    principal: Principal    request_id: str    execution_id: str    ontology_version: str    data: DataProvider    authorization: PolicyProvider    transaction: TransactionProvider    audit: AuditProvider    effects: EffectProvider
```

Execution Context là nơi truyền identity, dependencies và operation context xuyên suốt quá trình thực thi.

Nó cũng giúp Action handler không cần hard-code các infrastructure clients.

Principal propagation cần đặc biệt được nghiên cứu đối với AI Agent. Agent thực hiện thay người dùng khác với agent tự chạy dưới service identity.

Framework không nên cho phép một Action vô tình nâng quyền chỉ vì nó gọi một service bên ngoài.

<a id="sec-37"></a>

## 37. Permission Model

Permission có thể xuất hiện ở nhiều cấp độ:

| Cấp độ            | Ví dụ                                      |
| ----------------- | ------------------------------------------ |
| Ontology          | Có quyền khám phá domain Finance           |
| Object Type       | Có quyền truy cập PurchaseOrder            |
| Object Instance   | Chỉ xem đơn hàng thuộc department của mình |
| Property          | Không được đọc supplier bank account       |
| Link              | Không được traverse tới salary records     |
| Function          | Có quyền gọi risk calculation              |
| Action Type       | Có quyền thực hiện approve_order           |
| Action Parameters | Chỉ được approve cho warehouse phụ trách   |
| Mutation          | Chỉ được thay đổi các fields được cho phép |
| Metadata          | Chỉ được discover capabilities phù hợp     |

Framework có thể cung cấp policy contracts và enforcement points, còn policy implementation có thể được thực hiện bằng Python hoặc tích hợp OPA, Cedar, OpenFGA hay enterprise authorization provider phù hợp.

Ví dụ:

```
@policy(    resource=PurchaseOrder,    operation="read")def read_purchase_order(    principal: Principal,    order: PurchaseOrder) -> bool:    return (        principal.has_role("admin")        or principal.department_id == order.department_id    )
```

Điều quan trọng là permission không chỉ được kiểm tra tại UI.

Nó phải được enforce tại runtime execution boundary, bao gồm cả query, traversal và mutation.

<a id="sec-38"></a>

## 38. Authorization và Business Validation là hai khái niệm khác nhau

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

<a id="sec-39"></a>

## 39. Query-time security

Authorization ở cấp Object Set không thể mặc định được giải quyết bằng cách load toàn bộ dữ liệu rồi filter bằng Python.

Ví dụ:

```
orders = PurchaseOrder.objects.filter(    status=Status.PENDING)
```

Query engine nên chuyển những security constraints phù hợp xuống backend khi có thể.

Điều này quan trọng đối với pagination, aggregation, counts, joins và relation traversal.

Một principal không được đọc 1.000 PurchaseOrders thì không nên suy ra thông tin nhạy cảm của chúng thông qua unrestricted aggregation.

Thiết kế cụ thể của policy pushdown là một vấn đề research riêng. Đây là một trong những phần có thể khó hơn đáng kể so với xây dựng type system hoặc metadata registry.

<a id="sec-40"></a>

## 40. Audit và Provenance

Audit trả lời câu hỏi:

> Ai đã làm gì, vào thời điểm nào và kết quả ra sao?

Provenance trả lời câu hỏi:

> Dữ liệu hoặc quyết định này bắt nguồn từ đâu và dựa trên những dữ liệu, logic hay execution nào?

Ví dụ audit record:

```
{
  "executionId": "exec-001",
  "action": "procurement.approve_purchase_order",
  "actionVersion": "1.2.0",
  "principal": "employee-123",
  "target": "PurchaseOrder:PO-001",
  "result": "COMMITTED",
  "changes": {
    "status": {
      "before": "PENDING",
      "after": "APPROVED"
    }
  }
}
```

Provenance có thể bổ sung thông tin về datasource version, model version, input object references, policy decision và các execution dependencies.

Chúng ta có thể học từ PROV-O để xây provenance semantics mà không bắt buộc lưu provenance dưới dạng RDF.

Audit và provenance cũng cần policies riêng về dữ liệu nhạy cảm, access control và retention. Không phải mọi input, intermediate value hay property đều nên được ghi nguyên văn vào log.
