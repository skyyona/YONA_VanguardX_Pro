"""
middle/col1_ranking/ranking/sharp_decline_scorer.py
Sharp decline Sort by — 급락 직전 롱 쏠림 심볼 스코어링
자격 조건: 롱쏠림(lr) ≥ 50% AND FR ≥ 0 (숏이 비용을 내는 FR 음수 종목 제외 — 롱 쏠림 압박 아님, 2026-11-16)
  + 채점용 지표가 실제 값(ind_ready — 갱신 대상 밖 옛 값·기본값 제외, 2026-11-16)
5개 항목(13점 만점): 롱쏠림(0~4) + FR(0~3) + OI(0~2) + Player태그(0~2) + VSS(0~2)
  OI = 1시간 OI 증가율(oi_change_1h, 부호 유지): +3% 초과 1 · +8% 초과 2 — 롱 쏠림 중 새 레버리지 롱 유입(롱 청산 연료)
  (2026-11-16 — 기존 10분 |변화| 5%·15% 기준은 실측 100종목 0점, 감소도 가점이던 문제. Sharp rise와 같은 기준)
  롱청산근접(0~3) 제외 (2026-11-16, Sharp rise와 같은 이유) — liq_long_pct는 1h ATR%·FR·롱비율만의 추정값이라
  롱쏠림과 중복이고 남는 정보(ATR)는 변동성이 낮을수록 고득점. 값 자체는 엔진 G8·3열 청산 패널이 그대로 사용.
"""
from __future__ import annotations

from middle.analysis.tag_detector import TagDetector
from middle.widget.shared_context import get_ind, get_player, get_player_map, ind_ready


class SharpDeclineScorer:
    """Sharp decline 모드: 롱 쏠림 기반 급락 후보 스코어링."""

    # Player 가산 태그 — 하락 태그 중 롱비율·FR 조건만으로 정해지는 3개 제외 (2026-11-16):
    #   FR+ 과열(FR>0.10)·롱 스퀴즈(롱>80·FR>0.10)·FOMO 극단(롱>85·FR>0.08)은 롱쏠림·FR 항목과 같은 조건이라 이중 가점.
    #   청산 헌터(ATR)·세력 분산(OI·가격)·고래 매도(VSS·BPR)는 다른 정보 포함 → 유지. 3열 Player 가산점 표시도 이 집합 사용.
    PLAYER_KEYS = frozenset(TagDetector.DECLINE_KEYS - {"FR+ 과열", "롱 스퀴즈", "FOMO 극단"})

    @classmethod
    def _has_decline_tag(cls, sym: str, player_map: dict | None = None) -> bool:
        """Player 가산 태그(청산 헌터·세력 분산·고래 매도) 여부 — 절단 전 전체 태그 기준.
        player_map: 1열 재구성 시 계산한 get_player_map() 결과 (없으면 심볼 단독 감지)"""
        if player_map is not None:
            entry = player_map.get(sym)
            return bool(entry and cls.PLAYER_KEYS.intersection(entry["keys"]))
        det = get_player(sym)
        return bool(det and cls.PLAYER_KEYS.intersection(det.keys))

    @classmethod
    def calc_score(cls, sym: str, player_map: dict | None = None) -> dict:
        ind   = get_ind(sym)
        ready = ind_ready(sym)   # False → 자격 미달 (거래량 101~200위 옛 값·기본값으로 채점하지 않음)
        lr    = ind.get("long_ratio", 50.0)
        fr    = ind.get("funding_rate", 0.0)
        oi    = ind.get("oi_change_1h", 0.0)
        vss   = ind.get("vss", 1.0)

        s_lr  = 4 if lr >= 80 else 3 if lr >= 70 else 2 if lr >= 60 else 1 if lr >= 50 else 0
        s_fr  = 3 if fr > 0.08 else 2 if fr > 0.05 else 1 if fr > 0.03 else 0
        s_oi  = 2 if oi > 8 else 1 if oi > 3 else 0

        has_decline_tag = cls._has_decline_tag(sym, player_map)
        s_player = 2 if has_decline_tag else 0

        s_vss = 2 if vss > 1.5 else 1 if vss > 1.2 else 0

        return {
            "qualified": ready and lr >= 50.0 and fr >= 0.0,
            "ready": ready,
            "lr": lr, "fr": fr, "oi": oi, "vss": vss,
            "has_decline_tag": has_decline_tag,
            "scores": {"lr": s_lr, "fr": s_fr, "oi": s_oi,
                       "player": s_player, "vss": s_vss},
            "total": s_lr + s_fr + s_oi + s_player + s_vss,
            "max": 13,
        }

    @classmethod
    def get_sorted(cls, data: list, limit: int = 30) -> list:
        """롱쏠림≥50%·FR≥0 자격 + 점수≥4 필터 → 상위 N개."""
        player_map = get_player_map()
        scored = [(r, cls.calc_score(r[0], player_map)) for r in data]
        scored.sort(key=lambda x: (999, -x[1]["vss"]) if not x[1]["qualified"]
                    else (-x[1]["total"], -x[1]["vss"]))
        result = [r for r, res in scored if res["qualified"] and res["total"] >= 4]
        if not result:
            result = [r for r, res in scored if res["qualified"]]
        return result[:limit]
