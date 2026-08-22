"""
bottom/engine_core/quality_grader.py
StochRSI 4TF 품질 등급 평가 — 진입 신호 품질 수치화

5개 축(Cascade / Divergence / Zone / 지속성 / Swing) 각 25점.
Swing은 보너스 축: 기본 4축 100점 만점 + Swing 최대 25점 = 최대 125점.
A: 85+ / B: 65+ / C: 45+ / D: <45

4TF 합의 통과 이후 호출되므로 모든 TF의 K>D(롱) 또는 K<D(숏) 전제.
"""
from __future__ import annotations


_TF_KEYS = ("tf1", "tf3", "tf5", "tf15")


class QualityGrader:
    """4TF StochRSI 진입 신호 품질 평가기.

    ind_data: MiddleDataManager.get_ind(symbol) 반환 dict
    side:     "long" | "short"
    """

    @classmethod
    def grade(cls, ind_data: dict, side: str) -> tuple[str, int]:
        """품질 등급과 점수 반환. (grade: "A"|"B"|"C"|"D", score: 0~125)"""
        score = (
            cls._cascade_score(ind_data) +
            cls._divergence_score(ind_data, side) +
            cls._zone_score(ind_data, side) +
            cls._duration_score(ind_data) +
            cls._swing_score(ind_data, side)
        )
        if score >= 85:
            return "A", score
        if score >= 65:
            return "B", score
        if score >= 45:
            return "C", score
        return "D", score

    # ── 4개 평가 축 ───────────────────────────────────────────────

    @classmethod
    def _cascade_score(cls, ind_data: dict) -> int:
        """Cascade (25점): 4TF K-D 스프레드 평균.

        스프레드가 클수록 합의 강도가 높아 고점수.
        """
        spreads: list[float] = []
        for tf_key in _TF_KEYS:
            tf = ind_data.get(tf_key, {})
            k = float(tf.get("k", 50.0))
            d = float(tf.get("d", 50.0))
            spreads.append(abs(k - d))
        if not spreads:
            return 0
        avg = sum(spreads) / len(spreads)
        if avg >= 20: return 25
        if avg >= 15: return 22
        if avg >= 10: return 18
        if avg >= 5:  return 12
        if avg >= 2:  return 7
        return 0

    @classmethod
    def _divergence_score(cls, ind_data: dict, side: str) -> int:
        """Divergence (25점): 4TF 중 StochRSI 다이버전스 감지 여부.

        롱: bull div=25, 없음=12, bear div=0
        숏: bear div=25, 없음=12, bull div=0
        """
        best = 12   # 기본: 다이버전스 미감지 (중립)
        for tf_key in _TF_KEYS:
            div = ind_data.get(tf_key, {}).get("div", None)
            if side == "long":
                if div == "bull":
                    return 25          # 가장 유리한 케이스 즉시 반환
                if div == "bear":
                    best = min(best, 0)
            else:
                if div == "bear":
                    return 25
                if div == "bull":
                    best = min(best, 0)
        return best

    @classmethod
    def _zone_score(cls, ind_data: dict, side: str) -> int:
        """Zone (25점): 표준 TF(tf5) K값 위치.

        롱: K 낮을수록 과매도 구간 = 고점수
        숏: K 높을수록 과매수 구간 = 고점수
        """
        k = float(ind_data.get("tf5", {}).get("k", 50.0))
        if side == "long":
            if k < 20: return 25
            if k < 30: return 20
            if k < 40: return 15
            if k < 50: return 10
            return 5
        else:
            if k > 80: return 25
            if k > 70: return 20
            if k > 60: return 15
            if k > 50: return 10
            return 5

    @classmethod
    def _duration_score(cls, ind_data: dict) -> int:
        """지속성 (25점): tf5 기준 교차 후 경과 시간.

        _fmt_elapsed() 포맷("방금" | "Xmin 전" | "X시간 전")을 파싱.
        오래 지속될수록 신호 안정성 높음.
        """
        elapsed = ind_data.get("tf5", {}).get("elapsed", None)
        if elapsed is None:
            return 3
        elapsed_str = str(elapsed)
        if "시간 전" in elapsed_str:
            return 25
        if "분 전" in elapsed_str:
            try:
                mins = int(elapsed_str.split("분")[0].strip())
                if mins >= 10: return 25
                if mins >= 5:  return 20
                if mins >= 3:  return 15
                if mins >= 1:  return 10
            except ValueError:
                pass
            return 10
        if elapsed_str == "방금":
            return 5    # 수정: 15 → 5 (1분 전=10보다 낮게, 신호 불안정)
        return 3

    @classmethod
    def _swing_score(cls, ind_data: dict, side: str) -> int:
        """Swing 보너스 (25점): 15m 스윙 고저 구조 일치 여부.

        swing_bull(롱) / swing_bear(숏) 구조가 확인되면 추세 지속성 가점.
        """
        if side == "long" and ind_data.get("swing_bull", False):
            return 25
        if side == "short" and ind_data.get("swing_bear", False):
            return 25
        return 0
