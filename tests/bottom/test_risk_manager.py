"""
tests/bottom/test_risk_manager.py
RiskManager 단위 테스트.
"""
from bottom.engine_core.risk_manager import (
    RiskManager,
    MAX_CONCURRENT_POSITIONS,
    MAX_PORTFOLIO_LOSS_PCT,
    _TAKER_FEE_RATE,
)
from bottom.models import Position, PositionSide, PositionState, StrategyParams


def _idle(side: PositionSide) -> Position:
    return Position(symbol="BTCUSDT", side=side)


def _open(side: PositionSide) -> Position:
    p = Position(symbol="BTCUSDT", side=side)
    p.state      = PositionState.OPEN
    p.entry_price = 50_000.0
    p.quantity    = 0.01
    p.current_sl  = 1.0
    return p


def _params(**kw) -> StrategyParams:
    p = StrategyParams()
    for k, v in kw.items():
        setattr(p, k, v)
    return p


class TestValidateEntry:
    def test_normal_entry_allowed(self):
        result = RiskManager.validate_entry(
            _params(), PositionSide.LONG,
            _idle(PositionSide.LONG), _idle(PositionSide.SHORT),
        )
        assert result.allowed is True

    def test_leverage_zero_rejected(self):
        result = RiskManager.validate_entry(
            _params(leverage=0), PositionSide.LONG,
            _idle(PositionSide.LONG), _idle(PositionSide.SHORT),
        )
        assert result.allowed is False

    def test_leverage_over_125_rejected(self):
        result = RiskManager.validate_entry(
            _params(leverage=126), PositionSide.LONG,
            _idle(PositionSide.LONG), _idle(PositionSide.SHORT),
        )
        assert result.allowed is False

    def test_portfolio_loss_exceeded_rejected(self):
        loss = -(MAX_PORTFOLIO_LOSS_PCT + 1.0)
        result = RiskManager.validate_entry(
            _params(), PositionSide.LONG,
            _idle(PositionSide.LONG), _idle(PositionSide.SHORT),
            current_loss_pct=loss,
        )
        assert result.allowed is False

    def test_one_open_blocks_opposite_entry(self):
        """원웨이 모드: 롱 OPEN → 숏 진입 시도도 동시 한도(1)로 차단."""
        result = RiskManager.validate_entry(
            _params(), PositionSide.SHORT,
            _open(PositionSide.LONG), _idle(PositionSide.SHORT),
        )
        assert result.allowed is False

    def test_one_open_blocks_same_side_entry(self):
        """원웨이 모드: 롱 OPEN → 추가 롱 진입도 동시 한도(1)로 차단."""
        result = RiskManager.validate_entry(
            _params(), PositionSide.LONG,
            _open(PositionSide.LONG), _idle(PositionSide.SHORT),
        )
        assert result.allowed is False

    def test_portfolio_too_small_rejected(self):
        """allocated = 4.0 * 1% = 0.04 USDT < 5 USDT → 거부."""
        result = RiskManager.validate_entry(
            _params(funds_pct=1), PositionSide.LONG,
            _idle(PositionSide.LONG), _idle(PositionSide.SHORT),
            portfolio_usdt=4.0,
        )
        assert result.allowed is False

    def test_portfolio_none_skips_balance_check(self):
        """portfolio_usdt=None → 잔고 검사 SKIP → 레버리지·손실 조건만 확인."""
        result = RiskManager.validate_entry(
            _params(), PositionSide.LONG,
            _idle(PositionSide.LONG), _idle(PositionSide.SHORT),
            portfolio_usdt=None,
        )
        assert result.allowed is True


class TestShouldAutoStop:
    def test_loss_below_threshold_stops(self):
        assert RiskManager.should_auto_stop(-(MAX_PORTFOLIO_LOSS_PCT + 0.1)) is True

    def test_loss_exactly_threshold_does_not_stop(self):
        assert RiskManager.should_auto_stop(-MAX_PORTFOLIO_LOSS_PCT) is False

    def test_no_loss_does_not_stop(self):
        assert RiskManager.should_auto_stop(0.0) is False


class TestCalcPositionSize:
    def test_zero_mark_price_returns_zero(self):
        assert RiskManager.calc_position_size(_params(), 0.0, 1_000.0) == 0.0

    def test_negative_mark_price_returns_zero(self):
        assert RiskManager.calc_position_size(_params(), -1.0, 1_000.0) == 0.0

    def test_fee_deducted_from_notional(self):
        """수수료 공제 공식: (alloc × lev) / (1 + lev × fee) / mark."""
        params = _params(leverage=10, funds_pct=100)
        mark   = 50_000.0
        port   = 1_000.0
        expected = round(
            (port * 1.0 * 10) / (1.0 + 10 * _TAKER_FEE_RATE) / mark, 6
        )
        assert RiskManager.calc_position_size(params, mark, port, qty_precision=6) == expected

    def test_qty_precision_applied(self):
        """qty_precision=2 → 소수점 2자리."""
        params = _params(leverage=10, funds_pct=100)
        result = RiskManager.calc_position_size(params, 50_000.0, 1_000.0, qty_precision=2)
        assert result == round(result, 2)


class TestShouldStopLoss:
    def test_idle_position_returns_false(self):
        pos = _idle(PositionSide.LONG)
        pos.current_sl = 45_000.0
        assert RiskManager.should_stop_loss(pos, 44_000.0) is False

    def test_zero_sl_returns_false(self):
        pos = _open(PositionSide.LONG)
        pos.current_sl = 0.0
        assert RiskManager.should_stop_loss(pos, 44_000.0) is False

    def test_long_price_at_or_below_sl_triggers(self):
        pos = _open(PositionSide.LONG)
        pos.current_sl = 45_000.0
        assert RiskManager.should_stop_loss(pos, 44_999.0) is True
        assert RiskManager.should_stop_loss(pos, 45_000.0) is True  # equal도 손절

    def test_long_price_above_sl_no_trigger(self):
        pos = _open(PositionSide.LONG)
        pos.current_sl = 45_000.0
        assert RiskManager.should_stop_loss(pos, 46_000.0) is False

    def test_short_price_at_or_above_sl_triggers(self):
        pos = _open(PositionSide.SHORT)
        pos.current_sl = 55_000.0
        assert RiskManager.should_stop_loss(pos, 55_001.0) is True
        assert RiskManager.should_stop_loss(pos, 55_000.0) is True  # equal도 손절

    def test_short_price_below_sl_no_trigger(self):
        pos = _open(PositionSide.SHORT)
        pos.current_sl = 55_000.0
        assert RiskManager.should_stop_loss(pos, 54_000.0) is False
