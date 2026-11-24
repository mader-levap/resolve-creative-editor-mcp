"""What both stdio MCP servers share."""
import io
import sys


def use_utf8() -> None:
    """MCP speaks UTF-8; without this, stdio follows the locale (cp1250 on a Polish Windows) unless PYTHONUTF8 is set,
    and text outside it can't be read or written."""
    for stream in (sys.stdin, sys.stdout):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
