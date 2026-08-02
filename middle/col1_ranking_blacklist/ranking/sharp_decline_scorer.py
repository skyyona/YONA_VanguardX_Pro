"""
middle/col1_ranking_blacklist/ranking/sharp_decline_scorer.py
Sharp decline Sort by — 급락 직전 롱 쏠림 심볼 스코어링
자격 조건: 롱쏠림(lr) ≥ 50%
6개 항목: 롱쏠림(0~4) + FR(0~3) + 롱청산근접(0~3) + OI(0~2) + Player태그(0~2) + VSS(0~2)
"""
from __future__ import annotations

from middle.widget.shared_context import get_ind, _live_ranking

_DECLINE_KEYWORDS = ("FR+", "FOMO", "롱 스퀴즈", "청산 헌터", "헌터", "세력 분산")


class SharpDeclineScorer:
    """Sharp decline 모드: 롱 쏠림 기반 급락 후보 스코어링."""

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
        liq_l = abs(ind.get("liq_long_pct", -2.0))
        oi    = abs(ind.get("oi_change", 0.0))
        vss   = ind.get("vss", 1.0)

        s_lr  = 4 if lr >= 80 else 3 if lr >= 70 else 2 if lr >= 60 else 1 if lr >= 50 else 0
        s_fr  = 3 if fr > 0.08 else 2 if fr > 0.05 else 1 if fr > 0.03 else 0
        s_liq = 3 if liq_l < 1.0 else 2 if liq_l < 2.0 else 1 if liq_l < 3.0 else 0  # 롱 청산 임계: 1.0% (Sharp rise 1.5%보다 엄격 — 롱 청산이 하락 가속도 크므로 의도적 비대칭)
        s_oi  = 2 if oi > 15 else 1 if oi > 5 else 0

        tags = cls._get_player_tags(sym, tag_map)
        has_decline_tag = any(any(kw in t[0] for kw in _DECLINE_KEYWORDS) for t in tags)
        s_player = 2 if has_decline_tag else 0

        s_vss = 2 if vss > 1.5 else 1 if vss > 1.2 else 0

        return {
            "qualified": lr >= 50.0,
            "lr": lr, "fr": fr, "liq_l": liq_l, "oi": oi, "vss": vss,
            "has_decline_tag": has_decline_tag,
            "scores": {"lr": s_lr, "fr": s_fr, "liq": s_liq, "oi": s_oi,
                       "player": s_player, "vss": s_vss},
            "total": s_lr + s_fr + s_liq + s_oi + s_player + s_vss,
            "max": 16,
        }

    @classmethod
    def get_sorted(cls, data: list, limit: int = 30) -> list:
        """롱쏠림≥50% 자격 + 점수≥4 필터 → 상위 N개."""
        tag_map = {d[0]: d[11] for d in _live_ranking()}
        scored = [(r, cls.calc_score(r[0], tag_map)) for r in data]
        scored.sort(key=lambda x: (999, -x[1]["vss"]) if not x[1]["qualified"]
                    else (-x[1]["total"], -x[1]["vss"]))
        result = [r for r, res in scored if res["qualified"] and res["total"] >= 4]
        if not result:
            result = [r for r, res in scored if res["qualified"]]
        return result[:limit]
