"""Consistent response envelope: {"data": ..., "meta": {...}}"""
from typing import Any


def ok(data: Any, **meta) -> dict:
    return {"data": data, "meta": meta}
