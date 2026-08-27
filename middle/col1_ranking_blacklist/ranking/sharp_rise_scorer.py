"""
middle/col1_ranking_blacklist/ranking/sharp_rise_scorer.py
Sharp rise Sort by — 급등 직전 숏 쏠림 심볼 스코어링
자격 조건: 숏쏠림(sr) ≥ 50%
6개 항목: 숏쏠림(0~4) + FR(0~3) + 숏청산근접(0~3) + OI(0~2) + Player태그(0~2) + VSS(0~2)
"""
from __future__ import annotations

from middle.widget.shared_context import get_ind, _live_ranking

_RISE_KEYWORDS = ("고래 매수", "세력 매집", "기관 유입", "FR-")


class SharpRiseScorer:
    """Sharp rise 모드: 숏 쏠림 기반 급등 후보 스코어링."""

    @staticmethod
    def _get_player_tags(sym: str, tag_map: dict | None = None) -> list:
        if tag_map is not None:
            return tag_map.get(sym, [])
        for data in _live_ranking():
            if data[0] == sym:
                return data[11]
        return []

    @classmethod
    def calc_score(cls, sym: str, tag_map: dict | None = None) -> dict:
        ind   = get_ind(sym)
        lr    = ind.get("long_ratio", 50.0)
        fr    = ind.get("funding_rate", 0.0)
        liq_s = abs(ind.get("liq_short_pct", 2.0))
        oi    = abs(ind.get("oi_change", 0.0))
        vss   = ind.get("vss", 1.0)
        sr    = 100.0 - lr

        s_sr  = 4 if sr >= 80 else 3 if sr >= 70 else 2 if sr >= 60 else 1 if sr >= 50 else 0
        s_fr  = 3 if fr < -0.05 else 2 if fr < -0.03 else 1 if fr < -0.01 else 0
        s_liq = 3 if liq_s < 1.5 else 2 if liq_s < 2.0 else 1 if liq_s < 3.0 else 0  # 숏 청산 임계: 1.5% (Sharp decline 1.0%보다 완화 — 숏 스퀴즈 예비 구간 포함)
        s_oi  = 2 if oi > 15 else 1 if oi > 5 else 0

        tags = cls._get_player_tags(sym, tag_map)
        has_rise_tag = any(any(kw in t[0] for kw in _RISE_KEYWORDS) for t in tags)
        s_player = 2 if has_rise_tag else 0

        s_vss = 2 if vss > 1.5 else 1 if vss > 1.2 else 0

        return {
            "qualified": (fr < -0.01) or (sr >= 40.0),
            "sr": sr, "fr": fr, "liq_s": liq_s, "oi": oi, "vss": vss,
            "has_rise_tag": has_rise_tag,
            "scores": {"sr": s_sr, "fr": s_fr, "liq": s_liq, "oi": s_oi,
                       "player": s_player, "vss": s_vss},
            "total": s_sr + s_fr + s_liq + s_oi + s_player + s_vss,
            "max": 16,
        }

    @classmethod
    def get_sorted(cls, data: list, limit: int = 20) -> list:
        """숏쏠림≥50% 자격 + 점수≥4 필터 → 상위 N개."""
        tag_map = {d[0]: d[11] for d in _live_ranking()}
        scored = [(r, cls.calc_score(r[0], tag_map)) for r in data]
        scored.sort(key=lambda x: (999, -x[1]["vss"]) if not x[1]["qualified"]
                    else (-x[1]["total"], -x[1]["vss"]))
        result = [r for r, res in scored if res["qualified"] and res["total"] >= 4]
        if not result:
            result = [r for r, res in scored if res["qualified"]]
        return result[:limit]
