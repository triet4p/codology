# Codology (Ontology as Code) — Project Roadmap

Mục tiêu: developer khai báo mô hình và hành vi nghiệp vụ một lần; ứng dụng đọc dữ liệu và gọi Action theo cùng hợp đồng, không tự viết lại luật phân quyền hay điều phối giao dịch. Dùng ca duyệt đơn mua hàng làm ví dụ xuyên suốt, rồi kiểm tra khả năng tái sử dụng ngoài ca này.

Package Python gốc của framework là `codology`; Ontology as Code (OaC) là tên khái niệm, không phải tên package. Cấu trúc package con sẽ được thiết kế chi tiết khi triển khai.

## Milestones

Mỗi sprint tương ứng một milestone. Sprint 1–6 đã hoàn tất. Mỗi dòng mô tả kết quả của milestone, không phải danh sách task.

| Sprint | Milestone | Kết quả mong đợi |
| --- | --- | --- |
| 1 · Đã xong | Nền tảng kiến trúc | Có [bốn nghiên cứu](sprint-plans/sprint-1.md) và [hướng thiết kế](official/design/architecture-direction.md) phân định trách nhiệm của Object, Action, Module, Governance, Engine và Adapter. Đây là cơ sở thiết kế, chưa phải API đã chốt. |
| 2 · Đã xong | Hợp đồng nhìn từ phía developer | [Kế hoạch Sprint 2](sprint-plans/sprint-2.md): có [hợp đồng author](official/design/developer-contract.md) (Nấc 1–3), [hợp đồng consumer](official/design/consumer-contract.md) và [quy tắc tiến hóa + kiểm chứng đa miền](official/design/evolution-and-cross-domain.md). Chốt biểu diễn class-based declaration đầu tiên cho Sprint 3. |
| 3 · Đã xong | Mô hình khai báo dùng được | [Sprint 3](sprint-plans/sprint-3.md): có khai báo Python cho Procurement và Finance, Link kiểm tra tham chiếu liên module qua nghiệp vụ công khai và snapshot tĩnh bất biến; chưa cần backend. |
| 4 · Đã xong | Lát cắt thực thi đầu tiên | [Sprint 4](sprint-plans/sprint-4.md): [consumer mẫu nấc 2](../examples/atomic_approval/README.md) đọc đơn theo quyền rồi gọi `ApprovePurchaseOrder` trên SQLite. Đơn, khoản giữ ngân sách và kết quả yêu cầu commit cùng nhau hoặc không ghi gì; binding từ chối cấu hình không có transaction chung. Có tra cứu/replay local, chưa có chờ duyệt hay outbox. |
| 5 · Đã xong | Quy trình duyệt có thể chờ và tiếp tục | [Sprint 5](sprint-plans/sprint-5.md): đơn từ ngưỡng chờ người có thẩm quyền. Khi tiếp tục, engine chạy lại đúng quy tắc đã ghim nhưng xét lại quyền và ngân sách hiện tại; thông báo được giao sau commit và lỗi thông báo không làm duyệt đơn lần hai. |
| 6 · Đã xong | MVP có thể bàn giao và mở rộng | [Sprint 6](sprint-plans/sprint-6.md): [nghiệp vụ cấp quyền giả lập](../examples/break_glass_access/README.md) chạy trên SQLite không sửa lõi; [CLI độc lập](../examples/purchase_order_cli/README.md) gọi cùng hợp đồng duyệt đơn. Hướng dẫn bàn giao phân biệt phần đã kiểm chứng và giới hạn thực tế. |

**Lý do sắp thứ tự:** chốt trải nghiệm tác giả và người gọi trước khi đóng khung cú pháp; chạy một nghiệp vụ đồng bộ trọn đường trước khi thêm trạng thái chờ. Governance và Adapter xuất hiện ngay ở lát cắt chạy đầu tiên, không phải hai lớp ghép sau.

**Phạm vi sau MVP:** chỉ mở rộng sang nhiều backend, engine dạng dịch vụ hoặc tích hợp AI/MCP chuyên biệt khi có nhu cầu cụ thể. [Đề xuất MVP ban đầu](official/16-proof-of-concept-and-mvp.md) là tài liệu tham chiếu, không phải cam kết triển khai toàn bộ stack.
