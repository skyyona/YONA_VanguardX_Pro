"""
tests/middle/test_stochrsi.py
StochRSI 단위 테스트.
"""
from middle.col2_chart_indicators.mtf_stochrsi import StochRSI, StochRSIResult
from middle.models import OHLCVBar

# 기본 파라미터 기준 최소 필요 봉 수: 14+14+3+3+2 = 36
_MIN = StochRSI.RSI_PERIOD + StochRSI.STOCH_PERIOD + StochRSI.SMOOTH_K + StochRSI.SMOOTH_D + 2


def _bar(close: float, i: int = 0) -> OHLCVBar:
    return OHLCVBar(
        open_time=i, open=close, high=close, low=close,
        close=close, volume=1.0, quote_volume=close, close_time=i + 1,
    )


def _bars(closes: list) -> list:
    return [_bar(c, i) for i, c in enumerate(closes)]


_DEFAULT = StochRSIResult(50.0, 50.0, "↔")


class TestStochRSICalculateFallback:
    def test_empty_bars_returns_default(self):
        assert StochRSI.calculate([]) == _DEFAULT

    def test_one_less_than_min_returns_default(self):
        assert StochRSI.calculate(_bars([100.0] * (_MIN - 1))) == _DEFAULT

    def test_exactly_min_minus_one_returns_default(self):
        closes = [float(i) for i in range(1, _MIN)]
        assert StochRSI.calculate(_bars(closes)) == _DEFAULT


class TestStochRSICalculateOutput:
    def test_kd_in_valid_range(self):
        """충분한 봉에서 K·D 가 [0, 100] 범위 내."""
        closes = [float(i) for i in range(1, _MIN + 20)]
        result = StochRSI.calculate(_bars(closes))
        assert 0.0 <= result.k <= 100.0
        assert 0.0 <= result.d <= 100.0

    def test_direction_is_valid_string(self):
        closes = [float(i) for i in range(1, _MIN + 20)]
        result = StochRSI.calculate(_bars(closes))
        assert result.direction in ("▲", "▼", "↔")

    def test_direction_consistent_with_kd(self):
        """direction = _classify(K, D) — K·D 차이 2 미만이면 ↔."""
        closes = [float(i) for i in range(1, _MIN + 20)]
        result = StochRSI.calculate(_bars(closes))
        assert result.direction == StochRSI._classify(result.k, result.d)

    def test_returns_stochrsi_result_type(self):
        closes = [float(i) for i in range(1, _MIN + 5)]
        result = StochRSI.calculate(_bars(closes))
        assert isinstance(result, StochRSIResult)
        assert isinstance(result.k, float)
        assert isinstance(result.d, float)
        assert isinstance(result.direction, str)


class TestStochRSIClassify:
    """_classify — K−D ≥ 2 ▲ / D−K ≥ 2 ▼ / 그 외 ↔ (엔진 G7.5·백테스트 G6 교차 추적과 같은 정의)."""

    def test_spread_at_least_2_up(self):
        assert StochRSI._classify(k=52.0, d=50.0) == "▲"

    def test_spread_at_least_2_down(self):
        assert StochRSI._classify(k=50.0, d=52.0) == "▼"

    def test_spread_below_2_neutral(self):
        assert StochRSI._classify(k=51.9, d=50.0) == "↔"
        assert StochRSI._classify(k=50.0, d=51.9) == "↔"
        assert StochRSI._classify(k=50.0, d=50.0) == "↔"

    def test_overbought_oversold_do_not_override(self):
        """과매수에서 K < D(하락 중) → ▼, 과매도에서 K > D(상승 중) → ▲ (기존: 과매수 ▲·과매도 ▼ 우선)."""
        assert StochRSI._classify(k=85.0, d=90.0) == "▼"
        assert StochRSI._classify(k=15.0, d=10.0) == "▲"
        assert StochRSI._classify(k=99.0, d=98.5) == "↔"

    def test_same_threshold_as_backtest(self):
        """MIN_SPREAD = 백테스트 _MIN_SPREAD, 판정이 백테스트 교차 정의(_lo5·_so5)와 일치."""
        from bottom_engine.constants import _MIN_SPREAD
        assert StochRSI.MIN_SPREAD == _MIN_SPREAD
        for k in (0.0, 10.0, 19.9, 20.0, 50.0, 51.99, 52.0, 80.0, 100.0):
            for d in (0.0, 10.0, 18.0, 20.0, 48.0, 50.0, 52.01, 80.0, 100.0):
                lo = k > d and abs(k - d) >= _MIN_SPREAD
                so = k < d and abs(k - d) >= _MIN_SPREAD
                assert StochRSI._classify(k, d) == ("▲" if lo else "▼" if so else "↔"), (k, d)


class TestStochRSICalculateWithSeries:
    def test_too_few_bars_returns_empty_series(self):
        """봉 수 부족 → k_series = []."""
        _, series = StochRSI.calculate_with_series(_bars([100.0] * (_MIN - 1)))
        assert series == []

    def test_enough_bars_returns_nonempty_series(self):
        closes = [float(i) for i in range(1, _MIN + 10)]
        _, series = StochRSI.calculate_with_series(_bars(closes))
        assert len(series) > 0
        assert all(0.0 <= v <= 100.0 for v in series)
