"""
tests/test_backtest_truncation.py
[② 항목 3] 백테스트 미래참조 절단 검사 — 실제 백테스트 캐시 + 실거래 설정(_strategy.json "24h Ticker",
진입 M4 / 청산 CURRENT = 실거래 동일 경로).

Freqtrade lookahead-analysis 방식(freqtrade/optimize/analysis/lookahead.py 139-190):
포지션마다 진입 시각 +1봉, 청산 시각 +1봉까지만 남긴 데이터로 다시 실행해 결과가 같은지 비교.
  - 청산 절단: 절단 시점까지 끝난 모든 거래 행(PARTIAL 포함)의 비교 키가 전체 실행과 같아야 함.
  - 진입 절단: BacktestRunner는 데이터 끝에 열린 포지션을 결과에서 제외하므로 진입 판정은
    M4Entry.evaluate 실제 호출을 관찰해 비교 — 절단 실행의 판정 순서가 전체 실행의 앞부분과 같고,
    해당 진입 판정의 지표 입력(ind)이 전체 실행과 같아야 함.
절단: 1m는 기준 봉 open_time까지, 3m·5m·15m·1h는 그 1m 봉 close_time까지 마감된 봉, fr·liq는 시각 기준.
'1d'는 상장 일수(len)만 쓰이므로 그대로 둠. 네트워크 호출 차단(캐시만 사용).
포지션이 _MIN_POSITIONS 미만이면 판정 불가로 실패 — 심볼·기간 확대 필요.
"""
import bisect
import copy
import pickle
from pathlib import Path

import pytest

from bottom_engine.backtest import historical_data_loader as hdl
from bottom_engine.backtest.backtest_runner import BacktestRunner
from bottom_engine.strategy.m4_entry import M4Entry
from bottom_engine.sweep.base_params import make_base_params

_PERIOD    = "180일"
_CACHE_DIR = Path(__file__).resolve().parents[1] / "backtest_cache" / _PERIOD
# 180일 캐시 중 기간 전체가 채워진 심볼 — 실거래 설정 포지션 수 GRIFFAIN 12(PARTIAL 포함)·DOT 2·BCH 2 (2026-10-25 스캔)
_SYMBOLS       = ("GRIFFAINUSDT", "DOTUSDT", "BCHUSDT")
_MIN_POSITIONS = 10
_BAR_MS        = 60_000
_HTF           = ("3m", "5m", "15m", "1h")
_EXPECTED_BARS = {"1m": 259200, "3m": 86400, "5m": 51840, "15m": 17280, "1h": 3000}
_KEYS          = ("entry_time", "side", "entry_price", "exit_time", "exit_reason", "pnl_pct", "qty_ratio")


class _EntryRecorder:
    """M4Entry.evaluate 실제 호출을 그대로 수행하며 (side, ok)와 진입 판정 입력을 기록."""

    def __init__(self, orig):
        self._orig = orig
        self.calls: list[tuple[str, bool]] = []
        self.ok_inputs: dict[int, dict] = {}

    def __call__(self, side, ind_data, *args, **kwargs):
        ok, reason = self._orig(side, ind_data, *args, **kwargs)
        if ok:
            self.ok_inputs[len(self.calls)] = copy.deepcopy(ind_data)
        self.calls.append((side, ok))
        return ok, reason

    def taken_entries(self) -> list[tuple[int, str]]:
        """백테스트가 실제로 연 진입의 호출 인덱스 — 봉마다 long·short 순서로 2회 호출, long 우선."""
        out = []
        for i in range(0, len(self.calls) - 1, 2):
            (s_l, ok_l), (s_s, ok_s) = self.calls[i], self.calls[i + 1]
            assert (s_l, s_s) == ("long", "short")
            if ok_l:
                out.append((i, "long"))
            elif ok_s:
                out.append((i + 1, "short"))
        return out


def _key(trade) -> tuple:
    return tuple(getattr(trade, k) for k in _KEYS)


