# Feature 01: Workbook Ingestion and Analysis CLI

## Objective

Accept a local `.xlsx` workbook or supported native Google Sheets URL and build
the exact V1 dataset used by the analysis pipeline. V1 reads only `Survey`,
`Code`, and `Data`; every other worksheet, including `Work`, is ignored without
validation or interpretation.

## CLI

The only supported commands are:

```text
other-cluster analyze --input PATH_OR_GOOGLE_SHEETS_URL
other-cluster review --review-file REVIEW_JSON
```

`analyze` validates input, embeds, clusters, classifies eligible clusters,
writes one review JSON file, and prints a compact summary. `review` opens the
local browser application for that file. There is no legacy top-level analysis
syntax, `--output`, `--overwrite`, `--config`, TOML configuration, ordinary
`OTHER_CLUSTER_*` setting, CSV artifact, or finalization command.

Only `NEBIUS_API_KEY` and `GEMINI_API_KEY` are loaded from the process
environment or an optional current-directory `.env`. A key is required only
when its stage needs a provider call.

## Input behavior

Local input must be an existing `.xlsx` file. A supported native
`docs.google.com/spreadsheets/d/...` URL is exported through the XLSX endpoint
into an isolated temporary directory under `./.temp/`, using the filename from
`Content-Disposition`, and the file/directory are cleaned up in `finally`.
Temporary cleanup may warn without changing an otherwise successful result.

Before any paid call, the workbook is opened read-only with formulas visible
and the required sheets/headers are validated. `Survey`, `Code`, and `Data`
fixed headers are case-insensitive; dynamic question IDs remain case-sensitive.
Required headers are resolved by name and unexpected headers on those sheets
are ignored.

## Extraction contract

- `Code.list_name` is the question/choice-list key and remains the exact
  `Data` answer-column identifier.
- Deterministic normalization is used only to locate matching `Survey.name`
  metadata (`_other`, `_exp`, and terminal-digit underscore fallbacks).
- Question and choice bilingual labels use the nonblank side when the other
  side is blank; both blank labels are invalid.
- Code value `-96` is excluded as the Other choice.
- Blank/whitespace answers are skipped. HTML tags are removed from extracted
  question labels and answers; answers blank after cleanup are skipped.
- Numeric answer cells are skipped with a source-cell warning. Hidden data rows
  are processed. Formula, merged, and error-valued answer cells are invalid.
- Each answer retains a stable answer ID, exact respondent `KEY`, source row,
  question ID, source column, and exact source cell coordinate.
- Exact duplicate text is deduplicated once per question for later processing,
  with full occurrence and row-mapping fan-out.

No workbook is written, saved, or mutated during analysis or review. V1 never
opens, validates, or reads `Work`, even when that tab is malformed or populated.

## Source identity and output

The analysis computes the exact XLSX byte length and lowercase SHA-256 for the
review file. The file is written atomically to:

```text
./reviews/<normalized_source_stem>_<analysis_run_id>.json
```

The source workbook remains unchanged and no extracted CSV is created.
