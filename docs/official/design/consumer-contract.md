# Consumer Contract

*Đặc tả bề mặt người gọi cho OaC: Web app, CLI/automation và AI agent/MCP đi qua **một** cửa engine để đọc và để ghi. Phạm vi: ba nấc của `ApprovePurchaseOrder` — `1.0.0` đồng bộ đơn module, `1.1.0` liên module nguyên tử, `2.0.0` chờ duyệt + effect. Mọi code là minh họa hợp đồng, chưa phải syntax cuối. Phần author thuộc [`developer-contract.md`](./developer-contract.md); quy tắc tiến hóa version thuộc tài liệu versioning.*

## 1. Bề mặt thống nhất và ba thực thể

### 1.1 Một hợp đồng cho ba loại consumer

| Consumer | Cách dùng bề mặt | Điều phải nhớ |
| --- | --- | --- |
| Web app | `query` để render danh sách, `invoke` trên `ObjectRef[T]` do row trả về, `approve` từ màn hình duyệt | Không tự dựng lại ref từ `id` hay gọi backend trực tiếp |
| CLI / automation | `query` có `cursor` + `limit`, `invoke` kèm `request_key` ổn định cho job lặp, `reconcile` sau timeout | Key thuộc `tenant / principal / action`, không phải tên file hay PID |
| AI agent / MCP tool | `query` làm công cụ đọc có kiểu, `invoke` làm tool ghi duy nhất, `approve`/`reject` chỉ khi agent là approver | Tool read-only không được phép thực hiện mutation; agent không tự tạo key mới khi `UNKNOWN` |

Cả ba dùng chung một cửa policy của engine. Read và write là hai biên với luật khác nhau, nhưng **không có đường tắt**: caller không đọc raw rồi tự lọc, không dùng quyền đọc để ghi, không tự quyết định phân quyền trong client.

| Cửa | Kiểm tra live | Trả về khi rớt |
| --- | --- | --- |
| `engine.query(...)` | Read authorization trên từng row, count và cạnh traversal | `UnsupportedSecureQuery` (không lộ row) |
| `engine.invoke(...)` | Invoke permission, `request_key`, `intent_fingerprint`, precondition, guard | `DENIED` / `REJECTED` / `StalePlan` / `UNKNOWN` |
| `engine.approve` / `engine.reject` | Role + permission của approver, `self_approval`, callback key | `DENIED` **cho callback đó**, execution không đổi |
| `engine.reconcile(...)` | Read authorization trên execution record | `UNKNOWN` tiếp tục nếu ledger/provider cũng không có |

### 1.2 Ba thực thể — không gộp

| Thực thể | Ai ghi | Nội dung | Consumer thấy gì | Không được suy ra |
| --- | --- | --- | --- | --- |
| (a) Public Action Contract | Author, publish | `identity`, `version`, typed params, `reads`/`writes`/`calls`, `permission`, `approval`, `effects` | Definition bất biến qua registry | Không đổi theo từng lần gọi; host name không phải identity |
| (b) Caller Attempt Evidence | Engine ghi tại cửa, kể cả attempt bị từ chối | `request_key`, `intent_fingerprint`, principal, timestamp, input canonical, attempt outcome | Trace của lần gọi | **Không phải execution**; không chứa kết quả commit |
| (c) Authoritative Execution Record | **Chỉ engine** ghi sau revalidation | `execution_id`, status, pinned manifest, material intent, committed state, approver, effect summary | `ActionResult.execution` | Không tự sửa, tự duyệt hay tự terminate bằng payload của caller |

Hệ quả bắt buộc: một `DENIED` tại cửa attempt ghi evidence của attempt đó, **không tạo và không kết thúc execution record**. Chỉ engine chuyển record giữa `AWAITING_APPROVAL`, `COMMITTED`, `REJECTED`, `FAILED`.

Các tên camelCase trong `framework-design-v0.1.md` (`asRef()`, `requestKey`, `intentFingerprint`) là cùng một khái niệm; bề mặt dưới đây dùng snake_case để tách rõ `request_key` (invoke) khỏi `callback_key` (duyệt).

## 2. `query → ObjectRef[T] → invoke`

### 2.1 Chữ ký query và thứ tự áp policy

```python
page = engine.query(
    principal=p,
    from_="PurchaseOrder",             # `from` trong pseudocode cũ
    predicate=(status == "PENDING") & (normalized_amount >= Money(100_000, "USD")),
    order="created_at",
    cursor=None,
    limit=20,
    count_requested=False,
)
```

Thứ tự là hợp đồng, không phải tối ưu:

