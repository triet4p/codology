# Framework Design v0.1

*Tài liệu blueprint khuyến nghị cho OaC core: recommended implementation baseline, not owner-approved ADR. Kế thừa 4 deep-dives và chốt quyết định xây dựng. Mọi code là đặc tả contract minh họa, chưa phải syntax cuối. Không chứa kết quả prototype — bằng chứng thực nghiệm mới thuộc tài liệu độc lập [atomic-approval-evidence.md](./atomic-approval-evidence.md).*

*Phạm vi: in-process core + ports; ngoài phạm vi: durable workflow backend, 2PC manager, FX subsystem toàn cục, SDK versioned.*

## 1. Kiến trúc khuyến nghị

**Quyết định: embedded modular monolith.**

Core là thư viện nhúng trong tiến trình host, tổ chức module hóa nghiêm ngặt, đi qua một pipeline duy nhất:

```text
module composition → immutable linked registry → deployment binding → governed execution
```

- **Một nguồn khai báo chuẩn duy nhất (canonical declaration source):** object graph Python sau load+bind là source of truth ở runtime. Không bắt buộc distributed IR hay file JSON versioned để chạy.
- **Không IR phân tán bắt buộc:** chỉ xuất exported IR snapshot (JSON bất biến, có version) khi trigger đã chốt ở deep-dive 01: consumer cần artifact độc lập triển khai và version (SDK phát hành, audit snapshot, multi-enrollment deploy), hoặc CI cần diff hai revisions không import chung process được. Introspection trực tiếp từ live registry phục vụ consumer cùng triển khai (kể cả MCP server).
- **Luồng bất biến:** registry sau linking là immutable; deployment binding gắn provider đã chọn; execution chỉ resolve những gì đã bind.

## 2. Mô hình trung lập host và nguồn khai báo

**Quyết định: Python-first cho author/consumer, tách cú pháp OOP khỏi mô hình trung lập host.**

### 2.1. Host-neutral meta-model (compact)

Mô hình trung lập host gồm các node và cạnh sau. Binding là artifact riêng, không phải field của declaration.

- **Module:** `identity`, `version`, `exports[]` (danh sách identity được phép reference ngoài domain).
- **Object type:** `identity`, `version`, `keyType`, `properties[]`, `links[]`. ID của definition không phải key của instance. `ObjectRef` gồm type ID và canonical instance key trong phạm vi tenant; adapter ánh xạ key logic sang nguồn vật lý.
- **Property:** `name`, `valueType`, `required`, và `comparisonUnit` khi cần so sánh đại lượng có đơn vị.
- **Value:** kiểu vô hướng hoặc kiểu nghiệp vụ có cấu trúc, ví dụ `Money(amount, currency)`. Core không hard-code ngưỡng tiền, vai trò Finance hay quy tắc procurement.
- **Link:** `name`, `target` (object identity), `cardinality` (`one` | `many`), `traversal` (`navigable` | `internal` — chỉ `navigable` mới đi qua query boundary).
- **Action:** `identity`, `version`, `params[]`, `resultType`, `reads[]`, `writes[]`, `calls[]`, `permission`, `approval`, `commitRequirement` và `effects[]`. Chúng độc lập: Action có thể đòi **cả** commit nguyên tử **và** ghi một ý định phát event cùng transaction. Outbox không phải một giá trị thay thế cho atomicity. V0.1 chỉ thực hiện local atomic write; contract saga không được nhận như một Action atomic.
- **Function:** chỉ đọc (read-only), không mutation, không approval; dùng cho derived/normalized view như `normalized_amount`.
- **Ref:** `ObjectRef[T]` — tham số có kiểu, resolve ở invoke-time thành instance đúng type.
- **Query:** `from`, `predicate` (cấu trúc), `order`, `cursor`, `limit`, `countRequested`; mọi Query đi qua read authorization trước khi chạm provider.
- **Binding (artifact riêng, không thuộc declaration):** `resource → provider`, `enlistmentPlan` (kế hoạch enlist dự kiến), `concurrencyGuard`, `commitCheck`, `policyFreshness` (chỉ khi contract đòi), `effectDedup` (chỉ khi contract dùng effect).

