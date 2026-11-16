"""
tests/middle/test_bar_close_splice.py
봉 마감 즉시 반영 12건 — REST 마감 확정 판정(응답 마지막 원소 제외)·WS 마감 봉 접합·단조 가드·
엔진 종목 고정·STAGE3 제외. 네트워크 무의존(REST·WS 응답만 대역).
"""
import sys
import types

_ws_stub = types.ModuleType("websocket")
_ws_stub.WebSocketApp = object
sys.modules.setdefault("websocket", _ws_stub)

from middle.data import data_manager as _dm_mod
from middle.data.data_manager import MiddleDataManager
from middle.data.ohlcv_data import _parse_klines
from middle.models import OHLCVBar, SymbolTicker

_TF_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
          "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
_END = 1_800_000_000_000 - (1_800_000_000_000 % 86_400_000)   # 모든 TF 경계


def _bar(open_ms: int, tf: str, close: float = 100.0) -> OHLCVBar:
    return OHLCVBar(open_ms, close, close + 1, close - 1, close, 10.0, 1000.0, open_ms + _TF_MS[tf] - 1)


def _bars(tf: str, n: int, end_ms: int = _END) -> list[OHLCVBar]:
    """end_ms에 마지막 봉이 마감되는 n개 연속 봉."""
    step = _TF_MS[tf]
    return [_bar(end_ms - (n - k) * step, tf, 100.0 + k) for k in range(n)]


def _dm(symbol: str = "AUSDT", engine: str = "") -> MiddleDataManager:
    dm = MiddleDataManager()
    dm._last_detail_sym = symbol
    dm._engine_sym      = engine
    dm._ohlcv_cache[symbol] = {tf: _bars(tf, 30) for tf in _dm_mod._DETAIL_TFS}
    dm._deriv_cache[symbol] = (None, 0.0, None)
    return dm


def _capture(dm: MiddleDataManager):
    """_compute_detail·_refresh_detail 호출 기록 (계산·네트워크 대신)."""
    log = {"compute": [], "refresh": []}
    dm._compute_detail = lambda sym, bars, fr, oi, ls, oi_1h=0.0, deriv_ts=0.0: log["compute"].append((sym, bars))
    dm._refresh_detail = lambda sym: log["refresh"].append(sym)
    return log


def _run_threads_inline(monkeypatch):
    class _T:
        def __init__(self, target, args=(), daemon=None):
            self._t, self._a = target, args

        def start(self):
            self._t(*self._a)
    monkeypatch.setattr(_dm_mod.threading, "Thread", _T)


# ── REST 마감 확정 판정 ────────────────────────────────────────────────

def _raw(bars: list[OHLCVBar]) -> list[list]:
    """바이낸스 klines 응답 원소 12칸 형식 (8 거래 수·9 매수 체결량·10 매수 체결 금액·11 미사용)."""
    return [[b.open_time, str(b.open), str(b.high), str(b.low), str(b.close), str(b.volume),
             b.close_time, str(b.quote_volume), 0, str(b.taker_buy_volume), "0", "0"] for b in bars]


def test_parse_klines_drops_last_element():
    """응답 마지막 원소(진행 중 또는 마감 직후 미확정 봉)는 제외, 나머지는 그대로 — 로컬 시계 무관."""
    src = _bars("1m", 5)
    out = _parse_klines(_raw(src))
    assert out == src[:-1]
    assert _parse_klines(_raw(src[:1])) == []
    assert _parse_klines([]) == []


# ── WS 마감 봉 접합 ────────────────────────────────────────────────────

def test_ws_closed_bar_is_spliced_keeping_window(monkeypatch):
    """이어지는 마감 봉 → 해당 TF 끝에 접합·맨 앞 1개 제거(봉 수 불변), 다른 TF 그대로, REST 없음."""
    dm = _dm()
    log = _capture(dm)
    old = dm._ohlcv_cache["AUSDT"]
    new = _bar(_END, "1m", 555.0)
    dm._on_kline_closed("AUSDT", "1m", new)
    assert log["refresh"] == []
    sym, bars = log["compute"][0]
    assert sym == "AUSDT"
    assert len(bars["1m"]) == 30 and bars["1m"][-1] is new and bars["1m"][:-1] == old["1m"][1:]
    assert all(bars[tf] is old[tf] for tf in _dm_mod._DETAIL_TFS if tf != "1m")


def test_ws_already_applied_bar_ignored():
    """이미 반영된 봉(마감 시각 ≤ 캐시 마지막) → 계산·REST 모두 없음."""
    dm = _dm()
    log = _capture(dm)
    dm._on_kline_closed("AUSDT", "1m", dm._ohlcv_cache["AUSDT"]["1m"][-1])
    assert log == {"compute": [], "refresh": []}


def test_ws_gap_falls_back_to_rest(monkeypatch):
    """봉이 이어지지 않음(누락) → 접합하지 않고 REST 상세 갱신."""
    _run_threads_inline(monkeypatch)
    dm = _dm()
    log = _capture(dm)
    dm._on_kline_closed("AUSDT", "1m", _bar(_END + 60_000, "1m"))
    assert log == {"compute": [], "refresh": ["AUSDT"]}


def test_ws_without_derivatives_falls_back_to_rest(monkeypatch):
    """파생 데이터(펀딩·OI·롱숏) 미보유 → REST 상세 갱신."""
    _run_threads_inline(monkeypatch)
    dm = _dm()
    dm._deriv_cache.clear()
    log = _capture(dm)
    dm._on_kline_closed("AUSDT", "1m", _bar(_END, "1m"))
    assert log == {"compute": [], "refresh": ["AUSDT"]}


