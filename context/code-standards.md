# Code Standards

## Runtime and commands

- Target Python 3.13 and manage the project exclusively through `uv`.
- Add dependencies with `uv add <package>` and run project commands with `uv run ...`.
- Use `uv run other-cluster ...` for the packaged CLI and `uv run pytest` for tests.
- Keep dependency versions and the resolved environment in `pyproject.toml` and `uv.lock`; do not add a parallel `requirements.txt` workflow.
- Keep the root `pyproject.toml` console entry point aligned with the canonical `other-cluster` name. The current root `main.py` is only a scaffold and is not the target application boundary.

## Project structure and dependency direction

Use the confirmed `src` layout:

```text
src/other_cluster/
├── cli/             # argparse commands and presentation
├── config/          # TOML, .env, profiles, canonical hashes
├── domain/          # Pydantic models, protocols, statuses, errors
├── input/           # openpyxl template, parsing, validation
├── preprocessing/   # cleanup, classification, language, redaction, deduplication
├── providers/       # Nebius and direct Google adapters
├── embeddings/      # instructions, anchors, memmap, similarity gates
├── clustering/      # PCA, HDBSCAN, rare/noise/category discovery
├── pipeline/        # use cases, orchestration, assignments, lifecycle
└── artifacts/       # XLSX, JSON, cache, logs, atomic artifact writes
```

Keep imports directed toward `domain`. CLI code calls pipeline use cases; it does not contain semantic logic. Vendor adapters translate to and from domain contracts. Workbook objects, HTTP responses, and filesystem paths stop at their owning boundary.

## Python conventions

- Use explicit enums or literal values for statuses and operations. Do not create status strings ad hoc in pipeline branches.
- Raise typed application errors with stage and reason context. Do not catch `Exception` broadly unless converting it at a deliberate boundary and preserving the original cause.
- Keep side effects at boundaries: file writes, HTTP calls, cache mutations, logging, and random sampling should be visible in orchestration code or dedicated adapters.

## Configuration and secrets

- Parse TOML with the standard library and validate it against a versioned configuration model.
- Load all enviornment variables from the environment through `python-dotenv` from file `./.env`.
- Secret-bearing settings must use `repr=False` or an equivalent safe representation. Tests must assert that `repr(settings)` and error output do not expose secret values.

## VERY IMPORTANT: Simplicity First
- Avoid overengineering features, choose the simplest appropriate solution that meets the specific requirements.
- Minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

