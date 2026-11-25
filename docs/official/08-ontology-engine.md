# Part VIII — Ontology Engine

*[← Part VII — Governance and Security Model](07-governance-and-security-model.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part IX — Adapter Architecture and Platform Independence →](09-adapter-architecture.md)*

<a id="sec-41"></a>

## 41. Vai trò của Engine

Sau quá trình thảo luận và điều chỉnh scope, chúng ta thống nhất rằng một Ontology Engine nên tồn tại trong framework.

Nếu chỉ có class definitions, decorators và metadata, OaC rất dễ trở thành schema modeling library.

Developer vẫn phải tự quyết định cách resolve object, execute Action, áp dụng permission, thực hiện validation và ghi audit.

Engine giúp biến những definitions thành operational behavior nhất quán.

Tuy nhiên, nó nên là **embeddable engine**, không phải một standalone enterprise execution platform.

<a id="sec-42"></a>

## 42. Các logical engine modules

| Module            | Trách nhiệm                                          |
| ----------------- | ---------------------------------------------------- |
| Object Engine     | Resolve identity, materialize objects, data mapping  |
| Query Engine      | Query abstraction, filtering, aggregation, traversal |
| Function Runtime  | Thực thi functions với execution context             |
| Action Engine     | Điều phối Action lifecycle                           |
| Policy Engine     | Policy evaluation và enforcement coordination        |
| Validation Engine | Kiểm tra schema, constraints, invariants             |
| Mutation Engine   | Điều phối structured state changes                   |
| Effect Engine     | Điều phối events, external effects                   |
| Audit Engine      | Chuẩn hóa execution records                          |

Không nhất thiết mỗi module phải là một class, service hoặc package độc lập. Có thể tổ chức chúng thành các subsystem logic bên trong một lightweight runtime.

<a id="sec-43"></a>

## 43. Engine chịu trách nhiệm gì và không chịu trách nhiệm gì?

| Engine          | Nên sở hữu                             | Delegate cho infrastructure       |
| --------------- | -------------------------------------- | --------------------------------- |
| Object Engine   | Logical identity, resolution contract  | Physical data storage             |
| Query Engine    | ObjectSet query semantics              | SQL execution, search indexes     |
| Policy Engine   | Enforcement boundary                   | IAM và policy evaluation backend  |
| Action Engine   | Lifecycle, invocation, context         | Durable workflow infrastructure   |
| Mutation Engine | Mutation contract, commit requirements | Native transaction implementation |
| Effect Engine   | Effect coordination, status semantics  | Message delivery infrastructure   |
| Audit Engine    | Audit schema và operation hooks        | Audit storage và log platform     |

Framework không cần cạnh tranh với SQLAlchemy, Temporal, Kafka, PostgreSQL hoặc enterprise IAM.

Nó cần điều phối những thành phần đó theo ontology semantics.

<a id="sec-44"></a>

## 44. Ví dụ một Action Engine tối giản

Đây là một implementation sketch để minh họa engine responsibility:

```
def invoke(action_type, raw_params, context):    action = registry.resolve_action(action_type)    params = validate_parameters(        action.parameters,        raw_params    )    authorize_invocation(        action,        params,        context    )    validate_capabilities(        action.requirements,        context.providers    )    with context.transaction():        resolved_params = resolve_references(            params,            context        )        validate_preconditions(            action,            resolved_params,            context        )        result = execute_handler(            action,            resolved_params,            context        )        validate_postconditions(            action,            result,            context        )        record_success(            action,            result,            context        )    return result
```

Đoạn code này minh họa một synchronous execution path với một transaction boundary. Nó chưa xử lý approval, failed execution logging, concurrency races, external effects hoặc distributed execution.

Điểm quan trọng là các lời gọi như `context.transaction()` có thể sử dụng SQLAlchemy hoặc một transaction provider khác.

Framework định nghĩa orchestration contract; adapter cung cấp infrastructure-specific implementation.

<a id="sec-45"></a>

## 45. Execution Modes

Cùng một Action contract có thể được hỗ trợ bởi nhiều execution mode.

**Common Action Contract**

Parameters · Policies · Preconditions · Effects

**Local**

In-process

Python application, synchronous execution.

**Remote**

Service / Worker

Execution thông qua API hoặc remote worker.

**Durable**

Workflow backend

Long-running, approval, persistent execution.

MVP chỉ cần ưu tiên local execution.

Remote và durable execution có thể được nghiên cứu sau, khi engine contracts đã đủ rõ.

Local execution cũng là runtime. Không có yêu cầu phải triển khai một Ontology Server chỉ để thực thi Actions.