1. Authorize principal và predicate.
2. Đẩy xuống / đánh giá toàn bộ tập **đã authorize**.
3. Traverse chỉ cạnh `navigable` đã authorize; cạnh `internal` bị từ chối.
4. Sort, paginate bằng `cursor`/`limit`, rồi mới `count` nếu `count_requested=True`.

`count` luôn đếm trên tập đã lọc policy; không có `list_raw`, `count_unfiltered` hay đường duyệt link bỏ qua engine.

### 2.2 Ba nhánh trả lời của query

| Nhánh | Điều kiện | Consumer nhận | Cách thu hẹp / xử lý |
| --- | --- | --- | --- |
| Pushdown trung thực | Provider dịch được predicate đã authorize, kiểm tra tương đương ngữ nghĩa + conformance đạt | Rows, count, cursor đã đúng policy | Giữ predicate trong tập provider hỗ trợ; audit ghi pushdown đã áp |
| Bounded pre-authorized evaluation | Không pushdown được nhưng engine chứng minh được biên row/scope an toàn | Tập pre-authorized được nạp trọn, đánh giá xong **trước** paginate/count | Khai rõ biên; vượt biên thì chuyển nhánh sau |
| `UnsupportedSecureQuery` | Không chứng minh được biên an toàn | Từ chối query; không trả row, không lộ chi tiết nghiệp vụ | Thêm predicate khóa tenant/đơn/trạng thái, bỏ traversal `internal`, giảm `limit`, hoặc bật pushdown đã chứng minh |

Không có nhánh thứ tư: postfilter ngầm trên luồng unbounded là vi phạm hợp đồng.

### 2.3 Từ row sang invoke

```python
ref = page.rows[0].as_ref()            # ObjectRef[PurchaseOrder], mang type + version
attempt = engine.invoke(
    principal=p,
    action="procurement.approve_purchase_order",
    parameters={"order": ref, "reason": "approved after budget check"},
    request_key="tenant-A:p:approve:PO-001:001",
    intent_fingerprint=canonical_hash(
        action="procurement.approve_purchase_order",
        version="2.0.0",
        params={"order": ref, "reason": "approved after budget check"},
    ),
)
```

Quy tắc với khóa và fingerprint:

- `request_key` có phạm vi `tenant / principal / action / key`. Cùng key + cùng intent → trả lại kết quả đã lưu; cùng key + intent khác → `KEY_MISUSE`.
- Phạm vi key ổn định xuyên rollout version để dedup, nhưng fingerprint được **recompute theo manifest đã ghim của execution đó**, không theo "version mới nhất".
- `ref` mang type + version; engine resolve lại dưới policy live ở invoke, không tin version do caller tự khai.
- Phát lại payload chỉ để đọc/tra cứu thì cần read authorization trên execution record. Thực hiện lại mutation cần invoke authorization đầy đủ + key còn retention + revalidate live.

## 3. Envelope kết quả qua ba nấc

### 3.1 Hình dạng chung

```python
@dataclass(frozen=True)
class ActionResult:
    attempt: AttemptOutcome             # có cả khi attempt bị từ chối
    execution: ExecutionRecord | None   # None nếu DENIED trước khi chạm record

@dataclass(frozen=True)
class AttemptOutcome:
    code: Literal["COMMITTED", "AWAITING_APPROVAL", "DENIED", "REJECTED",
                  "StalePlan", "UNKNOWN"]
    detail: str | None                  # reason nghiệp vụ hoặc mã denies cụ thể
    request_key: str
    intent_fingerprint: str
    attempted_at: datetime

@dataclass(frozen=True)
class ExecutionRecord:
    execution_id: str
    status: Literal["AWAITING_APPROVAL", "COMMITTED", "REJECTED", "FAILED"]
    action: str
    pinned: PinnedManifest
    requester: Principal
    approver: Principal | None
    result: CommittedState | None
    effects: tuple[EffectStatus, ...]
```

`UNKNOWN` là trạng thái **hiểu biết của caller**, không phải status của execution; vì vậy nó nằm ở `AttemptOutcome`, không nằm ở `ExecutionRecord.status`.

### 3.2 `COMMITTED` — trường có sẵn

