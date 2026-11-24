"""What both stdio MCP servers share."""
import io
import json
import sys
from typing import Any

from .. import media


def use_utf8() -> None:
    """MCP speaks UTF-8; without this, stdio follows the locale (cp1250 on a Polish Windows) unless PYTHONUTF8 is set,
    and text outside it can't be read or written."""
    for stream in (sys.stdin, sys.stdout):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")


def media_result(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run a media__ tool and return its MCP result: a contact sheet as an image and its details, the rest as JSON."""
    try:
        result = media.run_media_tool(name, args)
    except Exception as exc:
        return {"isError": True, "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}]}
    if name == "make_contact_sheet":
        details = {k: v for k, v in result.items() if k not in {"image", "mimeType"}}
        return {"content": [{"type": "image", "data": result["image"], "mimeType": result["mimeType"]},
                            {"type": "text", "text": json.dumps(details, ensure_ascii=False, indent=2)}]}
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}
