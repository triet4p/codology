# Sprint 3 Plan — Declarations & Linked Registry

## Sprint Goal

Developer có thể khai báo Procurement và Finance bằng Python dưới package `codology`, liên kết `ApprovePurchaseOrder` với `ReserveBudget` qua API công khai và phát hiện lỗi mô hình ở Load/Link **trước khi kết nối backend**.

Sprint này tạo lớp mô hình tĩnh đầu tiên, không triển khai engine thực thi. Các ví dụ Sprint 2 là hợp đồng thiết kế, không phải API có sẵn; cú pháp cụ thể được chốt trong Sprint 3 và đồng bộ lại tài liệu.

## Phạm vi và tiêu chí hoàn thành

### Yêu cầu theo roadmap và hợp đồng hiện có

1. Có package Python gốc `codology`; cài đặt/import và chạy được ví dụ mô hình từ môi trường sạch theo hướng dẫn trong repository. `declarations` không phụ thuộc registry, engine hay adapter; registry không chạy handler hoặc đọc dữ liệu nghiệp vụ.
2. Author khai báo class-based cho `Module`, `ObjectType`, `Value`, `Link`, `Function`, `Action`, `ObjectRef[T]` và metadata cần thiết cho ca Procurement → Finance. Identity tách khỏi version và tên class; definition mặc định nội bộ, chỉ reference liên module khi đã export.
3. Compose hai module, Load và Link thành snapshot bất biến có thể tra cứu theo identity/version; cho thấy `ApprovePurchaseOrder` khai báo `calls` tới `finance.reserve_budget`. Việc compose/link không cần provider, DB hay credential.
4. Load từ chối identity trùng và key khai báo sai; Link từ chối reference không tồn tại, sai loại, không export hoặc không khớp tham số/kiểu handler. Forward reference liên module được resolve ở Link, kể cả hai module tham chiếu kiểu của nhau mà không import vòng khi chạy.
5. Kiểm thử có cả đường thành công lẫn lỗi và xác minh snapshot không bị thay đổi khi sửa declaration/collection đầu vào sau khi tạo; identity ổn định khi đổi host class name, hai class trùng host name nhưng khác identity không bị nhầm. Không tuyên bố static validation bắt được truy cập ẩn trong thân handler.
6. Hướng dẫn developer mô tả API thực tế, lệnh cài/chạy/kiểm thử và giới hạn. Tài liệu phân biệt Load/Link với deployment binding và runtime; không tuyên bố `ATOMIC`, authorization hoặc execution đã hoạt động.

### Mục tiêu thiết kế cần hiện thực trong phạm vi tĩnh

- Hỗ trợ khai báo có cấu trúc của `commitRequirement`, `approval` và `effects` để mô hình nấc 2–3 có thể được biểu diễn và kiểm tra tĩnh; không đánh giá approval trên dữ liệu thật, không giao effect. Load từ chối predicate không cấu trúc như lambda; Link kiểm tra các reference tương ứng. Ví dụ nấc 1 không phải khai báo boilerplate của nấc 2–3.
- Snapshot phơi bày biểu thức cấu trúc đủ phân biệt `>` và `>=`, cùng thông tin phiên bản và handler cần thiết cho audit/diff về sau. Không tuyên bố digest của artifact đã publish nếu sprint này chưa có quy trình build/publish artifact có thể xác minh.
- Kiểm tra typing với công cụ được cấu hình trong repository, bao gồm ví dụ hợp lệ và lỗi kiểu có ý nghĩa; mục tiêu Pyright strict theo thiết kế Sprint 2. Không đưa ra ngưỡng coverage hoặc hiệu năng khi chưa có điều kiện đo và phê duyệt.

### Ngoài phạm vi

Deployment binding và kiểm tra capability/`NoSharedTransaction`; engine `query`/`invoke`, authorization, session/UoW và atomic commit; approval callback/resume, outbox/effect delivery, idempotency/reconciliation; adapter backend thật, semantic diff hoàn chỉnh, SDK/MCP và publish/version rollout. Metadata `ATOMIC` được lưu trong mô hình không chứng minh backend đáp ứng atomicity. Các khả năng này thuộc sprint sau hoặc cần kế hoạch riêng.

## Atomic Tasks

Status: `[ ]` pending / `[~]` in progress / `[x]` done. **Workflow:** light; mỗi task có kiểm chứng phù hợp với phạm vi và commit theo phần việc; kiểm chứng tích hợp trước khi đóng sprint. Không ghi execution log vào kế hoạch.

