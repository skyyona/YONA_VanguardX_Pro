"""
tests/bottom_engine/test_position_slippage.py
LongPosition/ShortPosition.close — 청산 기준가·청산 슬리피지 기록 6건.
부호: + = 불리 (롱은 기준가보다 낮게 매도, 숏은 기준가보다 높게 매수).
"""
import pytest

from bottom_engine.long_engine.long_position import LongPosition
from bottom_engine.models import Position, PositionSide, PositionState
from bottom_engine.short_engine.short_position import ShortPosition


def _open(side: PositionSide) -> Position:
    return Position(symbol="BTCUSDT", side=side, state=PositionState.OPEN,
                    entry_price=100.0, quantity=1.0, leverage=10)


def test_long_exit_below_trigger_is_adverse():
    """롱 SL 기준가 100, 체결 99 → +1% (불리)."""
    p = LongPosition.close(_open(PositionSide.LONG), exit_price=99.0,
                           exit_reason="SL", trigger_price=100.0)
    assert p.exit_trigger_price == 100.0
    assert p.exit_slip_pct == pytest.approx(1.0)


def test_long_exit_above_trigger_is_favourable():
    """롱 기준가 100, 체결 100.5 → -0.5% (유리)."""
    p = LongPosition.close(_open(PositionSide.LONG), exit_price=100.5,
                           exit_reason="KD-EXIT", trigger_price=100.0)
    assert p.exit_slip_pct == pytest.approx(-0.5)


def test_short_exit_above_trigger_is_adverse():
    """숏 SL 기준가 100, 체결 101 → +1% (불리)."""
    p = ShortPosition.close(_open(PositionSide.SHORT), exit_price=101.0,
                            exit_reason="SL", trigger_price=100.0)
    assert p.exit_trigger_price == 100.0
    assert p.exit_slip_pct == pytest.approx(1.0)


def test_short_exit_below_trigger_is_favourable():
    """숏 기준가 100, 체결 99.8 → -0.2% (유리)."""
    p = ShortPosition.close(_open(PositionSide.SHORT), exit_price=99.8,
                            exit_reason="KD-EXIT", trigger_price=100.0)
    assert p.exit_slip_pct == pytest.approx(-0.2)


def test_unknown_trigger_records_none():
    """기준가 미상(0) → 슬리피지 None (0으로 기록하지 않음), PnL 계산은 기존과 동일."""
    p = LongPosition.close(_open(PositionSide.LONG), exit_price=99.0, exit_reason="LIQD")
    assert p.exit_trigger_price == 0.0
    assert p.exit_slip_pct is None
    assert p.pnl_usdt == pytest.approx((99.0 - 100.0) * 1.0 - (100.0 + 99.0) * 1.0 * 0.0004)


def test_new_position_slip_defaults():
    """신규·복구 포지션 기본값: signal_mark 0.0, 슬리피지 None."""
    p = _open(PositionSide.SHORT)
    assert p.signal_mark == 0.0
    assert p.entry_slip_pct is None
    assert p.exit_trigger_price == 0.0
    assert p.exit_slip_pct is None
