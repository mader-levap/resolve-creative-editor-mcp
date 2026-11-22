"""Shorthand for writing tool schemas."""
from collections.abc import Iterable
from typing import Any

S, I, B, N = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}, {"type": "number"}


def T(name: str, desc: str, props: dict[str, Any] | None = None, req: Iterable[str] = ()) -> dict[str, Any]:
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props or {}, "required": list(req)}}
