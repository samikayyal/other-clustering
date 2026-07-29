# other-cluster

`other-cluster` is a local Cluster-First V1 workflow for discovering and
reviewing categories for free-text SurveyCTO `Other` answers. It accepts a
local `.xlsx` workbook or a supported native Google Sheets URL, reads only
`Survey`, `Code`, and `Data`, and ends with one completed reviewed JSON file.

The `Work` worksheet is completely outside V1. It is never required, read,
validated, interpreted, or written. V1 never saves or mutates any workbook,
does not create an extracted CSV, and has no finalization command.

## Commands

```powershell
uv run other-cluster analyze --input input.xlsx
uv run other-cluster analyze --input "https://docs.google.com/spreadsheets/d/ID/edit"
uv run other-cluster review --review-file reviews\input_<analysis-run-id>.json
uv run pytest
```

`analyze` validates the workbook, embeds every distinct question/text answer,
clusters all answers independently per question, makes one Gemini request per
proposal-eligible cluster, and writes:

```text
./reviews/<normalized_source_stem>_<analysis_run_id>.json
```

`review` opens that same file in the local browser application bound to
`127.0.0.1:5000`. The JSON file is both evidence and editable review state.
Analysis starts it with `status: "in_review"`; browser edits and completion
use atomic replacement of the same file. A completed file is read-only.

## Provider behavior

The embedding stage uses Nebius `Qwen/Qwen3-Embedding-8B` vectors with the
validated SQLite exact-text cache at `./embedding_cache/cache.sqlite3`. The
cache stores sensitive exact answer text and derived vectors locally and is
retained until manually removed. A missing `NEBIUS_API_KEY` is required only
when an uncached answer must be embedded.

Cluster classification uses schema-constrained Gemini
`gemini-3.5-flash-lite`. It receives the question, all same-question existing
choices, and a deterministic cluster sample; it never receives respondent keys
or workbook locations. Each proposal can select one existing choice, propose a
new bilingual category, or reject the cluster. There is no per-answer Gemini
assignment stage. A missing `GEMINI_API_KEY` is required only when there is at
least one proposal-eligible cluster. Exhausted cluster calls become safe,
nonfatal provider-error warnings and remain reviewable fixed clusters.

Only `NEBIUS_API_KEY` and `GEMINI_API_KEY` are read from the process environment
or an optional current-directory `.env`. Discovery thresholds, models, and
provider behavior are fixed V1 constants; TOML and non-secret
`OTHER_CLUSTER_*` configuration are not supported.

## Review rules

Cluster membership is immutable. For every system cluster, the analyst chooses
the whole cluster's final disposition:

- assign all members to one existing choice from that question;
- accept one bilingual new category for all members; or
- leave the cluster unresolved.

Noise, rare, low-probability, and rejected-small-cluster canonical answers may
only be assigned to one same-question existing choice or left unresolved.
Members cannot be split, merged, moved, or manually categorized outside a
system cluster.

Values are allocated only at completion. For each question independently, the
application collects existing `Code` values greater than `100`, processes final
new categories by stable cluster ID, and assigns each the smallest unused
integer greater than `100`. Values may repeat across different question lists.

## Workbook boundary

Required headers are validated by name on:

- `Survey`: `type`, `name`, `label:english`, `label:arabic`;
- `Code`: `list_name`, `value`, `label:english`, `label:arabic`; and
- `Data`: `KEY` plus supported answer columns.

Fixed headers are case-insensitive and dynamic question IDs remain
case-sensitive. The `Code` value `-96` Other choice is excluded. Question and
choice labels use one-sided bilingual fallback, HTML markup is removed from
extracted labels/answers, numeric answer cells are skipped with warnings, and
exact duplicate texts are processed once per question with complete respondent
row/cell fan-out.

Google Sheets links are temporarily exported as XLSX using the response's
filename under `./.temp/` and cleaned up after success or failure. The exact
source byte length and SHA-256 are retained in the review file.

## V2 backlog

Workbook mutation, `Work` interpretation, respondent-output destinations,
final workbook saves, and approval/receipt/replay lifecycles are deferred to
V2. They are not active V1 requirements.
