"""
middle/col3_analysis_panels/comprehensive_analysis/recommended_leverage.py
권장 레버리지 계산 — ATR%·에너지·L/S 비율 기반
종합분석 패널 하단 "권장 레버리지" 표시에 사용
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LeverageRecommendation:
    leverage:    int    # 권장 레버리지 (1~20)
    grade:       str    # "안전" | "보통" | "위험"
    color:       str    # 표시 색상
    reason:      str    # 선택 근거 설명


from middle.widget.constants import (
    POSITIVE as _POSITIVE, NEGATIVE as _NEGATIVE,
    ORANGE as _ORANGE, YELLOW as _YELLOW,
)


class RecommendedLeverage:
    """권장 레버리지 계산기.

    공식:
      1. 기준 레버리지: ATR%에 반비례 (변동성 높을수록 낮게)
      2. 에너지 극단 보정: 에너지 편향이 클수록 위험도 증가 → 레버리지 감소
      3. L/S 과쏠림 보정: 극단 쏠림 시 추가 감소
    """

    @staticmethod
    def calculate(
        atr_pct:    float,
        long_pct:   float = 50.0,
        long_ratio: float = 0.5,    # EnergyBalance.long_ratio (0~1)
    ) -> LeverageRecommendation:
        """ATR%·에너지·L/S 기반 권장 레버리지 계산."""

        # ① 기준 레버리지 (ATR 기반)
        if atr_pct <= 0:
            base = 10
        elif atr_pct < 1.0:
            base = 15
        elif atr_pct < 2.0:
            base = 12
        elif atr_pct < 4.0:
            base = 10
        elif atr_pct < 6.0:
            base = 7
        elif atr_pct < 8.0:
            base = 5
        else:
            base = 3

        # ② 에너지 극단 보정 (에너지가 편향될수록 방향성 강함 = 리스크↑)
        energy_bias = abs(long_ratio - 0.5) * 2   # 0~1
        if energy_bias > 0.7:
            base = max(3, base - 3)
        elif energy_bias > 0.4:
            base = max(3, base - 1)

        # ③ L/S 과쏠림 보정
        if long_pct > 80 or long_pct < 20:
            base = max(3, base - 3)
        elif long_pct > 70 or long_pct < 30:
            base = max(3, base - 1)

        leverage = max(1, min(20, base))

        # 등급 분류
        if leverage >= 10:
            grade, color = "적정", _POSITIVE
        elif leverage >= 7:
            grade, color = "주의", _YELLOW
        elif leverage >= 5:
            grade, color = "고위험", _ORANGE
        else:
            grade, color = "매우위험", _NEGATIVE

        reason = (
            f"ATR {atr_pct:.1f}%·"
            f"에너지편향 {int(energy_bias*100)}%·"
            f"롱{long_pct:.0f}%"
        )

        return LeverageRecommendation(
            leverage=leverage,
            grade=grade,
            color=color,
            reason=reason,
        )

