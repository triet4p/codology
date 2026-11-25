# Evolution & Cross-Domain Validation

*Đặc tả ba việc còn lại của bề mặt developer: xếp hạng thay đổi hợp đồng theo SemVer kèm semantic diff, chứng minh Author Contract + Consumer Contract tái sử dụng nguyên vẹn ngoài Procurement/Finance, và chốt bề mặt khai báo Python đầu tiên cho `declarations/` + `registry/`. Mọi code là đặc tả contract minh họa, chưa phải syntax cuối.*

## 1. Tổng quan

Ba câu hỏi, ba đầu ra, cùng một tiêu chí: **thay đổi chỉ được coi là an toàn khi consumer hiện tại không phải sửa gì**.

| Câu hỏi | Trả lời ở | Đầu ra bắt buộc |
| --- | --- | --- |
| Thay đổi nào giữ nguyên contract, thay đổi nào phá consumer? | Mục 2 | Bảng quyết định PATCH/MINOR/MAJOR, semantic diff mẫu, quy tắc rollout cho execution đang treo |
| Bề mặt có bị "may đo" cho Procurement/Finance không? | Mục 3 | Khai báo + trace đầy đủ cho miền cấp quyền hạ tầng, bảng ánh xạ primitive 1-1 |
| Bề mặt khai báo Python đầu tiên là gì? | Mục 4 | Khuyến nghị class-based, tiêu chí đổi lựa chọn, ánh xạ package và checklist triển khai |

Hai nguyên tắc xuyên suốt:

- **Version thuộc về definition đã publish, không thuộc về host code.** `identity` ổn định; `version` là trường riêng; tên class, tên file và vị trí handler refactor tự do.
- **Ba pha tĩnh xanh không phải giấy chứng nhận tương thích.** Load/Link/binding chỉ kiểm tra cấu trúc và export; chúng không đọc thân handler, không đánh giá ngưỡng, không biết consumer nào đang chạy. Phân loại thay đổi phải dựa trên thứ consumer quan sát được, không dựa trên việc kiểm tra tĩnh có rớt hay không.

## 2. Hợp đồng tiến hóa và versioning

### 2.1 Phần contract quan sát được và phần mù

| Thành phần | Nơi sống | Load/Link/binding thấy? | Semantic diff thấy? | Đổi thì ai rớt? |
| --- | --- | --- | --- | --- |
| `identity`, `version` | Khai báo | Có (duy nhất, đúng dạng) | Có | Registry, audit, SDK, MCP tool |
| `params` (tên, thứ tự, kiểu) | Annotation + chữ ký handler | Có (Link kiểm kiểu + export) | Có | Caller, SDK, automation |
| `reads`, `writes`, `calls` | Khai báo | Có (Link + export) | Có | Deployment binding, phạm vi quyền chạm |
| `permission` | Chuỗi khai báo | Chỉ thấy "chuỗi hợp lệ" | Có | Principal tại invoke |
| `commitRequirement` | Khai báo | Có (capability + enlistment plan) | Có | Deployment, trước runtime |
| `approval` | Expression cấu trúc | Có cú pháp, **không** thấy hệ quả | Có | Caller (envelope) |
| `effects` | Danh sách declaration | Có (capability outbox) | Có | Consumer đọc trạng thái effect |
| Thân handler | Code | **Không** | Chỉ `handler_digest` | Audit, replay, migration test |
| Ngưỡng cụ thể trong `when` | Literal trong expression | Chỉ thấy "literal hợp lệ" | Có | Caller tại đúng điểm biên |

Hệ quả trực tiếp: sửa `>` thành `>=`, đổi `100_000` thành `50_000`, đổi đơn vị tiền tệ hay thu hẹp `permission` đều **pass cả ba pha**. Chúng không phải lỗi cấu hình; chúng là thay đổi ngữ nghĩa chỉ semantic diff và compat test bắt được.

### 2.2 Bảng quyết định SemVer

| # | Thay đổi | Ví dụ | Ba pha tĩnh | Consumer quan sát | SemVer |
| --- | --- | --- | --- | --- | --- |
| 1 | Sửa bug trong thân handler, contract y nguyên | Đổi cách tính `reserved`; sửa một `ctx.require` sai | Xanh; binding không đọc thân handler | Không đổi | **PATCH** |
| 2 | Đổi tên class/module host, giữ `identity` | `ApprovePurchaseOrder` → `ApprovePO`; `actions.py` → `approvals.py` | Xanh; check bám `identity` | Không đổi **nếu** tên sinh tự động suy từ `identity` | **PATCH** (ontology) |
| 3 | Thêm definition nội bộ, không export | `PurchaseOrderLineDraft` chỉ dùng trong `procurement` | Xanh | Không đổi | **PATCH** |
| 4 | Thêm `ObjectType`/`Function`/`Action` đã export | `security_audit.active_privileged_sessions` | Xanh | Thêm bề mặt, không sửa bề mặt cũ | **MINOR** |
| 5 | Thêm tham số tuỳ chọn có default | `reason: str = ""` | Link kiểm kiểu | Lời gọi cũ vẫn hợp lệ | **MINOR** |
| 6 | `1.0.0 → 1.1.0`: thêm `reads`, `calls`, `commitRequirement = ATOMIC` | `ApprovePurchaseOrder` Nấc 2 | Link xanh; binding có thể từ chối `NoSharedTransaction` | Mã envelope không đổi | **MINOR** |
| 7 | Thêm `Approval.conditional` cho action vốn đồng bộ | `1.1.0 → 2.0.0` | Xanh (cú pháp hợp lệ) | **Mã mới** `AWAITING_APPROVAL` xuất hiện | **MAJOR** |
| 8 | Đổi toán tử ngưỡng `>` → `>=` | `amount > 100_000` → `amount >= 100_000` | Xanh | Tại `amount == 100_000`: `COMMITTED` → `AWAITING_APPROVAL` | **MAJOR** |
| 9 | Đổi giá trị ngưỡng | `100_000` → `50_000` | Xanh | Tập đơn phải duyệt và tải duyệt đổi | **MAJOR** |
| 10 | Đổi đơn vị hoặc cách diễn giải tiền tệ | `Money(100_000, "USD")` → so với VND; đổi `comparisonUnit` | Xanh nếu literal hợp lệ | Cùng con số, nghĩa khác | **MAJOR** |
| 11 | Thu hẹp `permission` | `purchase_order.approve` → `purchase_order.approve_high_value` | Xanh (chuỗi hợp lệ) | Principal từng pass nay `DENIED` | **MAJOR** |
| 12 | Xoá/đổi tên identity export; xoá/đổi tên/đổi kiểu tham số bắt buộc | Bỏ `reason`; `order` → `purchaseOrder` | Link fail nếu còn tham chiếu, ngược lại xanh | Caller, SDK, automation gãy | **MAJOR** |

