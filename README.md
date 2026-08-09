# other-cluster

Local Cluster-First V1 review tooling for SurveyCTO `Other` answers. The
complete behavior contract is [context/v1-contract.md](context/v1-contract.md).

## Install and run

Python 3.13+ and [uv](https://docs.astral.sh/uv/) are required.

```powershell
uv sync
uv run other-cluster analyze --input input.xlsx
uv run other-cluster analyze --input "https://docs.google.com/spreadsheets/d/ID/edit"
uv run other-cluster review --review-file reviews\input_<analysis-run-id>.json
uv run other-cluster evaluate --review-file reviews\input_<analysis-run-id>.json
uv run other-cluster evaluate --review-file reviews\input_<analysis-run-id>.json --ground-truth "real\coding-sheet.gsheet"
uv run pytest
```

Use `uv add <package>` for dependencies and `uv run <command>` for all Python
commands. The supported entry points are the `other-cluster` console command
and `python -m other_cluster`; the repository has no top-level launcher.

## Secrets and privacy

Set `NEBIUS_API_KEY` when required Qwen discovery vectors are not already in
`embedding_cache`, and set `GEMINI_API_KEY` when proposal-eligible clusters
exist. Each can be a process environment variable or a value in a
current-directory `.env`; do not commit that file.

Review JSON stores canonical answer evidence, including respondent/cell mappings,
and must be treated as sensitive local data. `embedding_cache` contains exact
answer text, instruction-prefixed provider inputs, and derived vectors, and must
also be treated as sensitive. Google Sheets XLSX exports are created in the
operating system temporary directory and are removed after each run.

Add `--ground-truth` to `evaluate` to compare the immutable discovery evidence
to the human `_C1` codes in the reference workbook's `Work` tab. The benchmark
accepts a local XLSX file, a Google Sheets URL, or a local `.gsheet` pointer and
does not change either source. Ground truth is not accepted or displayed by the
analyst `review` workspace.
