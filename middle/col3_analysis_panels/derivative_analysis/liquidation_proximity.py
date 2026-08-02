"""
middle/col3_analysis_panels/derivative_analysis/liquidation_proximity.py
청산 근접도 분석 — 파생분석 패널 표시용
_refresh_deriv() 섹션 ④ 청산 근접도 시각화에 필요한 분석값 제공

공개 API 제약사항:
  Binance 강제청산 주문 조회(/fapi/v1/forceOrders)는 API 키 필요.
  → 공개 OHLCV Low/High + 펀딩비 기반 추정 방식으로 대체 구현.

추정 방식:
  - ATR% = 평균 실제 변동 폭
  - FR 방향 → 롱/숏 중 어느 쪽이 더 청산 압박 받는지 결정
  - 추정 청산 거리 = ATR% × 가중치 (FR 방향·강도에 따라 조정)
  - 최소 ±0.5%, 최대 ±5.0% 범위 내로 클램핑
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LiquidationProximity:
    liq_long_pct:  float   # 롱 청산 추정 거리 % (음수, 현재가 아래)
    liq_short_pct: float   # 숏 청산 추정 거리 % (양수, 현재가 위)


class LiquidationProximityPanel:
    """청산 근접도 분석 — 파생분석 패널 청산 근접 섹션.

    실제 강제청산 주문 데이터 대신 ATR%·FR 기반 추정값 사용.
    """

    # 시각화 최대 거리 (이 값 이상은 게이지 가득 참)
    GAUGE_MAX_PCT = 5.0
    # 추정 거리 기본 배수 (ATR 대비 몇 배가 청산 구간인지)
    BASE_MULTIPLIER  = 2.0
    # FR 방향에 따른 추가 위험 보정 (FR이 롱 비용이면 롱이 더 위험)
    FR_BIAS_FACTOR   = 0.3

    @classmethod
    def estimate(
        cls,
        atr_pct:   float,       # AtrPercent.calculate() 결과
        fr_pct:    float = 0.0, # 펀딩비 % (FundingRateAnalysis.rate_pct)
        long_pct:  float = 50.0, # 롱 계좌 비율 %
    ) -> LiquidationProximity:
        """ATR%·FR·L/S비율 기반 청산 근접도 추정.

        Args:
            atr_pct:  ATR% (1h 14봉 기준 권장)
            fr_pct:   펀딩비 % (FR이 양수=롱 비용, 음수=숏 비용)
            long_pct: 롱 계좌 비율 % (과쏠림 측이 더 위험)
        """
        base = max(atr_pct * cls.BASE_MULTIPLIER, 1.0)

        # FR 방향에 따른 편향 보정
        # FR > 0: 롱이 비용 지불 → 롱 청산 더 가까이 (liq_long_dist 감소)
        # FR < 0: 숏이 비용 지불 → 숏 청산 더 가까이 (liq_short_dist 감소)
        fr_bias = abs(fr_pct) * cls.FR_BIAS_FACTOR

        # 과쏠림 측 추가 압박 (많이 쏠릴수록 청산 더 가까이)
        long_excess  = max(0.0, (long_pct - 50.0) / 50.0)   # 0~1
        short_excess = max(0.0, (50.0 - long_pct) / 50.0)   # 0~1

        # 롱 청산 거리 (아래 방향, 음수)
        # FR 양수·롱 과쏠림 → 거리 감소 (청산 더 가까이)
        liq_long_dist = base - (fr_bias if fr_pct > 0 else 0) - long_excess * base * 0.5
        liq_long_dist = max(0.5, min(cls.GAUGE_MAX_PCT, liq_long_dist))

        # 숏 청산 거리 (위 방향, 양수)
        # FR 음수·숏 과쏠림 → 거리 감소 (청산 더 가까이)
        liq_short_dist = base - (fr_bias if fr_pct < 0 else 0) - short_excess * base * 0.5
        liq_short_dist = max(0.5, min(cls.GAUGE_MAX_PCT, liq_short_dist))

        return LiquidationProximity(
            liq_long_pct  = round(-liq_long_dist, 2),   # 음수
            liq_short_pct = round(+liq_short_dist, 2),  # 양수
        )

