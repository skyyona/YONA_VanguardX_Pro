"""
middle/col3_analysis_panels/derivative_analysis/longshort_ratio.py
롱숏 비율 분석 — 파생분석 패널 표시용
_refresh_deriv() 섹션 ③ 롱/숏 비율 표시에 필요한 분석값 제공
Sharp rise/decline 스코어러의 자격 조건과도 연동
"""
from __future__ import annotations

from dataclasses import dataclass
from middle.models import LongShortData


@dataclass
class LongShortAnalysis:
    long_pct:         float   # 롱 계좌 비율 %
    short_pct:        float   # 숏 계좌 비율 %
    long_short_ratio: float   # 롱/숏 비율 (long/short)
    bias:             str     # "롱 과쏠림" | "숏 과쏠림" | "균형"
    color_hint:       str     # "long_heavy" | "short_heavy" | "balanced"
    grade:            str     # 인간 친화적 등급 설명
    squeeze_risk:     str     # "Sharp Rise 후보  (숏 스퀴즈↑)" | "Sharp Decline 후보  (롱 스퀴즈↑)" | "—"
    score_4tf:        int     # 4TF Optimization 롱숏균형 점수 (0~1)
    warning:          str     # ⚠️ 경고 문구 (과쏠림 시)


class LongShortPanel:
    """롱숏 비율 분석 — 파생분석 패널 L/S 섹션."""

    @classmethod
    def from_pct(cls, long_pct: float) -> LongShortAnalysis:
        """long_pct(%) float 직접 입력 — panel_col3 인라인 대체용.

        analyze()는 long_account_pct/short_account_pct/long_short_ratio만
        참조하므로 symbol/timestamp는 더미값으로 전달.
        """
        short_pct = round(100.0 - long_pct, 2)
        ratio     = long_pct / short_pct if short_pct > 0 else 1.0
        return cls.analyze(
            LongShortData(
                symbol="",
                long_account_pct=long_pct,
                short_account_pct=short_pct,
                long_short_ratio=ratio,
                timestamp=0,
            )
        )

    @classmethod
    def analyze(cls, long_short: LongShortData | None) -> LongShortAnalysis:
        """LongShortData → LongShortAnalysis 변환."""
        if long_short is None:
            return LongShortAnalysis(50.0, 50.0, 1.0,
                                     "균형", "balanced", "데이터 없음", "—", 1, "")

        long_pct  = long_short.long_account_pct
        short_pct = long_short.short_account_pct
        ratio     = long_short.long_short_ratio

        # 방향·색상
        if long_pct >= 70:
            bias       = "롱 과쏠림"
            color_hint = "long_heavy"
        elif short_pct >= 70:
            bias       = "숏 과쏠림"
            color_hint = "short_heavy"
        elif long_pct >= 55:
            bias       = "롱 우세"
            color_hint = "long_heavy"
        elif short_pct >= 55:
            bias       = "숏 우세"
            color_hint = "short_heavy"
        else:
            bias       = "균형"
            color_hint = "balanced"

        # 등급
        if long_pct >= 80:
            grade = f"롱 극단 🔴  (롱 스퀴즈 위험 ↑)"
        elif long_pct >= 70:
            grade = f"롱 과쏠림 🟠  (Sharp Decline 자격)"
        elif short_pct >= 80:
            grade = f"숏 극단 🔴  (숏 스퀴즈 위험 ↑)"
        elif short_pct >= 70:
            grade = f"숏 과쏠림 🟠  (Sharp Rise 자격)"
        elif 30 <= long_pct <= 70:
            grade = f"균형 🟢  (4TF Optim 적합)"
        else:
            grade = f"불균형 🟡  (주의)"

        # 스퀴즈 위험 방향
        if short_pct >= 50:
            squeeze_risk = "Sharp Rise 후보  (숏 스퀴즈↑)"
        elif long_pct >= 50:
            squeeze_risk = "Sharp Decline 후보  (롱 스퀴즈↑)"
        else:
            squeeze_risk = "—"

        # 4TF 균형 점수
        score_4tf = 1 if 30.0 <= long_pct <= 70.0 else 0

        # 경고
        warning = ""
        if long_pct >= 80:
            warning = "⚠️  롱 극단 — 롱 청산 압박 주의"
        elif short_pct >= 80:
            warning = "⚠️  숏 극단 — 숏 청산 압박 주의"

        return LongShortAnalysis(
            long_pct=round(long_pct, 2),
            short_pct=round(short_pct, 2),
            long_short_ratio=round(ratio, 4),
            bias=bias,
            color_hint=color_hint,
            grade=grade,
            squeeze_risk=squeeze_risk,
            score_4tf=score_4tf,
            warning=warning,
        )

