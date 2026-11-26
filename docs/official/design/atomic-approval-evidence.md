# Atomic Approval Evidence

*Tài liệu bằng chứng thực nghiệm cho các tuyên bố runtime của OaC design. Thí nghiệm chạy một lần trên máy cục bộ ngày 2026-11-25 (UTC), dùng Python stdlib và SQLite; không cài đặt hạ tầng, không triển khai framework. Mã nguồn và hướng dẫn nằm tại [`experiments/atomic-approval/`](../../../experiments/atomic-approval/README.md).*

*Phạm vi: kiểm chứng ba cơ chế — guarded debit trong enlisted transaction, replay idempotent sau mất phản hồi, và từ chối strict atomic khi hai resource không share enlisted session. Đây là bằng chứng runtime cho **một interleaving xác định**, không phải chứng minh contract đúng cho mọi lịch chạy, không phải so sánh hiệu năng, và không phải tích hợp ERP.*

*Từ Sprint 4, framework có consumer mẫu chạy các cơ chế này trên chính API công khai và adapter SQLite của nó: [`examples/atomic_approval/`](../../../examples/atomic_approval/README.md), với kiểm thử tích hợp đọc lại DB cho commit, rollback, tranh budget, split binding và replay. Thí nghiệm dưới đây vẫn là bằng chứng độc lập, không bị thay thế bởi kiểm thử của framework.*

## Câu hỏi và phạm vi

Thí nghiệm trả lời ba câu hỏi hẹp, lấy từ các kịch bản có thể bác bỏ ở deep-dive 04 và quyết định ở framework design §7–§8:

1. Hai execution cùng quan sát một budget ban đầu, cùng xin vượt khả năng chi trả — guarded debit trong transaction có order và request ledger có chặn double-spend không?
2. Commit đã xảy ra nhưng caller mất phản hồi — retry cùng intent/key có tạo debit thứ hai không, và có trả lại đúng kết quả đã lưu không?
3. Khi hai resource không cùng một enlisted session — deployment binding có từ chối `Transaction.atomic()` **trước khi ghi nghiệp vụ** không?

Ngoài phạm vi: PostgreSQL/ERP thật, crash/power-loss, 2PC, saga/compensation, outbox, policy freshness, retention/prune của idempotency key, và kiểm thử tranh chấp cùng key đồng thời. Các giới hạn này được liệt kê lại ở cuối tài liệu.

## Môi trường chạy

| Thành phần | Giá trị |
| --- | --- |
| Hệ điều hành | Windows 11 |
| Python | 3.13.17 |
| SQLite (bundled) | 3.50.4 |
| Thư viện ngoài | Không có; chỉ `sqlite3`, `threading`, `hashlib`, `json` |
| Tiến trình | Một process; hai thread cho kịch bản tranh budget |
| Thư mục kết quả | `experiments/atomic-approval/.runs/<UTC stamp>/` (đã git-ignore) |

## Mô hình thí nghiệm

### Dữ liệu và transaction

Một file SQLite chứa ba bảng cho kịch bản 1–2:

- `budgets(id, balance, version)` — budget `B-001` khởi tạo 100.000, version 1;
- `purchase_orders(id, status, approved_amount, version)` — order khởi tạo `PENDING_APPROVAL`, version 1;
- `request_ledger(scope, request_key, intent_fingerprint, execution_id, status, result_json, recorded_at)` với khóa chính `(scope, request_key)`.

`scope` mô phỏng phạm vi `tenant / principal / action` (`tenant-demo/alice/procurement.approve_purchase_order`). `intent_fingerprint` là SHA-256 của JSON chuẩn hóa gồm action, action version, order id/version, budget id/version và amount. Ledger lưu cả `result_json` chứa before/after của budget và order.

Một attempt `invoke` chạy tuần tự: tra ledger theo `(scope, key)` → nếu có thì so fingerprint và replay hoặc từ chối misuse → nếu chưa có thì mở `BEGIN IMMEDIATE`, chạy guarded debit, guarded order transition, đọc after-state, insert ledger, commit. Guard-fail rollback rồi đọc lại budget để phân loại kết quả; không retry mù.

Guarded debit dùng đúng một câu lệnh:

```sql
UPDATE budgets
SET balance = balance - :amount, version = version + 1
WHERE id = :budget_id AND balance >= :amount AND version = :expected_version;
```

Attempt chỉ tiếp tục khi `rowcount == 1`. Order transition cũng có guard riêng:

```sql
UPDATE purchase_orders
SET status = 'APPROVED', approved_amount = :amount, version = version + 1
WHERE id = :order_id AND version = :expected_order_version
  AND status = 'PENDING_APPROVAL';
```

