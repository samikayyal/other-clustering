# Domain Docs

How the engineering skills should consume this repo's existing domain and engineering context.

This repo uses the `context/` directory as its source of truth. It does not use a root `CONTEXT.md`, `CONTEXT-MAP.md`, or `docs/adr/` layout for these materials.

## Before exploring or changing code

- **`context/v1-contract.md`** — read before changing application behavior. It defines the V1 outcome and boundary, supported commands and inputs, workbook ingestion rules, analysis pipeline, review document, and completion semantics. Update it when a product or behavior contract changes.
- **`context/code-standards.md`** — read before implementation changes. It defines the simplicity-first principle, `uv` tooling requirements, implementation boundaries, naming conventions, secret handling, supported Python version, and testing expectations.
- **`context/decisions.md`** — read when a proposed change could alter the architecture or contract. It records durable decisions such as cluster-first analysis, the schema-version-3 review artifact, boundary validation, cache compatibility, and completion allocation. Record new durable architecture decisions there.
- **`context/feature-specs/`** — read the relevant feature specification when one exists for the area being changed. This directory is optional and may be empty.

If a referenced context file or feature specification does not exist, proceed silently. Do not create a root `CONTEXT.md` or `docs/adr/` directory as part of ordinary work; use the existing `context/` convention unless the project explicitly adopts a different layout.

## File structure

Single-context repo:

```text
/
├── context/
│   ├── v1-contract.md
│   ├── code-standards.md
│   ├── decisions.md
│   └── feature-specs/
└── src/
```

## Use established vocabulary

When an issue, proposal, hypothesis, test, or refactor names a domain concept, use the terminology established in `context/v1-contract.md` and the relevant feature specification. In particular, preserve the project's survey concepts such as question, choice, answer, assignment, category, canonical answer, cluster, unresolved item, and review artifact. Do not introduce synonyms that obscure those established meanings.

If a concept is not defined in the context documents, treat that as a documentation gap and resolve the language with the `/domain-modeling` skill before making it part of a durable contract or architecture.

## Flag conflicts

If a proposed change contradicts `context/v1-contract.md`, `context/code-standards.md`, or an architecture decision in `context/decisions.md`, surface the conflict explicitly rather than silently overriding it:

> _Contradicts `context/decisions.md` (the relevant decision) — but worth revisiting because…_
