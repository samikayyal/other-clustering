# Spec 01 — Project Foundation and Domain Contracts

**Status:** Planned
**Dependencies:** None
**Implementation order:** 01 of 11

## Outcome

The repository becomes a packaged Python application with the canonical `other-cluster` identity, a `src/other_cluster/` layout, a working CLI help surface, typed domain contracts, and an application error vocabulary. No provider calls or semantic processing are introduced in this slice.

## Scope

- Update `pyproject.toml` metadata and console entry point to `other-cluster`.
- Create the confirmed `src/other_cluster/` package boundaries and test directories.
- Replace the root `main.py` scaffold with the packaged CLI entry point once the package command is verified.
- Add the domain model and protocol modules needed by later slices.
- Establish typed application errors and stable error categories for CLI mapping.
- Keep the first command surface limited to help/dispatch scaffolding; behavior belongs to later specs.

## Domain contracts

Create provider-independent typed models for:

- `QuestionSpec`: one question ID and wording.
- `ChoiceAnchor`: stable choice ID, label, optional description, and examples.
- `AnswerRecord`: string answer ID, raw answer text, optional language hint, and local passthrough metadata.
- `NormalizedVariant`: deterministic variant ID, normalized text, occurrence count, source answer IDs, and preprocessing status.
- `LanguageAssessment`: source hint, detected language, confidence, detector mode, and warning fields.
- `ProviderRequestRecord`: provider, model, operation, redaction/profile identifiers, request checksum, usage, and outcome.
- `ExistingChoiceMatch`: ranked choice candidates, similarities, margin, verifier result, and disposition.
- `ClusterCandidate`: stable run-local ID, member variants, membership statistics, examples, and review status.
- `BilingualCategoryLabel`: English and Arabic label/description fields plus validation status.
- `Assignment`: exactly one source-row outcome, primary category, confidence, composite flag, secondary suggestions, and unresolved reason.
- `ReviewRecord`: deterministic review-sample metadata and blank analyst-review fields.
- `RunManifest`: versioned run metadata contract; detailed fields are completed in Spec 09.

Models must keep IDs as strings, distinguish raw text from normalized/redacted text, and use explicit enums or literals for statuses and operations. Domain models must not import `openpyxl`, `httpx`, provider SDK types, or filesystem-specific classes.

## Error vocabulary

Define typed errors for at least:

- input/schema/configuration contract failure;
- budget rejection before paid calls;
- provider capability/preflight failure;
- individual item/provider failure that can become unresolved;
- circuit-breaker termination;
- incomplete or corrupt output artifact.

Each error should carry a safe reason code and stage. Secret values and raw unredacted answer text must never be included in error strings.

## Implementation tasks

1. Create package `__init__` files and inward-only import boundaries.
2. Add the console-script target that invokes `other_cluster.cli.main:main` or an equivalent typed entry function.
3. Add `other-cluster --help` and a placeholder subcommand registry using `argparse`.
4. Add domain models, statuses, protocols, and errors with serialization tests.
5. Verify that `uv run other-cluster --help` works from a clean environment.
6. Keep the root scaffold out of the runtime path after the packaged command is verified.

## Tests

- Package imports succeed from the installed project, not only from the repository root.
- CLI help exits successfully and lists the planned command groups.
- Every domain model validates its required fields and round-trips through its intended serialization format.
- IDs remain strings, including values with leading zeroes.
- Domain modules do not import vendor, workbook, or CLI implementation modules.
- Error representations contain stage/reason metadata but no secret-like values or raw answer payloads.

## Acceptance criteria

- `uv run other-cluster --help` succeeds.
- `pyproject.toml` names `other-cluster` consistently for project metadata and the console command.
- The target source tree exists under `src/other_cluster/` with the boundaries documented in `context/architecture.md`.
- The canonical domain types and error categories are available to later specs without vendor coupling.
- No semantic API call, workbook mutation, or production pipeline behavior is required for this slice.

## Non-goals

- Implementing workbook parsing, configuration validation, provider calls, clustering, or output generation.
- Choosing hidden model aliases or creating a compatibility layer for the old placeholder `ai-coding` name.