Không yêu cầu serialize arbitrary Python: approval/predicate chỉ hỗ trợ tập toán tử cấu trúc đã liệt kê (so sánh, and/or/not trên field có kiểu); biểu thức ngoài tập này bị từ chối ở load. Binding không thể phát hiện ambient host access (import lén, `getattr` động, đọc file/socket trong handler) — đó là rủi ro đã ghi nhận, xử lý bằng review/test chứ không bằng tuyên bố static coverage.

### 2.2. Handler artifact digest vs version labels

- **Version labels** (`actionVersion`, `ontologyVersion`) là tên do con người gán theo SemVer, dùng để pin logic, diff, và rollback.
- **Handler artifact digest** là hash của artifact handler đã build (bytecode/source bundle đã đóng gói) — thứ engine thực sự nạp khi resume/retry. Manifest ghim cả hai: version để con người lý giải, digest để máy nạp đúng bytes.
- Đổi thân handler giữ nguyên contract phải đổi digest và publish version mới (ít nhất PATCH); IR/diff mù trước thay đổi này nên consumer compatibility và migration tests là bắt buộc.

### 2.3. Author composition và query-to-invoke

Author khai báo composition tường minh; consumer đi từ query sang invoke qua cùng cửa policy:

```python
# author: composition khai báo, handler chỉ chạm cái đã khai báo
class ApprovePurchaseOrder(Action):
    identity = "procurement.approve_purchase_order"
    version = "2.0.0"
    order: ObjectRef[PurchaseOrder]
    reason: str
    reads = [PurchaseOrder, Budget]
    writes = [PurchaseOrder]
    calls = ["finance.reserve_budget"]
    permission = "purchase_order.approve"
    approval = Approval.conditional(
        when=Param("order").normalized_amount >= 100_000,
        role="finance_director",
    )
```

```text
# pseudocode: query → invoke qua cùng một engine
qs = engine.query(
    principal=p, from="PurchaseOrder",
    predicate=(status == "PENDING") & (normalized_amount >= 100_000),
    order="created_at", limit=20)          # policy áp trước paginate/count (mục 6)
ref = qs.rows[0].asRef()                    # Ref mang type + version đã bind
attempt = engine.invoke(
    principal=p, action="procurement.approve_purchase_order",
    parameters={"order": ref, "reason": "..."},
    requestKey="tenant-A:p:approve:PO-001:001",
    intentFingerprint=hash(canonical(action, version, ref, normalized_amount)))
```

## 3. Ranh giới đọc và ghi

**Quyết định: đọc/query và action/ghi là hai biên khác nhau, luật khác nhau.**

- **Read/query boundary:** truy vấn object set, filter/sort/paginate qua `DataProvider`. Authorization và query-time security đánh giá live theo principal.
- **Action/write boundary:** mọi mutation đi qua Action contract (authorize → validate → resolve → revalidate → commit). Handler nghiệp vụ thuần túy, chỉ chạm những gì declaration đã khai báo; truy cập không khai báo là lỗi bind khi phát hiện được, ngược lại là rủi ro đã ghi nhận — không phải tính năng.
- Static layer chỉ tin khai báo (`reads`, `writes`, `calls`, tham số có kiểu, `exports`).

## 4. Ports: core sở hữu định nghĩa, adapter thực thi, runtime gọi ra ngoài

Áp dụng dependency inversion: **core sở hữu mọi định nghĩa port** (Protocol/interface); **adapter thực thi** chúng; **runtime chỉ gọi outward** từ engine ra adapter. Adapter không bao giờ gọi ngược engine trừ callback đã khai báo trong contract. Host cung cấp providers thật, retention, relay, log platform.

