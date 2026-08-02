"""
middle/col2_chart_indicators/divergence_detector.py
StochRSI 다이버전스 감지 전담 — 가격 스윙과 K 스윙 비교

상승 다이버전스(bull): 가격 저저점 + StochRSI K 고저점 동시 감지
하락 다이버전스(bear): 가격 고고점 + StochRSI K 저고점 동시 감지

입력: bars(OHLCV) + k_series(StochRSI.calculate_with_series() 반환값)
출력: "bull" | "bear" | None
"""
from __future__ import annotations

from middle.models import OHLCVBar


class DivergenceDetector:
    """StochRSI 다이버전스 감지기.

    bars와 k_series의 정렬(alignment):
      k_series[i] ↔ bars[offset + i]  (offset = len(bars) - len(k_series))
      k_series[-1] = 가장 최신 봉 (항상 offset = 30 for default params)
    """

    SWING_WINDOW = 3    # 스윙 포인트 양쪽 확인 봉 수
    MAX_LOOKBACK = 20   # 최근 N개 k값만 사용 (오래된 다이버전스 무시)

    @classmethod
    def detect(cls, bars: list[OHLCVBar], k_series: list[float]) -> str | None:
        """다이버전스 감지 진입점.

        Args:
            bars:     시간 순 OHLCV (OHLCVBar 리스트)
            k_series: calculate_with_series() 가 반환한 K 시리즈
        Returns:
            "bull" | "bear" | None
        """
        min_len = cls.SWING_WINDOW * 2 + 1
        if len(k_series) < min_len or len(bars) < len(k_series):
            return None

        # ── 정렬: k_series 후반 MAX_LOOKBACK개 ↔ 해당 bars 구간 ──
        k = k_series[-cls.MAX_LOOKBACK:]
        offset = len(bars) - len(k_series)
        aligned = bars[offset:][-cls.MAX_LOOKBACK:]

        if len(k) < min_len or len(aligned) != len(k):
            return None

        price_lows  = [b.low  for b in aligned]
        price_highs = [b.high for b in aligned]

        if cls._bullish(price_lows, k):
            return "bull"
        if cls._bearish(price_highs, k):
            return "bear"
        return None

    # ── 내부 헬퍼 ────────────────────────────────────────────────

    @classmethod
    def _swing_lows(cls, values: list[float]) -> list[tuple[int, float]]:
        """로컬 저점 목록 반환 [(index, value), ...]."""
        w = cls.SWING_WINDOW
        result = []
        for i in range(w, len(values) - w):
            v = values[i]
            if (all(v <= values[i - j] for j in range(1, w + 1)) and
                    all(v <= values[i + j] for j in range(1, w + 1))):
                result.append((i, v))
        return result

    @classmethod
    def _swing_highs(cls, values: list[float]) -> list[tuple[int, float]]:
        """로컬 고점 목록 반환 [(index, value), ...]."""
        w = cls.SWING_WINDOW
        result = []
        for i in range(w, len(values) - w):
            v = values[i]
            if (all(v >= values[i - j] for j in range(1, w + 1)) and
                    all(v >= values[i + j] for j in range(1, w + 1))):
                result.append((i, v))
        return result

    @classmethod
    def _bullish(cls, price_lows: list[float], k_vals: list[float]) -> bool:
        """상승 다이버전스: 가격 저저점 + K 고저점."""
        p_sw = cls._swing_lows(price_lows)
        k_sw = cls._swing_lows(k_vals)
        if len(p_sw) < 2 or len(k_sw) < 2:
            return False
        # 가장 최근 두 스윙 저점 비교
        return p_sw[-1][1] < p_sw[-2][1] and k_sw[-1][1] > k_sw[-2][1]

    @classmethod
    def _bearish(cls, price_highs: list[float], k_vals: list[float]) -> bool:
        """하락 다이버전스: 가격 고고점 + K 저고점."""
        p_sw = cls._swing_highs(price_highs)
        k_sw = cls._swing_highs(k_vals)
        if len(p_sw) < 2 or len(k_sw) < 2:
            return False
        # 가장 최근 두 스윙 고점 비교
        return p_sw[-1][1] > p_sw[-2][1] and k_sw[-1][1] < k_sw[-2][1]
