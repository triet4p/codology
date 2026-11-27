# Ví dụ miền cấp quyền hạ tầng giả lập

Ví dụ dựng **hai module** `access_control` + `security_audit` bằng API công khai của `codology`, compose qua Load, Link và Snapshot, rồi bind phần host và chạy trên SQLite file-backed. Đây là lát cắt đa miền ngoài duyệt đơn: object, typed refs, action cha/con, predicate `any_of`, role/permission, effect payload có kiểu, cùng schema/seed, resource mapping, delegation, authority và một session vật lý cho hai phần ghi với outbox. Effect chỉ ghi thông báo vào sink local, không cấp quyền hay phát hành chứng chỉ thật.

## Cấu trúc

- `access_control.py` — `GrantRequest`, `NotificationPayload`, `NotifyLocalSink`, `GrantAccess` và module sở hữu `AccessControl`. `GrantAccess` khai báo `commitRequirement = ATOMIC`, `calls = ("security_audit.record_session",)`, `effects = (NotifyLocalSink,)` và approval `any_of` theo `duration_minutes >= 60` hoặc `sensitivity == "CRITICAL"` với role `security_officer`.
- `security_audit.py` — `AuditSession`, action con `RecordSession` và module sở hữu `SecurityAudit`. Module này không import `access_control`.
- `model.py` — hai `ModuleDeclarations`, `load`, `link`, `snapshot`, cùng key `DefinitionKey` tường minh.
- `scenarios.py` — lỗi tham chiếu không export và một handler probe chứng minh Load/Link/Snapshot không chạy handler.
- `database.py` — schema SQLite, seed một request `PENDING` và một session `NEW`, cùng helper đọc business/version/ledger/outbox bằng connection độc lập.
- `wiring.py` — `Deployment` enlists hai resource ghi và `OUTBOX_RESOURCE` trong một session, `ResourceBinding`, `DelegationGrant`, `Principal`, `ReadGrant`, `HostAuthority` và `Host`/`open_host`/`install`.
- `consumer.py` — `query → row.as_ref() → invoke → approve → resume → relay`, chỉ gọi API công khai; không chứa ngưỡng, role, trạng thái nghiệp vụ hay SQL.
- `__main__.py` — entry point: mặc định là đường tĩnh, `--runtime` chạy các kịch bản SQLite có assert.

`access_control` tham chiếu `security_audit.session` bằng identity chuỗi trong `reads` và forward annotation trên handler; chỉ import module kia dưới `TYPE_CHECKING`, nên không có import vòng lúc chạy.

## Chạy ví dụ

Từ gốc repo, sau `uv sync`:

```bash
uv run python -m examples.break_glass_access
uv run python -m examples.break_glass_access --runtime
```

Đường tĩnh in definition đã Load kèm owner/version, cạnh đã kiểm tra ở Link của action cha và action con (`params.*`, `reads`, `writes`, `calls`, `effects`), entry Snapshot gồm permission, `commitRequirement`, role và hai nhánh `any_of`, rồi lỗi `NotExported` với module/identity/field.

Chế độ `--runtime` tạo DB riêng cho mỗi ca dưới `.tmp/break-glass-access/` và assert:

- Request 30 phút, không nhạy cảm: `COMMITTED` không cần approval; hai write (`grant_requests.status = GRANTED`, `audit_sessions.status = OPEN`, version 2), ledger và một outbox row commit cùng nhau; relay giao một thông báo local.
- Đúng ngưỡng `duration_minutes = 60` và ca nhạy cảm `CRITICAL` ở 15 phút: cả hai `AWAITING_APPROVAL`, business/version, ledger `AWAITING_APPROVAL`, outbox và decisions không đổi; relay không giao gì.
- Callback sai authority (principal ngoài role/permission): `DENIED`, không có decision, execution vẫn chờ, audit ghi một attempt.
- Approve hợp lệ: chưa commit, outbox vẫn rỗng; `resume` commit hai phần ghi, ledger và outbox trong một transaction.
- Replay cùng `request_key` và refs đã cấp: cùng execution, `deduplicated=True`, không ghi lại.
- Relay chỉ giao sau commit; gọi lại không giao thêm và không chạy lại handler.
- `bind_action()` từ chối deployment tách session bằng `NoSharedTransaction` trước khi mở transaction.

## Kiểm thử

```bash
uv run pytest -q tests/test_break_glass_access_example.py tests/test_break_glass_access_runtime.py
uv run pyright examples/break_glass_access tests/test_break_glass_access_example.py tests/test_break_glass_access_runtime.py
uv run ruff check examples/break_glass_access tests/test_break_glass_access_example.py tests/test_break_glass_access_runtime.py
```

`tests/test_break_glass_access_example.py` phủ đường tĩnh. `tests/test_break_glass_access_runtime.py` gọi API công khai cho từng ca và đối chiếu kết quả bằng connection SQLite độc lập, gồm cả ca binding tách session bị từ chối.

## Non-claims

- Chỉ SQLite file-backed một session vật lý; không có backend khác, HTTP/service/SDK/MCP, IAM/PKI, broker hay chứng chỉ thật.
- `duration_minutes` là `int` phút ở runtime; không có `Duration`, chuyển đổi đơn vị tùy ý hay FX.
- Effect chỉ ghi một thông báo local; không cấp quyền, không phát hành chứng chỉ, không giao exactly-once ngoài DB local.
- `Principal`, `ReadGrant`, role/permission và `HostAuthority` là giá trị host tự cấp trong ví dụ, không phải hệ thống danh tính hay phân quyền thật.
- Không có scheduler/escalation, approval delivery, registry/publish pipeline hay migration pending.
- Không có gate latency, throughput hay coverage.
