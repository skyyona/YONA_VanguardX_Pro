"""
tests/middle/test_volatility_fixes.py
1열 Sort by 'Volatility' 결함 수정 (2026-11-16) — 네트워크 없이 대역.
 V1 거래량 101~200위 기본값 ATR 2.0이 실제 종목을 밀어내지 않음 (목록 = 지금 갱신되는 실제 봉 지표 종목)
 V2 갱신 대상 밖으로 밀려난 종목의 옛 ATR이 남지 않음
 V3 시작 직후(STAGE3 전) 기본값 목록을 ATR 순서처럼 보여주지 않음
 V4 1h 봉 15개 미만·1h 조회 실패 → '저변동' 대신 맨 아래 '데이터 부족' (같은 분 안 재시도)
 V5 ATR 표시 소수 2자리 (등급 경계와 표시 숫자 일치)
 V6 3열: 채점 보류·데이터 부족·목록 밖 표시
 V7 행 5번째 칸(24h 변동률 문자) 예비 경로 삭제
 G  Gold 1위 후보에서 봉 지표 미준비 종목 제외 (모든 Sort by 공통)
 표시 변경: '변동성 등급' → 엔진 Volatility 모드 G4 ATR% 허용 범위 (엔진과 같은 식, 설정 읽기만)
"""
import inspect
import time
import types

import pytest

import middle.data.data_manager as dm_mod
import middle.widget.shared_context as ctx
from middle.col1_ranking.ranking.volatility_scorer import VolatilityScorer
from middle.data.data_manager import MiddleDataManager
from middle.models import OHLCVBar, SymbolTicker


@pytest.fixture()
def dm(monkeypatch):
    m = MiddleDataManager()
    tk = [SymbolTicker(f"S{i}USDT", 1.0, 0.0, 0.0, 1e9 - i, 1.0, 1.0) for i in range(200)]
    m._tickers = m._sorted_tickers = tk
    m._tkr_map = {t.symbol: t for t in tk}
    m._vol_rank = {t.symbol: i + 1 for i, t in enumerate(tk)}
    monkeypatch.setattr(ctx, "_data_mgr", m)
    return m


def _put(dm, sym, atr, data=True, **kw):
    _ts = time.time()                                      # 롱숏·FR 수신 시각 — Gold 후보 조건(ind_ready)
    ind = dict(dm._simple_ind(dm._tkr_map[sym]), atr=atr, atr_pct=atr, _data_ready=data, _atr_ready=True,
               _ls_ts=_ts, _fr_ts=_ts)
    ind.update(kw)
    dm._ind_cache[sym] = ind


def _list(dm):
    dm._rebuild_ranking_rows()
    return [r[0] for r in VolatilityScorer.get_sorted(dm.get_ranking_rows(), limit=100)]


def test_v1_default_rows_do_not_push_out_real_symbols(dm):
    for i in range(100):                                   # 거래량 상위 100 — 실제 ATR 0.50~1.49 (실측 중앙 1.50)
        _put(dm, f"S{i}USDT", 0.5 + i * 0.01)
    lst = _list(dm)
    assert len(lst) == 100 and all(int(s[1:-4]) < 100 for s in lst)   # 수정 전: 101~200위 기본값 2.0 100행이 전부 차지
    assert lst[0] == "S99USDT" and lst[-1] == "S0USDT"


def test_v2_stale_value_outside_refresh_set_dropped(dm):
    _put(dm, "S5USDT", 3.0)
    _put(dm, "S150USDT", 9.0)                              # 상위 100일 때 남은 옛 ATR 9% — 지금 151위
    assert dm.bars_ready("S150USDT") is False
    assert _list(dm) == ["S5USDT"]                          # 수정 전: S150USDT 1위


def test_v2_selected_or_engine_symbol_outside_top100_counts(dm):
    _put(dm, "S150USDT", 9.0)
    dm._last_detail_sym = "S150USDT"                        # 상세 갱신 대상 — 실제 값
    assert _list(dm) == ["S150USDT"]
    dm._last_detail_sym, dm._engine_sym = "", "S150USDT"
    assert _list(dm) == ["S150USDT"]


def test_v3_startup_before_stage3_empty_not_volume_order(dm):
    # 시작 직후 — 캐시 없음(기본값 2.0) 또는 STAGE3 전(_data_ready False)
    _put(dm, "S1USDT", 2.0, data=False)
    assert _list(dm) == []                                  # 수정 전: 거래량 순서 100행 × '2.0% 중간 변동성'


def test_bars_ready_helper(dm, monkeypatch):
    _put(dm, "S1USDT", 1.0)
    assert dm.bars_ready("S1USDT") and ctx.bars_ready("S1USDT")
    assert not dm.bars_ready("S2USDT")                      # 캐시 없음
    monkeypatch.setattr(ctx, "_data_mgr", None)
    assert ctx.bars_ready("S1USDT") is False


