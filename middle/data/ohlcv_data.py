"""
middle/data/ohlcv_data.py
7TF(1m·3m·5m·15m·1h·4h·1d) OHLCV 캔들 수집 — 요청 봉 수는 data_manager._KLINES_LIMITS
RSI·ATR·EMA·VWAP·StochRSI·캔들 패턴 계산의 원천 데이터
"""
from __future__ import annotations

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


def parse_kline_row(k: list) -> OHLCVBar:
    """klines 응답 원소 1개 → OHLCVBar (IndexError·ValueError는 호출처 처리)."""
    return OHLCVBar(
        open_time=int(k[0]),
        open=float(k[1]),
        high=float(k[2]),
        low=float(k[3]),
        close=float(k[4]),
        volume=float(k[5]),
        quote_volume=float(k[7]),
        close_time=int(k[6]),
        taker_buy_volume=float(k[9]),
    )


def _parse_klines(raw: list[list]) -> list[OHLCVBar]:
    """마감 확정 봉만 반환 — 응답의 마지막 원소(진행 중 봉, 또는 마감 직후 미확정 값의 봉)는 제외.

    뒤에 다음 봉이 있는 봉만 최종값이다(2026-10-26 실측 130/130). 로컬 시계와 무관.
    """
    result: list[OHLCVBar] = []
    for k in raw[:-1]:
        try:
            result.append(parse_kline_row(k))
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

