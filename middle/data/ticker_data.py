"""
middle/data/ticker_data.py
24h 시세·거래량·변동률 수집 — 전체 USDT 선물 심볼
모든 Sort by 랭킹의 기본 데이터 소스
"""
from __future__ import annotations

from middle.api.binance_client import MiddleBinanceClient
from middle.models import SymbolTicker


class TickerData:
    def __init__(self, client: MiddleBinanceClient) -> None:
        self._client = client

    def fetch_all(self) -> list[SymbolTicker]:
        """전체 USDT 영구 선물 24h ticker 반환."""
        raw_list = self._client.fetch_all_tickers()
        result: list[SymbolTicker] = []
        for r in raw_list:
            try:
                result.append(SymbolTicker(
                    symbol=r["symbol"],
                    last_price=float(r.get("lastPrice", 0)),
                    price_change=float(r.get("priceChange", 0)),
                    price_change_pct=float(r.get("priceChangePercent", 0)),
                    volume_usdt=float(r.get("quoteVolume", 0)),
                    high_24h=float(r.get("highPrice", 0)),
                    low_24h=float(r.get("lowPrice", 0)),
                ))
            except (KeyError, ValueError):
                continue
        return result


