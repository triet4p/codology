# Ví dụ CLI consumer độc lập của `ApprovePurchaseOrder`

Package này là **consumer thứ hai** của action `procurement.approve_purchase_order@2.0.0`: một CLI gọi trực tiếp các cổng công khai của `codology`, tự diễn giải envelope trả về, và không import `examples/conditional_approval/consumer.py` (consumer mẫu của Sprint 5). Nó dùng lại đúng host contract của ví dụ đó — declaration, graph, deployment một session, principal, read grant và authority live — nên chứng minh một caller khác dùng cùng identity/version mà không chép luật nghiệp vụ hay phân quyền.

CLI không chứa ngưỡng duyệt, bảng role/quyền, logic giữ ngân sách, SQL hay hàm dựng fingerprint. Nó đọc row qua `query`, lấy `VersionedRef` bằng `row.as_ref()`, gọi `invoke`, rồi dùng đúng `callback_key` và `intent_fingerprint` do engine phát hành để `approve`; `resume`, `reconcile`/`reconcile_execution` và `deliver_committed` là các cổng công khai còn lại. Việc bind và cấp principal/grant nằm ở `host.py` (host-owned).

## Cấu trúc

- `host.py` — mở host của ví dụ conditional-approval, ánh xạ tên caller (`requester`, `approver`, `outsider`) và resource (`orders`, `budgets`) sang giá trị do host cấp; không có policy.
- `envelopes.py` — chuyển `ActionResult`, `DecisionResult`, page, delivery và effect state thành JSON, kèm bước gọi kế tiếp khi kết quả chưa chung thẩm.
- `__main__.py` — parser lệnh, một envelope JSON cho mỗi lần chạy, exit code 0/2.

## Chạy

Từ gốc repo sau `uv sync`:

```bash
uv run python -m examples.purchase_order_cli install --db .tmp/purchase-order-cli/orders.sqlite3
uv run python -m examples.purchase_order_cli query --db .tmp/purchase-order-cli/orders.sqlite3 --resource orders --status PENDING
uv run python -m examples.purchase_order_cli invoke --db .tmp/purchase-order-cli/orders.sqlite3 \
  --order PO-1 --budget B-1 \
  --reason "approved after budget check" \
  --request-key tenant-a:alice:approve:PO-1:001
```

`query` chỉ trả row mà read grant của caller phủ: seed có `PO-1` (tenant-a) và `PO-9` (tenant-b, cùng scope), nhưng page chỉ có `PO-1`; `budgets` tương tự với `B-1`. Row không có trong page không thể lấy ref.

`invoke` in envelope `AWAITING_APPROVAL` cho đơn 120000 (ngưỡng nằm ở declaration, không ở CLI), kèm `refs.order.instance_version` = `1` chứng minh ref lấy từ row, `required_approval.callback_key`/`intent_fingerprint` do engine cấp, và `next` chỉ bước `approve`. Ở thời điểm này DB giữ đơn `PENDING` v1, ngân sách `reserved = 0` v1, outbox rỗng.

Lấy các giá trị từ envelope rồi duyệt hợp lệ:

```bash
uv run python -m examples.purchase_order_cli approve --db .tmp/purchase-order-cli/orders.sqlite3 \
  --as approver --execution-id <execution_id> \
  --callback-key <callback_key> --fingerprint <intent_fingerprint> \
  --reason "budget confirmed"
```

`--as outsider` (principal rỗng quyền, authority rỗng do host cấp) trả `DENIED` và không ghi decision nào; execution vẫn `AWAITING_APPROVAL`. `approve` hợp lệ trả `attempt.code = AWAITING_APPROVAL`, `attempt.reason = APPROVED`, `decision.decision = APPROVE` và **không** commit nghiệp vụ.

`approve --reason` phải không rỗng: cửa decision lưu reason và `resume` đọc lại decision đó, nên CLI từ chối chuỗi rỗng trước khi gọi engine (exit 2) thay vì để bản ghi không đọc được. Đây là giới hạn của host/CLI, không phải API lõi mới.

```bash
uv run python -m examples.purchase_order_cli resume --db .tmp/purchase-order-cli/orders.sqlite3 \
  --execution-id <execution_id> --callback-key <callback_key>
uv run python -m examples.purchase_order_cli relay --db .tmp/purchase-order-cli/orders.sqlite3 \
  --execution-id <execution_id>
uv run python -m examples.purchase_order_cli reconcile --db .tmp/purchase-order-cli/orders.sqlite3 \
  --request-key tenant-a:alice:approve:PO-1:001
```

`resume` trả `COMMITTED`, và DB đổi trong cùng transaction: đơn `APPROVED` v2, ngân sách `reserved = 120000` v2, ledger `COMMITTED`, một outbox row và một resume outcome. `relay` giao đúng một thông báo local; gọi lại không giao thêm. `reconcile` dùng principal đọc bản ghi do host cấp (`execution.read`), không phải principal của `--as`, nên lệnh này không nhận `--as`. Theo key gốc trả cùng `execution_id`, `deduplicated = true`, và không tăng version hay giữ ngân sách thêm.

