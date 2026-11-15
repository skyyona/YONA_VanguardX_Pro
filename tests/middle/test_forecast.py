"""
tests/middle/test_forecast.py
가격 예고 (2026-11-09)
 1단계: 봉 체결 매수량(REST k[9]·WS "V") · OI 이력 {timestamp: OI}
 2단계: compute_features 손계산 대조·부족/불연속/OI 없음 → None · Forecaster 표시 규칙(채택·실사용 탈락·방향 충돌)
 3단계: data_manager 24h 상위 100·선택 종목 판정 → 캐시·기록 파일·화면 갱신 콜백, 선택 종목 최근 마감 기준 재계산
 5단계: 3열 종합 분석 맨 위 표시 (판정식 없음·계산 중·문구+근거 수치)
네트워크 조회만 대역.
"""
import json
import math
import time
import tkinter as tk

import pytest

import middle.data.data_manager as dm_mod
import middle.widget.panel_col3 as col3
from middle.data.data_manager import MiddleDataManager
from middle.models import SymbolTicker
from middle.widget.panel_col3 import _Col3Mixin

from middle.models import OHLCVBar
from middle.data.ohlcv_data import parse_kline_row, _parse_klines
from middle.data.open_interest_data import OpenInterestFetcher
from middle.analysis import forecast as fc
from middle.analysis.forecast import compute_features, Forecaster, FEATURE_NAMES, STEP_MS, BARS_NEEDED

T0 = 1_790_000_000_000 // STEP_MS * STEP_MS


# ── 1단계: 데이터 ─────────────────────────────────────────────
def test_parse_kline_row_reads_taker_buy_volume():
    k = [T0, "1.0", "2.0", "0.5", "1.5", "100.0", T0 + STEP_MS - 1, "150.0", 42, "61.5", "92.25", "0"]
    b = parse_kline_row(k)
    assert (b.volume, b.quote_volume, b.taker_buy_volume) == (100.0, 150.0, 61.5)
    assert _parse_klines([k, k]) == [b]          # 마지막 원소(진행 중 봉) 제외 규칙 유지


def test_oi_fetch_series_maps_timestamp_to_value():
    class _C:
        def fetch_open_interest_hist(self, sym, period, limit):
            self.args = (sym, period, limit)
            return [{"timestamp": T0, "sumOpenInterest": "10.5"}, {"timestamp": "bad"},
                    {"timestamp": T0 + STEP_MS, "sumOpenInterest": "11"}]
    c = _C()
    assert OpenInterestFetcher(c).fetch_series("AUSDT") == {T0: 10.5, T0 + STEP_MS: 11.0}
    assert c.args == ("AUSDT", "5m", 290)


# ── 2단계: 지표 ───────────────────────────────────────────────
def _bars(n, price=lambda i: 100.0 + i * 0.01, vol=lambda i: 10.0, taker=lambda i: 5.0, hi=None):
    out = []
    for i in range(n):
        p = price(i); o = price(i - 1) if i else p
        h = hi(i) if hi else max(o, p)
        out.append(OHLCVBar(T0 + i * STEP_MS, o, h, min(o, p), p, vol(i), vol(i) * p, T0 + (i + 1) * STEP_MS - 1, taker(i)))
    return out


def _oi(bars, val=lambda k: 1000.0 + k):
    """봉 마감 시각마다 OI (k = 마감 시각 순번)."""
    return {b.close_time + 1: val(k) for k, b in enumerate(bars)} | {bars[0].open_time: val(-1)}


