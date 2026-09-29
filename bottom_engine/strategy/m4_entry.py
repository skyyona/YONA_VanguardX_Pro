"""
bottom_engine/strategy/m4_entry.py
M4 진입 판정 — 실거래·백테스트 공용 단일 소스.

평가 순서:
  G0.  방향 편향 (Sort by 모드별 방향 허용 여부)
  G4.  ATR% 범위 필터 (cfg.atr_min ~ cfg.atr_max, ablation >= 6)
  G5.  거래량 배수 필터 (cfg.volume_mult, ablation >= 6)
  G6.  Sort by 품질 등급 필터 (cfg.quality_grade_req, ablation >= 6)
  G_K. tf5 K값 범위 게이트 (cfg.k_long_max / cfg.k_short_min, ablation >= 6)
  G_ema. macro_ema 거시 EMA 방향 게이트 (EMA5 vs EMA50, ablation >= 6)
  G1.  RSI 다이버전스 + 거래량 확인
         불리시 다이버전스: 가격 저점↓ + RSI 저점↑ (롱)
         베어리시 다이버전스: 가격 고점↑ + RSI 고점↓ (숏)
         강도 임계값: 가격 편차 ≥ m4_rsi_price_diff%, RSI 편차 ≥ m4_rsi_rsi_diff
         거래량 확인: 진입봉 vol ≥ 최근 20봉 평균 × m4_rsi_vol_mult
  G2.  M4 15m RSI 50 레벨 방향 확인 (RSI ≥ 50 롱 / ≤ 50 숏)
  G7.5 use_macro 거시 추세 방향 연동 (tf1h/tf4h/tf1d K·D 점수)
  G8.  절대 금지 필터 (ProhibitionFilter 항목)

ind_data 표준 키:
  "rsi_div_bull" : bool    불리시 RSI 다이버전스 발생 여부 (G1, 사전 계산 주입)
  "rsi_div_bear" : bool    베어리시 RSI 다이버전스 발생 여부 (G1, 사전 계산 주입)
  "rsi_div_vol_ok": bool   거래량 확인 결과 (G1, 사전 계산 주입)
  "atr_pct"     : float                      1h 기준 ATR% (G4, data_manager/backtest_runner 주입)
  "volume_ratio": float                      최근봉 vol / 20봉 평균 비율 (G5, 없으면 미체크)
  "tf1"/"tf3"   : {"k": float, "d": float}   1m/3m StochRSI (G6 QualityGrader 용)
  "swing_bull"  : bool                       불리시 스윙 여부 (G6 QualityGrader 용)
  "swing_bear"  : bool                       베어리시 스윙 여부 (G6 QualityGrader 용)
  "tf5"         : {"k": float, "d": float}   5m StochRSI (G_K K값 범위 게이트)
  "e5"          : float                      1h EMA5 (G_ema, macro_ema=True 시 주입)
  "e50"         : float                      1h EMA50 (G_ema, macro_ema=True 시 주입)
  "tf15"       : {"k": float, "d": float}   15m StochRSI (UI 표시용)
  "tf15_rsi"   : float                      15m RSI (G2 방향 확인, 사전 계산 주입)
  "tf1h"/"tf4h"/"tf1d": {"k", "d"}         HTF K/D (use_macro=True 시 G7.5)
  "funding_rate": float                     FR% (common_fr 판정, 없으면 0.0)
  "liq_long_pct": float                     롱 청산 거리% 음수 (없으면 -99.0)
  "liq_short_pct": float                    숏 청산 거리% 양수 (없으면 +99.0)
  "_player_tags": list                      Player Detection 태그 (없으면 [])
  "_days_listed": int                       상장일수 (days_listed 인자 대체 가능)

실거래: trading_engine.py가 5m 봉 조회 후 detect_rsi_divergence()로 계산하여 주입
백테스트: backtest_runner.py가 사전 계산 후 ind_bt에 주입
"""
from __future__ import annotations

from bottom_engine.models import PositionSide, StrategyParams
from bottom_engine.strategy_settings.realtrade_strategy_sort_by import get_mode_config
from bottom_engine.prohibition_settings.prohibition_filter import ProhibitionFilter
from bottom_engine.engine_core.sl_calculator import SLCalculator
from bottom_engine.engine_core.quality_grader import QualityGrader

