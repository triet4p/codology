# Ví dụ thực thi: query → ref → invoke

Ví dụ chạy được trên API công khai của `codology` và adapter SQLite thật. Một consumer đọc đơn đang chờ duyệt qua `query`, lấy `VersionedRef[PurchaseOrder]` từ `row.as_ref()`, rồi gọi `invoke` cho `ApprovePurchaseOrder@1.1.0` nấc 2. Đơn được duyệt và ngân sách được giữ trong cùng một transaction vật lý, hoặc cả hai không đổi.

Ví dụ này **không** chạy declaration nấc 3 trong `examples/procurement_finance/procurement.py`. Nó dùng contract nấc 2 ở `examples/procurement_finance/runtime.py`: không `approval`, không `effects`, handler thật chạy trong `HandlerCtx`.

## Cấu trúc

- `database.py` — schema SQLite cho `purchase_orders`, `budgets`, `request_ledger` và dữ liệu seed hai tenant. Mỗi lần chạy tạo file mới.
- `wiring.py` — host configuration: Load/Link/Snapshot graph, `Deployment` một session, `bind_action`, adapter, principal và read grant. Không có luật nghiệp vụ.
- `consumer.py` — đúng đường consumer: `find_orders`/`find_budget` gọi `query`, `approve` gọi `invoke` với ref do row phát hành. Không tự kiểm quyền, không tự tính ngân sách, không SQL.
- `__main__.py` — entry point in ra kết quả quan sát được và assert từng kỳ vọng.

## Chạy

Từ thư mục gốc repo, sau `uv sync`:

```bash
uv run python -m examples.atomic_approval
```

Mặc định database là `.tmp/atomic_approval/approval.sqlite3` (đã git-ignore). Có thể truyền đường dẫn khác từ Python:

```python
from pathlib import Path
from examples.atomic_approval.__main__ import main

raise SystemExit(main(Path(".tmp/atomic_approval/other.sqlite3")))
```

Script in ra, theo thứ tự:

- query `PENDING_APPROVAL` đã áp policy (count trước phân trang) và budget nhìn thấy được;
- `invoke` trả `COMMITTED`, execution id, child revision `finance.reserve_budget@1.0.0`, hai write cùng một transaction và `rowcount=1`;
- replay cùng `request_key`/intent trả `deduplicated=True`, `writes=0`, cùng execution id;
- `reconcile` đọc bản ghi đã commit qua connection mới;
- query sau commit: PO-1 đã `APPROVED` ở version 2, PO-2 vẫn `PENDING_APPROVAL`, PO-9 của tenant khác không xuất hiện;
- các nhánh từ chối: `ReadDenied`, query ngoài scope trả 0 row/count, traversal chưa hỗ trợ trả `UnsupportedSecureQuery`, invoke thiếu quyền trả `DENIED` không có execution, split binding trả `NoSharedTransaction`.

Kết thúc bằng `ALL CHECKS PASSED` và exit code 0. Một assertion sai làm script thoát khác 0, nên ví dụ không thể âm thầm báo thành công khi hành vi đổi.

## Kiểm thử tích hợp

`tests/test_atomic_approval_example.py` chạy chính các hàm consumer ở trên và đọc lại dữ liệu bằng connection độc lập:

| Ca | Bằng chứng |
| --- | --- |
| Commit | Một transaction id cho cả hai write; order `APPROVED`/40.000/version 2, budget reserved 40.000/version 2, một hàng ledger `COMMITTED` khớp execution id |
| Read denial | Principal không có quyền nhận `ReadDenied`; query ngoài scope trả 0 row và count 0; traversal chưa pushdown bị từ chối |
| Invoke denial | Thiếu `purchase_order.approve` trả `DENIED`, `execution=None`, DB và ledger không đổi |
| Split binding | Hai enlistment khác session bị `NoSharedTransaction` trước khi có write nào |
| Rollback | Lỗi sau write đầu tiên trước commit để lại order/budget nguyên trạng và không có hàng ledger |
| Race | Hai đơn tranh một budget chỉ đủ một khoản: đúng một `COMMITTED`, bên còn lại `StalePlan`/`REJECTED`, reserved không vượt ceiling |
| Replay | Mất phản hồi: `reconcile` qua connection mới và replay cùng key trả cùng execution id, `deduplicated=True`, không ghi thêm; intent khác cùng key bị `KEY_MISUSE` |
| Hạ tầng giao dịch | Provider không mở đúng session, `BEGIN IMMEDIATE` timeout và commit mất xác nhận trả `UNKNOWN` không execution; DB/ledger chỉ đổi khi commit thực sự durable và `reconcile` tra được kết quả đó |

```bash
uv run pytest tests/test_atomic_approval_example.py -q
```

## Tập query được hỗ trợ

Adapter đầu chỉ nhận:

- so sánh `==`, `!=`, `>`, `>=`, `<`, `<=` trên cột đã map và `all_of` của chúng;
- giá trị `str`, `int`, `None` hoặc `MinorMoney`;
- sort một cột tường minh, khóa làm tie-break;
- tenant/scope do grant quy định, áp trong cùng `WHERE` trước phân trang và count.

Traversal, predicate ngoài tập trên, cursor của query khác và definition không có mapping đọc đều fail closed bằng `UnsupportedSecureQuery`, `InvalidCursor` hoặc lỗi tương ứng; không trả dữ liệu từng phần.

## Non-claims

- Chỉ SQLite file-backed và một currency (`USD`), không FX, PostgreSQL hay ERP.
- Chỉ nấc 2 đồng bộ: không `approval`, callback/resume, effect delivery, outbox hay publish artifact.
- Lỗi hạ tầng cửa giao dịch trả `UNKNOWN` không execution, không phải `FAILED`; lifecycle terminal `FAILED`, effect và escalation tự động chưa thuộc phạm vi.
- Race được chứng minh trên một interleaving xác định với hai thread và `BEGIN IMMEDIATE`; không phải mọi lịch chạy hay crash/power-loss.
- `VersionedRef` là provenance trong-process, không phải sandbox; handler chạy trong process vẫn có thể chạm host capability ngoài `ctx`.
- Ví dụ không chứng minh transaction chung cho backend khác SQLite; bằng chứng thực nghiệm độc lập vẫn ở [`docs/official/design/atomic-approval-evidence.md`](../../docs/official/design/atomic-approval-evidence.md).
