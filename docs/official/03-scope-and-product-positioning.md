# Part III — Project Scope and Product Positioning

*[← Part II — Ontology as Code](02-ontology-as-code.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part IV — System Architecture →](04-system-architecture.md)*

<a id="sec-9"></a>

## 9. Mục đích thực sự của dự án

Trong quá trình trao đổi, chúng ta đã điều chỉnh một điểm rất quan trọng.

Ban đầu, ý tưởng dễ bị mở rộng thành việc xây dựng một standalone ontology platform tương tự một phần Palantir Foundry.

Tuy nhiên, mục tiêu bạn xác định là:

> Giúp developer xây dựng ontology/business layer dễ dàng hơn trên bất kỳ platform nào, thay vì phát triển một sản phẩm chạy độc lập.

Do đó, dự án nên được định vị là một **developer framework**, không phải data platform hay enterprise ontology management platform.

Working definition của dự án:

> Ontology as Code is a code-first developer framework for defining, composing, validating and executing governed operational business models across existing applications, data platforms and AI systems.

Hoặc ngắn gọn hơn:

> A framework for building business layers as code.

<a id="sec-10"></a>

## 10. Platform và Framework khác nhau thế nào?

Hai hướng phát triển khác nhau

**Standalone Platform**

Apps / AI Agents

Ontology Platform

Admin UI

Ontology Server

Storage

IAM

Execution Service

Monitoring

Deployment

External Systems

Doanh nghiệp sử dụng một platform mới.

**Developer Framework**

Existing System

Apps / AI Agents

Business Layer

Developer's Ontology

OaC Framework

Embedded Engine

Adapters

Existing DB, IAM, APIs, Events, Workflows

Developer sử dụng framework trong hệ thống hiện tại.

Framework không sở hữu toàn bộ hệ thống. Developer sở hữu hệ thống và quyết định infrastructure, deployment architecture cũng như integration strategy.

<a id="sec-11"></a>

## 11. Framework có cần Runtime không?

Chúng ta đã đi qua ba hướng suy nghĩ:

| Hướng                             | Đánh giá                                            |
| --------------------------------- | --------------------------------------------------- |
| Chỉ xây modeling library          | Có giá trị nhưng chưa chuẩn hóa execution semantics |
| Xây full-fledged Ontology Runtime | Quá lớn nếu bao gồm toàn bộ infrastructure          |
| Xây embeddable Ontology Engine    | Hướng hiện tại chúng ta thống nhất                  |

Điểm quan trọng là không đánh đồng engine với platform.

Engine cần tồn tại để framework có thể đảm bảo ontology không chỉ được định nghĩa thống nhất mà còn được sử dụng theo những semantic contracts thống nhất.

Tuy nhiên, engine không cần tự xây database, IAM, workflow infrastructure, distributed transaction manager hay một hệ thống lưu trữ riêng.

**Nguyên tắc kiến trúc: Own the semantics, delegate the infrastructure.**

<a id="sec-12"></a>

## 12. Scope và Non-goals

### In scope

Ontology meta-model

Code-first authoring

Typed primitives

Business semantics

Object / Action contracts

Embeddable engine

Governance enforcement

Adapter interfaces

Metadata introspection

Validation & testing

Developer tooling

Consumer integration

### Non-goals

Thay thế Palantir Foundry

Xây database mới

Xây data warehouse

Xây IAM platform

Xây workflow platform

Bắt buộc graph database

Bắt buộc sử dụng RDF

Bắt buộc central server

Distributed engine từ đầu

Enterprise admin platform

Full AI agent framework

Thay thế toàn bộ application

Framework phải hỗ trợ developer xây business layer phù hợp với hệ thống của họ, không ép hệ thống phải tái cấu trúc theo toàn bộ một platform mới.
