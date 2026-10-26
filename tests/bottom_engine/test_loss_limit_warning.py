"""
tests/bottom_engine/test_loss_limit_warning.py
TradingEngine._warn_loss_limits — 일일(KST)·포트폴리오(start 기준) 손실 한도 초과 시 경고만 표시 6건.
엔진 정지·진입 차단 없음(거래 계속 여부는 사용자 판단) — 백테스트도 차단 없음.
"""
import threading

import pytest

import bottom_engine.engine_core.daily_loss_tracker as _dlt_mod
from bottom_engine.engine_core.daily_loss_tracker import DailyLossTracker
from bottom_engine.engine_core.risk_manager import RiskManager
from bottom_engine.engine_core.trading_engine import EngineState, TradingEngine
from bottom_engine.models import Position, PositionSide, StrategyParams


def _idle(side: PositionSide) -> Position:
    return Position(symbol="BTCUSDT", side=side)


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """data/daily_loss.json 대신 임시 파일 사용."""
    monkeypatch.setattr(_dlt_mod, "_DATA_FILE", str(tmp_path / "daily_loss.json"))
    return tmp_path


def _engine(initial_balance: float, daily_initial: float) -> TradingEngine:
    """경고 판단에 쓰는 상태만 갖춘 엔진 (네트워크·스레드 미사용)."""
    eng = TradingEngine.__new__(TradingEngine)
    eng._lock       = threading.Lock()
    eng._stop_event = threading.Event()
    eng._state      = EngineState(running=True, initial_balance=initial_balance)
    DailyLossTracker._save({"date": DailyLossTracker._today(), "initial_balance": daily_initial})
    return eng


def test_daily_limit_exceeded_warns_without_stopping(isolated):
    """당일 −31% → 일일 경고, 엔진은 계속 실행 (정지 신호 없음)."""
    eng = _engine(initial_balance=690.0, daily_initial=1000.0)
    eng._warn_loss_limits(690.0)
    msg = eng._state.error_msg
    assert msg.startswith("[경고] 일일 손실 한도(-30%) 초과")
    assert "포트폴리오" not in msg
    assert "사용자 판단" in msg
    assert eng._state.running is True
    assert not eng._stop_event.is_set()


def test_portfolio_limit_exceeded_warns_only(isolated):
    """start 기준 −35%, 당일 기준 0% → 포트폴리오 경고만."""
    eng = _engine(initial_balance=1000.0, daily_initial=650.0)
    eng._warn_loss_limits(650.0)
    msg = eng._state.error_msg
    assert msg.startswith("[경고] 포트폴리오 손실 한도(-30%) 초과")
    assert "일일" not in msg
    assert eng._state.running is True
    assert not eng._stop_event.is_set()


def test_both_limits_exceeded_lists_both(isolated):
    """둘 다 초과 → 한 줄에 두 한도 모두 표시."""
    eng = _engine(initial_balance=1000.0, daily_initial=1000.0)
    eng._warn_loss_limits(600.0)
    assert eng._state.error_msg.startswith(
        "[경고] 일일 손실 한도(-30%) · 포트폴리오 손실 한도(-30%) 초과")


def test_within_limits_keeps_existing_message(isolated):
    """한도 이내 → 기존 메시지 유지 (경고로 덮어쓰지 않음)."""
    eng = _engine(initial_balance=1000.0, daily_initial=1000.0)
    eng._state.error_msg = "기존 메시지"
    eng._warn_loss_limits(750.0)
    assert eng._state.error_msg == "기존 메시지"


def test_exactly_at_limit_does_not_warn(isolated):
    """정확히 −30% → 초과 아님 (기존 판정 기준 '<' 유지)."""
    eng = _engine(initial_balance=1000.0, daily_initial=1000.0)
    eng._warn_loss_limits(700.0)
    assert eng._state.error_msg == ""


def test_validate_entry_does_not_block_on_loss():
    """진입 검증은 손실 한도로 차단하지 않음 — 손실 인자 자체가 없음."""
    rr = RiskManager.validate_entry(
        StrategyParams(), PositionSide.LONG,
        _idle(PositionSide.LONG), _idle(PositionSide.SHORT),
        portfolio_usdt=600.0)
    assert rr.allowed is True
