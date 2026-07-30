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
uv run pytest
```

Use `uv add <package>` for dependencies and `uv run <command>` for all Python
commands. The supported entry points are the `other-cluster` console command
and `python -m other_cluster`; the repository has no top-level launcher.

## Secrets and privacy

Set `NEBIUS_API_KEY` when uncached embeddings are required and `GEMINI_API_KEY`
when proposal-eligible clusters exist. They can be process environment variables
or values in a current-directory `.env`; do not commit that file.

The local embedding cache stores exact answer text and derived vectors in
`embedding_cache/cache.sqlite3`. Review JSON stores canonical answer evidence,
including respondent/cell mappings. Treat both as sensitive local data. Google
Sheets XLSX exports are created in the operating system temporary directory and
are removed after each run. Old caches with an incompatible embedding contract
must be deleted and rebuilt.
