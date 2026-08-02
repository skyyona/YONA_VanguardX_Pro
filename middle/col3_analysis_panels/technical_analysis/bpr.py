"""
middle/col3_analysis_panels/technical_analysis/bpr.py
BPR — Buying Pressure Ratio (매수 압박 비율)
매수 체결량 / 전체 체결량 비율 (0.0 ~ 1.0)
Taker Long/Short ratio 또는 캔들 위치로 추정
"""
from __future__ import annotations

from middle.models import OHLCVBar
from middle.widget.constants import POSITIVE as _POS, NEGATIVE as _NEG, YELLOW as _YEL


class BPR:
    """Buying Pressure Ratio 계산기 — 캔들 종가 위치로 추정.

    (close - low) / (high - low)
    """

    @staticmethod
    def from_candle(bar: OHLCVBar) -> float:
        """캔들 종가 위치로 BPR 근사.
        (close - low) / (high - low)
        고점 근처 마감 → BPR 높음 (매수 압박 강함)
        """
        rng = bar.high - bar.low
        if rng <= 0:
            return 0.5
        return round((bar.close - bar.low) / rng, 4)

    @classmethod
    def from_candles(cls, bars: list[OHLCVBar], period: int = 14) -> float:
        """최근 N봉 캔들 기반 BPR 평균 (taker 데이터 없을 때 대체)."""
        if not bars:
            return 0.5
        recent = bars[-period:] if len(bars) >= period else bars
        values = [cls.from_candle(b) for b in recent]
        return round(sum(values) / len(values), 4)

    @staticmethod
    def label(v: float) -> str:
        return "(Bull)" if v > 0.65 else ("(Bear)" if v < 0.35 else "(Balanced)")

    @staticmethod
    def color(v: float) -> str:
        return _POS if v > 0.65 else (_NEG if v < 0.35 else _YEL)

