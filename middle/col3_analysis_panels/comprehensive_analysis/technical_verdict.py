"""
middle/col3_analysis_panels/comprehensive_analysis/technical_verdict.py
기술분석 종합 판단 — 종합분석 패널 "기술" 요약 라인
_refresh_verdict() 기술 요약 라인 로직 대응
"""
from __future__ import annotations

from dataclasses import dataclass

from middle.widget.constants import (
    POSITIVE as _POSITIVE, NEGATIVE as _NEGATIVE, YELLOW as _YELLOW,
)


@dataclass
class TechnicalVerdict:
    prefix:  str   # "기술 "
    summary: str   # "RSI 62·BPR 71%·EMA 정배열"
    suffix:  str   # "→ 상승 구조"
    color:   str   # 판정 색상


class TechnicalVerdictPanel:
    """기술분석 종합 판단 생성기."""

    @staticmethod
    def analyze(
        rsi_1h:      float,
        bpr:         float,
        ema_align:   str,    # "정배열" | "역배열" | "혼조"
    ) -> TechnicalVerdict:
        """RSI·BPR·EMA 조합 → 종합분석 기술 요약 라인."""
        summary = f"RSI {rsi_1h:.0f}·BPR {int(bpr * 100)}%·EMA {ema_align}"

        if ema_align == "정배열":
            suffix = "→ 상승 구조"
            color  = _POSITIVE
        elif ema_align == "역배열":
            suffix = "→ 하락 구조"
            color  = _NEGATIVE
        else:
            suffix = "→ 방향 미결정"
            color  = _YELLOW

        # RSI 과매도·과매수 추가 경고
        if rsi_1h >= 75 and ema_align != "역배열":
            suffix = "→ 과매수 주의 (RSI 고점)"
            color  = _YELLOW
        elif rsi_1h <= 25 and ema_align != "정배열":
            if ema_align == "역배열":
                suffix = "→ 단기 반등 가능 (하락 추세 주의)"
                color  = _YELLOW
            else:
                suffix = "→ 과매도 반등 가능"
                color  = _POSITIVE

        return TechnicalVerdict(prefix="기술 ", summary=summary, suffix=suffix, color=color)

