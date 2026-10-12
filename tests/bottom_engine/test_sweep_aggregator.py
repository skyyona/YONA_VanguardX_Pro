"""
tests/bottom_engine/test_sweep_aggregator.py
SweepBucket 집계 정의 회귀 테스트.

핵심 불변식 2개:
  ① qty_ratio 를 pnl_pct 에 재적용하지 않는다 (models.py:156 계약)
  ② EV 는 1R = sl_used × L_eff 로 나눈다 (sl_used 단독이 아니다)
"""
from __future__ import annotations

import pytest

from bottom_engine.models import BacktestResult, BacktestTrade
from bottom_engine.sweep import SweepBucket, assert_sl_is_one_r

SL_USED = 4.0
L_EFF   = 2.0
ONE_R   = SL_USED * L_EFF          # = 8.0%


def _trade(pnl_pct: float, reason: str, qty_ratio: float = 1.0) -> BacktestTrade:
    return BacktestTrade(
        entry_time=0, exit_time=1, side="long",
        entry_price=100.0, exit_price=100.0,
        pnl_pct=pnl_pct, pnl_usdt=0.0,
        exit_reason=reason, qty_ratio=qty_ratio,
    )


def _result(trades: list[BacktestTrade]) -> BacktestResult:
    r = BacktestResult(symbol="TESTUSDT", sort_mode="24h Ticker",
                       period_days=90, trades=trades)
    r.l_eff     = L_EFF
    r.one_r_pct = ONE_R
    return r


class TestSweepBucket:
    def test_full_exit_sl_is_minus_one_r(self):
        """SL 청산 = -1R (비용 제외 시)."""
        b = SweepBucket()
        b.add(_result([_trade(-ONE_R, "SL", 1.0)]))
        s = b.summary()
        assert s["n"] == pytest.approx(1.0)
        assert s["ev_r"] == pytest.approx(-1.0)

    def test_qty_ratio_not_reapplied(self):
        """pnl_pct 는 이미 qty_ratio 가 적용된 값 — 재적용하면 안 된다.

        PARTIAL: 1.5R 지점에서 50% 청산 → pnl_pct = 1.5 × ONE_R × 0.5 = 6.0
        기대 R 기여 = 6.0 / 8.0 = 0.75,  n 기여 = 0.5
        → EV = 0.75 / 0.5 = 1.5R
        (재적용 버그가 있으면 EV = 0.375/0.5 = 0.75R 로 절반이 된다)
        """
        b = SweepBucket()
        b.add(_result([_trade(6.0, "PARTIAL", 0.5)]))
        s = b.summary()
        assert s["n"] == pytest.approx(0.5)
        assert s["ev_r"] == pytest.approx(1.5)

    def test_one_entry_split_into_two_records(self):
        """PARTIAL(0.5) + TRAIL(0.5) = 진입 1건.

        pnl_pct 합 = 6.0 + 4.0 = 10.0  →  10.0 / (8.0 × 1.0) = 1.25R
        """
        b = SweepBucket()
        b.add(_result([_trade(6.0, "PARTIAL", 0.5),
                       _trade(4.0, "TRAIL",   0.5)]))
        s = b.summary()
        assert s["n"] == pytest.approx(1.0)
        assert s["ev_r"] == pytest.approx(1.25)

    def test_pf_no_weight_reapplication(self):
        """PF = Σpnl⁺ / Σ|pnl⁻| — qty_ratio 가중 없음."""
        b = SweepBucket()
        b.add(_result([_trade(6.0, "PARTIAL", 0.5),
                       _trade(-8.0, "SL",     1.0)]))
        s = b.summary()
        assert s["pf"] == pytest.approx(6.0 / 8.0)

    def test_win_rate_is_qty_ratio_weighted(self):
        """WR 은 qty_ratio 가중 (건수 가중이므로 올바름)."""
        b = SweepBucket()
        b.add(_result([_trade(6.0, "PARTIAL", 0.5),
                       _trade(-8.0, "SL",     1.0)]))
        s = b.summary()
        assert s["n"] == pytest.approx(1.5)
        assert s["wr"] == pytest.approx(0.5 / 1.5 * 100.0)

    def test_skips_result_without_one_r(self):
        """one_r_pct == 0.0 (데이터 부족 조기 반환) 은 건너뛴다."""
        b = SweepBucket()
        empty = BacktestResult(symbol="X", sort_mode="24h Ticker", period_days=90)
        b.add(empty)
        assert b.summary()["n"] == pytest.approx(0.0)

    def test_raises_on_one_r_mismatch(self):
        """셀 내 1R 이 다르면 집계 거부."""
        b = SweepBucket()
        b.add(_result([_trade(-8.0, "SL", 1.0)]))
        other = _result([_trade(-4.0, "SL", 1.0)])
        other.one_r_pct = 4.0
        with pytest.raises(ValueError):
            b.add(other)

    def test_zero_trades_returns_zeros(self):
        b = SweepBucket()
        b.add(_result([]))
        s = b.summary()
        assert s["n"] == pytest.approx(0.0)
        assert s["ev_r"] == pytest.approx(0.0)


class TestAssertSlIsOneR:
    def test_passes_with_cost(self):
        """실제 SL 청산은 -(1 + 0.1/sl_used) = -1.025R."""
        r = _result([_trade(-ONE_R * (1.0 + 0.1 / SL_USED), "SL", 1.0)])
        ok, msg = assert_sl_is_one_r(r)
        assert ok, msg

    def test_detects_missing_leff(self):
        """L_eff 누락 시 SL 이 -2.05R 로 나타나며 검출되어야 한다."""
        r = _result([_trade(-ONE_R * (1.0 + 0.1 / SL_USED), "SL", 1.0)])
        r.one_r_pct = SL_USED          # ← L_eff 누락 재현
        ok, msg = assert_sl_is_one_r(r)
        assert not ok, msg
