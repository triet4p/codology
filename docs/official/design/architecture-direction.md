# Architecture Direction

*Brief quyết định kiến trúc chính cho OaC; chi tiết kỹ thuật xem [blueprint](./framework-design-v0.1.md). Không chứa kết quả thực nghiệm chưa kiểm chứng.*

## Câu chuyện tăng trưởng: từ nút duyệt đến hệ thống procurement

Ban đầu: tạo đơn, bấm duyệt, xong. Sau tăng trưởng, cùng nút duyệt phải thêm: vượt ngưỡng cần giám đốc tài chính; duyệt là giữ ngân sách thuộc Finance; nhà cung cấp đạt chính sách mới; xong thì báo kho. Brief này chốt cách thiết kế Object và Action để mỗi bước tăng trưởng chỉ thêm mới, không sửa lõi. Author thêm tờ khai mới thay vì luồn logic vào chỗ cũ; consumer đọc mỗi tác vụ như hợp đồng: gọi tên gì, cần quyền gì, xong ngay hay chờ duyệt.

## Object: dữ liệu có kiểu, ghép thay vì kế thừa

Object biểu diễn một thực thể nghiệp vụ có danh tính ổn định: cùng một đơn hàng vẫn là cùng một đơn dù đổi trạng thái hay chuyển nơi lưu. Dùng **giá trị** cho khái niệm không có vòng đời riêng như số tiền kèm đơn vị; dùng **quan hệ** khi hai thực thể có thể thay đổi độc lập như đơn hàng và nhà cung cấp. Không tạo loại đơn hàng mới chỉ vì nó cần thêm một bước duyệt.

So với active-record nhét mọi thứ vào phương thức object — tiện lúc đầu nhưng luật quản trị bị chôn trong code — và ORM chỉ-dữ-liệu đẩy logic ra service ngoài khiến không nơi nào trả lời trọn vẹn duyệt đơn cần gì: thiết kế được chọn giữ object là dữ liệu có kiểu, mọi tác vụ có quản trị thành Action có tên đứng riêng.

## Action: hàm thường hay action, đơn giản hay leo thang tường minh

Nếu chỉ trả lời một câu hỏi, dùng query hoặc function: “Đơn này còn thiếu bao nhiêu ngân sách?” vẫn là phép đọc dù cần kiểm tra quyền và đọc dữ liệu Finance. Nếu người gọi yêu cầu hệ thống **làm một việc** — duyệt đơn, giữ tiền, gửi yêu cầu sang hệ thống khác — dùng Action có tên nghiệp vụ. Điểm phân biệt là ý định và tác động, không phải số Object hay domain tham gia.

Với ca đơn giản, developer chỉ cần mô tả đầu vào, điều kiện và kết quả nghiệp vụ; không phải dựng workflow riêng. Khi phát sinh approval, effect hoặc thao tác ghi liên domain, khai báo thêm đúng phần đó. Engine kiểm tra trước những gì có thể biết từ mô hình và backend; quyền của người gọi, số dư và trạng thái đơn phải được xét khi chạy.

## Module, Governance, Engine and Adapter

### Module — nhóm theo quyết định nghiệp vụ, không theo nơi lưu dữ liệu

Module là ranh giới sở hữu: ai chịu trách nhiệm về ý nghĩa của một khái niệm và hành vi đã hứa với bên khác? Procurement quyết định khi nào một đơn được coi là đã duyệt. Finance quyết định thế nào là đã giữ ngân sách. Vì vậy, Procurement dùng nghiệp vụ giữ ngân sách mà Finance công bố, không tự sửa số dư. Finance có thể đổi cách tính số tiền khả dụng mà không buộc Procurement viết lại, miễn là giữ đúng lời hứa đã công bố.

**Mặc định giữ các phần thường đổi cùng nhau trong một module.** Đừng tách một module cho mỗi Object, mỗi bảng hay mỗi team. Chỉ tách khi có quy tắc cần một chủ sở hữu riêng và có thể mô tả rõ bên ngoài được dựa vào điều gì. Hai module có thể nằm trong cùng ứng dụng và dùng cùng database; công bố một nghiệp vụ cho module khác cũng **không** đồng nghĩa cấp quyền cho mọi người dùng.

Định nghĩa mới mặc định là nội bộ. Chỉ công bố những Object, quan hệ hoặc Action mà domain khác thực sự cần dựa vào; xác định rõ các phụ thuộc này để khi đổi một cam kết, developer biết phải trao đổi với ai.

### Governance — luật ở gần nghiệp vụ, kiểm tra nhất quán ở mọi cửa vào

Khi duyệt đơn, có ba câu hỏi: *người này được phép yêu cầu duyệt không; đơn còn hợp lệ để duyệt không; có cần người thứ hai xác nhận không?* Một người đủ quyền vẫn không được duyệt đơn đã hủy. Một đơn hợp lệ nhưng cần Finance xác nhận thì phải **chờ**, không phải bị từ chối. Developer thay quy tắc duyệt ở domain sở hữu nó; không lặp lại cùng phép kiểm tra trong web app, automation và AI.

Governance áp dụng cả cho việc đọc: không thấy một đơn thì cũng không được suy ra nó qua danh sách hay số đếm. Engine chịu trách nhiệm yêu cầu kiểm tra ở đúng thời điểm; tổ chức có thể giữ hệ thống danh tính và phân quyền hiện có. Cam kết này chỉ đúng với thao tác đi qua framework, không phải với ứng dụng tự dùng tài khoản database để đi đường khác.

