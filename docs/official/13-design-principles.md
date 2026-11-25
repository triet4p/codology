# Part XIII — Design Principles

*[← Part XII — Related Technologies and Design References](12-related-technologies.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part XIV — Research Questions and Open Problems →](14-research-questions.md)*

<a id="sec-66"></a>

## 66. Các nguyên tắc thiết kế nền tảng

Từ toàn bộ cuộc thảo luận, tôi tổng hợp thành 20 design principles. Một số là định hướng chúng ta đã thống nhất, một số là hệ quả kiến trúc nên tiếp tục được kiểm chứng.

| #   | Principle                | Ý nghĩa                                                                 |
| --- | ------------------------ | ----------------------------------------------------------------------- |
| P01 | **Code-first**           | Developer định nghĩa ontology bằng programming language quen thuộc.     |
| P02 | **Semantic-first**       | Thiết kế ý nghĩa của primitives trước khi thiết kế syntax.              |
| P03 | **Operational**          | Ontology mô tả cả business state và behavior.                           |
| P04 | **Storage-agnostic**     | Không bắt buộc RDF, graph database hoặc relational database.            |
| P05 | **Platform-agnostic**    | Có thể tích hợp vào nhiều hệ thống hiện có.                             |
| P06 | **Embeddable**           | Không yêu cầu triển khai một standalone platform.                       |
| P07 | **Typed**                | Objects, properties, relations, actions và functions có type contracts. |
| P08 | **Governed by design**   | Authorization và validation là thành phần nội tại.                      |
| P09 | **Controlled mutation**  | Business state changes đi qua governed operations.                      |
| P10 | **Introspectable**       | Metadata có thể được khám phá bởi human và machine.                     |
| P11 | **Composable**           | Domains và definitions có thể được kết hợp.                             |
| P12 | **Extensible**           | Có extension points và custom adapters.                                 |
| P13 | **Consumer-independent** | Human, application, automation và AI sử dụng chung semantics.           |
| P14 | **Infrastructure reuse** | Tận dụng engine và systems đã tồn tại.                                  |
| P15 | **Progressive adoption** | Có thể áp dụng từng phần thay vì migration toàn bộ.                     |
| P16 | **Versioned**            | Definitions và executable contracts có thể quản lý version.             |
| P17 | **Testable**             | Business behavior và governance có thể kiểm thử.                        |
| P18 | **Observable**           | Runtime operations có execution records và tracing.                     |
| P19 | **Interoperable**        | Có thể expose SDK, API, MCP hoặc export RDF.                            |
| P20 | **Developer-centric**    | Giảm effort và complexity khi xây dựng business layer.                  |

Ba nguyên tắc có thể trở thành triết lý xuyên suốt dự án:

> **Own the semantics, delegate the infrastructure.**

Framework sở hữu semantic contracts và orchestration cần thiết, nhưng tận dụng infrastructure hiện có.

> **Complexity belongs in the framework; simplicity belongs in the authoring layer.**

Developer nên tập trung mô tả nghiệp vụ, thay vì lặp lại infrastructure plumbing. Tuy nhiên, framework không nên che giấu các giới hạn consistency hoặc security mà developer cần biết.

> **Model once, consume everywhere.**

Một business domain được định nghĩa một lần và có thể được nhiều consumer sử dụng, trong phạm vi contracts và capabilities đã hỗ trợ.
