"""
middle/col1_ranking_blacklist/ranking/fourtf_scorer.py
4TF Optimization Sort by — 4개 타임프레임 합의 기반 진입 최적화 스코어링
8개 항목: 4TF정렬(0~4) + 1m진입근접(0~1) + 거시지지(0~3) + ATR적정(0~1)
        + 거래량순위(0~1) + FR중립(0~1) + OI증가(0~1) + 롱숏균형(0~1)
"""
from __future__ import annotations

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

        # ① 4TF 정렬 수 — 1h 기준 방향 대비 4TF(1m/3m/5m/15m) 일치 개수 (0~4)
        #   base_dir을 tf1h로 설정해 4TF 내부 순환 논리 제거
        tf1h_d = ind.get("tf1h", {}).get("dir", "↔")
        base_dir = tf1h_d if tf1h_d in ("▲", "▼") else None
        dirs = [ind.get(k, {}).get("dir", "↔") for k in ("tf1", "tf3", "tf5", "tf15")]
        s_align = sum(1 for d in dirs if d == base_dir) if base_dir else 0

        # ② 1m 진입 근접 (0~1) — base_dir 방향 기준 과매도/과매수 구간
        k1 = ind.get("tf1", {}).get("k", 50.0)
        if base_dir == "▲":
            s_entry = 1 if k1 < 20 else 0
        elif base_dir == "▼":
            s_entry = 1 if k1 > 80 else 0
        else:
            s_entry = 0

        # ③ 거시 지지 수 — tf1h/tf4h/tf1d 중 base_dir 일치 개수 (0~3)
        if base_dir:
            macro = [ind.get(k, {}) for k in ("tf1h", "tf4h", "tf1d")]
            s_macro = sum(1 for t in macro if t.get("dir", "↔") == base_dir)
        else:
            s_macro = 0

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
            "scores": {
                "align": s_align, "entry": s_entry, "macro": s_macro,
                "atr": s_atr, "volume": s_volume, "fr": s_fr,
                "oi": s_oi, "balance": s_balance,
            },
            "total": (s_align + s_entry + s_macro + s_atr + s_volume
                      + s_fr + s_oi + s_balance),
            "max": 13,
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