Quyền không tự tăng khi đi qua ranh giới module. Khi Procurement gọi Finance để giữ ngân sách, lời gọi chỉ mang thẩm quyền cần cho khoản giữ đó, không mượn toàn bộ quyền của dịch vụ Finance.

### Engine — thống nhất cách thực hiện, không quyết định thay domain

Engine trả lời “làm sao thực hiện đúng điều đã hứa?”, không trả lời “đơn bao nhiêu tiền thì cần giám đốc duyệt?”. Nếu ngày mai đổi ngưỡng duyệt mà phải sửa engine thì ranh giới đã đặt sai. Ngược lại, nếu mỗi Action phải tự lo người gọi gửi lại yêu cầu sau khi mất phản hồi, framework đang đẩy phần việc chung trở lại cho developer.

Chọn engine nhúng. Một Action đơn giản có thể xong ngay; chỉ nghiệp vụ phải chờ mới cần lưu tiến độ để tiếp tục. Khi tiếp tục, giữ quy tắc của lần yêu cầu ban đầu nhưng kiểm tra lại quyền và tình trạng hiện tại. **Dùng chung ngữ nghĩa không đòi hỏi mọi ứng dụng phải gọi chung một server.**

### Adapter — thay cách kết nối, không thay nghĩa của kết quả

Adapter nối các khái niệm logic với hạ tầng thật và cho engine biết hạ tầng đó bảo đảm được gì. Đổi nguồn đọc ngân sách từ SQL sang ERP có thể chỉ cần đổi mapping và adapter **nếu** danh tính, đơn vị và độ mới dữ liệu vẫn đáp ứng contract. Nếu ERP chỉ trả số dư cuối ngày, không thể gọi đó là “số dư hiện tại” bằng cách đổi tên trường.

Với thao tác ghi, ranh giới còn rõ hơn: nếu nghiệp vụ hứa “duyệt đơn **và** giữ ngân sách cùng thành công”, adapter không được trả thành công khi ERP mới nhận yêu cầu. Hoặc hạ tầng đáp ứng lời hứa, hoặc engine từ chối cách triển khai đó. Nếu doanh nghiệp chấp nhận **đang chờ giữ ngân sách**, domain có thể công bố kết quả mới này; đó là quyết định nghiệp vụ, không phải chi tiết adapter tự chọn.

Các căn cứ: [định danh và hợp đồng công khai của module](../deep-dives/01-static-architecture-and-definition-lifecycle.md), [quyền, phê duyệt và kết quả Action](../deep-dives/03-action-contract-and-business-workflow.md), [ranh giới engine và năng lực adapter](../deep-dives/04-engine-boundary-and-adapter-capabilities.md).

## Luật nền không đổi

Đọc và ghi cùng chịu governance, nhưng chỉ Action được đề nghị thay đổi trạng thái. Không có transaction chung thì từ chối lời hứa “duyệt đơn và giữ tiền cùng thành công hoặc cùng thất bại”; không tự chuyển sang bù trừ. Chờ người duyệt không giữ transaction mở: giữ phiên bản quy tắc, kiểm tra lại quyền và số dư khi tiếp tục. Nếu đơn đã duyệt nhưng báo kho thất bại, xử lý việc báo kho, không duyệt lại đơn.

## Mở rộng không sửa lõi: thực thể mới hay năng lực mới

Nếu Finance bổ sung `Budget` cùng nghiệp vụ `ReserveBudget`, Procurement có thể gọi nghiệp vụ Finance công bố thay vì tự sửa số dư. Thêm một nguồn dữ liệu để đọc cùng `Budget` là thay mapping, không phải tạo Object mới. Web app và automation cùng gọi “duyệt đơn”, không tự nối các bước giữ ngân sách. Nhưng nếu trước đây “thành công” nghĩa là duyệt ngay, nay có thể là “đang chờ”, thì contract đã đổi: cần công bố thay đổi và cho consumer đường chuyển phiên bản. **Mở rộng không sửa engine không có nghĩa là không cần sửa domain hoặc consumer.**

## Phương án đã cân nhắc

**Registry metadata tập trung so với IR phân tán.** Chọn registry trong tiến trình, chỉ xuất snapshot khi consumer ngoài cần artifact độc lập phiên bản. Đảo ngược khi consumer không đọc được registry sống.

**Engine nhúng so với phục vụ độc lập.** Chọn nhúng để tránh chi phí vận hành và lỗi mạng của service riêng. Đảo ngược khi workload buộc chia sẻ engine qua tiến trình.

**Cố ý để mở:** cú pháp khai báo, chuẩn hóa tiền tệ, ngưỡng tươi chính sách, thời hạn duyệt, vận hành relay — thuộc về blueprint và triển khai.

## Liên kết

Nền tảng: [tầm nhìn và phạm vi](../01-project-vision.md), [ontology as code](../02-ontology-as-code.md), [kiến trúc hệ thống](../04-system-architecture.md), [mô hình action](../06-action-model.md), [quản trị và engine](../07-governance-and-security-model.md). Phụ lục kỹ thuật (tùy chọn): [Framework Design v0.1](./framework-design-v0.1.md) cùng bốn deep-dives trong `../deep-dives/`.