_GRADE_ORDER: dict[str, int] = {"A": 0, "B": 1, "C": 2, "D": 3}


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
        entry_variant:     str  = "M4",
    ) -> tuple[bool, str]:
        """M4 진입 가능 여부 판단.

        side: "long" | "short"
        ablation: 게이트 누적 단계 (1~6). 실거래·기본=6(전체).
          1=RSI다이버전스  2=+거래량확인  3=+15m추세  4·5=3과동일  6=+G7.5+G8
        반환: (ok: bool, reason: str)
        """
        cfg     = get_mode_config(params.sort_mode)
        is_long = (side == "long")

        # ── ENERGY 진입 분기 ──────────────────────────────────────
        if entry_variant == "ENERGY":
            # G0: 방향 편향
            if is_long and cfg.direction_bias == "short_only":
                return False, f"[{params.sort_mode}] 숏 전용 모드 — 롱 진입 불가"
            if not is_long and cfg.direction_bias == "long_only":
                return False, f"[{params.sort_mode}] 롱 전용 모드 — 숏 진입 불가"
            # G4: ATR% 범위 필터
            _atr_p = float(ind_data.get("atr_pct", 0.0))
            if _atr_p > 0:
                _sl_a, _ = SLCalculator.clamp(
                    params.stop_loss, params.trail_stop, params.leverage, mmr=params.mmr)
                _atr_min_e = max(cfg.atr_min, _sl_a / 2.0)
                if not (_atr_min_e <= _atr_p <= cfg.atr_max):
                    return False, f"G4: ATR {_atr_p:.2f}% 범위 외 ({_atr_min_e:.2f}~{cfg.atr_max:.2f}%)"
            # G8: 절대 금지 필터
            _sl_e, _ = SLCalculator.clamp(
                params.stop_loss, params.trail_stop, params.leverage, mmr=params.mmr)
            _pos_e  = PositionSide.LONG if is_long else PositionSide.SHORT
            _hl_e   = False if is_long else has_opposite_open
            _hs_e   = has_opposite_open if is_long else False
            _res_e  = ProhibitionFilter.check(
                params.prohibition, _pos_e, ind_data,
                has_long_open=_hl_e, has_short_open=_hs_e,
                days_listed=days_listed, sl_used=_sl_e,
            )
            if _res_e.blocked:
                return False, _res_e.reason
            # ENERGY: BPR 에너지 소멸 허가
            if is_long and not ind_data.get("bear_exhausted", False):
                return False, "ENERGY: 약세 에너지 소멸 미확인"
            if not is_long and not ind_data.get("bull_exhausted", False):
                return False, "ENERGY: 강세 에너지 소멸 미확인"
            # ENERGY: 1m Stoch RSI 트리거
            if is_long and not ind_data.get("k_trigger_long", False):
                return False, "ENERGY: 1m K 상향 돌파 트리거 미발생"
            if not is_long and not ind_data.get("k_trigger_short", False):
                return False, "ENERGY: 1m K 하향 돌파 트리거 미발생"
            direction_e = "롱" if is_long else "숏"
            return True, f"ENERGY {direction_e} 진입 조건 충족 (BPR 에너지 소멸 + 1m K 트리거)"

        # ── STOCH_ONLY 진입 분기 (BPR 게이트 없음 — N3 대조군 전용) ─────
        if entry_variant == "STOCH_ONLY":
            # G0: 방향 편향
            if is_long and cfg.direction_bias == "short_only":
                return False, f"[{params.sort_mode}] 숏 전용 모드 — 롱 진입 불가"
            if not is_long and cfg.direction_bias == "long_only":
                return False, f"[{params.sort_mode}] 롱 전용 모드 — 숏 진입 불가"
            # G4: ATR% 범위 필터
            _atr_s = float(ind_data.get("atr_pct", 0.0))
            if _atr_s > 0:
                _sl_s, _ = SLCalculator.clamp(
                    params.stop_loss, params.trail_stop, params.leverage, mmr=params.mmr)
                _atr_min_s = max(cfg.atr_min, _sl_s / 2.0)
                if not (_atr_min_s <= _atr_s <= cfg.atr_max):
                    return False, f"G4: ATR {_atr_s:.2f}% 범위 외 ({_atr_min_s:.2f}~{cfg.atr_max:.2f}%)"
            # G8: 절대 금지 필터
            _sl_s2, _ = SLCalculator.clamp(
                params.stop_loss, params.trail_stop, params.leverage, mmr=params.mmr)
            _pos_s  = PositionSide.LONG if is_long else PositionSide.SHORT
            _hl_s   = False if is_long else has_opposite_open
            _hs_s   = has_opposite_open if is_long else False
            _res_s  = ProhibitionFilter.check(
                params.prohibition, _pos_s, ind_data,
                has_long_open=_hl_s, has_short_open=_hs_s,
                days_listed=days_listed, sl_used=_sl_s2,
            )
            if _res_s.blocked:
                return False, _res_s.reason
            # 1m Stoch RSI 트리거만 (BPR 게이트 없음)
            if is_long and not ind_data.get("k_trigger_long", False):
                return False, "STOCH_ONLY: 1m K 상향 돌파 트리거 미발생"
            if not is_long and not ind_data.get("k_trigger_short", False):
                return False, "STOCH_ONLY: 1m K 하향 돌파 트리거 미발생"
            direction_s = "롱" if is_long else "숏"
            return True, f"STOCH_ONLY {direction_s} 진입 조건 충족 (1m K 트리거)"

        # ── G0: 방향 편향 (항상 적용) ──────────────────────────
        if is_long and cfg.direction_bias == "short_only":
            return False, f"[{params.sort_mode}] 숏 전용 모드 — 롱 진입 불가"
        if not is_long and cfg.direction_bias == "long_only":
            return False, f"[{params.sort_mode}] 롱 전용 모드 — 숏 진입 불가"

        # ── G4: ATR% 범위 필터 (ablation >= 6) ────────────────────
        if ablation >= 6:
            _atr_p = float(ind_data.get("atr_pct", 0.0))
            if _atr_p > 0:
                _sl_atr, _ = SLCalculator.clamp(
                    params.stop_loss, params.trail_stop, params.leverage, mmr=params.mmr)
                _atr_min_eff = max(cfg.atr_min, _sl_atr / 2.0)
                if not (_atr_min_eff <= _atr_p <= cfg.atr_max):
                    return False, f"G4: ATR {_atr_p:.2f}% 범위 외 ({_atr_min_eff:.2f}~{cfg.atr_max:.2f}%)"

        # ── G5: 거래량 배수 필터 (ablation >= 6) ──────────────────
        if ablation >= 6 and cfg.volume_mult is not None:
            _vr = float(ind_data.get("volume_ratio", 1.0))
            if _vr < cfg.volume_mult:
                return False, f"G5: 거래량 부족 (ratio {_vr:.2f} < {cfg.volume_mult:.1f})"

        # ── G6: quality_grade_req 등급 필터 (ablation >= 6) ──────
        if ablation >= 6 and cfg.quality_grade_req is not None:
            _grade, _ = QualityGrader.grade(ind_data, side)
            if _GRADE_ORDER.get(_grade, 3) > _GRADE_ORDER.get(cfg.quality_grade_req, 3):
                return False, f"G6: 품질 등급 미달 ({_grade} < {cfg.quality_grade_req}+)"

        # ── G_K: tf5 K값 범위 게이트 (ablation >= 6) ────────────
        if ablation >= 6:
            _k5 = float(ind_data.get("tf5", {}).get("k", 50.0))
            if is_long and _k5 > cfg.k_long_max:
                return False, f"G_K: tf5 K={_k5:.1f} > {cfg.k_long_max:.0f} — 과매수 진입 차단"
            if not is_long and _k5 < cfg.k_short_min:
                return False, f"G_K: tf5 K={_k5:.1f} < {cfg.k_short_min:.0f} — 과매도 진입 차단"

        # ── G_ema: macro_ema 거시 EMA 방향 게이트 (ablation >= 6) ─
        if ablation >= 6 and cfg.macro_ema:
            _e5  = float(ind_data.get("e5",  0.0))
            _e50 = float(ind_data.get("e50", 0.0))
            if _e5 > 0 and _e50 > 0:
                if is_long and _e5 <= _e50:
                    return False, f"G_ema: EMA5({_e5:.4f}) ≤ EMA50({_e50:.4f}) — 상승추세 미확인"
                if not is_long and _e5 >= _e50:
                    return False, f"G_ema: EMA5({_e5:.4f}) ≥ EMA50({_e50:.4f}) — 하락추세 미확인"

        # ── G1: RSI 다이버전스 + 거래량 확인 ──────────────────────
        if is_long:
            if not ind_data.get("rsi_div_bull", False):
                return False, "G1: RSI 불리시 다이버전스 미발생"
        else:
            if not ind_data.get("rsi_div_bear", False):
                return False, "G1: RSI 베어리시 다이버전스 미발생"

        if ablation >= 2 and not ind_data.get("rsi_div_vol_ok", False):
            return False, "G1: 거래량 미확인 (진입봉 vol < 평균 × m4_rsi_vol_mult)"

        # ── G2: 15m RSI 50 레벨 방향 확인 (ablation >= 3) ─────
        tf15  = ind_data.get("tf15", {})
        k15   = float(tf15.get("k", 50.0))
        d15   = float(tf15.get("d", 50.0))
        rsi15 = float(ind_data.get("tf15_rsi", 50.0))
        if ablation >= 3:
            if "tf15_rsi" not in ind_data:
                return False, "G2: 15m RSI 데이터 없음 — 진입 보류"
            if is_long and rsi15 < 50.0:
                return False, f"G2: 15m RSI {rsi15:.1f} < 50 — 롱 방향 미확인"
            if not is_long and rsi15 > 50.0:
                return False, f"G2: 15m RSI {rsi15:.1f} > 50 — 숏 방향 미확인"

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
            f"(RSI다이버전스, 15m RSI={rsi15:.1f} K={k15:.1f} D={d15:.1f})"
        )
