# Application Building Context

Read `context/v1-contract.md` and `context/code-standards.md` before changing
application behavior. Read `context/decisions.md` only when a proposed change
alters an architecture or contract decision.

Use `uv` for all Python dependency management and execution:

- `uv add <package>` to add dependencies
- `uv run <command>` to run the application and tools
- `uv run pytest` to run tests

Update `context/v1-contract.md` when a product or behavior contract changes.
Record durable architecture decisions in `context/decisions.md` when applicable.