Tiêu chí phân loại, áp dụng cho thay đổi chưa có trong bảng:

- **MAJOR** khi một lời gọi hợp lệ hôm nay có thể nhận kết quả, mã trạng thái hoặc quyết định quyền khác đi: mã mới trong envelope, nhánh khác tại một điểm biên, `DENIED` ở chỗ trước đây pass, hoặc schema/tên tham số gãy.
- **MINOR** khi chỉ cộng bề mặt hoặc thêm nguyên nhân mới **bên trong mã đã công bố** (ví dụ thêm một lý do `REJECTED`), và consumer đang xử lý đúng envelope đã khai báo không phải sửa nhánh.
- **PATCH** khi public contract không đổi: chỉ byte của handler đổi, hoặc chỉ definition nội bộ được thêm.
- **Blast radius không đổi phân loại.** Ít đơn chạm điểm biên hay nhiều đơn chạm đều là MAJOR; độ lớn ảnh hưởng quyết định rollout (expand–contract, deprecation window), không quyết định số version.

Ghi chú riêng cho PATCH: sửa thân handler vẫn **bắt buộc** publish version PATCH mới kèm `handler_digest` mới. IR và semantic diff mù với code tuỳ ý, nên giữ nguyên số version sẽ khiến audit không phân biệt được byte đã chạy; PR phải kèm compat test và migration note cho execution đang ghim digest cũ. Tương tự, host rename giữ `identity` chỉ an toàn ở mức ontology: mọi tên consumer-facing **phải** suy từ `identity`, nếu không thì SDK/tool gãy và cần alias/deprecation một version hoặc MAJOR cho package SDK.

### 2.3 Ranh giới MINOR: ràng buộc binding và kết quả caller

`1.0.0 → 1.1.0` là ca dễ phân loại sai nhất, vì nhiều thứ mới xuất hiện cùng lúc và chúng rớt ở các cửa khác nhau. Chỉ dòng cuối của bảng chạm envelope:

| Thay đổi trong `1.1.0` | Cửa phát hiện | Ai rớt | Envelope đổi? | Phân loại |
| --- | --- | --- | --- | --- |
| `reads += Budget`, `calls += ["finance.reserve_budget"]` | Link | Không ai, nếu `Budget` và action đã export | Không | MINOR |
| `commitRequirement = ATOMIC` | Deployment binding | Deployment thiếu enlisted session chung (`NoSharedTransaction`) | Không | MINOR (điều kiện ship) |
| Child từ chối khi ngân sách không đủ | Invoke (`ctx.require` của child) | Caller nhận `REJECTED` | Không thêm mã; thêm **nguyên nhân** dưới `REJECTED` | MINOR + migration note |
| Thêm `approval` (nếu làm ở cùng bước) | Invoke | Caller nhận `AWAITING_APPROVAL` | **Có, mã mới** | MAJOR |

Cách đọc bảng này:

- **Binding từ chối không phải contract gãy.** `NoSharedTransaction` chặn deploy, không đổi ngữ nghĩa lời gọi. Contract vẫn MINOR; nhưng nếu không provider nào đáp ứng được thì thay đổi **không ship được** — hoặc đổi provider, hoặc ký contract khác (saga/outbox), và contract khác đó mới là thứ đổi kết quả quan sát được.
- **Thêm nguyên nhân `REJECTED` là MINOR theo contract, nhưng phải công bố.** Caller đúng hợp đồng đã phải xử lý `REJECTED` từ `1.0.0`; caller dựa vào quan sát "chưa bao giờ bị từ chối" là giả định ngoài hợp đồng, xử lý bằng changelog và deprecation window chứ không bằng cách nâng MAJOR.
- **Thêm mã `AWAITING_APPROVAL` là MAJOR.** Đây là khác biệt duy nhất giữa hai dòng cuối: một mã mới buộc mọi consumer thêm nhánh, kể cả consumer viết đúng hợp đồng.

### 2.4 Semantic diff mẫu

Diff cho `1.1.0 → 2.0.0` khi thêm `approval` và `effects`:

```text
Ontology: procurement
Definition: procurement.approve_purchase_order
Version: 1.1.0 -> 2.0.0 (MAJOR)
~ Action
  + approval = Approval.conditional(
        when = Param("order").normalized_amount >= Money(100_000, "USD"),
        role = "finance_director",
        self_approval = False)
  + effects  = [procurement.warehouse_order_approved@1.0.0]
    params          : order, reason                  (unchanged)
    reads           : [PurchaseOrder, Budget]        (unchanged)
    writes          : [PurchaseOrder]                (unchanged)
    calls           : ["finance.reserve_budget"]     (unchanged)
    permission      : "purchase_order.approve"       (unchanged)
    handler_digest  : sha256:4f1c...                 (unchanged)
    outcome envelope: {COMMITTED, REJECTED, DENIED, StalePlan, UNKNOWN}
                   -> {COMMITTED, AWAITING_APPROVAL, REJECTED, DENIED, StalePlan, UNKNOWN}

Detected dependents (declared graph):
  - permission reference: purchase_order.approve (policy registration)
  - generated artifacts: SDK action schema, MCP tool schema (derived from identity)
Unobservable:
  - installed SDK versions, external dashboards, human SOP, approval-queue capacity
Security-related changes: 1 (new approver authority, self_approval = False)
Potential breaking changes: 1 (new outcome code)
```

Diff cho thay đổi toán tử ngưỡng trên một `approval` đã tồn tại:

```text
Definition: procurement.approve_purchase_order
Version: v -> v+1 (MAJOR)
~ approval.when
    Param("order").normalized_amount >  Money(100_000, "USD")
 -> Param("order").normalized_amount >= Money(100_000, "USD")

  Affected boundary: normalized_amount == 100_000
    before: COMMITTED (nếu đủ quyền và budget)
    after:  AWAITING_APPROVAL (role = finance_director)
  Signature / reads / writes / calls / permission / handler_digest: unchanged
  Load / Link / deployment binding: pass
Security-related changes: 1
Potential breaking changes: 1
```

Trong chuỗi `ApprovePurchaseOrder` của bộ tài liệu này, `2.0.0` công bố `>=`; dạng `>` ở trên là mẫu tối thiểu để chứng minh semantic diff bắt được thứ ba pha tĩnh không thấy. Cùng dạng render áp dụng cho đổi giá trị ngưỡng và đổi `comparisonUnit`.

Ba tầng thông tin của diff, không được trộn:

- **Detected graph** — chỉ cạnh đã khai báo: ai `calls` identity này, policy nào reference `permission`, artifact schema nào sinh từ `identity` trong cùng lần build. Đây là thứ diff tuyên bố bao phủ.
- **Unobservable** — SDK đã cài, dashboard ngoài, SOP con người, tải duyệt thực tế. Không suy ra được từ registry hay runtime query; phải ghi rõ "chưa quan sát được" và xử lý bằng changelog, migration note, deprecation window.
- **Security flags** — thay đổi `permission`, `approval`, `self_approval`, `commitRequirement` hoặc đơn vị tiền tệ luôn gắn cờ, kể cả khi diff chỉ một dòng.

### 2.5 Rollout, execution đang treo và rollback

Version đã publish là bất biến. Rollout không sửa `2.0.0`; nó publish thêm và đổi version mặc định.

| Bước | Hành động | Bất biến phải giữ |
| --- | --- | --- |
| Publish | `2.0.0` vào registry cùng digest của handler và child revision | Nội dung một version không bao giờ bị sửa tại chỗ |
| Expand | `1.1.0` vẫn resolve trong deprecation window; invoke mới mặc định `2.0.0` | Không xoá artifact mà execution đang treo còn ghim |
| Pin | Execution mới ghim `2.0.0` + digest; execution cũ giữ manifest cũ | Không có "latest" ngầm định ở bất kỳ cửa resume nào |
| Resume | Recompute bằng đúng logic đã ghim, revalidate authorization và world state live | Không replay mutation plan cũ; không mang transaction qua approval |
| Contract | Cắt `1.1.0` khỏi resolution sau window | Artifact đã ghim vẫn đọc được cho tới khi hết retention |
| Rollback | Fallback mặc định về `1.1.0`; execution `2.0.0` đang treo vẫn chạy `2.0.0` | Không hồi tố `COMMITTED`, không tự hạ approval của pending |

Quy tắc cho execution `AWAITING_APPROVAL` xuyên rollout và rollback:

- **Không tự nâng pending lên logic mới.** Execution tạo dưới `2.0.0` resume bằng `2.0.0` kể cả khi `2.1.0` hay `3.0.0` đã publish.
- **Áp policy mới cho pending phải là migration tường minh.** Khai báo range + migration rule + reapproval; audit giữ cả manifest cũ và quyết định mới. Không có đường "duyệt lại cho tiện".
- **Material intent đổi thì reapproval.** Số tiền, `source_currency`/`target_currency`/`quote_version`, version object hoặc phạm vi child đổi so với lúc duyệt → không commit trên approval cũ.
- **Pinned artifact mất thì fail closed.** Không thay bằng version mới nhất; execution dừng và cần can thiệp, vì chạy byte khác với byte đã duyệt là vi phạm audit.
- **Rollback không mở lại quá khứ.** Execution đã `COMMITTED` giữ nguyên; pending dưới version bị rollback vẫn hoàn tất theo manifest của nó.

Ví dụ đúng tại điểm biên, dùng đúng chuỗi `>`/`>=`:

- Pending `120_000` tạo dưới logic `>` resume sau rollout `>=`: recompute bằng logic đã ghim, vẫn cần duyệt, giữ approver đã chỉ định. Không tự "nâng" sang `>=`.
- Execution mới `100_000` sau rollout ghim `2.0.0` và đi vào `AWAITING_APPROVAL`, vì `>=` bao gồm điểm biên.
- Pending `100_000` tạo dưới `>=` gặp rollback về `>`: vẫn duyệt theo `>=` đã ghim, không tự bỏ bước duyệt.

Bộ test tối thiểu đi kèm mọi thay đổi contract:

| Test | Câu hỏi | Ví dụ ở `1.1.0 → 2.0.0` |
| --- | --- | --- |
| Definition | Parse được, identity duy nhất, predicate cấu trúc | `Approval.conditional` load xanh |
| Boundary fixture | Tại đúng điểm biên, hành vi có đổi không? | `amount == 100_000`: cũ `COMMITTED`, mới `AWAITING_APPROVAL` |
| Authorization | Principal đủ/thiếu quyền tại điểm biên | Thiếu `purchase_order.approve` → `DENIED`, không tạo record |
| Consumer schema | SDK/tool schema sinh từ `identity` có đổi không? | Host rename không đổi; đổi `identity` thì gãy |
| Migration/pending | Execution cũ đọc dưới contract mới ra sao? | Pending `2.0.0` resume trên đúng digest |
| Rollback | Version fallback còn resolve và chạy đúng không? | `1.1.0` vẫn commit được sau khi `2.0.0` là default |

## 3. Kiểm chứng tái sử dụng đa miền

### 3.1 Miền chọn và tiêu chí kiểm chứng

Miền thứ hai là **cấp quyền truy cập hạ tầng nhạy cảm và tuân thủ bảo mật** (`access_control` + `security_audit`). Nó được chọn vì khác Procurement/Finance ở mọi thứ trừ hình dạng khai báo:

- Đại lượng so sánh là **thời lượng**, không phải tiền: `Duration` với `comparisonUnit = "min"`.
- Authority là **security officer** cho phiên đặc quyền có thời hạn, không phải finance director cho hạn mức chi.
- Nghiệp vụ là **break-glass khẩn cấp**, nơi thời gian và audit quan trọng hơn giá trị giao dịch.
- Có **hai module ghi nguyên tử** (`access_control` + `security_audit`), một effect cấp chứng chỉ ngắn hạn, và predicate duyệt hai nhánh (`or`).

Một miền chỉ được tính là kiểm chứng hợp lệ nếu hội đủ: danh từ nghiệp vụ khác, một Value có đơn vị khác, role khác, một cạnh liên module nguyên tử, một effect sau commit, và một predicate duyệt không phải so sánh đơn giản.

### 3.2 Module, Value, ObjectType và Link

```python
# access_control/model.py
class AccessControlModule(Module):
    identity = "access_control"
    version = "1.0.0"
    exports = [AccessGrantRequest, ProductionCluster, GrantBreakGlassAccess]


class Duration(Value):
    """Khoảng thời gian có đơn vị tường minh; so sánh theo comparisonUnit."""

    value: int
    unit: Literal["s", "min", "h"]
    comparisonUnit = "min"


class ProductionCluster(ObjectType):
    identity = "access_control.production_cluster"
    version = "1.0.0"
    keyType = "PC"

    name: str
    region: str
    tier: Literal["STANDARD", "CRITICAL"]
    requests: Link[AccessGrantRequest, "many", "internal"]


class AccessGrantRequest(ObjectType):
    identity = "access_control.access_grant_request"
    version = "1.0.0"
    keyType = "AGR"

    status: Literal["PENDING", "GRANTED", "CANCELLED"]
    environment: Literal["STAGING", "PROD", "PROD_CRITICAL"]
    requested_duration: Duration          # so sánh theo comparisonUnit = "min"
    reason: str

    cluster: Link[ProductionCluster, "one", "navigable"]
    session: Link[PrivilegedSession, "one", "navigable"]   # cạnh sang security_audit
```

`Duration` chiếm đúng chỗ `Money` chiếm ở Procurement: một `Value` không có vòng đời riêng, có đơn vị, được so sánh trong ngưỡng. Khác biệt duy nhất là quy đổi đơn vị thời gian **chính xác** (`1 h = 60 min`), nên không cần `quote_version`; `Money` khác currency vẫn phải ghi `source_currency` + `target_currency` + `quote_version`. Core không biết `Duration` hay `Money`; nó chỉ biết "Value có `comparisonUnit` khai báo".

Hai module tham chiếu kiểu của nhau (`access_control` link sang `PrivilegedSession`, `security_audit` link ngược sang `ProductionCluster`). Điều này hợp lệ vì annotation là chuỗi và registry resolve ở pha Link; module thứ hai chỉ import module đầu dưới `TYPE_CHECKING`. Không có import vòng ở runtime, và cũng không cần AST (mục 4.1).

### 3.3 Module audit: Function đọc và action con mức 1

```python
# security_audit/model.py
class SecurityAuditModule(Module):
    identity = "security_audit"
    version = "1.0.0"
    exports = [PrivilegedSession, RecordPrivilegedSession, ActivePrivilegedSessions]


class PrivilegedSession(ObjectType):
    identity = "security_audit.privileged_session"
    version = "1.0.0"
    keyType = "PS"

    session_status: Literal["RESERVED", "OPEN", "CLOSED", "EXPIRED"]
    ttl: Duration
    justification: str
    principal_id: str

    cluster: Link[ProductionCluster, "one", "internal"]


class ActivePrivilegedSessions(Function):
    """Read-only: số phiên đặc quyền còn hiệu lực trên một cluster."""

    identity = "security_audit.active_privileged_sessions"
    version = "1.0.0"
    cluster: ObjectRef[ProductionCluster]
    result = int

    def evaluate(self, ctx, cluster: ProductionCluster) -> int:
        ...


class RecordPrivilegedSession(Action):
    """Ghi nhận phiên đặc quyền; security_audit sở hữu mutation trên PrivilegedSession."""

    identity = "security_audit.record_privileged_session"
    version = "1.0.0"

    session: ObjectRef[PrivilegedSession]
    grant: ObjectRef[AccessGrantRequest]
    justification: str
    ttl: Duration

    reads = [PrivilegedSession, AccessGrantRequest]
    writes = [PrivilegedSession]
    permission = "security_audit.record_privileged_session"

    def handler(self, ctx, session: PrivilegedSession, grant: AccessGrantRequest,
                justification: str, ttl: Duration):
        ctx.require(session.session_status == "RESERVED", reason="session_not_reserved")
        ctx.require(grant.status == "PENDING", reason="grant_not_pending")

        ctx.uow.register_mutation(
            session,
            session_status="OPEN",
            ttl=ttl,
            justification=justification,
            expectedVersion=session.version,
        )
        return {"session": session.ref, "status": "OPEN"}
```

