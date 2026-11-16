"""
tests/header/test_balance_interval.py
헤더 선물 잔고 조회 주기 (2026-11-16) — 시계·세션 표시는 1초마다 그대로, 잔고(/fapi/v2/account 가중치 5)만 5초마다.
START·이체 완료 직후는 즉시 조회. 네트워크·Tk 창 없이 대역.
"""
import types

import header.widget.header_panel as hp
from core.config import HEADER_BALANCE_INTERVAL_SEC, HEADER_UPDATE_INTERVAL_SEC
from header.models import HeaderStatus, WalletBalanceResult, WalletQueryStatus
from header.status.app_status import AppStatus


def _panel(monkeypatch, status=WalletQueryStatus.OK):
    now = [1000.0]
    monkeypatch.setattr(hp.time, "monotonic", lambda: now[0])
    p = hp.HeaderPanel.__new__(hp.HeaderPanel)
    p._status = AppStatus()
    p._bal_ts = float("-inf")
    p._last_wallet_status = WalletQueryStatus.OK
    calls, renders = [], []
    p._client = types.SimpleNamespace(
        fetch_futures_total_balance_with_status=lambda: calls.append(now[0]) or WalletBalanceResult(status, 123.0))
    p._total_val = types.SimpleNamespace(update=lambda v: None)
    p._build_state = lambda: "state"
    p._root = types.SimpleNamespace(after=lambda ms, f: renders.append(now[0]))
    return p, now, calls, renders


def test_intervals():
    assert HEADER_UPDATE_INTERVAL_SEC == 1 and HEADER_BALANCE_INTERVAL_SEC == 5


def test_balance_every_5s_while_clock_renders_every_tick(monkeypatch):
    p, now, calls, renders = _panel(monkeypatch)
    p._status.set_running()
    for i in range(12):                       # 1초 간격 12회
        now[0] = 1000.0 + i
        p._tick()
    assert calls == [1000.0, 1005.0, 1010.0]  # 잔고: 5초마다 (기존: 12회)
    assert len(renders) == 12                 # 시계·세션 표시: 매 회


def test_force_on_start_and_transfer_done(monkeypatch):
    p, now, calls, _ = _panel(monkeypatch)
    p._status.set_running()
    p._tick()
    now[0] += 1
    p._tick(force=True)                       # START·이체 완료 직후 — 즉시 조회
    now[0] += 1
    p._tick()                                 # 그 뒤 5초 지나기 전 — 생략
    assert calls == [1000.0, 1001.0]


def test_idle_never_fetches_and_error_retries_every_5s(monkeypatch):
    p, now, calls, _ = _panel(monkeypatch, status=WalletQueryStatus.COMM_ERROR)
    for i in range(6):
        now[0] = 1000.0 + i
        p._tick()
    assert calls == []                        # IDLE: 조회 없음 (기존과 같음)
    p._status.set_running()
    for i in range(6, 17):
        now[0] = 1000.0 + i
        p._tick()
    assert p._status.get() == HeaderStatus.ERROR
    assert calls == [1006.0, 1011.0, 1016.0]  # 통신 오류 중 재시도도 5초마다


def test_start_and_transfer_use_force(monkeypatch):
    seen = []

    class _T:
        def __init__(self, target=None, kwargs=None, daemon=None):
            seen.append(kwargs)

        def start(self):
            pass
    monkeypatch.setattr(hp.threading, "Thread", _T)
    p, *_ = _panel(monkeypatch)
    p.start()
    p.on_transfer_done()
    assert seen == [{"force": True}, {"force": True}]
