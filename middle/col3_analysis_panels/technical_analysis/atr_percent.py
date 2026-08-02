"""
middle/col3_analysis_panels/technical_analysis/atr_percent.py
ATR% 변동성 — Volatility Sort by 스코어의 핵심 지표
ATR(Average True Range)을 현재가 대비 % 로 표현
"""
from __future__ import annotations

from middle.models import OHLCVBar
from middle.widget.constants import ORANGE as _ORA, ACCENT_BLUE as _BLU, DIM_TEXT as _DIM


class AtrPercent:
    """ATR% 계산기.

    ATR = max(H-L, |H-prevC|, |L-prevC|) 의 N봉 이동평균
    ATR% = ATR / 현재가 × 100
    """

    DEFAULT_PERIOD = 14

    @classmethod
    def calculate(cls, bars: list[OHLCVBar], period: int = DEFAULT_PERIOD) -> float:
        """bars: 시간 순 OHLCV 리스트 (최소 period+1개 필요).
        반환: ATR% (float, %). 데이터 부족 시 0.0 반환.
        """
        if len(bars) < period + 1:
            return 0.0

        true_ranges: list[float] = []
        for i in range(1, len(bars)):
            high  = bars[i].high
            low   = bars[i].low
            prev_close = bars[i - 1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)

        if not true_ranges:
            return 0.0

        # Wilder smoothing (초기값: 단순평균)
        atr = sum(true_ranges[:period]) / period
        for tr in true_ranges[period:]:
            atr = (atr * (period - 1) + tr) / period

        current_price = bars[-1].close
        if current_price <= 0:
            return 0.0
        return round(atr / current_price * 100.0, 4)

    @staticmethod
    def label(v: float) -> str:
        return "고변동" if v > 5.0 else ("중변동" if v >= 2.0 else "저변동")

    @staticmethod
    def color(v: float) -> str:
        return _ORA if v > 5.0 else (_BLU if v >= 2.0 else _DIM)

