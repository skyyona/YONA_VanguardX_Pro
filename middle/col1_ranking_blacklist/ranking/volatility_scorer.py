"""
middle/col1_ranking_blacklist/ranking/volatility_scorer.py
Volatility Sort by — ATR% 변동성 내림차순 정렬
"""
from __future__ import annotations

from middle.widget.shared_context import get_ind


class VolatilityScorer:
    """Volatility 모드: ATR%(변동성) 내림차순 정렬."""

    @staticmethod
    def get_sorted(data: list, limit: int = 100) -> list:
        def _vol_key(r):
            ind = get_ind(r[0])
            atr = ind.get("atr")
            if atr is None:
                try:
                    atr = abs(float(r[4].replace("%", "").replace("+", "")))
                except (ValueError, AttributeError):
                    atr = 0.0
            return -atr
        sorted_data = sorted(data, key=_vol_key)
        return sorted_data[:limit]
