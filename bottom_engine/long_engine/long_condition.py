"""
bottom/long_engine/long_condition.py
롱 진입 조건 평가 — M4 전략 (5m 에너지 + 15m 추세)

평가 순서:
  G0.  방향 편향 (Sort by 모드별 롱 허용 여부)
  G1.  M4 5m GC 감지 (K crosses above D) + K기울기 ≥ SLOPE_TH
  G2.  M4 15m 추세 합의 (K > D, spread ≥ 2)
  G7.5 use_macro 거시 추세 방향 연동 (tf1h/tf4h/tf1d K·D 점수)
  G8.  절대 금지 필터 (ProhibitionFilter 11개 항목)
"""
from __future__ import annotations

from bottom_engine.models import PositionSide, StrategyParams
from bottom_engine.strategy_settings.realtrade_strategy_sort_by import get_mode_config
from bottom_engine.prohibition_settings.prohibition_filter import ProhibitionFilter
from bottom_engine.engine_core.sl_calculator import SLCalculator


class LongCondition:
    """롱 진입 조건 평가기 — M4 전략 (5m 에너지 + 15m 추세)."""

    _prev_k5m: float | None = None  # 직전 5m K 값 — GC 크로스 감지용

    @classmethod
    def evaluate(
        cls,
        ind_data:       dict,
        params:         StrategyParams,
        has_short_open: bool = False,
        days_listed:    int  = 9999,
    ) -> tuple[bool, str]:
        """롱 진입 가능 여부 판단.

        반환: (ok: bool, reason: str)
        """
        cfg = get_mode_config(params.sort_mode)

        # ── G0: 방향 편향 ──────────────────────────────────────
        if cfg.direction_bias == "short_only":
            return False, f"[{params.sort_mode}] 숏 전용 모드 — 롱 진입 불가"

        # ── G1: M4 5m GC 감지 + K기울기 ───────────────────────
        tf5  = ind_data.get("tf5", {})
        k5   = float(tf5.get("k", 50.0))
        d5   = float(tf5.get("d", 50.0))
        pk5  = cls._prev_k5m
        cls._prev_k5m = k5
        gc = (pk5 is not None and pk5 < d5 and k5 > d5)
        if not gc:
            return False, f"G1: 5m GC 미발생 (K={k5:.1f} D={d5:.1f} prevK={pk5})"
        if (k5 - d5) < params.m4_slope_th:
            return False, (
                f"G1: 5m 기울기 부족 (K-D={k5 - d5:.1f} < SLOPE_TH={params.m4_slope_th})"
            )
        if k5 >= cfg.k_long_max:
            return False, (
                f"G1: K 과매수 필터 (K={k5:.1f} >= k_long_max={cfg.k_long_max})"
            )

        # ── G2: M4 15m 추세 합의 ───────────────────────────────
        tf15 = ind_data.get("tf15", {})
        k15  = float(tf15.get("k", 50.0))
        d15  = float(tf15.get("d", 50.0))
        if not (k15 > d15 and (k15 - d15) >= 2.0):
            return False, (
                f"G2: 15m 롱 추세 미합의 (K={k15:.1f} D={d15:.1f} spread={k15 - d15:.1f})"
            )

        # ── G7.5: use_macro 거시 추세 방향 연동 ────────────────
        if params.use_macro:
            _mac_score = 0
            for _tf in ("tf1h", "tf4h", "tf1d"):
                _td = ind_data.get(_tf, {})
                _k, _d = _td.get("k", 50.0), _td.get("d", 50.0)
                if   _k > _d and abs(_k - _d) >= 2.0: _mac_score += 1
                elif _k < _d and abs(_k - _d) >= 2.0: _mac_score -= 1
            if _mac_score <= -1:
                return False, f"거시 추세 하락 ({_mac_score:+d}/3) — 롱 진입 보류"

        # ── G8: 절대 금지 필터 ─────────────────────────────────
        _sl_used, _ = SLCalculator.clamp(
            params.stop_loss, params.trail_stop, params.leverage, mmr=params.mmr)
        result = ProhibitionFilter.check(
            params.prohibition, PositionSide.LONG, ind_data,
            has_short_open=has_short_open, days_listed=days_listed,
            sl_used=_sl_used,
        )
        if result.blocked:
            return False, result.reason

        return True, (
            f"M4 롱 진입 조건 충족 "
            f"(5m K={k5:.1f} D={d5:.1f}, 15m K={k15:.1f} D={d15:.1f})"
        )
