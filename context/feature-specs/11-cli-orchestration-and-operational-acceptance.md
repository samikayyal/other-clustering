# Spec 11 — CLI Orchestration and Operational Acceptance

**Status:** Planned
**Dependencies:** Specs 01–10 and Spec 02b
**Implementation order:** 11 of 11

## Outcome

All vertical slices are connected through a documented `argparse` CLI, the end-to-end stage order is enforced, output/failure statuses are surfaced clearly, and the application is evaluated against synthetic provider smoke tests and the initial Arabic-plus-English pilot acceptance criteria.

## Command behavior

### `template --output INPUT.xlsx`

Delegate to Spec 02 and generate the fixed three-sheet starter workbook plus documented example configuration.

### `validate --input INPUT.xlsx --config CONFIG.toml`

Run the complete local contract checks and report safe diagnostics. Make zero paid semantic calls.

### `estimate --input INPUT.xlsx --config CONFIG.toml`

Run validation, deterministic preprocessing, request sizing, and cost estimation, reporting the realistic-assumption estimate (assumptions printed) alongside the worst-case diagnostic bound. Make zero paid semantic calls and reject missing pricing metadata or plans whose realistic estimate exceeds the budget.

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
9. write workbook, manifest with stage statuses, logs, and cache metadata atomically where practical;
10. validate exactly-one-output traceability and artifact integrity before reporting success.

### `cache inspect` and `cache purge`

Delegate to Spec 10. Inspect never prints payload bodies. Purge previews scope and requires explicit confirmation.

## Exit and status contract

Define stable named exit categories for:

- success;
- schema/configuration error;
- budget rejection (preflight);
- mid-run budget exhaustion (`budget_exhausted_midrun`);
- provider preflight failure;
- circuit-breaker termination;
- category finalization diagnostic failure;
- incomplete or corrupt output.

The CLI must distinguish a successful complete run from provisional output, category-cap diagnostic failure, systemic provider stop, and incomplete artifact production. Human-readable output may include safe paths/counts/warnings but never credentials or raw unredacted answer text.

## Tests

- Every command has a help/argument-validation test and a safe exit-category assertion.
- `validate` and `estimate` are verified to make zero paid semantic calls; preview is verified to remain bounded.
- End-to-end synthetic fixtures verify exactly-one-output traceability, artifact integrity, secret exclusion, category-cap provisional output, and embedding-failure cleanup.
- Provider live smoke tests remain opt-in and use only tiny synthetic, non-sensitive fixtures.

## Operational acceptance

### Required automated coverage

- `uv run pytest` passes the unit, fixture-integration, and mocked Nebius/Google contract suites.
- The six-sheet workbook and JSON manifest round-trip on the 100,000-row acceptance fixture within configured resource limits.
- Exactly-one-output traceability, secret exclusion, memmap integrity, budget zero-call behavior, category-cap handling, and embedding-failure cleanup tests pass.

### Required live smoke gates

Opt-in smoke tests use tiny synthetic, non-sensitive data and must verify:

- Nebius `Qwen/Qwen3-Embedding-8B` at 4096 dimensions, endpoint selection, pricing/preflight behavior, and invalid-model rejection;
- direct Google `gemini-3.5-flash` structured generation, bilingual JSON schema, native Arabic-script validation, pricing/preflight behavior, endpoint selection, and invalid-model rejection.

Both profiles are unsupported for real runs until their respective smoke suites pass.

### Initial pilot fixture

The pilot evaluation consumes the Spec 02b gold fixture — it does not create one. The fixture, its truth JSON keyed by `answer_id`, its content requirements, and the Arabic-plus-English language scope are defined in Spec 02b, which must be complete long before this spec (it also feeds the Spec 06 instruction selection and the Spec 06–08 threshold defaults). Additive rows may be appended for pilot coverage, but the calibration rows remain unchanged so calibration and evaluation stay comparable. The gold file stays outside the production workbook contract and is not a public CLI input in v1.

Use these metric definitions:

- Assignment correctness: correct automatically assigned substantive source rows divided by all automatically assigned substantive source rows.
- Coverage: automatically assigned substantive source rows divided by all eligible substantive source rows.
- Unresolved rate: unresolved substantive source rows divided by all eligible substantive source rows.
- Category coherence: source-row-weighted cluster purity against the gold `intent_id`.
- Traceability: every source `answer_id` appears exactly once with a valid final status.

Report:

- review-sample assignment correctness, target at least 90%;
- category coherence, target at least 85%;
- exactly-one-output traceability;
- coverage and unresolved rate side by side with denominators/exclusions;
- per-language coverage and unresolved rate;
- English/Arabic label completeness and Arabic-script validity.

Report raw numerators and denominators, use 95% Wilson intervals for correctness, coverage, and unresolved rate, and report coherence as a point estimate with cluster and row counts. Continue reporting coverage and unresolved rate by language, while avoiding additional unapproved metrics. Do not hide low coverage behind correctness or coherence. Export metric definitions, denominators, exclusions, intervals, and per-stratum sample sizes in the manifest and Summary sheet.

## Implementation tasks

1. Wire all command parsers to pipeline use cases and typed exit outcomes.
2. Enforce command-specific paid-call and preview boundaries.
3. Add end-to-end synthetic fixtures and command-level tests.
4. Add operator documentation for credentials, smoke tests, token-counting/pricing assumptions, budget preflight, output inspection, failure diagnostics, and cache purge.
5. Run the initial pilot evaluation and record results in the manifest/progress tracker before declaring v1 operationally supported.

## Acceptance criteria

- Every documented command has a working help entry, safe validation, stable status/exit behavior, and tests.
- A valid end-to-end run produces complete, auditable artifacts and exactly one output status per answer ID.
- Invalid, over-budget, unsupported, interrupted, and circuit-breaker paths are diagnosable and leave safe artifacts for a new run.
- Both provider smoke suites pass before live provider profiles are advertised.
- The Arabic-plus-English pilot meets or transparently reports the agreed correctness, coherence, coverage, unresolved, traceability, and bilingual-label metrics.

## Non-goals

- Adding a web interface, survey-platform integration, automatic translation, official codebook mutation, persistent cross-run registries, or provider failover.
