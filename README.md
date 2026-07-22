# other-cluster

CLI workflow for extracting one or more SurveyCTO `Other`-coding questions from
an `.xlsx` workbook or a native Google Sheets link. Feature 01 validates the
workbook contract and builds the row-level dataset used by later provider and
review stages.

```powershell
uv run other-cluster --help
uv run other-cluster --input input.xlsx --output coded-output.xlsx
uv run other-cluster --input "https://docs.google.com/spreadsheets/d/ID/edit" --output coded-output.xlsx
uv run pytest
```

The ingestion command prints a JSON summary, writes the extracted records to
`./extracted_data/<normalized_input_name>_extracted.csv`, and does not call
external providers or write the output workbook yet. The CSV contains the
bilingual question text, original-language answer, respondent `KEY`, row, and
exact source cell. A Google Sheets input is exported using the filename
returned by the sheet into an isolated temporary directory under `./.temp/`
and deleted afterward, including when ingestion fails. The source and output
paths must be different, and an existing output path requires `--overwrite`.

Feature 01 reads only the `Survey`, `Code`, and `Data` sheets. It retains exact
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
