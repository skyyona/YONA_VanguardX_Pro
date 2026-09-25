"""
bottom/long_engine/long_position.py
롱 포지션 관리 — Phase1→2→3 멀티페이즈 청산 전략

Phase1: 초기 SL = entry × (1 − SL%)
Phase2: BEP 이동  — entry + 1R 도달 시 SL = entry (손실 없는 구간)
Phase3: 트레일링  — entry + 1.5R 도달 시 트레일링 SL 활성화
        Phase3 전환 시 trading_engine이 50% 부분 청산을 처리.

R = entry_price × (stop_loss_pct / 100)
"""
from __future__ import annotations

import time as _time

from bottom_engine.models import Position, PositionSide, PositionState, StrategyParams
from bottom_engine.strategy.m4_exit import M4Exit


class LongPosition:
    """롱 포지션 오픈·업데이트·청산."""

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
        sl_price = round(entry_price * (1 - _sl / 100), 8)
        return Position(
            symbol        = symbol,
            side          = PositionSide.LONG,
            state         = PositionState.OPEN,
            entry_price   = entry_price,
            quantity      = quantity,
            leverage      = params.leverage,
            stop_loss_pct = _sl,
            trail_stop_pct= _trail,
            trailing_high = entry_price,
            current_sl    = sl_price,
            phase         = 1,
            partial_closed= False,
            entry_time    = _time.time(),
        )

    @staticmethod
    def update(pos: Position, current_price: float) -> Position:
        """현재가 기준 SL 업데이트 및 Phase 전환.

        Phase1 → Phase2: current_price ≥ entry + R  (BEP 이동)
        Phase2 → Phase3: current_price ≥ entry + 1.5R  (트레일링 활성)

        M4Exit.evaluate()를 사용하여 BT와 동일한 Phase 전환 임계값 유지.
        KD 익절(_sl_loop 담당)·profit_trigger(engine 담당)는 여기서 처리하지 않음.
        """
        if pos.state != PositionState.OPEN:
            return pos

        old_phase = pos.phase
        dec = M4Exit.evaluate(
            side="LONG",
            phase=pos.phase,
            entry_price=pos.entry_price,
            sl_pct=pos.stop_loss_pct,
            trail_pct=pos.trail_stop_pct,
            trail_ref=pos.trailing_high,
            profit_trigger=0.0,   # LIVE: trail 즉시 활성 (_sl_loop이 profit_trigger 관리)
            hi=current_price,
            lo=current_price,
            close=current_price,
            k_prev=0.0,           # LIVE: KD 익절은 _sl_loop에서 직접 처리
            k_cur=0.0,
        )

        # Phase 전환 적용
        if dec.new_phase != pos.phase:
            pos.phase = dec.new_phase

        # SL 갱신 — Phase3는 trail_sl 상승만 허용 (ratchet)
        if dec.new_sl > 0.0:
            if old_phase == 3:
                pos.current_sl = max(pos.current_sl, round(dec.new_sl, 8))
            else:
                pos.current_sl = round(dec.new_sl, 8)

        # trailing_high 갱신 (Phase3 전환 시 또는 Phase3 trail 업데이트)
        if dec.new_trail_ref > 0.0:
            pos.trailing_high = dec.new_trail_ref

        # PnL 계산 (수수료 추정 차감 — close()와 동일 수식)
        if pos.entry_price > 0:
            _gross       = (current_price - pos.entry_price) * pos.quantity
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
            pos.pnl_usdt = (exit_price - pos.entry_price) * pos.quantity - _fee
            _margin = pos.entry_price * pos.quantity / pos.leverage if pos.leverage > 0 else 1
            pos.pnl_pct  = pos.pnl_usdt / _margin * 100
        return pos
