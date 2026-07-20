"""Small provider boundary protocols for later adapter slices."""

from typing import Protocol


class SemanticProvider(Protocol):
    """A provider adapter exposes only application-level operations."""

    def health_check(self) -> bool: ...
