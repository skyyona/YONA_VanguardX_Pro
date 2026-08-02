"""주기적 갱신 타이머 (threading.Timer 기반)"""
from __future__ import annotations
import logging
import threading
from collections.abc import Callable


class UpdateTimer:
    def __init__(self, interval_sec: float, callback: Callable[[], None]) -> None:
        self._interval  = interval_sec
        self._callback  = callback
        self._timer: threading.Timer | None = None
        self._running   = False
        self._lock      = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
        self._schedule()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()

    def _schedule(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._timer = threading.Timer(self._interval, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            if not self._running:
                return
        try:
            self._callback()
        except Exception as e:
            logging.warning("UpdateTimer callback error: %s", e)
        self._schedule()
