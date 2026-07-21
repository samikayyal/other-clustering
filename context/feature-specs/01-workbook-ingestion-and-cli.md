# Feature 01: Workbook Ingestion and CLI

## Objective

Provide the `other-cluster` command and convert a valid coding workbook into an exact in-memory representation of questions, existing choices, free-text answers, and their destination cells.

This feature establishes the workbook and invocation contracts used by every later feature. It does not call either AI provider, embed answers, cluster data, label categories, or save coding results.

## Detailed Description

The console entry point uses standard-library `argparse`. It accepts an input `.xlsx` workbook and the minimum settings required to run the application. Non-secret configuration is read with `tomllib`; secrets may be loaded into environment variables with `python-dotenv` for later features.

The command syntax is:

```text
other-cluster [--input PATH] [--output PATH] [--config PATH] [--overwrite]
```

`--input` and `--output` are optional at argument-parsing time so they can be supplied by configuration, but both paths are required after configuration resolution. The normal invocation supplies both flags. `--config` selects a TOML file; `--overwrite` is an explicit opt-in that permits replacing an existing output file. The input and output paths must refer to different files, so in-place source modification is invalid. Without overwrite enabled, an existing output path is a validation error.

The command returns exit code `0` on success, `2` for CLI or configuration errors (including unresolved input or output paths), and `1` for workbook, provider, or finalization failures.

When `--config` is omitted, the application uses the path in `OTHER_CLUSTER_CONFIG` when that environment variable is set; otherwise it looks for `other-cluster.toml` in the current working directory. An explicitly selected config file must exist and parse successfully. The default file is optional: if it is absent, resolution continues with environment variables and built-in defaults.

The initial TOML contract uses these keys:

```toml
input = "path/to/input.xlsx"
output = "path/to/output.xlsx"
overwrite = false

[discovery]
min_unique_answer_texts = 3
```

The corresponding environment variables are `OTHER_CLUSTER_INPUT`, `OTHER_CLUSTER_OUTPUT`, `OTHER_CLUSTER_OVERWRITE`, and `OTHER_CLUSTER_DISCOVERY_MIN_UNIQUE_ANSWER_TEXTS`. Environment variables may be provided by the process environment or an optional `.env` file. For each setting, precedence is CLI argument, then TOML, then environment variable, then built-in default. There is no built-in default for `input` or `output`; both must resolve to a path. `overwrite` defaults to `false`, and `discovery.min_unique_answer_texts` defaults to `3`. Unknown TOML keys are configuration errors.

Before any paid API call, the application opens the workbook with `openpyxl` and validates the required sheets and headers. It then extracts:

- supported question IDs from `Code.list_name`, using the first existing `Survey.name` from ordered deterministic lookup candidates: remove a trailing `_other`; for a trailing `_exp`, prefer the exact ID and fall back to the suffix-free ID; for each base, prefer exact spelling and fall back to a variant with a missing underscore restored between an ASCII letter and terminal digits;
- English and Arabic question text from `Survey.label:english` and
  `Survey.label:arabic`; when exactly one is blank or whitespace-only, the
  nonblank label is used for both fields, while both blank labels are invalid;
- existing choices from `Code`, using the required headers `list_name`, `value`, `label:english`, and `label:arabic`; additional headers on any supported sheet are ignored;
- English and Arabic choice labels from `Code.label:english` and
  `Code.label:arabic`, using the same one-sided fallback and rejecting rows
  whose two labels are both blank;
- every eligible original-language answer from the matching `Data` column whose header equals the question ID;
- the exact respondent `KEY` and source row;
- the corresponding `Work` triplet `<question_id>`, `<question_id>_Coded`, and `<question_id>_C1`; and
- the exact `_Coded` destination cell while preserving the source-answer and `_C1` formulas.

Required headers are resolved by their header names, not by fixed column positions. Fixed schema headers are matched case-insensitively (for example, `Label:Arabic` matches `label:arabic`), while dynamic question IDs remain case-sensitive, so
their order may vary independently on `Survey`, `Code`, `Data`, and `Work`. The one
intentional order constraint is that each `Work` question triplet remains contiguous
and ordered as `<question_id>`, `<question_id>_Coded`, `<question_id>_C1`.

Headers that are not required for the supported contract are ignored on every
supported sheet. Missing or duplicate required headers remain validation errors.

`Code.list_name` is the primary question/choice-list key. Only its Survey metadata lookup candidates are normalized. A trailing `_other` is removed to target the parent question. For a trailing `_exp`, the exact ID is preferred and the suffix-free ID is a fallback because either shape can be canonical in `Survey.name`. For each resulting base, exact spelling is preferred and a variant with a missing underscore restored between an ASCII letter and terminal digits is a fallback. The first candidate that exactly matches `Survey.name` is selected; no candidate remains an error. Fuzzy matching is not used. The original Code list name remains the exact `Data`/`Work` answer and coding-column ID. Survey rows without a matching normalized Code list name are ignored. The `Code` choice with value `-96` is the "Other" choice and is excluded as an existing semantic category.

Each `Work` triplet must exist exactly once and in the stated order. The application does not create, reorder, deduplicate, or repair these columns. A missing, reordered, or duplicate triplet member makes the workbook invalid.

Blank and whitespace-only answers are skipped. Numeric answer cells are invalid; the application does not use Excel number formats to convert them to displayed text. Hidden `Data` rows are processed like visible rows. Formula-based, merged, and error-valued respondent-answer cells in `Data` are outside the supported raw-data contract.

Every extracted answer receives a stable internal ID tied to its exact workbook location. Repeated answer text must retain every respondent row even when later computation deduplicates identical text.

For later provider and computation stages, exact duplicate answer text is deduplicated once per question and processed as one canonical item. The resulting decision or computation is fanned out to every row-level answer record with that question and exact text. Row-level records and their individual source and `_Coded` destination mappings are never discarded.

Workbook validation must report a clear failure and stop without modifying the source workbook when a required sheet, column, pairing, or value is invalid. When an issue belongs to a worksheet row or cell, the error includes its sheet and row number (or the precise cell location); errors without a source row, such as a missing sheet or invalid path, do not invent one.

## Outputs

- Parsed run settings.
- A workbook handle or source path reserved for final writing.
- Extracted question records.
- Existing-choice records grouped by question.
- Answer records with exact source and target cell locations.
- A validation result that prevents later stages from running against an invalid workbook.

## Success Looks Like

- Running `other-cluster` with the agreed CLI syntax can open a valid representative `.xlsx` workbook.
- Every supported "Other" question has the correct question text, question ID, and existing choices, with the "Other" choice excluded.
- Every eligible respondent answer is extracted exactly as stored, including Arabic, dialectal Arabic, and English text.
- Repeated text produces mappings for all respondent rows; no row is lost.
- Each extracted answer points to the exact cell that must eventually receive its `_Coded` value.
- Missing or inconsistent required workbook structure produces a non-zero exit and no workbook mutation.
- Automated workbook-fixture tests prove the extraction and cell mappings once the open workbook schema inputs are resolved.

## Not Included

- Embedding provider calls.
- Vector persistence.
- Existing-choice semantic assignment.
- PCA or clustering.
- Gemini labeling.
- Writing final category values.
