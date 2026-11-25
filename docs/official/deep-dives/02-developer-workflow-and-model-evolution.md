# Developer Workflow and Model Evolution

*Tài liệu deep-dive 02 — Developer workflow & model evolution. Phạm vi: chương chính thức 10 (§50–57), dùng lại 06 (§26–34), 07 (§40), 08 (§43–45). Ví dụ xuyên suốt: `ApprovePurchaseOrder` dùng chung giữa Procurement và Finance, tiếp nối deep-dive 01.*

*Quy ước đọc: mỗi mục ghi rõ nguồn của khẳng định — **[Nguồn]** = bằng chứng đã kiểm chứng từ tài liệu sơ cấp; **[Đề xuất OaC]** = quyết định thiết kế do tài liệu này đề xuất, chưa chốt; **[Câu hỏi mở]** = việc cần phase sau hoặc thí nghiệm trả lời. Mọi đoạn code Python trong tài liệu này là minh họa giả thuyết cho declaration, không phải syntax đã chốt và không phải implementation.*

## Executive Summary and Recommended Approach

**[Đề xuất OaC]** Khuyến nghị chính của tài liệu này:

1. Mọi thay đổi governance (ngưỡng duyệt, tiền tệ, permission, approval role) phải đi qua cùng pipeline: **author → model check (load/bind) → impact analysis (semantic diff + dependency graph) → review/tests (PR + test categories) → rollout (publish version, xử lý pending executions) → rollback có kế hoạch**.
2. Phân biệt rạch ròi hai loại tác động: **detected** (cạnh dependency đã đăng ký trong declarations: `calls`, `exports`, permission refs, generated artifact schema) và **unobservable** (handler code tùy ý, consumer ngoài không khai báo). Semantic diff và impact analysis chỉ bảo đảm trên detected graph. Việc sinh SDK/tool hay query qua runtime **không** liệt kê được downstream consumers/dashboards đã cài đặt hay queue impact — những thứ đó cần registration/telemetry riêng, nếu không vẫn là unobservable (observed ≠ complete).
3. Execution record **ghim (pin) cả `actionVersion` và `ontologyVersion`** tại thời điểm khởi tạo (§30); authorization decision được **đánh giá live tại invoke/commit** theo principal và world state hiện tại, và cả hai đều được ghi vào audit (§40).
4. Bắt đầu bằng **SemVer cho ontology version + expand–contract cho rollout**; chỉ sinh SDK/API artifact có version khi consumer cần pin độc lập triển khai (học từ Stripe và GitLab, xem mục Alternatives).

Giới hạn của khuyến nghị này được phân tích ở mục Counterexample (gồm phản ví dụ live authorization phá vỡ reproducibility, và host rename gãy SDK dù identity ổn định), và các giả định bàn giao cho phase 3 ở mục Handoff.

## Tracked Change: Threshold, Equality, and Currency

### Điểm xuất phát (baseline)

**[Nguồn]** Theo §28 và §50–53, developer viết Action bằng ngôn ngữ quen thuộc, framework trích metadata và kiểm tra static model trước deploy. Theo §27–28, approval requirement là một phần của contract, không phải chi tiết implementation giấu trong thân handler.

**[Đề xuất OaC]** Baseline của ví dụ xuyên suốt (kế thừa deep-dive 01):

```python
# procurement/actions.py — baseline v1.2.0
class ApprovePurchaseOrder(Action):
    """Duyệt đơn mua hàng, cần Finance đồng duyệt khi giá trị lớn."""

    identity = "procurement.approve_purchase_order"
    version = "1.2.0"

    order: ObjectRef[PurchaseOrder]
    reason: str

    reads = [PurchaseOrder, Budget, Supplier]
    writes = [PurchaseOrder]
    calls = ["finance.reserve_budget"]

    permission = "purchase_order.approve"
    approval = Approval.conditional(
        when=Param("order").amount > 100_000,
        role="finance_director",
    )
```

Ba thay đổi được theo dõi trong mục này đều giữ nguyên **handler signature** (`order`, `reason`) và giữ nguyên `reads`/`writes`/`calls`:

- Thay đổi A — toán tử ngưỡng: `>` thành `>=`.
- Thay đổi B — giá trị ngưỡng: `100_000` thành `50_000` (hoặc ngược lại).
- Thay đổi C — tiền tệ: `amount: Money` diễn giải theo `USD` thành chuẩn hóa về `VND` (hoặc thêm điều kiện `currency == "USD"`).

### Thay đổi A: strict `>` thành `>=` (equal threshold)

