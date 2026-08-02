"""앱 상태 관리 — IDLE · RUNNING · ERROR"""
from __future__ import annotations
import threading
from header.models import HeaderStatus
from core.config import APP_RUNNING, APP_IDLE, APP_ERROR


class AppStatus:
    def __init__(self) -> None:
        self._status = HeaderStatus.IDLE
        self._lock = threading.Lock()

    def get(self) -> HeaderStatus:
        with self._lock:
            return self._status

    def set_running(self) -> None:
        with self._lock:
            self._status = HeaderStatus.RUNNING

    def set_idle(self) -> None:
        with self._lock:
            self._status = HeaderStatus.IDLE

    def set_error(self) -> None:
        with self._lock:
            self._status = HeaderStatus.ERROR

    def color(self) -> str:
        with self._lock:
            if self._status == HeaderStatus.RUNNING:
                return APP_RUNNING
            if self._status == HeaderStatus.ERROR:
                return APP_ERROR
            return APP_IDLE
