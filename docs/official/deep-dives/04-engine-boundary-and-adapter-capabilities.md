# Engine Boundary and Adapter Capabilities

*Tài liệu deep-dive 04 — Engine boundary & adapter capabilities. Phạm vi: chương chính thức 08 (§41–45) và 09 (§46–49), kế thừa 01 (load/bind/invoke), 02 (pin/live, expand–contract) và 03 (contract, idempotency, effect). Ví dụ xuyên suốt: `ApprovePurchaseOrder` ghi `PurchaseOrder` trong PostgreSQL và gọi `finance.reserve_budget` ghi `Budget` trong ERP. Mọi đoạn code là minh họa declaration/binding, không phải syntax đã chốt.*

*Quy ước đọc: **[Nguồn]** = khẳng định đã kiểm chứng từ tài liệu sơ cấp; **[Đề xuất OaC]** = quyết định thiết kế do tài liệu này đề xuất, chưa chốt; **[Câu hỏi mở]** = việc cần phase sau hoặc thí nghiệm trả lời.*

## Executive Summary and Recommended Approach

**[Đề xuất OaC]** Khuyến nghị chính của tài liệu này:

1. Giữ engine là **embeddable orchestrator** (§41, §44): sở hữu lifecycle, enforcement boundary, mutation contract, effect coordination và audit schema; không sở hữu storage, SQL execution, IAM backend, durable workflow hay message delivery (§43).
2. Mọi bảo đảm runtime phải đi qua **binding artifact tường minh** nhưng chỉ thương lượng đúng requirements contract dùng tới: atomicity đơn thuần chỉ cần transaction enlistment + concurrency guard thật sự; các trường outbox/effect/policy chỉ bắt buộc khi contract dùng effect hoặc policy tươi. Thiếu một trường **được dùng** là từ chối `Transaction.atomic()` ở deployment binding.
3. Từ chối strict cross-resource atomic khi không có shared transaction; saga/compensation là **contract khác**, không phải cách thỏa atomic cũ; compensation có thể thất bại và thiếu isolation mặc định.
4. Triển khai trước: local atomic + conditional write (`expectedVersion`/`StalePlan`), idempotency có retention + reconciliation lookup, outbox có dedup id, ghi policy revision vào audit. Chưa làm: 2PC manager, durable workflow backend, auto-compensation.

## Responsibility Map: Engine, Handler, Adapter, Host

**[Nguồn]** Theo §43, engine sở hữu phía logical (identity, resolution contract, query semantics, enforcement boundary, lifecycle/invocation context, mutation contract, effect coordination/status, audit schema) và delegate phía physical cho infrastructure (storage, SQL/search indexes, IAM backend, durable workflow, native transaction, delivery, log platform).

**[Đề xuất OaC]** Phân vai bốn bên cho ví dụ `ApprovePurchaseOrder`:

- **Engine**: resolve `OrderRef` theo contract, chạy `authorize → validate → resolve → revalidate → commit` (§44 sketch), từ chối khi provider thiếu capability (§48), ghi execution record (§30).
- **Handler** (developer implementation, §28): nghiệp vụ thuần túy — tính `normalized_amount`, quyết định mutation trên object đã resolve. Chỉ chạm những gì declaration đã khai báo (`reads`/`writes`/`calls`); undeclared access là lỗi hoặc rủi ro đã ghi nhận (deep-dive 01).
- **Adapter**: dịch logical operation thành physical operation (§46–47: `DataProvider.resolve/query/apply`, `TransactionProvider.begin/commit/rollback`, `PolicyProvider.authorize`). Một adapter chỉ cam kết đúng capability nó có (§48).
- **Host** (application/infrastructure): cung cấp providers thật (PostgreSQL, ERP client, Kafka, OPA sidecar), cấu hình retention, vận hành relay và log platform.

Bằng chứng runtime phân biệt bốn bên: `StalePlan(expectedVersion=12, current=13)` là lỗi engine-level revalidation (§31), không phải lỗi handler; `NoSharedTransaction` là lỗi deployment binding (deep-dive 01), không phải lỗi invoke; callback outsider bị `DENIED` mà execution vẫn `AWAITING_APPROVAL` chứng minh denial thuộc cửa authorization, không thuộc engine transition (deep-dive 03).

