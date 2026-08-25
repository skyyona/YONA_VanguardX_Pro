"""
bottom/prohibition_settings/prohibition_filter.py
절대 거래 금지 11개 항목 필터 — 체크된 항목 조건 위반 시 거래 차단
공통 7개 + 롱 전용 2개 + 숏 전용 2개
"""
from __future__ import annotations

from dataclasses import dataclass
from bottom_engine.models import PositionSide, ProhibitionFlags

_FR_THRESHOLD     = 0.05   # FR 임계값 (%)
_NEW_DAYS_MIN     = 14     # 신규 상장 최소 거래 가능 일수
_LIQ_GAUGE_MAX    = 5.0    # liquidation_proximity.GAUGE_MAX_PCT 동기화 값


@dataclass
class FilterResult:
    blocked: bool
    reason:  str = ""


class ProhibitionFilter:
    """절대 거래 금지 항목 실시간 평가기.

    ind_data: middle module의 get_ind(symbol) 반환 dict
    """

    @classmethod
    def check(
        cls,
        flags:    ProhibitionFlags,
        side:     PositionSide,
        ind_data: dict,
        has_long_open:  bool  = False,
        has_short_open: bool  = False,
        days_listed:    int   = 9999,
        sl_used:        float = 2.5,
    ) -> FilterResult:
        """금지 항목 위반 여부 평가. 첫 번째 위반 항목에서 즉시 반환."""

        fr_pct     = ind_data.get("funding_rate", 0.0)
        player_tags = ind_data.get("_player_tags", [])
        tag_texts  = {t[0] if isinstance(t, (list, tuple)) else t for t in player_tags}

        # ── 공통 조건 ────────────────────────────────────────────
        # common_macro 제거: G7.5(use_macro)와 동일 로직이므로 중복 — use_macro가 단일 게이트

        if flags.common_liq:
            liq_l    = ind_data.get("liq_long_pct",  -99.0)
            liq_s    = ind_data.get("liq_short_pct", +99.0)
            liq_safe = min(sl_used, _LIQ_GAUGE_MAX * 0.95)  # 진입 허용 최소 청산 거리 상한값 (sl_used=3.6% 기준 → 3.6%, 빈도 아님)
            if side == PositionSide.LONG and abs(liq_l) < liq_safe:
                return FilterResult(True, f"롱 청산가 근접도 {abs(liq_l):.2f}% < liq_safe {liq_safe:.2f}% — 롱 진입 금지")
            if side == PositionSide.SHORT and abs(liq_s) < liq_safe:
                return FilterResult(True, f"숏 청산가 근접도 {abs(liq_s):.2f}% < liq_safe {liq_safe:.2f}% — 숏 진입 금지")

        # common_atr 제거: G4(long/short_condition ATR 범위 체크)와 동일 임계값으로 중복 — G4가 단일 게이트

        if flags.common_fr:
            if side == PositionSide.LONG and fr_pct > _FR_THRESHOLD:
                return FilterResult(True, f"FR {fr_pct:+.3f}% 롱 과밀 과열 — 롱 진입 차단")
            if side == PositionSide.SHORT and fr_pct < -_FR_THRESHOLD:
                return FilterResult(True, f"FR {fr_pct:+.3f}% 숏 과밀 음수 — 숏 진입 차단")

        if flags.common_new and days_listed < _NEW_DAYS_MIN:
            return FilterResult(True, f"신규 상장 {days_listed}일 — {_NEW_DAYS_MIN}일 경과 전 거래 금지")

        if flags.common_hunter:
            if any("청산 헌터" in k or "헌터" in k for k in tag_texts):
                return FilterResult(True, "Player Detection '청산 헌터' 감지 — 거래 금지")

        # ── 롱 전용 조건 ─────────────────────────────────────────
        if side == PositionSide.LONG:
            if flags.long_fomo:
                if any("FOMO" in k for k in tag_texts):
                    return FilterResult(True, "Player Detection 'FOMO 극단' 감지 — 롱 진입 금지")
            if flags.long_short_open and has_short_open:
                return FilterResult(True, "숏 포지션 보유 중 동시 롱 진입 금지")

        # ── 숏 전용 조건 ─────────────────────────────────────────
        elif side == PositionSide.SHORT:
            if flags.short_accum:
                if any("세력 매집" in k for k in tag_texts):
                    return FilterResult(True, "Player Detection '세력 매집' 감지 — 숏 진입 금지")
            if flags.short_long_open and has_long_open:
                return FilterResult(True, "롱 포지션 보유 중 동시 숏 진입 금지")

        return FilterResult(False)