# ── V4 데이터 부족(1h 봉 15개 미만·조회 실패) — '저변동' 대신 맨 아래 '데이터 부족' ──
_STEP = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _bars(tf, n):
    s = _STEP[tf]
    return [OHLCVBar(i * s, 1 + i * 1e-3, 1.05 + i * 1e-3, 0.95 + i * 1e-3, 1 + i * 1e-3, 100.0, 100.0, i * s + s - 1)
            for i in range(n)]


def test_v4_insufficient_atr_sorted_last(dm):
    _put(dm, "S1USDT", 1.0)
    _put(dm, "S2USDT", 0.0, _atr_ready=False)             # 신규 상장 10봉 → AtrPercent 0.0
    _put(dm, "S3USDT", 2.0, _atr_ready=False)             # 1h 조회 실패 → 값 2.0 남음
    _put(dm, "S4USDT", 0.3)
    assert _list(dm) == ["S1USDT", "S4USDT", "S2USDT", "S3USDT"]   # 수정 전: S3(2.0) 1위·S2 '0.0% 저변동'


def _bars_upto(tf, n, now_ms):
    """now_ms 기준 마지막 마감 봉까지 n개 (최신 봉 — 다른 TF가 재시도 표시를 켜지 않게)."""
    s = _STEP[tf]
    last = now_ms // s - 1
    return [OHLCVBar(i * s, 1.0, 1.05, 0.95, 1.0, 100.0, 100.0, i * s + s - 1) for i in range(last - n + 1, last + 1)]


def test_v4_stage3_1h_failure_marks_not_ready_and_retries(dm, monkeypatch):
    now_ms = 1_800_000_000_000 + 8_000
    monkeypatch.setattr(dm_mod.time, "time", lambda: now_ms / 1000)
    dm._sorted_tickers = dm._sorted_tickers[:1]
    dm._ohlcv_svc = types.SimpleNamespace(
        fetch=lambda s, tf, limit=None: [] if tf == "1h" else _bars_upto(tf, limit - 1, now_ms))
    dm._refresh_topn_klines(1)
    ind = dm._ind_cache["S0USDT"]
    assert ind["_data_ready"] is True and ind["_atr_ready"] is False
    assert dm._stage3_stale is True                        # 1h 조회 실패만으로 같은 분 안 재시도 (다른 TF는 최신)
    dm._ohlcv_svc = types.SimpleNamespace(fetch=lambda s, tf, limit=None: _bars_upto(tf, limit - 1, now_ms))
    dm._refresh_topn_klines(1)                             # 재시도 — 1h 저장 봉 없음 → 전체 조회
    assert dm._ind_cache["S0USDT"]["_atr_ready"] is True


def test_v4_stage3_short_history_not_ready(dm):
    dm._sorted_tickers = dm._sorted_tickers[:1]
    dm._ohlcv_svc = types.SimpleNamespace(fetch=lambda s, tf, limit=None: _bars(tf, 11))   # 마감 10봉
    dm._refresh_topn_klines(1)
    ind = dm._ind_cache["S0USDT"]
    assert ind["atr"] == 0.0 and ind["_atr_ready"] is False


@pytest.mark.parametrize("n, ready", [(14, False), (15, True), (199, True)])
def test_v4_detail_path_atr_ready(dm, n, ready):
    dm._ohlcv_svc = types.SimpleNamespace(fetch=lambda s, tf, limit=None: _bars(tf, n))
    dm._ls_svc = types.SimpleNamespace(fetch=lambda s: None)
    dm._fr_svc = types.SimpleNamespace(fetch=lambda s: None)
    dm._oi_svc = types.SimpleNamespace(fetch_changes=lambda s: (0.0, 0.0))
    dm._refresh_detail("S0USDT")
    assert dm._ind_cache["S0USDT"]["_atr_ready"] is ready
    assert "_atr_ready" in dm_mod._STAGE3_FIELDS and dm_mod._ATR_MIN_BARS == 15


def test_v4_col1_shows_insufficient_not_low_grade():
    import middle.widget.panel_col1 as pc1
    src = inspect.getsource(pc1)
    assert 'if not _ind_v.get("_atr_ready"):' in src and "데이터 부족 (1h 봉 15개 미만·조회 실패)" in src