Action con không khai báo `commitRequirement`: nó là child, atomicity thuộc về parent đã gọi nó. Đây đúng quy ước Nấc 2, chỉ đổi danh từ.

### 3.4 Action cha mức 3: approval, atomic, effect

```python
# access_control/actions.py
class BastionCertPayload(Value):
    grant: ObjectRef[AccessGrantRequest]
    cluster: ObjectRef[ProductionCluster]
    session: ObjectRef[PrivilegedSession]
    ttl: Duration


class ProvisionEphemeralBastionCert(Effect):
    identity = "access_control.provision_ephemeral_bastion_cert"
    version = "1.0.0"
    payload = BastionCertPayload
    dedupKey = ("grant",)


class GrantBreakGlassAccess(Action):
    identity = "access_control.grant_break_glass_access"
    version = "1.0.0"

    request: ObjectRef[AccessGrantRequest]
    justification: str

    reads = [AccessGrantRequest, ProductionCluster, PrivilegedSession]
    writes = [AccessGrantRequest]
    calls = ["security_audit.record_privileged_session"]
    permission = "access.grant_break_glass"
    commitRequirement = CommitRequirement.ATOMIC

    approval = Approval.conditional(
        when=(Param("request").requested_duration >= Duration(60, "min"))
        | (Param("request").environment == "PROD_CRITICAL"),
        role="security_officer",
        self_approval=False,
    )
    effects = [ProvisionEphemeralBastionCert]
```

Predicate duyệt dùng đúng tập toán tử cấu trúc đã chốt: so sánh trên Value có đơn vị và `or` giữa hai nhánh. Không lambda, không method call, không `getattr`.

Action mới sinh ra ở mức đầy đủ, không phải leo thang từ mức 1. Điều này không vi phạm progressive disclosure: khai báo vẫn chỉ gồm các thuộc tính đã có, và một action đơn giản khác trong cùng miền vẫn chỉ cần `identity`, `params`, `reads`, `writes`, `permission`, `handler`.

### 3.5 Handler của action cha

```python
    def handler(self, ctx, request: AccessGrantRequest, justification: str):
        ctx.require(request.status == "PENDING", reason="grant_request_not_pending")
        ctx.require(bool(justification.strip()), reason="justification_required")

        cluster = ctx.resolve(request.cluster)     # ObjectRef[ProductionCluster]
        session = ctx.resolve(request.session)     # ObjectRef[PrivilegedSession]
        ctx.call(
            "security_audit.record_privileged_session",
            session=session,
            grant=request,
            justification=justification,
            ttl=request.requested_duration,
        )

        ctx.uow.register_mutation(
            request,
            status="GRANTED",
            expectedVersion=request.version,
        )
        ctx.uow.enqueue_effect(
            ProvisionEphemeralBastionCert,
            payload=BastionCertPayload(
                grant=request.ref,
                cluster=cluster.ref,
                session=session.ref,
                ttl=request.requested_duration,
            ),
        )
        return {"request": request.ref, "session": session.ref, "status": "GRANTED"}
```

Handler chỉ dùng năm cửa đã chốt (`require`, `resolve`, `call`, `register_mutation`, `enqueue_effect`). Không có nhánh duyệt, không có state "đã duyệt", không đọc clock để tính hết hạn, không gọi PKI. "Break-glass" không phải chế độ của engine: nó là approval cộng audit cộng TTL ngắn, và engine không có đường bỏ qua approval.

### 3.6 Trace consumer: `query → ObjectRef → invoke → approve`

```python
page = engine.query(
    principal=oncall_sre,
    from_="AccessGrantRequest",
    predicate=(status == "PENDING") & (environment == "PROD_CRITICAL"),
    limit=20,
)
request_ref = page.rows[0].as_ref()        # ObjectRef[AccessGrantRequest]

attempt = engine.invoke(
    principal=oncall_sre,
    action="access_control.grant_break_glass_access",
    parameters={"request": request_ref, "justification": "SEV-1 INC-4412"},
    request_key="tenant-A:sre7:grant:AGR-0042:001",
    intent_fingerprint=canonical_hash(
        action="access_control.grant_break_glass_access",
        version="1.0.0",
        params={"request": request_ref, "justification": "SEV-1 INC-4412"},
    ),
)
# attempt.code == "AWAITING_APPROVAL"
# attempt.execution.required_approval.role == "security_officer"
# attempt.execution.required_approval.self_approval is False

decision = engine.approve(
    principal=security_officer,
    execution_id=attempt.execution.execution_id,
    callback_key=(f"{attempt.execution.execution_id}:"
                  f"{attempt.execution.required_approval.approval_id}"),
    expected_intent_fingerprint=attempt.intent_fingerprint,
    decision="APPROVE",
    reason="change window CHG-8891 confirmed",
)
# decision.code == "COMMITTED"
# decision.execution.effects == (
#     EffectStatus("access_control.provision_ephemeral_bastion_cert", "PENDING"),)
```

Cùng ma trận kết quả, chỉ đổi danh từ:

