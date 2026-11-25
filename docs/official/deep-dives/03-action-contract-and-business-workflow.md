# Action Contract and Business Workflow

*Tài liệu deep-dive 03 — Action contract & business workflow. Phạm vi: chương chính thức 06 (§26–34), 07 (§36–38, §40), tiếp nối deep-dive 01 (load/bind/invoke) và 02 (threshold `>`/`>=`, tiền tệ). Ví dụ xuyên suốt: `ApprovePurchaseOrder` với ngưỡng bao gồm (`>= 100_000` trên số tiền đã chuẩn hóa). Giá trị ngưỡng và lệnh cấm tự duyệt là policy ví dụ của domain này, không phải luật core của framework — core là cơ chế (so sánh trên số chuẩn hóa, phân biệt authority, binding intent, revalidation).*

*Quy ước đọc: **[Nguồn]** = khẳng định đã kiểm chứng từ tài liệu sơ cấp; **[Đề xuất OaC]** = quyết định thiết kế do tài liệu này đề xuất, chưa chốt; **[Câu hỏi mở]** = việc cần phase sau hoặc thí nghiệm trả lời. Mọi đoạn code là minh họa declaration, không phải syntax đã chốt. Cơ chế provider chi tiết (locking, outbox, saga, workflow engine) thuộc deep-dive 04, tài liệu này chỉ chốt contract quan sát được.*

## Executive Summary and Recommended Approach

**[Đề xuất OaC]** Khuyến nghị chính của tài liệu này:

1. So sánh ngưỡng trên số tiền đã chuẩn hóa về một comparison currency khai báo trong declaration. Khi currency của đơn khác comparison currency, declaration phải ghi rõ source field, target currency và quote/version dùng để quy đổi — không yêu cầu một FX subsystem toàn cục bắt buộc.
2. Ba kết quả invoke-time không được gộp: `DENIED` (thiếu quyền, §38), `REJECTED` (đủ quyền nhưng precondition nghiệp vụ rớt, §38), `AWAITING_APPROVAL` (đủ quyền, đủ điều kiện sơ bộ, còn thiếu duyệt, §30).
3. Core phân biệt hai authority (người yêu cầu vs người duyệt) và ủy quyền thu hẹp cho `ReserveBudget` liên domain, không bao giờ dùng quyền ambient của service. Cấm tự duyệt là policy ví dụ của domain này, không phải luật core.
4. Approval gắn với material intent (execution + version + số tiền chuẩn hóa gồm source/target/quote + phiên bản object), revalidate live trước commit; hết hạn/thu hồi thì quay lại chờ hoặc từ chối, không commit lặng lẽ.
5. Phân biệt `commit không rõ kết quả` với `effect chưa giao`: commit rồi mà notification/event lỗi thì execution vẫn `COMMITTED` kèm effect treo — không đánh dấu toàn bộ Action là chưa xảy ra (§33).

## Observable Transitions

**[Nguồn]** Theo §30, một invoke trả về `executionId`, `action`, `actionVersion`, `ontologyVersion`, `principal`, `status` và `requiredApproval` khi chờ duyệt. Theo §38, authorization và business precondition là hai cửa khác nhau và cho hai bảng kết quả khác nhau (Allowed/Denied × Satisfied/Failed).

**[Đề xuất OaC]** Máy trạng thái tối thiểu quan sát được của `ApprovePurchaseOrder`:

- `AWAITING_APPROVAL`: đủ quyền `purchase_order.approve`, đơn ở trạng thái duyệt được, `normalized_amount >= 100_000` nên còn thiếu duyệt của `finance_director`.
- `DENIED`: principal thiếu quyền tại thời điểm kiểm tra — không vào approval flow, không cho biết chi tiết nghiệp vụ vượt quá quyền được thấy (§38 cảnh báo lộ dữ liệu qua error response).
- `REJECTED`: đủ quyền nhưng precondition rớt (đơn đã cancel, budget không đủ, `expectedVersion` lệch và chính sách chọn từ chối thay vì chờ).
- `COMMITTED` / `FAILED`: trạng thái cuối của commit (thành công / lỗi không phục hồi được ở tầng contract).

