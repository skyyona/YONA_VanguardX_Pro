"""
bottom/engine_core/risk_manager.py
통합 리스크 관리 — 손실 한도·레버리지·동시 포지션 검증
진입 전 최종 안전 체크포인트
"""
from __future__ import annotations

from bottom.models import (
    Position, PositionSide, PositionState, RiskCheckResult, StrategyParams
)

# 포트폴리오 대비 최대 손실 한도 — 세션 기준, R=8%×3연패=-22.1% 허용 (%)
MAX_PORTFOLIO_LOSS_PCT = 30.0
# KST 자정 기준 일일 최대 실현 손실 한도 — 재시작 내성 (DailyLossTracker 연동) (%)
MAX_DAILY_LOSS_PCT = 20.0
# 단일 거래 최대 손실 비율 — SL 도달 시 손실이 이 값 초과 시 수량 상한 조정 (%)
_MAX_R_PCT = 8.0
# 엔진 레이어 하드 리밋: Binance Futures 절대 상한(125x). UI(AppliedLeverage: 1~20x)와 역할 다름.
# UI를 우회하는 비정상 경로에 대한 최후 백스탑.
MAX_LEVERAGE = 125
# 동시 허용 포지션 수 (롱 + 숏 합계)
# 원웨이(One-way) 모드 강제 환경: 반대 방향 주문은 신규가 아니라 기존 포지션 상계(netting).
# 2로 두면 앱 상태와 Binance 실제 포지션이 영구적으로 어긋난다.
MAX_CONCURRENT_POSITIONS = 1
# Binance Futures 테이커 수수료율 — 증거금+수수료 합산이 잔고 초과하는 -2019 방지
_TAKER_FEE_RATE = 0.0004


class RiskManager:
    """진입 전 리스크 검증기."""

    @classmethod
    def validate_entry(
        cls,
        params:       StrategyParams,
        side:         PositionSide,
        long_pos:     Position,
        short_pos:    Position,
        portfolio_usdt: float | None = None,
        current_loss_pct: float = 0.0,
    ) -> RiskCheckResult:
        """진입 가능 여부 검증 — 모든 조건 통과 시 allowed=True."""

        # ① 레버리지 한도 (하한 1x ~ 상한 125x)
        if not (1 <= params.leverage <= MAX_LEVERAGE):
            return RiskCheckResult(False,
                f"레버리지 {params.leverage}x — 유효 범위 1~{MAX_LEVERAGE}x")

        # ② 포트폴리오 최대 손실 한도
        if current_loss_pct < -MAX_PORTFOLIO_LOSS_PCT:
            return RiskCheckResult(False,
                f"포트폴리오 손실 {current_loss_pct:.1f}% — 한도 -{MAX_PORTFOLIO_LOSS_PCT}% 초과")

        # ③ 동시 포지션 한도
        open_count = (
            (1 if long_pos.state  == PositionState.OPEN else 0) +
            (1 if short_pos.state == PositionState.OPEN else 0)
        )
        if open_count >= MAX_CONCURRENT_POSITIONS:
            return RiskCheckResult(False,
                f"동시 포지션 {open_count}개 — 한도 {MAX_CONCURRENT_POSITIONS}개 초과")

        # ④ 동일 방향 포지션 중복 금지
        if side == PositionSide.LONG and long_pos.state == PositionState.OPEN:
            return RiskCheckResult(False, "롱 포지션 이미 보유 중 — 추가 롱 진입 불가")
        if side == PositionSide.SHORT and short_pos.state == PositionState.OPEN:
            return RiskCheckResult(False, "숏 포지션 이미 보유 중 — 추가 숏 진입 불가")

        # ⑤ 운용 자금 유효성 (None: 잔고 미전달 → SKIP / 0.0 포함 수치 전달 시 체크)
        if portfolio_usdt is not None:
            allocated = portfolio_usdt * params.funds_pct / 100.0
            if allocated < 5.0:
                return RiskCheckResult(False,
                    f"운용 자금 {allocated:.2f} USDT — 최소 5 USDT 미만")

        return RiskCheckResult(True)

    @classmethod
    def should_auto_stop(cls, current_loss_pct: float) -> bool:
        """세션 포트폴리오 손실 한도 초과 시 엔진 자동 정지 여부."""
        return current_loss_pct < -MAX_PORTFOLIO_LOSS_PCT

    @classmethod
    def should_daily_stop(cls, daily_loss_pct: float) -> bool:
        """KST 일일 실현 손실 한도 초과 시 엔진 자동 정지 여부."""
        return daily_loss_pct < -MAX_DAILY_LOSS_PCT

    @classmethod
    def calc_position_size(
        cls,
        params:        StrategyParams,
        mark_price:    float,
        portfolio_usdt: float,
        qty_precision:  int = 6,
    ) -> float:
        """포지션 수량(코인 수) 계산.
        수량 = (포트폴리오 × funds% × leverage) / (1 + leverage × fee) / 마크가격
        fee 나누기: 증거금 + 테이커수수료 합산이 할당자금 초과하지 않도록 사전 공제
        qty_precision: 심볼 LOT_SIZE stepSize 기반 소수 자릿수 (기본 6)
        """
        if mark_price <= 0:
            return 0.0
        allocated    = portfolio_usdt * params.funds_pct / 100.0
        gross_notional = allocated * params.leverage
        fee_divisor  = 1.0 + params.leverage * _TAKER_FEE_RATE
        net_notional = gross_notional / fee_divisor
        return round(net_notional / mark_price, qty_precision)

    @classmethod
    def apply_r_cap(
        cls,
        qty:            float,
        mark_price:     float,
        sl_pct:         float,
        portfolio_usdt: float,
        max_r_pct:      float = _MAX_R_PCT,
    ) -> float:
        """SL 도달 시 손실 ≤ portfolio × max_r_pct% 를 보장하도록 수량 상한 조정.

        sl_pct · mark_price · portfolio_usdt 중 하나라도 0 이하면 qty 원본 반환.
        수량 단위 반올림은 호출부(floor_qty)가 담당.
        """
        if sl_pct <= 0 or mark_price <= 0 or portfolio_usdt <= 0:
            return qty
        max_loss = portfolio_usdt * max_r_pct / 100.0
        sl_loss  = qty * mark_price * sl_pct / 100.0
        if sl_loss > max_loss:
            return max_loss / (mark_price * sl_pct / 100.0)
        return qty

    @classmethod
    def should_stop_loss(cls, position: Position, current_price: float) -> bool:
        """현재가 기준 SL 도달 여부."""
        if position.state != PositionState.OPEN or position.current_sl <= 0:
            return False
        if position.side == PositionSide.LONG:
            return current_price <= position.current_sl
        else:
            return current_price >= position.current_sl

