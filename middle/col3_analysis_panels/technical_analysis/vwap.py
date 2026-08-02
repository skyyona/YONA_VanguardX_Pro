"""
middle/col3_analysis_panels/technical_analysis/vwap.py
VWAP — Volume Weighted Average Price 이탈률
(현재가 - VWAP) / VWAP × 100 (%)
기술분석 패널 표시 및 진입 시점 참조에 사용
"""
from __future__ import annotations

from dataclasses import dataclass
from middle.models import OHLCVBar


@dataclass
class VWAPResult:
    vwap:        float   # VWAP 절대값
    deviation:   float   # 이탈률 % (양수=위, 음수=아래)
    label:       str     # 화면 표시용 설명
    position:    str     # "above" | "below" | "near"


class VWAP:
    """VWAP 이탈률 계산기.

    typical_price = (H + L + C) / 3
    VWAP = Σ(typical_price × volume) / Σ(volume)
    """

    NEAR_THRESHOLD = 0.3   # ±0.3% 이내면 "VWAP 근접"

    @classmethod
    def calculate(cls, bars: list[OHLCVBar]) -> VWAPResult:
        """VWAP 및 현재가 이탈률 계산.
        bars: 시간 순 OHLCV (당일 또는 최근 N봉)
        """
        if not bars:
            return VWAPResult(0.0, 0.0, "데이터 없음", "near")

        cum_pv = 0.0
        cum_v  = 0.0
        for b in bars:
            typical = (b.high + b.low + b.close) / 3.0
            cum_pv += typical * b.quote_volume
            cum_v  += b.quote_volume

        if cum_v <= 0:
            return VWAPResult(0.0, 0.0, "거래량 없음", "near")

        vwap = cum_pv / cum_v
        current = bars[-1].close

        if vwap <= 0:
            return VWAPResult(0.0, 0.0, "계산 불가", "near")

        deviation = (current - vwap) / vwap * 100.0

        position, label = cls._classify(deviation)
        return VWAPResult(
            vwap=round(vwap, 6),
            deviation=round(deviation, 3),
            label=label,
            position=position,
        )

    @classmethod
    def _classify(cls, deviation: float) -> tuple[str, str]:
        if deviation > 2.0:
            return "above", f"VWAP 위 +{deviation:.2f}% (매수 과열)"
        if deviation > cls.NEAR_THRESHOLD:
            return "above", f"VWAP 위 +{deviation:.2f}% (매수 우세)"
        if deviation < -2.0:
            return "below", f"VWAP 아래 {deviation:.2f}% (매도 과열)"
        if deviation < -cls.NEAR_THRESHOLD:
            return "below", f"VWAP 아래 {deviation:.2f}% (매도 우세)"
        return "near", f"VWAP 근접 {deviation:+.2f}% (균형)"

