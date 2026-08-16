"""
bottom/engine_core/sl_calculator.py
5m ATR + 신호 등급 + 레버리지 기반 Stop Loss & Trailing Stop 자동 계산.
"""
from __future__ import annotations

_GRADE_MULT: dict[str, float] = {"A": 2.0, "B": 1.6, "C": 1.2, "D": 1.0}
_LIQ_SAFETY  = 0.80   # 이론 청산까지 거리의 80% 이내로 SL 상한 제한
_MMR_APPROX  = 0.004  # 0.4% 유지증거금률 근사값 — Binance USDM 소규모 포지션 기준
_SL_MIN      = 0.3    # SL 최솟값 (%)
_TRAIL_RATIO = 0.5    # trail_raw = 5m ATR × 0.5
_TRAIL_MIN   = 0.5    # trail 최솟값 (%)
_TRAIL_CAP   = 0.6    # trail ≤ sl × 60%


class SLCalculator:
    """5m ATR 기반 Stop Loss / Trailing Stop 자동 계산기.

    atr_pct_5m == 0 이면 (0.0, 0.0) 반환 → 호출부에서 UI 설정값 대체 사용.
    """

    @staticmethod
    def compute(
        atr_pct_5m: float,
        grade:      str,
        leverage:   int,
        mmr:        float = _MMR_APPROX,
    ) -> tuple[float, float]:
        """SL%와 Trail%를 계산해 반환.

        Returns:
            (sl_pct, trail_pct) — 소수점 1자리 반올림.
            atr_pct_5m가 유효하지 않으면 (0.0, 0.0).
        """
        if atr_pct_5m <= 0.0:
            return 0.0, 0.0

        mult = _GRADE_MULT.get(grade, 1.0)

        # ── SL 계산: ATR × 등급배수, 레버리지 안전 상한 적용
        sl_raw   = atr_pct_5m * mult
        liq_safe = max(0.001, (1.0 / max(leverage, 1)) - mmr) * 100.0 * _LIQ_SAFETY
        sl_pct   = max(_SL_MIN, min(sl_raw, liq_safe))

        # ── Trail 계산: ATR × 0.5, SL의 60% 이내
        trail_raw = atr_pct_5m * _TRAIL_RATIO
        trail_pct = max(_TRAIL_MIN, trail_raw)
        trail_pct = min(trail_pct, sl_pct * _TRAIL_CAP)
        trail_pct = max(_TRAIL_MIN, trail_pct)   # cap 결과가 min보다 작을 경우 재보정

        return round(sl_pct, 1), round(trail_pct, 1)

    @staticmethod
    def clamp(
        stop_loss:  float,
        trail_stop: float,
        leverage:   int,
        mmr:        float = _MMR_APPROX,
    ) -> tuple[float, float]:
        """사용자 설정값에 liq_safe 상한을 적용해 (sl_used, trail_used) 반환.

        compute() 와 동일한 clamp → round 순서를 따른다.
        atr/grade 미사용 — leverage·mmr 만으로 상수 계산 가능.
        """
        liq_safe   = max(0.001, (1.0 / max(leverage, 1)) - mmr) * 100.0 * _LIQ_SAFETY
        sl_used    = max(_SL_MIN,   min(stop_loss,  liq_safe))
        trail_used = max(_TRAIL_MIN, min(trail_stop, sl_used * _TRAIL_CAP))
        return round(sl_used, 1), round(trail_used, 1)
