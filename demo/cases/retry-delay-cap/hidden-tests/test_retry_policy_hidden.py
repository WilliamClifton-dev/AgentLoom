from src.retry_policy import cap_retry_delay


def test_retry_delay_is_capped_and_preserves_boundary() -> None:
    assert cap_retry_delay(60, maximum=60) == 60
    assert cap_retry_delay(75, maximum=60) == 60
    assert cap_retry_delay(0, maximum=60) == 0

