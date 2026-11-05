"""주기적 갱신 타이머 (상주 스레드 1개 기반)

주기마다 새 스레드를 만들지 않는다 — Tk를 호출한 뒤 종료되는 스레드마다
Tcl 스레드별 Event 핸들이 1개씩 남음(2026-11-05 실측 분당 약 53개 증가).
"""
from __future__ import annotations
import logging
import threading
from collections.abc import Callable


class UpdateTimer:
    def __init__(self, interval_sec: float, callback: Callable[[], None]) -> None:
        self._interval  = interval_sec
        self._callback  = callback
        self._stop_evt: threading.Event | None = None   # 실행 중 = 정지 신호 객체 보유
        self._lock      = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._stop_evt is not None:
                return
            # 시작마다 새 정지 신호 — stop() 직후 재시작해도 이전 스레드는 자기 신호로 종료
            stop_evt = self._stop_evt = threading.Event()
        threading.Thread(target=self._run, args=(stop_evt,), daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            stop_evt, self._stop_evt = self._stop_evt, None
        if stop_evt is not None:
            stop_evt.set()

    def _run(self, stop_evt: threading.Event) -> None:
        # 콜백 종료 후 interval 대기 → 다음 콜백 (기존 Timer 재예약과 같은 주기)
        while not stop_evt.wait(self._interval):
            try:
                self._callback()
            except Exception as e:
                logging.warning("UpdateTimer callback error: %s", e)
