"""
middle/col3_analysis_panels/technical_analysis/ema_alignment.py
EMA 정배열·역배열 판단 (5 / 10 / 20 기간)
4TF Optimization 스코어링 + 기술분석 패널 표시에 사용
"""
from __future__ import annotations

from dataclasses import dataclass
from middle.models import OHLCVBar


@dataclass
class EMAResult:
    ema5:  float
    ema10: float
    ema20: float
    ema50: float   # EMA50 — 50봉 이상 데이터 시 유효
    align: str     # "정배열" | "역배열" | "혼조"
    label: str     # 화면 표시용 한글 설명


class EMAAlignment:
    """EMA 5/10/20 정배열·역배열 계산기."""

    @staticmethod
    def _ema(prices: list[float], period: int) -> float:
        """단순 EMA 계산 (마지막 값 반환)."""
        if not prices:
            return 0.0
        k = 2.0 / (period + 1)
        val = prices[0]
        for p in prices[1:]:
            val = p * k + val * (1 - k)
        return round(val, 8)

    @classmethod
    def calculate(cls, bars: list[OHLCVBar]) -> EMAResult:
        """EMA 5/10/20 계산 및 정배열/역배열/혼조 판단.

        bars: 시간 순 OHLCV 리스트 (최소 20개 권장)
        """
        closes = [b.close for b in bars]
        if len(closes) < 20:
            price = closes[-1] if closes else 0.0
            return EMAResult(price, price, price, price, "혼조", "데이터 부족")

        e5  = cls._ema(closes, 5)
        e10 = cls._ema(closes, 10)
        e20 = cls._ema(closes, 20)
        e50 = cls._ema(closes, 50) if len(closes) >= 50 else closes[-1]

        if e5 > e10 > e20:
            align = "정배열"
            label = "정배열 🟢  (상승 추세)"
        elif e5 < e10 < e20:
            align = "역배열"
            label = "역배열 🔴  (하락 추세)"
        else:
            align = "혼조"
            label = "혼조 🟡  (추세 전환 구간)"

        return EMAResult(ema5=round(e5, 6), ema10=round(e10, 6),
                         ema20=round(e20, 6), ema50=round(e50, 6),
                         align=align, label=label)


