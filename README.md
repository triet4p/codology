# Codology

Codology (Ontology as Code) là lớp mô hình tĩnh cho phép developer khai báo thực thể, quan hệ và hành vi nghiệp vụ bằng Python, rồi kiểm tra mô hình trước khi kết nối backend. Package Python gốc là `codology`; OaC là tên khái niệm, không phải tên package.

## Trạng thái

Repository đang ở Sprint 3 — Declarations & Linked Registry. Phần đã có là project scaffold và hạ tầng khai báo tĩnh:

- `codology` import được từ môi trường sạch, không cần database, credential hay backend SDK.
- `codology.declarations` cung cấp quy ước handler duy nhất và cơ chế resolve forward annotation ở pha Link.
- Load, Link, snapshot, binding, engine và adapter **chưa được triển khai**; các task sau trong sprint bổ sung dần.

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
  declarations/
    __init__.py
    annotations.py   # giữ annotation thô, resolve ở pha Link
    handler.py       # quy ước handler duy nhất
tests/
  test_annotations.py
  test_handler.py
  test_package.py
```

## Quyết định đã chốt

- **Một quy ước handler duy nhất:** `def handler(self, ctx, ...)` trên class khai báo. `@staticmethod def handle(...)` không được hỗ trợ; không có API thứ hai để giữ đồng bộ. `self` không mang execution state.
- **Forward reference không import vòng:** annotation được giữ nguyên dạng viết lúc tạo class và chỉ resolve ở pha Link bằng namespace đã compose từ mọi module tham gia link. Hai module có thể tham chiếu kiểu của nhau mà không import nhau lúc chạy.
- **Layout và công cụ:** source đặt trong `src/codology/`, đóng gói bằng Hatchling, quản lý bằng uv; kiểm thử bằng pytest; type-check bằng Pyright strict; lint/format bằng Ruff.
- Chi tiết và hệ quả cho các task sau: [`docs/official/design/implementation-baseline.md`](docs/official/design/implementation-baseline.md).

## Giới hạn

- Đây là lớp mô hình **tĩnh**. Chưa có engine `query`/`invoke`, authorization, session/Unit of Work, atomic commit, approval callback hay effect delivery.
- Chưa có Load/Link/registry; các kiểm tra identity, export và reference liên module thuộc các task kế tiếp của Sprint 3.
- Không có tuyên bố `ATOMIC`, authorization hay execution đã hoạt động. Metadata `ATOMIC` được lưu trong mô hình (khi có) không chứng minh backend đáp ứng atomicity.
- Static validation không phát hiện truy cập ẩn trong thân handler (import lén, `getattr` động, đọc file/socket). Đó là rủi ro đã ghi nhận, xử lý bằng review và test.

## Tài liệu

- [Sprint 3 plan](docs/sprint-plans/sprint-3.md)
- [Implementation baseline](docs/official/design/implementation-baseline.md)
- [Developer Contract](docs/official/design/developer-contract.md)
- [Framework Design v0.1](docs/official/design/framework-design-v0.1.md)
