"""bottom/trading_parameters/applied_leverage.py
레버리지 설정 — UI 입력 제한: 1~20x (실용 상한, 고레버리지 사용자 실수 방지).
엔진 하드 리밋(RiskManager.MAX_LEVERAGE=125)과는 역할이 다름 — 값 변경 시 둘 다 검토 필요."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class AppliedLeverage:
    value: int = 10  # 1~20

    def validate(self) -> bool:
        return 1 <= self.value <= 20

    def position_size_usdt(self, allocated_usdt: float) -> float:
        return allocated_usdt * self.value

    def margin_required(self, notional: float) -> float:
        return notional / self.value
