"""
tests/bottom_engine/test_bar_close_wait.py
TradingEngine._wait_bar_close — 경계에 마감되는 TF 봉이 중단 캐시에 반영되면 즉시 판단, WS 미도착 시
4·7초 REST 강제 갱신, 10초 초과 시 건너뜀 5건. 가짜 서버 시계로 실행(실제 대기·네트워크 없음).
"""
import types

from bottom_engine.engine_core import trading_engine as te
from bottom_engine.engine_core.trading_engine import TradingEngine

_B = 1_800_000_000_000 - (1_800_000_000_000 % 86_400_000) + 300_000   # 5m 경계 (3m·15m 경계 아님)


class _Clock:
    """서버 시각(초) — _stop_event.wait(sec) 호출 시 그만큼 진행."""

    def __init__(self, t: float):
        self.t = t

    def wait(self, sec: float) -> bool:
        self.t += sec
        return False


def _engine(clock: _Clock) -> TradingEngine:
    eng = TradingEngine.__new__(TradingEngine)
    eng._stop_event = clock
    eng._client = types.SimpleNamespace(_time_offset=0.0)
    eng._server_now = lambda: clock.t
    return eng


def _probe(monkeypatch, closes: dict, arrive_at: dict | None = None, clock: _Clock | None = None):
    """TF별 캐시 마지막 close_time — arrive_at[tf] 초(서버, 경계 기준) 이후 경계 봉 반영."""
    def get_last_close(sym, tf):
        if arrive_at and tf in arrive_at and clock.t - _B / 1000 >= arrive_at[tf]:
            return _B - 1
        return closes.get(tf, 0)
    monkeypatch.setattr(te, "_get_last_close", get_last_close)
    rest = []
    monkeypatch.setattr(te, "_refresh_detail_now", lambda s: rest.append(round(clock.t - _B / 1000, 1)))
    return rest


def test_returns_immediately_when_all_due_bars_present(monkeypatch):
    """1m·5m 경계 봉 모두 반영 → 대기·REST 없이 True."""
    clock = _Clock(_B / 1000 + 0.05)
    rest = _probe(monkeypatch, {tf: _B - 1 for tf in ("1m", "3m", "5m", "15m", "1h", "4h", "1d")}, clock=clock)
    assert _engine(clock)._wait_bar_close("AUSDT", _B) is True
    assert rest == [] and clock.t == _B / 1000 + 0.05


def test_waits_for_every_due_tf(monkeypatch):
    """1m 먼저 도착해도 5m 경계 봉 반영(0.8초)까지 대기 후 True — 3m·15m(경계 아님)는 대기 대상 아님."""
    clock = _Clock(_B / 1000)
    old = {tf: _B - 300_001 for tf in ("1m", "3m", "5m", "15m", "1h", "4h", "1d")}
    rest = _probe(monkeypatch, old, arrive_at={"1m": 0.3, "5m": 0.8}, clock=clock)
    assert _engine(clock)._wait_bar_close("AUSDT", _B) is True
    assert 0.8 <= clock.t - _B / 1000 < 0.9
    assert rest == []


def test_rest_fallback_at_4_and_7_seconds(monkeypatch):
    """WS 미도착 → 4초·7초 REST 강제 갱신, 7.5초 반영 시 True."""
    clock = _Clock(_B / 1000)
    rest = _probe(monkeypatch, {"1m": _B - 60_001, "5m": _B - 300_001},
                  arrive_at={"1m": 7.5, "5m": 7.5}, clock=clock)
    assert _engine(clock)._wait_bar_close("AUSDT", _B) is True
    assert len(rest) == 2 and 4.0 <= rest[0] <= 4.1 and 7.0 <= rest[1] <= 7.1   # 0.1초 확인 주기 내


def test_gives_up_after_max_wait(monkeypatch):
    """10초까지 미반영 → False (이번 봉 판단 건너뜀)."""
    clock = _Clock(_B / 1000)
    rest = _probe(monkeypatch, {"1m": _B - 60_001, "5m": _B - 300_001}, clock=clock)
    assert _engine(clock)._wait_bar_close("AUSDT", _B) is False
    assert te._BAR_WAIT_MAX_SEC <= clock.t - _B / 1000 < te._BAR_WAIT_MAX_SEC + 0.2
    assert len(rest) == 2 and 4.0 <= rest[0] <= 4.1 and 7.0 <= rest[1] <= 7.1   # 0.1초 확인 주기 내


def test_htf_without_cache_not_required(monkeypatch):
    """1d 경계라도 캐시에 1d 봉이 없으면(상장 직후) 대기 대상에서 제외 — 1m만 반영되면 True."""
    b_day = 1_800_000_000_000 - (1_800_000_000_000 % 86_400_000)
    clock = _Clock(b_day / 1000)
    monkeypatch.setattr(te, "_get_last_close", lambda s, tf: b_day - 1 if tf == "1m" else 0)
    monkeypatch.setattr(te, "_refresh_detail_now", lambda s: None)
    assert _engine(clock)._wait_bar_close("AUSDT", b_day) is True
