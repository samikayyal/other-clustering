# other-cluster

CLI workflow for extracting and conservatively assigning one or more SurveyCTO
`Other`-coding questions from an `.xlsx` workbook or a native Google Sheets
link. The command validates the workbook contract, builds the exact row-level
dataset, creates original-language Nebius embeddings for canonical
question/text records, then verifies possible existing-choice assignments with
Gemini.

```powershell
uv run other-cluster --help
uv run other-cluster --input input.xlsx --output coded-output.xlsx
uv run other-cluster --input "https://docs.google.com/spreadsheets/d/ID/edit" --output coded-output.xlsx
uv run other-cluster review --review-package review_packages\PACKAGE_review.json
uv run pytest
```

The command requires `NEBIUS_API_KEY` in the environment or optional `.env`
when an answer is not already cached, plus `GEMINI_API_KEY` when a question has
one or more existing choices to verify. It prints a JSON summary, writes
extracted records to `./extracted_data/<normalized_input_name>_extracted.csv`,
retains validated vectors and their row mappings in memory for the active
process, and keeps reusable exact-text vectors in
`./embedding_cache/cache.sqlite3`. The SQLite database stores the exact answer
and embedding identity in plaintext columns plus a little-endian `float32` BLOB,
so it contains sensitive derived survey data and is retained until manually
deleted. It uses WAL mode and validates its version, schema, identity, BLOB
length, finite values, and unit norm before cache reuse; an incompatible or
corrupt cache fails safely rather than being rebuilt. The legacy hashed JSON
cache format is intentionally unsupported and was discarded without migration.

A successful analysis writes an immutable JSON review package under
`./review_packages`. Open one package in the local browser review application
with `other-cluster review --review-package ...`; the server binds only to
`127.0.0.1:5000`. Every accepted edit is atomically auto-saved under
`./review_state`, and a complete review writes one immutable approval under
`./review_approvals`. The review application never writes a workbook. Feature
07 finalization remains a separate gated stage.

Answers are sent exactly as extracted after HTML-tag cleanup, without
translation, prefixes, or other language changes. Gemini receives each exact
answer with the bilingual question text and every bilingual choice only for its
own question. It may assign only one supplied stored value or return no match;
uncertain, ambiguous, negated, partial, and otherwise unsafe answers stay
unassigned for the discovery stage. The CSV and in-memory row map retain the
respondent `KEY`, row, and exact source cell. A Google Sheets input is
exported using the filename returned by the sheet into an isolated temporary
directory under `./.temp/` and deleted afterward, including when processing
fails. The source workbook is not mutated. The source and eventual output paths
must be different, and an existing output path requires `--overwrite`.

Ingestion reads only the `Survey`, `Code`, and `Data` sheets. It retains exact
respondent rows and `Data` source cells; no coding-destination tab is required
or interpreted.

Configuration can be supplied through `other-cluster.toml`, `OTHER_CLUSTER_CONFIG`,
or the environment (including an optional `.env` file):

```toml
input = "input.xlsx"
output = "coded-output.xlsx"
overwrite = false

[discovery]
min_unique_answer_texts = 3
```

CLI values take precedence over TOML, then environment variables, then the
built-in defaults.