### Mất phản hồi và hai execution độc lập

"Mất phản hồi" được mô phỏng bằng một exception ném ra **sau khi `conn.commit()` trả về**, trước khi caller nhận kết quả. Đây không phải timeout mạng: hàng đã commit thật và caller thực sự không thấy response.

Kịch bản tranh budget dùng hai thread, mỗi thread mở connection riêng để đọc budget, gặp nhau ở `threading.Barrier`, rồi mỗi execution tự mở transaction riêng. Thread A commit trước; thread B chỉ bắt đầu write sau khi A hoàn tất, nhưng mang expected snapshot cũ (100.000, version 1).

### Split binding

Kịch bản 3 bind `PurchaseOrder` vào `orders.sqlite3` và `Budget` vào `erp_budget.sqlite3`, mỗi file một session identity riêng. `begin_strict_atomic` kiểm tra enlistment plan của các write trước khi chạy SQL và ném `NoSharedTransaction` nếu tập session identity có nhiều hơn một phần tử. Hai file cùng là SQLite nhưng không share transaction — đúng điểm "cùng brand không đồng nghĩa cùng transaction". `erp_budget.sqlite3` chỉ là **stand-in cấu trúc** cho ERP ledger; không có ERP client, network, hay nghiệp vụ ERP nào được chạy.

## Kết quả chạy

Run được ghi nhận: `experiments/atomic-approval/.runs/20261125T084641Z/`. Lệnh:

```bash
python experiments/atomic-approval/run_experiment.py
```

Kết quả cuối của script: `ALL ASSERTIONS PASSED`, exit code 0. Script dừng bằng assertion nếu bất kỳ invariant nào sai.

Các hàng dưới đây được đọc lại bằng một tiến trình Python riêng, không dùng output của script:

```bash
python -c "import sqlite3; c=sqlite3.connect('experiments/atomic-approval/.runs/20261125T084641Z/race.sqlite3'); print(c.execute('SELECT id,balance,version FROM budgets').fetchall()); print(c.execute('SELECT id,status,approved_amount,version FROM purchase_orders ORDER BY id').fetchall()); print(c.execute('SELECT scope,request_key,execution_id,status FROM request_ledger').fetchall())"
```

### Kịch bản 1 — mất phản hồi, retry cùng key, key misuse

Budget 100.000, order `PO-100` version 1, approval 40.000, key `req-0001`, execution `EX-0001`.

Sau khi commit rồi ném mất phản hồi, trạng thái đọc lại từ `approval.sqlite3`:

| Bảng | Hàng quan sát được |
| --- | --- |
| `budgets` | `('B-001', 60000, 2)` |
| `purchase_orders` | `('PO-100', 'APPROVED', 40000, 2)` |
| `request_ledger` | `scope=tenant-demo/alice/...`, `key=req-0001`, `execution=EX-0001`, `status=COMMITTED` |

`result_json` của ledger ghi `budgetBefore={balance: 100000, version: 1}`, `budgetAfter={balance: 60000, version: 2}`, `orderBefore={PENDING_APPROVAL, 1}`, `orderAfter={APPROVED, 2}`, fingerprint bắt đầu `fc65a01b3e196ead...`. Tổng debit theo ledger là 40.000, khớp `100000 − 60000 = 40000`.

Retry cùng scope/key/intent trả:

```text
[retry] status=COMMITTED reason=REPLAYED_FROM_LEDGER execution=EX-0001 deduplicated=True budget_balance=60000 budget_version=2
```

Trước và sau retry, cả ba bảng bằng nhau từng hàng; chuỗi `result_json` đã lưu cũng bằng nhau. Không có debit thứ hai, không có order transition thứ hai.

Gọi lại cùng key với amount 70.000 (fingerprint khác) trả:

```text
[conflict] status=DENIED reason=KEY_MISUSE execution=None deduplicated=False budget_balance=60000 budget_version=2
```

Trạng thái ba bảng vẫn y hệt sau lần từ chối. Tra ledger bằng cùng key nhưng scope `tenant-demo/bob/...` không tìm thấy hàng, xác nhận ledger được scope theo tenant/principal/action chứ không phải key đơn lẻ.

### Kịch bản 2 — hai execution tranh một budget

Hai order `PO-A`, `PO-B` cùng `PENDING_APPROVAL` version 1; mỗi order xin 80.000; budget 100.000.

Hai thread đều đọc được cùng snapshot trước khi bên nào commit:

