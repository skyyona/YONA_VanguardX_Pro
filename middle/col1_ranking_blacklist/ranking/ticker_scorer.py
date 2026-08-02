"""
middle/col1_ranking_blacklist/ranking/ticker_scorer.py
24h Ticker Sort by — 전체 심볼 24h 변동률 내림차순 정렬
"""
from __future__ import annotations


class TickerScorer:
    """24h Ticker 모드: 변동률 내림차순 정렬, 블랙리스트 필터링."""

    @staticmethod
    def get_sorted(data: list, data_mgr, bl_mgr, limit: int = 100) -> list:
        """전체 심볼에서 24h 변동률 상위 N개 반환.

        get_ranking_rows()는 거래량 상위 200개만 반환하므로
        24h Ticker는 DataManager의 전용 메서드로 전체 심볼에서 직접 정렬한다.
        data_mgr가 없으면 이미 전달된 data(거래량 상위 200개 풀)로 폴백한다.
        """
        if data_mgr is not None:
            rows = data_mgr.get_all_ranked_by_change(limit)
            if bl_mgr is not None and bl_mgr.get_all():
                rows = [r for r in rows if not bl_mgr.is_blacklisted(r[0])]
            return rows
        sorted_data = sorted(
            data, key=lambda r: -float(r[4].replace("%", "").replace("+", ""))
        )
        return sorted_data[:limit]
