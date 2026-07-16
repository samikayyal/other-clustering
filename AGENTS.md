# Application Building Context

Read the following files in order before doing anything:

1. `context/project-overview.md` — product definition, goals, features, and scope
2. `context/architecture.md` — system structure, boundaries, storage model, and invariants
3. `context/code-standards.md` — Python conventions, patterns, and file organization
4. `context/feature-specs/` — numbered vertical-slice specs and implementation contracts
5. `context/progress-tracker.md` — current phase, completed work, open questions, and next steps

Use `uv` for all Python dependency management and execution:

- `uv add <package>` to add dependencies
- `uv run <command>` to run the application and tools
- `uv run pytest` to run tests

Update `context/progress-tracker.md` after every
meaningful implementation change.

If implementation changes the architecture, scope,
standards, or feature contracts, update the relevant
context file before continuing.

Record durable architecture decisions in the
`Architecture Decisions` section of
`context/progress-tracker.md` and update
`context/architecture.md` when applicable.