def test_features_match_hand_calculation():
    bars = _bars(BARS_NEEDED, vol=lambda i: 20.0 if i >= BARS_NEEDED - 48 else 10.0,
                 taker=lambda i: 15.0 if i >= BARS_NEEDED - 12 else 5.0,
                 hi=lambda i: 200.0 if i == 100 else None or 100.0 + i * 0.01)
    oi = _oi(bars)
    f = compute_features(bars, oi)
    c = bars[-1].close
    assert f["r1h"] == pytest.approx((c / bars[-13].close - 1) * 100)
    assert f["r4h"] == pytest.approx((c / bars[-49].close - 1) * 100)
    assert f["r24"] == pytest.approx((c / bars[-288].open - 1) * 100)
    assert f["dd_high"] == pytest.approx((c / 200.0 - 1) * 100)
    assert f["high_age_h"] == pytest.approx((BARS_NEEDED - 1 - 100) / 12)
    t = bars[-1].close_time + 1
    assert f["oi1h"] == pytest.approx((oi[t] / oi[t - 12 * STEP_MS] - 1) * 100)
    assert f["oi24h"] == pytest.approx((oi[t] / oi[t - 288 * STEP_MS] - 1) * 100)
    assert f["taker1h"] == pytest.approx(math.log(15.0 * 12 / (20.0 * 12 - 15.0 * 12)))
    assert f["vol4h_vs_24h"] == pytest.approx(math.log(20.0 * 48 / (10.0 * 240 / 5)))
    assert f["dd_if_pumped"] == 0.0                 # r24 < 15
    assert list(f) == list(FEATURE_NAMES)


def test_features_none_when_short_gapped_or_no_oi():
    bars = _bars(BARS_NEEDED)
    oi = _oi(bars)
    assert compute_features(bars[1:], oi) is None                                   # 봉 부족
    gap = bars[:150] + [OHLCVBar(**{**b.__dict__, "open_time": b.open_time + STEP_MS}) for b in bars[150:]]
    assert compute_features(gap, oi) is None                                       # 불연속
    t = bars[-1].close_time + 1
    assert compute_features(bars, {k: v for k, v in oi.items() if k != t}) is None  # 마감 시각 OI 없음
    assert compute_features(bars, oi) is not None


# ── 2단계: 표시 규칙 ──────────────────────────────────────────
def _params(adopted=("peak_drop", "down", "early_up", "big_move"), live=None):
    live = live or {}
    nf = len(FEATURE_NAMES)
    lab = lambda k, m, rng, d, ctx: {"key": k, "context": ctx, "model": m, "r24_range": rng, "threshold": 0.5,
                                     "direction": d, "adopted": k in adopted, "live_status": live.get(k, "검증 중")}
    return {"features": list(FEATURE_NAMES), "mu": [0.0] * nf, "sd": [1.0] * nf,
            "models": {m: {"w": [0.0] * nf, "b": 0.0} for m in ("dn", "up", "big")},
            "labels": [x for ctx in ("list", "all") for x in (
                lab("peak_drop", "dn", [15, 1e9], "S", ctx), lab("down", "dn", [-1e9, 15], "S", ctx),
                lab("early_up", "up", [-1e9, 15], "L", ctx), lab("big_move", "big", [-1e9, 15], "A", ctx))]}


def _feats(r24):
    return {n: 0.0 for n in FEATURE_NAMES} | {"r24": r24}


def _set_bias(p, **b):
    for m, v in b.items():
        p["models"][m]["b"] = v
    return p


def test_display_picks_priority_label_and_live_status():
    f = Forecaster(_set_bias(_params(), dn=2.0, up=-2.0, big=-2.0))   # 하락 점수만 높음
    r = f.judge(_feats(20.0))
    assert r["labels"] == ["peak_drop"]
    assert f.display(r) == (fc.LABEL_TEXT["peak_drop"], "실사용 검증 중")
    r = f.judge(_feats(5.0))
    assert r["labels"] == ["down"]


def test_not_adopted_or_failed_live_is_hidden():
    f = Forecaster(_set_bias(_params(adopted=("down",)), dn=-2.0, up=2.0, big=-2.0))
    r = f.judge(_feats(5.0))
    assert r["labels"] == ["early_up"] and r["shown"] == []
    assert f.display(r) == (fc.NO_SIGNAL_TEXT, "")
    f = Forecaster(_set_bias(_params(live={"down": "탈락"}), dn=2.0, up=-2.0, big=-2.0))
    assert f.display(f.judge(_feats(5.0)))[0] == fc.NO_SIGNAL_TEXT
    f = Forecaster(_set_bias(_params(live={"down": "통과"}), dn=2.0, up=-2.0, big=-2.0))
    assert f.display(f.judge(_feats(5.0))) == (fc.LABEL_TEXT["down"], "실사용 검증 통과")


