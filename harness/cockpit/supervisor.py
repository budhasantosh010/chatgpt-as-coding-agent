"""The supervisor: `python -m harness up`.

ONE process that:
  * serves the cockpit GUI on 127.0.0.1:<cockpit_port> (this process),
  * spawns the MCP engine (`harness serve`) as a CHILD process on :8848,
  * points the engine's event sink back at the cockpit's /_ingest,
  * monitors the child and offers restart/stop from the GUI.

Restarting the engine restarts the CHILD, never this process — so the cockpit
stays up and there is no self-kill paradox (the resolution of the launcher-vs-
self-restart blindspot).

The native folder picker also lives here (browsers can't reveal folder paths).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..config import Config
from .server import Cockpit, build_cockpit_app


class Supervisor:
    def __init__(self, config: Config):
        self.config = config
        self.cockpit = Cockpit(config, supervisor=self)
        self._engine: subprocess.Popen | None = None
        self._engine_lock = threading.Lock()
        self._want_engine = True

    # ---- engine child lifecycle -------------------------------------------

    def _engine_env(self) -> dict:
        env = dict(os.environ)
        port = self.config.cockpit_port
        env["HARNESS_EVENT_SINK"] = f"http://127.0.0.1:{port}/_ingest"
        env["HARNESS_EVENT_TOKEN"] = self.cockpit.ingest_token
        return env

    def start_engine(self) -> None:
        with self._engine_lock:
            if self._engine and self._engine.poll() is None:
                return
            self._engine = subprocess.Popen(
                [sys.executable, "-m", "harness", "serve"],
                env=self._engine_env(),
            )

    def stop_engine(self) -> None:
        with self._engine_lock:
            if self._engine and self._engine.poll() is None:
                self._engine.terminate()
                try:
                    self._engine.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self._engine.kill()
            self._engine = None

    def restart_engine(self) -> None:
        self.stop_engine()
        time.sleep(0.5)
        self.start_engine()

    def engine_status(self) -> str:
        with self._engine_lock:
            if self._engine is None:
                return "stopped"
            return "running" if self._engine.poll() is None else "crashed"

    def engine_busy(self) -> dict | None:
        """What a restart would interrupt (checklist 1.2): active tasks +
        background processes. Best-effort, read from shared state."""
        active = [t.id for t in self.cockpit.store.list_tasks()
                  if t.status.value in ("implementing", "validating", "repairing",
                                        "discovering", "planning")]
        if not active:
            return None
        return {"active_tasks": active}

    def _watchdog(self) -> None:
        # Auto-restart a crashed engine (checklist 1.3).
        while True:
            time.sleep(2.0)
            if not self._want_engine:
                continue
            with self._engine_lock:
                dead = self._engine is not None and self._engine.poll() is not None
            if dead:
                self.start_engine()

    # ---- native folder picker (checklist 1.4) ------------------------------

    def pick_folder(self) -> str | None:
        """Open the OS folder dialog on a fresh Tk root. Returns an absolute
        path or None if cancelled / unavailable."""
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception:  # noqa: BLE001 - headless / no Tk
            return None
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(title="Add a project folder")
            root.destroy()
            return path or None
        except Exception:  # noqa: BLE001
            return None

    # ---- run ---------------------------------------------------------------

    def run(self) -> int:
        import uvicorn

        threading.Thread(target=self._watchdog, daemon=True).start()
        self.start_engine()
        app = build_cockpit_app(self.cockpit)
        port = self.config.cockpit_port
        url = f"http://127.0.0.1:{port}/"
        print("=" * 60)
        print(" HARNESS COCKPIT — operator console")
        print(f"   Open:   {url}")
        print(f"   Engine: http://127.0.0.1:{self.config.port} (child, for ChatGPT)")
        print("   (Cockpit is localhost-only and never funneled.)")
        print("=" * 60)
        try:
            import webbrowser
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        except Exception:  # noqa: BLE001
            pass
        try:
            uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")
        finally:
            self._want_engine = False
            self.stop_engine()
        return 0


def run_supervisor(config: Config) -> int:
    return Supervisor(config).run()
