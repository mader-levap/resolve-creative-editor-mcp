"""The _operation block every result carries (status, verification, changes, warnings), an idea borrowed
from the upstream Resolve MCP."""
from collections.abc import Iterable
from typing import Any, Literal

# preview: nothing changed yet, confirm to apply; planned: a dry run's result; blocked: refused before any change
Status = Literal["success", "partial", "failed", "preview", "blocked", "planned"]


def op(status: Status, verified: bool | None = None, changes: dict[str, Any] | None = None,
       warnings: Iterable[str] = (), **payload: Any) -> dict[str, Any]:
    """The result every writing tool returns. verified: None = unverified (couldn't be read back), True = passed,
    False = contradiction (read-back differs). Other keyword arguments become top-level keys of the result."""
    verification = "unverified" if verified is None else ("passed" if verified else "contradiction")
    payload["_operation"] = {"status": status, "verification": verification, "changes": changes or {},
                             "warnings": list(warnings)}
    return payload


def blocked(reason: str) -> dict[str, Any]:
    """Refused before anything changed, with the reason for the user."""
    return op("blocked", reason=reason)


def preview(plan: Any, warnings: Iterable[str] = ()) -> dict[str, Any]:
    """What a confirm would do; nothing has changed. dispatch.run adds the timeline the confirm must name."""
    return op("preview", plan=plan, warnings=warnings,
              next="Show this to the user; call again with confirm=true and timeline=<this result's timeline>.")
