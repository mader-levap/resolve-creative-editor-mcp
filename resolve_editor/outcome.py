"""The _operation block every result carries (status, verification, changes, warnings), an idea borrowed
from the upstream Resolve MCP."""
from collections.abc import Iterable
from typing import Any


def op(status: str, verified: bool | None = None, changes: dict[str, Any] | None = None,
       warnings: Iterable[str] = (), **payload: Any) -> dict[str, Any]:
    verification = "unverified" if verified is None else ("passed" if verified else "contradiction")
    payload["_operation"] = {"status": status, "verification": verification, "changes": changes or {},
                             "warnings": list(warnings)}
    return payload


def blocked(reason: str) -> dict[str, Any]:
    return op("blocked", reason=reason)


def preview(plan: Any, warnings: Iterable[str] = ()) -> dict[str, Any]:
    return op("preview", plan=plan, warnings=warnings, next="Show this to the user; call again with confirm=true.")
