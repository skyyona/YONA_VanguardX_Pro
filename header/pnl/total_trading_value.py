"""Total Trading Value — 총 거래 평가금액 추적"""
import threading


class TotalTradingValue:
    def __init__(self) -> None:
        self._value: float = 0.0
        self._lock = threading.Lock()

    def update(self, value_usdt: float) -> None:
        with self._lock:
            self._value = max(0.0, value_usdt)

    def get(self) -> float:
        with self._lock:
            return self._value