Gọi lại `invoke` với cùng `request_key` **khi execution còn chờ** trả cùng execution (`deduplicated = true`) và không ghi gì thêm. Sau commit, CLI luôn query lại nên ref mang version mới: `invoke` cùng key trả `DENIED`/`KEY_MISUSE` do intent khác; hãy dùng `reconcile --request-key` (hoặc `--execution-id`) để tra cứu execution gốc.

### Khi commit chưa rõ

`resume --simulate-lost-ack before|after` dùng hook fault-injection **do host cung cấp** (`wiring.InterruptedProvider`) để mô phỏng mất ack commit; CLI chỉ chuyển adapter đó vào `resume`. Kết quả `attempt.code = UNKNOWN` kèm `next.command = reconcile`, `execution_id` gốc và ghi chú giữ nguyên request key:

```json
{"command": "reconcile", "execution_id": "<id>",
 "note": "the commit outcome is not confirmed: reconcile with the original request key or execution id; do not mint a new request key from a timeout."}
```

Chạy `reconcile --execution-id <id>` (hoặc `--request-key` gốc) thấy `COMMITTED`, rồi `resume` lại trả `COMMITTED` với `deduplicated = true`; ngân sách vẫn chỉ giữ một lần và không có key mới nào được sinh.

## Lệnh và envelope

| Lệnh | Tham số chính | Kết quả |
| --- | --- | --- |
| `install` | `--db`, `--amount`, `--status`, `--ceiling` | Tạo fixture SQLite và bảng relay |
| `query` | `--db`, `--as`, `--resource orders\|budgets`, `--id`, `--status`, `--limit` | `page.count`, `page.rows`, `next_cursor` |
| `invoke` | `--order`, `--budget`, `--reason`, `--request-key` | `result.attempt`, `result.execution`, `refs`, `next` |
| `approve` | `--as`, `--execution-id`, `--callback-key`, `--fingerprint`, `--reason` | `result.attempt`, `result.decision`, `next` |
| `resume` | `--execution-id`, `--callback-key`, `--simulate-lost-ack` | `result.attempt`, `result.execution`, `next` |
| `reconcile` | `--request-key` hoặc `--execution-id` | `lookup`, `result.attempt`, `result.execution` |
| `relay` | `--execution-id` (tùy chọn) | `deliveries`, `effects` |

Mỗi lần chạy in đúng một JSON object. Exit code `0` cho mọi envelope hợp lệ — kể cả `AWAITING_APPROVAL`, `DENIED`, `UNKNOWN` — và `2` cho lỗi dùng lệnh hoặc thiếu quyền/không thấy row/không mở được fixture.

## Kiểm thử xuyên lớp

```bash
uv run pytest -q tests/test_purchase_order_cli.py
```

Sáu ca chạy CLI bằng subprocess trên fixture SQLite thật; mỗi envelope được đối chiếu bằng connection SQLite độc lập:

- `query` chỉ thấy `PO-1`/`B-1` dù seed còn row tenant khác.
- `invoke` từ ref của row trả pending, không ghi đơn/ngân sách/outbox, ledger `AWAITING_APPROVAL`.
- `approve --as outsider` bị `DENIED`, pending giữ nguyên, không có decision; approve hợp lệ sau đó vẫn đi tiếp.
- approve rồi resume commit hai write + ledger + outbox; relay giao một lần, gọi lại rỗng.
- replay `invoke` cùng key và `reconcile` theo key gốc trả cùng execution, `deduplicated`, không tăng version/giữ ngân sách thêm.
- replay `invoke` chỉ được kiểm ở trạng thái chờ; sau commit chỉ `reconcile` với key/id gốc là đường tra cứu có bằng chứng.
- mất ack commit trả `UNKNOWN` kèm hướng dẫn `reconcile` bằng id/key gốc; reconcile thấy `COMMITTED`, retry idempotent.

## Non-claims

- Chỉ SQLite file-backed một session; principal, grant, authority, role và dữ liệu seed là giá trị host-coded của ví dụ, không phải IAM/PKI.
- CLI không tự tính `request_key`, `intent_fingerprint` hay `callback_key`; mọi giá trị đó đến từ envelope của engine và được truyền lại nguyên vẹn (nhập từ tham số dòng lệnh).
- `--as outsider` chỉ chọn một principal/authority rỗng do host cấp để chứng minh nhánh deny; không phải mô hình phân quyền.
- `--simulate-lost-ack` là fault injection của host cho ca commit chưa rõ, không phải hành vi mặc định.
- Relay at-least-once với dedup bền ở receiver; không exactly-once ngoài DB local. Không HTTP/service/SDK/MCP, không scheduler/escalation, không cam kết hiệu năng.
- Đối chiếu chữ ký API và envelope với [hướng dẫn author §7](../../docs/author-extension-guide.md).