## Binding Artifact: What Must Be Bound Before Commit

**[Nguồn]** Theo §48, Action khai báo requirements (`requires = {WRITE, ATOMIC_TRANSACTION, CONCURRENCY_CONTROL}`); engine kiểm tra provider có đáp ứng không, thiếu thì lỗi rõ ràng thay vì đánh đổi âm thầm.

**[Đề xuất OaC]** Binding artifact tối thiểu — chỉ gồm các trường contract thật sự dùng (atomicity đơn thuần không đòi outbox/policy):

```python
BindingEntry(
    resource="PurchaseOrder", provider="postgres-main",
    enlisted_tx="pg-main-tx#<txid-concrete>",  # cùng label chưa đủ: phải cùng transaction enlisted thật sự
    concurrency="guarded-debit(WHERE balance >= amount AND version = :v)",
    commit_check="rowcount == 1 else StalePlan/Conflict",
)
```

- **Resource/enlisted transaction**: nhãn domain chung chưa đủ — hai resources chỉ atomic khi cùng enlisted trong **một transaction vật lý** (cùng connection/txid). Đòi `Transaction.atomic()` mà enlistment tách đôi là `NoSharedTransaction`.
- **Conditional write/isolation**: invariant budget giữ bằng guarded debit kiểm tra **nguyên tử trong cùng statement** (`balance >= amount`, `version = :v`) và xác nhận `rowcount == 1`; `rowcount == 0` là conflict, không phải success. **[Nguồn]** DynamoDB chỉ coi conditional write là retry-an-toàn khi condition kiểm tra đúng attribute mà write thay đổi; increment vô điều kiện không idempotent và retry sau uncertain-response có thể double-apply.
- **Sau conflict đọc lại/tính lại; guard ≠ idempotency**: `StalePlan`/guard-fail buộc re-read state rồi recompute mutation; guard chống race, không thay thế idempotency key. Retry mù cùng payload mà không re-read vẫn sai.
- **Idempotency retention + reconciliation**: **[Nguồn]** Stripe lưu status + body của request đầu tiên sau khi endpoint bắt đầu thực thi và trả lại cho retry cùng key (kể cả `500`); validation hoặc xung đột concurrent không lưu nên được retry; key tái dùng sau khi prune thành request mới. Hệ quả: sau prune **không tự lặp lại OaC action** — giữ `UNKNOWN` hoặc reconcile; nếu local ledger uy tín nằm cùng transaction với state thì tra ledger là đủ, không bắt buộc lookup provider ngoài.
- **Effect ack (chỉ khi contract dùng effect)**: cần consumer-dedup bền (bảng dedup/inbox cùng tx với state) hoặc downstream idempotent trong retention; **[Nguồn]** Debezium outbox SMT mang event `id` trong header để khử trùng lặp, relay at-least-once nên duplicate là bình thường. Broker ack chỉ là vận chuyển — không đồng nghĩa business effect đã thực hiện; lost ack xử lý bằng redelivery + dedup, không "un-commit".
- **Policy freshness (chỉ khi contract đòi policy tươi)**: **[Nguồn]** OPA phân phối bundle eventually consistent, poll định kỳ, activate không restart; mỗi decision log mang bundle revision để audit. Activation timestamp hay `304 Not Modified` không chứng minh được tươi — contract phải chọn tường minh **hard-fail** (từ chối commit khi stale quá ngưỡng) hay **advisory** (commit kèm cảnh báo + revision), và không hứa thu hồi tức thời.

## Declared Capability versus Conformance versus Runtime Evidence

**[Đề xuất OaC]** Ba lớp không được gộp:

