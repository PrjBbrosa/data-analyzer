"""One manager operation at a time; Tk consumes results on its own thread."""
from __future__ import annotations

import queue
import threading


class BackgroundOperation:
    def __init__(self):
        self.thread = None
        self._events = queue.Queue()
        self._pending = False

    def start(self, operation):
        if self._pending:
            raise RuntimeError("manager operation already pending")
        self._pending = True
        self.thread = threading.Thread(target=self._run, args=(operation,),
                                       name="extension-manager-operation", daemon=False)
        self.thread.start()

    def _run(self, operation):
        try:
            result = operation()
        except Exception as exc:
            self._events.put(("error", exc))
        else:
            self._events.put(("result", result))

    def poll(self):
        try:
            event = self._events.get_nowait()
        except queue.Empty:
            return None
        self.thread.join()  # result is posted as the final worker action
        self._pending = False
        return event
