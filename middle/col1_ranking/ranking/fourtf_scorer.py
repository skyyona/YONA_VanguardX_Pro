"""
middle/col1_ranking/ranking/fourtf_scorer.py
4TF Optimization Sort by — 일일 추세 방향 기준 단기 4TF 합의 진입 최적화 스코어링
기준 방향 = 일일 추세(1h·4h·1d 중 같은 방향 2개 이상, middle.analysis.trend 단일 정의) — 중립이면 방향 항목 0점
8개 항목: 단기일치(0~4) + 1m진입근접(0~1) + 일일강도(0~2) + ATR적정(0~1)
        + 거래량순위(0~1) + FR중립(0~1) + OI증가(0~1) + 롱숏균형(0~1)
"""
from __future__ import annotations

from middle.analysis.trend import SHORT_KEYS, daily_trend, short_trend
from middle.widget.shared_context import get_ind


class FourTFScorer:
    """4TF Optimization 모드: 멀티 타임프레임 합의 스코어링."""

    @staticmethod
    def calc_score(sym: str) -> dict:
        ind = get_ind(sym)
        atr = ind.get("atr", 0.0)
        fr  = ind.get("funding_rate", 0.0)
        oi  = ind.get("oi_change", 0.0)
        lr  = ind.get("long_ratio", 50.0)
        vol_rank = ind.get("volume", {}).get("rank", 99)

        # ① 단기일치 — 일일 추세 방향과 같은 단기 TF(1m/3m/5m/15m) 수 (0~4)
        daily = daily_trend(ind)
        base_dir = daily.direction
        dirs = [ind.get(k, {}).get("dir", "↔") for k in SHORT_KEYS]
        s_align = sum(1 for d in dirs if d == base_dir) if base_dir else 0

        # ② 1m 진입 근접 (0~1) — base_dir 방향 기준 과매도/과매수 구간
        k1 = ind.get("tf1", {}).get("k", 50.0)
        if base_dir == "▲":
            s_entry = 1 if k1 < 20 else 0
        elif base_dir == "▼":
            s_entry = 1 if k1 > 80 else 0
        else:
            s_entry = 0

        # ③ 일일강도 — 일일 추세 3TF 모두 같은 방향 2점, 2개 1점, 중립 0점 (0~2)
        s_macro = daily.count - 1 if base_dir else 0

        s_atr    = 1 if 3.0 <= atr <= 8.0 else 0
        s_volume = 1 if vol_rank <= 10 else 0
        s_fr     = 1 if -0.05 <= fr <= 0.05 else 0
        s_oi     = 1 if oi > 0 else 0

        # ④ 롱숏균형 — 추세 방향에 따른 우세 포지션 확인
        if base_dir == "▲":
            s_balance = 1 if lr > 60 else 0
        elif base_dir == "▼":
            s_balance = 1 if lr < 40 else 0
        else:
            s_balance = 0

        return {
            "atr": atr, "k1": k1, "fr": fr, "oi": oi, "lr": lr,
            "vol_rank": vol_rank, "base_dir": base_dir,
            "daily": daily, "short": short_trend(ind),
            "scores": {
                "align": s_align, "entry": s_entry, "macro": s_macro,
                "atr": s_atr, "volume": s_volume, "fr": s_fr,
                "oi": s_oi, "balance": s_balance,
            },
            "total": (s_align + s_entry + s_macro + s_atr + s_volume
                      + s_fr + s_oi + s_balance),
            "max": 12,
        }

    @classmethod
    def get_sorted(cls, data: list, limit: int = 50) -> list:
        """점수≥4 필터 → 상위 N개."""
        scored = [(r, cls.calc_score(r[0])) for r in data]
        scored.sort(key=lambda x: (-x[1]["total"], -x[1]["atr"]))
        result = [r for r, res in scored if res["total"] >= 4]
        if not result:
            result = [r for r, _ in scored[:30]]
        return result[:limit]
