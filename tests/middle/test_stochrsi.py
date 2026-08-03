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
        """direction 값이 _classify 로직과 일치한다 (K>D → ▲ 포함)."""
        closes = [float(i) for i in range(1, _MIN + 20)]
        result = StochRSI.calculate(_bars(closes))
        if result.k == result.d:
            # K==D → "↔" 또는 과매수·과매도 여부에 따라 다름
            assert result.direction in ("▲", "▼", "↔")
        # K>D이면 "↔"가 아닐 수 있지만 "▼"는 아님
        if result.k > result.d:
            assert result.direction != "▼"
        if result.k < result.d:
            assert result.direction != "▲"

    def test_returns_stochrsi_result_type(self):
        closes = [float(i) for i in range(1, _MIN + 5)]
        result = StochRSI.calculate(_bars(closes))
        assert isinstance(result, StochRSIResult)
        assert isinstance(result.k, float)
        assert isinstance(result.d, float)
        assert isinstance(result.direction, str)


class TestStochRSIClassify:
    """_classify 내부 로직 직접 검증."""

    def test_golden_cross_returns_up(self):
        """prev_k ≤ prev_d 이고 k > d → 골든크로스 → '▲'."""
        assert StochRSI._classify(k=51.0, d=49.0, prev_k=48.0, prev_d=50.0) == "▲"

    def test_dead_cross_returns_down(self):
        """prev_k ≥ prev_d 이고 k < d → 데드크로스 → '▼'."""
        assert StochRSI._classify(k=49.0, d=51.0, prev_k=52.0, prev_d=50.0) == "▼"

    def test_overbought_without_cross_returns_up(self):
        """크로스 없고 K ≥ 80(과매수) → '▲'."""
        assert StochRSI._classify(k=85.0, d=82.0, prev_k=84.0, prev_d=81.0) == "▲"

    def test_oversold_without_cross_returns_down(self):
        """크로스 없고 K ≤ 20(과매도) → '▼'."""
        assert StochRSI._classify(k=15.0, d=18.0, prev_k=16.0, prev_d=17.0) == "▼"

    def test_kd_equal_returns_neutral(self):
        """K == D, 크로스 없음, 과매수·과매도 아님 → '↔'."""
        assert StochRSI._classify(k=50.0, d=50.0, prev_k=50.0, prev_d=50.0) == "↔"

    def test_k_above_d_mid_range_returns_up(self):
        """크로스 아님, 50 < K > D, 과매수 아님 → '▲'."""
        assert StochRSI._classify(k=60.0, d=55.0, prev_k=61.0, prev_d=54.0) == "▲"


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