| Port (do core định nghĩa) | Thực thi bởi | Hướng gọi runtime | Trách nhiệm contract |
| --- | --- | --- | --- |
| `DataProvider.resolve/query/apply` | Adapter | Engine → Adapter | Resolve `ObjectRef`, query có policy, apply mutation đã bind |
| `TransactionProvider.begin/commit/rollback` | Adapter | Engine → Adapter | Enlistment transaction vật lý thật sự, không phải label trùng tên |
| `PolicyProvider.authorize` | Adapter | Engine → Adapter | Decision live theo principal/world state, kèm revision để audit |
| `EffectPort.enqueue` | Adapter | Engine → Adapter | Ghi outbox row **trong cùng enlisted session** với state; relay at-least-once, dedup bằng id bền |
| Handler interface | Developer | Engine → Handler | Tính toán nghiệp vụ trên object đã resolve, đăng ký mutation vào UoW do engine cấp |

Phụ thuộc lớp: `consumer → engine → ports → adapters → backends`. Handler không import adapter, không mở connection, không gọi backend trực tiếp.

## 5. Handler context: không credential, không bearer token, không raw commit

In-process trust boundary không phải sandbox; handler ctx công khai không mang credential.

- `HandlerCtx` chỉ mang: caller identity đã xác thực, **delegation descriptor** (mô tả phạm vi ủy quyền: action, instance, quyền, hạn — engine kiểm tra lại trước mỗi dùng, không phải bearer token ai cầm cũng dùng được), resolved object handles, read-model đã lọc policy, và UoW handle giới hạn (chỉ `register_mutation` / `enqueue_effect`, **không có raw `commit`/`rollback`**).
- Không truyền provider/IAM/SQL credentials, connection string hay ambient service identity qua ctx. Deployment binding có thể từ chối một delegation mapping vượt quyền đã khai báo; nó không thể phát hiện hoặc chặn mọi truy cập trực tiếp từ Python code của host.
- Handler chạy cùng process nên không có cô lập bộ nhớ hay giới hạn tài nguyên — mọi bảo đảm đến từ khai báo + bind + revalidation + backend guard.

## 6. An toàn read: pushdown trung thực trước, engine bounded sau, còn lại từ chối

- Mọi query trả về qua engine: áp policy trước khi trả row, count, cursor, và cạnh link traversal (`navigable` only). Không có đường `list_raw`, `count_unfiltered`, hay duyệt link trực tiếp qua adapter bỏ qua engine.
- **Mặc định: faithful constrained predicate pushdown khi provider hỗ trợ.** Engine dịch predicate đã authorize thành điều kiện provider (ví dụ `WHERE`), kèm kiểm tra tương đương ngữ nghĩa + conformance test + ghi audit pushdown đã áp dụng. Count và traversal tuân cùng luật: count chỉ đếm trên tập đã authorize; traversal chỉ đi qua cạnh `navigable` đã authorize.
- **Dự phòng duy nhất: bounded complete pre-authorized engine evaluation trước pagination/count khi pushdown không đủ.** Engine nạp tập pre-authorized đầy đủ trong biên đã công bố (giới hạn row/scope), đánh giá toàn bộ, rồi mới paginate/count. Chỉ áp dụng khi chứng minh được biên an toàn cho workload đó.
- **Còn lại: `UnsupportedSecureQuery`.** Không bao giờ postfilter ngầm trên luồng unbounded (lấy raw không giới hạn rồi lọc lặng lẽ ở engine): hoặc pushdown trung thực, hoặc bounded pre-authorized evaluation, hoặc từ chối rõ ràng để caller thu hẹp scope.
- Error response ở cửa authorization không lộ chi tiết nghiệp vụ vượt quá quyền được thấy.

## 7. Transaction và scoped Unit of Work

**Quyết định: scoped Unit of Work (UoW) là mặc định; generic mutation plan là contract quan sát được, không phải cơ chế thực thi.**