| Trường | Nghĩa | Consumer dùng để |
| --- | --- | --- |
| `execution_id` | Định danh execution bền | Tra cứu, audit, đối chiếu callback |
| `action`, `pinned.action_version`, `pinned.ontology_version` | Definition đã chạy, pin theo manifest | Hiện đúng version đã commit, không đoán theo version hiện tại |
| `pinned.handler_digest` | Byte đã chạy | Đối chiếu audit/replay |
| `pinned.child_revisions` | Ví dụ `finance.reserve_budget@1.0.0#<digest>` | Biết child nào đã góp phần commit |
| `result.committed_state` | Tóm tắt state đã ghi: target `ObjectRef`, field đổi, `before`/`after` | Hiện kết quả mà không đọc handler |
| `deduplicated` | `True` nếu đây là replay của key đã commit | Phân biệt lần đầu và lần trả lại |
| `requester`, `approver` | Hai authority, audit cả hai | Hiện ai yêu cầu / ai duyệt |
| `effects` | Tóm tắt giao effect (`PENDING`/`PENDING_RETRY`/`DELIVERED`/`FAILED`) | Hiện trạng thái thông báo tách khỏi commit |
| `completed_at` | Thời điểm commit | Sắp xếp, đối soát |

Nấc 1 và 2 trả cùng shape này với `approver=None`, `effects=()` và không có child approval; Nấc 3 bổ sung approver và effect. Consumer không cần nhánh riêng theo version để đọc kết quả.

### 3.3 `AWAITING_APPROVAL` — trường có sẵn

| Trường | Nghĩa | Consumer dùng để |
| --- | --- | --- |
| `execution_id` | Execution đã tồn tại, đang chờ | Gắn vào màn hình duyệt |
| `pinned`, `pinned.child_revisions` | Manifest đã ghim | Báo cho approver biết đang duyệt đúng logic nào |
| `required_approval.approval_id`, `.role`, `.scope` | Callback key, vai trò và phạm vi được duyệt | Chọn đúng approver; không gọi nhầm principal |
| `required_approval.expires_at` | Hạn của approval | Nhắc hạn, không commit trên approval hết hạn |
| `required_approval.self_approval` | Policy cấm/cho tự duyệt của domain | Không gợi ý requester tự duyệt khi `False` |
| `material_intent` | `normalized_amount` + `source_currency` + `target_currency` + `quote_version` + `expectedVersion` + phạm vi child | Hiện đúng nội dung sẽ commit; so sánh khi world đổi |
| `callback_requirements` | `callback_key`, `expected_intent_fingerprint`, `decision`, `reason` | Điền vào `approve`/`reject` mà không tự dựng payload |
| `status = AWAITING_APPROVAL` | Không commit, **không giữ transaction/session/lock** | Dừng luồng ghi; worker chết hay deploy mới không mất execution |

Đây là **trạng thái nghiệp vụ hợp lệ, không phải lỗi**: cửa authorize và precondition đã pass, engine chỉ còn thiếu authority của approver. Retry `invoke` cùng key trong lúc chờ chỉ trả lại chính execution này — không tạo execution mới và không đẩy nhanh duyệt.

### 3.4 `DENIED` tại cửa attempt

| Nguyên nhân | Pha | Tác động | Consumer làm gì |
| --- | --- | --- | --- |
| Thiếu `purchase_order.approve` của requester | Invoke | Không handler, không record; audit attempt | Xin quyền rồi gửi lại, không đọc code handler để tự sửa |
| `KEY_MISUSE`: key sai scope tenant/principal/action, hoặc `intent_fingerprint` lệch | Invoke | Không record | Tính lại canonical intent; đổi key nếu intent đổi; không tái dùng key cũ với payload khác |
| Callback từ outsider, self-approval bị cấm, hoặc approver mất role/permission | Callback | Execution **vẫn `AWAITING_APPROVAL`** | Gọi đúng approver; audit chỉ ghi callback bị từ chối |
| Dùng quyền read-only để replay mutation | Invoke | Không ghi gì | Dùng invoke authorization đầy đủ; quyền đọc chỉ để xem attempt evidence |

`DENIED` trả lời câu "ai được phép", `REJECTED` trả lời "điều kiện nghiệp vụ có xong". Gộp hai mã này làm consumer không biết phải xin quyền hay sửa dữ liệu; error response cũng không được lộ chi tiết nghiệp vụ vượt quá quyền được thấy.

### 3.5 `REJECTED`, `StalePlan`, `UNKNOWN`

