"""
bottom/backtest/historical_data_loader.py
백테스팅용 과거 OHLCV 데이터 로드 — Binance 공개 API 사용 (키 불필요)
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

_FUTURES_BASE = "https://fapi.binance.com"

# Binance klines API 1회 요청 최대 봉 수
_MAX_LIMIT = 1500

# 기간별 캔들 수 (백테스팅용)
# 7일: 5m×2016봉 — 1m 기반 4TF 전략에 가장 근접한 실용 TF
#       (1m×10080봉 필요하나 Binance 1회 1500봉 제한으로 1m 불가, 5m이 최적)
#       2016봉 > 1500 → load_for_period()에서 2회 페이지네이션 자동 처리
PERIOD_CANDLES = {
    "7일":  {"interval": "5m", "limit": 2016},    # 7 × 288 (5m 봉/일)
    "14일": {"interval": "1h", "limit": 336},     # 14 × 24
    "30일": {"interval": "1h", "limit": 720},     # 30 × 24
    "90일": {"interval": "4h", "limit": 540},     # 90 × 6
}


@dataclass
class HistoricalBar:
    open_time:  int
    open:       float
    high:       float
    low:        float
    close:      float
    volume:     float
    close_time: int


class HistoricalDataLoader:
    """Binance Futures 과거 OHLCV 데이터 로더."""

    @staticmethod
    def load(symbol: str, interval: str = "5m", limit: int = 2016,
             end_time_ms: int | None = None) -> list[HistoricalBar]:
        """공개 API로 과거 캔들 데이터 로드.

        end_time_ms: 해당 시각 이전 봉까지 로드 (페이지네이션 2차 요청용).
        """
        qs = (f"symbol={symbol}&interval={interval}"
              f"&limit={min(limit, _MAX_LIMIT)}")
        if end_time_ms is not None:
            qs += f"&endTime={end_time_ms}"
        url = f"{_FUTURES_BASE}/fapi/v1/klines?{qs}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            return [
                HistoricalBar(
                    open_time=int(k[0]), open=float(k[1]), high=float(k[2]),
                    low=float(k[3]), close=float(k[4]), volume=float(k[5]),
                    close_time=int(k[6]),
                )
                for k in raw
            ]
        except Exception:
            return []

    @staticmethod
    def load_bars(symbol: str, interval: str, total: int) -> list[HistoricalBar]:
        """N회 페이지네이션으로 total봉을 시간 오름차순으로 로드.

        total ≤ _MAX_LIMIT(1500)이면 1회 요청. 초과하면 최신 배치부터 역방향으로
        누적 후 시간 오름차순으로 병합한다.
        """
        if total <= _MAX_LIMIT:
            return HistoricalDataLoader.load(symbol, interval, total)

        pages:       list[list[HistoricalBar]] = []
        need:        int = total
        end_time_ms: "int | None" = None

        while need > 0:
            n     = min(need, _MAX_LIMIT)
            page  = HistoricalDataLoader.load(symbol, interval, n, end_time_ms)
            if not page:
                break
            pages.append(page)
            need -= len(page)
            if len(page) < n:       # API가 요청보다 적게 반환 → 더 이전 데이터 없음
                break
            end_time_ms = page[0].open_time - 1  # 이전 배치 직전 ms 로 역방향 이동

        # pages[0] = 최신 배치, pages[-1] = 가장 오래된 배치 → 역순 병합
        pages.reverse()
        merged: list[HistoricalBar] = []
        for p in pages:
            merged.extend(p)
        return merged

    @staticmethod
    def load_for_period(symbol: str, period: str) -> list[HistoricalBar]:
        """기간 문자열("7일", "14일", "30일", "90일")로 로드.

        limit > _MAX_LIMIT(1500)인 경우 페이지네이션 2회 요청으로 자동 처리.
        현재 "7일"(5m×2016봉)이 해당됨.
        """
        cfg      = PERIOD_CANDLES.get(period, {"interval": "1h", "limit": 168})
        interval = cfg["interval"]
        limit    = cfg["limit"]

        if limit <= _MAX_LIMIT:
            return HistoricalDataLoader.load(symbol, interval, limit)

        # 페이지네이션: 최근 _MAX_LIMIT봉 + 그 이전 나머지 봉
        first = HistoricalDataLoader.load(symbol, interval, _MAX_LIMIT)
        if not first:
            return []

        remaining   = limit - _MAX_LIMIT
        end_time_ms = first[0].open_time - 1   # 첫 번째 배치 직전 ms
        second      = HistoricalDataLoader.load(
            symbol, interval, remaining, end_time_ms)

        # 시간 오름차순 병합: 오래된 봉(second) + 최신 봉(first)
        return second + first

    @staticmethod
    def load_long_short_ratio(symbol: str) -> tuple[list[int], list[float]]:
        """글로벌 롱/숏 비율 이력 로드. (times_ms, long_pct_list) 튜플 반환.

        5m 페이지네이션으로 최대 30일치 로드 (Binance API 제공 상한).
        결손 구간은 호출처에서 50% 중립 처리 (bisect_right 경계 기준).
        부분 실패 시 지금까지 수집분을 반환한다.
        공개 API — 인증 불필요.
        ⚠ 90일 백테스트 시 최대 커버리지 33.3% (30일 / 90일).
        """
        _LIMIT    = 500                              # API 1회 최대 반환 수
        _MAX_BARS = 30 * 24 * 12                     # 30일 × 5m 봉 수 = 8,640
        _MAX_PAGES = (_MAX_BARS + _LIMIT - 1) // _LIMIT  # = 18

        pages_times: list[list[int]]   = []
        pages_pct:   list[list[float]] = []
        end_time_ms: int | None        = None

        for _ in range(_MAX_PAGES):
            qs = f"symbol={symbol}&period=5m&limit={_LIMIT}"
            if end_time_ms is not None:
                qs += f"&endTime={end_time_ms}"
            url = f"{_FUTURES_BASE}/futures/data/globalLongShortAccountRatio?{qs}"
            try:
                with urllib.request.urlopen(url, timeout=10) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                if not raw:
                    break
                t_list   = [int(r["timestamp"])              for r in raw]
                pct_list = [float(r["longAccount"]) * 100.0  for r in raw]
                pages_times.append(t_list)
                pages_pct.append(pct_list)
                if len(raw) < _LIMIT:   # 더 이전 데이터 없음
                    break
                end_time_ms = t_list[0] - 1  # 이전 배치 직전 ms 로 역방향 이동
            except Exception:
                break  # 부분 실패 시 수집분 반환

        # pages[0] = 최신 배치, pages[-1] = 가장 오래된 배치 → 역순 병합
        pages_times.reverse()
        pages_pct.reverse()
        times:    list[int]   = []
        long_pct: list[float] = []
        for t, p in zip(pages_times, pages_pct):
            times.extend(t)
            long_pct.extend(p)
        return times, long_pct

    @staticmethod
    def load_funding_rate(symbol: str, limit: int = 360) -> tuple[list[int], list[float]]:
        """과거 펀딩비 이력 로드. (times_ms, fr_pct_list) 튜플 반환.

        limit=360 → 90일 기준 약 360건 (8시간마다 1건).
        fundingRate raw float에 100.0을 곱해 % 단위로 변환.
        공개 API — 인증 불필요.
        """
        url = (f"{_FUTURES_BASE}/fapi/v1/fundingRate"
               f"?symbol={symbol}&limit={limit}")
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            times  = [int(r["fundingTime"])         for r in raw]
            fr_pct = [float(r["fundingRate"]) * 100.0 for r in raw]
            return times, fr_pct
        except Exception:
            return [], []

