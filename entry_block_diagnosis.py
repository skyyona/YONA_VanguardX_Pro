"""
entry_block_diagnosis.py — 진입 차단 사유 진단 (150심볼 × 180일)
_strategy.json "24h Ticker" 실거래 값 사용, selected_symbols.json 150심볼

M4Entry.evaluate() 반환 사유(첫 번째로 막은 게이트)를 심볼·방향별로 집계한다.
  - all    : 평가된 모든 1m 봉
  - signal : 해당 방향 G1 다이버전스가 발생한 봉만 (신호가 있었는데 무엇이 막았는가)
엔진·전략 코드는 수정하지 않는다. 이 스크립트 실행 중에만 evaluate 를 감싸 집계 후 원복한다.

결과 저장: entry_block_diagnosis_result.json (프로젝트 루트)

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python entry_block_diagnosis.py
"""
import sys
import json
import time
import pickle
import pathlib
from collections import Counter

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from bottom_engine.backtest.backtest_runner import BacktestRunner
from bottom_engine.backtest.historical_data_loader import HistoricalDataLoader
from bottom_engine.constants import _NEW_DAYS_MIN
from bottom_engine.strategy.m4_entry import M4Entry
from bottom_engine.sweep.base_params import load_symbols, make_base_params, run_metadata, print_metadata

SYMBOLS      = load_symbols()
PERIOD       = "180일"
_PERIOD_DAYS = 180
_RESULT_PATH = _ROOT / "entry_block_diagnosis_result.json"

_CATS = ["PASS", "G0", "G4", "G5", "G6", "G_K", "G_ema", "G1", "G1_vol", "G2", "G7.5",
         "G8_liq", "G8_fr", "G8_new", "G8_other"]


def classify(ok: bool, reason: str) -> str:
    """M4Entry.evaluate 사유 문자열 → 게이트 분류."""
    if ok:
        return "PASS"
    if reason.startswith("G1: 거래량"):
        return "G1_vol"
    for key in ("G_ema", "G_K", "G4", "G5", "G6", "G1", "G2"):
        if reason.startswith(key + ":"):
            return key
    if reason.startswith("["):
        return "G0"
    if reason.startswith("거시 추세"):
        return "G7.5"
    if "청산가 근접도" in reason:
        return "G8_liq"
    if reason.startswith("FR"):
        return "G8_fr"
    if reason.startswith("신규 상장"):
        return "G8_new"
    return "G8_other"


def _new_counters() -> dict:
    return {kind: {"long": Counter(), "short": Counter()} for kind in ("all", "signal")}


def _pct_table(counter: Counter) -> dict:
    total = sum(counter.values())
    return {c: (counter[c], (counter[c] / total * 100.0) if total else 0.0) for c in _CATS}


def _print_group(title: str, rows: list) -> None:
    for side in ("long", "short"):
        sig = Counter()
        for r in rows:
            sig.update(r["signal"][side])
        total = sum(sig.values())
        print(f"  [{title}] {side:<5} 신호 발생 봉 {total:,}")
        for c, (n, p) in _pct_table(sig).items():
            if n:
                print(f"      {c:<9} {n:>9,}  {p:5.1f}%")


def main():
    params = make_base_params()
    _meta = run_metadata(params, PERIOD, SYMBOLS)
    print_metadata(_meta)
    print(f"[진입 차단 진단] {len(SYMBOLS)}심볼 × {PERIOD}")
    print("-" * 70)

    t0 = time.time()
    preloaded_cache: dict = {}
    for sym in SYMBOLS:
        _cache_path = _ROOT / "backtest_cache" / PERIOD / f"{sym}.pkl"
        if _cache_path.exists():
            with open(_cache_path, "rb") as f:
                preloaded_cache[sym] = pickle.load(f)
        else:
            print(f"  캐시 없음: {sym} — API 로딩중...", flush=True)
            preloaded_cache[sym] = BacktestRunner.load_tf_bars(sym, PERIOD)
            preloaded_cache[sym]["fr"]  = HistoricalDataLoader.load_funding_rate(sym)
            preloaded_cache[sym]["liq"] = HistoricalDataLoader.load_long_short_ratio(sym, _PERIOD_DAYS)
            preloaded_cache[sym]["1d"]  = HistoricalDataLoader.load(sym, "1d", _NEW_DAYS_MIN + 5)
    print(f"[캐시 로드] {time.time() - t0:.1f}초\n")

    _orig = M4Entry.evaluate
    _cur: dict = {}

    def _counting(side, ind_data, p, **kw):
        ok, reason = _orig(side, ind_data, p, **kw)
        cat = classify(ok, reason)
        _cur["c"]["all"][side][cat] += 1
        if ind_data.get("rsi_div_bull" if side == "long" else "rsi_div_bear", False):
            _cur["c"]["signal"][side][cat] += 1
        return ok, reason

    rows: list = []
    M4Entry.evaluate = staticmethod(_counting)
    try:
        for idx, sym in enumerate(SYMBOLS, 1):
            _cur["c"] = _new_counters()
            res = BacktestRunner.run(sym, params, PERIOD,
                                     preloaded=preloaded_cache[sym],
                                     entry_variant="M4", exit_variant="CURRENT")
            c = _cur["c"]
            rows.append({
                "symbol":    sym,
                "trades":    sum(tr.qty_ratio for tr in res.trades),
                "evaluated": sum(c["all"]["long"].values()),
                "all":       {s: dict(c["all"][s]) for s in ("long", "short")},
                "signal":    {s: dict(c["signal"][s]) for s in ("long", "short")},
            })
            if idx % 25 == 0:
                print(f"  진행 {idx}/{len(SYMBOLS)}  ({time.time() - t0:.0f}초)", flush=True)
    finally:
        M4Entry.evaluate = staticmethod(_orig)

    elapsed = time.time() - t0
    zero    = [r for r in rows if r["trades"] == 0]
    traded  = [r for r in rows if r["trades"] > 0]
    no_eval = [r["symbol"] for r in rows if r["evaluated"] == 0]
    no_sig  = [r["symbol"] for r in zero
               if not r["signal"]["long"] and not r["signal"]["short"]]

    print(f"\n[결과]  (소요시간 {elapsed/60:.1f}분)")
    print(f"  거래 발생 심볼 {len(traded)} / 거래 0건 심볼 {len(zero)} / 평가 0회 심볼 {len(no_eval)}")
    print(f"  거래 0건 중 G1 신호 자체가 없던 심볼 {len(no_sig)}")
    print("=" * 70)
    print("  신호 발생 봉에서 첫 번째로 막은 게이트 (PASS = 진입 허용)")
    _print_group("거래 0건 심볼", zero)
    _print_group("거래 발생 심볼", traded)
    print("=" * 70)

    with open(_RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "meta":           _meta,
            "elapsed_min":    elapsed / 60.0,
            "symbols_traded": len(traded),
            "symbols_zero":   len(zero),
            "no_eval":        no_eval,
            "zero_no_signal": no_sig,
            "by_symbol":      rows,
        }, f, indent=2, ensure_ascii=False)
    print(f"[저장] {_RESULT_PATH.name}")


if __name__ == "__main__":
    main()