```text
[observed] A snapshot=Snapshot(balance=100000, version=1) B snapshot=Snapshot(balance=100000, version=1)
[A] status=COMMITTED reason=COMMITTED execution=EX-A deduplicated=False budget_balance=20000 budget_version=2
[B] status=REJECTED reason=GUARD_FAILED_BUDGET_RECHECK_INSUFFICIENT_BUDGET execution=None deduplicated=False budget_balance=20000 budget_version=2
```

Trạng thái cuối đọc từ `race.sqlite3`:

| Bảng | Hàng quan sát được |
| --- | --- |
| `budgets` | `('B-001', 20000, 2)` |
| `purchase_orders` | `('PO-A', 'APPROVED', 80000, 2)`; `('PO-B', 'PENDING_APPROVAL', None, 1)` |
| `request_ledger` | chỉ `key=req-A`, `execution=EX-A`, `status=COMMITTED` |

Không có ledger row cho `req-B`, order B không đổi, và không có debit nào ngoài 80.000. Invariant kiểm tra: `total_debited = 80000 = 100000 − 20000`; số execution id duy nhất bằng số ledger row; order đã duyệt khớp đúng `PO-A`; `budgetBefore − amount = budgetAfter` trên từng ledger row.

B's guard trả `rowcount = 0` vì cả hai điều kiện cùng không còn đúng: `version = 1` đã cũ sau commit của A, và `balance >= 80000` cũng sai trên trạng thái sống (20.000). Lần chạy này không tách riêng để chứng minh predicate nào một mình đủ; nó chứng minh guard conjunctive từ chối plan cũ và B phải re-read rồi kết luận `REJECTED`, không ghi gì.

### Kịch bản 3 — split resource bị từ chối trước khi ghi

Binding plan có hai session:

```text
[binding] sessions=['sqlite:erp_budget.sqlite3', 'sqlite:orders.sqlite3']
[refused] NoSharedTransaction: strict atomic refused: writes would span separate sessions ['sqlite:erp_budget.sqlite3', 'sqlite:orders.sqlite3']
```

Hai database được chụp trước và sau lần từ chối; chúng bằng nhau:

| Database | Trạng thái sau từ chối |
| --- | --- |
| `orders.sqlite3` | budget `('B-001', 100000, 1)`; order `('PO-200', 'PENDING_APPROVAL', None, 1)`; ledger rỗng |
| `erp_budget.sqlite3` | budget `('B-001', 100000, 1)`; không order; ledger rỗng |

Không có debit, không có order transition, không có ledger row. Lỗi xảy ra ở deployment-binding check, trước business write, đúng contract "không downgrade lặng lẽ".

`erp_budget.sqlite3` là file SQLite cục bộ đóng vai ERP ledger. Thí nghiệm không chứng minh hành vi ERP, không gọi API ERP, và không có compensate/saga khi ERP từ chối.

## Invariant đã assert

Script không chỉ in số liệu; mỗi kết quả trên đi kèm assertion và lần chạy sẽ fail nếu sai:

1. Sau mất phản hồi: budget 60.000/version 2, order `APPROVED`/40.000/version 2, đúng một ledger row `EX-0001`; ledger amount khớp chênh lệch budget.
2. Retry: trạng thái ba bảng không đổi, `result_json` đã lưu không đổi, execution id và balance trả về khớp ledger, `deduplicated=True`.
3. Key misuse: `DENIED`/`KEY_MISUSE`, không sinh execution, không đổi bất kỳ hàng nào; lookup scope khác không thấy key.
4. Tranh budget: hai snapshot đọc được bằng nhau `(100000, 1)`; đúng một `COMMITTED`, một `REJECTED`; budget cuối 20.000/version 2; đúng một ledger row; đúng một order approved; tổng debit bằng chênh lệch budget.
5. Split binding: ném `NoSharedTransaction`; cả hai database bằng snapshot trước đó; ledger rỗng; budget ERP vẫn 100.000/version 1.
6. Ledger toàn cục: fingerprint trong row bằng fingerprint trong `result_json`; execution id trong row bằng execution id trong payload; mỗi ledger row ứng với đúng một order `APPROVED` cùng amount; không có hai row dùng chung execution id.

## Ý nghĩa cho thiết kế

Các quan sát ủng hộ những điểm sau trong deep-dive 04 và framework design:

- **Guarded debit là cơ chế giữ invariant, không phải revalidation suông.** Hai execution cùng đọc 100.000 nhưng chỉ một commit; bên thua nhận `rowcount = 0` và bị `REJECTED` sau re-read.
- **Budget, order và scoped ledger nằm trong một transaction.** Với A, cả ba thay đổi cùng commit; với B, rollback không để lại order/ledger rác.
- **Idempotency cần durable ledger, không chỉ key.** Sau khi response mất, retry tìm được kết quả đã lưu và không debit lại; cùng key nhưng intent khác bị từ chối trước business write.
- **Scope của key là một phần của contract.** Cùng key ở principal khác không dedup với nhau.
- **Strict atomic từ chối ở binding khi enlistment tách rời.** Hai file cùng brand vẫn bị `NoSharedTransaction`; từ chối xảy ra trước khi ghi.

