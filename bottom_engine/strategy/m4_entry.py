"""
bottom_engine/strategy/m4_entry.py
M4 진입 판정 — 실거래·백테스트 공용 단일 소스.

평가 순서:
  G0.  방향 편향 (Sort by 모드별 방향 허용 여부)
  G1.  M4 5m GC/DC 감지 + K기울기 ≥ SLOPE_TH + 극값 필터 + EMA50 이격도
  G2.  M4 15m 추세 합의 (spread ≥ 2)
  G7.5 use_macro 거시 추세 방향 연동 (tf1h/tf4h/tf1d K·D 점수)
  G8.  절대 금지 필터 (ProhibitionFilter 11개 항목)

ind_data 표준 키:
  "tf5"        : {"k": float, "d": float}   5m StochRSI (G1)
  "tf15"       : {"k": float, "d": float}   15m StochRSI (G2)
  "_prev_k5m"  : float | None               직전 5m 봉 K — GC/DC 감지용
  "base"       : float                      현재가격 (EMA50 이격도용, G1)
  "e50"        : float                      1h EMA50 (이격도용, G1)
  "tf1h"/"tf4h"/"tf1d": {"k", "d"}         HTF K/D (use_macro=True 시 G7.5)
  "funding_rate": float                     FR% (common_fr 판정, 없으면 0.0)
  "liq_long_pct": float                     롱 청산 거리% 음수 (없으면 -99.0)
  "liq_short_pct": float                    숏 청산 거리% 양수 (없으면 +99.0)
  "_player_tags": list                      Player Detection 태그 (없으면 [])
  "_days_listed": int                       상장일수 (days_listed 인자 대체 가능)

실거래: trading_engine.py가 _prev_k5m을 봉 경계마다 갱신하여 ind_data에 주입
백테스트: backtest_runner.py가 _k5m_prev_bar를 "_prev_k5m"으로 전달
"""
from __future__ import annotations

from bottom_engine.models import PositionSide, StrategyParams
from bottom_engine.strategy_settings.realtrade_strategy_sort_by import get_mode_config
from bottom_engine.prohibition_settings.prohibition_filter import ProhibitionFilter
from bottom_engine.engine_core.sl_calculator import SLCalculator


