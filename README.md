# Codology

Codology (Ontology as Code) là lớp mô hình tĩnh cho phép developer khai báo thực thể, quan hệ và hành vi nghiệp vụ bằng Python, rồi kiểm tra mô hình trước khi kết nối backend. Package Python gốc là `codology`; OaC là tên khái niệm, không phải tên package.

## Trạng thái

Repository đang ở Sprint 3 — Declarations & Linked Registry. Phần đã có là project scaffold và hạ tầng khai báo tĩnh:

- `codology` import được từ môi trường sạch, không cần database, credential hay backend SDK.
- `codology.declarations` cung cấp primitive cấu trúc bất biến `Module`, `ObjectType`, `Value`, `Link` và `ObjectRef[T]`: identity/version tường minh, property có kiểu, link có target/cardinality/traversal và `exports` đóng băng.
- `codology.declarations` cung cấp `Action`, `Function`, `Effect` và predicate approval cấu trúc: `params`, `reads`/`writes`/`calls`, `permission`, `commitRequirement`, `approval` và `effects` được đóng băng lúc khai báo; không chạy handler hay đánh giá predicate.
- Load và Link đã được triển khai; snapshot/registry công khai, binding, engine và adapter **chưa được triển khai**; các task sau trong sprint bổ sung dần.

## Yêu cầu

