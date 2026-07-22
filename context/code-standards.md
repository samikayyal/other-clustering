# Code Standards

## Governing Principle: Simplicity First

- Use the minimum code that correctly implements the agreed requirement.
- Do not implement speculative features.
- Do not add configurability without a stated product need.
- Do not create an abstraction for a single use unless it directly protects a required boundary.
- Do not handle scenarios that the established input contract makes impossible.
- If an implementation is substantially longer or more indirect than necessary, simplify it before continuing.

## Python Tooling

- Use `uv` for all dependency management and execution.
- Add dependencies with `uv add <package>`.
- Run the application and tools with `uv run <command>`.
- Run tests with `uv run pytest`.
- Expose the application through the `other-cluster` console entry point.
- Use standard-library `argparse` for the CLI.

## Implementation Conventions

- Prefer small functions with one concrete responsibility.
- Prefer direct data flow over service layers, registries, factories, or dependency-injection frameworks.
- Keep workbook interpretation in the workbook boundary and provider-specific HTTP details in the relevant provider boundary.
- Preserve original answer text and stable workbook row references.
- Use explicit names that reflect survey concepts: question, choice, answer, assignment, category, and source column.
- Store secrets only in environment variables; never hard-code them or write them to logs/artifacts.
- Add tests for behavior introduced by each feature specification.

- Support Python `>=3.13`, matching `pyproject.toml`.

[INPUT REQUIRED: Define any required formatter, linter, type checker, docstring convention, or coverage threshold. None was specified.]
