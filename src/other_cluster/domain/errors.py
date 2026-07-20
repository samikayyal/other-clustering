"""Safe application errors for CLI exit mapping."""

from __future__ import annotations

import re

_SAFE_REASON_CODE = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")
_SAFE_STAGE = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")


class ApplicationError(Exception):
    """An application failure with safe, machine-readable context."""

    def __init__(self, *, stage: str, reason_code: str) -> None:
        if not _SAFE_STAGE.fullmatch(stage):
            raise ValueError("stage must be a safe machine-readable identifier")
        if not _SAFE_REASON_CODE.fullmatch(reason_code):
            raise ValueError("reason_code must be a safe machine-readable identifier")
        self.stage = stage
        self.reason_code = reason_code
        super().__init__(f"stage={stage} reason={reason_code}")


class InputContractError(ApplicationError):
    pass


class BudgetRejectedError(ApplicationError):
    pass


class ProviderPreflightError(ApplicationError):
    pass


class ProviderItemError(ApplicationError):
    pass


class CircuitBreakerError(ApplicationError):
    pass


class OutputArtifactError(ApplicationError):
    pass


InputSchemaError = InputContractError
BudgetRejectionError = BudgetRejectedError
ProviderItemFailureError = ProviderItemError
ArtifactIntegrityError = OutputArtifactError
