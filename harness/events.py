"""Structured live-event bus (checklist 0.9).

The audit log (audit.jsonl) is the permanent historical record. This bus is the
LIVE channel: every event gets a monotonic event_id so a consumer can resume
exactly where it left off (SSE Last-Event-ID), and an optional HTTP sink pushes
events to the supervisor process (which serves the cockpit on localhost:8849).

Design constraints:
  * publishing must NEVER slow or break a tool call — the sink runs on a
    daemon thread with a bounded queue and drops on overflow/failure;
  * the in-memory ring buffer bounds replay memory;
  * the sink URL/token come from config; the supervisor sets them when it
    spawns the engine, so a standalone engine simply has no sink (events still
    reach audit.jsonl as before).
"""

from __future__ import annotations

import json
import queue
import threading
import urllib.request
from collections import deque


def _now_iso() -> str:
    from .session import _now_iso as f

    return f()


class EventBus:
    def __init__(self, sink_url: str = "", sink_token: str = "", maxlen: int = 1000):
        self._buffer: deque = deque(maxlen=maxlen)
        self._next_id = 1
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue] = []
        self._sink_url = (sink_url or "").strip()
        self._sink_q: queue.Queue | None = None
        if self._sink_url:
            self._sink_q = queue.Queue(maxsize=500)
            t = threading.Thread(
                target=self._sink_worker, args=(self._sink_url, sink_token), daemon=True
            )
            t.start()

    # ---- publish/consume -----------------------------------------------------

    def publish(self, type: str, task_id: str | None = None, **data) -> dict:
        with self._lock:
            event = {
                "event_id": self._next_id,
                "time": _now_iso(),
                "type": type,
                "task_id": task_id,
                "data": data,
            }
            self._next_id += 1
            self._buffer.append(event)
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # a slow consumer loses events; replay via since()
        if self._sink_q is not None:
            try:
                self._sink_q.put_nowait(event)
            except queue.Full:
                pass  # never block a tool call on a slow sink
        return event

    def since(self, last_id: int) -> list[dict]:
        with self._lock:
            return [e for e in self._buffer if e["event_id"] > last_id]

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    # ---- HTTP sink (engine -> supervisor push) --------------------------------

    def _sink_worker(self, url: str, token: str) -> None:
        while True:
            event = self._sink_q.get()
            try:
                body = json.dumps(event, ensure_ascii=False).encode("utf-8")
                req = urllib.request.Request(
                    url, data=body, method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "X-Harness-Event-Token": token or "",
                    },
                )
                urllib.request.urlopen(req, timeout=2).read()
            except Exception:  # noqa: BLE001 - the sink is best-effort by design
                pass


def make_event_hook(bus: EventBus):
    """Pre-hook: publish every tool call to the live bus (the SSE feed's main
    signal). Same shape the audit hook records, so the cockpit's activity view
    and audit.jsonl agree."""

    def _publish(call) -> None:
        try:
            hc = call.context
            args = call.args or ()
            detail = args[0][:160] if (args and isinstance(args[0], str)) else ""
            bus.publish(
                "tool_call",
                task_id=getattr(hc, "task_id", None),
                tool=call.tool,
                capability=call.capability.value if call.capability else None,
                mode=getattr(getattr(hc, "policy", None), "mode", None),
                detail=detail,
            )
        except Exception:  # noqa: BLE001 - events must never break a tool call
            pass

    return _publish
