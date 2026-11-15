"""
middle/data/open_interest_data.py
미결제약정(OI) 수집 및 OI 변화율 계산
파생분석 / Sharp rise·decline / 4TF Optimization / Newly Listed 스코어링에 사용
"""
from __future__ import annotations

from middle.api.binance_client import MiddleBinanceClient
from middle.models import OpenInterestData


class OpenInterestFetcher:
    def __init__(self, client: MiddleBinanceClient) -> None:
        self._client = client

    def fetch(self, symbol: str) -> OpenInterestData | None:
        """현재 OI 반환."""
        raw = self._client.fetch_open_interest(symbol)
        if not raw:
            return None
        try:
            return OpenInterestData(
                symbol=raw.get("symbol", symbol),
                open_interest=float(raw.get("openInterest", 0.0)),
                timestamp=int(raw.get("time", 0)),
            )
        except (KeyError, ValueError):
            return None

    def fetch_series(self, symbol: str, period: str = "5m", limit: int = 290) -> dict[int, float]:
        """OI 이력 {timestamp ms: sumOpenInterest} — timestamp는 해당 시각의 OI (봉 마감 시각 = 다음 봉 open_time).
        조회 실패·형식 오류 항목은 제외."""
        out: dict[int, float] = {}
        for x in self._client.fetch_open_interest_hist(symbol, period, limit):
            try:
                out[int(x["timestamp"])] = float(x["sumOpenInterest"])
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def fetch_change_pct(self, symbol: str, period: str = "5m", lookback: int = 2) -> float:
        """OI 변화율 (%) 반환.
        lookback: 몇 기간 전 대비 현재 OI 변화율을 계산할지
        """
        hist = self._client.fetch_open_interest_hist(symbol, period, max(lookback + 1, 3))
        if len(hist) < 2:
            return 0.0
        try:
            newest = float(hist[-1].get("sumOpenInterest", 0))
            oldest = float(hist[0].get("sumOpenInterest", 0))
            if oldest <= 0:
                return 0.0
            return (newest - oldest) / oldest * 100.0
        except (KeyError, ValueError, IndexError):
            return 0.0