def test_ws_other_symbol_ignored():
    """엔진 종목·선택 종목이 아닌 심볼 → 무시."""
    dm = _dm()
    log = _capture(dm)
    dm._on_kline_closed("ZUSDT", "1m", _bar(_END, "1m"))
    assert log == {"compute": [], "refresh": []}


def test_ws_engine_symbol_accepted_when_middle_selects_other():
    """중단 모듈이 다른 종목을 선택 중이어도 엔진 종목 봉은 접합."""
    dm = _dm(symbol="AUSDT", engine="AUSDT")
    dm._last_detail_sym = "BUSDT"
    log = _capture(dm)
    dm._on_kline_closed("AUSDT", "1m", _bar(_END, "1m"))
    assert len(log["compute"]) == 1


# ── 단조 가드 ──────────────────────────────────────────────────────────

class _Svc:
    def __init__(self, bars_by_tf):
        self._b = bars_by_tf

    def fetch(self, symbol, tf, limit=None):
        return list(self._b[tf])


def test_rest_refresh_keeps_newer_cached_bars():
    """REST 응답(마감 직후 이전 봉까지)이 캐시보다 오래된 TF는 캐시 봉 유지."""
    dm = _dm()
    cached_1m = _bars("1m", 30, _END + 60_000)            # 캐시가 1봉 더 최신 (WS 접합분)
    dm._ohlcv_cache["AUSDT"]["1m"] = cached_1m
    dm._ohlcv_svc = _Svc({tf: _bars(tf, 30) for tf in _dm_mod._DETAIL_TFS})
    dm._fr_svc = types.SimpleNamespace(fetch=lambda s: None)
    dm._oi_svc = types.SimpleNamespace(fetch_changes=lambda s: (0.0, 0.0))
    dm._ls_svc = types.SimpleNamespace(fetch=lambda s: None)
    got = []
    dm._compute_detail = lambda sym, bars, fr, oi, ls, oi_1h=0.0, deriv_ts=0.0: got.append(bars)
    dm._refresh_detail("AUSDT")
    assert got[0]["1m"] is cached_1m
    assert got[0]["5m"][-1].close_time == _END - 1


def test_compute_does_not_overwrite_newer_cache():
    """계산 중 더 최신 봉이 반영됐으면 이번 계산 결과로 덮어쓰지 않음."""
    dm = _dm()
    dm._tkr_map["AUSDT"] = SymbolTicker("AUSDT", 100.0, 0.0, 0.0, 1e6, 101.0, 99.0)
    stale = dict(dm._ohlcv_cache["AUSDT"])
    newer = dict(stale)
    newer["1m"] = _bars("1m", 30, _END + 60_000)
    dm._ohlcv_cache["AUSDT"] = newer
    dm._ind_cache["AUSDT"] = {"marker": True}
    dm._compute_detail("AUSDT", stale, None, 0.0, None)
    assert dm._ind_cache["AUSDT"] == {"marker": True}
    assert dm._ohlcv_cache["AUSDT"] is newer


def test_compute_writes_when_not_older():
    """최신 봉으로 계산하면 지표·봉 캐시 반영 (tf1 K/D 포함)."""
    dm = _dm()
    dm._tkr_map["AUSDT"] = SymbolTicker("AUSDT", 100.0, 0.0, 0.0, 1e6, 101.0, 99.0)
    bars = dict(dm._ohlcv_cache["AUSDT"])
    bars["1m"] = bars["1m"][1:] + [_bar(_END, "1m", 130.0)]
    dm._compute_detail("AUSDT", bars, None, 0.0, None)
    assert dm._ohlcv_cache["AUSDT"] is bars
    assert dm._ind_cache["AUSDT"]["_data_ready"] is True and "k" in dm._ind_cache["AUSDT"]["tf1"]
    assert dm.get_last_close("AUSDT", "1m") == _END + 60_000 - 1


# ── 엔진 종목 고정 ─────────────────────────────────────────────────────

class _WS:
    def __init__(self):
        self.symbol = ""

    def set_symbol(self, s):
        self.symbol = s


def test_engine_pin_keeps_ws_symbol(monkeypatch):
    """고정 중에는 중단 모듈 선택이 WS 구독 종목을 바꾸지 않고, 해제하면 선택 종목으로 복귀."""
    _run_threads_inline(monkeypatch)
    dm = MiddleDataManager()
    dm._refresh_detail = lambda sym: None
    dm._ws_klines = _WS()
    dm.set_engine_symbol("AUSDT")
    assert dm._ws_klines.symbol == "AUSDT"
    dm.request_selected("BUSDT")
    assert dm._ws_klines.symbol == "AUSDT" and dm._last_detail_sym == "BUSDT"
    dm.set_engine_symbol("")
    assert dm._ws_klines.symbol == "BUSDT"


def test_stage3_skips_engine_symbol():
    """STAGE3 상위 N 갱신은 엔진 종목을 수집하지 않음 (limit 차이·시점 경합 차단)."""
    dm = MiddleDataManager()
    dm._engine_sym = "AUSDT"
    dm._sorted_tickers = [SymbolTicker("AUSDT", 100.0, 0.0, 0.0, 1e6, 101.0, 99.0)]
    fetched = []
    dm._ohlcv_svc = types.SimpleNamespace(fetch=lambda s, tf, limit=None: fetched.append(s) or [])
    dm._refresh_topn_klines(1)
    assert fetched == []