# ── V5 표시 숫자(소수 2자리)와 등급 경계 일치 ─────────────────────────
@pytest.mark.parametrize("atr, txt, grade", [
    (4.96, "4.96%", "중간"),    # 수정 전 '5.0%' + 중간 변동성
    (5.0, "5.00%", "중간"),     # 고변동은 5.0 초과
    (5.01, "5.01%", "고변동"),
    (1.96, "1.96%", "저변동"),  # 수정 전 '2.0%' + 저변동
    (2.0, "2.00%", "중간"),
])
def test_v5_display_two_decimals_matches_grade(atr, txt, grade):
    from middle.analysis.atr_percent import AtrPercent
    import middle.widget.panel_col1 as pc1
    assert f"{atr:.2f}%" == txt
    lbl = AtrPercent.label(atr)
    assert ("고변동" in lbl) == (grade == "고변동") and ("저변동" in lbl) == (grade == "저변동")
    src = inspect.getsource(pc1)
    assert '_atr_txt = f"{_atr:.2f}%"' in src and '_atr_txt = f"{_atr:.1f}%"' not in src


# ── V6 3열 Volatility 선정 근거 — 채점 보류·데이터 부족·목록 밖 ─────────────
def _verdict_texts(sym, sorted_rows):
    import tkinter as tk
    from middle.widget.middle_panel import MiddlePanel
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    root.withdraw()
    try:
        p = MiddlePanel.__new__(MiddlePanel)
        p._verdict_f = tk.Frame(root)
        p._sel_var = tk.StringVar(root, sym)
        p._sort_mode = "Volatility"
        p._get_phase_for_sym = lambda s: ("", "")
        p._render_forecast = lambda s: None
        p._get_sorted_ranking = lambda: sorted_rows
        p._refresh_verdict()
        out = []
        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Label):
                    out.append(c.cget("text"))
                walk(c)
        walk(p._verdict_f)
        return out
    finally:
        root.destroy()


def test_v6_not_ready_symbol_held(dm):
    dm._rebuild_ranking_rows()
    _put(dm, "S150USDT", 9.0)                              # 옛 값 — 수정 전 'ATR 9.0% (고변동)' 실제처럼 표시
    texts = _verdict_texts("S150USDT", [])
    assert any("Volatility 채점 보류 (갱신 대상 밖·데이터 준비 중)" in t for t in texts), texts
    assert not any(t.startswith("ATR ") for t in texts)


def test_v6_insufficient_data(dm):
    dm._rebuild_ranking_rows()
    _put(dm, "S1USDT", 0.0, _atr_ready=False)
    texts = _verdict_texts("S1USDT", [])
    assert any("ATR 데이터 부족 (1h 봉 15개 미만·조회 실패)" in t for t in texts), texts


def test_v6_rank_or_outside_list(dm):
    dm._rebuild_ranking_rows()
    _put(dm, "S1USDT", 3.456)
    texts = _verdict_texts("S1USDT", [("S1USDT",)])
    assert "ATR 3.46% (중변동)" in texts and "  (전체 1위)" in texts, texts
    texts = _verdict_texts("S1USDT", [])
    assert "  (목록 밖 — 100위 밖)" in texts, texts       # 수정 전: 순위 없이 표시


# ── V7 실행되지 않던 r[4](24h 변동률 문자) 예비 경로 삭제 ─────────────────
def test_v7_no_row_text_fallback(dm):
    src = inspect.getsource(VolatilityScorer)
    assert "r[4]" not in src
    _put(dm, "S1USDT", 1.5)
    dm._rebuild_ranking_rows()
    row = next(r for r in dm.get_ranking_rows() if r[0] == "S1USDT")
    assert row[4].strip().endswith("%")                   # r[4] = 24h 변동률 문자 (ATR 아님)
    assert _list(dm) == ["S1USDT"]


# ── G Gold 1위 후보 — 봉 지표 미준비(갱신 대상 밖 옛 값·기본값) 제외 (모든 Sort by 공통) ──
def test_g_gold_skips_not_ready_candidates(dm):
    from middle.col1_ranking.ranking.gold_ranking import GoldRanking
    _put(dm, "S150USDT", 9.0)                              # 옛 ATR 9% — 수정 전 atr_score 0.25로 우세
    _put(dm, "S5USDT", 1.2)                                # 실제 값
    syms = ["S150USDT", "S5USDT", "S199USDT"]              # S199 = 기본값(캐시 없음)
    assert GoldRanking.calc("S150USDT") > GoldRanking.calc("S5USDT")   # 점수식 자체는 그대로
    assert GoldRanking.get_top1(ctx.get_player_map(syms), syms) == "S5USDT"
    assert GoldRanking.get_top1({}, ["S150USDT", "S199USDT"]) == ""     # 실제 값 후보 없음 → Gold 없음
    dm._last_detail_sym = "S150USDT"                       # 선택 종목 — 상세 갱신 실제 값이면 후보
    assert GoldRanking.get_top1({}, syms) == "S150USDT"


