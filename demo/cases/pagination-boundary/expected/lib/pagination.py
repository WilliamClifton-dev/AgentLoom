def page_count(total_items: int, page_size: int) -> int:
    if total_items < 0 or page_size <= 0:
        raise ValueError("invalid pagination input")
    return (total_items + page_size - 1) // page_size