Gộp `DENIED` với `REJECTED` làm consumer không biết phải xin quyền, sửa nghiệp vụ, hay chờ duyệt — đúng phân biệt §38 đã chốt.

**[Đề xuất OaC]** Callback bị `DENIED` không đồng nghĩa execution bị kết thúc. Một approval callback không đủ thẩm quyền (outsider, hoặc self-approval vi phạm policy ví dụ) bị từ chối ở cửa callback; execution đang chờ vẫn ở `AWAITING_APPROVAL`, chỉ callback bị từ chối được ghi audit. Execution chỉ chuyển trạng thái trên quyết định đã authorized.

Ngưỡng bao gồm trên tiền chuẩn hóa (kế thừa deep-dive 02, thay đổi A + C):

```python
approval = Approval.conditional(
    when=Param("order").normalized_amount >= 100_000,
    role="finance_director",
)
```

**[Đề xuất OaC]** `normalized_amount` là số tiền đã quy về comparison currency khai báo (ví dụ VND), kèm `source_currency`, `quote_version` (bảng giá/phiên bản quy đổi đã dùng) trong audit khi có chuyển đổi. Không chuẩn hóa mà so trực tiếp `amount >= 100_000` là lỗi contract: `100_000 VND` và `100_000 USD` đi cùng một luồng. Tài liệu này không bắt buộc một FX subsystem chung — chỉ bắt buộc khai báo nguồn/đích/phiên bản quy đổi để audit tái hiện được.

## Authority: Requester, Approver, and Delegated Child

**[Nguồn]** §34 đặt câu hỏi authorization/composition: action cha có quyền invoke action con không, action con chạy dưới identity nào, có được dùng service identity thay user không. §36 yêu cầu principal propagation tường minh, cấm nâng quyền vô tình khi gọi service ngoài.

**[Đề xuất OaC]** Ba quy tắc authority cho ví dụ này:

1. **Người yêu cầu ≠ người duyệt (separation of duties, core).** Requester authority (tạo execution) và approver authority (thỏa `requiredApproval`) là hai vai khác nhau, audit ghi cả hai principal. Lệnh cấm tự duyệt (`employee-123` không duyệt chính đơn mình tạo dù giữ role duyệt) là policy ví dụ của domain này — framework cung cấp cơ chế tách vai, từng domain quyết định có cấm tự duyệt không.
2. **Người duyệt cần cả hai:** role `finance_director` cho approval requirement **và** permission `purchase_order.approve` còn hiệu lực tại thời điểm duyệt (live check, học từ submission criteria của Palantir — conditions đánh giá tại thời điểm submit theo current user/parameter/context).
3. **Ủy quyền thu hẹp cho `ReserveBudget`.** Khi `ApprovePurchaseOrder` gọi `finance.reserve_budget`, child chạy dưới principal ủy quyền (down-scoped delegation từ requester, giới hạn `budget.reserve` trên đúng `Budget:B-001`), không kế thừa toàn bộ quyền của parent, không dùng admin identity của service. Child có thể yêu cầu approval riêng (§34) — khi đó parent ở `AWAITING_APPROVAL` cho tới khi child duyệt xong.

## Approval Binds Intent; Revalidate Before Commit

**[Nguồn]** Theo §31, giữa lúc lập Mutation Plan và lúc commit world state có thể đổi; runtime phải revalidate assumptions hoặc dùng concurrency guarantees của backend. Mutation Plan mẫu mang `expectedVersion` cho từng object.

**[Đề xuất OaC]** Approval không duyệt "đơn PO-001 nói chung" mà duyệt một material intent cụ thể: (`executionId`, `actionVersion`, `normalized_amount` + `source_currency` + `target_currency` + `quote_version`, `expectedVersion` của `PurchaseOrder`, phạm vi `ReserveBudget`). Chỉ thay đổi material (đổi kết quả approval, đổi số tiền chuẩn hóa, đổi phiên bản object) mới kích hoạt reapproval; thay đổi phi material không bắt duyệt lại. Trước commit, engine revalidate live:

