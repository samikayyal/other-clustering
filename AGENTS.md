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

## Agent skills

### Issue tracker

Issues and PRDs for `samikayyal/other-clustering` live in its private GitHub Issues; use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo whose domain and engineering context live under `context/`. See `docs/agents/domain.md`.
