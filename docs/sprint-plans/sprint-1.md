# Operational Architecture Research

Nghiên cứu trên cùng ca `ApprovePurchaseOrder`; mỗi phần được đọc và đối chiếu với contract của phần trước trước khi mở phần kế tiếp. Mỗi tài liệu phân biệt bằng chứng từ nguồn sơ cấp, đề xuất cho OaC và câu hỏi cần thử nghiệm. Không chốt ADR hay triển khai framework trong đợt này.

1. [x] [Static architecture & meta-model](../official/deep-dives/01-static-architecture-and-definition-lifecycle.md): tách kiểm tra khai báo, liên kết, capability khi triển khai và dữ liệu khi gọi.
2. [x] [Developer workflow & model evolution](../official/deep-dives/02-developer-workflow-and-model-evolution.md): phân biệt tương thích chữ ký với hành vi; graph đã đăng ký với downstream chưa biết; phiên bản logic với dữ liệu và quyền hiện hành.
3. [x] [Action contract & business workflow](../official/deep-dives/03-action-contract-and-business-workflow.md): phân biệt kết quả callback, trạng thái execution, kết quả commit mà caller biết và trạng thái giao effect.
4. [x] [Engine boundary & adapter capabilities](../official/deep-dives/04-engine-boundary-and-adapter-capabilities.md): kiểm tra guarantee theo resource và transaction thực; phân biệt guarded write, idempotency và xác nhận effect. Các kịch bản tranh ngân sách và mất phản hồi là thiết kế thử nghiệm, chưa chạy.