- Generic mutation plan mô tả *định đổi gì* (`expectedVersion` mỗi object, tập writes) để revalidate và audit. Nó không quy định *ghi thế nào* trên từng backend.
- Scoped UoW là cơ chế thực thi duy nhất trong v0.1: engine mở một UoW trên đúng enlisted session đã bind, handler đăng ký mutations vào UoW, engine revalidate rồi commit một lần. UoW có biên rõ (một Action execution, một transaction vật lý), có guard nguyên tử trong cùng statement (`WHERE balance >= amount AND version = :v`, `rowcount == 1 else StalePlan/Conflict`), và bắt re-read/recompute sau conflict — cấm retry mù cùng payload.
- Giới hạn: UoW không mở rộng qua backend thứ hai không shared session; không thay thế saga/durable orchestration cho flow dài ngày.
- **Strict atomic mode:** mọi mutation bắt buộc của Action và child dùng chung một transaction thực, do engine commit. Nếu `PurchaseOrder@postgres` và `Budget@erp` không thể enlist chung, trả `NoSharedTransaction` trước khi ghi. Outbox có thể ghi *ý định* thông báo ERP chứ không thể bảo đảm ngân sách ERP đã được giữ. Muốn cho phép ngân sách ở trạng thái chờ phải định nghĩa một contract nghiệp vụ khác.
- **Binding kiểm tra ability + enlistment plan; execution bảo đảm single session thật.** Deployment binding kiểm tra provider có khả năng (capability) và duyệt enlistment plan (resource nào enlist vào session nào). Nhưng bảo đảm chỉ hoàn tất ở execution: engine xác nhận mọi writes cùng enlisted trong **một session đang mở duy nhất** rồi mới commit. Label trùng tên hay cùng brand DB mà enlistment tách đôi vẫn rớt.
- **Không giữ transaction mở xuyên approval.** Execution `AWAITING_APPROVAL` không giữ session/UoW nào đang mở. Khi resume (callback duyệt, retry, rollout xen giữa), engine mở UoW mới, recompute bằng logic version đã ghim (digest trong manifest), revalidate live authorization/world state, rồi mới commit. Thay đổi material → reapproval.
- **Một pinned root manifest cho mỗi execution.** Manifest ghim `actionVersion` + `ontologyVersion` + handler digest của root và **exact child + handler revisions** cho mọi `calls` (ví dụ `finance.reserve_budget@1.0.0#digest`). Resume dùng đúng revisions đã ghim. Child migrate độc lập chỉ tồn tại như **explicit contract riêng** (parent khai báo chấp nhận child range + migration rule + reapproval policy), không bao giờ là "lấy latest của child" ngầm định.

## 8. Phê duyệt, authority, idempotency

- **Ba thực thể tách biệt:** (a) public Action contract (definition bất biến đã publish); (b) evidence of caller attempt (submission: request key, intent fingerprint, input, principal, thời điểm); (c) authoritative execution record (kết quả do engine ghi sau revalidation). Attempt không phải record; record chỉ engine được ghi.
- **Core tách hai authority:** requester (tạo execution) và approver (thỏa `requiredApproval`) là hai vai, audit ghi cả hai. Approver cần cả role duyệt và permission còn hiệu lực tại thời điểm duyệt (live check). Cấm tự duyệt là policy của domain ví dụ, khai báo tường minh để tắt/mở — không phải luật core.
- **Approval gắn material intent:** (`executionId`, `actionVersion`, `normalized_amount` + source/target currency + `quote_version`, `expectedVersion`, phạm vi child). Chỉ thay đổi material kích hoạt reapproval. Hết hạn/thu hồi trước commit → quay về chờ hoặc từ chối, không commit lặng lẽ. Callback bị `DENIED` chỉ ghi audit cho callback đó; execution vẫn `AWAITING_APPROVAL`.
- **Payload replay ≠ mutate twice:** phát lại cùng payload để đọc/tra cứu attempt evidence chỉ cần read authorization trên execution record. Thực hiện lại mutation đòi invoke authorization đầy đủ + idempotency key còn retention + revalidate live — không dùng quyền đọc để ghi.
- **Idempotency scope:** key có phạm vi `tenant / principal / action / key` đã xác thực, kèm **canonical intent fingerprint** (hash chuẩn của action + version + params chuẩn hóa + normalized amount + target refs). Scope ổn định xuyên rollout version: cùng intent dưới version khác vẫn cùng scope để dedup, nhưng recompute theo manifest đã ghim của execution đó. Tính duy nhất (uniqueness) + business state + execution record + outbox row commit **trong cùng transaction**; duplicate trả kết quả đã lưu sau khi kiểm tra read authorization của caller; cùng key khác fingerprint → từ chối misuse. Cùng key không bao giờ thực thi lại một execution đã `COMMITTED`. Pinned artifact (manifest/digest) không còn khả dụng → fail closed (từ chối resume), không đoán latest.
- **Attempt denial vs execution terminal:** `DENIED` ở cửa attempt (thiếu quyền invoke, key misuse, fingerprint mismatch) là từ chối attempt đó — execution (nếu đã tồn tại) không đổi trạng thái, audit ghi attempt bị từ chối tách khỏi lịch sử execution. Chỉ `COMMITTED`/`FAILED`/terminal policy mới kết thúc execution.
- **Commit vs effect:** commit `COMMITTED` và giao effect có trạng thái riêng. Effect lỗi sau commit → execution vẫn `COMMITTED` kèm effect `PENDING_RETRY`/`FAILED`, xử lý bằng retry có key hoặc compensation — không "un-commit".

