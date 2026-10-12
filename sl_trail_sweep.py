"""
SL 확장 sweep — 150심볼 × 4조합 × 180일
_strategy.json "24h Ticker" 실거래 기준(leverage=20) SL/trail 최적 조합 탐색
trail=0.4 고정 (선행 탐색에서 trail=0.4가 모든 SL 구간에서 최우수)
현재 실거래 파라미터(SL=2.9%, trail=1.2%)가 기준선으로 포함됨

체크포인트 지원: 중단 후 재실행 시 완료된 심볼 자동 스킵
  checkpoint: sl_trail_sweep_180d_checkpoint.json (자동 관리, 전체 완료 시 삭제)

결과 저장: sl_trail_sweep_180d_result.json (프로젝트 루트)

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python sl_trail_sweep.py
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
from bottom_engine.sweep.base_params import load_symbols, make_base_params

SYMBOLS = load_symbols()

# (stop_loss%, trail_stop%) 조합
SL_TRAIL_COMBOS = [
    (1.8, 0.7),   # 구 실거래 파라미터 (이전 기준선)
    (2.5, 0.4),   # 선행 90일 탐색 EV 양수 확인
    (2.9, 1.2),   # 현재 실거래 파라미터 (기준선)
    (3.0, 0.4),   # 선행 90일 탐색 최우수
    (3.5, 0.4),   # 추가 탐색
]

PERIOD           = "180일"
_CHECKPOINT_PATH = _ROOT / "sl_trail_sweep_180d_checkpoint.json"
_PERIOD_DAYS     = 180


def _init_buckets(combos: list) -> list:
    return [{"sl_set": sl, "trail_set": trail, "bucket": SweepBucket()}
            for sl, trail in combos]


def _load_checkpoint(combos: list) -> tuple:
    if not _CHECKPOINT_PATH.exists():
        return set(), _init_buckets(combos)
    with open(_CHECKPOINT_PATH, encoding="utf-8") as f:
        ckpt = json.load(f)
    first = ckpt["buckets"][0] if ckpt["buckets"] else {}
    if "sum_pnl" not in first:   # 구 포맷 → 처음부터 다시
        return set(), _init_buckets(combos)
    buckets = []
    for d, (sl, trail) in zip(ckpt["buckets"], combos):
        bkt = SweepBucket(
            n=d["n"], wins=d["wins"], sum_pnl=d["sum_pnl"],
            sum_pos_pnl=d["sum_pos_pnl"], sum_neg_pnl=d["sum_neg_pnl"],
            one_r_pct=d["one_r_pct"],
        )
        buckets.append({"sl_set": sl, "trail_set": trail, "bucket": bkt})
    return set(ckpt["completed"]), buckets


def _save_checkpoint(completed: set, buckets: list) -> None:
    serializable = [
        {"sl_set": b["sl_set"], "trail_set": b["trail_set"],
         **dataclasses.asdict(b["bucket"])}
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
            "sl_set":    b["sl_set"],
            "trail_set": b["trail_set"],
            "one_r_pct": s["one_r_pct"],
            "n":         s["n"],
            "wr":        s["wr"],
            "ev_r":      s["ev_r"],
            "pf":        s["pf"],
            "pf_ci":     s["pf_ci"],
        })
    return sorted(results, key=lambda r: r["ev_r"], reverse=True)


def main():
    combos = SL_TRAIL_COMBOS
    completed, buckets = _load_checkpoint(combos)

    print(f"[SL 확장 sweep] {len(SYMBOLS)}심볼 × {len(combos)}조합 × {PERIOD}")
    print(f"[고정] leverage=20  m4_rsi_vol_mult=1.5  sort_mode=24h Ticker")
    print(f"[조합] SL/trail={[(c[0], c[1]) for c in combos]}")
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

        for i, (sl, trail) in enumerate(combos):
            _p = make_base_params()
            _p.stop_loss  = sl
            _p.trail_stop = trail
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

    baseline = next(
        (r for r in results
         if abs(r["sl_set"] - 2.9) < 0.01 and abs(r["trail_set"] - 1.2) < 0.01),
        None,
    )

    print(f"\n[완료] 소요시간 {elapsed / 60:.1f}분  ({len(completed)}/{len(SYMBOLS)} 심볼)\n")
    if baseline:
        print(
            f"[기준선] SL={baseline['sl_set']:.1f}% trail={baseline['trail_set']:.1f}% "
            f"→ EV={baseline['ev_r']:+.4f}R  PF={baseline['pf']:.3f}  "
            f"WR={baseline['wr']:.1f}%  N={baseline['n']:.0f}  1R={baseline['one_r_pct']:.2f}%"
        )
    unavail = "⚠판정불가" if (baseline and baseline["one_r_pct"] <= 0) else ""
    print(f"{'SL%':>5} {'trail%':>7} {'1R%':>6} | "
          f"{'N':>6} {'WR%':>6} {'EV(R)':>9} {'PF':>6} {'PF±CI':>8}  비교")
    print("-" * 80)

    for r in results:
        is_baseline = (
            abs(r["sl_set"] - 2.9) < 0.01 and abs(r["trail_set"] - 1.2) < 0.01)
        diff_str = "(기준)" if is_baseline else (
            f"({r['ev_r'] - baseline['ev_r']:+.4f}R)" if baseline else "")
        flag = " ← _strategy.json 실거래" if is_baseline else ""
        unavail_flag = " ⚠판정불가" if r["one_r_pct"] <= 0 else ""
        print(
            f"{r['sl_set']:>5.1f} {r['trail_set']:>7.1f} {r['one_r_pct']:>6.2f} | "
            f"{r['n']:>6.0f} {r['wr']:>6.1f}% {r['ev_r']:>+9.4f} {r['pf']:>6.3f} "
            f"±{r['pf_ci']:>6.3f}  {diff_str}{flag}{unavail_flag}"
        )

    if results:
        best = results[0]
        print("\n" + "=" * 80)
        print(f"[최우수 조합] SL={best['sl_set']:.1f}%  trail={best['trail_set']:.1f}%"
              f"  1R={best['one_r_pct']:.2f}%")
        print(
            f"  N={best['n']:.0f}  WR={best['wr']:.1f}%  "
            f"EV={best['ev_r']:+.4f}R  PF={best['pf']:.3f} ±{best['pf_ci']:.3f}"
        )
        if baseline:
            print(f"  기준선 대비: {best['ev_r'] - baseline['ev_r']:+.4f}R")
        print("=" * 80)

    out_path = _ROOT / "sl_trail_sweep_180d_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, indent=2, ensure_ascii=False)
    print(f"\n[저장] {out_path}")

    return results


if __name__ == "__main__":
    main()
