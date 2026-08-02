"""
middle/col1_ranking_blacklist/ranking/player_ranking.py
Real-Time Ranking 1열 — Player Detection 배경 표시용 전심볼 스캔

Sort by 모드 무관하게 랭킹 목록 전 심볼에 TagDetector를 실행하여
태그가 감지된 심볼 목록을 반환한다.
gold_ranking.py 와 동일한 shared_context 접근 패턴 사용.
"""
from __future__ import annotations

from middle.widget.shared_context import get_ind, _live_ranking
from middle.col3_analysis_panels.player_detection.tag_detector import TagDetector


class PlayerRanking:
    """랭킹 전 심볼 Player Detection 스캔."""

    @staticmethod
    def scan_all() -> dict[str, dict]:
        """랭킹 목록 전 심볼 태그 감지.

        Returns:
            {symbol: {
                "tags":      [(tag_text, tag_color, strength_pct), ...],  # 강도 내림차순
                "direction": "long" | "short" | "mixed",                  # 롱 편향 / 숏 편향 / 혼재
            }}
            태그가 없는 심볼은 결과에 포함되지 않는다.
        """
        result: dict[str, dict] = {}
        try:
            for row in _live_ranking():
                sym = row[0]
                try:
                    ind = get_ind(sym)
                    if not ind:
                        continue
                    det = TagDetector.detect(
                        long_pct      = ind.get("long_ratio",       50.0),
                        fr_pct        = ind.get("funding_rate",      0.0),
                        oi_change_pct = ind.get("oi_change",         0.0),
                        vss           = ind.get("vss",               1.0),
                        bpr           = ind.get("bpr",               0.5),
                        atr_pct       = ind.get("atr",               2.0),
                        price_chg_pct = ind.get("price_change_pct",  0.0),
                    )
                    if not det.tags:
                        continue
                    tags = [(t.tag_text, t.tag_color, t.strength_pct) for t in det.tags]
                    detected_keys = {t.tag_key for t in det.tags}
                    has_rise    = bool(detected_keys & TagDetector.RISE_KEYS)
                    has_decline = bool(detected_keys & TagDetector.DECLINE_KEYS)
                    if has_rise and has_decline:
                        direction = "mixed"
                    elif has_rise:
                        direction = "long"
                    else:
                        direction = "short"
                    result[sym] = {"tags": tags, "direction": direction}
                except Exception:
                    pass
        except Exception:
            pass
        return result
