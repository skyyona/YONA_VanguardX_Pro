"""
middle/data/longshort_data.py
롱숏 비율·청산 근접도 수집
파생분석 / Sharp rise(숏 쏠림)·Sharp decline(롱 쏠림) 스코어링에 사용
"""
from __future__ import annotations

from middle.api.binance_client import MiddleBinanceClient
from middle.models import LongShortData


class LongShortFetcher:
    def __init__(self, client: MiddleBinanceClient) -> None:
        self._client = client

    def fetch(self, symbol: str, period: str = "5m") -> LongShortData | None:
        """계좌 기준 롱/숏 비율 반환."""
        raw_list = self._client.fetch_long_short_ratio(symbol, period, 1)
        if not raw_list:
            return None
        raw = raw_list[-1]
        try:
            long_pct  = float(raw.get("longAccount", 0.5)) * 100.0
            short_pct = float(raw.get("shortAccount", 0.5)) * 100.0
            ratio     = float(raw.get("longShortRatio", 1.0))
            return LongShortData(
                symbol=symbol,
                long_account_pct=long_pct,
                short_account_pct=short_pct,
                long_short_ratio=ratio,
                timestamp=int(raw.get("timestamp", 0)),
            )
        except (KeyError, ValueError):
            return None


