"""bottom/trading_parameters/trailing_stop.py
트레일링 스탑(Trailing Stop) 설정 및 동적 SL 추적"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class TrailingStop:
    pct: float = 1.5  # 트레일 거리 %

    def update_long_sl(self, current_high: float, trail_high: float) -> tuple[float, float]:
        new_high = max(trail_high, current_high)
        new_sl   = round(new_high * (1 - self.pct / 100.0), 8)
        return new_high, new_sl

    def update_short_sl(self, current_low: float, trail_low: float) -> tuple[float, float]:
        new_low = min(trail_low, current_low) if trail_low > 0 else current_low
        new_sl  = round(new_low * (1 + self.pct / 100.0), 8)
        return new_low, new_sl

    def validate(self) -> bool:
        return 0.1 <= self.pct <= 10.0
