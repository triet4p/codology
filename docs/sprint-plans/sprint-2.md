# Sprint 2 Plan — Developer-Facing Contract & Progressive Complexity Surface

## Sprint Goal
Thiết kế và kiểm chứng bề mặt hợp đồng developer (Authoring Contract, Consumer Contract và Evolution/Versioning Rules) cho **Codology** qua các kịch bản thực tế có độ phức tạp tăng dần, chốt cách biểu diễn khai báo đầu tiên để làm đầu vào trực tiếp cho Sprint 3 mà không khóa cứng API dài hạn.

## Atomic Tasks

Status legend: `[ ]` pending / `[~]` in progress / `[x]` done

Workflow: Light route (no per-task `evidence-reviewer`, no checkpoint executor, no deep review); worker commits verified own scope to `F:/ai-ml/codology` (`ref: main`, scoped porcelain on task-owned files only, Conventional Commits per `~/.agents/rules/git.md`). Scoped auto-routing authorized for Sprint 2 (`S2-T1`..`S2-T4`: `gold-task` for T1, T2, T4; `silver-task` for T3).

Acceptance:

- **Agreed requirements:**
    1. Bề mặt khai báo đạt tính **progressive disclosure**: ca đơn giản chỉ khai báo tối thiểu (`ObjectType`, `Action`, `permission`, `handler`); khi leo thang lên giao dịch liên module, chờ duyệt hoặc phát effect thì chỉ **cộng thêm (additive)** thuộc tính khai báo, không đổi cấu trúc cốt lõi.
    2. Mọi ví dụ code trên bề mặt Author và Consumer tuân thủ nghiêm ngặt các biên đã chốt ở Sprint 1: `HandlerCtx` không lộ raw credentials/connection/commit; read/query lọc quyền trước paginate/count; `ObjectRef[T]` mang danh tính có kiểu; tách biệt rõ `DENIED`, `REJECTED`, `AWAITING_APPROVAL`, `COMMITTED`, `StalePlan`, `UNKNOWN` và trạng thái `Effect`.
    3. Bề mặt không bị "may đo" riêng cho Procurement/Finance: được kiểm chứng tái sử dụng trên ít nhất một domain khác mà không phát sinh primitive mới ngoài meta-model v0.1.
- **Proposed targets:** Giữ bộ tài liệu đặc tả Sprint 2 gọn, trực diện theo phong cách `docs/official/design/` (ưu tiên bảng đối chiếu contract và code minh họa tối giản trước–sau tiến hóa).

Review continuation: Two rounds by default if subagent review is invoked; Main may authorize one third for evidenced progress and a bounded correction/check; owner decision otherwise or after round 3 without PASS.

- [x] **Task 1: Nấc 1 & 2 — Authoring Contract từ ca đồng bộ đơn lẻ đến liên module nguyên tử (`Procurement` → `Finance`).** (`e1ae05b`, [`developer-contract.md`](../official/design/developer-contract.md))
  - **Phạm vi:** Đặc tả cách người viết domain khai báo `Module`, `ObjectType`, `Value` (`Money`), `Link`, `Function` (read-only) và `Action` ở hai mức độ đầu tiên:
    - *Mức 1 (Synchronous single-module):* `ApprovePurchaseOrder` v1.0 chỉ kiểm tra trạng thái đơn và đổi sang `APPROVED` trong nội bộ `procurement`.
    - *Mức 2 (Cross-module atomic & narrowed delegation):* `finance` công bố `Budget` và `ReserveBudget` qua `exports`; `ApprovePurchaseOrder` v1.1 khai báo `calls = ["finance.reserve_budget"]` và `commitRequirement = CommitRequirement.ATOMIC` trên cùng `HandlerCtx` / scoped `UoW`.
  - **Acceptance:** Chỉ rõ những gì author **phải** khai báo, những gì mặc định là nội bộ (`private` trừ khi nằm trong `exports`), giao diện `HandlerCtx` tối thiểu, và lỗi tĩnh nào bị chặn ở pha `load/link/bind` (`DuplicateIdentity`, `NotExported`, `NoSharedTransaction`).

- [x] **Task 2: Nấc 3 — Leo thang quản trị bất đồng bộ (`Approval`, `Revalidation`, `Effects`) trên bề mặt Authoring.** (`511c130`, [`developer-contract.md`](../official/design/developer-contract.md))
  - **Phạm vi:** Mở rộng cùng `ApprovePurchaseOrder` lên v2.0 khi nghiệp vụ đòi hỏi:
    - Điều kiện chờ duyệt có cấu trúc (`Approval.conditional` trên `normalized_amount >= 100_000` với đơn vị tiền tệ tường minh, tách requester và approver).
    - Khai báo `effects` (outbox cùng enlisted session, ví dụ thông báo kho/ERP sau khi duyệt) tách biệt khỏi kết quả commit của Action.
    - Hành vi của handler khi engine resume sau `AWAITING_APPROVAL` (recompute trên pinned manifest + revalidate quyền và ngân sách hiện tại, phát hiện thay đổi material).
  - **Acceptance:** Chứng minh sự chuyển dịch từ Mức 1 → Mức 2 → Mức 3 hoàn toàn là khai báo cộng thêm (additive declaration); bảng phân định rõ phần việc của Author trong handler vs phần việc của Engine khi tạm dừng và tiếp tục.