```python
# procurement/actions.py — candidate v2.0.0 (MAJOR — xem phân loại bên dưới)
class ApprovePurchaseOrder(Action):
    """Ngưỡng bao gồm cả giá trị biên."""

    identity = "procurement.approve_purchase_order"
    version = "2.0.0"

    order: ObjectRef[PurchaseOrder]
    reason: str

    reads = [PurchaseOrder, Budget, Supplier]
    writes = [PurchaseOrder]
    calls = ["finance.reserve_budget"]

    permission = "purchase_order.approve"
    approval = Approval.conditional(
        when=Param("order").amount >= 100_000,
        role="finance_director",
    )
```

**[Đề xuất OaC]** Đây là thay đổi **behavior tại điểm biên duy nhất** (`amount == 100_000`): trước đây đi thẳng `COMMITTED` (nếu đủ quyền và budget), sau thay đổi chuyển thành `AWAITING_APPROVAL` với `requiredApproval.role = "finance_director"`. Handler signature không đổi nên mọi check ở pha load/bind kiểu cũ đều pass — chỉ **semantic diff ở mức approval expression** mới bắt được.

**[Nguồn]** Phân loại version học từ đặc tả SemVer: MAJOR cho incompatible API changes, MINOR cho backward-compatible functionality, PATCH cho backward-compatible bug fixes.

- [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)

**[Đề xuất OaC]** Dù signature không đổi, thay đổi A là **incompatible public-contract change khi approval behavior thuộc contract**: luồng tại `amount == 100_000` đổi từ `COMMITTED` thành `AWAITING_APPROVAL`, nên theo SemVer (MAJOR khi có backward incompatible change) phải bump MAJOR (`1.2.0` → `2.0.0`) và gắn security-related flag trong semantic diff (theo mẫu §55). Blast radius quan sát được (ít hay nhiều đơn chạm điểm biên) không hạ mức này xuống MINOR/PATCH. Ngoại lệ duy nhất: contract đã tuyên bố tường minh approval rules là variable/không bảo đảm (ví dụ tài liệu contract ghi "ngưỡng duyệt có thể điều chỉnh mà không báo trước") — khi đó mới được dùng MINOR (`1.3.0`) và phải trích dẫn điều khoản đó trong PR. Không có ngoại lệ PATCH cho thay đổi governance behavior.

### Thay đổi B: giá trị ngưỡng

**[Đề xuất OaC]** Đổi `100_000` thành `50_000` mở rộng tập đơn phải duyệt (mọi đơn trong `[50_000, 100_000)` đổi luồng); đổi ngược lại thu hẹp tập đó. Cả hai đều không đổi signature, không đổi `reads`/`writes`, nhưng đổi **tải duyệt (approval load), thời gian chu trình, và rủi ro tuân thủ**. Semantic diff phải render thay đổi này như một dòng governance riêng (giống mẫu §55 hiển thị `Permission` và `Approval requirement`), không được gộp vào "sửa bug nhỏ".

### Thay đổi C: tiền tệ

**[Đề xuất OaC]** Thay đổi tiền tệ nguy hiểm hơn cả hai thay đổi trên vì nó đổi **ý nghĩa của con số mà không đổi con số**. Ví dụ: `100_000 VND` so với `100_000 USD` chênh lệch hàng chục nghìn lần; một rule so sánh `amount >= 100_000` mà không chuẩn hóa `currency` sẽ hoặc duyệt thừa hoặc chặn thiếu toàn bộ một dải đơn. Đề xuất: mọi ngưỡng tiền tệ trong declaration phải mang đơn vị tường minh (`Money(amount, currency)` hoặc `currency` field riêng), và semantic diff phải flag mọi thay đổi chạm tới `currency` như security-related change ngay cả khi số ngưỡng giữ nguyên.

## Stable Identity versus Host Rename, with SDK Caveat

### Identity ổn định, host rename tự do (có điều kiện)

**[Nguồn]** Deep-dive 01 đã thiết lập: identity (`procurement.approve_purchase_order`) ổn định, có namespace, là thứ execution record (§30), audit và cross-domain reference bám vào; host name (tên class Python `ApprovePurchaseOrder`, đường dẫn module `procurement/actions.py`) phục vụ ergonomics và refactor được miễn identity không đổi. Tiền lệ: Palantir object type ID đổi là gãy application; K8s Name tái dùng được còn UID định danh instance.