def _truncate(data: dict, last_open_1m: int) -> tuple[dict, int]:
    out = dict(data)
    out["1m"] = [b for b in data["1m"] if b.open_time <= last_open_1m]
    cut = out["1m"][-1].close_time
    for tf in _HTF:
        out[tf] = [b for b in data[tf] if b.close_time <= cut]
    for k in ("fr", "liq"):
        times, vals = data[k]
        n = bisect.bisect_right(times, cut)
        out[k] = (list(times[:n]), list(vals[:n]))
    return out, cut


@pytest.fixture
def run_bt(monkeypatch):
    def _blocked(*_a, **_k):
        raise RuntimeError("test_backtest_truncation: 네트워크 호출 차단 — 캐시만 사용")

    for name in dir(hdl.HistoricalDataLoader):
        if name.startswith("load"):
            monkeypatch.setattr(hdl.HistoricalDataLoader, name, staticmethod(_blocked))
    orig = M4Entry.evaluate
    params = make_base_params()

    def _run(sym: str, data: dict):
        rec = _EntryRecorder(orig)
        monkeypatch.setattr(M4Entry, "evaluate", staticmethod(rec))
        res = BacktestRunner.run(sym, params, _PERIOD, preloaded=data,
                                 entry_variant="M4", exit_variant="CURRENT")
        return res, rec

    return _run


def test_backtest_has_no_lookahead_on_truncation(run_bt):
    if not _CACHE_DIR.is_dir():
        pytest.skip(f"백테스트 캐시 없음: {_CACHE_DIR}")
    checked = 0
    for sym in _SYMBOLS:
        data = pickle.load(open(_CACHE_DIR / f"{sym}.pkl", "rb"))
        assert all(len(data.get(k) or []) >= 0.98 * n for k, n in _EXPECTED_BARS.items()), \
            f"{sym} 캐시가 기간 전체를 담고 있지 않음 — 심볼 재선정 필요"
        full, full_rec = run_bt(sym, data)
        rows      = [_key(t) for t in full.trades]
        positions = sorted((t for t in full.trades if t.exit_reason != "PARTIAL"), key=lambda t: t.entry_time)
        taken     = full_rec.taken_entries()
        assert len(taken) >= len(positions)
        for p, (idx, side) in zip(positions, taken):
            assert side == p.side, f"{sym} 진입 순서 매핑 오류"

            # ── 청산 절단: 청산 봉 +1봉 (exit_time = 청산 1m 봉 close_time = open_time + 59999) ──
            exit_open        = p.exit_time - (_BAR_MS - 1)
            data_x, cut_x    = _truncate(data, exit_open + _BAR_MS)
            cut_res, _       = run_bt(sym, data_x)
            assert [_key(t) for t in cut_res.trades] == [r for r in rows if r[3] <= cut_x], \
                f"{sym} 청산 절단 불일치 — entry {p.entry_time} exit {p.exit_time} {p.exit_reason}"

            # ── 진입 절단: 진입 봉 +1봉 ──
            data_e, cut_e = _truncate(data, p.entry_time + _BAR_MS)
            ent_res, ent_rec = run_bt(sym, data_e)
            assert len(ent_rec.calls) > idx, f"{sym} 진입 절단 실행에서 진입 판정 미도달 — entry {p.entry_time}"
            assert ent_rec.calls[:idx + 1] == full_rec.calls[:idx + 1], \
                f"{sym} 진입 판정 순서 불일치 — entry {p.entry_time}"
            assert ent_rec.ok_inputs.get(idx) == full_rec.ok_inputs[idx], \
                f"{sym} 진입 판정 지표 입력 불일치 — entry {p.entry_time}"
            assert [_key(t) for t in ent_res.trades] == [r for r in rows if r[3] <= cut_e], \
                f"{sym} 진입 절단 시 이전 거래 불일치 — entry {p.entry_time}"
            checked += 1
    assert checked >= _MIN_POSITIONS, f"판정 불가: 포지션 {checked}건 < {_MIN_POSITIONS} — 심볼·기간 확대 필요"
