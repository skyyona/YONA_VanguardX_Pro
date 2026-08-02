"""
middle/col3_analysis_panels/derivative_analysis/funding_rate.py
펀딩비(FR) 분석·등급화 — 파생분석 패널 표시용
_refresh_deriv() 섹션 ① FR 표시에 필요한 분석값 제공
"""
from __future__ import annotations

from dataclasses import dataclass
from middle.models import FundingRateData


@dataclass
class FundingRateAnalysis:
    rate_pct:       float   # FR in %, e.g. +0.013
    direction:      str     # "롱 비용" | "숏 비용" | "중립"
    color_hint:     str     # "long_cost" | "short_cost" | "neutral"
    daily_cost_pct: float   # 하루 FR 비용 (= |rate_pct| × 3교 × leverage)
    grade:          str     # 인간 친화적 등급 설명
    score_4tf:      int     # 4TF Optimization FR 중립 점수 (0~1)


class FundingRatePanel:
    """펀딩비 분석 — 파생분석 패널 FR 섹션."""

    # 시각화 게이지 최대 범위 (±%)
    GAUGE_MAX = 0.15

    @classmethod
    def analyze(
        cls,
        funding:       FundingRateData | None,
        rec_leverage:  int = 10,
    ) -> FundingRateAnalysis:
        """FundingRateData → FundingRateAnalysis 변환."""
        rate_raw = funding.funding_rate if funding else 0.0
        rate_pct = rate_raw * 100.0          # raw 0.0001 → 0.01%

        # 방향·색상
        if rate_pct > 0.05:
            direction  = "롱 비용"
            color_hint = "long_cost"
        elif rate_pct < -0.05:
            direction  = "숏 비용"
            color_hint = "short_cost"
        else:
            direction  = "중립"
            color_hint = "neutral"

        # 하루 비용 (= |rate| × 3회 × 레버리지)
        daily = abs(rate_pct) * 3 * rec_leverage

        # 등급
        abs_r = abs(rate_pct)
        if abs_r >= 0.10:
            grade = "과열 ⚠️  (포지션 비용 급증)"
        elif abs_r >= 0.05:
            grade = "압박 🟠  (방향성 과쏠림)"
        elif abs_r >= 0.02:
            grade = "주의 🟡  (미세 쏠림)"
        else:
            grade = "안정 🟢  (균형 상태)"

        # Sort by 점수
        score_4tf = 1 if -0.05 <= rate_pct <= 0.05 else 0

        return FundingRateAnalysis(
            rate_pct=round(rate_pct, 4),
            direction=direction,
            color_hint=color_hint,
            daily_cost_pct=round(daily, 4),
            grade=grade,
            score_4tf=score_4tf,
        )

    @classmethod
    def from_rate(cls, rate_pct: float, rec_leverage: int = 10) -> FundingRateAnalysis:
        """rate_pct(%) float 직접 입력 — panel_col3 인라인 대체용.

        analyze()는 FundingRateData.funding_rate(raw)만 참조하므로
        symbol/funding_time은 더미값으로 전달.
        """
        return cls.analyze(
            FundingRateData(symbol="", funding_rate=rate_pct / 100.0, funding_time=0),
            rec_leverage,
        )


