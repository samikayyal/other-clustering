# other-cluster

CLI foundation for clustering one survey question's open-text `Other` answers.

```powershell
uv run other-cluster --help
uv run pytest
```

This first slice only supplies the package, CLI help surface, and provider-neutral
domain contracts. It does not read workbooks or call providers.
