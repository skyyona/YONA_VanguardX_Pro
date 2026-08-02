"""
bottom/prohibition_settings/prohibition_filter.py
절대 거래 금지 11개 항목 필터 — 체크된 항목 조건 위반 시 거래 차단
공통 7개 + 롱 전용 2개 + 숏 전용 2개
"""
from __future__ import annotations

from dataclasses import dataclass
from bottom.models import PositionSide, ProhibitionFlags

_ATR_DANGER   = 8.0    # ATR% 과변동 임계값 (%)
_FR_THRESHOLD = 0.05   # FR 임계값 (%)
_NEW_DAYS_MIN = 14     # 신규 상장 최소 거래 가능 일수


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
        has_long_open:  bool = False,
        has_short_open: bool = False,
        days_listed:    int  = 9999,
    ) -> FilterResult:
        """금지 항목 위반 여부 평가. 첫 번째 위반 항목에서 즉시 반환."""

        atr_pct    = ind_data.get("atr_pct", 0.0)
        fr_pct     = ind_data.get("funding_rate", 0.0)
        player_tags = ind_data.get("_player_tags", [])
        tag_keys   = {t[0] if isinstance(t, (list, tuple)) else t for t in player_tags}

        # ── 공통 조건 ────────────────────────────────────────────
        if flags.common_macro:
            macro_score = 0
            for key in ("tf1h", "tf4h", "tf1d"):
                td = ind_data.get(key, {})
                k, d = td.get("k", 50.0), td.get("d", 50.0)
                if k > d and abs(k - d) >= 2.0:
                    macro_score += 1
                elif k < d and abs(k - d) >= 2.0:
                    macro_score -= 1
            if side == PositionSide.LONG and macro_score <= -1:
                return FilterResult(True, f"거시 추세 하락 ({macro_score:+d}/3) — 롱 진입 금지")
            elif side == PositionSide.SHORT and macro_score >= 1:
                return FilterResult(True, f"거시 추세 상승 ({macro_score:+d}/3) — 숏 진입 금지")

        # common_4tf: G1(long_condition/short_condition)에서 처리
        #   → flags.common_4tf=True 시 완전 4TF 합의 필수, False 시 3/4 과반 완화

        if flags.common_liq:
            liq_l = ind_data.get("liq_long_pct",  -99.0)
            liq_s = ind_data.get("liq_short_pct", +99.0)
            if side == PositionSide.LONG and abs(liq_l) < 1.5:
                return FilterResult(True, f"롱 청산가 근접도 {abs(liq_l):.2f}% — 롱 진입 금지")
            if side == PositionSide.SHORT and abs(liq_s) < 1.5:
                return FilterResult(True, f"숏 청산가 근접도 {abs(liq_s):.2f}% — 숏 진입 금지")

        if flags.common_atr and atr_pct > _ATR_DANGER:
            return FilterResult(True, f"ATR% {atr_pct:.1f}% 과변동 구간 — 거래 금지")

        if flags.common_fr:
            if side == PositionSide.LONG and fr_pct > _FR_THRESHOLD:
                return FilterResult(True, f"FR {fr_pct:+.3f}% 롱 과밀 과열 — 롱 진입 차단")
            if side == PositionSide.SHORT and fr_pct < -_FR_THRESHOLD:
                return FilterResult(True, f"FR {fr_pct:+.3f}% 숏 과밀 음수 — 숏 진입 차단")

        if flags.common_new and days_listed < _NEW_DAYS_MIN:
            return FilterResult(True, f"신규 상장 {days_listed}일 — {_NEW_DAYS_MIN}일 경과 전 거래 금지")

        if flags.common_hunter:
            if any("청산 헌터" in k or "헌터" in k for k in tag_keys):
                return FilterResult(True, "Player Detection '청산 헌터' 감지 — 거래 금지")

        # ── 롱 전용 조건 ─────────────────────────────────────────
        if side == PositionSide.LONG:
            if flags.long_fomo:
                if any("FOMO" in k for k in tag_keys):
                    return FilterResult(True, "Player Detection 'FOMO 극단' 감지 — 롱 진입 금지")
            if flags.long_short_open and has_short_open:
                return FilterResult(True, "숏 포지션 보유 중 동시 롱 진입 금지")

        # ── 숏 전용 조건 ─────────────────────────────────────────
        elif side == PositionSide.SHORT:
            if flags.short_accum:
                if any("세력 매집" in k for k in tag_keys):
                    return FilterResult(True, "Player Detection '세력 매집' 감지 — 숏 진입 금지")
            if flags.short_long_open and has_long_open:
                return FilterResult(True, "롱 포지션 보유 중 동시 숏 진입 금지")

        return FilterResult(False)

