"""
tests/bottom_engine/test_funding_cost.py
BacktestRunner._funding_cost·_cost — 보유 구간 실제 펀딩비 7건.
단위: PnL%와 같은 자본 대비 % (+ = 비용, − = 수령). fr_pct는 rate×100.
"""
import pytest

from bottom_engine.backtest.backtest_runner import BacktestRunner, _FUNDING_BARS, _FUNDING_RATE
from bottom_engine.backtest.historical_data_loader import HistoricalBar

_H = 3_600_000
_E = 0                      # 진입 체결 시각 (ms)


def _bars(prices: dict[int, float]) -> tuple[list[int], list[HistoricalBar]]:
    """시각(ms)→시가 매핑으로 1m 봉 목록 생성 (펀딩 시각 봉만 필요)."""
    bars = [HistoricalBar(t, px, px, px, px, 0.0, t + 59_999) for t, px in sorted(prices.items())]
    return [b.open_time for b in bars], bars


def test_long_pays_positive_short_receives():
    """양(+) 펀딩 0.01% 1회, 가격 불변, 레버리지 10 → 롱 +0.1, 숏 −0.1."""
    o, b = _bars({8 * _H: 100.0})
    fr_t, fr_p = [8 * _H], [0.01]
    assert BacktestRunner._funding_cost(10, "long", _E, 9 * _H, 100.0, fr_t, fr_p, o, b) == pytest.approx(0.1)
    assert BacktestRunner._funding_cost(10, "short", _E, 9 * _H, 100.0, fr_t, fr_p, o, b) == pytest.approx(-0.1)


def test_negative_rate_reverses_direction():
    """음(−) 펀딩 → 롱 수령(−), 숏 지불(+)."""
    o, b = _bars({8 * _H: 100.0})
    assert BacktestRunner._funding_cost(10, "long", _E, 9 * _H, 100.0, [8 * _H], [-0.02], o, b) == pytest.approx(-0.2)
    assert BacktestRunner._funding_cost(10, "short", _E, 9 * _H, 100.0, [8 * _H], [-0.02], o, b) == pytest.approx(0.2)


def test_only_fundings_inside_holding_window_count():
    """entry_fill < fundingTime ≤ exit 만 포함 — 진입 시각 펀딩 제외, 청산 시각 펀딩 포함."""
    o, b = _bars({0: 100.0, 8 * _H: 100.0, 16 * _H: 100.0, 24 * _H: 100.0})
    fr_t, fr_p = [0, 8 * _H, 16 * _H, 24 * _H], [0.01, 0.01, 0.01, 0.01]
    assert BacktestRunner._funding_cost(1, "long", 0, 16 * _H, 100.0, fr_t, fr_p, o, b) == pytest.approx(0.02)


def test_price_ratio_scales_notional():
    """펀딩 시각 가격이 진입가의 1.1배 → 펀딩도 1.1배."""
    o, b = _bars({8 * _H: 110.0})
    assert BacktestRunner._funding_cost(10, "long", _E, 9 * _H, 100.0, [8 * _H], [0.01], o, b) == pytest.approx(0.11)


def test_no_funding_inside_window_is_zero():
    """보유 구간에 펀딩 없음 → 0."""
    o, b = _bars({8 * _H: 100.0})
    assert BacktestRunner._funding_cost(10, "long", _E, 7 * _H, 100.0, [8 * _H], [0.01], o, b) == 0.0


def test_no_records_falls_back_to_previous_fixed_estimate():
    """펀딩 기록 없음 → 기존 고정 추정치와 동일 (bars_held = 보유 1m 봉 수)."""
    bars_held = 1000
    got = BacktestRunner._funding_cost(20, "short", _E, _E + bars_held * 60_000, 100.0, [], [], [], [])
    assert got == pytest.approx(20 * _FUNDING_RATE * (bars_held / _FUNDING_BARS) * 100)


def test_cost_adds_round_trip_fee_and_slippage():
    """_cost = 왕복 수수료·슬리피지 + 펀딩 (펀딩 0이면 왕복 비용만)."""
    base = BacktestRunner._cost(20, 0.0)
    assert BacktestRunner._cost(20, 0.37) == pytest.approx(base + 0.37)
    assert BacktestRunner._cost(20, -0.5) == pytest.approx(base - 0.5)
