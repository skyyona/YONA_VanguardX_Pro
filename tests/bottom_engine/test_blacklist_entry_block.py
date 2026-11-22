"""
tests/bottom_engine/test_blacklist_entry_block.py
엔진 신호 루프의 블랙리스트 신규 진입 차단 (2026-11-22 — 안전 경로 테스트 공백 보완, 엔진 코드 무수정)
 블랙리스트 종목 → 진입 판단(롱·숏 G 필터 평가) 블록에 들어가지 않고, 진입 함수 미호출, 차단 사유 기록
 대조군(블랙리스트 아님) → 같은 조건에서 진입 판단 블록에 들어감 — 위 결과가 우연이 아님을 확인
신호 루프 1회만 실행: 정지 신호·봉 대기·지표 조회만 대역 (네트워크·주문 없음).
"""
import threading
import types

import bottom_engine.engine_core.trading_engine as _te_mod
from bottom_engine.engine_core.trading_engine import EngineState, TradingEngine


class _OneLoop:
    """while 조건 1회만 통과 · 봉 마감 대기는 즉시 진행."""

    def __init__(self):
        self.checks = 0

    def is_set(self):
        self.checks += 1
        return self.checks > 1

    def wait(self, _timeout=None):
        return False


class _TrackedInd(dict):
    """진입 판단 블록 첫 줄(ind.get('_days_listed'))에 도달했는지 기록."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.keys_read = []

    def get(self, key, default=None):
        self.keys_read.append(key)
        return super().get(key, default)


def _run_one_cycle(monkeypatch, blacklisted: bool):
    eng = TradingEngine.__new__(TradingEngine)
    eng._lock = threading.Lock()
    eng._state = EngineState(running=True, symbol="ABCUSDT")
    eng._client = types.SimpleNamespace(_time_offset=0.0)
    eng._sel_refresher = None
    eng._stop_event = _OneLoop()
    eng._wait_bar_close = lambda sym, boundary_ms: True
    ind = _TrackedInd(_data_ready=True)
    eng._get_ind_data = lambda: ind
    entered = []
    eng._enter_long = lambda mark, ind=None: entered.append("long") or True
    eng._enter_short = lambda mark, ind=None: entered.append("short") or True
    monkeypatch.setattr(_te_mod, "_is_blacklisted", lambda s: blacklisted and s == "ABCUSDT")
    monkeypatch.setattr(_te_mod, "_blacklist_problem", lambda: "")
    eng._signal_loop()
    return eng, ind, entered


def test_blacklisted_symbol_blocks_new_entry(monkeypatch):
    eng, ind, entered = _run_one_cycle(monkeypatch, blacklisted=True)
    assert "_days_listed" not in ind.keys_read                       # 진입 판단 블록 미진입
    assert entered == []                                             # 롱·숏 진입 함수 미호출
    assert eng._state.last_blocked_reason == "ABCUSDT 블랙리스트 등록 — 신규 진입 차단 (보유 포지션은 유지)"
    assert eng._state.last_blocked_side == "" and eng._state.running is True   # 엔진은 계속 동작 (정지 아님)


def test_not_blacklisted_reaches_entry_evaluation(monkeypatch):
    """대조군 — 블랙리스트가 아니면 같은 조건에서 진입 판단 블록에 들어간다."""
    eng, ind, _ = _run_one_cycle(monkeypatch, blacklisted=False)
    assert "_days_listed" in ind.keys_read
    assert "블랙리스트" not in eng._state.last_blocked_reason
