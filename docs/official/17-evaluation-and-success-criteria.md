# Part XVII — Evaluation and Success Criteria

*[← Part XVI — Proof of Concept and MVP](16-proof-of-concept-and-mvp.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part XVIII — Project Foundation Summary →](18-project-foundation-summary.md)*

<a id="sec-83"></a>

## 83. Làm thế nào để chứng minh framework có giá trị?

Cần so sánh ít nhất ba cách xây dựng cùng một nghiệp vụ.

| Approach   | Nội dung                                                         |
| ---------- | ---------------------------------------------------------------- |
| Baseline A | Python application, SQLAlchemy và business services thông thường |
| Baseline B | Semantic Web-based ontology kết hợp application logic            |
| Proposed C | Ontology as Code Framework                                       |

Cả ba nên được đánh giá trên một business domain có functional requirements tương đương.

Không nên cố tình xây baseline kém chất lượng để làm cho OaC trông tốt hơn.

<a id="sec-84"></a>

## 84. Evaluation Dimensions

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

<a id="sec-85"></a>

## 85. Candidate Acceptance Tests

**PoC Acceptance Checklist**

0/12

**Shared semantic model**

Python SDK, Web API và AI Agent đều nhìn thấy cùng Object Type contract.

**Shared action semantics**

Cùng Action được invoke từ nhiều consumer nhưng sử dụng chung business logic.

**Authorization enforcement**

Principal không có quyền bị từ chối tại runtime.

**Business validation**

Order ở trạng thái không hợp lệ không thể được approve.

**Transactional mutation**

Khi mutation thứ hai thất bại, mutation đầu được rollback trên backend transactional.

**Auditability**

Có thể truy xuất execution record và kết quả Action.

**Metadata introspection**

Có thể lấy schema của Objects và Actions mà không đọc toàn bộ source code.

**Backend capability checks**

Write Action bị từ chối trên read-only provider.

**Adapter substitution**

Cùng domain contract có thể sử dụng memory và relational providers trong tập capabilities tương đương.

**Business-rule evolution**

Thay đổi approval rule chỉ cần sửa tại shared domain layer.

**Developer tooling**

Invalid definitions được phát hiện trước khi thực thi.

**AI consumption**

Agent có thể discover, validate và invoke một Action hợp lệ.

Đây là danh sách acceptance criteria dự kiến, chưa phải những tests đã được thực hiện.

<a id="sec-86"></a>

## 86. North Star

Thước đo thành công của project không phải là framework có bao nhiêu features tương tự Palantir.

Cũng không phải số lượng adapters, độ phức tạp của compiler hay khả năng hỗ trợ hàng tỷ Objects ngay từ đầu.

Thước đo chính là:

> Developer có thể xây dựng một operational business layer đúng đắn, dễ đọc, dễ kiểm thử, dễ bảo trì và có thể chia sẻ giữa nhiều consumer với ít effort hơn bao nhiêu?

Mọi subsystem được bổ sung nên phục vụ mục tiêu này.