| Mã | Pha phát hiện | Tác động lên execution | Consumer làm gì |
| --- | --- | --- | --- |
| `REJECTED` | `ctx.require` ở invoke, hoặc guard business recheck trước commit — ví dụ đơn đã `CANCELLED`, budget không đủ | Terminal `REJECTED`, mang `reason` | Đọc `reason`, sửa dữ liệu nghiệp vụ, submit với key mới; không retry cùng key để chờ kết quả khác |
| `StalePlan` | Pre-commit revalidation: `expectedVersion` lệch hoặc guard `rowcount != 1` | Plan cũ bị từ chối, không ghi đè; execution không commit | `query` lại version/snapshot mới, recompute `intent_fingerprint`, rồi gửi lại; **cấm retry mù payload cũ**. Giữ key nếu material intent không đổi, đổi key nếu intent đổi; xin reapproval nếu material đổi |
| `UNKNOWN` | Timeout/mất phản hồi sau commit — tri thức của caller, phát hiện khi reconcile | Chưa biết; mặc định **không** coi là `FAILED` | `engine.reconcile(principal, action, request_key)` hoặc theo `execution_id`; nếu vẫn unknown thì lookup ledger/provider; chỉ retry invoke khi xác nhận chưa commit; **không sinh key mới** |

## 4. Callback `approve` / `reject`, re-approval và quan sát `Effect`

### 4.1 Chữ ký callback

```python
decision = engine.approve(
    principal=approver,
    execution_id="EX-2f9c",
    callback_key="EX-2f9c:AP-7b10",     # executionId + approvalId, KHÔNG phải request_key
    expected_intent_fingerprint="9c1a...",
    decision="APPROVE",                  # engine.reject(...) dùng "REJECT"
    reason="budget confirmed",
)
```

Approver cần role `finance_director` **và** permission còn hiệu lực tại thời điểm callback (live check), cộng với policy `self_approval` của domain. `callback_key` thuộc approval decision, tách khỏi `request_key` của invoke; `expected_intent_fingerprint` gắn decision vào đúng material intent đã hiện cho approver.

### 4.2 Hành vi callback và re-approval

| Tình huống | Kết quả callback | Execution | Consumer làm gì |
| --- | --- | --- | --- |
| Approver hợp lệ, material không đổi, guard khớp | `COMMITTED` | `COMMITTED` | Hiện kết quả; đọc `effects` |
| Outsider / tự duyệt bị cấm / mất quyền | `DENIED` | Vẫn `AWAITING_APPROVAL` | Đổi đúng approver; không coi execution là bị từ chối |
| Duplicate cùng `callback_key` + cùng fingerprint/decision | Idempotent replay của decision đã lưu | Không thêm transition | Coi là thành công; không gửi callback khác |
| Cùng `callback_key` nhưng tham số khác | `KEY_MISUSE` (`DENIED`) | Không đổi | Dùng đúng payload đã ghim, hoặc callback key mới |
| Approval hết hạn / bị thu hồi trước commit | Quay lại chờ duyệt | `AWAITING_APPROVAL` | Xin approval mới; audit giữ approval cũ và lý do |
| Material đổi trước commit (số tiền, currency/quote, version object, phạm vi child) | `AWAITING_APPROVAL` với intent mới, hoặc `StalePlan` / `REJECTED` tùy cửa rớt | Không commit trên intent cũ | `query` lại, recompute, xin duyệt lại; không dùng fingerprint cũ |
| Requester/approver mất quyền lúc resume | `DENIED` cho attempt resume | Không commit | Cấp quyền lại rồi callback mới |

Engine mở UoW **mới** khi resume, chạy lại handler trên manifest đã ghim và revalidate live. Consumer không được giả định plan cũ còn hiệu lực hay tự gửi lại mutation plan.

### 4.3 Quan sát `Effect` sau commit

Trạng thái effect là trường riêng trong `ExecutionRecord.effects`; `execution.status` vẫn là `COMMITTED` trong mọi dòng dưới đây.

| Trạng thái | Ý nghĩa | Consumer làm gì |
| --- | --- | --- |
| `PENDING` | Outbox row đã commit cùng state, relay chưa ack | Chờ; không gọi lại action |
| `PENDING_RETRY` | Relay lỗi tạm thời, còn retry có dedup key | Đọc effect, retry effect theo key bền; giữ execution |
| `DELIVERED` | Đã giao, duplicate được chặn ở phía nhận | Đóng thông báo |
| `FAILED` | Hết retention / không retry được | Compensation hoặc can thiệp tay theo effect; **không "un-commit"** action |

Gọi lại `invoke` chỉ để "gửi lại thông báo" hay đánh dấu execution `FAILED` vì effect lỗi đều sai hợp đồng: nó xóa ranh giới giữa cam kết nghiệp vụ và giao thông báo.

## 5. Ma trận hành động consumer

Đây là bảng tra cứu duy nhất cho caller; không cần đọc thân handler hay tự viết lại luật phân quyền.

