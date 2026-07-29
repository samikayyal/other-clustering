"""Errors shared by the configuration and workbook boundaries."""

from __future__ import annotations

from collections.abc import Iterable


class OtherClusterError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(OtherClusterError):
    """Raised when the fixed V1 CLI input boundary is invalid."""


class InputDownloadError(OtherClusterError):
    """Raised when a Google Sheets workbook cannot be downloaded."""


class EmbeddingError(OtherClusterError):
    """Raised when embeddings cannot be obtained or safely persisted."""


class CategoryDiscoveryError(OtherClusterError):
    """Raised when in-memory category discovery cannot produce valid evidence."""


class ClusterClassificationError(OtherClusterError):
    """Raised when cluster classification cannot safely be prepared."""


class ReviewFileError(OtherClusterError):
    """Raised when a schema-version-2 review file is invalid or cannot be saved."""


class WorkbookContractError(OtherClusterError):
    """Raised when a workbook cannot satisfy the supported XLSX contract."""

    def __init__(self, message: str | Iterable[str]) -> None:
        if isinstance(message, str):
            issues = (message,)
        else:
            issues = tuple(message)
        if not issues:
            issues = ("unknown workbook contract error",)
        self.issues = issues
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if len(self.issues) == 1:
            return self.issues[0]
        return "Workbook contract validation failed:\n" + "\n".join(
            f"- {issue}" for issue in self.issues
        )
