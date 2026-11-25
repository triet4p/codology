# Implementation Baseline — Declarations Scaffold

*Bản ghi quyết định triển khai cho lớp khai báo tĩnh. Tài liệu này chốt những lựa chọn mà Sprint 2 để mở và Sprint 3 phải cố định trước khi viết các primitive: phiên bản Python, layout/đóng gói, công cụ test và type-check, quy ước handler, và cơ chế resolve forward annotation. Các sprint sau đọc tài liệu này thay vì chọn lại.*

## 1. Phạm vi

Baseline này chỉ phủ **lớp mô hình tĩnh**. Nó không mô tả Load/Link/registry, deployment binding, engine hay adapter — các phần đó do task kế tiếp trong [Sprint 3](../../sprint-plans/sprint-3.md) triển khai. Không có tuyên bố về `ATOMIC`, authorization hay execution.

## 2. Quyết định

| Chủ đề | Quyết định | Lý do |
| --- | --- | --- |
| Python runtime | CPython 3.13; `requires-python = ">=3.13"`, pin `.python-version` = `3.13` | Phiên bản ổn định đang dùng; cho phép dùng cú pháp typing hiện đại và khớp floor 3.12 của quy ước Python |
| Layout | `src/` layout: `src/codology/` | Ngăn import nhầm source chưa cài, tách package khỏi `docs/`, `artifacts/`, `experiments/`; đóng gói wheel sạch |
| Packaging | Hatchling build backend, version lấy từ `src/codology/__init__.py`, uv quản lý môi trường và `uv.lock` | Một nguồn version; lockfile tái lập được; không cần setuptools legacy |
| Test | pytest, test dưới `tests/`, cấu hình `testpaths` trong `pyproject.toml` | Chuẩn của repo; chạy được từ môi trường sạch bằng một lệnh |
| Type-check | Pyright strict trên `src` và `tests` | Sprint 2 nhắm Pyright strict; strict bắt lỗi kiểu của author ngay trong editor |
| Lint/format | Ruff (`ruff check`, `ruff format --check`) | Một công cụ cho lint và format, cấu hình trong `pyproject.toml` |
| Handler | Một quy ước duy nhất: `def handler(self, ctx, ...)` | Khớp toàn bộ ví dụ đã publish; không có tên thứ hai hay bề mặt kép |
| Forward annotation | Giữ nguyên annotation thô lúc tạo class; resolve ở pha Link bằng namespace đã compose | Hai module tham chiếu kiểu của nhau mà không import vòng lúc chạy |

## 3. Quy ước handler

Mọi declaration có hành vi (`Action`, `Function`, `Effect` khi các task sau thêm chúng) khai báo đúng một instance method tên `handler`:

```python
class ApprovePurchaseOrder(Action):
    def handler(self, ctx, order: PurchaseOrder, reason: str) -> None:
        ...
```

- **Không hỗ trợ `@staticmethod def handle(...)`.** Đây là quyết định dứt điểm: một tên, một chữ ký, một bề mặt. Không có adapter hay alias để che khác biệt giữa kế hoạch Sprint 2 và thiết kế chi tiết.
- **`self` không mang state.** Declaration là class, nên `self` là hệ quả tự nhiên; engine dùng lại một metadata instance và không cho phép dùng thuộc tính instance làm execution state.
- **Cưỡng chế ở Load/Link, không ở metaclass.** `codology.declarations.handler.handler_signature(cls)` trả `inspect.Signature` sau khi kiểm tra: `handler` tồn tại, là plain function trong namespace của chính class, và hai tham số đầu tên `self`, `ctx`. Hàm này không resolve kiểu tham số; Link resolve chúng cùng annotation của declaration.
- **Kiểu contract tách khỏi kiểu handler.** Annotation trong thân class là kiểu contract (`ObjectRef[T]`); annotation trên `handler` là kiểu đã resolve (`T`). Việc đối chiếu hai bên thuộc pha Link (task S3-T5), không phải runtime.

## 4. Resolve forward annotation

Annotation có thể nhắc tới declaration thuộc module khác. Nếu Python evaluate annotation ngay khi tạo class, hai module tham chiếu lẫn nhau sẽ tạo import vòng. Cơ chế hiện tại:

1. Khi class được tạo, `raw_annotations(target)` (dùng `inspect.get_annotations(..., eval_str=False)`) giữ nguyên annotation dạng chuỗi/đối tượng như đã viết. Không import module khác.
2. Ở pha Link, registry compose một namespace gồm tên declaration của **mọi** module tham gia link, ánh xạ tới class tương ứng.
3. `resolve_annotations(target, namespace)` merge namespace của module sở hữu (fallback) với namespace đã compose (ưu tiên khi trùng tên), rồi gọi `typing.get_type_hints(..., include_extras=True)`.

Hệ quả:

- Hai module có thể khai báo `budget: "Budget"` và `purchase_order: "PurchaseOrder"` mà không import nhau; chỉ cần cả hai được đưa vào cùng namespace lúc Link.
- Annotation không resolve được (thiếu tên, sai tham chiếu) là lỗi ở pha Link, không phải lỗi lúc import.
- `include_extras=True` giữ `Annotated[...]` cho các task dùng metadata typing.

## 5. Lệnh tái lập

Từ thư mục gốc repo, trong môi trường sạch có Python 3.13 và uv:

```bash
uv sync
uv run python -c "import codology; print(codology.__version__)"
uv run pytest
uv run pyright
uv run ruff check .
uv run ruff format --check .
```

## 6. Giới hạn và non-claims

- Load (`codology.loading.load`) thu thập definition theo ownership, giữ identity/version và từ chối identity trùng cùng field lạ; Link/registry chưa có nên chưa có kiểm tra export hay reference.
- Không có engine, authorization, UoW, atomic commit, approval callback, effect delivery hay adapter.
- Metadata `ATOMIC` trong mô hình không chứng minh backend đáp ứng atomicity; không có digest artifact publish.
- Static validation không phát hiện truy cập ẩn trong thân handler (import lén, `getattr` động, file/socket). Đây là rủi ro đã ghi nhận, không phải năng lực đã có.
- Không có ngưỡng coverage hay hiệu năng.

## 7. Hệ quả cho các task sau

- S3-T2/T3 dựng `ObjectType`, `Value`, `Link`, `Action`, `Function` trên `codology.declarations`; mọi hành vi dùng `handler(self, ctx, ...)`.
- S3-T4/T5 dùng `raw_annotations`/`resolve_annotations` và `handler_signature` để kiểm tra export, reference và đối chiếu chữ ký tại Load/Link.
- S3-T6 giữ snapshot bất biến; không thêm API đọc `latest` ngầm định.
- S3-T7 viết ví dụ Procurement/Finance trên API thật, không dựa vào ví dụ Sprint 2 như code đã có.