def test_no_adopted_label_says_so_instead_of_no_signal():
    f = Forecaster(_set_bias(_params(adopted=()), dn=2.0, up=-2.0, big=-2.0))
    assert f.display(f.judge(_feats(5.0))) == (fc.NONE_ADOPTED_TEXT, "")
    f = Forecaster(_set_bias(_params(adopted=("down",), live={"down": "탈락"}), dn=2.0, up=-2.0, big=-2.0))
    assert f.display(f.judge(_feats(5.0)))[0] == fc.NONE_ADOPTED_TEXT


def test_context_selects_its_own_thresholds_and_adoption():
    p = _set_bias(_params(), dn=0.5, up=-2.0, big=-2.0)           # 하락 점수 0.62
    for lab in p["labels"]:
        if lab["context"] == "list" and lab["key"] == "down":
            lab["threshold"] = 0.7                                   # 목록 조건 경계가 더 높음
    f = Forecaster(p)
    assert f.judge(_feats(5.0), in_list=False)["labels"] == ["down"]
    assert f.judge(_feats(5.0), in_list=True)["labels"] == []
    p2 = _set_bias(_params(), dn=2.0, up=-2.0, big=-2.0)
    for lab in p2["labels"]:
        lab["adopted"] = lab["context"] == "all"                   # 목록 조건은 채택 표시 없음
    f2 = Forecaster(p2)
    assert f2.display(f2.judge(_feats(5.0), in_list=True)) == (fc.NONE_ADOPTED_TEXT, "")
    assert f2.display(f2.judge(_feats(5.0), in_list=False))[0] == fc.LABEL_TEXT["down"]


def test_range_without_adopted_label_says_out_of_range():
    """C-1: 채택 표시가 맡지 않는 24h 변동률 구간(예: +15% 이상 급등, 고점 이탈 미채택)은 '평소 수준'이 아니라 '판정 범위 밖'."""
    f = Forecaster(_set_bias(_params(adopted=("big_move",)), dn=-2.0, up=-2.0, big=-2.0))
    assert f.display(f.judge(_feats(20.0), in_list=True)) == (fc.OUT_OF_RANGE_TEXT, "")
    assert f.display(f.judge(_feats(5.0), in_list=True)) == (fc.NO_SIGNAL_TEXT, "")
    f2 = Forecaster(_set_bias(_params(adopted=("big_move", "peak_drop")), dn=-2.0, up=-2.0, big=-2.0))
    assert f2.display(f2.judge(_feats(20.0), in_list=True)) == (fc.NO_SIGNAL_TEXT, "")   # 맡는 표시가 있으면 평소 수준


def test_log_path_per_params_version():
    """C-3: 판정식 버전(학습 시각)별 기록 파일."""
    assert fc.log_path("2026-11-10T00:22:43").name == "forecast_log_20261110T002243.csv"
    assert fc.log_path("2026-12-08T03:00:00") != fc.log_path("2026-11-10T00:22:43")
    assert Forecaster({"trained_at": "2026-11-10T00:22:43"}).version == "2026-11-10T00:22:43"


def test_conflicting_directions_show_big_move_only_if_it_triggers():
    f = Forecaster(_set_bias(_params(), dn=2.0, up=2.0, big=-2.0))
    assert f.display(f.judge(_feats(5.0)))[0] == fc.NO_SIGNAL_TEXT
    f = Forecaster(_set_bias(_params(), dn=2.0, up=2.0, big=2.0))
    assert f.display(f.judge(_feats(5.0)))[0] == fc.LABEL_TEXT["big_move"]