| Mã | Nguồn trong miền này | Consumer làm gì |
| --- | --- | --- |
| `COMMITTED` | Request `GRANTED`, session `OPEN`, outbox row cùng transaction | Hiện grant; chờ effect cấp chứng chỉ |
| `AWAITING_APPROVAL` | `requested_duration >= 60 min` hoặc `environment == "PROD_CRITICAL"` | `security_officer` gọi `approve`; không ghi gì trước đó |
| `DENIED` | Thiếu `access.grant_break_glass`, hoặc requester tự duyệt khi `self_approval=False` | Xin quyền; đổi approver; không sửa handler |
| `REJECTED` | Request không `PENDING`, justification rỗng, session không `RESERVED` | Sửa dữ liệu nghiệp vụ, key mới |
| `StalePlan` | Version request/session lệch lúc revalidate | Query lại, recompute fingerprint |
| `UNKNOWN` | Mất phản hồi sau commit | `reconcile`; không sinh key mới |

### 3.7 Bảng ánh xạ primitive 1-1

| Primitive | Procurement / Finance | Access / Security | Cùng slot khai báo? |
| --- | --- | --- | --- |
| `Module` | `procurement`, `finance` | `access_control`, `security_audit` | Có — `identity`, `version`, `exports` |
| `ObjectType` | `PurchaseOrder`, `Budget` | `AccessGrantRequest`, `ProductionCluster`, `PrivilegedSession` | Có — `identity`, `keyType`, property, link |
| `Property` | `status`, `amount` | `status`, `environment`, `requested_duration` | Có — kiểu tường minh, `required` khi cần |
| `Value` + `comparisonUnit` | `Money(amount, currency)` | `Duration(value, "min")` | Có — Value có đơn vị, không vòng đời |
| `Link` | `PurchaseOrder.budget → Budget` | `AccessGrantRequest.cluster → ProductionCluster` | Có — `cardinality`, `traversal` |
| `ObjectRef[T]` | `order`, `budget` | `request`, `cluster`, `session` | Có — tham chiếu có kiểu |
| `Function` | `finance.remaining_budget` | `security_audit.active_privileged_sessions` | Có — read-only, không approval/effect |
| `Action` | `ApprovePurchaseOrder`, `ReserveBudget` | `GrantBreakGlassAccess`, `RecordPrivilegedSession` | Có — `params`, `reads`, `writes`, `calls`, `handler` |
| `Approval.conditional` | `normalized_amount >= Money(100_000, "USD")`, role `finance_director` | `requested_duration >= Duration(60, "min")` hoặc `environment == "PROD_CRITICAL"`, role `security_officer` | Có — `when`, `role`, `self_approval` |
| `CommitRequirement.ATOMIC` | `PurchaseOrder` + `Budget` | `AccessGrantRequest` + `PrivilegedSession` | Có — binding kiểm enlisted session |
| `Effect` | `NotifyWarehouseOrderApproved` | `ProvisionEphemeralBastionCert` | Có — payload Value, dedup key, outbox |
| `HandlerCtx` | `require`/`resolve`/`call`/`register_mutation`/`enqueue_effect` | Cùng năm cửa | Có — không thêm cửa nào |
| Envelope consumer | `COMMITTED`, `AWAITING_APPROVAL`, `DENIED`, `REJECTED`, `StalePlan`, `UNKNOWN` | Cùng sáu mã | Có — cùng ma trận hành động |

Không có dòng nào cần primitive mới. Cái đổi giữa hai miền là **dữ liệu**: identity, tên property, đơn vị Value, tên role, ngưỡng, payload effect.

### 3.8 Cái gì bị giữ ngoài core

- **Từ vựng miền:** `PROD_CRITICAL`, `security_officer`, ngưỡng 60 phút, chính sách dual-control. Chúng là literal trong declaration, không phải kiểu trong core.
- **Tuân thủ và lưu trữ:** retention của audit record, WORM storage, chứng thực PKI, kỳ hạn chứng chỉ. Thuộc provider/effect, không thuộc meta-model.
- **Vận hành khẩn cấp:** paging, escalation, thông báo on-call. Effect hoặc hệ ngoài; handler không gọi.
- **"Break-glass" như một chế độ:** không tồn tại. Nếu một ngày ai đó thêm `bypassApproval=True` vào core, đó là phá vỡ mô hình, không phải tính năng của miền này.
- **Quy đổi đơn vị phức tạp:** tháng/năm dương lịch không có độ dài cố định. Miền nào cần thì tự khai báo `comparisonUnit` và chính sách quy đổi; core không đoán.

### 3.9 Kết luận kiểm chứng

- Author Contract dùng lại **nguyên vẹn**: không thuộc tính nào của Action phải thêm, bớt hay đổi nghĩa.
- Consumer Contract dùng lại **nguyên vẹn**: cùng sáu mã, cùng ngữ nghĩa `DENIED`/`REJECTED`/`StalePlan`/`UNKNOWN`, cùng luật effect sau commit.
- Tính chất "không may đo" được chứng minh bằng phép thử đảo: thay toàn bộ danh từ Procurement bằng danh từ hạ tầng, khai báo vẫn hợp lệ và vẫn qua Load/Link/binding khi provider đáp ứng.
- Phần duy nhất phải viết mới là **nghiệp vụ**: predicate, ngưỡng, payload, role. Đó chính là phần thuộc về domain, không thuộc framework.

## 4. Khuyến nghị biểu diễn khai báo Python đầu tiên

### 4.1 Ràng buộc đầu vào

Bề mặt khai báo phải thỏa đồng thời:

