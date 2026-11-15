"""
tests/middle/test_24h_ticker_fixes.py
1열 24h Ticker 점검 결함 수정 (2026-11-12)
 A-1 3열이 거래량 상위 200 밖 종목도 1열과 같은 행 사용 (get_row) · Player·Gold는 표시 목록 기준
 A-2 웹소켓 '데이터 받음' = 최근 수신 기준 (끊기면 REST 대체 갱신 재개)
 A-3 갱신 대상 밖 종목의 남은 지표 캐시는 1열 행·Player 표시에 쓰지 않음 (엔진 get_ind는 그대로)
네트워크 조회만 대역.
"""
import json

import middle.data.data_manager as dm_mod
import middle.data.websocket_ticker as wst
import middle.data.websocket_klines as wsk
import middle.widget.shared_context as _ctx
import middle.col1_ranking.ranking.gold_ranking as gr
from middle.data.data_manager import MiddleDataManager
from middle.models import OHLCVBar, SymbolTicker
from bottom_engine.models import StrategyParams

_STEP15 = 900_000


def _bars15(n, up=True):
    out, p = [], 100.0
    for i in range(n):
        p *= 1.004 if (up and i % 3) or (not up and i % 3 == 0) else 0.997
        out.append(OHLCVBar(i * _STEP15, p, p * 1.001, p * 0.999, p, 10.0, 1000.0, (i + 1) * _STEP15 - 1))
    return out


def _dm(monkeypatch):
    monkeypatch.setattr(dm_mod.StrategyLoader, "load_or_default",
                        staticmethod(lambda m: StrategyParams(sort_mode=m, use_macro=False)))
    return MiddleDataManager()


def _with_cache(dm, sym, rank, chg=20.0):
    """sym: 지표 캐시(정배열·15m 봉 상승) 보유 + 거래량 순위 rank."""
    tkr = SymbolTicker(sym, 100.0, 1.0, chg, 1e6, 101.0, 99.0)
    dm._tkr_map[sym] = tkr
    dm._tickers.append(tkr)
    dm._vol_rank[sym] = rank
    dm._ind_cache[sym] = {"align": "정배열", **{tf: {"k": 50.0, "d": 50.0} for tf in ("tf1h", "tf4h", "tf1d")}}
    dm._ohlcv_cache[sym] = {"15m": _bars15(60)}
    return tkr


# ── A-3 ───────────────────────────────────────────────────────
def test_stale_cache_outside_refresh_scope_is_not_shown(monkeypatch):
    dm = _dm(monkeypatch)
    _with_cache(dm, "INUSDT", rank=50)
    _with_cache(dm, "OUTUSDT", rank=150)                 # 예전 100위 안 → 지금 150위 (캐시는 남아 있음)
    r_in, r_out = dm.get_row("INUSDT"), dm.get_row("OUTUSDT")
    assert r_in[2] in ("▲ 롱 대기", "▼ 숏 대기") and r_in[8] == "▲▲ 상승 진행"
    assert r_out[2] == "─ 데이터 없음"                     # 옛 '롱 대기' 대신
    assert r_out[8] == "▲! 급등 진행"                      # 옛 정배열 대신 24h 변동률 구간 (+20%)
    assert dm.get_ind("OUTUSDT")["align"] == "정배열"      # 엔진 입력은 그대로


def test_selected_and_engine_symbols_use_cache_outside_top100(monkeypatch):
    dm = _dm(monkeypatch)
    _with_cache(dm, "SELUSDT", rank=300)
    _with_cache(dm, "ENGUSDT", rank=400)
    dm._last_detail_sym, dm._engine_sym = "SELUSDT", "ENGUSDT"   # 상세 갱신·WS 봉 마감으로 갱신되는 종목
    assert dm.get_row("SELUSDT")[8] == "▲▲ 상승 진행"
    assert dm.get_row("ENGUSDT")[8] == "▲▲ 상승 진행"


def test_player_detection_skips_stale_symbols(monkeypatch):
    dm = _dm(monkeypatch)
    for sym, rank in (("INUSDT", 10), ("OUTUSDT", 150)):
        _with_cache(dm, sym, rank)
        dm._ind_cache[sym].update({"long_ratio": 86.0, "funding_rate": 0.105})   # FOMO·FR+ 과열 조건
    assert dm.get_player("INUSDT") is not None and dm.get_player("INUSDT").tags
    assert dm.get_player("OUTUSDT") is None