- Principal còn quyền không (authorization live, theo kiểu OPA và submission criteria).
- Budget còn đủ không, đơn còn ở trạng thái duyệt được không.
- `expectedVersion` còn khớp không — lệch thì từ chối plan cũ (`StalePlan`), không ghi đè.

Tài liệu này không tuyên bố revalidation "chống được TOCTOU" nói chung. Revalidation chỉ thu hẹp cửa sổ đua; bảo đảm thật sự đến từ backend (optimistic locking / native transaction, §32) — và với split backend không có shared transaction thì không tồn tại bảo đảm tương đương (xem bảng quyết định). Mọi tuyên bố mạnh hơn đều thuộc deep-dive 04 kèm provider cụ thể.

## Pending Pin, Expiry, Duplicates, and Unknown Outcomes

Kế thừa quy tắc pin của deep-dive 02 (ghim version của plan-generating logic, recompute khi resume, reapproval nếu material), tài liệu này chốt thêm các interleaving lỗi:

- **Pending execution pin.** Execution `AWAITING_APPROVAL` ghim logic version đã tạo nó. Resume sau rollout recompute bằng đúng logic đã ghim rồi revalidate live; thay đổi material thì yêu cầu reapproval theo chính sách đã công bố — không tự commit theo plan cũ, không tự nâng rule mới.
- **Expired/revoked approval.** Approval mang hạn và có thể bị thu hồi (mất role, policy đổi). Hết hạn/thu hồi trước commit → execution quay về `AWAITING_APPROVAL` (chờ duyệt lại) hoặc `REJECTED`/`DENIED` tùy cửa rớt, kèm audit ghi rõ approval nào, version nào, thu hồi khi nào. Không commit trên approval đã chết.
- **Callback authorization ≠ execution transition.** Outsider gọi duyệt một pending execution của người khác, hoặc self-approval vi phạm policy ví dụ, bị `DENIED` ở cửa callback mà execution không đổi trạng thái (vẫn `AWAITING_APPROVAL`); audit ghi callback bị từ chối tách khỏi lịch sử execution.
- **Request idempotency tách khỏi callback key.** Request key (client intent key cho invoke, phạm vi execution) khác callback key (`executionId` + `approvalId`, phạm vi approval decision). Retry invoke cùng request key + cùng tham số trả lại kết quả đã lưu; callback trùng cùng callback key là no-op trả decision đã lưu; cùng key khác tham số thì từ chối misuse.

**[Nguồn]** Stripe lưu status + body của request đầu tiên sau khi endpoint bắt đầu thực thi và trả lại cho retry cùng key (kể cả `500`); validation lỗi hoặc xung đột với request đang chạy thì không lưu và được retry; reuse key sau khi bị prune sẽ thành request mới.