- Tạo được meta-model graph **không cần AST, bytecode hay phân tích import** — mọi thứ cần thiết nằm trong namespace của definition.
- `identity` là nguồn duy nhất của tên consumer-facing; tên class chỉ là host name.
- Annotation cross-module resolve **lazy** ở pha Link, để hai module link kiểu của nhau mà không import vòng.
- Progressive disclosure: ca đơn giản không phải khai báo gì thêm cho có lệ; ca phức tạp chỉ cộng thuộc tính.
- Pyright strict đọc được: sai kiểu tham số, sai kiểu Value, sai kiểu payload effect phải là lỗi tĩnh của editor, không phải lỗi runtime.

### 4.2 Ứng viên A — class-based declarative schema (khuyến nghị)

```python
class GrantBreakGlassAccess(Action):
    identity = "access_control.grant_break_glass_access"
    version = "1.0.0"

    request: ObjectRef[AccessGrantRequest]
    justification: str

    reads = [AccessGrantRequest, ProductionCluster, PrivilegedSession]
    writes = [AccessGrantRequest]
    calls = ["security_audit.record_privileged_session"]
    permission = "access.grant_break_glass"
    commitRequirement = CommitRequirement.ATOMIC
    approval = Approval.conditional(...)
    effects = [ProvisionEphemeralBastionCert]

    def handler(self, ctx, request: AccessGrantRequest, justification: str):
        ...
```

Cơ chế, không có phép thuật:

- `Action.__init_subclass__` chạy **một lần** lúc class được tạo, đọc namespace: các key khai báo, annotation dạng chuỗi, và callable `handler`. Kết quả là một `ActionDecl` frozen, gắn vào `cls.__decl__`.
- Không instantiate để lấy metadata; không đọc source; không import module khác lúc capture.
- Annotation được resolve ở pha Link bằng `typing.get_type_hints(..., include_extras=True)` trên snapshot đã compose, nên forward ref và vòng kiểu cross-module hoạt động.
- `params` lấy từ chữ ký `handler`; kiểu khai báo ở thân class là kiểu **contract** (`ObjectRef[T]`), kiểu trong handler là kiểu **đã resolve** (`T`). Lệch tên, arity hoặc cặp kiểu này là lỗi Link, không phải lỗi runtime.
- Engine gọi handler trên một instance metadata dùng chung; instance không mang state execution. Cấm override `__init__` hoặc dùng thuộc tính instance làm state.
- Key lạ trong thân class (`readz = [...]`) bị Load từ chối; không có chuyện typo biến thành thuộc tính nội bộ im lặng.

Chọn `def handler(self, ctx, ...)` thay vì `@staticmethod def handle(ctx, ...)`: giữ đúng một quy ước, khớp toàn bộ ví dụ đã publish, và không tạo hai tên cho cùng một khái niệm. `self` không mang state; nó chỉ là hệ quả của việc definition là một class.

### 4.3 Ứng viên B — decorator/function-builder DSL

```python
@action(
    identity="access_control.grant_break_glass_access",
    version="1.0.0",
    reads=[AccessGrantRequest, ProductionCluster, PrivilegedSession],
    writes=[AccessGrantRequest],
    calls=["security_audit.record_privileged_session"],
    permission="access.grant_break_glass",
    commit_requirement=CommitRequirement.ATOMIC,
    approval=Approval.conditional(...),
    effects=[ProvisionEphemeralBastionCert],
)
def grant_break_glass_access(
    ctx: HandlerCtx,
    request: Annotated[AccessGrantRequest, ObjectRef],
    justification: str,
) -> GrantResult:
    ...
```

Điểm mạnh thật:

- Boilerplate thấp cho `Function`/`Effect` nhỏ; không cần class rỗng.
- Keyword sai bị Python báo ngay, không cần check key lạ.
- Gắn được lên hàm có sẵn của team domain mà không đổi hình dạng code.

Điểm phải trả giá:

- Metadata tách khỏi implementation: hợp đồng nằm ở decorator, hành vi ở thân hàm. Review và diff phải đọc hai nơi.
- Để giữ một chữ ký duy nhất, kiểu contract phải nhét vào `Annotated[T, ObjectRef]` — một quy ước typing mới, dễ sai và khó đọc hơn cặp annotation/handler của A.
- Để Pyright giữ đúng kiểu qua decorator cần overload/`ParamSpec`; nếu không, lỗi kiểu tham số biến mất khỏi editor.
- Builder dạng chuỗi (`Action("x").reads(...).build()`) là mutable và không diff được như một khối khai báo.

Repo đã từng có dạng lai (`@action(...)` trên một class) trong tài liệu nền. Dạng lai bị loại vì chia cùng một contract ra hai bề mặt, đúng lỗi mà B mắc phải, cộng thêm chi phí class của A.

### 4.4 So sánh trực tiếp

| Tiêu chí | A — class-based | B — decorator/function | Chọn |
| --- | --- | --- | --- |
| Tạo graph không AST | `__init_subclass__` đọc namespace | Decorator đọc tham số và hàm | Hòa |
| Pyright strict | Annotation class + chữ ký handler, tự nhiên | Cần `Annotated` + overload để giữ kiểu | **A** |
| Progressive disclosure | Cộng thuộc tính trong một khối | Cộng keyword, dễ phình | **A** |
| Review/diff | Contract nằm một chỗ, cạnh handler | Contract và handler tách đôi | **A** |
| Key lạ / typo | A phải tự check key lạ ở Load | Python báo ngay | **B** (nhẹ hơn) |
| Chi phí ca nhỏ | Class tối thiểu vài dòng | Ngắn hơn cho Function/Effect | **B** |
| Registry collection | `__decl__` trên class, dễ đếm và chặn trùng | Thuộc tính trên function, tương đương | Hòa |
| Rủi ro khóa cú pháp | Chỉ khóa cách dựng `ActionDecl` | Tương tự | Hòa |

### 4.5 Khuyến nghị và tiêu chí đổi lựa chọn

