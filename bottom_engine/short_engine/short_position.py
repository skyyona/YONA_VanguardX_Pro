"""
bottom/short_engine/short_position.py
숏 포지션 관리 — Phase1→2→3 멀티페이즈 청산 전략

Phase1: 초기 SL = entry × (1 + SL%)
Phase2: BEP 이동  — entry − 1R 도달 시 SL = entry (손실 없는 구간)
Phase3: 트레일링  — entry − 1.5R 도달 시 트레일링 SL 활성화
        Phase3 전환 시 trading_engine이 50% 부분 청산을 처리.

R = entry_price × (stop_loss_pct / 100)
"""
from __future__ import annotations

import time as _time

from bottom_engine.models import Position, PositionSide, PositionState, StrategyParams


class ShortPosition:
    """숏 포지션 오픈·업데이트·청산."""

    @staticmethod
    def open(
        symbol:      str,
        entry_price: float,
        quantity:    float,
        params:      StrategyParams,
        *,
        sl_pct:    float | None = None,
        trail_pct: float | None = None,
    ) -> Position:
        _sl    = sl_pct    if sl_pct    is not None else params.stop_loss
        _trail = trail_pct if trail_pct is not None else params.trail_stop
        sl_price = round(entry_price * (1 + _sl / 100), 8)
        return Position(
            symbol        = symbol,
            side          = PositionSide.SHORT,
            state         = PositionState.OPEN,
            entry_price   = entry_price,
            quantity      = quantity,
            leverage      = params.leverage,
            stop_loss_pct = _sl,
            trail_stop_pct= _trail,
            trailing_low  = entry_price,
            current_sl    = sl_price,
            phase         = 1,
            partial_closed= False,
            entry_time    = _time.time(),
        )

    @staticmethod
    def update(pos: Position, current_price: float) -> Position:
        """현재가 기준 SL 업데이트 및 Phase 전환.

        Phase1 → Phase2: current_price ≤ entry − R  (BEP 이동)
        Phase2 → Phase3: current_price ≤ entry − 1.5R  (트레일링 활성)
        """
        if pos.state != PositionState.OPEN:
            return pos

        R = pos.entry_price * pos.stop_loss_pct / 100.0

        if pos.phase == 1:
            # Phase1: SL 고정 (초기 SL)
            pos.current_sl = round(pos.entry_price * (1 + pos.stop_loss_pct / 100), 8)
            if R > 0 and current_price <= pos.entry_price - R:
                pos.phase     = 2
                pos.current_sl = pos.entry_price   # BEP로 즉시 이동

        elif pos.phase == 2:
            # Phase2: SL = entry (BEP 유지)
            pos.current_sl = pos.entry_price
            if R > 0 and current_price <= pos.entry_price - R * 1.5:
                pos.phase        = 3
                pos.trailing_low = current_price   # 트레일링 기준점 설정

        elif pos.phase == 3:
            # Phase3: 트레일링 SL (trailing_low 추적)
            if pos.trailing_low > 0:
                pos.trailing_low = min(pos.trailing_low, current_price)
            else:
                pos.trailing_low = current_price
            trail_sl = pos.trailing_low * (1 + pos.trail_stop_pct / 100)
            prev_sl  = pos.current_sl if pos.current_sl > 0 else trail_sl
            pos.current_sl = min(prev_sl, round(trail_sl, 8))

        # PnL 계산 (수수료 추정 차감 — close()와 동일 수식)
        if pos.entry_price > 0:
            _gross       = (pos.entry_price - current_price) * pos.quantity
            _est_fee     = (pos.entry_price + current_price) * pos.quantity * 0.0004
            pos.pnl_usdt = _gross - _est_fee
            _margin      = pos.entry_price * pos.quantity / pos.leverage if pos.leverage > 0 else 1
            pos.pnl_pct  = pos.pnl_usdt / _margin * 100

        return pos

    @staticmethod
    def close(pos: Position, exit_price: float = 0.0, exit_reason: str = "") -> Position:
        pos.state       = PositionState.CLOSED
        pos.exit_price  = exit_price
        pos.exit_reason = exit_reason
        pos.exit_time   = _time.time()
        _TAKER_FEE = 0.0004
        if exit_price > 0 and pos.entry_price > 0:
            _fee = (pos.entry_price + exit_price) * pos.quantity * _TAKER_FEE
            pos.pnl_usdt = (pos.entry_price - exit_price) * pos.quantity - _fee
            _margin = pos.entry_price * pos.quantity / pos.leverage if pos.leverage > 0 else 1
            pos.pnl_pct  = pos.pnl_usdt / _margin * 100
        return pos
