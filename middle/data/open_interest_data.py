"""
middle/data/open_interest_data.py
미결제약정(OI) 수집 및 OI 변화율 계산
파생분석 / Sharp rise·decline / 4TF Optimization / Newly Listed 스코어링에 사용
"""
from __future__ import annotations

from middle.api.binance_client import MiddleBinanceClient
from middle.models import OpenInterestData


_CHANGE_1H_POINTS = 13   # 5m 이력 13개 = 1시간(12구간)


def _change_pct(hist: list[dict]) -> float:
    """이력 처음→끝 OI 변화율 (%). 2개 미만·형식 오류·처음 값 0 이하 → 0.0."""
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

    def fetch_changes(self, symbol: str, period: str = "5m") -> tuple[float, float]:
        """(10분 OI 변화율 %, 1시간 OI 변화율 %) — 5m 이력 13개 요청 1회 (기존 3개 → 13개, 요청 수 같음, 2026-11-16).
        10분 값: 마지막 3개 처음→끝 (기존 oi_change 정의 그대로 — Player 태그·Sharp decline·4TF·Newly·3열 공용).
        1시간 값: 13개(12구간) 처음→끝 — Sharp rise OI 항목 전용. 13개 미만(신규 상장 등)이면 0.0."""
        hist = self._client.fetch_open_interest_hist(symbol, period, _CHANGE_1H_POINTS)
        chg_1h = _change_pct(hist) if len(hist) >= _CHANGE_1H_POINTS else 0.0
        return _change_pct(hist[-3:]), chg_1h

