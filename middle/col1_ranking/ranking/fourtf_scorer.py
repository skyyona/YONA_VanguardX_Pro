"""
middle/col1_ranking/ranking/fourtf_scorer.py
4TF Optimization Sort by — 일일 추세 방향 기준 단기 4TF 합의 진입 최적화 스코어링
기준 방향 = 일일 추세(1h·4h·1d 중 같은 방향 2개 이상, middle.analysis.trend 단일 정의) — 중립이면 방향 항목 0점
6개 항목(10점 만점): 단기일치(0~4) + 1m진입근접(0~1) + 일일강도(0~2) + 거래량Top10(0~1)
        + OI 1h 증가(0~1) + 추세쏠림(0~1)
설계 변경 (2026-11-16, 30일 이력 검증 — f_github/fourtf_design_eval_20261116.log):
  - FR중립 제거: 표본 96.7%가 1점(변별력 없음)·점수 그룹 성과 우위 없음
  - ATR적정(3~8%) 제거·ATR 동점 정렬 제거: 3~8%·엔진 범위 1.85~6.0% 모두 성과 차이 없음 (엔진 범위는 3열 표시만)
  - OI: 10분 OI > 0(동전 던지기, 4h −0.07%p) → 1시간 OI > +3% (4h +1.37%p·적중 58.5%, Sharp와 같은 기준)
  - 롱숏균형 → 추세쏠림(이름만): 규칙(상승 롱>60 / 하락 롱<40)은 1h +0.08%p로 유지, 실제 뜻은 추세 방향 쏠림
채점 대상: 지금 갱신되는 종목의 실제 지표(ind_ready) — 그 밖(거래량 101~200위 옛 값·기본값·조회 실패 기본값)은
  총점 0·ready False (2026-11-16 T1·T7 — Gold 1위 4TF 점수도 같은 값 사용)
"""
from __future__ import annotations

from middle.analysis.trend import SHORT_KEYS, daily_trend, short_trend
from middle.widget.shared_context import get_ind, get_vol_rank, ind_ready


class FourTFScorer:
    """4TF Optimization 모드: 멀티 타임프레임 합의 스코어링."""

    @staticmethod
    def calc_score(sym: str) -> dict:
        ind = get_ind(sym)
        ready = ind_ready(sym)
        atr = ind.get("atr", 0.0)                 # 표시용 (점수 항목 아님)
        oi  = ind.get("oi_change_1h", 0.0)        # 1시간 OI 변화 % (부호 유지)
        lr  = ind.get("long_ratio", 50.0)
        vol_rank = get_vol_rank(sym)   # 현재 순위 — ind["volume"]["rank"]는 캐시 생성 시 고정 (T3)

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

        s_volume = 1 if vol_rank <= 10 else 0
        s_oi     = 1 if oi > 3.0 else 0          # 1시간 OI +3% 초과 (새 포지션 유입)

        # ④ 추세쏠림 — 추세 방향 쪽 계좌 쏠림 (상승 롱>60 / 하락 롱<40)
        if base_dir == "▲":
            s_balance = 1 if lr > 60 else 0
        elif base_dir == "▼":
            s_balance = 1 if lr < 40 else 0
        else:
            s_balance = 0

        return {
            "atr": atr, "k1": k1, "oi": oi, "lr": lr,
            "vol_rank": vol_rank, "base_dir": base_dir, "ready": ready,
            "daily": daily, "short": short_trend(ind),
            "scores": {
                "align": s_align, "entry": s_entry, "macro": s_macro,
                "volume": s_volume, "oi": s_oi, "balance": s_balance,
            },
            "total": (s_align + s_entry + s_macro + s_volume + s_oi + s_balance) if ready else 0,
            "max": 10,
        }

    @classmethod
    def get_sorted(cls, data: list, limit: int = 50) -> list:
        """실제 지표·일일 추세 방향 있는 종목 중 점수≥4 → 상위 N개 (없으면 빈 목록)."""
        scored = [(r, cls.calc_score(r[0])) for r in data]
        scored = [x for x in scored if x[1]["ready"]]          # T1: 실제 지표 종목만
        scored.sort(key=lambda x: -x[1]["total"])   # 동점 = 풀 순서(거래량 내림차순) 유지 — ATR 동점 정렬 제거
        # T5: 일일 추세 중립은 제외 — 방향과 무관한 항목만으로 4점이 되어 추세 정보 없이 목록에 오르던 문제
        result = [r for r, res in scored if res["total"] >= 4 and res["base_dir"] is not None]
        # T2: 4점 이상이 없으면 빈 목록 — 기준 미달 상위 30을 선정처럼 보여주던 대체 목록 삭제 (2026-11-16)
        return result[:limit]