## 9. Lifecycle và ma trận lỗi

Lifecycle tối thiểu quan sát được: `SUBMITTED → (DENIED | REJECTED | AWAITING_APPROVAL | COMMITTED | FAILED)`, với `AWAITING_APPROVAL → (COMMITTED | REJECTED | DENIED | EXPIRED→AWAITING_APPROVAL)`.

- Bảng ma trận:

| Lỗi | Pha phát hiện | Kết quả | Xử lý |
| --- | --- | --- | --- |
| `DuplicateIdentity` | Load | Từ chối load | Sửa khai báo, không vào bind |
| `UnresolvedReference` / `NotExported` | Linking | Từ chối bind | Export hoặc sửa reference |
| `NoSharedTransaction` | Deployment binding | Từ chối atomic contract | Ký contract khác (saga/outbox) |
| `DENIED` attempt (thiếu quyền/key misuse) | Invoke/callback/commit | Từ chối attempt | Không đổi execution; audit attempt |
| `REJECTED` (precondition rớt) | Invoke/commit | Từ chối nghiệp vụ | Sửa dữ liệu rồi submit mới |
| `AWAITING_APPROVAL` | Invoke | Chờ duyệt | Callback đủ thẩm quyền |
| `StalePlan` / guard conflict | Pre-commit revalidation | Từ chối plan cũ | Re-read/recompute, reapproval nếu material |
| `UNKNOWN` (timeout sau commit) | Caller reconcile | Chưa biết | Tra key → lookup ledger/provider |
| `UnsupportedSecureQuery` | Query plan | Từ chối query | Thu hẹp scope hoặc bật pushdown được chứng minh |
| Effect `PENDING_RETRY`/`FAILED` | Sau commit | Effect treo | Retry effect có key / compensation |
| Compensation thất bại | Saga contract | `ESCALATED` | Can thiệp tay, không tự `COMMITTED` |

Gộp `DENIED` với `REJECTED` hoặc gộp effect lỗi vào execution `FAILED` đều sai contract vì xóa thông tin consumer cần để hành động.

## 10. Tiến hóa và workflow developer

Áp dụng từ deep-dive 02: author → model check (load/bind) → impact analysis (semantic diff + detected graph) → review/tests (PR) → rollout (publish version, xử lý pending) → rollback có kế hoạch.

- Execution ghim manifest của plan-generating logic (`actionVersion` + `ontologyVersion` + handler digest + child revisions); resume recompute bằng đúng manifest rồi revalidate live; thay đổi material → reapproval theo chính sách đã công bố.
- Authorization decision và world state luôn live; audit ghi cả manifest đã ghim và decision live.
- Thay đổi approval behavior thuộc contract (`>` thành `>=`) là MAJOR dù signature không đổi — ví dụ chuẩn là `1.2.0 → 2.0.0` inclusive (`>= 100_000`); blast radius chỉ quyết định rollout (expand–contract, deprecation window), không hạ MAJOR. Rollback = publish/fallback về version bất biến, không sửa version tại chỗ.
- Impact analysis chỉ tuyên bố bao phủ detected graph (`calls`, `exports`, permission refs, generated schema); downstream đã cài SDK, dashboard ngoài, SOP con người là unobservable — xử lý bằng changelog/migration note/deprecation window.
- Mọi ngưỡng tiền tệ khai báo comparison currency; khi quy đổi ghi `source_currency` + `target_currency` + `quote_version`. Không dựng FX subsystem toàn cục.

