"""One child MCP server process, spoken to over stdio."""
import contextlib
import json
import os
import pathlib
import queue
import subprocess
import threading
import time
from typing import Any

from .. import __version__


class Child:
    """One child MCP server process, spoken to over its stdin and stdout."""
    def __init__(self, label: str, command: list[str], cwd: pathlib.Path):
        self.label = label
        self.command = command
        self.cwd = str(cwd)
        self.proc: subprocess.Popen[str] | None = None
        self.next_id = 1
        self.lock = threading.Lock()
        self.responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self.reader: threading.Thread | None = None
        self.initialize_result: dict[str, Any] | None = None
        self.tools: list[dict[str, Any]] = []

    def start(self, protocol_version: str) -> None:
        """Start the process (if not running), do the MCP handshake and load its tool list."""
        if self.proc and self.proc.poll() is None:
            return
        self.proc = subprocess.Popen(
            self.command, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=None, text=True, encoding="utf-8", errors="replace", bufsize=1,
            env=os.environ.copy(),
        )
        self.reader = threading.Thread(target=self._read_responses, daemon=True, name=f"{self.label}-stdout")
        self.reader.start()
        result = self.request("initialize", {
            "protocolVersion": protocol_version,
            "capabilities": {},
            "clientInfo": {"name": "resolve-creative-editor-gateway", "version": __version__},
        })
        if "error" in result:
            raise RuntimeError(f"{self.label} initialize failed: {result['error']}")
        self.initialize_result = result.get("result", {})
        self.notify("notifications/initialized", {})
        listed = self.request("tools/list", {})
        if "error" in listed:
            raise RuntimeError(f"{self.label} tools/list failed: {listed['error']}")
        self.tools = listed.get("result", {}).get("tools", [])

    def _read_responses(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(response, dict) and "id" in response:
                self.responses.put(response)

    def request(self, method: str, params: dict[str, Any], timeout: float = 180.0) -> dict[str, Any]:
        """Send one request and wait for its reply; one at a time. Raises when the process isn't running or
        TimeoutError after `timeout`; a reply that comes after its timeout is discarded later."""
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError(f"{self.label} MCP process is not running")
        with self.lock:
            request_id = self.next_id
            self.next_id += 1
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            assert self.proc.stdin is not None
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            deadline = time.monotonic() + timeout
            while True:  # discard late replies to requests that already timed out
                try:
                    response = self.responses.get(timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty as exc:
                    raise TimeoutError(f"{self.label} timed out handling {method} after {timeout:g}s") from exc
                if response.get("id") == request_id:
                    return response

    def notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a notification (no reply expected); does nothing when the process isn't running."""
        if self.proc and self.proc.poll() is None and self.proc.stdin:
            self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
            self.proc.stdin.flush()

    def close(self) -> None:
        """Stop the process and close its pipes; harmless when already closed. An MCP server stops at the end of its
        input, so it gets 2 s to exit by itself (its own cleanup runs); then terminate, then kill after 3 s more."""
        if not self.proc:
            return
        if self.proc.poll() is None:
            if self.proc.stdin:
                with contextlib.suppress(OSError):
                    self.proc.stdin.close()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
        if self.reader:
            self.reader.join(timeout=3)  # the process is gone, so it reads EOF; then stdout is no longer in use
        for stream in (self.proc.stdin, self.proc.stdout):
            if stream:
                stream.close()
