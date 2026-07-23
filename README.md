# other-cluster

CLI workflow for extracting and embedding one or more SurveyCTO `Other`-coding
questions from an `.xlsx` workbook or a native Google Sheets link. The command
validates the workbook contract, builds the exact row-level dataset, and creates
original-language Nebius embeddings for the canonical question/text records.

```powershell
uv run other-cluster --help
uv run other-cluster --input input.xlsx --output coded-output.xlsx
uv run other-cluster --input "https://docs.google.com/spreadsheets/d/ID/edit" --output coded-output.xlsx
uv run pytest
```

The command requires `NEBIUS_API_KEY` in the environment or optional `.env`
when an answer is not already cached. It prints a JSON summary, writes extracted
records to `./extracted_data/<normalized_input_name>_extracted.csv`, retains
validated vectors and their row mappings in memory for the active process, and
keeps reusable exact-text vectors under `./embedding_cache/`. The cache contains
sensitive derived survey data and is retained until manually deleted.

Answers are sent exactly as extracted after HTML-tag cleanup, without
translation, prefixes, or other language changes. The CSV and in-memory row map
retain the respondent `KEY`, row, and exact source cell. A Google Sheets input is
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
