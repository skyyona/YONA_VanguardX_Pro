"""Futures 전체 잔고 조회"""
from __future__ import annotations
from header.api.binance_client import HeaderBinanceClient
from header.models import WalletBalanceResult


class FuturesBalance:
    def __init__(self, client: HeaderBinanceClient) -> None:
        self._client = client

    def fetch(self) -> WalletBalanceResult:
        return self._client.fetch_futures_total_balance_with_status()
