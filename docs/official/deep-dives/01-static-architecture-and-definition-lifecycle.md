# Static Architecture and Definition Lifecycle

*Tài liệu deep-dive 01 — Static architecture & meta-model. Phạm vi: chương chính thức 04 (§13–16), 05 (§17–25), 06 (§26–34). Ví dụ xuyên suốt: `ApprovePurchaseOrder` dùng chung giữa Procurement và Finance.*

*Quy ước đọc: mỗi mục ghi rõ nguồn của khẳng định — **[Nguồn]** = bằng chứng đã kiểm chứng từ tài liệu sơ cấp; **[Đề xuất OaC]** = quyết định thiết kế do tài liệu này đề xuất, chưa chốt; **[Câu hỏi mở]** = việc cần phase sau hoặc thí nghiệm trả lời.*

## Executive Summary and Recommended Approach

**[Đề xuất OaC]** Khuyến nghị chính của tài liệu này:

1. Mỗi definition mang một **identity ổn định** (`procurement.approve_purchase_order`), tách khỏi **host name** (tên class Python `ApprovePurchaseOrder` trong module `procurement.actions`).

2. Mọi phụ thuộc mà static layer cần biết phải được **khai báo tường minh với kiểu** (`reads`, `writes`, `ObjectRef[T]`, tham số Action) — không suy ra từ việc đọc thân handler.

3. Kiểm tra theo ba pha **load → bind → invoke**, mỗi pha từ chối lỗi thuộc về mình thay vì dồn xuống runtime.

4. Bắt đầu bằng **in-process registry** làm source of truth; xuất **canonical IR (JSON)** có version chỉ khi một trong các decision trigger kích hoạt. Introspection trực tiếp từ registry đang sống (kể cả cho MCP server) và diff bằng cách import hai revisions không yêu cầu file IR độc lập.

Giới hạn của khuyến nghị này được phân tích ở mục Counterexample (gồm phản ví dụ live introspection và giới hạn AST/IR), và các giả định — cùng các giả thuyết cần kiểm chứng — bàn giao cho phase 2 ở mục Handoff.

## Minimal Declaration and Typed Dependencies

### Khung ví dụ: ApprovePurchaseOrder liên domain

**[Nguồn]** Theo §28, Action gồm ba phần tách biệt: Action Definition (declarative contract), Action Engine (framework), Action Implementation (developer). Theo §34, khi Procurement gọi sang Finance (ví dụ `ApprovePurchaseOrder` cần `ReserveBudget` của Finance), đó là governed operation composition, không phải function call thuần túy — cần trả lời authorization, principal propagation, transaction, audit ngay ở mức contract.

**[Nguồn]** Theo §27, một Action phải trả lời được: identity, parameters, target objects, read scope, write scope, handler, mutation plan, approval, transaction, idempotency, failure semantics. Theo §26, `ApprovePurchaseOrder` không đơn thuần là `order.status = "APPROVED"` mà phải qua budget, supplier, role, approval, concurrency, transaction.

**[Đề xuất OaC]** Khai báo tối thiểu, chỉ giữ những gì static layer kiểm tra được:

```python
# procurement/actions.py
class ApprovePurchaseOrder(Action):
    """Tên hiển thị cho human và AI."""

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

```python
# finance/actions.py
class ReserveBudget(Action):
    """Thuộc domain Finance, được Procurement gọi tới."""

    identity = "finance.reserve_budget"
    version = "1.0.0"

    budget: ObjectRef[Budget]
    amount: Money

    reads = [Budget]
    writes = [Budget]

    permission = "budget.reserve"
