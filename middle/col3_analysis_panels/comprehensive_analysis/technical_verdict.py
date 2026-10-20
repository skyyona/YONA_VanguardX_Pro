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

        # [W-G] BPR 보조 경고 — bpr.py 임계 재사용 (>0.65 Bull / <0.35 Bear)
        # RSI 정상 범위(25~75)일 때만 반영. RSI 경고가 뒤에서 덮어쓰므로 우선순위 낮음.
        if 25 < rsi_1h < 75:
            if bpr < 0.35:   # 매도 압박 강함
                if ema_align == "정배열":
                    suffix = "→ 상승 구조 · 매도 압박 주의"
                    color  = _YELLOW
                elif ema_align == "혼조":
                    suffix = "→ 매도 압박 강함"
                    color  = _NEGATIVE
                # 역배열은 이미 하락 판정 — suffix/color 유지
            elif bpr > 0.65:  # 매수 압박 강함
                if ema_align == "역배열":
                    suffix = "→ 하락 구조 · 매수 압박 주목"
                    color  = _YELLOW
                elif ema_align == "혼조":
                    suffix = "→ 매수 압박 강함"
                    color  = _POSITIVE
                # 정배열은 이미 상승 판정 — suffix/color 유지

        # RSI 과매도·과매수 경고 — 최고 우선순위 (BPR 보조 경고를 덮어씀)
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

