"""
middle/data/funding_rate_data.py
펀딩비(FR) 수집 — 파생분석 / Sharp rise·decline 스코어링에 사용
"""
from __future__ import annotations

from middle.api.binance_client import MiddleBinanceClient
from middle.models import FundingRateData


class FundingRateFetcher:
    def __init__(self, client: MiddleBinanceClient) -> None:
        self._client = client

    def fetch(self, symbol: str) -> FundingRateData | None:
        """최신 펀딩비 1건 반환."""
        raw = self._client.fetch_latest_funding_rate(symbol)
        if not raw:
            return None
        try:
            return FundingRateData(
                symbol=raw.get("symbol", symbol),
                funding_rate=float(raw.get("fundingRate", 0.0)),
                funding_time=int(raw.get("fundingTime", 0)),
            )
        except (KeyError, ValueError):
            return None

    def fetch_history(self, symbol: str, limit: int = 8) -> list[FundingRateData]:
        """펀딩비 이력 반환 (FR 추세 분석용)."""
        raw_list = self._client.fetch_funding_rate_history(symbol, limit)
        result: list[FundingRateData] = []
        for r in raw_list:
            try:
                result.append(FundingRateData(
                    symbol=r.get("symbol", symbol),
                    funding_rate=float(r.get("fundingRate", 0.0)),
                    funding_time=int(r.get("fundingTime", 0)),
                ))
            except (KeyError, ValueError):
                continue
        return result