# ── A-1 ───────────────────────────────────────────────────────
def test_get_row_covers_symbols_outside_ranking_pool(monkeypatch):
    dm = _dm(monkeypatch)
    _with_cache(dm, "POOLUSDT", rank=5)
    _with_cache(dm, "FARUSDT", rank=350, chg=33.0)
    dm._rebuild_ranking_rows()
    dm._sorted_tickers = sorted(dm._tickers, key=lambda t: dm._vol_rank[t.symbol])
    dm._rebuild_ranking_rows()
    assert {r[0] for r in dm.get_ranking_rows()} == {"POOLUSDT", "FARUSDT"}   # 대역은 2종목뿐이라 둘 다 풀 안
    dm._ranking_rows = [r for r in dm._ranking_rows if r[0] == "POOLUSDT"]  # 실제처럼 FAR는 풀 밖
    row24 = next(r for r in dm.get_all_ranked_by_change(100) if r[0] == "FARUSDT")
    assert dm.get_row("FARUSDT") == row24                                  # 3열 = 1열 24h 행
    assert dm.get_row("NOPEUSDT") is None


def test_col3_phase_and_header_use_get_row(monkeypatch):
    import middle.widget.panel_col3 as col3
    dm = _dm(monkeypatch)
    _with_cache(dm, "FARUSDT", rank=50, chg=33.0)
    dm._ranking_rows = []                                                   # 거래량 상위 200 풀에 없음
    monkeypatch.setattr(_ctx, "_data_mgr", dm)
    p = col3._Col3Mixin()
    assert p._get_phase_for_sym("FARUSDT") == (dm.get_row("FARUSDT")[8], dm.get_row("FARUSDT")[9])
    assert p._get_phase_for_sym("FARUSDT")[0] == "▲▲ 상승 진행"


def test_player_map_and_gold_use_given_symbols(monkeypatch):
    dm = _dm(monkeypatch)
    for sym, rank in (("AUSDT", 1), ("BUSDT", 2)):
        _with_cache(dm, sym, rank)
        dm._ind_cache[sym].update({"long_ratio": 86.0, "funding_rate": 0.105})
    dm._ranking_rows = [dm.get_row("AUSDT")]                                   # 풀 = A만 (B는 풀 밖 24h 목록 종목)
    monkeypatch.setattr(_ctx, "_data_mgr", dm)
    assert set(dm.get_player_map()) == {"AUSDT"}                               # 기본 = 풀 기준 (기존 동작)
    pm = dm.get_player_map(["AUSDT", "BUSDT"])
    assert set(pm) == {"AUSDT", "BUSDT"}                                       # 표시 목록 기준
    monkeypatch.setattr(gr.GoldRanking, "calc", staticmethod(lambda s, m=None: {"AUSDT": 0.2, "BUSDT": 0.7}[s]))
    assert gr.GoldRanking.get_top1(pm, ["AUSDT", "BUSDT"]) == "BUSDT"
    assert gr.GoldRanking.get_top1(pm) == "AUSDT"                              # 풀 기준이면 B는 대상 아님


