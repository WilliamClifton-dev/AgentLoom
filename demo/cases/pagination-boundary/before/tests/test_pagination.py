import pytest

from lib.pagination import page_count


def test_page_count_exact_multiple() -> None:
    assert page_count(20, 10) == 2


def test_page_count_rejects_invalid_page_size() -> None:
    with pytest.raises(ValueError, match="invalid pagination input"):
        page_count(10, 0)
