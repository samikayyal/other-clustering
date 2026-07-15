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
└── artifacts/       # XLSX, JSON, cache, checkpoints, logs
```

Keep imports directed toward `domain`. CLI code calls pipeline use cases; it does not contain semantic logic. Vendor adapters translate to and from domain contracts. Workbook objects, HTTP responses, and filesystem paths stop at their owning boundary.

## Python conventions

- Follow PEP 8 and use type annotations for public functions, methods, module-level constants, and returned collections.
- Prefer small, single-purpose functions with explicit inputs and outputs. Keep normalization, classification, hashing, and ordering logic pure where practical.
- Use descriptive nouns for data models and verbs for operations. Use `snake_case` for functions/variables/modules, `PascalCase` for classes/models, and `UPPER_SNAKE_CASE` only for true constants.
- Use Pydantic models for serialized/public domain contracts and provider-independent validation. Use frozen standard-library dataclasses for compact immutable settings/value objects such as secret-safe environment settings.
- Avoid untyped dictionaries at module boundaries. If a provider or workbook produces a dictionary, parse it immediately into a typed model and do not pass the vendor shape deeper into the application.
- Use explicit enums or literal values for statuses and operations. Do not create status strings ad hoc in pipeline branches.
- Raise typed application errors with stage and reason context. Do not catch `Exception` broadly unless converting it at a deliberate boundary and preserving the original cause.
- Keep side effects at boundaries: file writes, HTTP calls, cache mutations, logging, and random sampling should be visible in orchestration code or dedicated adapters.

## Configuration and secrets

- Parse TOML with the standard library and validate it against a versioned configuration model.
- Load `NEBIUS_API_KEY`, optional `NEBIUS_AI_PROJECT_ID`, and `GEMINI_API_KEY` from the environment through `python-dotenv`.
- Never put credentials in TOML, manifests, workbooks, checkpoints, logs, cache payloads, test output, exception messages, or object representations.
- Secret-bearing settings must use `repr=False` or an equivalent safe representation. Tests must assert that `repr(settings)` and error output do not expose secret values.
- Do not print raw answer text in operational logs. Provider-bound text must already be deterministically redacted, and passthrough metadata must never enter provider payloads.

## Determinism and data contracts

- Preserve raw `answer_text` exactly; never use the normalized or redacted value as a replacement for the local original.
- Treat IDs as strings at every workbook boundary so leading zeroes survive.
- Use canonical serialization, stable sorting, explicit seeds only where a randomized algorithm requires them, and versioned hashes for input/configuration/prompt/profile/cleanup/redaction contracts.
- Sort variants by `variant_id` before clustering. Do not infer vector identity from workbook row order after preprocessing.
- Keep the fixed Nebius model, dimension, dtype, L2 normalization, instruction, and original-language policy explicit in configuration and manifests.
- Never translate, transliterate, silently correct spelling, summarize, chunk, or application-truncate eligible answers. Validate the complete redacted answer against model context instead.
- Every source `answer_id` must map to exactly one final assignment/status. Missing, blank, non-semantic, rare, unresolved, and provider-error cases are valid explicit outcomes.

## Workbook and artifact handling

- Use `openpyxl` for XLSX parsing, validation, template generation, and output writing.
- Read required cells as strings, reject formulas in required fields, and validate exact sheet names and required columns before any provider call.
- Never modify the input workbook. Write a new six-sheet result workbook with the fixed sheet names and documented columns.
- Use read-only/write-only workbook modes or bounded row processing where appropriate for the 100,000-row target; do not materialize unnecessary duplicate copies of the full workbook or vector matrix.
- Write manifests, checkpoints, caches, and result files atomically where practical. Flush and checksum the memmap before handing it to clustering or declaring a stage complete.
- Keep bulk embedding vectors only in the canonical memmap, not as a second full JSON matrix in the provider cache.

## Provider boundaries

- Keep `SemanticProvider` operations typed and provider-neutral: `healthcheck`, `estimate`, `embed`, and `generate_structured`.
- Use `httpx` with explicit connect/read/write/pool timeouts and bounded retry behavior. Respect provider rate-limit signals such as `Retry-After` when available.
- Keep Nebius embeddings and Google generation as separate adapters, credentials, profiles, endpoint policies, and capability checks.
- Validate every structured response locally. Retry malformed responses according to policy; convert persistent item-level failures into explicit unresolved records.
- Never silently switch provider, model ID, endpoint, embedding dimension, instruction, or redaction policy during resume.

## CLI and error handling

- Implement commands with standard-library `argparse`; command handlers should call application use cases and return typed outcomes.
- Use stable nonzero exit categories for schema/configuration errors, budget rejection, provider preflight failure, circuit-breaker termination, and incomplete output.
- `validate` and `estimate` must not make paid semantic calls. `preview` must remain a bounded preview path and must not authorize an unplanned full run.
- Confirmation-protect destructive cache purge operations and print metadata summaries without payload bodies.
- Human-readable CLI messages may include paths, counts, statuses, and safe diagnostics, but never credentials or raw unredacted answer text.

## Testing standards

- Use `pytest` and run the suite through `uv run pytest`.
- Keep default tests offline, deterministic, and non-sensitive. Mock Nebius and Google at the provider-contract boundary rather than mocking internal implementation details throughout the pipeline.
- Place fast unit tests under `tests/unit/`, fixture-level workflows under `tests/integration/`, and credential-gated synthetic smoke tests under `tests/live/`.
- Live tests are opt-in and must use tiny synthetic fixtures; never send survey answers to smoke-test providers.
- Cover contract rejection, leading-zero IDs, formula detection, pure discovery, cleanup/redaction, language precedence, deduplication, vector/memmap integrity, budget zero-call behavior, similarity gates, HDBSCAN noise/rare handling, bilingual Arabic-script validation, checkpoint compatibility, cache purge confirmation, manifest secrecy, and exactly-one-output traceability.
- Test failure paths deliberately: individual provider failures continue as unresolved, systemic thresholds checkpoint and stop, and incompatible resume is rejected.
- Add regression tests for every fixed bug and for every change to a hashed contract such as prompts, profiles, dimensions, normalization, or redaction rules.

## Documentation and review

- Keep feature behavior in the numbered files under `context/feature-specs/`; update `context/progress-tracker.md` after every meaningful implementation change.
- When implementation changes a contract, update the relevant feature spec, architecture boundary, tests, and progress tracker in the same change.
- Prefer explicit acceptance criteria and failure behavior over vague verbs such as “handle” or “support.”
- Do not claim provider support until the exact model, endpoint, dimension, pricing/limits, and credential-gated smoke test have been verified.