## 11. Seams code/package và thứ tự thực hiện

Seams đề xuất (bám port ở mục 4; định nghĩa port sống trong core):

```text
codology/
  declarations/   # Action, ObjectType, Module, Function, Query, Approval expression
  registry/       # composition, load/link, immutable snapshot, introspect
  binding/        # deployment binding, capability + enlistment plan check
  engine/         # invoke pipeline, UoW, revalidation, execution record, audit
  ports/          # định nghĩa port do core sở hữu (DataProvider, TransactionProvider, ...)
  adapters_pg/    # thực thi port cho PostgreSQL: guarded debit, outbox cùng session
```

Tên package Python gốc là `codology`; OaC là viết tắt của khái niệm Ontology as Code. Các package con và thứ tự dưới đây là đề xuất thiết kế, không phải code đã triển khai.

Thứ tự thực hiện (mỗi bước có acceptance + negative):

1. **Declarations + composition + immutable registry.** Acceptance: trùng identity rớt load; reference sai/export thiếu rớt linking. Negative: ambient host access trong handler (import lén, `getattr` động) mà bind vẫn pass — ghi nhận rủi ro, không tuyên bố phát hiện toàn cục.
2. **Deployment binding + strict atomic.** Acceptance: hai writes cùng enlisted session pass; PG+ERP đòi atomic → `NoSharedTransaction`. Negative: hai connections cùng brand DB nhưng enlistment tách đôi vẫn rớt.
3. **Invoke pipeline + UoW + revalidation.** Acceptance: `StalePlan(expected=12, current=13)` thay vì ghi đè; hai executions tranh một budget → đúng một `COMMITTED` bằng guarded debit. Negative: retry mù cùng payload sau conflict vẫn sai (phải re-read).
4. **Approval + idempotency + reconciliation.** Acceptance: outsider callback `DENIED` mà execution vẫn chờ; duplicate callback cùng key là no-op, khác fingerprint thì từ chối; timeout → `UNKNOWN` rồi lookup; pinned artifact mất → fail closed. Negative: dùng quyền đọc record để ghi lại mutation phải bị từ chối.
5. **Effects (outbox enqueue cùng session + dedup) + audit schema.** Acceptance: relay crash → redelivery trùng id cho một effect duy nhất; execution vẫn `COMMITTED`. Negative: broker ack không tính là effect đã làm.
6. **Semantic diff + evolution workflow.** Acceptance: `>`→`>=` render một dòng approval + cờ security-related + MAJOR `1.2.0 → 2.0.0`; host rename giữ identity thì bind xanh nhưng SDK sinh từ host name rớt compat test.

Chưa làm trong v0.1: 2PC manager, durable workflow backend, saga orchestrator đầy đủ, auto-compensation bảo đảm, SDK versioned trước trigger.

## 12. Alternatives ranked by topic (với selection trigger)

Mỗi topic giữ đúng 2 ứng viên thực sự cân nhắc; trigger ghi rõ quan sát nào đổi lựa chọn.

- **Topic A — Cơ chế ghi: scoped UoW (chọn) vs generic mutation plan làm cơ chế thực thi.** Chọn UoW vì biên hẹp kiểm tra được ở binding, guard gắn statement, audit before/after. Đổi sang generic-plan-as-executor chỉ khi xuất hiện backend đòi planner trung gian không ánh xạ được vào UoW một session (ví dụ coordinator đa backend có bảo đảm tương đương atomic đã chứng minh) — và khi đó UoW thành trường hợp riêng của planner, không bị xóa.
- **Topic B — Read authorization: faithful constrained pushdown mặc định (chọn) vs luôn evaluate ở engine.** Chọn pushdown trung thực khi provider hỗ trợ vì tránh rò rỉ qua unbounded postfilter và giữ count/traversal đúng; dự phòng duy nhất là bounded complete pre-authorized evaluation, còn lại `UnsupportedSecureQuery`. Đổi sang engine-always chỉ cho workload cụ thể nơi chứng minh được biên pre-authorized evaluation luôn an toàn và rẻ hơn pushdown — đo bằng trace rò rỉ bằng không + chi phí thấp hơn trên workload đó.
- **Topic C — Child versioning: one pinned root manifest (chọn) vs independent child migration (latest ngầm).** Chọn pinned manifest vì resume/retry/audit tái hiện được exact revisions. Chấp nhận independent child migration chỉ như explicit contract riêng (parent khai báo range + migration rule + reapproval) khi vận hành chứng minh được child tương thích ngược hoàn toàn qua compat suite trên mọi parent đang pending — một ca reapproval vòng lặp hay audit không tái hiện được sẽ quay về pinned manifest.

