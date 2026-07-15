"""Minimal Language Server Protocol client (checklist Phase 5).

Gives ChatGPT real code intelligence — go-to-definition, find-references, hover
types, document symbols — instead of only text search. Speaks LSP (JSON-RPC with
Content-Length framing) to a language server spawned as a subprocess, one per
(workspace, language), reused across calls and shut down with the server.

Design:
  * No new hard dependency: if no language server is installed we degrade with a
    clear "install X" message. Detection is per-language, first match wins.
  * Synchronous request/response over stdio on a background reader thread. LSP is
    request/response with ids, so we match responses to requests by id.
  * Best-effort and defensive: a language server that misbehaves must never hang
    a tool call (every wait is bounded by a timeout).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path

# Per-language server candidates (command + args), first that resolves wins.
# All are optional; none is bundled.
_SERVERS: dict[str, list[tuple[str, list[str]]]] = {
    "python": [
        ("pyright-langserver", ["--stdio"]),
        ("basedpyright-langserver", ["--stdio"]),
        ("pylsp", []),
    ],
    "typescript": [("typescript-language-server", ["--stdio"])],
    "javascript": [("typescript-language-server", ["--stdio"])],
    "rust": [("rust-analyzer", [])],
    "go": [("gopls", [])],
}

_EXT_LANG = {
    ".py": "python", ".pyi": "python",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".rs": "rust", ".go": "go",
}

_LANG_ID = {"python": "python", "typescript": "typescript",
            "javascript": "javascript", "rust": "rust", "go": "go"}


def lang_for(path: str) -> str | None:
    return _EXT_LANG.get(Path(path).suffix.lower())


def server_for(language: str) -> tuple[str, list[str]] | None:
    for cmd, args in _SERVERS.get(language, []):
        if shutil.which(cmd):
            return cmd, args
    return None


def install_hint(language: str) -> str:
    hints = {
        "python": "pip install python-lsp-server  (or install pyright)",
        "typescript": "npm i -g typescript typescript-language-server",
        "javascript": "npm i -g typescript typescript-language-server",
        "rust": "rustup component add rust-analyzer",
        "go": "go install golang.org/x/tools/gopls@latest",
    }
    return hints.get(language, f"install a language server for {language}")


def _uri(path: Path) -> str:
    return path.as_uri()


class LSPServer:
    """One language-server subprocess for one (root, language)."""

    def __init__(self, cmd: str, args: list[str], root: Path):
        self.cmd = cmd
        self.root = root
        self._proc = subprocess.Popen(
            [cmd, *args], cwd=str(root),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self._id = 0
        self._lock = threading.Lock()
        self._responses: dict[int, dict] = {}
        self._cond = threading.Condition()
        self._opened: set[str] = set()
        self._alive = True
        threading.Thread(target=self._reader, daemon=True).start()
        self._initialize()

    # ---- wire protocol -----------------------------------------------------

    def _write(self, msg: dict) -> None:
        body = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        with self._lock:
            if self._proc.stdin:
                self._proc.stdin.write(header + body)
                self._proc.stdin.flush()

    def _reader(self) -> None:
        stream = self._proc.stdout
        try:
            while self._alive and stream:
                # read headers
                headers = {}
                while True:
                    line = stream.readline()
                    if not line:
                        return
                    line = line.strip()
                    if not line:
                        break
                    if b":" in line:
                        k, _, v = line.partition(b":")
                        headers[k.strip().lower()] = v.strip()
                length = int(headers.get(b"content-length", b"0"))
                if length <= 0:
                    continue
                body = stream.read(length)
                try:
                    msg = json.loads(body)
                except ValueError:
                    continue
                if "id" in msg and ("result" in msg or "error" in msg):
                    with self._cond:
                        self._responses[msg["id"]] = msg
                        self._cond.notify_all()
                # notifications/requests from server are ignored (we drive it)
        except Exception:  # noqa: BLE001 - reader thread must never crash the app
            pass

    def _request(self, method: str, params: dict, timeout: float = 8.0) -> dict | None:
        with self._cond:
            self._id += 1
            rid = self._id
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        with self._cond:
            ok = self._cond.wait_for(lambda: rid in self._responses, timeout=timeout)
            if not ok:
                return None
            return self._responses.pop(rid)

    def _notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    # ---- lifecycle ---------------------------------------------------------

    def _initialize(self) -> None:
        self._request("initialize", {
            "processId": None,
            "rootUri": _uri(self.root),
            "capabilities": {
                "textDocument": {
                    "definition": {"linkSupport": False},
                    "references": {},
                    "hover": {"contentFormat": ["plaintext", "markdown"]},
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                },
            },
        }, timeout=15.0)
        self._notify("initialized", {})

    def _ensure_open(self, path: Path) -> None:
        uri = _uri(path)
        if uri in self._opened:
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        lang = _LANG_ID.get(lang_for(str(path)) or "", "plaintext")
        self._notify("textDocument/didOpen", {
            "textDocument": {"uri": uri, "languageId": lang, "version": 1, "text": text},
        })
        self._opened.add(uri)

    def close(self) -> None:
        self._alive = False
        try:
            self._proc.terminate()
        except Exception:  # noqa: BLE001
            pass

    # ---- features ----------------------------------------------------------

    def definition(self, path: Path, line: int, col: int) -> dict | None:
        self._ensure_open(path)
        return self._request("textDocument/definition", _pos(path, line, col))

    def references(self, path: Path, line: int, col: int) -> dict | None:
        self._ensure_open(path)
        params = _pos(path, line, col)
        params["context"] = {"includeDeclaration": True}
        return self._request("textDocument/references", params)

    def hover(self, path: Path, line: int, col: int) -> dict | None:
        self._ensure_open(path)
        return self._request("textDocument/hover", _pos(path, line, col))

    def symbols(self, path: Path) -> dict | None:
        self._ensure_open(path)
        return self._request("textDocument/documentSymbol",
                             {"textDocument": {"uri": _uri(path)}})


def _pos(path: Path, line: int, col: int) -> dict:
    # LSP is 0-based; our tools take 1-based line, 0-based/1-based col tolerated.
    return {
        "textDocument": {"uri": _uri(path)},
        "position": {"line": max(0, line - 1), "character": max(0, col)},
    }


class LSPManager:
    """Owns the running language servers, one per (root, language). Lives on the
    HarnessServer; shut down with it."""

    def __init__(self):
        self._servers: dict[tuple[str, str], LSPServer] = {}
        self._lock = threading.Lock()

    def get(self, root: Path, language: str) -> LSPServer | None:
        key = (str(root), language)
        with self._lock:
            srv = self._servers.get(key)
            if srv is not None and srv._alive:
                return srv
            found = server_for(language)
            if found is None:
                return None
            cmd, args = found
            try:
                srv = LSPServer(cmd, args, root)
            except Exception:  # noqa: BLE001
                return None
            self._servers[key] = srv
            return srv

    def shutdown_all(self) -> None:
        with self._lock:
            for srv in self._servers.values():
                srv.close()
            self._servers.clear()
