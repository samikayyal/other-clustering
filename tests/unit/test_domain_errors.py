import pytest

from other_cluster.domain import InputSchemaError


def test_errors_expose_only_safe_stage_and_reason():
    error = InputSchemaError(stage="input", reason_code="input.invalid_schema")
    assert str(error) == "stage=input reason=input.invalid_schema"
    assert "secret" not in repr(error).lower()

    with pytest.raises(ValueError, match="reason_code"):
        InputSchemaError(stage="input", reason_code="Raw answer: secret")

    with pytest.raises(ValueError, match="stage"):
        InputSchemaError(stage="Raw answer: secret", reason_code="input.invalid_schema")