Những điểm thí nghiệm **không** chứng minh:

- Hành vi của PostgreSQL (MVCC, isolation level, lock timeout) hay của ERP thật;
- crash/power-loss và khả năng phục hồi sau commit nhưng trước khi caller thấy kết quả;
- tranh chấp **cùng key đồng thời** (khóa chính ledger là lưới an toàn, nhưng race này không được điều khiển trong thí nghiệm);
- retention/prune của ledger, `UNKNOWN`, reconciliation với provider;
- outbox/effect, policy freshness, saga/compensation, durable execution;
- việc engine xác nhận một session vật lý đang mở tại execution time (thí nghiệm chỉ kiểm tra enlistment plan ở binding);
- mọi interleaving ngoài lịch A-commit-trước-B.

## Hạn chế bằng chứng

- **Một lần chạy, một interleaving.** Barrier bảo đảm hai lần đọc xảy ra trước khi ghi, nhưng thứ tự A rồi B được điều khiển bằng event. Đây không phải stress test, fuzz test, hay chứng minh cho mọi lịch chạy.
- **SQLite không phải PostgreSQL.** `BEGIN IMMEDIATE`, WAL và row-level behavior của SQLite không đại diện cho isolation/locking của PostgreSQL. Kết quả là bằng chứng cơ chế trong môi trường cục bộ, không phải bằng chứng production.
- **Mất phản hồi là mô phỏng trong process.** Exception ném sau `commit()` kiểm tra đúng tính durable của ledger, nhưng không mô phỏng TCP timeout, crash tiến trình, hay mất kết nối.
- **ERP chỉ là file stand-in.** Không có ERP client/network/credential; kịch bản 3 kiểm tra cấu trúc enlistment, không kiểm tra ngữ nghĩa ERP.
- **Binding check ở mức metadata.** Hàm từ chối dựa trên session identity của plan; nó không mở và xác nhận một transaction vật lý dùng chung. Đường pass của shared session không được chạy trong thí nghiệm này.
- **Chỉ dùng số nguyên.** Không có currency, quote version hay chuẩn hóa tiền tệ như contract `ApprovePurchaseOrder` đầy đủ.
- **Không kiểm tra đồng thời cùng key.** Hai request cùng key chạy song song có thể cùng miss ledger trước khi một bên insert; khóa chính sẽ chặn bên thứ hai, nhưng nhánh xử lý `IntegrityError`/reconciliation chưa được thực thi.
- **Không có đảm bảo về thời gian.** Timestamp trong ledger chỉ để quan sát, không tham gia invariant.

## Tái lập

Từ thư mục gốc repository, không cần cài package hay dịch vụ:

```bash
python experiments/atomic-approval/run_experiment.py
```

Muốn tách riêng từng lần chạy:

```bash
python experiments/atomic-approval/run_experiment.py --workdir experiments/atomic-approval/.runs/replay-01
```

Kỳ vọng:

- exit code 0 và dòng cuối `ALL ASSERTIONS PASSED`;
- `summary.json` trong thư mục run chứa cùng các giá trị đã nêu;
- các file `.sqlite3` đọc lại cho đúng hàng ở bảng trên;
- không có network, không có dependency, không sửa dữ liệu ngoài thư mục run.

Có thể xóa toàn bộ `experiments/atomic-approval/.runs/` để chạy lại từ đầu; thư mục này đã được git-ignore.

## Liên kết

- Mã và hướng dẫn chạy: [`experiments/atomic-approval/README.md`](../../../experiments/atomic-approval/README.md), [`run_experiment.py`](../../../experiments/atomic-approval/run_experiment.py).
- Kịch bản có thể bác bỏ: [`04-engine-boundary-and-adapter-capabilities.md`](../deep-dives/04-engine-boundary-and-adapter-capabilities.md) — mục "Falsifiable Scenarios and Spike (Not Executed)".
- Quyết định tương ứng: [`framework-design-v0.1.md`](./framework-design-v0.1.md) §7 (scoped UoW, guarded debit, strict atomic) và §8 (idempotency scope, ledger cùng transaction).

*Trạng thái: bằng chứng runtime cho các điều kiện đã nêu; không thay thế review thiết kế, kiểm thử PostgreSQL/ERP thật, hay chứng minh tính đúng cho mọi interleaving.*
