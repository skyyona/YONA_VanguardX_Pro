"""bottom/trading_parameters/stop_loss.py
손절가(Stop Loss) 설정 및 계산"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class StopLoss:
    pct: float = 2.5  # 손절 % (진입가 대비)

    def long_sl_price(self, entry: float) -> float:
        return round(entry * (1 - self.pct / 100.0), 8)

    def short_sl_price(self, entry: float) -> float:
        return round(entry * (1 + self.pct / 100.0), 8)

    def validate(self) -> bool:
        return 0.1 <= self.pct <= 20.0
