"""
middle/col1_ranking/ranking/newlisted_scorer.py
Newly Listed Sort by — 신규 상장 심볼 활동성 선정
자격 조건: 최소 VSS≥1.2 또는 OI변화≥3% (활동성 있는 신규 상장만)
4개 항목 + 연령 가중치:
  Volume Surge(0~4) + OI Momentum(0~3) + Price Velocity(0~3) + Funding Extreme(0~2)
  × 연령 가중치 (7일↓=2.0, 14일↓=1.6, 30일↓=1.3)
  get_sorted()의 30일 필터로 60일↓/90일↓/이상 구간은 도달 불가 → 제거

상장 경과일(행 r[1])은 data_manager가 exchangeInfo onboardDate로 계산해 전달
"""
from __future__ import annotations

from middle.widget.shared_context import get_ind


class NewlistedScorer:
    """Newly Listed 모드: 신규 상장 심볼 활동성 스코어링."""

    # ── 점수 계산 (panel_col1.py에서 사용) ──────────────────────
    @staticmethod
    def calc_score(sym: str, row: list | None = None) -> dict:
        days = row[1] if row else 0
        ind  = get_ind(sym)
        vss  = ind.get("vss", 1.0)
        oi   = abs(ind.get("oi_change", 0.0))
        fr   = abs(ind.get("funding_rate", 0.0))
        chg  = abs(float(row[4].replace("%", "").replace("+", ""))) if row else 0.0

        # 자격 조건: 최소 거래량 또는 OI 활동 필요
        qualified = not (vss < 1.2 and oi < 3.0)

        # ① Volume Surge (0~4)
        if   vss >= 4.0: s_surge = 4
        elif vss >= 3.0: s_surge = 3
        elif vss >= 2.0: s_surge = 2
        elif vss >= 1.5: s_surge = 1
        else:            s_surge = 0
        # ② OI Momentum (0~3)
        if   oi >= 20: s_oi = 3
        elif oi >= 10: s_oi = 2
        elif oi >=  5: s_oi = 1
        else:          s_oi = 0
        # ③ Price Velocity (0~3)
        if   chg >= 20: s_vel = 3
        elif chg >= 10: s_vel = 2
        elif chg >=  5: s_vel = 1
        else:           s_vel = 0
        # ④ Funding Extreme (0~2)
        if   fr >= 0.10: s_fr = 2
        elif fr >= 0.05: s_fr = 1
        else:            s_fr = 0

        # 연령 가중치 — get_sorted() 30일 필터로 실제 도달 가능 구간만 유지
        if   days <=  7: age_w = 2.0
        elif days <= 14: age_w = 1.6
        else:            age_w = 1.3  # days 15~30

        total = s_surge + s_oi + s_vel + s_fr
        return {
            "days": days, "vss": vss, "oi": oi, "fr": fr, "chg": chg,
            "qualified": qualified, "age_weight": age_w,
            "scores": {"surge": s_surge, "oi": s_oi, "velocity": s_vel, "funding": s_fr},
            "total": total, "weighted": total * age_w, "max": 12,
        }

    @classmethod
    def get_sorted(cls, data: list, limit: int = 30) -> list:
        """30일 이내 신규 상장만, 가중 점수 내림차순 정렬 → 상위 N개."""
        data = [r for r in data if 0 < r[1] <= 30]   # 30일 이내만

        def _newlist_key(r):
            res = cls.calc_score(r[0], r)
            if not res["qualified"]:
                return (999.0, res["days"])
            return (-res["weighted"], res["days"])

        data.sort(key=_newlist_key)
        return data[:limit]
