"""
middle/col3_analysis_panels/comprehensive_analysis/newlisted_lifecycle.py
Newly Listed 생애주기 분석 — 신규 상장 심볼 전용 블록
_nl_lifecycle() + verdict 패널의 생애주기 섹션 로직 대응
"""
from __future__ import annotations

from dataclasses import dataclass

from middle.widget.constants import (
    POSITIVE as _POSITIVE, NEGATIVE as _NEGATIVE, ORANGE as _ORANGE,
    YELLOW as _YELLOW, ACCENT_BLUE as _ACCENT_BLUE, DIM_TEXT as _DIM,
    LIGHT_GREEN as _LGR,
)
_LIGHT_GREEN = _LGR


@dataclass
class LifecycleResult:
    stage:    str   # "pre_pump" | "pre_pump_late" | "pump_active" | "top_formed" | "distribution" | "stable" | "unknown"
    label:    str   # "🔥 펌프 미발생" 등
    color:    str
    strategy: str   # 매매 전략 가이드
    days:     int   # 상장 후 경과일


class NewlistedLifecycle:
    """Newly Listed 생애주기 감지기.

    공개 API 기반 추정:
      - days: onboardDate 기반 경과일
      - vss: 거래량 급등 여부 (펌프 신호)
      - oi_change: OI 모멘텀 (자금 유입 여부)
      - price_change_pct: 상장 대비 가격 변화 (mockup의 list_pct 대체)
      - is_high_from_open: ATH 형성 추정 (가격이 많이 올랐는지)
    """

    @classmethod
    def analyze(
        cls,
        days:             int,
        vss:              float = 1.0,
        oi_change_pct:    float = 0.0,
        price_change_pct: float = 0.0,   # 24h 변화율 (list_pct 근사)
        high_24h_pct:     float = 0.0,   # 24h 고점 vs 현재가 차이 % (ATH 형성 여부 근사)
    ) -> LifecycleResult | None:
        """신규 상장 생애주기 단계 감지. days <= 0 이면 None 반환."""
        if days <= 0:
            return None

        # ① 펌프 진행 중: 거래량 급등 + OI 급증 + 상장 초기
        if days <= 14 and (vss >= 1.8 or oi_change_pct > 8):
            if price_change_pct > 15:
                return LifecycleResult(
                    stage="pump_active",
                    label="🚀 펌프 진행 중",
                    color=_YELLOW,
                    strategy="신규 추격 금지 — 고점 형성 대기",
                    days=days,
                )
            else:
                return LifecycleResult(
                    stage="pre_pump_late",
                    label="⚡ 지연 펌프 대기",
                    color=_ACCENT_BLUE,
                    strategy="VSS+OI 유지 확인 — 발화 시 즉각 대응",
                    days=days,
                )

        # ② 펌프 미발생: 초기 구간 + 거래량 풍부 + 아직 상승 없음
        if days <= 7 and abs(price_change_pct) < 20 and vss >= 0.6:
            return LifecycleResult(
                stage="pre_pump",
                label="🔥 펌프 미발생",
                color=_ACCENT_BLUE,
                strategy="VSS+OI 동시 급증 시 진입 고려",
                days=days,
            )

        # ③ 고점 형성 의심: 가격 급등 후 하락 전환
        if price_change_pct > 30 and high_24h_pct > 10:
            return LifecycleResult(
                stage="top_formed",
                label="⚠ 고점 형성 의심",
                color=_ORANGE,
                strategy="신규 롱 금지 — 반등 확인 후 접근",
                days=days,
            )

        # ④ 디스트리뷰션: 가격 하락 + OI 감소
        if price_change_pct < -15 and oi_change_pct < -5:
            return LifecycleResult(
                stage="distribution",
                label="📉 디스트리뷰션",
                color=_NEGATIVE,
                strategy="반등 시 숏 기회 — 거래량 감시",
                days=days,
            )

        # ⑤ 안정화: 90일 이상 + 거래량 정상화
        if days >= 90 and 0.6 <= vss <= 1.4:
            return LifecycleResult(
                stage="stable",
                label="✅ 안정화 진입",
                color=_LIGHT_GREEN,
                strategy="일반 코인 분석 기준 적용 가능",
                days=days,
            )

        # ⑥ 관망
        return LifecycleResult(
            stage="unknown",
            label="관망 중",
            color=_DIM,
            strategy="추가 신호 대기",
            days=days,
        )

