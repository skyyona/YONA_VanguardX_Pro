"""
middle/col3_analysis_panels/technical_analysis/vss.py
VSS — Volume Surge Score
현재 캔들 거래량 / 과거 N봉 평균 거래량 비율
Sharp rise·decline 스코어링 및 기술분석 패널에 사용
"""
from __future__ import annotations

from middle.models import OHLCVBar
from middle.widget.constants import ORANGE as _ORA, YELLOW as _YEL, DIM_TEXT as _DIM


class VSS:
    """Volume Surge Score 계산기.

    VSS = current_quote_vol / avg_quote_vol(N봉)
    1.0 = 평균 수준, 1.5 = 평균의 150%, 2.0 = 두 배
    """

    DEFAULT_PERIOD = 20   # 평균 계산 기준 봉 수

    @classmethod
    def calculate(cls, bars: list[OHLCVBar], period: int = DEFAULT_PERIOD) -> float:
        """VSS 반환. 데이터 부족 시 1.0 반환.

        bars: 시간 순 OHLCV 리스트 (최소 period+1개 권장)
        """
        if len(bars) < 2:
            return 1.0

        # 현재 봉 (마지막)
        current_vol = bars[-1].quote_volume
        if current_vol <= 0:
            return 1.0

        # 직전 N봉 평균 (현재 봉 제외)
        lookback = bars[-(period + 1):-1] if len(bars) >= period + 1 else bars[:-1]
        avg_vols = [b.quote_volume for b in lookback if b.quote_volume > 0]

        if not avg_vols:
            return 1.0

        avg = sum(avg_vols) / len(avg_vols)
        if avg <= 0:
            return 1.0

        return round(current_vol / avg, 4)

    @staticmethod
    def label(v: float) -> str:
        return "(High Vol)" if v > 1.8 else ("(Normal)" if v >= 1.0 else "(Low Vol)")

    @staticmethod
    def color(v: float) -> str:
        return _ORA if v > 1.8 else (_YEL if v > 1.0 else _DIM)

