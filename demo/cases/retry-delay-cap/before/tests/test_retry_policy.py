import pytest

from src.retry_policy import cap_retry_delay


def test_retry_delay_below_cap_is_preserved() -> None:
    assert cap_retry_delay(5, maximum=60) == 5


def test_retry_delay_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        cap_retry_delay(-1)
    with pytest.raises(ValueError):
        cap_retry_delay(1, maximum=0)

