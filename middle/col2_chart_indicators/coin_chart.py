"""
middle/col2_chart_indicators/coin_chart.py
Coin Chart 데이터 준비 전담 — Col2 캔들 차트 렌더링용 전처리
panel_col2._draw_mpl_chart() / _draw_canvas_fallback() 에서 호출.

입력: generate_ohlcv() 호환 dict 리스트 [{"o","h","l","c","v"}, ...]
출력: ChartData (candles / ema20 / ema50 / vwap / support / resist)
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

    panel_col2 가 generate_ohlcv() 로 받은 dict 리스트를 받아
    렌더링에 필요한 EMA20·EMA50·VWAP·지지저항 수준을 계산하여 반환.
    """

    @classmethod
    def prepare(
        cls,
        candles: list[dict],   # [{"o","h","l","c","v"}, ...] — generate_ohlcv() 호환
        symbol: str = "",
    ) -> ChartData:
        """OHLCV dict 리스트 → ChartData 변환.

        Args:
            candles: generate_ohlcv() 반환 dict 리스트 (시간 순, 호출자가 봉 수 지정)
            symbol:  표시 심볼명
        """
        if not candles:
            return ChartData([], [], [], [], None, None, symbol=symbol)

        chart_candles = [
            ChartCandle(
                o=c["o"], h=c["h"], l=c["l"], c=c["c"], v=c.get("v", 0.0),
                is_bullish=(c["c"] >= c["o"]),
            )
            for c in candles
        ]

        closes = [c["c"] for c in candles]
        ema20  = cls._ema(closes, 20)
        ema50  = cls._ema(closes, 50)
        vwap   = cls._vwap(candles)

        lookback      = candles[-20:]
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