**Chọn A** cho `declarations/` và `registry/` phiên bản đầu. Lý do quyết định: contract nhìn thấy được ở một chỗ, kiểu contract và kiểu resolved tách bạch mà không cần quy ước `Annotated`, và registry có một artifact rõ ràng (`cls.__decl__`) để chặn trùng identity, kiểm export và tính digest.

Điều khuyến nghị này **không** khóa: nó chốt `ActionDecl`/`ObjectTypeDecl`/... là IR bất biến, không chốt cú pháp Python. Bất kỳ bề mặt nào khác chỉ cần dựng đúng IR đó.

Tiêu chí đổi lựa chọn, phải quan sát được:

- Nếu ≥50% declaration là `Function`/`Effect` ngắn và chi phí class boilerplate đo được làm chậm authoring rõ rệt → thêm **adapter decorator chỉ cho `Function`/`Effect`**, vẫn emit cùng IR. Không mở bề mặt thứ hai cho `Action`.
- Nếu team domain bắt buộc phải gắn declaration lên hàm có sẵn, không được viết lại thành class → B được phép như adapter, với điều kiện IR và compat test giống hệt A.
- Nếu CI chứng minh decorator không giữ được kiểu tham số (`reveal_type` lệch) → B không đủ điều kiện làm bề mặt chính.
- Nếu một nguồn khai báo phi Python (YAML, MCP-generated) trở thành chính → A và B đều thành emitter; IR không đổi.
- Nếu bắt buộc phải kế thừa base class để tái dùng `reads`/`permission` → dừng lại: kế thừa thuộc tính contract làm hợp đồng vô hình. Chỉ cho phép base rỗng làm marker, bất kể A hay B.

### 4.6 Ánh xạ vào `declarations/` và `registry/`

```text
codology/
  declarations/
    base.py        # Module, ObjectType, Value, Link, Function, Action, Effect
    expression.py  # Param + toán tử cấu trúc (không nhận Python callable)
    approval.py    # Approval.conditional
    values.py      # Money, Duration: helper Value có đơn vị (hoặc khai báo trong miền), KHÔNG phải core primitive
  registry/
    collect.py     # import module khai báo, gom __decl__, DuplicateIdentity
    link.py        # export, reference, param/handler alignment, resolve annotation
    snapshot.py    # snapshot bất biến, IR chuẩn hoá, handler digest
    introspect.py  # chiếu IR cho semantic diff và generator SDK/MCP
```

Luật của lớp này:

- Package Python gốc là `codology`; `declarations/` và `registry/` là các package con dự kiến cho Sprint 3. Tên gọi *Ontology as Code* (OaC) vẫn dùng cho khái niệm, không phải tên package.
- `declarations/` không import `registry/`, `engine/`, adapter hay backend.
- `registry/` không chạy handler và không đọc dữ liệu nghiệp vụ; nó chỉ đọc declaration.
- `Money`/`Duration` có thể ship ở `values.py` hoặc khai báo trong miền như mục 3.2; cả hai đều là Value thường, không phải core primitive. Miền tự định nghĩa Value của mình vẫn hợp lệ nếu có `comparisonUnit`.
- Mọi tên sinh cho consumer (SDK, MCP tool, URL) suy từ `identity`, không từ `cls.__name__`.

### 4.7 Checklist bàn giao cho giai đoạn triển khai

- Tạo class definition trả về `*Decl` frozen; sửa sau khi tạo phải raise.
- Load chặn trùng `identity`, key khai báo lạ, predicate không cấu trúc.
- Link chặn reference thiếu export, annotation không resolve, lệch kiểu `ObjectRef[T]` với chữ ký handler.
- Snapshot expose IR đủ để tính semantic diff `>` → `>=` và `handler_digest` của đúng byte đã publish.
- Generator tên consumer chỉ đọc `identity`; có test khẳng định host rename không đổi output.
- Negative test bắt buộc: trùng identity, thiếu export, lệch param/handler, lambda trong `when`, hai class cùng host name ở hai module.
- Không có API nào cho phép đọc `latest` ngầm định; resolver chỉ trả version được chỉ định hoặc version mặc định đã công bố.

## 5. Ranh giới và liên kết

- Không nằm ở đây: cú pháp cuối cùng của từng primitive, tập đầy đủ toán tử predicate, và cấu trúc artifact publish. Ba thứ đó thuộc giai đoạn triển khai `declarations/` + `registry/`.
- Không thêm primitive: mục 3 chỉ dùng lại meta-model v0.1; mục 4 chỉ chọn cách dựng IR, không mở rộng IR.

- [Developer Contract](./developer-contract.md) — khai báo author, `HandlerCtx`, scoped UoW, `approval`, `effects` và ma trận lỗi Load/Link/binding.
- [Consumer Contract](./consumer-contract.md) — `query`/`invoke`/`approve`/`reconcile`, envelope và ma trận hành động cho từng mã kết quả.
- [Framework Design v0.1](./framework-design-v0.1.md) — meta-model, pin manifest, idempotency, strict atomic và thứ tự thực hiện.
- [Architecture Direction](./architecture-direction.md) — module sở hữu nghiệp vụ, quyền không tự tăng qua ranh giới.
- [Developer Workflow and Model Evolution](../deep-dives/02-developer-workflow-and-model-evolution.md) — ngưỡng `>`/`>=`, tiền tệ, host rename và SDK caveat.
- [Static Architecture and Definition Lifecycle](../deep-dives/01-static-architecture-and-definition-lifecycle.md) — load/link/binding, identity vs host name, exports.
- [Engine Boundary and Adapter Capabilities](../deep-dives/04-engine-boundary-and-adapter-capabilities.md) — enlistment, outbox/relay và `NoSharedTransaction`.
