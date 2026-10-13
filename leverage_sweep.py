"""
leverage_sweep.py — leverage 4조합 × 150심볼 × 90일
_strategy.json 실거래 값 사용, selected_symbols.json 150심볼
G1 파라미터 고정: rsi_min_diff=3.0, vol_mult=1.5, lookback=20

체크포인트 지원: 중단 후 재실행 시 완료된 심볼 자동 스킵
  checkpoint: leverage_sweep_checkpoint.json (자동 관리, 전체 완료 시 삭제)

결과 저장: leverage_sweep_result.json (프로젝트 루트)

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python leverage_sweep.py
"""
import sys
import time
import json
import pickle
import dataclasses
import pathlib

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from bottom_engine.backtest.backtest_runner import BacktestRunner
from bottom_engine.backtest.historical_data_loader import HistoricalDataLoader
from bottom_engine.constants import _NEW_DAYS_MIN
from bottom_engine.sweep import SweepBucket, assert_sl_is_one_r
from bottom_engine.sweep.base_params import load_symbols, make_base_params, run_metadata, print_metadata

SYMBOLS = load_symbols()

LEVERAGES        = (5, 10, 15, 20)
PERIOD           = "90일"
_CHECKPOINT_PATH = _ROOT / "leverage_sweep_checkpoint.json"
_PERIOD_DAYS     = 90


def _init_buckets() -> list:
    return [{"leverage": lev, "bucket": SweepBucket()} for lev in LEVERAGES]


def _load_checkpoint() -> tuple:
    if not _CHECKPOINT_PATH.exists():
        return set(), _init_buckets()
    with open(_CHECKPOINT_PATH, encoding="utf-8") as f:
        ckpt = json.load(f)
    first = ckpt["buckets"][0] if ckpt["buckets"] else {}
    if "sum_pnl" not in first:
        return set(), _init_buckets()
    buckets = []
    for d, lev in zip(ckpt["buckets"], LEVERAGES):
        bkt = SweepBucket(
            n=d["n"], wins=d["wins"], sum_pnl=d["sum_pnl"],
            sum_pos_pnl=d["sum_pos_pnl"], sum_neg_pnl=d["sum_neg_pnl"],
            one_r_pct=d["one_r_pct"],
        )
        buckets.append({"leverage": lev, "bucket": bkt})
    return set(ckpt["completed"]), buckets


