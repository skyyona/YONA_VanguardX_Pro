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
    계산 값은 반올림하지 않는다 — 백테스트(_calc_kd)와 같은 값으로 엔진 판정(G_K·KD 익절·G6·G7.5) 일치,
    자릿수는 화면 표시에서만 정한다.
    """

    RSI_PERIOD    = 14
    STOCH_PERIOD  = 14
    SMOOTH_K      = 3    # K 스무딩
    SMOOTH_D      = 3    # D 스무딩

    # 방향 판정 최소 K−D 차이 — 백테스트 tf5 교차 추적·G7.5와 같은 기준(bottom_engine.constants._MIN_SPREAD)
    MIN_SPREAD = 2.0

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

        k = k_series[-1]
        d = d_series[-1]

        direction = cls._classify(k, d)
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

        k = k_series[-1]
        d = d_series[-1]
        direction = cls._classify(k, d)
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
            series.append(100.0 - 100.0 / (1.0 + rs))
        return series

    @staticmethod
    def _sma(data: list[float], period: int) -> list[float]:
        return [
            sum(data[i - period + 1 : i + 1]) / period
            for i in range(period - 1, len(data))
        ]

    @classmethod
    def _classify(cls, k: float, d: float) -> str:
        """방향 — K가 D보다 MIN_SPREAD 이상 위 ▲ / 아래 ▼ / 그 외 ↔(중립).
        엔진 G7.5·백테스트 G6 지속성(교차 시점)과 같은 정의 → 방향이 바뀐 시점부터의 경과(elapsed)가 백테스트와 일치.
        과매수·과매도(K 80·20)는 방향을 덮어쓰지 않는다 (K값 표시로 확인)."""
        if k - d >= cls.MIN_SPREAD:
            return "▲"
        if d - k >= cls.MIN_SPREAD:
            return "▼"
        return "↔"
