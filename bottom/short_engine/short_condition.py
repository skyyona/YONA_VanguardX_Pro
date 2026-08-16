"""
bottom/short_engine/short_condition.py
숏 진입 조건 평가 — 7축 교차 검증 + Sort by 모드 분기

평가 순서:
  G0. 방향 편향 (Sort by 모드별 숏 허용 여부)
  G1. 4TF 완전 합의 (1m/3m/5m/15m K<D, spread≥2)
  G2. K 임계값 (Sort by 모드별 과매수 구간 확인)
  G3. 품질 등급 (Cascade/Divergence/Zone/지속성 100점 → A/B/C/D)
  G4. ATR% 범위 (너무 정적 or 과변동 구간 필터)
  G5. 거래량 배수 (1m 현재봉 / 20봉 평균)
  G6. EMA 거시 추세 (EMA5 < EMA50 — 하락 방향 확인)
  G7. 스윙 구조 (15m 하락 고저점 구조 확인)
  G7.5. use_macro 거시 추세 방향 연동 (tf1h/tf4h/tf1d K·D 점수)
  G8. 절대 금지 필터 (ProhibitionFilter 11개 항목)
"""
from __future__ import annotations

from bottom.models import PositionSide, StrategyParams
from bottom.engine_core.fourtf_consensus import FourTFConsensus
from bottom.engine_core.sort_mode_config import get_mode_config
from bottom.engine_core.quality_grader import QualityGrader
from bottom.prohibition_settings.prohibition_filter import ProhibitionFilter
from bottom.engine_core.sl_calculator import SLCalculator

_GRADE_ORDER = {"A": 4, "B": 3, "C": 2, "D": 1}


class ShortCondition:
    """숏 진입 조건 평가기 — Sort by 모드별 7축 교차 검증."""

    @classmethod
    def evaluate(
        cls,
        ind_data:      dict,
        params:        StrategyParams,
        has_long_open: bool = False,
        days_listed:   int  = 9999,
    ) -> tuple[bool, str]:
        """숏 진입 가능 여부 판단.

        반환: (ok: bool, reason: str)
        """
        cfg = get_mode_config(params.sort_mode)

        # ── G0: 방향 편향 ──────────────────────────────────────
        if cfg.direction_bias == "long_only":
            return False, f"[{params.sort_mode}] 롱 전용 모드 — 숏 진입 불가"

        # ── G1: 4TF 합의 ──────────────────────────────────────
        signal = FourTFConsensus.evaluate(ind_data)
        if params.consensus_mode == "4/4":
            if not signal.short_consensus:
                return False, f"4TF 숏 완전 미합의 ({signal.aligned_short}/4 TF)"
        else:
            if signal.aligned_short < 3:
                return False, f"4TF 숏 최소 미합의 ({signal.aligned_short}/4 TF)"

        # ── G2: Sort by 모드별 K 임계값 ────────────────────────
        k_std = float(ind_data.get("tf5", {}).get("k", 50.0))
        if k_std <= cfg.k_short_min:
            return False, (
                f"K={k_std:.1f} — {params.sort_mode} 숏 하한 K>{cfg.k_short_min} 미달"
            )

        # ── G3: 품질 등급 ──────────────────────────────────────
        if cfg.quality_grade_req is not None:
            grade, score = QualityGrader.grade(ind_data, "short")
            if _GRADE_ORDER.get(grade, 1) < _GRADE_ORDER.get(cfg.quality_grade_req, 1):
                return False, (
                    f"품질 등급 {grade}({score}점) "
                    f"— {params.sort_mode} 최소 {cfg.quality_grade_req}등급 필요"
                )

        # ── G4: ATR% 범위 ──────────────────────────────────────
        atr_pct = float(ind_data.get("atr_pct", 0.0))
        if atr_pct < cfg.atr_min:
            return False, (
                f"ATR%={atr_pct:.2f} — {params.sort_mode} 최소 변동성 {cfg.atr_min}% 미달"
            )
        if atr_pct > cfg.atr_max:
            return False, (
                f"ATR%={atr_pct:.2f} — {params.sort_mode} 과변동 {cfg.atr_max}% 초과"
            )

        # ── G5: 거래량 배수 ────────────────────────────────────
        if cfg.volume_mult is not None:
            vol_ratio = float(ind_data.get("volume_ratio", 1.0))
            if vol_ratio < cfg.volume_mult:
                return False, (
                    f"거래량 배수={vol_ratio:.2f}x "
                    f"— {params.sort_mode} 최소 {cfg.volume_mult}x 미달"
                )

        # ── G6: EMA 거시 추세 (EMA5 < EMA50) ──────────────────
        if cfg.macro_ema:
            e5  = float(ind_data.get("e5",  0.0))
            e50 = float(ind_data.get("e50", 0.0))
            if e50 > 0 and e5 >= e50:
                return False, (
                    f"EMA5({e5:.4f}) ≥ EMA50({e50:.4f}) "
                    f"— 거시 상승 추세, {params.sort_mode} 숏 보류"
                )

        # ── G7: 스윙 구조 ──────────────────────────────────────
        if cfg.requires_swing:
            if not ind_data.get("swing_bear", False):
                return False, (
                    f"15m 하락 스윙 구조 미형성 — {params.sort_mode} 숏 보류"
                )

        # ── G7.5: use_macro 거시 추세 방향 연동 ────────────────
        if params.use_macro:
            _mac_score = 0
            for _tf in ("tf1h", "tf4h", "tf1d"):
                _td = ind_data.get(_tf, {})
                _k, _d = _td.get("k", 50.0), _td.get("d", 50.0)
                if   _k > _d and abs(_k - _d) >= 2.0: _mac_score += 1
                elif _k < _d and abs(_k - _d) >= 2.0: _mac_score -= 1
            if _mac_score >= 1:
                return False, f"거시 추세 상승 ({_mac_score:+d}/3) — 숏 진입 보류"

        # ── G8: 절대 금지 필터 ─────────────────────────────────
        _sl_used, _ = SLCalculator.clamp(
            params.stop_loss, params.trail_stop, params.leverage, mmr=params.mmr)
        result = ProhibitionFilter.check(
            params.prohibition, PositionSide.SHORT, ind_data,
            has_long_open=has_long_open, days_listed=days_listed,
            sl_used=_sl_used,
        )
        if result.blocked:
            return False, result.reason

        return True, f"{params.consensus_mode} 합의 [{params.sort_mode}] — 숏 진입 조건 충족"
