"""
middle/col3_analysis_panels/derivative_analysis/open_interest.py
미결제약정(OI) 분석·등급화 — 파생분석 패널 표시용
_refresh_deriv() 섹션 ② OI 표시에 필요한 분석값 제공
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OpenInterestAnalysis:
    change_pct:   float   # OI 변화율 %
    direction:    str     # "유입↑" | "이탈↓" | "보합"
    color_hint:   str     # "increasing" | "decreasing" | "stable"
    grade:        str     # 인간 친화적 등급 설명
    score_4tf:    int     # 4TF Optimization OI 증가 점수 (0~1)


class OpenInterestPanel:
    """OI 변화 분석 — 파생분석 패널 OI 섹션."""

    GAUGE_MAX = 30.0   # 게이지 최대 범위 (±%)

    @classmethod
    def analyze(cls, oi_change_pct: float) -> OpenInterestAnalysis:
        """OI 변화율 → OpenInterestAnalysis 변환."""
        # 방향·색상
        if oi_change_pct > 5:
            direction  = "유입↑"
            color_hint = "increasing"
        elif oi_change_pct < -5:
            direction  = "이탈↓"
            color_hint = "decreasing"
        else:
            direction  = "보합"
            color_hint = "stable"

        # 등급 (방향 인식)
        abs_oi = abs(oi_change_pct)
        if oi_change_pct > 0:
            if abs_oi >= 20:   grade = "급등 🔴  (포지션 급증 — 추세 가속 가능)"
            elif abs_oi >= 10: grade = "증가 🟠  (관심 유입 중)"
            elif abs_oi >= 5:  grade = "미증 🟡  (소폭 변화)"
            else:              grade = "보합 ⚪  (포지션 변화 미미)"
        else:
            if abs_oi >= 20:   grade = "급락 🔴  (포지션 급감 — 청산 가속 가능)"
            elif abs_oi >= 10: grade = "감소 🟠  (포지션 이탈 중)"
            elif abs_oi >= 5:  grade = "소감 🟡  (소폭 감소)"
            else:              grade = "보합 ⚪  (포지션 변화 미미)"

        # Sort by 점수
        score_4tf = 1 if oi_change_pct > 0 else 0

        return OpenInterestAnalysis(
            change_pct=round(oi_change_pct, 2),
            direction=direction,
            color_hint=color_hint,
            grade=grade,
            score_4tf=score_4tf,
        )

