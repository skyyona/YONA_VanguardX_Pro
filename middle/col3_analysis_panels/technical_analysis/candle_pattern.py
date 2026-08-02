"""
middle/col3_analysis_panels/technical_analysis/candle_pattern.py
주요 캔들 패턴 감지 (기술분석 패널 표시용)
도지·장악형·망치형·슈팅스타·하락장악형 등 감지
"""
from __future__ import annotations

from middle.models import OHLCVBar


class CandlePattern:
    """캔들 패턴 감지기.

    최소 2봉(현재 + 직전) 기준으로 주요 패턴을 감지.
    """

    # 도지 판단 기준: 몸통 / 전체 길이 비율
    DOJI_RATIO = 0.1
    # 장악형 판단: 현재 봉이 직전 봉 몸통을 완전히 감싸는 비율 기준
    ENGULF_RATIO = 1.0
    # 망치형/슈팅스타: 수염 길이 / 전체 길이
    HAMMER_WICK_RATIO = 0.6

    @classmethod
    def detect(cls, bars: list[OHLCVBar]) -> str:
        """최신 봉 기준 패턴 감지. 감지된 패턴명 반환 (없으면 "패턴 없음").
        bars: 시간 순 OHLCV (최소 2봉)
        """
        if len(bars) < 2:
            return "데이터 부족"

        cur  = bars[-1]
        prev = bars[-2]

        # ── 현재 봉 기본값 ──────────────────────────
        c_body  = abs(cur.close - cur.open)
        c_range = cur.high - cur.low
        if c_range <= 0:
            return "패턴 없음"

        # ── 도지 (몸통이 매우 작음) ─────────────────
        if c_body / c_range <= cls.DOJI_RATIO:
            return "도지 🕯️  (추세 전환 주시)"

        c_is_bull = cur.close > cur.open
        p_is_bull = prev.close > prev.open
        p_body    = abs(prev.close - prev.open)

        # ── 강세 장악형 (Bullish Engulfing) ─────────
        if (not p_is_bull and c_is_bull
                and cur.open <= min(prev.open, prev.close)
                and cur.close >= max(prev.open, prev.close)):
            return "강세 장악형 🕯️  (상승 반전 신호)"

        # ── 약세 장악형 (Bearish Engulfing) ─────────
        if (p_is_bull and not c_is_bull
                and cur.open >= max(prev.open, prev.close)
                and cur.close <= min(prev.open, prev.close)):
            return "약세 장악형 🕯️  (하락 반전 신호)"

        c_upper_wick = cur.high - max(cur.open, cur.close)
        c_lower_wick = min(cur.open, cur.close) - cur.low

        # ── 망치형 (Hammer) — 하락 추세 후 하단 수염 ──
        if (c_is_bull
                and c_lower_wick >= c_range * cls.HAMMER_WICK_RATIO
                and c_upper_wick <= c_body * 0.3):
            return "망치형 🔨  (상승 반전 가능)"

        # ── 슈팅스타 (Shooting Star) — 상단 수염 ─────
        if (not c_is_bull
                and c_upper_wick >= c_range * cls.HAMMER_WICK_RATIO
                and c_lower_wick <= c_body * 0.3):
            return "슈팅스타 ⭐  (하락 반전 가능)"

        # ── 강세 장대 양봉 ──────────────────────────
        if c_is_bull and c_body >= c_range * 0.7:
            return "장대 양봉 📈  (강세 지속)"

        # ── 약세 장대 음봉 ──────────────────────────
        if not c_is_bull and c_body >= c_range * 0.7:
            return "장대 음봉 📉  (약세 지속)"

        return "패턴 없음 —"

