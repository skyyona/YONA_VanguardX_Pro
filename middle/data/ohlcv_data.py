"""
middle/data/ohlcv_data.py
4TF(1m·5m·1h·4h) OHLCV 캔들 수집
RSI·ATR·EMA·VWAP·StochRSI·캔들 패턴 계산의 원천 데이터
"""
from __future__ import annotations

import time

from middle.api.binance_client import MiddleBinanceClient
from middle.models import OHLCVBar

# 각 타임프레임별 기본 요청 캔들 수 (지표 계산에 충분한 양)
_DEFAULT_LIMITS: dict[str, int] = {
    "1m":  100,
    "5m":  100,
    "1h":   60,
    "4h":   60,
    "1d":   30,
}


def _parse_klines(raw: list[list]) -> list[OHLCVBar]:
    result: list[OHLCVBar] = []
    current_ms = int(time.time() * 1000)
    for k in raw:
        try:
            close_time = int(k[6])
            if close_time >= current_ms:
                continue  # 미완성 봉(진행 중 캔들) 건너뜀 — 리페인팅 방지
            result.append(OHLCVBar(
                open_time=int(k[0]),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                quote_volume=float(k[7]),
                close_time=close_time,
            ))
        except (IndexError, ValueError):
            continue
    return result


class OHLCVData:
    def __init__(self, client: MiddleBinanceClient) -> None:
        self._client = client

    def fetch(self, symbol: str, interval: str, limit: int | None = None) -> list[OHLCVBar]:
        """단일 심볼·단일 타임프레임 OHLCV 캔들 반환."""
        n = limit or _DEFAULT_LIMITS.get(interval, 100)
        raw = self._client.fetch_klines(symbol, interval, n)
        return _parse_klines(raw)

    @staticmethod
    def closes(bars: list[OHLCVBar]) -> list[float]:
        return [b.close for b in bars]

