"""
middle/col2_chart_indicators/coin_chart.py
Coin Chart 데이터 준비 전담 — Col2 캔들 차트 렌더링용 전처리
panel_col2._draw_chart() 에서 호출.

입력: shared_context.get_chart_bars() dict 리스트 [{"o","h","l","c","v"}, ...] — 마감 봉 + 진행 중 봉(맨 끝), 시간 순
출력: ChartData (표시할 마지막 show 봉의 candles / ema20 / ema50 / vwap / support / resist)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChartCandle:
    """차트 렌더링용 단순화 캔들 (dict 변환 결과)."""
    o:  float   # open
    h:  float   # high
    l:  float   # low
    c:  float   # close
    v:  float   # volume
    is_bullish: bool


@dataclass
class ChartData:
    """panel_col2 차트 렌더러에 전달할 준비된 데이터."""
    candles:       list[ChartCandle]
    ema20_line:    list[float]        # EMA 20
    ema50_line:    list[float]        # EMA 50
    vwap_line:     list[float]        # VWAP
    support_level: float | None       # 최근 20봉 저점
    resist_level:  float | None       # 최근 20봉 고점
    symbol:        str = ""


class CoinChart:
    """Coin Chart 데이터 준비기.

    panel_col2 가 받은 봉 dict 리스트로 EMA20·EMA50·VWAP·지지저항 수준을 계산해 표시 구간만 반환.
    """

    @classmethod
    def prepare(
        cls,
        candles: list[dict],   # [{"o","h","l","c","v"}, ...] — 시간 순 (마지막 = 진행 중 봉일 수 있음)
        symbol: str = "",
        show: int = 60,        # 화면에 그릴 봉 수
    ) -> ChartData:
        """OHLCV dict 리스트 → ChartData 변환 (표시 구간 = 마지막 show 봉).

        EMA는 받은 전체 봉(1m~1h 캐시 약 200봉, 4h·1d 차트 전용 약 250봉)으로 계산한 뒤 표시 구간만 자른다 —
        표시 봉 수(60)로만 계산하면 첫 봉에서 시작한 EMA50이 실제 값과 어긋나던 문제(1시간봉 표시 구간 최대 차이
        중앙 2.0%, 2026-11-23 실측). 4h·1d는 캐시 80봉으로는 부족해 차트 전용 251봉 조회 (2026-11-25).
        VWAP·지지저항은 표시 구간 기준 (기존과 같은 의미).
        """
        if not candles:
            return ChartData([], [], [], [], None, None, symbol=symbol)

        closes = [c["c"] for c in candles]
        ema20  = cls._ema(closes, 20)[-show:]
        ema50  = cls._ema(closes, 50)[-show:]
        shown  = candles[-show:]
        vwap   = cls._vwap(shown)

        chart_candles = [
            ChartCandle(
                o=c["o"], h=c["h"], l=c["l"], c=c["c"], v=c.get("v", 0.0),
                is_bullish=(c["c"] >= c["o"]),
            )
            for c in shown
        ]

        lookback      = shown[-20:]
        support_level = min(c["l"] for c in lookback) if lookback else None
        resist_level  = max(c["h"] for c in lookback) if lookback else None

        return ChartData(
            candles=chart_candles,
            ema20_line=ema20,
            ema50_line=ema50,
            vwap_line=vwap,
            support_level=support_level,
            resist_level=resist_level,
            symbol=symbol,
        )

    # ── 계산 헬퍼 ────────────────────────────────────────────────

    @staticmethod
    def _ema(prices: list[float], period: int) -> list[float]:
        """지수이동평균 전체 시리즈 반환 (봉 수 유지)."""
        if not prices:
            return []
        k   = 2.0 / (period + 1)
        ema = [prices[0]]
        for p in prices[1:]:
            ema.append(p * k + ema[-1] * (1 - k))
        return ema

    @staticmethod
    def _vwap(candles: list[dict]) -> list[float]:
        """VWAP 시리즈 반환 (봉 수 유지)."""
        cum_pv, cum_v = 0.0, 0.0
        result: list[float] = []
        for c in candles:
            typical  = (c["h"] + c["l"] + c["c"]) / 3.0
            vol      = c.get("v", 1.0)
            cum_pv  += typical * vol
            cum_v   += vol
            result.append(cum_pv / cum_v if cum_v > 0 else c["c"])
        return result