def test_missing_or_mismatched_params_disable(tmp_path):
    assert Forecaster.load(tmp_path / "none.json").ok is False
    p = _params(); p["features"] = p["features"][:-1]
    path = tmp_path / "p.json"; path.write_text(json.dumps(p), encoding="utf-8")
    f = Forecaster.load(path)
    assert f.ok is False and f.display(f.judge(_feats(5.0)))[0] == fc.NONE_ADOPTED_TEXT


# ── 3단계: data_manager 판정·기록 ────────────────────────────
class _Bars5m:
    def __init__(self, end_ms):
        self.end, self.calls = end_ms, []

    def fetch(self, sym, tf, limit=None):
        self.calls.append((sym, tf, limit))
        n = limit - 1
        start = self.end - n * STEP_MS
        return [OHLCVBar(start + i * STEP_MS, 100.0, 100.5, 99.5, 100.0 + i * 0.01, 10.0, 1000.0,
                         start + (i + 1) * STEP_MS - 1, 5.0) for i in range(n)]


class _OISeries:
    def __init__(self, end_ms):
        self.end, self.calls = end_ms, []

    def fetch_series(self, sym, period="5m", limit=290):
        self.calls.append((sym, period, limit))
        return {self.end - k * STEP_MS: 1000.0 + k for k in range(limit)}


