"""The _operation block every result carries (status, verification, changes, warnings), an idea borrowed
from the upstream Resolve MCP."""
from collections.abc import Iterable
from typing import Any, Literal

# preview: nothing changed yet, confirm to apply; planned: a dry run's result; blocked: refused before any change
Status = Literal["success", "partial", "failed", "preview", "blocked", "planned"]


def op(status: Status, verified: bool | None = None, changes: dict[str, Any] | None = None,
       warnings: Iterable[str] = (), **payload: Any) -> dict[str, Any]:
    verification = "unverified" if verified is None else ("passed" if verified else "contradiction")
    payload["_operation"] = {"status": status, "verification": verification, "changes": changes or {},
                             "warnings": list(warnings)}
    return payload


def blocked(reason: str) -> dict[str, Any]:
    return op("blocked", reason=reason)


def preview(plan: Any, warnings: Iterable[str] = ()) -> dict[str, Any]:
    return op("preview", plan=plan, warnings=warnings,
              next="Show this to the user; call again with confirm=true and timeline=<this result's timeline>.")
