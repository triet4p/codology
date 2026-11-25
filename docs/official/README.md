# Ontology as Code (OaC) — Documentation Index

Bộ tài liệu này được tách từ bản tổng hợp [`init.md`](../research/init.md) thành các chương đọc độc lập trong `docs/official/`. Bản gốc `docs/research/init.md` được giữ nguyên, không chỉnh sửa, và tiếp tục là nguồn lưu trữ (archival source).

- **Tài liệu nguồn:** [init.md](../research/init.md) — *Conceptual Architecture & Research Foundation v0.1*
- **Nội dung:** phần giới thiệu, 19 phần với 91 mục được đánh số, và kết luận.
- **Quy ước:** tiêu đề tài liệu và tiêu đề chương bằng tiếng Anh; nội dung và tiêu đề mục giữ nguyên tiếng Việt.

## Framework Design

- **Đọc trước: [Architecture Direction](design/architecture-direction.md).** Thiết kế khuyến nghị ở mức kiến trúc: business layer chịu trách nhiệm gì, nằm ở đâu và có thể hứa điều gì với ứng dụng.
- Khi bắt đầu triển khai: [Framework Design v0.1](design/framework-design-v0.1.md) và [Atomic Approval Evidence](design/atomic-approval-evidence.md) là phụ lục kỹ thuật, không phải API đã chốt.
- **Hợp đồng author (Nấc 1–2):** [Developer Contract](design/developer-contract.md) — khai báo tối thiểu cho action đồng bộ đơn module, leo thang liên module nguyên tử `Procurement` → `Finance` bằng thuộc tính cộng thêm, bề mặt `HandlerCtx`/scoped UoW và ma trận lỗi load/link/binding.

## Architecture Deep Dives

Bốn nghiên cứu bổ sung dùng cùng ca `ApprovePurchaseOrder`. Đây là các khuyến nghị để kiểm chứng, không thay thế tài liệu nền hoặc mặc nhiên trở thành ADR.

1. [Static Architecture and Definition Lifecycle](deep-dives/01-static-architecture-and-definition-lifecycle.md)
2. [Developer Workflow and Model Evolution](deep-dives/02-developer-workflow-and-model-evolution.md)
3. [Action Contract and Business Workflow](deep-dives/03-action-contract-and-business-workflow.md)
4. [Engine Boundary and Adapter Capabilities](deep-dives/04-engine-boundary-and-adapter-capabilities.md)

## Chapters

| # | Chapter | Sections |
| --- | --- | --- |
| — | [Introduction](00-introduction.md) | — |
| I | [Part I — Project Vision](01-project-vision.md) | 1–4 |
| II | [Part II — Ontology as Code](02-ontology-as-code.md) | 5–8 |
| III | [Part III — Project Scope and Product Positioning](03-scope-and-product-positioning.md) | 9–12 |
| IV | [Part IV — System Architecture](04-system-architecture.md) | 13–16 |
| V | [Part V — Ontology Meta-Model](05-ontology-meta-model.md) | 17–25 |
| VI | [Part VI — Action Model: The Core of Operational Ontology](06-action-model.md) | 26–34 |
| VII | [Part VII — Governance and Security Model](07-governance-and-security-model.md) | 35–40 |
| VIII | [Part VIII — Ontology Engine](08-ontology-engine.md) | 41–45 |
| IX | [Part IX — Adapter Architecture and Platform Independence](09-adapter-architecture.md) | 46–49 |
| X | [Part X — Developer Experience](10-developer-experience.md) | 50–57 |
| XI | [Part XI — AI Agent Integration](11-ai-agent-integration.md) | 58–62 |
| XII | [Part XII — Related Technologies and Design References](12-related-technologies.md) | 63–65 |
| XIII | [Part XIII — Design Principles](13-design-principles.md) | 66 |
| XIV | [Part XIV — Research Questions and Open Problems](14-research-questions.md) | 67–70 |
| XV | [Part XV — Research Roadmap](15-research-roadmap.md) | 71–76 |
| XVI | [Part XVI — Proof of Concept and MVP](16-proof-of-concept-and-mvp.md) | 77–82 |
| XVII | [Part XVII — Evaluation and Success Criteria](17-evaluation-and-success-criteria.md) | 83–86 |
| XVIII | [Part XVIII — Project Foundation Summary](18-project-foundation-summary.md) | 87–89 |
| XIX | [Part XIX — Recommended Next Step](19-recommended-next-step.md) | 90–91 |
| — | [Conclusion](20-conclusion.md) | — |

## Subject Index

### Introduction

- [Ontology as Code (OaC)](00-introduction.md)

### Part I — Project Vision

