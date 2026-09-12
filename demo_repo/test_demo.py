import base64
import json
import pytest

from demo_repo.pricing import calculate_discounted_unit_price
from demo_repo.filters import paginate_records
from demo_repo.auth import parse_auth_header


def test_pricing_standard():
    result = calculate_discounted_unit_price(price=100.0, discount_percent=20.0, quantity=2)
    assert result == 40.0


def test_filters_standard():
    records = list(range(25))
    page1 = paginate_records(records, page=1, page_size=10)
    assert page1["items"] == list(range(10))
    assert page1["total_pages"] == 3
    assert page1["total_items"] == 25


def test_auth_standard():
    token_dict = {"user": {"id": "usr_123"}, "roles": ["admin", "viewer"]}
    token_str = base64.b64encode(json.dumps(token_dict).encode("utf-8")).decode("utf-8")
    header = f"Bearer {token_str}"

    auth_data = parse_auth_header(header)
    assert auth_data["authenticated"] is True
    assert auth_data["user_id"] == "usr_123"
    assert "admin" in auth_data["roles"]