# ── A-2 ───────────────────────────────────────────────────────
def test_ticker_ws_data_flag_expires_after_silence(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(wst.time, "time", lambda: now[0])
    ws = wst.WebSocketTicker(on_update=lambda t: None)
    assert ws.has_received_data is False
    ws._on_message(None, json.dumps({"data": [{"s": "BTCUSDT", "c": "1", "o": "1", "h": "1", "l": "1", "q": "1"}]}))
    assert ws.has_received_data is True
    now[0] += wst._STALE_SEC - 1
    assert ws.has_received_data is True
    now[0] += 2                                                               # 15초 넘게 수신 없음
    assert ws.has_received_data is False                                      # → REST 대체 갱신 재개


def test_klines_ws_data_flag_expires_after_silence(monkeypatch):
    now = [2_000_000.0]
    monkeypatch.setattr(wsk.time, "time", lambda: now[0])
    ws = wsk.WebSocketKlines(on_closed=lambda s, tf, b: None)
    ws._symbol = "BTCUSDT"
    msg = {"data": {"s": "BTCUSDT", "k": {"t": 0, "T": 59_999, "i": "1m", "x": True, "o": "1", "h": "1",
                                          "l": "1", "c": "1", "v": "1", "q": "1", "V": "0.5"}}}
    ws._on_message(None, json.dumps(msg))
    assert ws.has_received_data is True
    now[0] += wsk._STALE_SEC + 1
    assert ws.has_received_data is False


def test_rest_ticker_fallback_resumes_when_ws_silent(monkeypatch):
    """data_manager 루프 조건 그대로: WS가 조용해지면 REST _refresh_tickers 호출."""
    now = [3_000_000.0]
    monkeypatch.setattr(wst.time, "time", lambda: now[0])
    ws = wst.WebSocketTicker(on_update=lambda t: None)
    ws._last_data_time = now[0]
    use_rest = lambda: ws is None or not ws.has_received_data
    assert use_rest() is False
    now[0] += 60
    assert use_rest() is True


# ── B (화면) ──────────────────────────────────────────────────
import tkinter as tk
import pytest
from middle.widget.middle_panel import MiddlePanel
from middle.analysis.forecast import Forecaster


@pytest.fixture()
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    r.withdraw()
    yield r
    r.destroy()


def _row(sym, days=100, m4="─ 로딩중", m4_col="#888888", chg="  +1.00%"):
    return (sym, days, m4, m4_col, chg, "#00ff00", "+1.00%", "#00ff00", "⟳ 전환 대기", "#ffff00", 4)


def test_blacklist_removed_before_top_n_cut(monkeypatch):
    """B-5: 블랙리스트를 먼저 빼고 자름 → 항상 limit개. 예고 '목록' 조건도 같은 목록."""
    dm = _dm(monkeypatch)
    for i in range(5):
        _with_cache(dm, f"S{i}USDT", rank=1, chg=10.0 - i)
    dm._list_excluded = lambda s: s == "S1USDT"
    rows = dm.get_all_ranked_by_change(3)
    assert [r[0] for r in rows] == ["S0USDT", "S2USDT", "S3USDT"]
    assert [t.symbol for t in dm._change_ranked(3)] == ["S0USDT", "S2USDT", "S3USDT"]


def test_rebuild_highlights_only_selected_symbol_in_analysis(monkeypatch, root):
    """B-3: 분석 중이고 선택 종목이 목록에 있을 때만 강조 — 첫 행 대신 강조 없음."""
    monkeypatch.setattr(_ctx, "_data_mgr", None)
    p = MiddlePanel.__new__(MiddlePanel)
    p._inner = tk.Frame(root)
    for k in ("_special", "_cum_labels", "_cum_shown", "_change_labels", "_phase_labels", "_m4_labels", "_nl_rows"):
        setattr(p, k, {})
    p._row_frames, p._sort_mode = [], "24h Ticker"
    data = [_row("AUSDT"), _row("BUSDT")]
    p._get_sorted_ranking = lambda: data
    p._build_ranking_rows = lambda d=None: p._row_frames.extend((None, r[0]) for r in d)
    lit = []
    p._restore_row_highlight = lit.append
    for state, sel, expect in (("ANALYSIS", "BUSDT", [1]), ("ANALYSIS", "ZUSDT", []), ("RANKING", "AUSDT", [])):
        lit.clear(); p._row_frames = []
        p._app_state, p._sel_var = state, tk.StringVar(root, value=sel)
        p._rebuild_ranking_rows()
        assert lit == expect, (state, sel)


def _tf_panel(root, fixed=True):
    p = MiddlePanel.__new__(MiddlePanel)
    p._time_fixed, p._timer_running, p._elapsed_sec = fixed, fixed, 12
    p._time_fix_prices = {"AUSDT": 1.0}
    p._timer_lbl = tk.Label(root, text="00:00:12")
    p._timefix_btn = tk.Button(root, text="✕  Release")
    p._cancel_tick_timer = lambda: None
    return p


def test_time_fix_auto_released_before_user_rebuild(root):
    """B-4: 목록 재생성 사용자 동작 전 Time Fix 자동 해제 + '자동 해제' 표시. 고정 아니면 아무것도 안 함."""
    p = _tf_panel(root)
    p._release_time_fix_for_rebuild()
    assert p._time_fixed is False and p._timer_running is False and p._time_fix_prices == {}
    assert p._timer_lbl.cget("text") == "자동 해제" and p._timefix_btn.cget("text") == "⏱  Time Fix"
    q = _tf_panel(root, fixed=False)
    q._release_time_fix_for_rebuild()
    assert q._timer_lbl.cget("text") == "00:00:12"


def test_soft_update_refreshes_m4_even_during_time_fix(root):
    """B-7: Time Fix 중 Change%는 고정, M4 준비는 갱신."""
    p = MiddlePanel.__new__(MiddlePanel)
    p._time_fixed, p._sort_mode, p._player_tags_map = True, "24h Ticker", {}
    m4 = tk.Label(root, text="─ 로딩중", fg="#888888")
    chg = tk.Label(root, text="  +1.00%", fg="#00ff00")
    p._m4_labels, p._change_labels, p._phase_labels = {"AUSDT": m4}, {"AUSDT": chg}, {}
    p._row_frames = [(None, "AUSDT")]
    p._get_sorted_ranking = lambda: [_row("AUSDT", m4="▲ 롱 대기", m4_col="#11de93", chg="  +9.00%")]
    p._do_soft_ranking_update()
    assert (m4.cget("text"), m4.cget("fg")) == ("▲ 롱 대기", "#11de93")
    assert chg.cget("text") == "  +1.00%"


class _HdrDM:
    def __init__(self, row, vol_rank):
        self.row, self._tkr_map = row, {row[0]: SymbolTicker(row[0], 1.0, 0.0, 1.0, 1.0, 1.0, 1.0)}
        self._vol_rank = {row[0]: vol_rank}

    def get_row(self, sym):
        return self.row if sym == self.row[0] else None


def _hdr_texts(monkeypatch, root, row, vol_rank):
    monkeypatch.setattr(_ctx, "_data_mgr", _HdrDM(row, vol_rank))
    p = MiddlePanel.__new__(MiddlePanel)
    p._hdr_f = tk.Frame(root)
    p._sel_var = tk.StringVar(root, value=row[0])
    p._action_bar, p._assigned_sym = None, ""
    p._refresh_header()
    return [w.cget("text") for f in p._hdr_f.winfo_children() for w in f.winfo_children()]


def test_col3_header_new_badge_and_volume_rank_badge(monkeypatch, root):
    """B-1: '신규 N일'은 30일 이하만 · A-1: 거래량 200위 밖 24h 목록 종목도 행 값 표시 + 거래량 순위 뱃지."""
    t = _hdr_texts(monkeypatch, root, _row("BTCUSDT", days=2621, m4="▲ 롱 대기"), vol_rank=1)
    assert not any("신규" in x for x in t) and "  TOP 200 " in t and "  ▲ 롱 대기 " in t
    t = _hdr_texts(monkeypatch, root, _row("NEWUSDT", days=5, m4="─ 데이터 없음"), vol_rank=350)
    assert " 신규5일" in t and "  350위 " in t and "  ─ 데이터 없음 " in t and "⟳ 전환 대기" in t


class _VerdictDM:
    """3열 종합 분석이 읽는 조회만 — AUSDT·BUSDT 24h 행 (실시간 순위 A 1위·B 2위)."""
    _forecaster = Forecaster(None)

    def __init__(self):
        self.rows = [_row("AUSDT", chg="  +9.00%"), _row("BUSDT", chg="  +5.00%")]
        self._tkr_map = {r[0]: SymbolTicker(r[0], 1.0, 0.0, 1.0, 1.0, 1.0, 1.0) for r in self.rows}
        self._vol_rank = {"AUSDT": 1, "BUSDT": 2}

    def get_row(self, sym):
        return next((r for r in self.rows if r[0] == sym), None)

    def get_ind(self, sym):
        return {}

    def get_player(self, sym):
        return None

    def get_forecast(self, sym):
        return None

    def get_listing_days(self, sym):
        return 100

    def get_ranking_rows(self):
        return self.rows

    def get_all_ranked_by_change(self, limit=100):
        return self.rows[:limit]


def test_col3_24h_rank_uses_column1_displayed_order(monkeypatch, root):
    """B-6: 분석 중 1열은 멈춰 있음 — 3열 '(전체 N위)'는 1열 # 칸 순위 (실시간으로 바뀐 순위 아님)."""
    class _BL:
        def get_all(self): return []
        def is_blacklisted(self, s): return False
    monkeypatch.setattr(_ctx, "_data_mgr", _VerdictDM())
    monkeypatch.setattr(_ctx, "_bl_mgr", _BL())
    p = MiddlePanel.__new__(MiddlePanel)
    p._verdict_f = tk.Frame(root)
    p._sel_var = tk.StringVar(root, value="AUSDT")
    p._sort_mode = "24h Ticker"
    p._row_frames = [(None, "BUSDT"), (None, "AUSDT")]          # 1열 표시(멈춤) = B 1위·A 2위
    p._refresh_verdict()
    texts = [w.cget("text") for f in p._verdict_f.winfo_children() for w in f.winfo_children()
             if isinstance(w, tk.Label)]
    assert "  (전체 2위)" in texts and "  (전체 1위)" not in texts