- [1. Bối cảnh và động lực](01-project-vision.md#sec-1)
- [2. Vấn đề với cách xây dựng Ontology truyền thống](01-project-vision.md#sec-2)
- [3. Định nghĩa lại khái niệm Ontology](01-project-vision.md#sec-3)
- [4. Ontology không nhất thiết là Knowledge Graph](01-project-vision.md#sec-4)

### Part II — Ontology as Code

- [5. Ý tưởng Ontology as Code](02-ontology-as-code.md#sec-5)
- [6. Tại sao OOP là một abstraction tự nhiên?](02-ontology-as-code.md#sec-6)
- [7. Không nên đồng nhất Ontology với OOP](02-ontology-as-code.md#sec-7)
- [8. Code-first, nhưng không nhất thiết code-only](02-ontology-as-code.md#sec-8)

### Part III — Project Scope and Product Positioning

- [9. Mục đích thực sự của dự án](03-scope-and-product-positioning.md#sec-9)
- [10. Platform và Framework khác nhau thế nào?](03-scope-and-product-positioning.md#sec-10)
- [11. Framework có cần Runtime không?](03-scope-and-product-positioning.md#sec-11)
- [12. Scope và Non-goals](03-scope-and-product-positioning.md#sec-12)

### Part IV — System Architecture

- [13. High-level Reference Architecture](04-system-architecture.md#sec-13)
- [14. Kiến trúc tĩnh và kiến trúc động](04-system-architecture.md#sec-14)
- [15. Logical planes](04-system-architecture.md#sec-15)
- [16. Phân chia trách nhiệm giữa Framework và Developer](04-system-architecture.md#sec-16)

### Part V — Ontology Meta-Model

- [17. Meta-model là gì và tại sao quan trọng?](05-ontology-meta-model.md#sec-17)
- [18. Candidate ontology primitives](05-ontology-meta-model.md#sec-18)
- [19. Object Type](05-ontology-meta-model.md#sec-19)
- [20. Object Identity và Object Reference](05-ontology-meta-model.md#sec-20)
- [21. Property và Value Type](05-ontology-meta-model.md#sec-21)
- [22. Link Type](05-ontology-meta-model.md#sec-22)
- [23. Interface](05-ontology-meta-model.md#sec-23)
- [24. Object Set và Query Model](05-ontology-meta-model.md#sec-24)
- [25. Functions](05-ontology-meta-model.md#sec-25)

### Part VI — Action Model: The Core of Operational Ontology

- [26. Tại sao Action không đơn giản là Function?](06-action-model.md#sec-26)
- [27. Anatomy of an Action](06-action-model.md#sec-27)
- [28. Action Definition, Implementation và Engine](06-action-model.md#sec-28)
- [29. Action Lifecycle](06-action-model.md#sec-29)
- [30. ActionExecution như một thực thể có identity](06-action-model.md#sec-30)
- [31. Mutation Plan](06-action-model.md#sec-31)
- [32. Transaction và Consistency](06-action-model.md#sec-32)
- [33. Effects và Failure Handling](06-action-model.md#sec-33)
- [34. Action Composition](06-action-model.md#sec-34)

### Part VII — Governance and Security Model

- [35. Governance là thành phần nội tại của Ontology](07-governance-and-security-model.md#sec-35)
- [36. Principal và Execution Context](07-governance-and-security-model.md#sec-36)
- [37. Permission Model](07-governance-and-security-model.md#sec-37)
- [38. Authorization và Business Validation là hai khái niệm khác nhau](07-governance-and-security-model.md#sec-38)
- [39. Query-time security](07-governance-and-security-model.md#sec-39)
- [40. Audit và Provenance](07-governance-and-security-model.md#sec-40)

### Part VIII — Ontology Engine

- [41. Vai trò của Engine](08-ontology-engine.md#sec-41)
- [42. Các logical engine modules](08-ontology-engine.md#sec-42)
- [43. Engine chịu trách nhiệm gì và không chịu trách nhiệm gì?](08-ontology-engine.md#sec-43)
- [44. Ví dụ một Action Engine tối giản](08-ontology-engine.md#sec-44)
- [45. Execution Modes](08-ontology-engine.md#sec-45)

### Part IX — Adapter Architecture and Platform Independence

- [46. Core + Adapter](09-adapter-architecture.md#sec-46)
- [47. Provider Contracts](09-adapter-architecture.md#sec-47)
- [48. Capability Model](09-adapter-architecture.md#sec-48)
- [49. Progressive Adoption](09-adapter-architecture.md#sec-49)

### Part X — Developer Experience

- [50. Developer Experience là mục tiêu cốt lõi](10-developer-experience.md#sec-50)
- [51. Developer-facing API](10-developer-experience.md#sec-51)
- [52. Repository Organization](10-developer-experience.md#sec-52)
- [53. Ontology Development Lifecycle](10-developer-experience.md#sec-53)
- [54. Static Validation](10-developer-experience.md#sec-54)
- [55. Semantic Diff](10-developer-experience.md#sec-55)
- [56. Ontology Visualization](10-developer-experience.md#sec-56)
- [57. Testing](10-developer-experience.md#sec-57)

### Part XI — AI Agent Integration

- [58. AI là consumer tự nhiên của Ontology](11-ai-agent-integration.md#sec-58)
- [59. Ontology như một Contract cho AI](11-ai-agent-integration.md#sec-59)
- [60. Dynamic Tool Discovery](11-ai-agent-integration.md#sec-60)
- [61. Ontology-based MCP Integration](11-ai-agent-integration.md#sec-61)
- [62. AI Safety tại Action Boundary](11-ai-agent-integration.md#sec-62)

### Part XII — Related Technologies and Design References

- [63. Không cần phát minh lại từng thành phần](12-related-technologies.md#sec-63)
- [64. Các design references](12-related-technologies.md#sec-64)
- [65. Điều chúng ta thực sự cần thiết kế](12-related-technologies.md#sec-65)

### Part XIII — Design Principles

- [66. Các nguyên tắc thiết kế nền tảng](13-design-principles.md#sec-66)

### Part XIV — Research Questions and Open Problems

- [67. Những gì chúng ta đã thống nhất](14-research-questions.md#sec-67)
- [68. Những gì chưa được quyết định](14-research-questions.md#sec-68)
- [69. Độ phức tạp của từng subsystem](14-research-questions.md#sec-69)
- [70. Những architectural risks cần tránh](14-research-questions.md#sec-70)

### Part XV — Research Roadmap

- [71. Hướng nghiên cứu tổng thể](15-research-roadmap.md#sec-71)
- [72. Research Track 1 — Ontology Landscape](15-research-roadmap.md#sec-72)
- [73. Research Track 2 — Ontology Meta-model](15-research-roadmap.md#sec-73)
- [74. Research Track 3 — Action Semantics](15-research-roadmap.md#sec-74)
- [75. Research Track 4 — Authoring Language và Developer Experience](15-research-roadmap.md#sec-75)
- [76. Research Track 5 — Engine Contracts](15-research-roadmap.md#sec-76)

### Part XVI — Proof of Concept and MVP

- [77. Mục đích của MVP](16-proof-of-concept-and-mvp.md#sec-77)
- [78. Domain đề xuất: Procurement](16-proof-of-concept-and-mvp.md#sec-78)
- [79. Một execution scenario hoàn chỉnh](16-proof-of-concept-and-mvp.md#sec-79)
- [80. Minimal MVP Scope](16-proof-of-concept-and-mvp.md#sec-80)
- [81. Proposed Reference Stack](16-proof-of-concept-and-mvp.md#sec-81)
- [82. Minimal package architecture](16-proof-of-concept-and-mvp.md#sec-82)

### Part XVII — Evaluation and Success Criteria

- [83. Làm thế nào để chứng minh framework có giá trị?](17-evaluation-and-success-criteria.md#sec-83)
- [84. Evaluation Dimensions](17-evaluation-and-success-criteria.md#sec-84)
- [85. Candidate Acceptance Tests](17-evaluation-and-success-criteria.md#sec-85)
- [86. North Star](17-evaluation-and-success-criteria.md#sec-86)

### Part XVIII — Project Foundation Summary

- [87. Project Charter v0.1](18-project-foundation-summary.md#sec-87)
- [88. Toàn bộ ý tưởng trong một sơ đồ](18-project-foundation-summary.md#sec-88)
- [89. Bản chất của thứ chúng ta muốn xây](18-project-foundation-summary.md#sec-89)

### Part XIX — Recommended Next Step

- [90. Bước nghiên cứu tiếp theo](19-recommended-next-step.md#sec-90)
- [91. Trạng thái hiện tại của dự án](19-recommended-next-step.md#sec-91)

### Conclusion

- [Conclusion](20-conclusion.md)

## Preservation Notes

- Bản gốc dùng Markdown bị escape; bản tách đã khôi phục heading, bảng, danh sách, blockquote và code fence.
- Các ví dụ hoặc sơ đồ nhiều dòng đã bị phẳng hóa trong bản gốc được giữ nguyên nội dung và thứ tự; bố cục không được phục dựng lại.
- Phần thân giữ nguyên nội dung tiếng Việt; chỉ bổ sung tiêu đề chương tiếng Anh và điều hướng.

## Archival Source

- [`docs/research/init.md`](../research/init.md) — bản tổng hợp gốc, được giữ nguyên không chỉnh sửa.
