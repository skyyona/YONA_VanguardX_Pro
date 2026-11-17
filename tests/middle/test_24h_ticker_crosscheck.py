"""
tests/middle/test_24h_ticker_crosscheck.py
1열 24h Ticker 교차 검증 결함 수정 (2026-11-17, W1~W5)
 T-1a Gold 후보 = ind_ready — 롱숏·FR 미수신 종목이 ATR 단독 점수로 1위가 되지 않음 (W1·W4)
 T-1b 빈 심볼('') 행은 Gold 배경이 아님 (W2)
 T-2b 순위에서 빠졌지만 화면에 남은 종목도 Change% 갱신, Time Fix 중에는 고정 유지 (W3)
 W5   get_rows — get_row 와 같은 행, 설정(_strategy.json)은 1회만 읽음
 T-2c Time Fix 중 장단계도 고정 — Change%(고정)와 같은 24h 변동률 기반 장단계가 같은 행에서 모순되지 않음
네트워크 조회 없음 · 설정 읽기는 대역(사용자 _strategy.json 미사용).
"""
import time
import tkinter as tk

import pytest

import middle.data.data_manager as dm_mod
import middle.widget.shared_context as _ctx
from bottom_engine.models import StrategyParams
from middle.col1_ranking.ranking.gold_ranking import GoldRanking
from middle.data.data_manager import MiddleDataManager
from middle.models import SymbolTicker
from middle.widget.constants import DARK_ROW_EVN, DARK_ROW_ODD
from middle.widget.middle_panel import MiddlePanel


@pytest.fixture()
def reads(monkeypatch):
    """설정 읽기 횟수 — StrategyLoader.load_or_default 호출 수 (use_macro=False 대역)."""
    n = {"count": 0}

    def _load(mode):
        n["count"] += 1
        return StrategyParams(sort_mode=mode, use_macro=False)

    monkeypatch.setattr(dm_mod.StrategyLoader, "load_or_default", staticmethod(_load))
    return n


def _dm(monkeypatch, n):
    """n개 종목 — 24h 변동률 내림차순(S0 최고), 거래량 순위 = 번호 + 1."""
    m = MiddleDataManager()
    tk_ = [SymbolTicker(f"S{i}USDT", 100.0, 0.0, 10.0 - i * 0.05, 1e9 - i, 101.0, 99.0) for i in range(n)]
    m._tickers = m._sorted_tickers = tk_
    m._tkr_map = {t.symbol: t for t in tk_}
    m._vol_rank = {t.symbol: i + 1 for i, t in enumerate(tk_)}
    monkeypatch.setattr(_ctx, "_data_mgr", m)
    monkeypatch.setattr(_ctx, "_bl_mgr", None)
    return m


def _put(m, sym, atr, deriv, d="▲"):
    """봉 지표 반영(_data_ready) 지표 캐시 — deriv=False 면 롱숏·FR 미수신(_ls_ts·_fr_ts 없음). d = 7개 TF 방향."""
    tf = {"dir": d, "k": 50.0, "d": 50.0}
    ind = dict(m._simple_ind(m._tkr_map[sym]), atr=atr, atr_pct=atr, _data_ready=True, _atr_ready=True,
               long_ratio=55.0, funding_rate=0.01, oi_change_1h=0.0,
               **{k: dict(tf) for k in ("tf1", "tf3", "tf5", "tf15", "tf1h", "tf4h", "tf1d")})
    if deriv:
        ind["_ls_ts"] = ind["_fr_ts"] = time.time()
    m._ind_cache[sym] = ind


# ── T-1a ──────────────────────────────────────────────────────
def test_t1a_gold_skips_symbol_without_long_short_fr(monkeypatch, reads):
    m = _dm(monkeypatch, 120)
    _put(m, "S0USDT", atr=1.0, deriv=True, d="↔")    # 약세·횡보장 — 4TF 중립, 실제 점수 = ATR 1% × 0.25/3 ≈ 0.083
    _put(m, "S1USDT", atr=9.0, deriv=False)          # 봉 지표만 반영(bars_ready O · ind_ready X) — ATR 단독 0.25
    assert _ctx.bars_ready("S1USDT") and not _ctx.ind_ready("S1USDT")
    assert GoldRanking.get_top1({}, ["S0USDT", "S1USDT"]) == "S0USDT"
    _put(m, "S1USDT", atr=9.0, deriv=True)           # 롱숏·FR 수신 후에는 후보
    assert GoldRanking.get_top1({}, ["S0USDT", "S1USDT"]) == "S1USDT"


# ── T-1b ──────────────────────────────────────────────────────
def test_t1b_empty_symbol_row_is_not_gold():
    p = MiddlePanel.__new__(MiddlePanel)
    p._player_tags_map, p._gold_sym = {}, ""          # Gold 없음(Pending 모드 등) + 안내 행 심볼 ''
    assert p._row_bg("", 0) == DARK_ROW_ODD
    assert p._row_bg("", 1) == DARK_ROW_EVN


