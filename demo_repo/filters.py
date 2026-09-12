"""Data filtering and pagination utilities with boundary conditions."""

from __future__ import annotations

from typing import Any


def paginate_records(
    records: list[Any],
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """Paginate a sequence of records.
    
    Flaws:
    1. Does not validate page >= 1; if page <= 0, start_idx becomes negative,
       causing unexpected negative list slicing from the tail.
    2. Does not validate page_size > 0; if page_size == 0, raises ZeroDivisionError.
    3. Off-by-one on total_pages calculation when records list is empty.
    """
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size

    items = records[start_idx:end_idx]
    total_pages = (len(records) + page_size - 1) // page_size

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total_items": len(records),
        "total_pages": total_pages,
    }