def _fc_dm(monkeypatch, tmp_path, n_syms=3, selected=""):
    end = (int(time.time() * 1000) // STEP_MS) * STEP_MS
    dm = MiddleDataManager()
    dm._ohlcv_svc, dm._oi_svc = _Bars5m(end), _OISeries(end)
    dm._forecaster = Forecaster(_set_bias(_params(adopted=("down",)), dn=2.0, up=-2.0, big=-2.0))
    dm._tickers = [SymbolTicker(f"S{i}USDT", 100.0, 1.0, 10.0 - i, 1e6, 101.0, 99.0) for i in range(n_syms)]
    dm._last_detail_sym = selected
    dm._forecast_log = tmp_path / "forecast_log.csv"
    return dm, end


def test_refresh_forecasts_caches_logs_and_notifies_selected(monkeypatch, tmp_path):
    dm, end = _fc_dm(monkeypatch, tmp_path, selected="SELUSDT")
    seen = []
    dm._on_detail_ready_cb = seen.append
    dm._refresh_forecasts()
    syms = ["S0USDT", "S1USDT", "S2USDT", "SELUSDT"]                  # 24h 변동률 순 + 목록 밖 선택 종목
    assert sorted(c[0] for c in dm._ohlcv_svc.calls) == sorted(syms)
    assert {c[1:] for c in dm._ohlcv_svc.calls} == {("5m", 300)}      # 5m 300 (엔진용 5m 200 표와 별개)
    assert {c[1:] for c in dm._oi_svc.calls} == {("5m", 290)}
    r = dm.get_forecast("S0USDT")
    assert r["t"] == end and r["text"] == fc.LABEL_TEXT["down"] and r["status"] == "실사용 검증 중"
    lines = (tmp_path / "forecast_log.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "t_close,symbol,context,price,r24,score_dn,score_up,score_big,labels,shown"
    assert len(lines) == 1 + len(syms) and lines[1].startswith(f"{end},S0USDT,list,")
    assert lines[-1].startswith(f"{end},SELUSDT,all,")                  # 목록 밖 선택 종목 = 그 밖 조건
    assert dm.get_forecast("SELUSDT")["result"]["context"] == "all"
    assert seen == ["SELUSDT"]


def test_refresh_forecasts_skips_when_params_missing(monkeypatch, tmp_path):
    dm, _ = _fc_dm(monkeypatch, tmp_path)
    dm._forecaster = Forecaster(None)
    dm._refresh_forecasts()
    assert dm._ohlcv_svc.calls == [] and not (tmp_path / "forecast_log.csv").exists()


def test_selected_forecast_recomputes_only_when_older_than_last_close(monkeypatch, tmp_path):
    dm, end = _fc_dm(monkeypatch, tmp_path, selected="AUSDT")
    seen = []
    dm._on_detail_ready_cb = seen.append
    dm._refresh_selected_forecast("AUSDT")
    dm._refresh_selected_forecast("AUSDT")
    last_close = (int(time.time() * 1000) - 60_000) // STEP_MS * STEP_MS
    expected = 1 if end >= last_close else 2
    assert len(dm._ohlcv_svc.calls) == expected and seen == ["AUSDT"] * expected
    assert not (tmp_path / "forecast_log.csv").exists()               # 클릭 계산은 기록하지 않음 (15분 표본만)


def test_latest_close_oi_not_published_uses_previous_bar(monkeypatch, tmp_path):
    dm, end = _fc_dm(monkeypatch, tmp_path)
    full = dm._oi_svc.fetch_series
    dm._oi_svc.fetch_series = lambda sym, period="5m", limit=290: {k: v for k, v in full(sym).items() if k != end}
    dm._refresh_forecasts()
    r = dm.get_forecast("S0USDT")
    assert r["t"] == end - STEP_MS and r["feats"] is not None          # 직전 마감 봉으로 판정


def test_forecast_due_waits_after_close_on_start_and_runs_once_per_cycle():
    """A: 15분 마감 + 240초마다 1회. 시작이 마감 후 240초 안이면 정기 실행을 기다림 (같은 봉 두 번 판정 방지)."""
    cyc, delay = dm_mod._FORECAST_CYCLE_MS, dm_mod._FORECAST_DELAY_MS
    assert delay == 240_000
    b = 1_794_318_300_000 // cyc * cyc                     # 15분 마감 시각
    dm = MiddleDataManager()
    assert dm._forecast_due(b + 79_000) is False           # 11-10 23:01:19 시작 사례 — 바로 실행 안 함
    assert dm._forecast_due(b + 239_000) is False
    assert dm._forecast_due(b + 240_000) is True           # 정기 실행
    assert dm._forecast_due(b + 600_000) is False          # 같은 구간 재실행 없음
    assert dm._forecast_due(b + cyc + 240_000) is True     # 다음 구간
    dm2 = MiddleDataManager()
    assert dm2._forecast_due(b + 420_000) is True          # 대기 시간 밖 시작 → 바로 실행
    assert dm2._forecast_due(b + cyc + 239_000) is False
    assert dm2._forecast_due(b + cyc + 240_000) is True
    dm2.stop_auto_refresh()                                # STOP → START 도 시작 규칙 적용
    assert dm2._forecast_slot == -1 and dm2._forecast_due(b + 2 * cyc + 100_000) is False


def _log_rows(tmp_path):
    return (tmp_path / "forecast_log.csv").read_text(encoding="utf-8").splitlines()[1:]


def test_same_bar_is_logged_once_even_after_restart(monkeypatch, tmp_path):
    """B: 같은 봉 재판정(시작 직후 두 번·STOP→START·앱 재시작)은 기록하지 않음 — 재시작 후엔 파일 끝에서 이어받음."""
    dm, end = _fc_dm(monkeypatch, tmp_path)
    dm._refresh_forecasts()
    dm._refresh_forecasts()                                # 같은 봉 두 번 판정
    assert len(_log_rows(tmp_path)) == 3
    dm2, _ = _fc_dm(monkeypatch, tmp_path)                 # 새 프로세스(기록 상태 없음)
    dm2._refresh_forecasts()
    assert len(_log_rows(tmp_path)) == 3
    dm3, _ = _fc_dm(monkeypatch, tmp_path)
    dm3._ohlcv_svc, dm3._oi_svc = _Bars5m(end + 3 * STEP_MS), _OISeries(end + 3 * STEP_MS)   # 다음 15분 봉
    dm3._refresh_forecasts()
    rows = _log_rows(tmp_path)
    assert len(rows) == 6 and all(r.startswith(f"{end + 3 * STEP_MS},") for r in rows[3:])


def test_older_fallback_bar_after_newer_is_not_logged(monkeypatch, tmp_path):
    """B: 이미 최신 봉을 기록한 뒤 OI 미게시로 직전 봉 대체 판정이 나와도 기록하지 않음 (화면 기록은 갱신)."""
    dm, end = _fc_dm(monkeypatch, tmp_path)
    dm._refresh_forecasts()
    full = dm._oi_svc.fetch_series
    dm._oi_svc.fetch_series = lambda sym, period="5m", limit=290: {k: v for k, v in full(sym).items() if k != end}
    dm._refresh_forecasts()
    assert len(_log_rows(tmp_path)) == 3
    assert dm.get_forecast("S0USDT")["t"] == end - STEP_MS


def test_read_logged_times_reads_tail_and_skips_cut_line(tmp_path):
    p = tmp_path / "log.csv"
    lines = ["t_close,symbol,context,price,r24,score_dn,score_up,score_big,labels,shown"]
    lines += [f"{1000 + k},S{k % 7}USDT,list,1,0,0,0,0,," for k in range(5000)]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    got = dm_mod._read_logged_times(p, tail_bytes=2_000)
    assert got == {f"S{s}USDT": max(1000 + k for k in range(5000) if k % 7 == s) for s in range(7)}
    assert dm_mod._read_logged_times(tmp_path / "none.csv") == {}


def test_insufficient_data_shows_hold_and_is_not_logged(monkeypatch, tmp_path):
    dm, end = _fc_dm(monkeypatch, tmp_path, selected="S0USDT")
    seen = []
    dm._on_detail_ready_cb = seen.append
    dm._oi_svc.fetch_series = lambda sym, period="5m", limit=290: {}
    dm._refresh_forecasts()
    r = dm.get_forecast("S0USDT")
    assert r["t"] == end - STEP_MS and r["feats"] is None and r["text"] == fc.INSUFFICIENT_TEXT   # 직전 봉으로도 불가
    assert not (tmp_path / "forecast_log.csv").exists()
    dm._forecast.clear()
    dm._refresh_selected_forecast("S0USDT")                            # 같은 5분 구간에 이미 계산 → 다시 조회 안 함 (C-6)
    assert dm.get_forecast("S0USDT") is None
    dm._forecast_checked.clear()                                       # 다음 5분 구간
    dm._refresh_selected_forecast("S0USDT")                            # 선택 종목 판단 보류도 화면 갱신
    assert dm.get_forecast("S0USDT")["text"] == fc.INSUFFICIENT_TEXT and seen[-1] == "S0USDT"


def test_selected_hold_symbol_not_refetched_within_same_5m_slot(monkeypatch, tmp_path):
    """C-6: 판단 보류 종목을 30초마다 다시 조회하지 않음 — 같은 5분 구간 1회."""
    dm, end = _fc_dm(monkeypatch, tmp_path, selected="AUSDT")
    dm._oi_svc.fetch_series = lambda sym, period="5m", limit=290: {}
    dm._refresh_selected_forecast("AUSDT")
    n = len(dm._ohlcv_svc.calls)
    dm._refresh_selected_forecast("AUSDT")
    dm._refresh_selected_forecast("AUSDT")
    assert n == 1 and len(dm._ohlcv_svc.calls) == 1


def test_transient_failure_keeps_previous_valid_forecast(monkeypatch, tmp_path):
    """C-4: 조회 일시 실패(빈 응답)면 30분 안의 직전 정상 판정 유지 — '휴장·신규 상장' 오표시 없음."""
    dm, end = _fc_dm(monkeypatch, tmp_path)
    dm._refresh_forecasts()
    good = dm.get_forecast("S0USDT")
    assert good["feats"] is not None
    dm._ohlcv_svc.fetch = lambda sym, tf, limit=None: []               # 다음 주기 조회 실패
    dm._forecast_checked.clear()
    dm._refresh_forecasts()
    assert dm.get_forecast("S0USDT") is good
    monkeypatch.setattr(dm_mod, "_FORECAST_KEEP_MS", -1)               # 유지 한도 지남
    dm._refresh_forecasts()
    assert dm.get_forecast("S0USDT")["text"] == fc.INSUFFICIENT_TEXT


def test_cycle_also_judges_volume_top100_outside_list_as_all(monkeypatch, tmp_path):
    """C-2: 24h 목록('list') 밖 거래량 상위 100도 'all' 조건으로 판정·기록 — 그 밖 조건 실사용 검증 표본."""
    dm, end = _fc_dm(monkeypatch, tmp_path, n_syms=3)
    vol_only = SymbolTicker("VOLUSDT", 100.0, 1.0, -3.0, 9e9, 101.0, 99.0)
    dm._tickers.append(vol_only)
    dm._sorted_tickers = sorted(dm._tickers, key=lambda t: -t.volume_usdt)
    monkeypatch.setattr(dm_mod, "_FORECAST_TOPN", 3)                   # 24h 상위 3 = S0·S1·S2, 거래량 상위 3에 VOL 포함
    dm._refresh_forecasts()
    rows = _log_rows(tmp_path)
    ctx = {r.split(",")[1]: r.split(",")[2] for r in rows}
    assert ctx == {"S0USDT": "list", "S1USDT": "list", "S2USDT": "list", "VOLUSDT": "all"}


# ── 5단계: 3열 표시 ───────────────────────────────────────────
class _Panel(_Col3Mixin):
    def __init__(self, root):
        self._verdict_f = tk.Frame(root)


def _texts(frame):
    out = []
    for w in frame.winfo_children():
        out += [w.cget("text")] if isinstance(w, tk.Label) else _texts(w)
    return out


@pytest.fixture
def root():
    r = tk.Tk(); r.withdraw()
    yield r
    r.destroy()


def test_render_forecast_states(monkeypatch, root):
    p = _Panel(root)
    monkeypatch.setattr(col3, "forecast_enabled", lambda: False)
    monkeypatch.setattr(col3, "get_forecast", lambda s: None)
    p._render_forecast("AUSDT")
    assert _texts(p._verdict_f)[:3] == ["🔮 가격 예고 (12시간)", "─ 판정식 없음", "  forecast_params.json 학습 필요"]
    for w in p._verdict_f.winfo_children(): w.destroy()
    monkeypatch.setattr(col3, "forecast_enabled", lambda: True)
    p._render_forecast("AUSDT")
    assert "─ 계산 중" in _texts(p._verdict_f)
    for w in p._verdict_f.winfo_children(): w.destroy()
    feats = {n: 0.0 for n in FEATURE_NAMES} | {"r24": 18.04, "dd_high": -1.52, "oi4h": -4.07}
    t = 1_794_200_400_000
    monkeypatch.setattr(col3, "get_forecast", lambda s: {"t": t, "feats": feats, "text": fc.LABEL_TEXT["peak_drop"],
                                                         "status": "실사용 검증 중"})
    p._render_forecast("AUSDT")
    tx = _texts(p._verdict_f)
    assert tx[1] == "▼ 급등 고점 이탈" and tx[2] == "  12시간 내 하락 전환 가능성 높음"
    from datetime import datetime
    assert tx[3] == f"{datetime.fromtimestamp(t / 1000):%H:%M} 판정 · 24h +18.0% · 고점 대비 -1.5% · OI 4h -4.1% · 실사용 검증 중"
    for w in p._verdict_f.winfo_children(): w.destroy()
    monkeypatch.setattr(col3, "get_forecast", lambda s: {"t": t, "feats": None, "text": fc.INSUFFICIENT_TEXT, "status": ""})
    p._render_forecast("AUSDT")
    assert _texts(p._verdict_f) == ["🔮 가격 예고 (12시간)", "─ 판단 보류", "  5분 봉·OI 24시간 연속 기록 부족 (휴장·신규 상장 등)"]
