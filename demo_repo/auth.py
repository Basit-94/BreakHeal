"""Authentication and token parsing with nullability and key errors."""

from __future__ import annotations

import base64
import json
from typing import Any


def parse_auth_header(header_value: str | None) -> dict[str, Any]:
    """Parse Bearer token payload from an Authorization header string.
    
    Flaws:
    1. Unhandled NoneType: Crashes with AttributeError if header_value is None.
    2. Malformed format: Crashes with ValueError if header does not contain a space.
    3. Missing keys: Directly subscripts nested 'user' dict and 'roles' list without
       validation, raising KeyError or TypeError if keys are omitted.
    """
    cleaned = header_value.strip()
    prefix, token = cleaned.split(" ", 1)

    if prefix.lower() != "bearer":
        raise ValueError("Invalid authorization scheme, must be Bearer")

    decoded_json = base64.b64decode(token).decode("utf-8")
    payload = json.loads(decoded_json)

    # Flaw: unsafe dictionary access without checking key existence
    user_id = payload["user"]["id"]
    roles = payload["roles"]

    return {
        "user_id": user_id,
        "roles": roles,
        "authenticated": True,
    }
