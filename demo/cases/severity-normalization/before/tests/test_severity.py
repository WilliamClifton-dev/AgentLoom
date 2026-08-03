import pytest

from src.severity import normalize_severity


def test_normalize_severity_accepts_surrounding_whitespace() -> None:
    assert normalize_severity(" high ") == "HIGH"


def test_normalize_severity_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="unsupported severity"):
        normalize_severity("urgent")