# ── T-2b · W5 (1열 1초 갱신) ──────────────────────────────────
@pytest.fixture()
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    r.withdraw()
    yield r
    r.destroy()


def _panel(root, syms):
    p = MiddlePanel.__new__(MiddlePanel)
    tk.Frame.__init__(p, root)
    p._sort_mode, p._app_state, p._time_fixed = "24h Ticker", "RANKING", False
    p._m4_labels, p._phase_labels, p._player_tags_map = {}, {}, {}
    p._change_labels = {s: tk.Label(root, text="+10.00%") for s in syms}
    p._row_frames = [(None, s) for s in syms]
    return p


def test_t2b_soft_update_refreshes_symbol_out_of_ranking(monkeypatch, root, reads):
    m = _dm(monkeypatch, 150)
    p = _panel(root, ["S5USDT"])
    m._tkr_map["S5USDT"] = SymbolTicker("S5USDT", 100.0, 0.0, -40.0, 1e9 - 5, 101.0, 99.0)   # 급락 → 상위 100 밖
    m._tickers = list(m._tkr_map.values())
    assert "S5USDT" not in {r[0] for r in p._get_sorted_ranking()}
    p._do_soft_ranking_update()
    assert p._change_labels["S5USDT"].cget("text").strip() == "-40.00%"
    p._time_fixed = True                                    # Time Fix 중 Change% 고정 (설계)
    p._change_labels["S5USDT"].configure(text="+10.00%")
    p._do_soft_ranking_update()
    assert p._change_labels["S5USDT"].cget("text").strip() == "+10.00%"


def test_t2c_time_fix_keeps_phase_fixed(monkeypatch, root, reads):
    """Time Fix 중: 순위 안(S0)·순위 밖(S250, 갱신 대상 밖) 종목 모두 장단계 고정, M4 준비는 갱신 · 해제 후 장단계 갱신."""
    m = _dm(monkeypatch, 300)
    syms = ["S0USDT", "S250USDT"]
    p = _panel(root, syms)
    phase = {s: (tk.Frame(root), tk.Label(root, text="옛 장단계")) for s in syms}
    p._phase_labels = phase
    p._m4_labels = {s: tk.Label(root, text="옛 M4") for s in syms}
    m._tkr_map["S250USDT"] = SymbolTicker("S250USDT", 100.0, 0.0, -40.0, 1e9 - 250, 101.0, 99.0)  # −40% — 순위 밖 (급락 진행)
    m._tickers = list(m._tkr_map.values())
    ranked = {r[0] for r in p._get_sorted_ranking()}
    assert "S0USDT" in ranked and "S250USDT" not in ranked                   # S0 +10% = 순위 안
    p._time_fixed = True
    p._do_soft_ranking_update()
    for s in syms:
        assert phase[s][1].cget("text") == "옛 장단계"                        # 장단계 고정
        assert p._change_labels[s].cget("text") == "+10.00%"                 # Change% 고정
        assert p._m4_labels[s].cget("text") != "옛 M4"                        # M4 준비는 Time Fix 중에도 갱신
    p._time_fixed = False
    p._do_soft_ranking_update()
    assert phase["S0USDT"][1].cget("text") == "▲! 급등 진행"                  # 해제 후 갱신 (+10%)
    assert phase["S250USDT"][1].cget("text") == "▼! 급락 진행"                # 해제 후 갱신 (−40%)
    assert p._change_labels["S250USDT"].cget("text").strip() == "-40.00%"


def test_w5_get_rows_equals_get_row_and_reads_settings_once(monkeypatch, reads):
    m = _dm(monkeypatch, 150)
    syms = [f"S{i}USDT" for i in range(150)] + ["NOPEUSDT"]
    reads["count"] = 0
    rows = _ctx.get_rows(syms)
    assert reads["count"] == 1                               # 종목 수와 관계없이 설정 1회 읽기
    assert "NOPEUSDT" not in rows and len(rows) == 150       # 시세 없는 종목은 빠짐 (get_row → None 과 같음)
    assert all(rows[s] == m.get_row(s) for s in rows)


def test_w5_soft_update_settings_reads_do_not_grow_with_out_of_ranking_rows(monkeypatch, root, reads):
    """화면에 남은 순위 이탈 종목 수(5개·77개)와 관계없이 1회 갱신의 설정 읽기 횟수가 같음."""
    _dm(monkeypatch, 300)
    counts = []
    for n_out in (5, 77):
        out = [f"S{i}USDT" for i in range(300 - n_out, 300)]                 # 변동률 하위 = 24h 상위 100 밖
        p = _panel(root, out + [f"S{i}USDT" for i in range(100 - n_out)])
        reads["count"] = 0
        p._do_soft_ranking_update()
        counts.append(reads["count"])
        assert all(p._change_labels[s].cget("text") != "+10.00%" for s in out)   # 이탈 종목도 갱신됨
    assert counts[0] == counts[1]