1. **Static declared**: declaration nói "tôi cần `ATOMIC_TRANSACTION`" (§48). Kiểm tra ở deployment binding, chưa chạm dữ liệu.
2. **Conformance**: adapter tự báo + suite kiểm tra (ví dụ outbox relay có emit `id` header không, conditional write có trả conflict không). Conformance pass không bảo đảm runtime không lỗi.
3. **Runtime evidence**: traces quan sát được (`StalePlan`, `ConditionalCheckFailed`, callback `DENIED`, effect `PENDING_RETRY`, decision log kèm bundle revision) chỉ **bác bỏ hoặc minh họa** — một run pass không chứng minh mọi interleaving đều đúng; bảo đảm đầy đủ cần guard nguyên tử + review, không suy từ "chạy một lần xanh".

Nhầm conformance với runtime là lỗi thiết kế trung tâm: provider "hỗ trợ transaction" ở bảng capability không đồng nghĩa hai resource cùng enlisted trong một transaction vật lý ở lần commit này.

## Local Single DB versus PG plus ERP

**[Nguồn]** §32 cho local atomic ủy quyền cho backend bằng một commit duy nhất; split backend không shared transaction thì từ chối `Transaction.atomic()` ở deployment binding, muốn đi tiếp phải ký contract khác.

- **Local single DB** (`PurchaseOrder` + `Budget` cùng một PostgreSQL, cùng enlisted transaction): một commit nguyên tử **và** guarded debit (`WHERE balance >= amount AND version = :v`, `rowcount == 1`) mới giữ invariant; revalidation "đọc rồi ghi" không đủ.
- **PG + ERP** (`PurchaseOrder@postgres` + `Budget@erp`): không tồn tại commit nguyên tử chung — từ chối `Transaction.atomic()`, chuyển sang saga/compensation hoặc outbox cho event, với trạng thái trung gian quan sát được.
- **Cùng brand DB không đồng nghĩa cùng transaction**: **[Nguồn]** PostgreSQL 2PC (`PREPARE/COMMIT PREPARED`) dành cho external transaction manager, không tự phối hợp; `postgres_fdw` quản lý remote transaction theo local transaction nhưng không thay thế coordinator cho mọi cặp database. Hai database PostgreSQL riêng qua hai connections vẫn cần manager bên ngoài hoặc pattern bù trừ ở application.

## Saga Is Separate Contract; Compensation Can Fail

**[Nguồn]** Saga là chuỗi local transactions được phối hợp đáng tin cậy: nếu step sau vi phạm business rule thì các step đã xong được gỡ bằng compensating transactions; tài liệu chốt hai nhược điểm — thiếu automatic rollback (developer phải thiết kế compensation tường minh) và thiếu isolation (đồng thời nhiều saga gây anomaly, phải dùng countermeasures sau phân tích cẩn thận).

Hệ quả cho ví dụ: `ReserveBudget@erp` thất bại sau khi `PurchaseOrder@postgres` đã commit không "rollback" được — chỉ có thể chạy compensation (`cancel`/`release`) mà bản thân compensation cũng có thể thất bại, hết retry, hoặc cần duyệt tay. Saga vì thế là contract mới với trạng thái `PENDING`/`COMPENSATING`/`COMPENSATED` quan sát được, retry policy và escalation, không phải `Transaction.atomic()` đổi tên.

## Denial of Callback Leaves Execution Pending

Kế thừa deep-dive 03: callback bị `DENIED` (outsider, self-approval vi phạm policy ví dụ, approver mất quyền) chỉ ghi audit cho callback đó; execution đang `AWAITING_APPROVAL` không chuyển trạng thái. Mọi thiết kế "deny là fail cả execution" đều sai contract vì lẫn lộn hai authority (người yêu cầu vs người duyệt) và hai cửa (authorization vs business precondition, §38).

## Two Concurrent Orders Competing for One Budget

Hai executions cùng tranh `Budget:B-001` còn đủ cho đúng một đơn là scenario phân biệt bắt buộc: revalidation suông ("đọc rồi ghi") để lọt double-spend dưới race; chỉ guarded debit nguyên tử trong cùng statement (`balance >= amount AND version = :v`, `rowcount == 1`) mới giữ invariant. Guard-fail buộc re-read/recompute, không retry mù; guard chống race, không thay thế idempotency key. Với PG + ERP không shared transaction, không tồn tại cơ chế tương đương — phải chấp nhận trạng thái trung gian + compensation, hoặc serialize tranh chấp qua một owner duy nhất.

