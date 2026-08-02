"""
middle/col3_analysis_panels/technical_analysis/rsi.py
RSI (Relative Strength Index) — 멀티 타임프레임 (1m·5m·1h·4h)
종합분석 선정 근거 / Sharp rise·decline 스코어링에 사용
"""
from __future__ import annotations

from middle.models import OHLCVBar
from middle.widget.constants import POSITIVE as _POS, NEGATIVE as _NEG, ACCENT_BLUE as _BLU


class RSI:
    """RSI 계산기 (Wilder smoothing)."""

    DEFAULT_PERIOD = 14

    @classmethod
    def calculate(cls, bars: list[OHLCVBar], period: int = DEFAULT_PERIOD) -> float:
        """Wilder smoothing RSI 반환 (0~100).
        bars: 시간 순 OHLCV 리스트 (최소 period+1개 필요).
        데이터 부족 시 50.0 반환.
        """
        closes = [b.close for b in bars]
        return cls.from_closes(closes, period)

    @classmethod
    def from_closes(cls, closes: list[float], period: int = DEFAULT_PERIOD) -> float:
        if len(closes) < period + 1:
            return 50.0

        gains, losses = [], []
        for i in range(1, len(closes)):
            delta = closes[i] - closes[i - 1]
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100.0 - 100.0 / (1.0 + rs), 2)

    @staticmethod
    def label(v: float) -> str:
        return "(Overbought)" if v > 70 else ("(Oversold)" if v < 30 else "(Neutral)")

    @staticmethod
    def color(v: float) -> str:
        return _NEG if v > 70 else (_POS if v < 30 else _BLU)

