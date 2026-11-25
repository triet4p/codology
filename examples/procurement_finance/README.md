# Ví dụ Procurement → Finance

Ví dụ chạy được trên API công khai thật của `codology`: khai báo hai module Procurement và Finance, compose chúng qua Load, Link và Snapshot, rồi in cả đường thành công lẫn sáu lỗi tĩnh. Không có database, provider, credential, engine hay adapter nào tham gia.

## Cấu trúc

- `common.py` — `Money`, một `Value` cấu trúc không có identity, dùng chung cho hai module.
- `finance.py` — `Budget`, `ReserveBudget`, `Finance`; export `Budget` và `ReserveBudget`.
- `procurement.py` — `PurchaseOrder`, `OrderApprovedPayload`, `NotifyWarehouseOrderApproved`, `ApprovePurchaseOrder`, `Procurement`. Tham chiếu Finance bằng identity đã khai báo (`Link["finance.budget", ...]`, `calls = ("finance.reserve_budget",)`) nên module này không import Finance lúc chạy.
- `model.py` — ghép hai `ModuleDeclarations` và chạy `load`, `link`, `snapshot`.
- `scenarios.py` — sáu ca lỗi tĩnh; mỗi hàm trả về error thật để script in ra và test assert lại.
- `__main__.py` — entry point của ví dụ.

## Chạy ví dụ

Từ thư mục gốc repo, sau `uv sync`:

```bash
uv run python -m examples.procurement_finance
```

Script in ra:

- definition đã Load kèm owner và version;
- cạnh đã kiểm tra ở Link của `procurement.approve_purchase_order` (`params.order`, `reads`, `writes`, `calls`, `effects`);
- entry Snapshot gồm kind, permission, `commitRequirement`, và biểu thức approval đã chuẩn hoá;
- sáu lỗi tĩnh kèm module, identity và field do Load/Link gắn vào error.

Script trả exit code 0 khi mọi ca lỗi đều fail đúng như mong đợi. Một ca không còn fail sẽ raise `AssertionError` và thoát khác 0, nên ví dụ không thể âm thầm báo "đã kiểm tra" khi kiểm tra biến mất.

## Chạy kiểm thử và typing

```bash
uv run pytest -q
uv run pyright
uv run ruff check .
uv run ruff format --check .
```

- `tests/test_procurement_finance_integration.py` import chính package ví dụ, kiểm tra đường Load → Link → Snapshot, sáu lỗi bên dưới, và output của entry point.
- `tests/typing/valid_api.py` dùng `assert_type` để ghim kiểu trả về của `load`, `link`, `snapshot`, `lookup` và `DefinitionKey`.
- `tests/typing/invalid_api.py` chứa các lỗi kiểu có chủ đích. File bật `reportUnnecessaryTypeIgnoreComment=error`, nên mỗi `# pyright: ignore[...]` phải thật sự chặn một lỗi; nếu Pyright ngừng bắt lỗi đó, `uv run pyright` fail.

## Lỗi được minh họa

| Ca | Lỗi | Pha |
| --- | --- | --- |
| Identity trùng | `DuplicateIdentity` | Load |
| Reference không export | `NotExported` | Link |
| Reference không tồn tại | `UnresolvedReference` | Link |
| `ObjectRef[T]` lệch kiểu handler | `ObjectRefMismatch` | Link |
| Tên tham số handler lệch contract | `HandlerMismatch` | Link |
| Lambda trong approval predicate | `UnsupportedApprovalExpression` | Declaration |

## Load/Link so với deployment binding và runtime

| Pha | Ví dụ này có | Ví dụ này không có |
| --- | --- | --- |
| Load | Thu thập definition theo ownership, kiểm tra identity trùng và field lạ | Resolve reference hay đọc dữ liệu |
| Link | Resolve forward annotation, kiểm tra đích tồn tại/đúng kind/được export, đối chiếu chữ ký handler | Gọi handler, suy dependency từ thân handler |
| Snapshot | Graph bất biến, lookup tường minh theo identity + version, dependency và approval expression | `latest`, digest artifact publish |
| Deployment binding | Không có | Chọn provider, kiểm tra capability/`NoSharedTransaction`, cấu hình môi trường |
| Runtime | Không có | `query`/`invoke`, authorization, session/Unit of Work, atomic commit, approval callback, effect delivery |

Mọi handler trong ví dụ đều raise `AssertionError`; Load, Link và Snapshot chỉ đọc metadata nên không handler nào chạy. Không có backend giả, không có stub runtime, và không có tuyên bố rằng các năng lực runtime đã hoạt động.

## Non-claims

- `commitRequirement = CommitRequirement.ATOMIC` chỉ là metadata được lưu và công bố; nó không chứng minh backend đáp ứng atomicity.
- `approval` chỉ là biểu thức cấu trúc; không đánh giá ngưỡng, không gọi callback duyệt.
- `effects` chỉ là mô tả outbox intent; không có effect nào được giao.
- `permission = "purchase_order.approve"` là chuỗi khai báo; authorization live chưa tồn tại.
- Static validation không phát hiện truy cập ẩn trong thân handler (`getattr` động, import lén, đọc file/socket).