## Decision Table

| Hình thức | Khi dùng | Cam kết quan sát được | Cái giá |
| --- | --- | --- | --- |
| Local atomic (cùng enlisted tx) | Hai writes cùng enlisted trong một tx vật lý + guarded debit | Một commit; guard-fail (`rowcount == 0`) trả `StalePlan`, re-read/recompute rồi mới retry | Không mở rộng sang ERP/API; guard ≠ idempotency key |
| SplitBackend từ chối atomic | `PurchaseOrder@pg` + `Budget@erp` mà đòi `Transaction.atomic()` | Lỗi deployment binding `NoSharedTransaction`, không downgrade lặng lẽ | Phải ký contract khác mới đi tiếp |
| Saga + compensation (contract riêng) | Split backend chấp nhận trạng thái trung gian | `PENDING → COMMITTED / COMPENSATING → COMPENSATED / ESCALATED`; compensation có thể thất bại | Mất isolation mặc định; cần countermeasure + escalation |
| Outbox cho effect | Effect sau commit (chỉ khi contract dùng) | Commit `COMMITTED` + effect `PENDING_RETRY/DELIVERED`; dedup bền (inbox cùng tx) hoặc downstream idem trong retention; broker ack ≠ effect đã làm | Relay at-least-once; duplicate là bình thường |
| Durable execution | Approval dài ngày, retry/compensation phức tạp | Progress sống sót crash; phân biệt transient/permanent | Nặng nhất; chỉ khi state machine + retry có key không đủ (§45 MVP local trước) |

## Falsifiable Scenarios and Spike (Not Executed)

**Chưa thực thi — mọi "kết quả kỳ vọng" là dự đoán cần kiểm chứng, không phải bằng chứng.** Dự kiến đặt tại `fixtures/engine-binding/`:

- Local single PG: hai đơn đồng thời tranh một budget vừa đủ một đơn → đúng một `COMMITTED` bằng guarded debit (`rowcount == 1`), một guard-fail + re-read/recompute; trace minh họa (không chứng minh mọi interleaving) không double-spend.
- PG + ERP đòi `Transaction.atomic()` → deployment binding từ chối `NoSharedTransaction`; cùng contract đổi sang saga thì đi tiếp với trạng thái `COMPENSATING` quan sát được khi ERP rớt.
- Compensation thất bại (ERP từ chối release) → execution `ESCALATED`, không tự thành `COMMITTED`; audit giữ cả hai attempts.
- Timeout sau commit, retry cùng request key → trả response đã lưu khi còn retention; sau prune **không tự lặp lại action** — giữ `UNKNOWN` hoặc reconcile; ledger uy tín cùng tx với state thì tra ledger là đủ, cấm retry mù.
- Outbox relay crash trước ack → redelivery trùng `id` header; consumer dedup bền (hoặc downstream idem trong retention) cho một effect duy nhất, execution vẫn `COMMITTED`; broker ack không tính là effect đã làm.
- Policy bundle stale quá ngưỡng đã công bố → theo chính sách contract: hard-fail từ chối commit, hoặc advisory commit kèm cảnh báo + revision; timestamp/`304` không thay thế ngưỡng này; không hứa thu hồi tức thời.
- Callback outsider → callback `DENIED`, execution vẫn `AWAITING_APPROVAL`; self-approval theo policy ví dụ cho kết quả ngược khi tắt policy.

Điều kiện bác bỏ (chống false-positive — một run pass không tính là pass): bác bỏ khi trace tái hiện được atomic xuyên PG–ERP không coordinator, double-spend dưới race dù đã guarded debit, compensation-fail vẫn tự `COMMITTED`, retry mù sau prune cho kết quả sai mà không reconcile, duplicate `id` cho effect lặp, hoặc effect lỗi kéo cả execution về `FAILED` mất `before/after`. Một run đơn lẻ pass chỉ minh họa, không chứng minh tính đúng cho mọi interleaving.

## Recommendations: What to Implement First and What Not Yet