Các lựa chọn trên là mặc định để bắt đầu triển khai. Thứ cần bảo toàn nếu đổi cơ chế là contract quan sát được và các ca kiểm chứng, không phải tên class hay layout package.

## 13. Đóng băng, linh hoạt, ngoài phạm vi, bằng chứng

- **Đóng băng cho v0.1:** pipeline composition → registry → binding → execution; meta-model mục 2.1 và `exports`; core sở hữu định nghĩa port; strict atomic (single enlisted session hoặc từ chối, bảo đảm ở execution); scoped UoW + enqueue effect cùng session; không tx mở xuyên approval (re-open UoW mới khi resume); pinned root manifest; tách contract/attempt/record; tách request key/callback key + intent fingerprint; fail closed khi pinned artifact mất; `UNKNOWN` chỉ giải quyết bằng reconciliation; effect có trạng thái riêng; currency khai báo kèm source/target/quote; read theo pushdown-trung-thực/bounded/`UnsupportedSecureQuery`.
- **Linh hoạt (mutable):** cú pháp Python cụ thể của declaration; tập toán tử cấu trúc của approval/predicate; vị trí chuẩn hóa `Money`; ngưỡng hard-fail/advisory cho policy stale; retention idempotency và prune policy; ai vận hành outbox relay; thời hạn approval và quyền gia hạn.
- **Ngoài phạm vi v0.1:** durable workflow backend, 2PC/external transaction manager, saga orchestrator đầy đủ, FX subsystem toàn cục, SDK versioned trước trigger, property-level scope đầy đủ (§39), interface structural-vs-behavioral (§23).
- **Phân biệt bằng chứng:** khẳng định gắn **[Nguồn]** trong 4 deep-dives là bằng chứng hiện có từ tài liệu sơ cấp (đã trích dẫn URL). Khẳng định gắn **[Đề xuất OaC]** là quyết định phân tích, chưa phải bằng chứng thực nghiệm. Kết quả thí nghiệm độc lập (bao gồm kiểm chứng atomic/approval) thuộc [atomic-approval-evidence.md](./atomic-approval-evidence.md).

## References and Web Sources

Liên kết bắt buộc — 4 nghiên cứu nền và tài liệu bằng chứng độc lập:

- [Static Architecture and Definition Lifecycle](../deep-dives/01-static-architecture-and-definition-lifecycle.md) — load/bind/invoke, identity vs host name, exports, registry-first và IR triggers, undeclared dependencies.
- [Developer Workflow and Model Evolution](../deep-dives/02-developer-workflow-and-model-evolution.md) — threshold/currency, SemVer cho contract, pinned execution vs live authorization, expand–contract, rollback.
- [Action Contract and Business Workflow](../deep-dives/03-action-contract-and-business-workflow.md) — `DENIED`/`REJECTED`/`AWAITING_APPROVAL`, authority và delegation thu hẹp, intent binding và revalidation, idempotency keys, `UNKNOWN` reconciliation, commit vs effect.
- [Engine Boundary and Adapter Capabilities](../deep-dives/04-engine-boundary-and-adapter-capabilities.md) — responsibility map, binding artifact, declared vs conformance vs runtime evidence, local atomic vs PG+ERP, saga là contract riêng, guarded debit và outbox.
- [Atomic Approval Evidence](./atomic-approval-evidence.md) — kết quả thí nghiệm độc lập (tài liệu riêng; không đưa kết quả vào blueprint này).
