# Spec 11 — CLI Orchestration and Operational Acceptance

**Status:** Planned
**Dependencies:** Specs 01–10
**Implementation order:** 11 of 11

## Outcome

All vertical slices are connected through a documented `argparse` CLI, the end-to-end stage order is enforced, output/failure statuses are surfaced clearly, and the application is evaluated against synthetic provider smoke tests and the initial Arabic-plus-English pilot acceptance criteria.

## Command behavior

### `template --output INPUT.xlsx`

Delegate to Spec 02 and generate the fixed three-sheet starter workbook plus documented example configuration.

### `validate --input INPUT.xlsx --config CONFIG.toml`

Run the complete local contract checks and report safe diagnostics. Make zero paid semantic calls.

### `estimate --input INPUT.xlsx --config CONFIG.toml`

Run validation, deterministic preprocessing, request sizing, and conservative cost estimation. Make zero paid semantic calls and reject missing pricing metadata or over-budget plans.

### `preview --input INPUT.xlsx --config CONFIG.toml --output-dir DIR`

Analyze a fixed-seed, frequency/language-stratified sample capped at 2,000 unique normalized variants. Report language distribution, detector confidence, unsupported/uncertain groups, and cleanup/redaction diagnostics. Produce a preview workbook/manifest without authorizing an unplanned full run or invoking translation.

### `run --input INPUT.xlsx --config CONFIG.toml --output-dir DIR`

Execute the full sequence:

1. validate and fingerprint;
2. preprocess, deduplicate, language-assess, and redact;
3. preflight providers and budget;
4. embed variants/anchors and verify the memmap;
5. match existing choices;
6. discover new categories;
7. label clusters and review composites;
8. assign every source row;
9. write workbook, manifest, checkpoints, logs, and cache metadata;
10. validate exactly-one-output traceability and artifact integrity before reporting success.

### `resume --run-id RUN_ID --output-dir DIR`

Load the last compatible checkpoint, validate all hashes/artifacts, and continue without provider/model mixing.

### `cache inspect` and `cache purge`

Delegate to Spec 10. Inspect never prints payload bodies. Purge previews scope and requires explicit confirmation.

## Exit and status contract

Define stable named exit categories for:

- success;
- schema/configuration error;
- budget rejection;
- provider preflight failure;
- circuit-breaker termination;
- incompatible resume;
- category finalization diagnostic failure;
- incomplete or corrupt output.

The CLI must distinguish a successful complete run from provisional output, category-cap diagnostic failure, systemic provider stop, and incomplete artifact production. Human-readable output may include safe paths/counts/warnings but never credentials or raw unredacted answer text.

## Tests

- Every command has a help/argument-validation test and a safe exit-category assertion.
- `validate` and `estimate` are verified to make zero paid semantic calls; preview is verified to remain bounded.
- End-to-end synthetic fixtures verify exactly-one-output traceability, artifact integrity, secret exclusion, and compatible resume behavior.
- Provider live smoke tests remain opt-in and use only tiny synthetic, non-sensitive fixtures.

## Operational acceptance

### Required automated coverage

- `uv run pytest` passes the unit, fixture-integration, and mocked Nebius/Google contract suites.
- The six-sheet workbook and JSON manifest round-trip on the 100,000-row acceptance fixture within configured resource limits.
- Exactly-one-output traceability, secret exclusion, memmap integrity, budget zero-call behavior, and incompatible-resume tests pass.

### Required live smoke gates

Opt-in smoke tests use tiny synthetic, non-sensitive data and must verify:

- Nebius `Qwen/Qwen3-Embedding-8B` at 2048 dimensions, endpoint selection, pricing/preflight behavior, and invalid-model rejection;
- direct Google `gemini-3.5-flash` structured generation, bilingual JSON schema, native Arabic-script validation, pricing/preflight behavior, endpoint selection, and invalid-model rejection.

Both profiles are unsupported for real runs until their respective smoke suites pass.

### Initial pilot fixture

Create a seeded, manually labeled fixture before tuning thresholds. The current confirmed language scope is:

- Arabic, including representative Modern Standard Arabic and dialectal Arabic answers;
- English.

The fixture should include roughly 20–30 semantic intents, 3–5 human-labeled variants per intent, spelling errors, short answers, blanks/refusals, existing-choice matches, new-category cases, rare meanings, and multi-concept answers. Do not create the gold set through automatic translation. Broader language coverage is deferred until real data justifies it.

Report:

- review-sample assignment correctness, target at least 90%;
- category coherence, target at least 85%;
- exactly-one-output traceability;
- coverage and unresolved rate side by side with denominators/exclusions;
- per-language coverage and unresolved rate;
- English/Arabic label completeness and Arabic-script validity.

Do not hide low coverage behind correctness or coherence. Export metric definitions, denominators, exclusions, confidence intervals where meaningful, and per-stratum sample sizes in the manifest and Summary sheet.

## Implementation tasks

1. Wire all command parsers to pipeline use cases and typed exit outcomes.
2. Enforce command-specific paid-call and preview boundaries.
3. Add end-to-end synthetic fixtures and command-level tests.
4. Add operator documentation for credentials, smoke tests, budget preflight, output inspection, resume, and cache purge.
5. Run the initial pilot evaluation and record results in the manifest/progress tracker before declaring v1 operationally supported.

## Acceptance criteria

- Every documented command has a working help entry, safe validation, stable status/exit behavior, and tests.
- A valid end-to-end run produces complete, auditable artifacts and exactly one output status per answer ID.
- Invalid, over-budget, unsupported, interrupted, and circuit-breaker paths are diagnosable and resumable when compatible.
- Both provider smoke suites pass before live provider profiles are advertised.
- The Arabic-plus-English pilot meets or transparently reports the agreed correctness, coherence, coverage, unresolved, traceability, and bilingual-label metrics.

## Non-goals

- Adding a web interface, survey-platform integration, automatic translation, official codebook mutation, persistent cross-run registries, or provider failover.