- [Palantir — Create an object type](https://www.palantir.com/docs/foundry/object-link-types/create-object-type)
- [Kubernetes — Object Names and IDs](https://kubernetes.io/docs/concepts/overview/working-with-objects/names/)

**[Đề xuất OaC]** Áp dụng cho ví dụ này: đổi tên class `ApprovePurchaseOrder` thành `ApprovePO`, hoặc tách module `procurement/actions.py` thành `procurement/approvals.py`, **không phải breaking change ở mức ontology** miễn `identity` và contract giữ nguyên. Load/bind checks phải bám vào identity, không bám vào qualified name của Python.

### SDK caveat: host rename vẫn có thể gãy consumer

**[Nguồn]** Stripe gắn API version tại thời điểm phát hành SDK: các SDK kiểu `stripe-java`, `stripe-go`, `stripe-dotnet` (strongly typed) cố định API version theo bản SDK; muốn đổi version phải nâng/hạ SDK. Webhook endpoint cũng mang version riêng, không tự kế thừa version của server-side SDK.

- [Stripe — Versioning](https://docs.stripe.com/api/versioning)
- [Stripe — API upgrades](https://docs.stripe.com/upgrades)

**[Đề xuất OaC, caveat]** Nếu generator sinh tên hàm SDK, đường import, hoặc MCP tool name từ **host name / display name** thay vì từ **identity**, thì host rename (vốn an toàn ở mức ontology) trở thành breaking change ở mức SDK/consumer contract. Hệ quả thiết kế:

- Mọi consumer-facing name sinh tự động **phải** suy từ `identity` (ví dụ `procurement_approve_purchase_order`), không suy từ tên class Python.
- Nếu đã lỡ sinh từ host name, host rename phải đi kèm **alias/deprecation** một version (giữ cả tên cũ và mới trong SDK), hoặc bump MAJOR của SDK package — tương tự cách Stripe yêu cầu đối chiếu breaking changes của target version trước khi nâng cấp.
- Kiểm tra "host rename an toàn" thuộc về **consumer compatibility tests** (§57), không thuộc về load/bind checks của ontology.

## Concrete Workflow: Author to Rollback

**[Nguồn]** §53 định nghĩa lifecycle Define → Inspect → Validate → Test → Review → Publish → Integrate → Observe. §55 định nghĩa semantic diff phục vụ review, impact analysis, compatibility và migration. §57 liệt kê các test categories từ definition tests tới consumer compatibility và migration tests.

### Từng bước với ví dụ ngưỡng `>` thành `>=`

**Bước 1 — Author.** Developer sửa `when` từ `>` thành `>=`, bump MAJOR `version` lên `2.0.0` (vì approval behavior thuộc contract — xem phân loại ở trên), ghi changelog entry (học từ Keep a Changelog: mỗi version ghi notable changes, không dump git log).

- [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)

**Bước 2 — Model check (máy kiểm tra, không cần reviewer).** Chạy lại ba pha của deep-dive 01:

- Load: không trùng identity, parse được expression `>=`.
- Linking: `Param("order").amount` vẫn resolve ra field của `PurchaseOrder`; `finance.reserve_budget` vẫn exported.
- Deployment binding: yêu cầu transaction/atomicity không đổi nên không cần re-bind provider.

Thay đổi ngưỡng **phải pass cả ba pha** — đây là điểm mấu chốt: model check xanh không có nghĩa thay đổi vô hại, mà chỉ có nghĩa thay đổi hợp lệ về mặt cấu trúc.

**Bước 3 — Impact analysis (semantic diff + dependency graph).** Dựa trên mẫu §55, diff kỳ vọng render (minh họa, chưa phải output tool đã có):

```text
Ontology: procurement
Version: 1.2.0 -> 2.0.0 (MAJOR — approval behavior đổi tại điểm biên)
~ ApprovePurchaseOrder (procurement.approve_purchase_order)
  Approval.when: Param("order").amount > 100_000 -> >= 100_000
  Affected boundary: amount == 100_000 (COMMITTED -> AWAITING_APPROVAL)
Potential breaking changes: 1
Security-related changes: 1
```

Impact analysis liệt kê trên detected graph: (a) cạnh `calls`/`exports` nào reference identity này; (b) generated artifact schema nào đổi (SDK/tool signature sinh từ identity). Riêng downstream consumers đã cài đặt (ai đang dùng SDK bản nào), dashboards ngoài, và queue impact (approval queue tăng bao nhiêu) **không** suy ra được từ việc sinh artifact hay query qua runtime — chúng cần registration/telemetry riêng; nếu không có, phải ghi vào PR là "chưa quan sát được" và xử lý bằng migration note/deprecation window, không được tuyên bố "không ảnh hưởng".

**Bước 4 — Review/tests (PR).** PR mang theo semantic diff (không chỉ git diff, theo §55), cộng ít nhất:

- Definition tests: schema/approval expression parse đúng.
- Business logic tests: fixture tại `amount == 100_000` (xem mục Fixture).
- Authorization tests: principal có/không có `purchase_order.approve` tại điểm biên.
- Consumer compatibility tests: SDK/tool schema sinh ra có đổi không (đặc biệt sau host rename).
- Migration tests: dữ liệu/execution cũ đọc dưới contract mới ra sao.

**Bước 5 — Rollout.** Publish ontology version mới (`ontologyVersion` bump, `actionVersion=2.0.0`). Execution mới ghim `2.0.0`. Áp dụng expand–contract khi cần giai đoạn cùng tồn tại (xem nguồn GitLab/Fowler ở mục Alternatives).

**Bước 6 — Pending executions (quy tắc duy nhất, áp dụng cả rollout lẫn rollback).** Execution ghim **version của plan-generating logic** (rule sinh plan), không ghim plan cũ đã stale. Khi một execution `AWAITING_APPROVAL` resume (worker khởi động lại, retry, hoặc rollout xen giữa):

- Recompute plan bằng đúng logic version đã ghim, rồi revalidate live authorization và world state (principal còn quyền không, budget còn đủ không, `expectedVersion` còn khớp không).
- Nếu thay đổi giữa các versions là material đối với execution đó (ví dụ kết quả approval khác đi: `COMMITTED` thành `AWAITING_APPROVAL` hoặc ngược lại), execution **không** tự commit theo plan cũ — nó chuyển sang yêu cầu reapproval/re-submit theo chính sách đã công bố trước rollout.
- Ví dụ: pending `120_000` tạo dưới `1.2.0` resume sau rollout — recompute bằng logic `1.2.0`, vẫn cần duyệt, giữ nguyên người duyệt đã chỉ định; không tự "nâng" lên logic `2.0.0`. Execution mới `amount == 100_000` sau rollout ghim `2.0.0` và đi vào `AWAITING_APPROVAL`.

**Bước 7 — Rollback.** Vì mỗi version đã phát hành là bất biến (học từ SemVer: contents of a version MUST NOT be modified), rollback = publish/fallback về version trước (`1.2.0`), không sửa `2.0.0` tại chỗ. Checklist: (a) execution mới ghim lại `1.2.0`; (b) pending tạo dưới `2.0.0` áp dụng đúng quy tắc bước 6 (recompute bằng logic `2.0.0` đã ghim, revalidate live, reapproval nếu material) — rollback không hồi tố các execution đã `COMMITTED` và không tự hạ cấp approval của pending mới; (c) audit giữ nguyên mọi version để truy vết (xem mục Audit).

## Detected Dependencies versus Unobservable External Consumers

### Cái gì máy thấy được (detected)

**[Nguồn]** §55 nêu rõ: chỉ metadata và dependencies đã đăng ký mới phân tích được đáng tin cậy. Deep-dive 01 biến nguyên tắc này thành quy tắc kiểm tra: static layer chỉ tin những gì đã khai báo (`reads`, `writes`, `calls`, tham số có kiểu, `exports`).

**[Đề xuất OaC]** Với ví dụ ngưỡng, những thứ sau là detected và semantic diff phải bao phủ — hiểu đúng phạm vi: thấy được *cạnh khai báo và schema đã sinh*, không phải *downstream consumers đang chạy ngoài kia*:

- Mọi Action khai báo `calls = ["procurement.approve_purchase_order"]`.
- Mọi policy/permission reference `purchase_order.approve` đã đăng ký.
- Generated artifact schema đổi hay không (SDK/tool signature sinh từ identity trong cùng lần build) — đây là schema của artifact, không phải danh sách ai đã cài SDK bản nào.

### Cái gì máy không thấy (unobservable)

**[Nguồn]** Cùng §55 (câu chốt): arbitrary executable code hoặc external consumers không khai báo dependency sẽ giới hạn impact analysis. Cuối §54 nêu cùng nguyên tắc: Framework cần kết hợp static validation, runtime validation và automated tests vì không phải mọi business constraint hay Python logic tùy ý đều kiểm chứng statically được.

**[Đề xuất OaC]** Những consumer sau là unobservable đối với semantic diff, và tài liệu review phải gọi tên chúng thay vì giả định "diff xanh là an toàn":

- Downstream consumers đã cài SDK/tool bản cũ (ai đang pin version nào ngoài production): việc `runtime.to_sdk()` sinh được schema mới không cho biết ai đã cài, ai chưa nâng — cần consumer registration hoặc telemetry phiên bản, nếu không vẫn là unobservable.
- Dashboards, báo cáo và automation đọc ngoài contract (raw SQL/BI, webhook forward, RPA/cron hard-code luồng "đơn 100_000 tự duyệt"): đổi `>=` làm chúng sai mà không có cạnh dependency nào để flag.
- Queue impact thực tế (approval queue tăng bao nhiêu đơn/tháng): suy ra được *tập đơn đổi luồng* từ rule, nhưng tải và độ trễ thực tế cần telemetry hàng đợi — không quan sát được từ registry hay số lượng query qua runtime.
- Handler lén chạm dữ liệu không khai báo (undeclared dependency — xem deep-dive 01): đổi ngưỡng có thể đổi tần suất chạm `Budget`/`Supplier` trong handler mà `reads` không phản ánh.
- Con người: SOP vận hành, training slide, và AI agent prompt ghi nhớ ngưỡng cũ.

Hệ quả: impact analysis trong bước 3 chỉ được tuyên bố bao phủ **detected graph**; phần unobservable phải xử lý bằng communication (changelog, migration note, deprecation window), không phải bằng thêm một nút "kiểm tra sâu hơn" không có cơ sở.

## Design Alternatives for Versioning and Pinning

### Alternative A — Pinned execution (khuyến nghị cho contract)

Mỗi execution ghim `actionVersion` + `ontologyVersion` tại lúc tạo (§30: execution record mang cả hai) — cụ thể là ghim **version của plan-generating logic** (rule sinh approval decision, validation, mutation plan), không ghim plan cũ đã stale. Khi resume, execution recompute plan bằng logic version đã ghim rồi revalidate live authorization/world state; nếu thay đổi là material thì yêu cầu reapproval (xem quy tắc bước 6). Audit ghi lại đúng logic version đã dùng (§40).

**[Nguồn]** Stripe là tiền lệ sản phẩm: SDK strongly typed cố định API version theo bản phát hành; webhook endpoint mang version riêng; nâng cấp yêu cầu đối chiếu breaking changes của target version.

- [Stripe — Versioning](https://docs.stripe.com/api/versioning)
- [Stripe — API upgrades](https://docs.stripe.com/upgrades)

Ưu: reproducible, audit truy vết được "ai, làm gì, bằng rule nào"; rollback chỉ là đổi version cho execution mới. Nhược: hai executions cùng action có thể chạy hai rule khác nhau trong giai đoạn chuyển tiếp — phải chấp nhận và giải thích, không được giấu.

### Alternative B — Live-always (mọi thứ luôn theo mới nhất)

Mọi execution (kể cả pending `AWAITING_APPROVAL`) luôn đánh giá theo definition mới nhất. Không cần pin, không cần migration.

**[Nguồn]** OPA là tiền lệ cho mặt live của pattern này: application gửi `input` tới OPA và nhận policy decision tách khỏi application; decision phụ thuộc input tại thời điểm hỏi, có thể phân phối qua bundle và log lại.

- [OPA — Integrating OPA](https://www.openpolicyagent.org/docs/integration)

Ưu: đơn giản về mặt version, không có "hai rule cùng sống". Nhược: phá vỡ reproducibility và audit ("đơn này được duyệt theo rule nào?"), pending execution đổi luồng giữa chừng mà người liên quan không hay; rollback không có ngữ nghĩa rõ vì không có version để quay về. Tài liệu này **bác bỏ live-always cho approval/contract**, nhưng **chấp nhận live cho authorization decision** (xem phân tách dưới).

### Alternative C — Expand–contract / parallel change (khuyến nghị cho rollout)

**[Nguồn]** Fowler định nghĩa parallel change (expand–contract): mở rộng interface để hỗ trợ cả cũ lẫn mới, migrate consumers dần dần, rồi mới contract (xóa cũ); mỗi phase đều release được; migrate phase có thể dài và cần kỷ luật để không kẹt ở trạng thái kép.

- [Martin Fowler — Parallel Change](https://martinfowler.com/bliki/ParallelChange.html)

**[Nguồn]** GitLab áp dụng cùng pattern cho fleet nhiều version cùng sống (web/API/Sidekiq/DB ở version khác nhau trong lúc update; canary chạy version mới trước): expand → migrate → contract phải nằm ở các milestone khác nhau; contract có thể lùi tới major release.

- [GitLab — Backwards compatibility across updates](https://docs.gitlab.com/development/multi_version_compatibility/)

Áp dụng cho ngưỡng: (1) expand — publish `2.0.0` song song `1.2.0`, SDK giữ cả hai tool signature nếu cần; (2) migrate — consumer chuyển sang ghim `2.0.0`, theo dõi approval queue bằng telemetry hàng đợi (không suy từ registry); (3) contract — deprecate rồi gỡ `1.2.0` theo deprecation window. Đổi tiền tệ (thay đổi C) gần như bắt buộc đi đường này vì blast radius lớn.

### Phân tách quyết định: pin cái gì, live cái gì

**[Đề xuất OaC]** Không chọn một cực duy nhất:

- **Pin**: version của plan-generating logic — approval rule, validation, parameter schema — theo `actionVersion`/`ontologyVersion` đã ghim trong execution record; resume thì recompute bằng đúng logic version đó, không dùng plan cũ đã stale. Đây là thứ audit cần tái hiện.
- **Live**: authorization decision (principal còn quyền `purchase_order.approve` không?) và world state (budget còn đủ không? `expectedVersion` còn khớp không?) — đánh giá tại invoke và revalidate trước commit, theo kiểu OPA (input tại thời điểm hỏi) và submission criteria của Palantir (conditions pass tại thời điểm submit — nguồn đã dẫn ở deep-dive 01).

**[Nguồn]** Palantir submission criteria: action chỉ submit khi mọi criteria thỏa mãn tại thời điểm submit, theo current user/parameter/execution context.

- [Palantir — Action types submission criteria](https://www.palantir.com/docs/foundry/action-types/submission-criteria/)

**[Nguồn]** Audit/provenance (§40): audit record mang `executionId`, `action`, `actionVersion`, `principal`, `target`, `result`, `changes.before/after`; provenance bổ sung datasource/model version, input refs, policy decision và execution dependencies.

### Audit: ghi gì cho thay đổi ngưỡng

**[Đề xuất OaC]** Mỗi execution sau thay đổi ngưỡng phải ghi đủ để trả lời "ai, làm gì, bằng rule nào, trên dữ liệu nào":

- `action`, `actionVersion`, `ontologyVersion`, `principal`, `target` (`PurchaseOrder:PO-001`).
- `input` biên (`amount == 100_000`, `currency`), policy decision (`allow` + rule version đã đánh giá).
- `result` (`COMMITTED` / `AWAITING_APPROVAL` / `DENIED` / `REJECTED`) và `changes.before/after`.
- Không ghi nguyên văn mọi intermediate value nhạy cảm vào log — audit/provenance cần policies riêng về access control và retention (§40).

## Decision Drivers

**[Đề xuất OaC]** Khi phân loại version và chọn pinning cho một thay đổi như đổi ngưỡng, cân nhắc theo thứ tự:

1. **Auditability trước tiện lợi.** Nếu thay đổi làm mất khả năng trả lời "rule nào đã chạy" thì phải pin và log, dù live-always code ít hơn.
2. **Contract trước, blast radius sau.** Nếu approval behavior thuộc public contract, `>` → `>=` là MAJOR bất kể blast radius quan sát được lớn hay nhỏ. Blast radius (số consumer, tần suất chạm `== 100_000`) chỉ quyết định mức độ rollout (có cần expand–contract, deprecation window dài bao nhiêu), không hạ MAJOR xuống MINOR.
3. **Semantic, không phải cú pháp — nhưng contract quyết định, không phải cảm nhận.** Ký tự diff không quyết định; điều khoản contract quyết định. Chỉ khi contract đã tuyên bố tường minh approval rules là variable/không bảo đảm thì `>` → `>=` mới được gắn MINOR, và PR phải trích dẫn điều khoản đó. Không có PATCH cho thay đổi governance behavior.
4. **Pending và in-flight luôn có chủ.** Mọi rollout phải trả lời trước: pending executions ghim logic version nào, resume recompute/revalidate ra sao, khi nào reapproval; rollback chạm tới ai — không để mặc định ngầm (xem quy tắc duy nhất ở bước 6).
5. **Unobservable được gọi tên.** Nếu tồn tại dashboard/SOP/RPA ngoài graph, thay đổi ngưỡng phải kèm migration note và deprecation window, không chỉ semantic diff xanh.
6. **SDK sinh từ identity.** Mọi quyết định đặt tên SDK/tool phải bám identity ổn định; nếu không làm được, host rename phải đi đường deprecation như breaking change.

## Counterexample and Limit

**Phản ví dụ 1 — live authorization phá vỡ reproducibility của pinned execution.** Khuyến nghị "execution ghim rule nhưng authorization live" có nghĩa hai executions cùng `actionVersion=2.0.0`, cùng `amount == 100_000`, có thể cho hai kết quả khác nhau nếu quyền `purchase_order.approve` của principal bị thu hồi giữa chừng (một `COMMITTED` trước, một `DENIED` sau). Audit vẫn đúng (mỗi record ghi decision tại thời điểm của nó), nhưng bất kỳ ai kỳ vọng "cùng version là cùng kết quả" sẽ thất vọng. Đây là giới hạn có chủ ý: authorization là thuộc tính của principal tại thời điểm gọi, không phải thuộc tính của definition version — tài liệu này chọn live và chấp nhận không-reproducible ở chiều này, thay vì ghim quyền cũ đã bị thu hồi (rủi ro bảo mật lớn hơn).

**Phản ví dụ 2 — host rename gãy SDK dù identity ổn định.** Đổi `ApprovePurchaseOrder` thành `ApprovePO` giữ nguyên identity nên load/bind và detected graph đều xanh; nhưng SDK đã sinh tên hàm từ tên class (`approvePurchaseOrder(...)`) khiến mọi caller ngoài gãy compile. Khuyến nghị "identity ổn định" **không bao phủ** lớp đặt tên sinh tự động — phải sửa generator (sinh từ identity) hoặc đối xử host rename như breaking change ở mức SDK package. Đây chính là SDK caveat ở trên, và là lý do consumer compatibility tests (§57) là bắt buộc chứ không phải tùy chọn.

**Giới hạn — tiền tệ ngoài tầm của ngưỡng số.** Mọi phân tích `>`/`>=` trong tài liệu này giả định `amount` đã chuẩn hóa một đơn vị. Nếu `Money` mang `currency` mà declaration không bắt buộc chuẩn hóa, semantic diff so sánh số ngưỡng sẽ mù trước thay đổi nguy hiểm nhất (đổi đơn vị). Phase 3 cần quyết định `Money` bắt buộc chuẩn hóa ở đâu (declaration, bind, hay invoke) — ngoài phạm vi tài liệu này.

## Falsifiable Fixture (Not Executed)

**[Đề xuất OaC]** Fixture dưới đây được thiết kế để bác bỏ được các khẳng định trên; **chưa thực thi — mọi "kết quả kỳ vọng" là dự đoán cần kiểm chứng, không phải bằng chứng**.

Dự kiến đặt tại `fixtures/threshold-evolution/` (minh họa cấu trúc, chưa tạo file):

- `v1_2_0/procurement/actions.py` — baseline `when=Param("order").amount > 100_000`, `version = "1.2.0"`.
- `v2_0_0/procurement/actions.py` — candidate `when=Param("order").amount >= 100_000`, `version = "2.0.0"`, signature và `reads`/`writes`/`calls` giữ nguyên.
- `v2_0_0_renamed/procurement/approvals.py` — như `v2_0_0` nhưng class đổi thành `ApprovePO`, module đổi thành `approvals.py`, `identity` giữ nguyên.
- `cases/boundary.json` — các case `amount`: `99_999`, `100_000`, `100_001`, mỗi case kèm `currency` (`USD`, `VND`) và principal có/không có permission.

Kết quả kỳ vọng (nếu fixture được thực thi):

- `v1_2_0` + `amount == 100_000` + đủ quyền + đủ budget → `COMMITTED` (không qua approval).
- `v2_0_0` + `amount == 100_000` + đủ quyền + đủ budget → `AWAITING_APPROVAL` với `requiredApproval.role = "finance_director"`.
- `v2_0_0` + `amount == 99_999` → `COMMITTED` (dưới ngưỡng cả hai versions); `amount == 100_001` → `AWAITING_APPROVAL` (trên ngưỡng cả hai versions) — hai case cận biên chứng minh thay đổi chỉ lật hành vi tại đúng `100_000`.
- Semantic diff `v1_2_0` → `v2_0_0` render đúng một dòng `Approval.when` đổi `>` thành `>=`, gắn cờ `Security-related: 1` và `Potential breaking changes: 1 (MAJOR)`; diff transport schema (signature/tools) trống — chứng minh "signature không đổi nhưng contract đổi".
- Load cả `v2_0_0` và `v2_0_0_renamed` trong hai registry độc lập: cùng một `identity`, bind cùng pass; nhưng consumer compatibility test dùng SDK sinh từ host name **được kỳ vọng fail** sau rename — chứng minh SDK caveat.
- Case `currency = "VND"` với ngưỡng số giữ nguyên được kỳ vọng lộ ra quyết định thiếu: hoặc diff flag cảnh báo đơn vị, hoặc test biên cho thấy luồng sai — chứng minh giới hạn tiền tệ.

Điều kiện bác bỏ: nếu semantic diff không flag được `>` → `>=` (vì expression lưu dưới dạng opaque), hoặc fixture cho thấy `v2_0_0` vẫn `COMMITTED` tại `100_000`, thì khẳng định "static layer bắt được thay đổi ngưỡng" bị bác bỏ và tài liệu này phải sửa (yêu cầu serialize approval expression — xem Handoff giả định 5 của deep-dive 01).

## Handoff Assumptions to Phase 3

Các giả định phase 3 (governance chi tiết, authorization/policy engine, execution bền vững) được phép dựa vào; nếu phase 3 bác bỏ giả định nào, phải quay lại sửa tài liệu này:

1. Approval expression (`Approval.conditional(when=...)`) có thể serialize đầy đủ để semantic diff so sánh được (kế thừa giả định 5 của deep-dive 01); cú pháp `Param("order").amount >= 100_000` vẫn là minh họa.
2. Mọi ngưỡng tiền tệ mang đơn vị tường minh; chưa chốt chuẩn hóa ở declaration, bind hay invoke.
3. Execution ghim version của plan-generating logic (`actionVersion` + `ontologyVersion`); authorization và world-state checks live tại invoke/commit và revalidate trước commit; resume thì recompute bằng logic version đã ghim, reapproval nếu material; audit ghi cả hai.
4. Rollback = quay về version bất biến đã publish, không sửa version tại chỗ; pending executions tuân thủ đúng quy tắc resume/recompute/reapproval ở bước 6 (không có chính sách "giữ plan cũ stale" hay "tự hạ cấp approval" nào khác).
5. SDK/tool names sinh từ `identity`; mọi ngoại lệ (sinh từ host name) được coi là tech debt phải gắn deprecation alias.
6. Impact analysis chỉ tuyên bố bao phủ detected graph; unobservable consumers xử lý bằng changelog/migration note/deprecation window.

## Open Questions

**[Câu hỏi mở]**

- Property-level scope (§39 query-time security) có làm thay đổi cách khai báo ngưỡng trên từng property không, hay ngưỡng vẫn ở mức Action?
- Interface là structural hay behavioral contract (§23) — và điều đó ảnh hưởng gì tới ranh giới "approval behavior có thuộc contract hay không" (câu hỏi quyết định MAJOR hay ngoại lệ MINOR ở trên)?
- Version của thân handler quản lý thế nào khi IR diff không thấy được (giới hạn đã nêu ở deep-dive 01 §8)?
- Principal propagation và shared transaction cho `calls` liên domain (§34) biểu diễn ra sao khi parent và child ở hai ontology versions khác nhau trong giai đoạn expand–contract?

## References and Web Sources

Nguồn sơ cấp đã đọc và trích dẫn (mọi khẳng định **[Nguồn]** đều bám vào các mục cụ thể dưới đây):

- [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html) — MAJOR/MINOR/PATCH, public API, released version MUST NOT be modified. Dùng cho: phân loại thay đổi ngưỡng; rollback bất biến.
- [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) — notable changes per version, không dump git log. Dùng cho: workflow author/changelog.
- [Stripe — Versioning](https://docs.stripe.com/api/versioning) — monthly nonbreaking + major releases; SDK strongly typed cố định API version; webhook endpoint version riêng. Dùng cho: pinned execution; SDK caveat.
- [Stripe — API upgrades](https://docs.stripe.com/upgrades) — đối chiếu breaking changes của target version trước khi nâng cấp. Dùng cho: review/upgrade workflow.
- [Martin Fowler — Parallel Change](https://martinfowler.com/bliki/ParallelChange.html) — expand → migrate → contract; mỗi phase đều release được; migrate phase cần kỷ luật. Dùng cho: rollout thay đổi ngưỡng/tiền tệ.
- [GitLab — Backwards compatibility across updates](https://docs.gitlab.com/development/multi_version_compatibility/) — nhiều versions cùng sống trong lúc update; expand–contract qua milestones; contract có thể lùi tới major. Dùng cho: pending executions; rollout.
- [OPA — Integrating OPA](https://www.openpolicyagent.org/docs/integration) — tách policy decision khỏi application; decision theo input tại thời điểm hỏi; bundle/status/decision logs. Dùng cho: live authorization; phân tách pin/live.
- [Palantir — Action types submission criteria](https://www.palantir.com/docs/foundry/action-types/submission-criteria/) — conditions trên current user/parameter/execution context; tất cả phải pass lúc submit. Dùng cho: live checks tại invoke.
- [Palantir — Create an object type](https://www.palantir.com/docs/foundry/object-link-types/create-object-type) — type ID vs display name (đổi ID gãy app). Dùng cho: stable identity vs host rename.
- [Kubernetes — Object Names and IDs](https://kubernetes.io/docs/concepts/overview/working-with-objects/names/) — Name vs UID. Dùng cho: identity vs host names (kế thừa deep-dive 01).

Chương chính thức OaC sử dụng: `10-developer-experience.md` (§50–57), `06-action-model.md` (§26–34, đặc biệt approval ở §28 và execution record ở §30–31), `07-governance-and-security-model.md` (§40 audit/provenance), `08-ontology-engine.md` (§43–45 engine responsibilities/execution modes), cùng deep-dive `01-static-architecture-and-definition-lifecycle.md` (load/bind/invoke, registry vs IR, undeclared dependencies).
