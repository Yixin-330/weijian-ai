from __future__ import annotations

import json
from typing import Any


def serialize_job(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def deserialize_job(value: bytes) -> dict[str, Any]:
    decoded = json.loads(value.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("arq payload must be a JSON object")
    return decoded