**[Đề xuất OaC]** Làm trước: registry + load/bind/invoke tối thiểu (§44 sketch chỉ sync path); deployment binding từ chối cross-domain atomic khi enlistment tách đôi; guarded debit + `StalePlan` với re-read/recompute; idempotency key có retention (sau prune giữ `UNKNOWN`/reconcile, ledger cùng tx là đủ); outbox cùng transaction với state + consumer dedup bền (chỉ khi contract dùng effect); ghi policy revision vào audit với chính sách hard-fail/advisory tường minh (chỉ khi contract đòi policy tươi); phân biệt `DENIED`/`REJECTED`/`AWAITING_APPROVAL` (deep-dive 03).

Chưa làm: 2PC/external transaction manager; durable workflow backend (§45 để sau local); saga orchestrator đầy đủ; FX subsystem toàn cục (chỉ cần source/target/quote theo deep-dive 03); auto-compensation được bảo đảm; SDK/consumer contract versioned cho tới khi trigger ở deep-dive 01 kích hoạt.

## Open Questions

**[Câu hỏi mở]**

- Contract chọn hard-fail hay advisory cho policy stale (ngưỡng bao nhiêu, ai override, override ghi audit ra sao)? Không hứa thu hồi tức thời — độ trễ phân phối bundle là một phần contract.
- Retention idempotency bao lâu cho từng resource, ai trả chi phí ledger, và prune policy công bố ở đâu?
- Outbox relay do ai vận hành (engine embedded hay host), và redelivery bảo đảm tới đâu trước khi giao cho durable backend?
- Child `ReserveBudget` ở ontology version khác parent trong expand–contract thì pin binding artifact theo version nào?

## References and Web Sources

- [PostgreSQL — Two-Phase Transactions](https://www.postgresql.org/docs/current/two-phase.html) — `PREPARE/COMMIT PREPARED` dành cho external transaction manager. Dùng cho: cùng brand DB không cùng transaction.
- [PostgreSQL — postgres_fdw](https://www.postgresql.org/docs/current/postgres-fdw.html) — quản lý remote transaction theo local transaction; không thay thế coordinator chung. Dùng cho: PG + ERP/split backend.
- [DynamoDB — Working with items (Conditional writes, Atomic counters)](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/WorkingWithItems.html) — conditional write retry-an-toàn khi condition đúng attribute bị đổi; atomic counter vô điều kiện không idempotent. Dùng cho: aggregate invariant.
- [Stripe — Idempotent requests](https://docs.stripe.com/api/idempotent_requests) — lưu status + body sau khi thực thi bắt đầu; validation/concurrent-conflict không lưu; prune sau ~24h thành request mới. Dùng cho: retention + reconciliation.
- [Debezium — Outbox Event Router](https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html) — outbox insert thành message, `id` trong header để khử trùng lặp. Dùng cho: effect ack/duplicate/lost ack.
- [Microservices.io — Pattern: Saga](https://microservices.io/patterns/data/saga.html) — chuỗi local transactions; thiếu automatic rollback và isolation; cần compensating transactions và countermeasures. Dùng cho: saga là contract riêng.
- [OPA — Bundles](https://www.openpolicyagent.org/docs/management-bundles) — phân phối eventually consistent, activate không restart, ETag/`304`, long polling. Dùng cho: policy freshness.
- [OPA — Decision Logs](https://www.openpolicyagent.org/docs/management-decision-logs) — mỗi decision mang bundle revision để audit. Dùng cho: policy revision evidence.

Chương chính thức OaC sử dụng: `08-ontology-engine.md` (§41 embeddable engine, §43 ownership/delegation, §44 sync sketch, §45 execution modes), `09-adapter-architecture.md` (§46 core + adapter, §47 provider contracts, §48 capability model, §49 progressive adoption), cùng deep-dive `01-static-architecture-and-definition-lifecycle.md` (deployment binding, `NoSharedTransaction`), `02-developer-workflow-and-model-evolution.md` (pin/live, expand–contract) và `03-action-contract-and-business-workflow.md` (idempotency, `UNKNOWN`, effect, callback).
