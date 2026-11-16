"""
middle/col1_ranking/ranking/newlisted_scorer.py
Newly Listed Sort by — 신규 상장 심볼 활동성 선정
자격 조건: 최소 VSS≥1.2 또는 1시간 OI 증가≥3% (활동성 있는 신규 상장만) + 봉 지표 실제 값(bars_ready)
4개 항목 + 연령 가중치:
  Volume Surge(0~4) + OI Momentum(0~3) + Price Velocity(0~3) + Funding Extreme(0~2)
  × 연령 가중치 (7일↓=2.0, 14일↓=1.6, 30일↓=1.3)
  get_sorted()의 30일 필터로 60일↓/90일↓/이상 구간은 도달 불가 → 제거
2026-11-16 수정: 갱신 대상 밖 기본값·옛 값 채점 금지(N1·N2, bars_ready — 롱숏 비율 미사용이라 ind_ready 아님),
  자격 미달 행 목록 제외(N3), 상장 24시간 미만 포함(N4), OI = 1시간 OI(부호 유지, N5),
  롱 방향만 가점(사용자 결정 ② — 엔진 Newly Listed 모드 롱 전용): 가격 속도 = 24h 상승분만, OI = 증가분만

상장 경과일(행 r[1])은 data_manager가 exchangeInfo onboardDate로 계산해 전달
"""
from __future__ import annotations

from middle.widget.shared_context import bars_ready, get_ind


class NewlistedScorer:
    """Newly Listed 모드: 신규 상장 심볼 활동성 스코어링."""

    # ── 점수 계산 (panel_col1.py에서 사용) ──────────────────────
    @staticmethod
    def calc_score(sym: str, row: list | None = None) -> dict:
        days = row[1] if row else 0
        ind  = get_ind(sym)
        ready = bars_ready(sym)                     # False → 자격 미달 (갱신 대상 밖 기본값·옛 값으로 채점하지 않음)
        vss  = ind.get("vss", 1.0)
        oi   = ind.get("oi_change_1h", 0.0)         # 1시간 OI 변화 % (부호 유지 — 증가만 가점)
        fr   = abs(ind.get("funding_rate", 0.0))
        chg  = float(row[4].replace("%", "").replace("+", "")) if row else 0.0   # 24h 변동 % (부호 유지 — 상승만 가점)

        # 자격 조건: 봉 지표 실제 값 + 최소 거래량 또는 OI 유입
        qualified = ready and not (vss < 1.2 and oi < 3.0)

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
            "qualified": qualified, "ready": ready, "age_weight": age_w,
            "scores": {"surge": s_surge, "oi": s_oi, "velocity": s_vel, "funding": s_fr},
            "total": total, "weighted": total * age_w, "max": 12,
        }

    @classmethod
    def get_sorted(cls, data: list, limit: int = 30) -> list:
        """30일 이내(24시간 미만 포함) 신규 상장 중 자격 충족만, 가중 점수 내림차순 → 상위 N개 (없으면 빈 목록).
        자격 미달 행은 제외 (N3 — 기존: 뒤로 보내기만 해 목록 대부분이 '⚠ 자격 미달'로 채워짐)."""
        scored = [(r, cls.calc_score(r[0], r)) for r in data if 0 <= r[1] <= 30]
        scored = [(r, res) for r, res in scored if res["qualified"]]
        scored.sort(key=lambda x: (-x[1]["weighted"], x[1]["days"]))
        return [r for r, _ in scored[:limit]]
