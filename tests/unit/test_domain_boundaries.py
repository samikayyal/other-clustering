from pathlib import Path


def test_domain_does_not_import_boundary_implementations():
    domain_dir = Path(__file__).parents[2] / "src" / "other_cluster" / "domain"
    forbidden = ("openpyxl", "httpx", "other_cluster.cli", "pathlib")
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in domain_dir.glob("*.py")
    )
    assert not any(name in source for name in forbidden)
