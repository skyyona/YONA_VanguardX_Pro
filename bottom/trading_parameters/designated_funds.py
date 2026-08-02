"""bottom/trading_parameters/designated_funds.py
운용 자금(Designated Funds) 설정 — 포트폴리오 대비 %"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class DesignatedFunds:
    pct: int = 100  # 1~100 (%)
    total_usdt: float = 0.0  # 전체 포트폴리오 USDT

    @property
    def allocated_usdt(self) -> float:
        return self.total_usdt * (self.pct / 100.0)

    def validate(self) -> bool:
        return 1 <= self.pct <= 100 and self.total_usdt > 0