- [x] **Task 3: Consumer Contract — Bề mặt gọi `query`, `invoke`, `approve`, `reconcile` và ma trận kết quả/lỗi.** (`7e2d43e`, [`consumer-contract.md`](../official/design/consumer-contract.md))
  - **Phạm vi:** Đặc tả hợp đồng phía người gọi (Web app, automation, AI agent/MCP) khi tương tác với một Action ở cả 3 mức độ phức tạp:
    - Luồng `query → ObjectRef[T] → invoke` qua cùng cửa policy (bao gồm truyền `requestKey` và `intentFingerprint`).
    - Cấu trúc `ActionResult` / `ExecutionRecord` / `AttemptOutcome` trả về cho caller: dữ liệu nào có ở `COMMITTED`, dữ liệu nào có ở `AWAITING_APPROVAL` (ai cần duyệt, phạm vi nào), và cách phân biệt `DENIED` (lỗi quyền/key misuse tại cửa attempt) với `REJECTED` (rớt điều kiện nghiệp vụ), `StalePlan` (xung đột phiên bản/guard), `UNKNOWN` (mất phản hồi cần `reconcile`).
    - Hợp đồng gọi `approve` / `reject` callback và đọc trạng thái giao `Effect` (`PENDING_RETRY` / `DELIVERED` / `FAILED`).
  - **Acceptance:** Consumer có bảng tra cứu hành động tương ứng cho từng mã trạng thái trả về mà không cần đọc code nội bộ của handler hay tự viết lại rule phân quyền.

- [x] **Task 4: Evolution & Versioning Contract + Kiểm chứng tái sử dụng đa miền (Cross-Domain Validation).** (`8f0ea1b`, [`evolution-and-cross-domain.md`](../official/design/evolution-and-cross-domain.md))
  - **Phạm vi:**
    - Chốt bảng quy tắc tiến hóa hợp đồng (`v1.0 → v1.1 → v2.0`): thay đổi nào giữ nguyên contract (PATCH/host rename giữ `identity`), thay đổi nào mở rộng tương thích ngược (MINOR), thay đổi nào phá vỡ giả định của consumer và bắt buộc nâng `MAJOR` (thêm trạng thái `AWAITING_APPROVAL` cho action vốn đồng bộ, đổi ngưỡng `>` thành `>=`, đổi đơn vị tiền tệ, thu hẹp quyền).
    - Kiểm chứng tính tái sử dụng của toàn bộ bề mặt (Author + Consumer) bằng cách áp vào một use case thuộc miền nghiệp vụ khác (ví dụ: cấp quyền truy cập hạ tầng nhạy cảm hoặc xử lý yêu cầu hoàn tiền/bảo hành nhiều bước) dùng đúng bộ primitives đã chốt.
    - Chốt khuyến nghị biểu diễn khai báo đầu tiên trong Python (class-based declaration vs decorator/builder tradeoffs) làm đầu vào cho Sprint 3.
  - **Acceptance:** Không phát sinh khái niệm/primitive đặc thù domain trong core; có bảng quyết định SemVer + semantic diff mẫu và bản thiết kế bề mặt khai báo sẵn sàng để Sprint 3 bắt đầu code `declarations/` và `registry/`.

## Decisions / Blockers

- **Tên dự án:** Chính thức sử dụng tên **Codology** cho repository và kế hoạch dự án (giữ thuật ngữ khái niệm *Ontology as Code / OaC* trong các tài liệu nền).
- **Package Python gốc:** `codology` là namespace thống nhất cho framework; `OaC` vẫn là viết tắt của khái niệm Ontology as Code. Sprint 3 thiết kế và triển khai các package con dự kiến `codology.declarations` và `codology.registry`.
- **Phương pháp thiết kế Sprint 2:** Case-Driven API Design theo nấc thang độ phức tạp (Mức 1: Đồng bộ đơn lẻ → Mức 2: Liên module nguyên tử → Mức 3: Chờ duyệt & Effect → Mức 4: Tiến hóa & Kiểm chứng đa miền).
- **Ranh giới Sprint 2 vs Sprint 3:** Sprint 2 chốt hợp đồng developer và chọn hình thức khai báo đầu tiên ở mức thiết kế có kiểm chứng chéo; Sprint 3 mới viết mã thư viện thực thi cho `declarations/` và `registry/`.
- **Khuyến nghị biểu diễn khai báo đầu tiên cho Sprint 3:** Chọn **class-based declarative schema** (`class ApprovePurchaseOrder(Action): ...` + `@staticmethod def handle(ctx, ...)`), ánh xạ trực tiếp 1-1 vào `declarations/` và `registry/` mà không cần AST/bytecode magic (xem [`evolution-and-cross-domain.md` §3](../official/design/evolution-and-cross-domain.md)).
