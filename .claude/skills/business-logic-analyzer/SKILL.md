---
name: business-logic-analyzer
description: Analyzes, models, and documents domain concepts, business rules, workflows, and system constraints. Use when asked to understand domain logic, model workflows, or extract business rules from requirements or code.
---

# Business Logic Analyzer

A skill for analyzing complex domain logic, mapping workflows, and translating abstract business rules into clear system logic.

## When to Use

Use this skill when the user asks to:
- Extract business rules from code or requirements documents
- Map domain models, entities, and state transitions
- Evaluate edge cases, regulatory constraints, or policy impacts
- Define domain terminology (Ubiquitous Language)

## Core Principles

1. **Domain First**: Focus on business outcomes, rules, and domain events rather than tech stack or implementation details.
2. **Ubiquitous Language**: Use clear, consistent domain terminology throughout documentation.
3. **Edge-Case Rigor**: Explicitly highlight boundary conditions, state validation errors, and policy exceptions.
4. **Visual Mapping**: Represent complex state machines or multi-actor processes using structured tables or workflows.

## Workflow

1. **Identify Entities & Roles**:
   - Who are the actors?
   - What are the core domain entities and their states?
2. **Map the Happy Path**:
   - Step-by-step trigger -> validation -> transformation -> outcome.
3. **Identify Invariants & Business Rules**:
   - What conditions MUST always hold true?
   - What triggers a validation failure or policy violation?
4. **Document Output**:
   - **Entity / Data Model**: Attributes, relationships, and constraints.
   - **Business Rules Matrix**: Rule ID, Rule Description, Trigger, and Exception Behavior.
   - **State Diagram / Process Flow**: Step-by-step logic map.

## Output Format

- Use Markdown tables for Business Rule matrices.
- Use explicit bulleted state flows or Mermaid/text diagrams for process transitions.