- [Stripe — Idempotent requests](https://docs.stripe.com/api/idempotent_requests)

- **Unknown commit: tri thức của observer, cần reconciliation an toàn.** Timeout sau commit mà trước response là `UNKNOWN` — đó là trạng thái hiểu biết của caller, không phải trạng thái của execution. Key đơn độc không giải quyết được nếu không có durable ledger/provider lookup: quy trình bắt buộc là tra execution record bằng request key, nếu vẫn unknown thì lookup provider (durable ledger hoặc backend) rồi mới quyết định retry/compensate — cấm retry mù cả Action (§33) và cấm mặc định `FAILED`.
- **Unknown commit vs effect delivery.** Commit state (`COMMITTED`) và giao effect (notification/event/ERP) có trạng thái riêng: effect lỗi sau commit thì execution vẫn `COMMITTED` kèm effect `PENDING_RETRY`/`FAILED`, xử lý bằng retry có key hoặc compensation — không "un-commit" nghiệp vụ.
- **Auditable outcomes.** Mỗi đường đi ghi đủ để trả lời "ai, làm gì, bằng rule nào, trên dữ liệu nào": `action`, `actionVersion`, `ontologyVersion`, `principal` (requester + approver + delegated child principal), `target`, `normalized_amount` + currencies + `quote_version`, policy decision, callback decisions bị từ chối, reconciliation lookups, `result` và `changes.before/after` (§40). Intermediate value nhạy cảm tuân thủ access/retention riêng của audit.

## Decision Table: Execution Shapes and Atomicity

**[Nguồn]** §29 chuẩn hóa lifecycle contract thay vì bắt buộc một durable workflow engine; §32 liệt kê strategies theo backend (native transaction, optimistic locking, outbox, idempotency/retry, saga, durable provider) và yêu cầu từ chối execution khi provider không đáp ứng guarantee. Durable execution giữ progress qua replay/event history và phân biệt transient/permanent/negative outcome.

- [Temporal — Durable Execution](https://docs.temporal.io/durable-execution)
- [Palantir — Action types submission criteria](https://www.palantir.com/docs/foundry/action-types/submission-criteria/)

| Hình thức | Khi dùng cho `ApprovePurchaseOrder` | Cam kết quan sát được | Cái giá |
| --- | --- | --- | --- |
| Synchronous command | Đơn dưới ngưỡng, một backend, không approval | `COMMITTED`/`REJECTED`/`DENIED` ngay trong một transaction | Không chịu được chờ duyệt hay lỗi giữa chừng — timeout là `UNKNOWN` (tri thức observer), giải quyết bằng reconciliation qua ledger/provider lookup, không chỉ bằng key |
| Persisted state machine | Có approval (`AWAITING_APPROVAL`), callback/expire/revoke | Mọi transition bền vững + audit được; resume sau crash | Phải quản lý pin version, expiry, duplicate callback một cách tường minh |
| Durable orchestration | `ReserveBudget` ngoài + retry dài ngày + compensation | Progress sống sót worker crash; phân biệt retry được/không | Nặng nhất; chỉ dùng khi state machine + retry có key không đủ — chi tiết provider thuộc 04 |

| Atomicity | Điều kiện | Contract |
| --- | --- | --- |
| Local atomic | `PurchaseOrder` + `Budget` cùng transactional backend | Ủy quyền atomicity cho backend (§32); một commit duy nhất |
| Split backend không shared transaction | `PurchaseOrder@postgres` + `Budget@erp` | Từ chối `Transaction.atomic()` ở deployment binding (deep-dive 01); muốn đi tiếp phải ký contract khác (saga/compensation hoặc outbox cho event) — không downgrade lặng lẽ (§32) |

## Falsifiable Scenarios (Not Executed)

**Chưa thực thi — mọi "kết quả kỳ vọng" là dự đoán cần kiểm chứng, không phải bằng chứng.** Dự kiến đặt tại `fixtures/action-contract/`:

- `amount == 100_000` chuẩn hóa + đủ quyền + đủ budget → `AWAITING_APPROVAL` với `requiredApproval.role = "finance_director"`; `99_999` → `COMMITTED` thẳng.
- Outsider gọi duyệt pending execution của người khác → callback `DENIED`, execution vẫn `AWAITING_APPROVAL`; audit có thêm bản ghi callback bị từ chối, lịch sử execution không thêm transition.
- Requester tự duyệt đơn của mình (policy ví dụ cấm) → callback `DENIED`, execution không đổi; tắt policy ví dụ đi thì cùng callback thành công — chứng minh đây là policy, không phải luật core.
- Thu hồi `purchase_order.approve` của approver giữa `AWAITING_APPROVAL` và commit → commit bị `DENIED`, không commit lặng lẽ.
- Duplicate approval callback cùng callback key + cùng tham số → một decision duy nhất, lần hai là no-op; cùng key khác tham số → từ chối misuse. Request key và callback key không thay thế nhau.
- Timeout sau commit: tra bằng request key thấy `UNKNOWN` → lookup ledger/provider xác định đã `COMMITTED` → không retry; effect notification lỗi → execution `COMMITTED` kèm effect `PENDING_RETRY`.

Điều kiện bác bỏ: nếu bất kỳ scenario nào cho kết quả gộp (ví dụ callback outsider kết thúc luôn execution, key đơn độc được tuyên bố đủ mà không cần lookup, hoặc effect lỗi kéo cả execution về `FAILED` mất `before/after`), thì khẳng định contract tương ứng trong tài liệu này bị bác bỏ và phải sửa.

## Recommendations

**[Đề xuất OaC]** Các quyết định cần chốt trước khi sang deep-dive 04:

1. Mọi approval expression chạm tiền tệ khai báo comparison currency; khi chuyển đổi phải ghi `source_currency` + `target_currency` + `quote_version`. Semantic diff flag mọi thay đổi chạm đơn vị/quy đổi như security-related. Không dựng FX subsystem toàn cục bắt buộc.
2. Tách vai requester/approver ở core (audit cả hai); cấm tự duyệt là policy ví dụ của domain, khai báo tường minh để tắt/mở được.
3. Delegation thu hẹp mặc định cho `calls` liên domain; ambient service identity là lỗi deployment binding.
4. Approval có hạn + thu hồi được; mọi commit kiểm tra hạn/hiệu lực live; callback bị từ chối không chạm execution.
5. Request key và callback key tách nhau, bắt buộc cho invoke và approval callback; `UNKNOWN` chỉ giải quyết bằng safe reconciliation (ledger/provider lookup), không bằng retry mù.
6. Effect có trạng thái riêng khỏi commit; retry/compensation đi theo effect, không đi theo toàn bộ Action.

## Open Questions

**[Câu hỏi mở]**

- Property-level scope (§39) có tách quyền "thấy số tiền" khỏi quyền "duyệt đơn" không, và error response giấu chi tiết tới mức nào?
- Child `ReserveBudget` ở ontology version khác parent trong giai đoạn expand–contract thì pin theo version nào (kế thừa câu hỏi deep-dive 02)?
- Hạn approval bao lâu, ai được gia hạn, và reapproval có cần người khác người duyệt đầu không?
- Effect retention và redelivery bảo đảm tới đâu trước khi giao cho deep-dive 04 (outbox/saga/durable provider)?

## References and Web Sources

- [Stripe — Idempotent requests](https://docs.stripe.com/api/idempotent_requests) — lưu response đầu tiên sau khi thực thi bắt đầu; validation/xung đột không lưu; key tái dùng sau prune thành request mới. Dùng cho: request/callback idempotency, `UNKNOWN` sau timeout.
- [Temporal — Durable Execution](https://docs.temporal.io/durable-execution) — replay qua Event History; phân biệt transient/permanent/negative outcome. Dùng cho: decision table execution shapes.
- [Palantir — Action types submission criteria](https://www.palantir.com/docs/foundry/action-types/submission-criteria/) — conditions pass tại thời điểm submit theo user/parameter/context. Dùng cho: live authorization, revalidate trước commit.
- [Palantir — Action types overview](https://www.palantir.com/docs/foundry/action-types/overview) — action type là tập edits + side effects dùng chung. Dùng cho: parent/child governed composition.

Chương chính thức OaC sử dụng: `06-action-model.md` (§26–34, đặc biệt §29 lifecycle, §30 execution record, §31 mutation plan/revalidation, §32 transaction, §33 effects/failure, §34 composition), `07-governance-and-security-model.md` (§36 principal propagation, §37 permission levels, §38 auth-vs-validation, §40 audit/provenance), cùng deep-dive `01-static-architecture-and-definition-lifecycle.md` (load/bind/invoke, `DENIED`/`REJECTED`/`AWAITING_APPROVAL`, deployment binding) và `02-developer-workflow-and-model-evolution.md` (ngưỡng `>`/`>=`, tiền tệ, pending pin, rollback).