# ── 표시 변경: '변동성 등급' → 엔진 Volatility 모드 G4 ATR% 허용 범위 ──────────────
def _params(monkeypatch, **kw):
    from bottom_engine.models import StrategyParams
    p = StrategyParams(sort_mode="Volatility", **kw)
    monkeypatch.setattr(dm_mod.StrategyLoader, "load_or_default", staticmethod(lambda m: p))
    return p


@pytest.mark.parametrize("sl, lev, lo", [(1.2, 20, 0.70), (3.7, 10, 1.85), (0.8, 20, 0.70)])
def test_band_same_formula_as_engine_g4(dm, monkeypatch, sl, lev, lo):
    from bottom_engine.strategy.m4_entry import M4Entry
    p = _params(monkeypatch, stop_loss=sl, leverage=lev)
    band = dm.engine_atr_band("Volatility")
    assert band[1] == 8.0 and band[0] == pytest.approx(lo)
    # 엔진 M4Entry G4 판정과 같은 경계 — 범위 밖이면 G4 사유, 안이면 G4 통과(다음 게이트 사유)
    for atr, inside in ((band[0] - 0.01, False), (band[0], True), (band[1], True), (band[1] + 0.01, False)):
        ok, reason = M4Entry.evaluate("long", {"atr_pct": atr}, p)
        assert reason.startswith("G4") is (not inside), (atr, reason)


def _col1_texts(dm, root):
    import tkinter as tk
    from middle.widget.middle_panel import MiddlePanel
    p = MiddlePanel.__new__(MiddlePanel)
    p._app_state, p._sort_mode = "RANKING", "Volatility"
    p._inner, p._verdict_f = tk.Frame(root), tk.Frame(root)
    p._row_frames, p._special, p._cum_labels, p._change_labels, p._phase_labels = [], {}, {}, {}, {}
    p._m4_labels, p._nl_rows = {}, {}
    p._player_tags_map, p._gold_sym = {}, ""
    p._time_fixed, p._time_fix_prices = False, {}
    p._sel_var = tk.StringVar(root, "")
    dm._rebuild_ranking_rows()
    p._build_ranking_rows(VolatilityScorer.get_sorted(dm.get_ranking_rows(), limit=100))
    out = {}
    for f, sym in p._row_frames:
        out[sym] = []
        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Label):
                    out[sym].append((c.cget("text"), c.cget("fg")))
                walk(c)
        walk(f)
    return out


def test_col1_engine_band_column(dm, monkeypatch):
    import tkinter as tk
    from middle.widget.constants import ORANGE, POSITIVE, DIM_TEXT
    _params(monkeypatch, stop_loss=1.2, leverage=20)       # 범위 0.70~8.0
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    root.withdraw()
    try:
        _put(dm, "S1USDT", 15.59)
        _put(dm, "S2USDT", 1.2)                            # 수정 전 '❄ 저변동 — 스캘핑 부적합' (엔진은 진입 허용)
        _put(dm, "S3USDT", 0.5)
        _put(dm, "S4USDT", 0.0, _atr_ready=False)
        t = _col1_texts(dm, root)
        assert list(t) == ["S1USDT", "S2USDT", "S3USDT", "S4USDT"]
        assert ("15.59%", ORANGE) in t["S1USDT"] and ("▲ 범위 초과 (>8.0%) — 엔진 진입 차단", ORANGE) in t["S1USDT"]
        assert ("✓ 엔진 ATR 범위 (0.70~8.0%)", POSITIVE) in t["S2USDT"]
        assert ("▼ 범위 미만 (<0.70%) — 엔진 진입 차단", DIM_TEXT) in t["S3USDT"]
        assert ("데이터 부족 (1h 봉 15개 미만·조회 실패)", DIM_TEXT) in t["S4USDT"]
        assert not any("스캘핑 부적합" in x for v in t.values() for x, _ in v)
    finally:
        root.destroy()


def test_col3_engine_band_line(dm, monkeypatch):
    _params(monkeypatch, stop_loss=1.2, leverage=20)
    dm._rebuild_ranking_rows()
    _put(dm, "S1USDT", 9.1)
    texts = _verdict_texts("S1USDT", [("S1USDT",)])
    assert "▲ 엔진 ATR 범위 초과 (>8.0%) — 진입 차단" in texts, texts
    _put(dm, "S1USDT", 1.2)
    texts = _verdict_texts("S1USDT", [("S1USDT",)])
    assert "✓ 엔진 ATR 범위 안 (0.70~8.0%) — 다른 진입 조건은 별도" in texts, texts


def test_header_renamed():
    import middle.widget.panel_col1 as pc1
    src = inspect.getsource(pc1)
    assert 'text="엔진 ATR 범위", anchor="center"' in src and '"변동성 등급"' not in src
