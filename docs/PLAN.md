# Codology (Ontology as Code) — Project Roadmap

Mục tiêu: developer khai báo mô hình và hành vi nghiệp vụ một lần; ứng dụng đọc dữ liệu và gọi Action theo cùng hợp đồng, không tự viết lại luật phân quyền hay điều phối giao dịch. Dùng ca duyệt đơn mua hàng làm ví dụ xuyên suốt, rồi kiểm tra khả năng tái sử dụng ngoài ca này.

Package Python gốc của framework là `codology`; Ontology as Code (OaC) là tên khái niệm, không phải tên package. Cấu trúc package con sẽ được thiết kế chi tiết khi triển khai.

## Milestones

Mỗi sprint tương ứng một milestone. Sprint 1 và Sprint 2 đã hoàn tất; các mốc còn lại là thứ tự đề xuất. Mỗi dòng mô tả kết quả ở cuối sprint, không phải danh sách task.

| Sprint | Milestone | Kết quả mong đợi |
| --- | --- | --- |
| 1 · Đã xong | Nền tảng kiến trúc | Có [bốn nghiên cứu](sprint-plans/sprint-1.md) và [hướng thiết kế](official/design/architecture-direction.md) phân định trách nhiệm của Object, Action, Module, Governance, Engine và Adapter. Đây là cơ sở thiết kế, chưa phải API đã chốt. |
| 2 · Đã xong | Hợp đồng nhìn từ phía developer | [Kế hoạch Sprint 2](sprint-plans/sprint-2.md): có [hợp đồng author](official/design/developer-contract.md) (Nấc 1–3), [hợp đồng consumer](official/design/consumer-contract.md) và [quy tắc tiến hóa + kiểm chứng đa miền](official/design/evolution-and-cross-domain.md). Chốt biểu diễn class-based declaration đầu tiên cho Sprint 3. |
| 3 · Kế tiếp | Mô hình khai báo dùng được | Developer có thể định nghĩa Procurement và Finance trong code, nối hai module qua nghiệp vụ công khai và phát hiện tham chiếu sai trước khi kết nối backend. |
| 4 · Dự kiến | Lát cắt thực thi đầu tiên | Ứng dụng đọc đơn theo quyền rồi gọi `ApprovePurchaseOrder` qua engine nhúng và một adapter thật. Duyệt đơn và giữ ngân sách cùng thành công hoặc cùng thất bại; backend không đáp ứng thì không được nhận lời hứa này. |
| 5 · Dự kiến | Quy trình duyệt có thể chờ và tiếp tục | Đơn vượt ngưỡng chờ người có thẩm quyền. Khi tiếp tục, engine dùng phiên bản quy tắc ban đầu nhưng xét lại quyền và ngân sách hiện tại; lỗi gửi thông báo không làm duyệt đơn lần hai. |
| 6 · Dự kiến | MVP có thể bàn giao và mở rộng | Một developer khác dùng tài liệu để thêm nghiệp vụ ngoài ca duyệt đơn mà không sửa lõi; một consumer khác gọi cùng hợp đồng mà không chép lại luật. Ghi rõ giới hạn mà phiên bản đầu thực sự hỗ trợ. |

**Lý do sắp thứ tự:** chốt trải nghiệm tác giả và người gọi trước khi đóng khung cú pháp; chạy một nghiệp vụ đồng bộ trọn đường trước khi thêm trạng thái chờ. Governance và Adapter xuất hiện ngay ở lát cắt chạy đầu tiên, không phải hai lớp ghép sau.

**Phạm vi sau MVP:** chỉ mở rộng sang nhiều backend, engine dạng dịch vụ hoặc tích hợp AI/MCP chuyên biệt khi có nhu cầu cụ thể. [Đề xuất MVP ban đầu](official/16-proof-of-concept-and-mvp.md) là tài liệu tham chiếu, không phải cam kết triển khai toàn bộ stack. Kế hoạch chi tiết của từng sprint sẽ được lập khi mở sprint đó.
