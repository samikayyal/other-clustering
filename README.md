# other-cluster

CLI workflow for extracting one or more SurveyCTO `Other`-coding questions from
an `.xlsx` workbook. Feature 01 validates the workbook contract and builds the
row-level dataset used by later provider and review stages.

```powershell
uv run other-cluster --help
uv run other-cluster --input input.xlsx --output coded-output.xlsx
uv run pytest
```

The ingestion command prints a JSON summary and does not call external
providers or write the output workbook yet. The source and output paths must be
different, and an existing output path requires `--overwrite`.

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