- Python 3.13 (pin trong `.python-version`).
- [uv](https://docs.astral.sh/uv/) để quản lý môi trường và dependency.

## Cài đặt và tái lập

```bash
uv sync
```

Lệnh trên tạo `.venv`, cài package ở chế độ editable và cài nhóm dependency `dev` (pytest, Pyright, Ruff).

## Chạy kiểm tra

```bash
uv run python -c "import codology; print(codology.__version__)"
uv run pytest
uv run pyright
uv run ruff check .
uv run ruff format --check .
```

## Cấu trúc

```text
src/codology/
  __init__.py
  py.typed
  loading.py        # Load: thu thập definition, kiểm tra identity và field
  linking.py        # Link: resolve reference, export, kind và chữ ký handler
  declarations/
    __init__.py
    annotations.py   # giữ annotation thô, resolve ở pha Link
    behavior.py      # Action/Function/Effect và governance metadata
    handler.py       # quy ước handler duy nhất
    primitives.py    # Module/ObjectType/Value/Link/ObjectRef bất biến
tests/
  test_annotations.py
  test_behavior.py
  test_declarations.py
  test_handler.py
  test_linking.py
  test_loading.py
  test_package.py
```

## Khai báo cấu trúc

```python
from decimal import Decimal

from codology.declarations import Link, Module, ObjectRef, ObjectType, Value


class Money(Value):
    amount: Decimal
    currency: str


class Budget(ObjectType):
    identity = "finance.budget"
    version = "1.0.0"
    keyType = "B"
    limit: Money
    reserved: Money


class PurchaseOrder(ObjectType):
    identity = "procurement.purchase_order"
    version = "1.0.0"
    keyType = "PO"
    budget = Link[Budget, "one", "navigable"]


class Procurement(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder,)


order_ref = ObjectRef[PurchaseOrder]
```

Identity và version phải được khai báo tường minh, không suy từ tên class. Class khai báo và các collection đầu vào (`exports`, `links`, annotation) được sao chép và đóng băng lúc tạo; sửa chúng sau đó không làm đổi declaration. `exports` là ranh giới sở hữu, không phải quyền truy cập; việc kiểm tra reference liên module thuộc pha Link (chưa triển khai).

## Khai báo hành vi và governance

`Action` khai báo `params` (annotation có kiểu), `reads`, `writes`, `permission` và `handler(self, ctx, ...)`; `Function` là view chỉ đọc có `result`. Các nấc sau chỉ **thêm** thuộc tính: `calls` và `commitRequirement = CommitRequirement.ATOMIC` (liên module), rồi `approval` và `effects` (duyệt có điều kiện, effect sau commit). `Effect` khai `payload` (một `Value`) và `dedupKey` tùy chọn.

```python
from codology.declarations import (
    Action,
    Approval,
    Effect,
    ObjectRef,
    Param,
    Value,
)


class OrderApprovedPayload(Value):
    order: ObjectRef[PurchaseOrder]
    approved_amount: Money


class NotifyWarehouseOrderApproved(Effect):
    identity = "procurement.warehouse_order_approved"
    version = "1.0.0"
    payload = OrderApprovedPayload
    dedupKey = ("order",)


class ApprovePurchaseOrder(Action):
    identity = "procurement.approve_purchase_order"
    version = "1.0.0"
    order: ObjectRef[PurchaseOrder]
    reason: str
    reads = (PurchaseOrder,)
    writes = (PurchaseOrder,)
    permission = "purchase_order.approve"

    def handler(self, ctx, order: PurchaseOrder, reason: str) -> None: ...


approval = Approval.conditional(
    when=Param("order").normalized_amount >= 100_000,
    role="finance_director",
    self_approval=False,
)
```

`when` chỉ nhận predicate cấu trúc: so sánh `>`, `>=`, `<`, `<=`, `==`, `!=` và `all_of`/`any_of`/`not_` (hoặc `.and_`/`.or_`/`.not_`). Lambda, phép toán số học và method call bị từ chối ngay lúc khai báo, kèm tên biểu thức không được hỗ trợ. `>` và `>=` là hai toán tử khác nhau trong predicate. Khai báo không đánh giá predicate trên dữ liệu thật, không gọi handler và không giao effect.

## Load: thu thập và kiểm tra declaration

`load` nhận một hoặc nhiều `ModuleDeclarations`: mỗi nhóm gồm một `Module` và mọi definition mà module đó sở hữu, kể cả definition không nằm trong `exports`. Kết quả là `LoadedDeclarations` bất biến với ánh xạ module và definition theo identity đã khai báo.

```python
from codology import ModuleDeclarations, load

loaded = load(
    ModuleDeclarations(Procurement, [PurchaseOrder, ApprovePurchaseOrder]),
    ModuleDeclarations(Finance, [Budget, ReserveBudget]),
)
reserved = loaded.definitions["finance.reserve_budget"]
assert reserved.owner == "finance" and reserved.version == "1.0.0"
```

Load từ chối identity trùng (`DuplicateIdentity`) và field khai báo không hợp lệ (`UnknownDeclarationKey`). Cả hai lỗi đều kèm module, identity và field để author sửa; một field gõ nhầm trong thân class bị từ chối thay vì bị bỏ qua. Identity luôn lấy từ `identity` đã khai báo, không suy từ tên class: hai class cùng tên `Budget` nhưng identity khác nhau load được bình thường, và `Value` không khai identity giữ `identity = None`. Collection đầu vào được sao chép tại Load; sửa chúng sau đó không làm đổi kết quả.

Load **không** resolve reference, kiểm tra export hay gọi handler; các việc đó thuộc Link.

## Link: resolve và kiểm tra ranh giới module

`link` nhận `LoadedDeclarations` từ Load và trả `LinkedDeclarations` bất biến: mỗi definition có annotation đã resolve, chữ ký handler đã đối chiếu và các cạnh reference đã kiểm tra. Namespace được compose từ mọi definition tham gia link, nên hai module có thể tham chiếu kiểu của nhau bằng forward annotation mà không import vòng lúc chạy.

```python
from codology import ModuleDeclarations, link, load

linked = link(
    load(
        ModuleDeclarations(Procurement, [PurchaseOrder, ApprovePurchaseOrder]),
        ModuleDeclarations(Finance, [Budget, ReserveBudget]),
    )
)
approve = linked.definitions["procurement.approve_purchase_order"]
assert approve.hints["order"].target is PurchaseOrder
```

Link từ chối reference không tồn tại (`UnresolvedReference`), đích sai loại (`WrongKind`), definition liên module chưa export (`NotExported`), `ObjectRef[T]` không khớp (`ObjectRefMismatch`) và handler sai quy ước/tham số (`HandlerMismatch`). Mỗi lỗi kèm module, identity và field để author sửa. Link chỉ đọc annotation và chữ ký: không gọi handler, không suy dependency từ thân handler và không cần provider hay credential.

## Quyết định đã chốt

- **Một quy ước handler duy nhất:** `def handler(self, ctx, ...)` trên class khai báo. `@staticmethod def handle(...)` không được hỗ trợ; không có API thứ hai để giữ đồng bộ. `self` không mang execution state.
- **Forward reference không import vòng:** annotation được giữ nguyên dạng viết lúc tạo class và chỉ resolve ở pha Link bằng namespace đã compose từ mọi module tham gia link. Hai module có thể tham chiếu kiểu của nhau mà không import nhau lúc chạy.
- **Layout và công cụ:** source đặt trong `src/codology/`, đóng gói bằng Hatchling, quản lý bằng uv; kiểm thử bằng pytest; type-check bằng Pyright strict; lint/format bằng Ruff.
- Chi tiết và hệ quả cho các task sau: [`docs/official/design/implementation-baseline.md`](docs/official/design/implementation-baseline.md).

## Giới hạn

- Đây là lớp mô hình **tĩnh**. Chưa có engine `query`/`invoke`, authorization, session/Unit of Work, atomic commit, approval callback hay effect delivery.
- Load đã thu thập definition và kiểm tra identity/field; Link đã resolve reference, kiểm tra export/kind và chữ ký handler. Snapshot/registry công khai và kiểm tra deployment binding thuộc các task kế tiếp.
- Predicate approval chỉ được lưu dạng cấu trúc; chưa có đánh giá ngưỡng, callback duyệt hay giao effect. `Function` dùng cùng quy ước `handler(self, ctx, ...)` với `Action` theo implementation baseline.
- Không có tuyên bố `ATOMIC`, authorization hay execution đã hoạt động. Metadata `ATOMIC` được lưu trong mô hình (khi có) không chứng minh backend đáp ứng atomicity.
- Static validation không phát hiện truy cập ẩn trong thân handler (import lén, `getattr` động, đọc file/socket). Đó là rủi ro đã ghi nhận, xử lý bằng review và test.

## Tài liệu

- [Sprint 3 plan](docs/sprint-plans/sprint-3.md)
- [Implementation baseline](docs/official/design/implementation-baseline.md)
- [Developer Contract](docs/official/design/developer-contract.md)
- [Framework Design v0.1](docs/official/design/framework-design-v0.1.md)