```

Điểm cố ý tối thiểu:

- Không có `validate`/`handler` trong ví dụ này vì thân handler thuộc implementation, không thuộc static contract (§28 phân biệt Definition vs Implementation).
- `reads`/`writes` liệt kê Object Type, không liệt kê property — property-level scope là việc của phase sau (query-time security, §39).
- Cạnh `calls` là dependency liên domain được khai báo tường minh, không phải import Python ngầm — xem mục Undeclared Handler Dependencies.
- Trong ví dụ này, parent ghi trực tiếp `PurchaseOrder.status`; `finance.reserve_budget` sở hữu mutation trên `Budget`. Hai Action khai báo cùng một Object Type trong `writes` không tự thân là lỗi: chúng có thể ghi hai instance khác nhau. Cần xét invariant, đối tượng thực tế và cơ chế concurrency trước khi kết luận có xung đột.

### Vì sao phụ thuộc phải có kiểu

**[Nguồn]** Tài liệu Pydantic — Models xác nhận: model định nghĩa field bằng annotated attribute, dữ liệu không tin cậy đi qua validation thì instance kết quả được đảm bảo conform với kiểu đã khai báo; nếu không parse được, `ValidationError` được raise.

- [Pydantic — Models](https://pydantic.dev/docs/validation/latest/concepts/models/)

**[Nguồn]** Tài liệu SQLAlchemy — Mapping Classes with Declarative cho thấy pattern code-first đã thành công: class Python + annotation ánh xạ thành metadata trong registry, engine dùng metadata đó thay vì đọc thân code.

- [SQLAlchemy — Mapping Classes with Declarative](https://docs.sqlalchemy.org/en/20/orm/declarative_mapping.html)

**[Đề xuất OaC]** Áp dụng cùng nguyên tắc: `ObjectRef[PurchaseOrder]` là tham số có kiểu — static layer kiểm tra được `PurchaseOrder` tồn tại và `order` ở invoke-time phải resolve ra đúng type. Khai báo `reads` chỉ nói *định chạm gì*, không đồng nghĩa *được phép chạm*: quyền thực tế phụ thuộc principal tại invoke-time (authorization và query-time security thuộc governance, ngoài phạm vi tài liệu này). `str` trần cho `order` sẽ mất toàn bộ khả năng kiểm tra này.

## Identity versus Host Names

### Hai loại tên, hai vòng đời khác nhau

**[Nguồn]** Kubernetes — Object Names and IDs phân biệt rạch ròi: mỗi object có **Name** (client-provided, duy nhất trong phạm vi kind + namespace, có thể tái sử dụng sau khi xóa) và **UID** (system-generated, duy nhất toàn cluster trong toàn bộ vòng đời, dùng để phân biệt các lần tồn tại lịch sử của thực thể cùng tên).

- [Kubernetes — Object Names and IDs](https://kubernetes.io/docs/concepts/overview/working-with-objects/names/)

**[Nguồn]** Palantir — Create an object type: mỗi object type có **ID** (chữ thường, số, gạch nối; ký tự đầu phải là chữ thường) dùng để reference từ application, tách khỏi **display name**; đổi property ID sau khi đã reference sẽ **gãy application**. Primary key phải duy nhất, deterministic; đổi primary key xóa toàn bộ edits gắn với key cũ.

- [Palantir — Create an object type](https://www.palantir.com/docs/foundry/object-link-types/create-object-type)

**[Nguồn]** Palantir — SuperRepo Core concepts: Ontology-as-code là source of truth, TypeScript definitions được compile và materialize thành entities thật; SDK bindings (OSDK) được sinh tự động từ definitions; entity đã tồn tại được import bằng `foundry import ontology` kèm lock file để code generation dựa vào.

- [Palantir — SuperRepo Core concepts](https://www.palantir.com/docs/foundry/superrepo/core-concepts/)

**[Đề xuất OaC]** Áp dụng cho OaC:

- **Identity** (`procurement.approve_purchase_order`, `sales.customer`): ổn định, có namespace domain, là thứ execution record (§30), audit, consumer contract và cross-domain reference bám vào. Đổi identity = breaking change.
- **Host name** (`ApprovePurchaseOrder` trong `procurement/actions.py`): tên class/module Python, phục vụ developer ergonomics, refactor thoải mái miễn identity không đổi.
- **Display name** (`"Approve Purchase Order"`): cho human/AI discovery (§27), không dùng để reference.

Bảng đối chiếu:

| Khái niệm OaC | Tương đương đã kiểm chứng | Tính chất mượn được |
| --- | --- | --- |
| Identity (mức definition) | Palantir object type ID | Ổn định, duy nhất, đổi là gãy consumer |
| Host name | K8s Name; Python qualified name | Tiện cho con người, tái dùng được, refactor được |
| Display name | Palantir title key / display name | Chỉ để hiển thị, không reference |

**Thu hẹp hai analogy (tránh suy rộng quá mức):**

- Khai báo `reads` ≠ được cấp quyền. `reads = [Budget, ...]` chỉ tuyên bố *định đọc gì* để static layer kiểm tra tồn tại/kiểu/export; quyền đọc thực tế của từng principal do authorization và query-time security quyết định ở invoke-time. Analogy với Pydantic dừng ở "kiểu được kiểm tra", không mở rộng thành "quyền được cấp".
- K8s UID ≠ OaC definition identity. UID định danh một *instance runtime* trong vòng đời cluster; identity OaC định danh một *definition* xuyên suốt các triển khai và version. Mượn từ K8s chỉ là hai tính chất ổn định + duy nhất toàn cục; tiền lệ gần hơn cho definition identity là Palantir object type ID (định danh mức định nghĩa, đổi là gãy consumer — nguồn đã dẫn ở trên).

### Quy tắc đặt identity

**[Đề xuất OaC]** `<domain>.<snake_name>`, chữ thường, ví dụ `procurement.approve_purchase_order`. Domain = Module (§18). Version đi kèm identity trong execution record (`actionVersion`, `ontologyVersion` — §30), không nhúng version vào identity.

## Exported versus Internal Contracts

### Vấn đề

**[Nguồn]** Chương 04 (§16) nêu: framework sở hữu type system và semantics, developer sở hữu business objects. Nhưng chưa có nội dung nào trong 04–06 trả lời: consumer ngoài domain thấy được gì, cái gì là nội bộ. §23 đặt câu hỏi interface là structural hay behavioral contract nhưng chưa chốt.

### Tiền lệ từ Python

**[Nguồn]** Python Tutorial — Modules: `from fibo import *` import mọi tên **trừ tên bắt đầu bằng gạch dưới**; import `*` nói chung bị xem là kém vì đưa một tập tên không rõ vào interpreter.

- [Python Tutorial — Modules](https://docs.python.org/3/tutorial/modules.html)

**[Đề xuất OaC]** Mượn đúng hai cơ chế này cho ontology module:

- Mọi definition mặc định là **internal** với domain của nó, trừ khi được liệt kê trong `exports` của module.
- Chỉ definition **exported** mới được domain khác reference (ví dụ Procurement reference `finance.reserve_budget` chỉ hợp lệ nếu Finance export nó), mới sinh SDK/consumer contract, và mới chịu ràng buộc tương thích.

```python
# finance/module.py
class FinanceModule(Module):
    """Domain Finance."""

    identity = "finance"
    exports = [Budget, ReserveBudget]