- [ ] **S3-T1 — Chốt thiết kế chi tiết và khởi tạo project Python.** Thiết lập cấu trúc `codology`, packaging, môi trường chạy và test; ghi rõ phiên bản Python và lệnh tái lập. Chốt một quy ước handler duy nhất và cách resolve annotation không import vòng; đồng bộ các ví dụ liên quan. Kế hoạch Sprint 2 ghi `@staticmethod handle`, trong khi thiết kế chi tiết khuyến nghị `handler(self, ...)`: không hỗ trợ hai API chỉ để che bất đồng này. **Acceptance:** từ môi trường sạch import được package, chạy được kiểm thử nền; tài liệu nêu rõ quyết định và phân biệt API thiết kế với runtime chưa có.
- [ ] **S3-T2 — Khai báo cấu trúc miền.** Hiện thực biểu diễn class-based và metadata bất biến cho `Module`, `ObjectType`, `Value`, `Link`, `ObjectRef[T]`: identity/version, property có kiểu, target/cardinality/traversal và export. **Acceptance:** tạo được `PurchaseOrder`, `Budget`, `Money` và liên kết có kiểu; snapshot/declaration không thay đổi theo mutation của input; không cần database.
- [ ] **S3-T3 — Khai báo hành vi và governance tĩnh.** Hiện thực `Function`, `Action`, tham số, `reads`/`writes`/`calls`, permission, commit requirement, approval expression cấu trúc và effect/payload metadata. **Acceptance:** biểu diễn được nấc đơn module, liên module và nấc approval/effect bằng các thuộc tính cộng thêm; so sánh `>`/`>=` phân biệt được; lambda và expression không được hỗ trợ bị từ chối rõ ràng. Không chạy handler hay thực hiện action.
- [ ] **S3-T4 — Load và kiểm tra declaration.** Thu thập definition theo module, bảo toàn ownership và identity/version; kiểm tra identity duy nhất và trường khai báo hợp lệ, không lấy tên class làm identity. **Acceptance:** lỗi `DuplicateIdentity` và key lạ phát hiện ở Load; hai host class cùng tên với identity khác nhau không va chạm; lỗi có đủ context để author sửa.
- [ ] **S3-T5 — Link và kiểm tra ranh giới module.** Resolve typed references và forward annotations sau composition; kiểm tra đích tồn tại, đúng loại, được export khi qua module và chữ ký handler khớp contract. **Acceptance:** Procurement gọi được action Finance đã export; typo, reference không export, target sai loại và mismatch `ObjectRef[T]`/handler đều fail ở Link; ví dụ hai chiều không cần runtime circular import. Không chạy handler, không suy luận dependency ẩn từ thân handler.
- [ ] **S3-T6 — Snapshot và introspection tĩnh.** Công bố graph đã link bất biến, lookup tường minh theo identity/version, metadata của dependency và approval expression; không ngầm chọn `latest`. **Acceptance:** thay đổi input hay collection trả về không làm đổi snapshot; host rename không đổi identity/lookup; consumer phân biệt được hai expression khác toán tử. Chỉ ghi handler digest nếu xác định được bytes và phạm vi digest; không gọi hash tùy ý là digest artifact publish.
- [ ] **S3-T7 — Ví dụ tích hợp và bàn giao developer.** Xây ví dụ Procurement/Finance dùng API thật, minh họa đường Load/Link thành công và cách xử lý lỗi; bổ sung kiểm thử tích hợp và kiểm tra typing, hướng dẫn chạy, giới hạn tĩnh. **Acceptance:** môi trường sạch chạy ví dụ và các kiểm thử theo lệnh tài liệu; các ca duplicate, missing export, unresolved reference, sai kiểu/chữ ký và approval lambda được kiểm chứng; không cần backend, không giả lập runtime thành chức năng thật.

Thứ tự phụ thuộc: T1 trước các task code; T2–T3 cung cấp metadata cho T4; T5 dùng T4; T6 dùng graph đã link; T7 kiểm chứng toàn bộ đường đi. Các task có thể được chia nhỏ hơn khi triển khai nếu vẫn giữ kết quả và acceptance trên.

## Decisions / Blockers

- **Đã quyết định:** package Python gốc là `codology`; class-based là hướng authoring đầu tiên, không chốt mọi chi tiết cú pháp.
- **Cần quyết định trong S3-T1:** quy ước handler, phiên bản Python, layout/source packaging, công cụ test/type-check và cơ chế resolve forward references. Chọn theo khả năng kiểm chứng, rồi cập nhật tài liệu; không coi chúng đã được cài đặt hay chốt sẵn.
- **Ranh giới:** Sprint 2 là thiết kế; việc mô hình hóa metadata approval/effect ở đây không chuyển chức năng runtime của Sprint 4–5 vào Sprint 3.

## Tài liệu đầu vào

- [Roadmap](../PLAN.md) và [Sprint 2](sprint-2.md).
- [Developer Contract](../official/design/developer-contract.md): primitive, ownership, Load/Link và ranh giới tĩnh.
- [Evolution & Cross-Domain Validation](../official/design/evolution-and-cross-domain.md): class-based declaration, snapshot và checklist triển khai.
- [Framework Design v0.1](../official/design/framework-design-v0.1.md): seams package và ranh giới binding/runtime.