class M4Entry:
    """M4 진입 판정 — 실거래·백테스트 공용 단일 소스."""

    @staticmethod
    def evaluate(
        side:              str,
        ind_data:          dict,
        params:            StrategyParams,
        has_opposite_open: bool = False,
        days_listed:       int  = 9999,
        ablation:          int  = 6,
    ) -> tuple[bool, str]:
        """M4 진입 가능 여부 판단.

        side: "long" | "short"
        ablation: 게이트 누적 단계 (1~6). 실거래·기본=6(전체).
          1=GC/DC  2=+slope  3=+15m추세  4=+이격도  5=+극값필터  6=+G7.5+G8
        반환: (ok: bool, reason: str)
        """
        cfg     = get_mode_config(params.sort_mode)
        is_long = (side == "long")

        # ── G0: 방향 편향 (항상 적용) ──────────────────────────
        if is_long and cfg.direction_bias == "short_only":
            return False, f"[{params.sort_mode}] 숏 전용 모드 — 롱 진입 불가"
        if not is_long and cfg.direction_bias == "long_only":
            return False, f"[{params.sort_mode}] 롱 전용 모드 — 숏 진입 불가"

        # ── G1: M4 5m GC/DC 감지 + K기울기 + 극값 + 이격도 ────
        tf5 = ind_data.get("tf5", {})
        k5  = float(tf5.get("k", 50.0))
        d5  = float(tf5.get("d", 50.0))
        pk5 = ind_data.get("_prev_k5m")  # float | None

        if is_long:
            cross = (pk5 is not None and pk5 < d5 and k5 > d5)
            if not cross:
                return False, f"G1: 5m GC 미발생 (K={k5:.1f} D={d5:.1f} prevK={pk5})"
            if ablation >= 2 and (k5 - d5) < params.m4_slope_th:
                return False, (
                    f"G1: 5m 기울기 부족 (K-D={k5 - d5:.1f} < SLOPE_TH={params.m4_slope_th})"
                )
            if ablation >= 5 and k5 >= cfg.k_long_max:
                return False, f"G1: K 과매수 필터 (K={k5:.1f} >= k_long_max={cfg.k_long_max})"
        else:
            cross = (pk5 is not None and pk5 > d5 and k5 < d5)
            if not cross:
                return False, f"G1: 5m DC 미발생 (K={k5:.1f} D={d5:.1f} prevK={pk5})"
            if ablation >= 2 and (d5 - k5) < params.m4_slope_th:
                return False, (
                    f"G1: 5m 기울기 부족 (D-K={d5 - k5:.1f} < SLOPE_TH={params.m4_slope_th})"
                )
            if ablation >= 5 and k5 <= cfg.k_short_min:
                return False, f"G1: K 과매도 필터 (K={k5:.1f} <= k_short_min={cfg.k_short_min})"

        if ablation >= 4 and params.m4_div_th is not None:
            _price = float(ind_data.get("base", 0.0))
            _e50   = float(ind_data.get("e50",  0.0))
            if _price > 0.0 and _e50 > 0.0:
                _div_pct = abs(_price - _e50) / _e50 * 100.0
                if _div_pct > params.m4_div_th:
                    return False, (
                        f"G1: 1h EMA50 이격도 과도 ({_div_pct:.1f}% > DIV_TH={params.m4_div_th})"
                    )

        # ── G2: M4 15m 추세 합의 (ablation >= 3) ──────────────
        tf15 = ind_data.get("tf15", {})
        k15  = float(tf15.get("k", 50.0))
        d15  = float(tf15.get("d", 50.0))
        if ablation >= 3:
            if is_long:
                if not (k15 > d15 and (k15 - d15) >= 2.0):
                    return False, (
                        f"G2: 15m 롱 추세 미합의 (K={k15:.1f} D={d15:.1f} spread={k15 - d15:.1f})"
                    )
            else:
                if not (k15 < d15 and (d15 - k15) >= 2.0):
                    return False, (
                        f"G2: 15m 숏 추세 미합의 (K={k15:.1f} D={d15:.1f} spread={d15 - k15:.1f})"
                    )

        # ── G7.5: use_macro 거시 추세 방향 연동 (ablation >= 6) ─
        if ablation >= 6 and params.use_macro:
            _mac_score = 0
            for _tf in ("tf1h", "tf4h", "tf1d"):
                _td = ind_data.get(_tf, {})
                _k  = float(_td.get("k", 50.0))
                _d  = float(_td.get("d", 50.0))
                if   _k > _d and abs(_k - _d) >= 2.0: _mac_score += 1
                elif _k < _d and abs(_k - _d) >= 2.0: _mac_score -= 1
            if is_long and _mac_score <= -1:
                return False, f"거시 추세 하락 ({_mac_score:+d}/3) — 롱 진입 보류"
            if not is_long and _mac_score >= 1:
                return False, f"거시 추세 상승 ({_mac_score:+d}/3) — 숏 진입 보류"

        # ── G8: 절대 금지 필터 (ablation >= 6, ProhibitionFilter 11개) ─
        if ablation >= 6:
            _sl_used, _ = SLCalculator.clamp(
                params.stop_loss, params.trail_stop, params.leverage, mmr=params.mmr)
            _pos_side  = PositionSide.LONG if is_long else PositionSide.SHORT
            _has_long  = False if is_long else has_opposite_open
            _has_short = has_opposite_open if is_long else False
            result = ProhibitionFilter.check(
                params.prohibition, _pos_side, ind_data,
                has_long_open=_has_long, has_short_open=_has_short,
                days_listed=days_listed, sl_used=_sl_used,
            )
            if result.blocked:
                return False, result.reason

        direction = "롱" if is_long else "숏"
        return True, (
            f"M4 {direction} 진입 조건 충족 "
            f"(5m K={k5:.1f} D={d5:.1f}, 15m K={k15:.1f} D={d15:.1f})"
        )