def _save_checkpoint(completed: set, buckets: list) -> None:
    serializable = [
        {"leverage": b["leverage"], **dataclasses.asdict(b["bucket"])}
        for b in buckets
    ]
    with open(_CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump({"completed": list(completed), "buckets": serializable},
                  f, ensure_ascii=False)


def _finalize(buckets: list) -> list:
    results = []
    for b in buckets:
        s = b["bucket"].summary()
        results.append({
            "leverage":  b["leverage"],
            "one_r_pct": s["one_r_pct"],
            "n":         s["n"],
            "wr":        s["wr"],
            "ev_r":      s["ev_r"],
            "pf":        s["pf"],
            "pf_ci":     s["pf_ci"],
        })
    return sorted(results, key=lambda r: r["ev_r"], reverse=True)


def main():
    completed, buckets = _load_checkpoint()

    _meta = run_metadata(make_base_params(), PERIOD, SYMBOLS)
    print_metadata(_meta)
    _base_lev = _meta["params"]["leverage"]
    print(f"[leverage sweep] {len(SYMBOLS)}심볼 × {len(LEVERAGES)}조합 × {PERIOD}")
    print(f"[변동] leverage={LEVERAGES}  ({_base_lev} = _strategy.json 실거래)")
    if completed:
        print(f"[체크포인트] {len(completed)}/{len(SYMBOLS)} 완료, "
              f"{len(SYMBOLS) - len(completed)}개 이어서 실행")
    print("-" * 70)

    t0 = time.time()
    _assert_done = False

    for sym in SYMBOLS:
        s_idx = SYMBOLS.index(sym)
        if sym in completed:
            print(f"  [{s_idx+1}/{len(SYMBOLS)}] {sym} 스킵 (체크포인트)", flush=True)
            continue

        _cache_path = _ROOT / "backtest_cache" / PERIOD / f"{sym}.pkl"
        if _cache_path.exists():
            print(f"  [{s_idx+1}/{len(SYMBOLS)}] {sym} 캐시 로드", flush=True)
            with open(_cache_path, "rb") as _f:
                preloaded = pickle.load(_f)
        else:
            print(f"  [{s_idx+1}/{len(SYMBOLS)}] {sym} API 로딩중...", flush=True)
            preloaded = BacktestRunner.load_tf_bars(sym, PERIOD)
            preloaded["fr"]  = HistoricalDataLoader.load_funding_rate(sym)
            preloaded["liq"] = HistoricalDataLoader.load_long_short_ratio(sym, _PERIOD_DAYS)
            preloaded["1d"]  = HistoricalDataLoader.load(sym, "1d", _NEW_DAYS_MIN + 5)

        for i, lev in enumerate(LEVERAGES):
            _p = make_base_params()
            _p.leverage   = lev
            res = BacktestRunner.run(sym, _p, PERIOD, preloaded=preloaded,
                                     entry_variant="M4", exit_variant="CURRENT")
            buckets[i]["bucket"].add(res)

            if not _assert_done and i == 0:
                ok, msg = assert_sl_is_one_r(res)
                print(f"  [SL검증] {sym}: {msg}")
                _assert_done = True

        completed.add(sym)
        _save_checkpoint(completed, buckets)

    elapsed = time.time() - t0
    results  = _finalize(buckets)

    if _CHECKPOINT_PATH.exists():
        _CHECKPOINT_PATH.unlink()

    baseline = next((r for r in results if r["leverage"] == 20), None)

    print(f"\n[완료] 소요시간 {elapsed / 60:.1f}분  ({len(completed)}/{len(SYMBOLS)} 심볼)\n")
    if baseline:
        print(
            f"[기준선] leverage=20 → EV={baseline['ev_r']:+.4f}R  "
            f"PF={baseline['pf']:.3f}  WR={baseline['wr']:.1f}%  "
            f"N={baseline['n']:.0f}  1R={baseline['one_r_pct']:.2f}%"
        )
    print(f"{'leverage':>9} {'1R%':>6} | "
          f"{'N':>6} {'WR%':>6} {'EV(R)':>9} {'PF':>6} {'PF±CI':>8}  비교")
    print("-" * 70)

    for r in results:
        is_baseline = (r["leverage"] == 20)
        diff_str = "(기준)" if is_baseline else (
            f"({r['ev_r'] - baseline['ev_r']:+.4f}R)" if baseline else "")
        flag = " ← 현재기본값" if is_baseline else ""
        unavail_flag = " ⚠판정불가" if r["one_r_pct"] <= 0 else ""
        print(
            f"{r['leverage']:>9} {r['one_r_pct']:>6.2f} | "
            f"{r['n']:>6.0f} {r['wr']:>6.1f}% {r['ev_r']:>+9.4f} {r['pf']:>6.3f} "
            f"±{r['pf_ci']:>6.3f}  {diff_str}{flag}{unavail_flag}"
        )

    if results:
        best = results[0]
        print("\n" + "=" * 70)
        print(f"[최우수 조합] leverage={best['leverage']}  1R={best['one_r_pct']:.2f}%")
        print(
            f"  N={best['n']:.0f}  WR={best['wr']:.1f}%  "
            f"EV={best['ev_r']:+.4f}R  PF={best['pf']:.3f} ±{best['pf_ci']:.3f}"
        )
        if baseline:
            print(f"  기준선(leverage=20) 대비: {best['ev_r'] - baseline['ev_r']:+.4f}R")
        print("=" * 70)

    out_path = _ROOT / "leverage_sweep_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"meta": _meta, "results": results}, f, indent=2, ensure_ascii=False)
    print(f"\n[저장] {out_path}")

    return results


if __name__ == "__main__":
    main()
