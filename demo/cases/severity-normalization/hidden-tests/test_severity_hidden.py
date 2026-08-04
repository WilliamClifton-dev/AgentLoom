from src.severity import normalize_severity


def test_normalize_severity_handles_tabs_and_newlines() -> None:
    assert normalize_severity("\tcritical\n") == "CRITICAL"
