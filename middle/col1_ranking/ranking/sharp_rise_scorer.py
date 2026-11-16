"""
middle/col1_ranking/ranking/sharp_rise_scorer.py
Sharp rise Sort by — 급등 직전 숏 쏠림 심볼 스코어링
자격 조건: FR<-0.01% OR 숏쏠림(sr) ≥ 50% (숏 다수 — 숏쏠림 점수 시작점과 같은 기준, 2026-11-16 40→50)
  + 채점용 지표가 실제 값(ind_ready — 갱신 대상 밖 옛 값·기본값 제외, 2026-11-16)
5개 항목(13점 만점): 숏쏠림(0~4) + FR(0~3) + OI(0~2) + Player태그(0~2) + VSS(0~2)
  OI = 1시간 OI 증가율(oi_change_1h, 부호 유지): +3% 초과 1 · +8% 초과 2 (2026-11-16 — 기존 10분 |변화| 5%·15% 기준은
  실측 100종목 0점(10분 최대 3.15%). 1시간 실측 상위 5% +3.26% · 최대 +13.19%. 감소는 가점 없음)
  숏청산근접(0~3) 제외 (2026-11-16) — liq_short_pct는 1h ATR%·FR·롱비율만의 추정값이라 숏쏠림·FR과 중복이고
  남는 정보(ATR)는 변동성이 낮을수록 고득점 → 목적과 반대. 값 자체는 엔진 G8·3열 청산 패널이 그대로 사용.
"""
from __future__ import annotations

from middle.analysis.tag_detector import TagDetector
from middle.widget.shared_context import get_ind, get_player, get_player_map, ind_ready


class SharpRiseScorer:
    """Sharp rise 모드: 숏 쏠림 기반 급등 후보 스코어링."""

    # Player 가산 태그 — 상승 태그 중 'FR-' 제외 (2026-11-16): FR- 태그 조건(FR < −0.05%)은 FR 항목 3점과
    # 같은 조건이라 펀딩비 하나가 5점이 되던 이중 가점 제거. 3열 Player 가산점 표시도 이 집합 사용.
    PLAYER_KEYS = frozenset(TagDetector.RISE_KEYS - {"FR-"})

    @classmethod
    def _has_rise_tag(cls, sym: str, player_map: dict | None = None) -> bool:
        """Player 가산 태그(고래 매수·세력 매집·기관 유입) 여부 — 절단 전 전체 태그 기준.
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
        sr    = 100.0 - lr

        s_sr  = 4 if sr >= 80 else 3 if sr >= 70 else 2 if sr >= 60 else 1 if sr >= 50 else 0
        s_fr  = 3 if fr < -0.05 else 2 if fr < -0.03 else 1 if fr < -0.01 else 0
        s_oi  = 2 if oi > 8 else 1 if oi > 3 else 0

        has_rise_tag = cls._has_rise_tag(sym, player_map)
        s_player = 2 if has_rise_tag else 0

        s_vss = 2 if vss > 1.5 else 1 if vss > 1.2 else 0

        return {
            "qualified": ready and ((fr < -0.01) or (sr >= 50.0)),
            "ready": ready,
            "sr": sr, "fr": fr, "oi": oi, "vss": vss,
            "has_rise_tag": has_rise_tag,
            "scores": {"sr": s_sr, "fr": s_fr, "oi": s_oi,
                       "player": s_player, "vss": s_vss},
            "total": s_sr + s_fr + s_oi + s_player + s_vss,
            "max": 13,
        }

    @classmethod
    def get_sorted(cls, data: list, limit: int = 20) -> list:
        """FR<-0.01 or SR≥50% 자격 + 점수≥4 필터 → 상위 N개."""
        player_map = get_player_map()
        scored = [(r, cls.calc_score(r[0], player_map)) for r in data]
        scored.sort(key=lambda x: (999, -x[1]["vss"]) if not x[1]["qualified"]
                    else (-x[1]["total"], -x[1]["vss"]))
        result = [r for r, res in scored if res["qualified"] and res["total"] >= 4]
        if not result:
            result = [r for r, res in scored if res["qualified"]]
        return result[:limit]
