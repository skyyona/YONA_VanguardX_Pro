"""
middle/col1_ranking_blacklist/ranking/gold_ranking.py
종합 1위 (Gold Ranking) — 모든 Sort by 모드와 무관하게
수익 가능성이 가장 높은 코인 심볼 1개를 자동 선별.

방향 분리 평가 (롱·숏 방향 충돌 방지):
  4TF ▲  →  롱 기회 = tf × 0.40 + SharpRise(qualified) × 0.35 + ATR × 0.25
  4TF ▼  →  숏 기회 = tf × 0.40 + SharpDecline(qualified) × 0.35 + ATR × 0.25
  4TF 중립 →  중립  = max(Rise, Decline)(qualified) × 0.35 + ATR × 0.25
  최종 = max(롱 기회, 숏 기회, 중립)   (0.0 ~ 1.0)
후보 = 랭킹 풀(거래량 상위 200) 중 블랙리스트 제외 (1열 목록과 같은 제외 기준)
"""
from __future__ import annotations

from middle.widget.shared_context import get_ind, _live_ranking, is_blacklisted
from middle.col1_ranking_blacklist.ranking.fourtf_scorer import FourTFScorer
from middle.col1_ranking_blacklist.ranking.sharp_rise_scorer import SharpRiseScorer
from middle.col1_ranking_blacklist.ranking.sharp_decline_scorer import SharpDeclineScorer


class GoldRanking:
    """종합 수익 가능성 1위 코인 심볼 선별기 (롱·숏 방향 중립)."""

    @staticmethod
    def calc(sym: str, player_map: dict | None = None) -> float:
        """단일 심볼의 종합 점수 계산 (0.0 ~ 1.0).

        4TF 방향(▲/▼/중립)에 따라 롱·숏 평가 경로를 분리하여
        방향 충돌(4TF ▲ + SharpDecline 합산)을 원천 차단.
        player_map: 1열 재구성 시 계산한 get_player_map() 결과 (없으면 심볼 단독 감지)
        """
        ind = get_ind(sym)
        if not ind:
            return 0.0

        atr_score = min(ind.get("atr", 0.0) / 3.0, 1.0)

        tf_res   = FourTFScorer.calc_score(sym)
        tf_score = tf_res["total"] / tf_res["max"]
        base_dir = tf_res.get("base_dir")   # "▲" / "▼" / None

        rise_res = SharpRiseScorer.calc_score(sym, player_map)
        decl_res = SharpDeclineScorer.calc_score(sym, player_map)

        # ── 롱 기회: 4TF ▲ 정렬 + 숏스퀴즈 가능성 ─────────────
        if base_dir == "▲":
            squeeze = (rise_res["total"] / rise_res["max"]
                       if rise_res["qualified"] else 0.0)
            return tf_score * 0.40 + squeeze * 0.35 + atr_score * 0.25

        # ── 숏 기회: 4TF ▼ 정렬 + 롱스퀴즈 가능성 ─────────────
        if base_dir == "▼":
            squeeze = (decl_res["total"] / decl_res["max"]
                       if decl_res["qualified"] else 0.0)
            return tf_score * 0.40 + squeeze * 0.35 + atr_score * 0.25

        # ── 4TF 중립: 스퀴즈 + 변동성 기반 (최대 60점) ─────────
        sq = max(
            rise_res["total"] / rise_res["max"] if rise_res["qualified"] else 0.0,
            decl_res["total"] / decl_res["max"] if decl_res["qualified"] else 0.0,
        )
        return sq * 0.35 + atr_score * 0.25

    @staticmethod
    def get_top1(player_map: dict | None = None) -> str:
        """현재 랭킹 목록(블랙리스트 제외)에서 종합 점수 1위 심볼 반환. 없으면 빈 문자열."""
        best_sym, best_score = "", -1.0
        try:
            for row in _live_ranking():
                sym = row[0]
                if is_blacklisted(sym):
                    continue
                try:
                    s = GoldRanking.calc(sym, player_map)
                    if s > best_score:
                        best_score, best_sym = s, sym
                except Exception:
                    pass
        except Exception:
            pass
        return best_sym
