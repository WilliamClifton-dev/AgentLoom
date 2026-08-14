def cap_retry_delay(requested: int, maximum: int = 60) -> int:
    if requested < 0:
        raise ValueError("requested delay must be non-negative")
    if maximum <= 0:
        raise ValueError("maximum delay must be positive")
    return min(requested, maximum)

