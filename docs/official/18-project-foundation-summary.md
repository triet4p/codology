# Part XVIII — Project Foundation Summary

*[← Part XVII — Evaluation and Success Criteria](17-evaluation-and-success-criteria.md) · [Mục lục](README.md) · [Bản gốc](../research/init.md) · [Part XIX — Recommended Next Step →](19-recommended-next-step.md)*

<a id="sec-87"></a>

## 87. Project Charter v0.1

PROJECT CONCEPT · V0.1

## Ontology as Code

A Developer Framework for Building Operational Business Layers

**Problem**

Các phương pháp xây dựng ontology truyền thống có thể khó phát triển và bảo trì khi business semantics, operational logic, governance và data mapping được phân tán giữa nhiều technologies và application layers.

**Vision**

Cho phép developer định nghĩa và vận hành một operational business domain bằng code, độc lập với physical storage và infrastructure cụ thể.

**Core Idea**

Thống nhất Objects, Relations, Functions, Actions, Policies và execution contracts trong một programmable ontology layer.

**Architecture**

Code-first authoring + Meta-model + Lightweight engine + Provider contracts + Developer tooling.

**Target Users**

Software engineers, data engineers, AI engineers và developers xây dựng enterprise business systems.

**Primary Consumers**

Applications, humans, automation và AI Agents.

**Scope**

Một embeddable developer framework, có thể tích hợp với hệ thống hiện tại.

**Non-goal**

Không xây dựng một standalone enterprise platform thay thế Palantir Foundry.

**North Star**

Giảm effort xây dựng và bảo trì business layer mà vẫn đảm bảo business semantics, correctness và governance.

<a id="sec-88"></a>

## 88. Toàn bộ ý tưởng trong một sơ đồ

## Developer

Defines the operational world

### Ontology as Code

Object

Property

Relation

Interface

Value Type

Function

Action

Policy

Constraint

**Meta-model & Metadata Registry**

Types · Semantics · Dependencies · Contracts

## Ontology Engine

Resolve

Query

Compute

Authorize

Validate

Act

Mutate

Audit

Embeddable · Governed · Extensible

Infrastructure Adapters

Databases / Datasets

IAM / Policy

External APIs

Workflow / Events

Consumer Adapters

Python SDK

Applications

REST / GraphQL

AI Agent / MCP

**Developer Tooling**

Validate · Test · Inspect · Version · Visualize · Generate

<a id="sec-89"></a>

## 89. Bản chất của thứ chúng ta muốn xây

Nếu phải giải thích project thông qua những framework quen thuộc, có thể nói:

```
SQLAlchemy
    Abstraction cho database interaction.
Pydantic
    Abstraction cho structured data models.
FastAPI
    Abstraction cho API development.
Pulumi
    Abstraction cho infrastructure as code.
dbt
    Abstraction cho data transformation models.
Ontology as Code
    Abstraction cho operational business layers.
```

OaC nằm ở cấp độ nghiệp vụ, cao hơn database access và không bị ràng buộc vào một consumer cụ thể.

Nó không chỉ trả lời:

```
Dữ liệu có cấu trúc thế nào?
```

Mà còn trả lời:

```
Dữ liệu đại diện cho thực thể nghiệp vụ nào?
Các thực thể liên hệ với nhau thế nào?
Có thể thực hiện những nghiệp vụ nào?
Ai được phép thực hiện?
Điều kiện để thực hiện là gì?
Những trạng thái nào sẽ thay đổi?
Operation được thực thi và theo dõi ra sao?
Application và AI sử dụng chung model thế nào?
```

Đó là lý do chúng ta cần nhiều hơn một ORM, nhiều hơn một knowledge graph, nhiều hơn một API schema và nhiều hơn một function registry.
