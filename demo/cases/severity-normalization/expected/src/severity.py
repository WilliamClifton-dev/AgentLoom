ALLOWED_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def normalize_severity(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in ALLOWED_SEVERITIES:
        raise ValueError(f"unsupported severity: {value}")
    return normalized
