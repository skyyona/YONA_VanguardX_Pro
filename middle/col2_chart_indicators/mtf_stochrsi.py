"""
middle/col2_chart_indicators/mtf_stochrsi.py
MTF StochRSI — 멀티 타임프레임 Stochastic RSI 계산 전담
data_manager.py 가 STAGE3/STAGE1(온디맨드) 에서 직접 호출.
K: RSI 스토캐스틱 N봉 SMA / D: K의 M봉 SMA
"""
from __future__ import annotations

from dataclasses import dataclass
from middle.models import OHLCVBar


@dataclass
class StochRSIResult:
    k:         float   # Fast %K (0~100)
    d:         float   # Slow %D (0~100)
    direction: str     # "▲" | "▼" | "↔"


class StochRSI:
    """Stochastic RSI 계산기.

    1. RSI 시리즈 계산 (Wilder smoothing)
    2. 스토캐스틱: (RSI - min_RSI) / (max_RSI - min_RSI) × 100
    3. K = stoch의 smooth_k봉 SMA
    4. D = K의 smooth_d봉 SMA
    """

    RSI_PERIOD    = 14
    STOCH_PERIOD  = 14
    SMOOTH_K      = 3    # K 스무딩
    SMOOTH_D      = 3    # D 스무딩

    OVERBOUGHT = 80.0
    OVERSOLD   = 20.0

    @classmethod
    def calculate(
        cls,
        bars: list[OHLCVBar],
        rsi_period:   int = RSI_PERIOD,
        stoch_period: int = STOCH_PERIOD,
        smooth_k:     int = SMOOTH_K,
        smooth_d:     int = SMOOTH_D,
    ) -> StochRSIResult:
        """StochRSI K·D 계산.
        bars: 시간 순 OHLCV (최소 rsi_period + stoch_period + smooth_k + smooth_d 개 필요)
        """
        closes = [b.close for b in bars]
        min_needed = rsi_period + stoch_period + smooth_k + smooth_d + 2

        if len(closes) < min_needed:
            return StochRSIResult(50.0, 50.0, "↔")

        # ── 1. RSI 시리즈 ────────────────────────────
        rsi_series = cls._rsi_series(closes, rsi_period)

        # ── 2. 스토캐스틱 시리즈 ────────────────────
        stoch_series: list[float] = []
        for i in range(stoch_period - 1, len(rsi_series)):
            window = rsi_series[i - stoch_period + 1 : i + 1]
            lo, hi = min(window), max(window)
            if hi == lo:
                stoch_series.append(50.0)
            else:
                stoch_series.append((rsi_series[i] - lo) / (hi - lo) * 100.0)

        if len(stoch_series) < smooth_k + smooth_d:
            return StochRSIResult(50.0, 50.0, "↔")

        # ── 3. K = stoch 의 SMA(smooth_k) ───────────
        k_series = cls._sma(stoch_series, smooth_k)

        if len(k_series) < smooth_d:
            return StochRSIResult(50.0, 50.0, "↔")

        # ── 4. D = K 의 SMA(smooth_d) ────────────────
        d_series = cls._sma(k_series, smooth_d)

        k = round(k_series[-1], 2)
        d = round(d_series[-1], 2)

        direction = cls._classify(k, d,
                                  k_series[-2] if len(k_series) >= 2 else k,
                                  d_series[-2] if len(d_series) >= 2 else d)
        return StochRSIResult(k=k, d=d, direction=direction)

    @classmethod
    def calculate_with_series(
        cls,
        bars: list[OHLCVBar],
        rsi_period:   int = RSI_PERIOD,
        stoch_period: int = STOCH_PERIOD,
        smooth_k:     int = SMOOTH_K,
        smooth_d:     int = SMOOTH_D,
    ) -> tuple[StochRSIResult, list[float]]:
        """StochRSIResult + k_series 전체 반환. 다이버전스 감지용.
        k_series[i] ↔ bars[len(bars)-len(k_series)+i] (1:1 시간 정렬)
        """
        closes = [b.close for b in bars]
        min_needed = rsi_period + stoch_period + smooth_k + smooth_d + 2

        if len(closes) < min_needed:
            return StochRSIResult(50.0, 50.0, "↔"), []

        rsi_series = cls._rsi_series(closes, rsi_period)

        stoch_series: list[float] = []
        for i in range(stoch_period - 1, len(rsi_series)):
            window = rsi_series[i - stoch_period + 1 : i + 1]
            lo, hi = min(window), max(window)
            if hi == lo:
                stoch_series.append(50.0)
            else:
                stoch_series.append((rsi_series[i] - lo) / (hi - lo) * 100.0)

        if len(stoch_series) < smooth_k + smooth_d:
            return StochRSIResult(50.0, 50.0, "↔"), []

        k_series = cls._sma(stoch_series, smooth_k)

        if len(k_series) < smooth_d:
            return StochRSIResult(50.0, 50.0, "↔"), []

        d_series = cls._sma(k_series, smooth_d)

        k = round(k_series[-1], 2)
        d = round(d_series[-1], 2)
        direction = cls._classify(k, d,
                                  k_series[-2] if len(k_series) >= 2 else k,
                                  d_series[-2] if len(d_series) >= 2 else d)
        return StochRSIResult(k=k, d=d, direction=direction), k_series

    @staticmethod
    def _rsi_series(closes: list[float], period: int) -> list[float]:
        """Wilder smoothing RSI 시리즈 전체 반환."""
        if len(closes) < period + 1:
            return [50.0] * len(closes)
        gains  = [max(closes[i] - closes[i-1], 0.0) for i in range(1, len(closes))]
        losses = [max(closes[i-1] - closes[i], 0.0) for i in range(1, len(closes))]
        avg_g  = sum(gains[:period])  / period
        avg_l  = sum(losses[:period]) / period
        series: list[float] = []
        for i in range(period, len(gains)):
            avg_g = (avg_g * (period - 1) + gains[i])  / period
            avg_l = (avg_l * (period - 1) + losses[i]) / period
            rs = avg_g / avg_l if avg_l > 0 else 100.0
            series.append(round(100.0 - 100.0 / (1.0 + rs), 4))
        return series

    @staticmethod
    def _sma(data: list[float], period: int) -> list[float]:
        return [
            sum(data[i - period + 1 : i + 1]) / period
            for i in range(period - 1, len(data))
        ]

    @classmethod
    def _classify(cls, k: float, d: float,
                  prev_k: float, prev_d: float) -> str:
        # 골든크로스: K가 D를 하향에서 상향 돌파
        if prev_k <= prev_d and k > d:
            return "▲"
        # 데드크로스: K가 D를 상향에서 하향 돌파
        if prev_k >= prev_d and k < d:
            return "▼"
        if k >= cls.OVERBOUGHT:
            return "▲"
        if k <= cls.OVERSOLD:
            return "▼"
        if k > d:
            return "▲"
        if k < d:
            return "▼"
        return "↔"