| Tín hiệu | Pha phát hiện | Tác động execution | Retry cùng key? | Hành động bắt buộc |
| --- | --- | --- | --- | --- |
| `COMMITTED` | Revalidate + commit | Terminal `COMMITTED` | Có — replay trả result đã lưu, không mutate thêm | Hiện kết quả; đọc `deduplicated` và `effects`; không chạy lại handler |
| `COMMITTED` + `deduplicated=True` | Attempt gate, key đã dùng | Không đổi, trỏ execution cũ | Có — chính là replay an toàn | Dùng result đã lưu; không tạo execution hay đổi payload |
| `AWAITING_APPROVAL` | Invoke sau `approval.when=True` | `AWAITING_APPROVAL`, không giữ transaction | Có — cùng key trả lại cùng execution; poll không tạo key mới | Hiện `requiredApproval` + `material_intent`; chỉ approver gọi `approve`/`reject`; dừng luồng ghi |
| `DENIED (UNAUTHORIZED)` | Attempt gate (invoke hoặc callback) | Không tạo/kết thúc record; audit attempt | Có sau khi được cấp quyền (chưa có record), nhưng không tự lặp | Xin invoke permission đúng, hoặc role + permission live cho approver |
| `DENIED (KEY_MISUSE)` | Attempt gate: key/fingerprint lệch | Không đổi record | Không — cùng key sai vẫn rớt | Recompute canonical intent, đúng scope `tenant/principal/action`; đổi key nếu intent đổi |
| `REJECTED` | `ctx.require` hoặc recheck trước commit | Terminal `REJECTED`, có `reason` | Không — key cũ trả rejection đã lưu | Sửa nghiệp vụ (đơn/budget), submit key mới |
| `StalePlan` | Pre-commit revalidation, guard lệch | Plan cũ bị từ chối, không commit | Không với payload cũ — re-read/recompute; giữ key nếu intent không đổi, đổi key nếu có | `query` lại, tính lại fingerprint + `expectedVersion`, xin reapproval nếu material đổi |
| `NoSharedTransaction` | Deployment binding, trước runtime | Không có execution nào | Không | Báo lỗi cấu hình; đổi provider có enlisted session chung hoặc ký contract saga/outbox; consumer không tự retry |
| `UnsupportedSecureQuery` | Query plan | Không đọc row, không invoke | Không áp dụng cho invoke | Thu hẹp predicate/scope, bỏ traversal `internal`, bật pushdown đã chứng minh rồi query lại |
| `UNKNOWN` | Caller reconciliation sau timeout | Chưa biết; không mặc định `FAILED` | Có cho `reconcile` (cùng key hoặc `execution_id`); cấm sinh key mới | `engine.reconcile(principal, action, request_key)`; nếu cần thì lookup ledger/provider; chỉ retry khi xác nhận chưa commit |
| `FAILED` | Handler/guard lỗi không phục hồi trước commit | Terminal `FAILED`, không effect | Không | Đọc `reason`; escalate lỗi hạ tầng; submit mới sau sửa, không tự đổi thành `COMMITTED` |
| `COMMITTED` + Effect `PENDING_RETRY` | Sau commit, relay lỗi tạm thời | Vẫn `COMMITTED` | Không re-invoke action | Retry effect có dedup key; giữ execution |
| `COMMITTED` + Effect `FAILED` | Sau commit, hết retention | Vẫn `COMMITTED` | Không re-invoke action | Compensation hoặc can thiệp tay theo effect; không đánh dấu action chưa commit |

Ba nhầm lẫn bị bảng này cấm: gộp `DENIED` với `REJECTED`, coi `UNKNOWN` là `FAILED`, và kéo effect lỗi vào `execution.status`.

## 6. Ranh giới và liên kết

- Không nằm ở đây: cách author khai báo `approval`/`effects`, nội dung `HandlerCtx`, lỗi Load/Link/binding của author, và bảng SemVer cho `1.0 → 1.1 → 2.0`.
- Không thêm primitive mới: `query`, `invoke`, `approve`, `reject`, `reconcile` chỉ là cửa của engine lên meta-model v0.1 đã chốt.

- [Developer Contract](./developer-contract.md) — author khai báo gì, `HandlerCtx`, scoped UoW và ma trận lỗi tĩnh.
- [Framework Design v0.1](./framework-design-v0.1.md) — meta-model, pin manifest, idempotency và ma trận lỗi nền.
- [Action Contract and Business Workflow](../deep-dives/03-action-contract-and-business-workflow.md) — authority, material intent, callback bị từ chối và `UNKNOWN`.
- [Engine Boundary and Adapter Capabilities](../deep-dives/04-engine-boundary-and-adapter-capabilities.md) — enlistment, outbox/relay và hiệu lực của `NoSharedTransaction`.