```

`FinancialPolicy` (quy tắc nội bộ Finance, §34) không export → Procurement không được reference trực tiếp; muốn dùng phải qua `ReserveBudget` đã export. Đây là cách biến "domain sở hữu operation và contract" (§34) thành quy tắc kiểm tra được ở pha bind.

## Undeclared Handler Dependencies — Caveat

### Cảnh báo trung tâm của tài liệu này

**[Đề xuất OaC]** Static layer **chỉ tin những gì được khai báo** (`reads`, `writes`, tham số có kiểu). Bất cứ thứ gì handler chạm tới mà không khai báo — `ctx.resolve()` thêm một object, import lén một domain khác, gọi động một action theo string — đều **vô hình với load/bind checks** và chỉ lộ ra ở invoke-time hoặc không bao giờ lộ cho tới khi audit.

### Tiền lệ 1: dbt hidden ref

**[Nguồn]** dbt — About ref function: `ref()` vừa nội suy schema vừa **xây dependency graph ở parse phase** để chạy model đúng thứ tự. Nếu `ref` bị giấu trong nhánh `{% if execute %}` (không chạy ở parse phase), dbt không biết dependency và **ném lỗi ở runtime**; cách sửa là khai báo tường minh bằng comment `--depends_on: {{ ref(...) }}`. Jinja comment (`{# ... #}`) không có tác dụng vì parser bỏ qua.

- [dbt — About ref function](https://docs.getdbt.com/reference/dbt-jinja-functions/ref)

Đây chính xác là hình ảnh của undeclared handler dependency: logic ẩn khỏi parse phase = logic ẩn khỏi static layer.

### Tiền lệ 2: Python import là câu lệnh thực thi

**[Nguồn]** Python — The import system: câu lệnh `import` gồm hai thao tác, **search rồi bind**; `sys.modules` là cache, xóa entry khỏi cache không hủy module object nếu nơi khác còn giữ reference, và import lại sẽ tạo ra **hai module object khác nhau**. Module search path (`sys.path`) có thể bị chương trình sửa sau khởi tạo.

- [Python — The import system](https://docs.python.org/3/reference/import.html)

Hệ quả cho OaC: không thể đồng nhất "đã import trong Python" với "đã khai báo trong ontology". Một handler import được module không có nghĩa dependency đó thuộc contract.

### Quy tắc áp dụng

- **[Đề xuất OaC, giả thuyết]** Ở MVP, undeclared dependency là **lỗi bind-time** khi phát hiện được bằng đối chiếu khai báo (ví dụ handler cần delegation mà thiếu cạnh `calls`), và là **rủi ro đã ghi nhận** khi không phát hiện được. Đọc thân handler bằng AST để moi dependency vượt scope MVP — xem giới hạn ở mục Counterexample.
- Mọi truy cập cross-domain trong handler **nên** đi qua declared dependency; engine ở invoke-time chỉ resolve những gì đã bind — vế "chỉ" là giả thuyết thiết kế, cần engine thực tế kiểm chứng (thuộc phase engine, ngoài phạm vi tài liệu này).

## Load, Bind, and Invoke Checks

### Ba pha và trách nhiệm

**[Nguồn]** Chương 04 (§14.1) liệt kê các câu hỏi static layer phải trả lời: object types nào, properties/relations gì, action nhận parameter types nào, action phụ thuộc gì, policy nào áp dụng, có breaking contract không, backend cần capabilities gì. Chương 06 (§28) tách Definition / Engine / Implementation. Từ hai nguồn này, tài liệu đề xuất ba pha kiểm tra:

- **Load**: đọc được definitions, không trùng identity, không vỡ cú pháp. Chưa kiểm tra ý nghĩa.
- **Bind** gồm hai bước tách biệt:
    - **Linking**: mọi reference (`ObjectRef[T]`, `calls`, `reads`/`writes`) phân giải được vào registry, kiểu khớp, export cho phép. Chưa chạm dữ liệu, chưa chạm infrastructure.
    - **Deployment binding**: đối chiếu yêu cầu với provider đã chọn. Nếu Action yêu cầu ghi nguyên tử cả đơn hàng trong PostgreSQL và khoản giữ ngân sách trong ERP nhưng không có cơ chế commit nguyên tử chung, deployment binding phải từ chối contract đó. Saga hoặc outbox không cung cấp cùng bảo đảm.
- **Invoke**: principal, submission criteria, precondition trên world state hiện tại, version, concurrency, và revalidation plan-trước-commit. Chạm dữ liệu thật.

**[Nguồn]** Palantir — Action types overview: action type là định nghĩa của một tập edits + side effects; cùng logic và validation dùng chung cho mọi application.

- [Palantir — Action types overview](https://www.palantir.com/docs/foundry/action-types/overview)

**[Nguồn]** Palantir — Submission criteria: action chỉ submit được khi **mọi** submission criteria thỏa mãn tại thời điểm submit (kết hợp conditions trên current user, parameter, execution context); mỗi criteria có failure message riêng cho end user; có test run để verify trước.

- [Palantir — Action types submission criteria](https://www.palantir.com/docs/foundry/action-types/submission-criteria/)

Submission criteria chính là tiền lệ invoke-time check: cùng một definition, kết quả đổi theo principal và world state tại thời điểm gọi.

### Negative examples (mỗi pha một ví dụ trượt)

Pha load — trùng identity:

```python
# procurement/actions.py
class ApprovePurchaseOrder(Action):
    """..."""
    identity = "procurement.approve_purchase_order"
```

```python
# procurement/legacy.py
class ApprovePurchaseOrderLegacy(Action):
    """Module cũ bị import nhầm cùng lúc."""

    identity = "procurement.approve_purchase_order"
```

Lỗi load-time: `DuplicateIdentity("procurement.approve_purchase_order")`. Chưa cần biết gì về semantics cũng phải từ chối — tương tự `ModuleNotFoundError` của Python import khi search thất bại trước mọi binding.

Pha bind — reference tới definition không tồn tại hoặc không export:

```python
class ApprovePurchaseOrder(Action):
    """..."""
    identity = "procurement.approve_purchase_order"
    calls = ["finance.reserve_budget_typo"]
```

Lỗi linking-time: `UnresolvedReference("finance.reserve_budget_typo")`. Biến thể thứ hai: reference đúng tên nhưng Finance không export → `NotExported("finance.internal_policy")`. Cả hai đều phải rớt trước khi chạm dữ liệu.

Pha bind (deployment binding) — atomic trên hai backend không shared transaction:

```python
class ApprovePurchaseOrder(Action):
    """..."""
    identity = "procurement.approve_purchase_order"
    writes = [PurchaseOrder]              # PostgreSQL
    calls = ["finance.reserve_budget"]    # ERP, không shared transaction
    transaction = Transaction.atomic()
```

Lỗi deployment-binding-time: `NoSharedTransaction(["PurchaseOrder@postgres", "Budget@erp"])`. Nếu nghiệp vụ chấp nhận trạng thái trung gian và bù trừ, developer có thể đề xuất **contract khác**; đó không phải là cách thỏa `Transaction.atomic()`. Linking chỉ hỏi “reference có tồn tại không”; deployment binding hỏi “hạ tầng có thể cung cấp bảo đảm đã hứa không”.

### Negative examples ở invoke-time: ba kết quả phải phân biệt

Cùng một definition đã bind đúng, ba ngữ cảnh invoke cho ba kết quả thuộc ba cơ chế khác nhau:

```python
execution = ontology.actions.invoke(
    action="procurement.approve_purchase_order",
    parameters={"order": "PO-001", "reason": "Supplier verified"},
)
```

1. Requester hợp lệ, đơn vượt ngưỡng → `AWAITING_APPROVAL` (chờ duyệt, không phải từ chối; theo §30, status kèm `requiredApproval`):

```python
{
    "executionId": "exec-001",
    "action": "procurement.approve_purchase_order",
    "actionVersion": "1.2.0",
    "ontologyVersion": "2.1.0",
    "principal": "employee-123",
    "status": "AWAITING_APPROVAL",
    "requiredApproval": {
        "role": "finance_director"
    },
}
```

2. Principal không có permission `purchase_order.approve` → từ chối ở cửa authorization, không vào approval flow:

```python
{
    "executionId": "exec-002",
    "action": "procurement.approve_purchase_order",
    "principal": "contractor-999",
    "status": "DENIED",
    "failureMessage": "Principal thiếu quyền purchase_order.approve",
}
```

3. Đủ quyền nhưng budget không đủ → lỗi business validation/precondition, không phải lỗi authorization:

```python
{
    "executionId": "exec-003",
    "action": "procurement.approve_purchase_order",
    "principal": "employee-123",
    "status": "REJECTED",
    "failureMessage": "Budget B-001 còn lại không đủ cho số tiền đề nghị",
}
```

Gộp ba kết quả thành một `REJECTED` chung sẽ làm consumer không biết phải xin duyệt, xin quyền, hay sửa nghiệp vụ. Đúng như submission criteria của Palantir: conditions đánh giá tại thời điểm submit theo principal và world state, không phải lúc định nghĩa.

### Invoke-time revalidation: plan ≠ commit

**[Nguồn]** Theo §31, giữa lúc lập Mutation Plan và lúc commit, world state có thể đổi; runtime phải revalidate các assumptions liên quan (ví dụ `expectedVersion`) hoặc dùng concurrency guarantees phù hợp của backend, thay vì ghi đè mù.

**[Đề xuất OaC]** Mutation Plan của parent mang `expectedVersion` cho `PurchaseOrder:PO-001`. Nếu một execution khác đã commit version mới trước, commit coordination từ chối plan cũ (`StalePlan(expectedVersion=12, current=13)`) thay vì ghi đè — đây là check invoke-time, không thể dời lên bind vì bind chưa chạm dữ liệu.

## Registry versus Exported IR

### Ba lớp: registry, transport schema, exported IR

**[Nguồn]** Chương 02 (§8): source of truth là ontology source code; compiler/introspection trích xuất thành Canonical IR (JSON metadata: typed definitions + executable references) phục vụ engine, SDK, AI tools, RDF export. Nhưng JSON không biểu diễn được arbitrary executable code — IR chỉ mang operation contract + tham chiếu tới handler đã version.

**[Đề xuất OaC]** Phân vai ba lớp, không gộp:

- **Registry**: object graph trong process Python sau load+bind — source of truth ở runtime, cho phép resolve, validation, orchestration (§13: Validated Registry với canonical metadata, dependency graph, type information, execution contracts).
- **Transport schema**: contract trích ra cho một consumer cụ thể (ví dụ MCP tool schema cho AI agent) — có thể sinh bằng introspection trực tiếp từ registry đang sống, không cần file IR versioned độc lập.
- **Exported IR**: snapshot JSON bất biến, có version, của toàn bộ ontology (contracts + dependency graph + execution requirements) — cho consumer cần artifact độc lập process và version.

Transport schema ≠ whole ontology IR: schema cho MCP chỉ mang signature gọi action; IR mang cả dependency graph, execution requirements, metadata phục vụ diff và audit. Đồng nhất hai thứ sẽ hoặc thiếu thông tin (diff mù) hoặc phình to consumer contract.

### Decision triggers: khi nào IR versioned là bắt buộc

**[Đề xuất OaC]** Bắt đầu registry-only; introspection trực tiếp phục vụ consumer cùng-triển khai (kể cả MCP server đọc từ live registry). Xuất IR versioned khi gặp bất kỳ trigger nào:

1. Consumer cần artifact độc lập process **và** version (SDK ngôn ngữ khác phát hành theo version, audit snapshot gắn execution record §40).
2. Cần semantic diff giữa hai ontology versions (§55) trong CI mà không import được cả hai revisions vào cùng process — ngược lại, nếu import được cả hai, diff trực tiếp hai registry, không cần IR trung gian.
3. Triển khai kiểu Marketplace/SuperRepo (build artifact cài lên nhiều enrollment — SuperRepo build/deploy, xem nguồn SuperRepo ở trên).

**[Nguồn]** Palantir — SuperRepo Core concepts (đã dẫn ở trên): build step biến components thành single reproducible artifact; mỗi commit tag semantic version thành product version; ontology linting chạy trên entity definitions in code trước deploy. Đây là bằng chứng IR/artifact trở thành bắt buộc ngay khi có build–deploy–distribute, không phải ngay từ ngày đầu.

### Counterexample and Limit of the Key Recommendation

Khuyến nghị chính (registry-first, IR khi trigger) có ít nhất một phản ví dụ và một giới hạn đã biết trước:

**Phản ví dụ — live introspection thay thế IR cho consumer ngoài process.** MCP server riêng process vẫn có thể expose schemas bằng cách introspect live registry (cùng triển khai, endpoint truy vấn) thay vì đọc file IR versioned. Lúc đó "consumer ngoài process" không đủ để bắt buộc IR — chỉ khi consumer cần artifact versioned, độc lập triển khai (audit snapshot, SDK phát hành, multi-enrollment deploy) thì IR mới bắt buộc.

- Cơ sở nguồn cho phản ví dụ này: §8 đã dự kiến IR phục vụ AI Tools, nhưng §8 đồng thời tách Declaration/Implementation/Execution — introspection đọc declarations đang sống đã đủ cho tool schema; SuperRepo cho thấy OSDK bindings được sinh tự động từ definitions và local servers regenerate bindings khi ontology đổi (nguồn SuperRepo Core concepts, mục OSDK, đã dẫn ở trên).

- Hệ quả thiết kế — dưới dạng **[Giả thuyết]**, không phải đảm bảo: mọi declaration nên thiết kế sao cho *có thể* serialize đầy đủ (identity, types, reads/writes, permission) để ngày cần IR không viết lại. Tính khả thi đầy đủ của serializability (đặc biệt với `Approval.conditional` chứa biểu thức `Param("order").amount > 100_000`) chưa được chứng minh — phase 2 phải kiểm chứng, và cú pháp Python trong tài liệu này chỉ là minh họa giả thuyết, chưa phải syntax đã chốt (bản thân các chương chính thức cũng ghi mọi API/syntax là conceptual DSL minh họa — §6).

**Giới hạn — IR không mang được executable, và một mẫu AST dương không chứng minh được phát hiện toàn cục.** §8 nói rõ JSON metadata không biểu diễn được arbitrary executable Python code: đổi thân handler mà giữ contract thì IR diff mù. Tương tự, dù thí nghiệm AST bắt được một undeclared dependency cụ thể, các dạng che giấu tổng quát (`getattr` động, dispatch theo string dựng ở runtime, import trong nhánh điều kiện) về nguyên tắc không phát hiện hết bằng static analysis — một mẫu dương không biện minh cho cơ chế phát hiện toàn cục. Do đó "undeclared access là rủi ro đã ghi nhận" giữ nguyên bất kể kết quả thí nghiệm đơn lẻ; giới hạn này chuyển sang phase 2 dưới dạng câu hỏi: version và kiểm soát handler thế nào khi cả IR lẫn AST đều không thấy hết thân code.

## Handoff Assumptions to Phase 2

Các giả định phase 2 (Developer workflow & model evolution) được phép dựa vào; nếu phase 2 bác bỏ giả định nào, phải quay lại sửa tài liệu này:

1. Identity format `<domain>.<snake_name>`, chữ thường; version nằm ngoài identity, đi kèm trong execution record.
2. `reads`/`writes` khai báo ở mức Object Type trên class Action; property-level scope thuộc phase sau.
3. Cross-domain reference chỉ hợp lệ khi target đã export; danh sách `exports` nằm ở module.
4. Handler chỉ chạm những gì đã khai báo; undeclared access là lỗi hoặc rủi ro đã ghi nhận, không phải tính năng.
5. **[Giả thuyết cần kiểm chứng]** Mọi declaration có thể serialize đầy đủ thành JSON (kể cả điều kiện approval dạng biểu thức); cú pháp Python trong tài liệu này là minh họa, chưa phải syntax đã chốt.
6. Ba pha load/bind/invoke là hợp đồng ổn định; phase 2 chỉ thêm rule mới vào từng pha, không gộp pha. Phân biệt linking vs deployment binding (mục Checks) giữ nguyên.

Mọi khuyến nghị thực tiễn, cú pháp mẫu và giả định serializability trong tài liệu này là giả thuyết làm việc, không phải đảm bảo — phase 2 có quyền bác bỏ kèm bằng chứng, và khi đó tài liệu này phải được sửa theo.

## Open Questions and Next Falsifiable Experiment

**[Câu hỏi mở]**

- Property-level read/write scope khai báo ở đâu mà không làm declaration phình to (liên quan §39 query-time security)?
- Interface là structural hay behavioral contract (§23), và điều đó ảnh hưởng gì tới `exports`?
- Version của handler thân code quản lý thế nào khi IR diff không thấy được (§8 + giới hạn ở trên)?
- Action composition liên domain (§34): principal propagation và shared transaction biểu diễn ra sao trong `calls` đã khai báo?

**Thí nghiệm falsifiable tiếp theo (cho phase 2 hoặc spike nhỏ).** Dự đoán: viết registry tối thiểu import hai module (`procurement`, `finance`), trong đó handler của `ApprovePurchaseOrder` lén `ctx.resolve()` một `Supplier` không có trong `reads`, rồi chạy bind checks — bind **vẫn pass** (undeclared dependency thoát). Dù kết quả ra sao, một thí nghiệm đơn lẻ chỉ trả lời cho mẫu đó: nếu bind fail nhờ AST scan đơn giản, vẫn không được kết luận "đã phát hiện được mọi undeclared access" (xem giới hạn ở trên); nếu bind pass, giả định 4 đứng vững và AST scan không vào bind phase MVP.

## References and Web Sources

Nguồn sơ cấp đã đọc và trích dẫn (mọi khẳng định **[Nguồn]** đều bám vào các mục cụ thể dưới đây):

- [Python — The import system](https://docs.python.org/3/reference/import.html) — §5 mở đầu (import = search + bind), §5.3.1 (sys.modules cache, re-import tạo object khác), §5.3.2 (finders/loaders, ModuleNotFoundError). Dùng cho: undeclared dependency caveat; load-phase semantics.
- [Python Tutorial — Modules](https://docs.python.org/3/tutorial/modules.html) — §6.1 (`import *` trừ tên gạch dưới; bị xem là kém). Dùng cho: exported vs internal.
- [Kubernetes — Object Names and IDs](https://kubernetes.io/docs/concepts/overview/working-with-objects/names/) — Name (client-provided, duy nhất trong kind + namespace, tái dùng được) vs UID (system-generated, duy nhất toàn cluster lifetime). Dùng cho: identity vs host names.
- [Pydantic — Models](https://pydantic.dev/docs/validation/latest/concepts/models/) — annotated fields, validation guarantee, ValidationError, model_json_schema/model_dump. Dùng cho: typed dependencies; IR derivation analogy.
- [SQLAlchemy — Mapping Classes with Declarative](https://docs.sqlalchemy.org/en/20/orm/declarative_mapping.html) — code-first class + annotation thành registry metadata. Dùng cho: registry pattern.
- [dbt — About ref function](https://docs.getdbt.com/reference/dbt-jinja-functions/ref) — ref xây dependency graph ở parse phase; hidden ref trong `if execute` gây runtime error; `--depends_on` và SQL comment (không phải Jinja comment). Dùng cho: undeclared handler dependency caveat.
- [Palantir — Action types overview](https://www.palantir.com/docs/foundry/action-types/overview) — action type = tập edits + side effects dùng chung mọi app. Dùng cho: definition vs invoke; shared contract.
- [Palantir — Submission criteria](https://www.palantir.com/docs/foundry/action-types/submission-criteria/) — conditions trên current user/parameter/execution context; tất cả phải pass lúc submit; failure message; test run. Dùng cho: invoke-time checks.
- [Palantir — Object types overview](https://www.palantir.com/docs/foundry/object-link-types/object-types-overview) — object type vs object vs object set. Dùng cho: M2/M1/M0 (§17) đối chiếu thực tế.
- [Palantir — Create an object type](https://www.palantir.com/docs/foundry/object-link-types/create-object-type) — type ID vs display name (đổi ID gãy app); primary key duy nhất + deterministic (đổi key mất edits/links). Dùng cho: identity stability.
- [Palantir — SuperRepo Core concepts](https://www.palantir.com/docs/foundry/superrepo/core-concepts/) — Ontology-as-code là source of truth; definitions compile/materialize thành entities; OSDK bindings sinh tự động; import kèm lock file; build thành reproducible artifact; lint trước deploy. Dùng cho: registry vs IR triggers; counterexample.

Chương chính thức OaC sử dụng: `04-system-architecture.md` (§13–16), `05-ontology-meta-model.md` (§17–25), `06-action-model.md` (§26–34), cùng `02-ontology-as-code.md` (§8) cho canonical IR.
