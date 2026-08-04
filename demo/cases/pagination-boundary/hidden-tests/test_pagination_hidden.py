from lib.pagination import page_count


def test_page_count_for_empty_and_partial_pages() -> None:
    assert page_count(0, 10) == 0
    assert page_count(21, 10) == 3
