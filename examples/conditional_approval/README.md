# Ví dụ thực thi: chờ duyệt, tiếp tục và giao thông báo

Ví dụ chạy được trên API công khai của `codology` và adapter SQLite thật: một consumer đọc đơn qua `query`, lấy ref có kiểu từ `row.as_ref()`, gọi `invoke` cho action có `approval` và `effects`, rồi đi qua callback `approve`/`reject`, `resume`, `reconcile`, `deliver_committed` và `read_effect_status`. Không có policy hay SQL trong caller; ngưỡng tiền, vai trò và `self_approval` nằm ở declaration, quyền và dữ liệu nằm ở host và engine.

Ví dụ này là phần nấc 3. Nó **không** thay thế ví dụ nấc 2 ở [`examples/atomic_approval/`](../atomic_approval/README.md): ví dụ đó vẫn chỉ chạy contract `runtime.py` không có approval/effect và không được tuyên bố là đã chạy nấc 3.

## Cấu trúc

- `declarations.py` — runtime declaration có handler thật: root `procurement.approve_purchase_order@2.0.0` với `Approval.conditional`, child `finance.reserve_budget@1.0.0` và effect `procurement.warehouse_order_approved@1.0.0`; một revision set mới hơn có handler ném lỗi để chứng minh replay dùng manifest đã ghim.
- `database.py` — schema và seed SQLite cho đơn, ngân sách, ledger, decision/audit, resume outcome và outbox. Chỉ file này (phía host) viết SQL thật.
- `wiring.py` — host configuration: identity, deployment một session, provider/adapter SQLite thật, principal, read grant, authority live và các hook fault-injection có tính quyết định. Không có luật nghiệp vụ.
- `consumer.py` — toàn bộ đường gọi công khai; nhận principal/grant/adapter từ host, không tự tính fingerprint, không tự áp ngưỡng hay role, không SQL.
- `__main__.py` — entry point chạy mọi kịch bản, in kết quả quan sát được và assert từng kỳ vọng.

## Chạy

Từ gốc repo sau `uv sync`:

```bash
uv run python -m examples.conditional_approval
```

Mặc định dùng file `.tmp/conditional-approval/*.sqlite3` (đã git-ignore). Có thể truyền thư mục khác:

```python
from pathlib import Path
from examples.conditional_approval.__main__ import main

raise SystemExit(main(Path(".tmp/khac")))
```

Script in các nhóm sau và kết thúc bằng `ALL CHECKS PASSED`; assertion sai làm exit khác 0:

- **Dưới ngưỡng** — `COMMITTED` không cần approver; `reconcile`, effect `PENDING → DELIVERED`.
- **Tại ngưỡng, restart, đổi revision mặc định** — `AWAITING_APPROVAL` không ghi đơn/ngân sách/outbox; mở lại host, replay cùng key dưới revision mặc định mới vẫn trả đúng execution đã ghim; approve rồi resume mới commit.
- **Callback bị từ chối/trùng/reject** — outsider và fingerprint sai bị `DENIED`/`KEY_MISUSE` mà execution vẫn chờ; duplicate trả decision đã lưu; `reject` hợp lệ là terminal không ghi nghiệp vụ.
- **Duyệt lại** — amount đổi trước commit thì resume cấp callback key/fingerprint mới; key cũ bị `KEY_MISUSE`; approve mới rồi commit một lần.
- **Tranh ngân sách** — hai resume cùng lúc qua barrier; nhiều nhất một commit thật, reservation và resume outcome vẫn ghi một lần.
- **Mất ack commit** — resume `UNKNOWN`, `reconcile` theo key và theo execution id thấy `COMMITTED`, retry trả result đã lưu; không giữ ngân sách lần hai.
- **Lỗi relay** — transient `PENDING_RETRY` rồi retry `DELIVERED`; permanent `FAILED`; mất ack sau khi sink đã ghi thì replay vẫn chỉ một thông báo địa phương.

## Kiểm thử xuyên lớp

```bash
uv run pytest tests/test_conditional_approval_example.py -q
```

Mỗi kết quả API được đối chiếu bằng một connection SQLite độc lập: trạng thái/version của đơn, reserved/version của ngân sách, hàng ledger, hàng outbox, decision/audit, resume outcome và inbox của receiver. Bộ kiểm gồm 13 ca: entry point, commit dưới ngưỡng, chờ không ghi/không giữ lock, restart và pin, deny/duplicate, reject, duyệt lại, tranh chấp, mất ack commit, relay transient/permanent/lost ack và cửa đọc effect theo tenant/quyền.

`uv run pytest tests/test_relay.py tests/test_outbox.py tests/test_resume.py tests/test_waiting.py tests/test_child_action.py tests/test_atomic_approval_example.py -q` giữ regression cho các layer đã có.

## Non-claims

- Chỉ SQLite file-backed, số nguyên đơn vị nhỏ với một currency cố định, không FX, PostgreSQL, ERP, broker hay mạng.
- Bằng chứng là interleaving hữu hạn có điều khiển (barrier, hook mất ack), không phải mọi lịch chạy, crash/power-loss hay exactly-once ngoài DB local.
- `VersionedRef` là provenance trong-process, không phải sandbox cho handler.
- Không có publish artifact/registry, scheduler/escalation tự động hay cam kết hiệu năng.
- Việc giao effect là at-least-once với dedup bền phía receiver; effect `FAILED` không "un-commit" action.
