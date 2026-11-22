"""The _operation block every result carries (status, verification, changes, warnings), an idea borrowed
from the upstream Resolve MCP."""


def op(status, verified=None, changes=None, warnings=(), **payload):
    verification = "unverified" if verified is None else ("passed" if verified else "contradiction")
    payload["_operation"] = {"status": status, "verification": verification, "changes": changes or {},
                             "warnings": list(warnings)}
    return payload


def blocked(reason):
    return op("blocked", reason=reason)


def preview(plan, warnings=()):
    return op("preview", plan=plan, warnings=warnings, next="Show this to the user; call again with confirm=true.")
