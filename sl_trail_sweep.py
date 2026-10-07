"""
SL/Trail 비율 sweep — 44심볼 × 15조합 × 90일
G1 파라미터 고정: rsi_min_diff=3.0, vol_mult=1.5, lookback=20

체크포인트 지원: 중단 후 재실행 시 완료된 심볼 자동 스킵
  checkpoint: sl_trail_sweep_checkpoint.json (자동 관리, 전체 완료 시 삭제)

결과 저장: sl_trail_sweep_result.json (프로젝트 루트)

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
from bottom_engine.engine_core.sl_calculator import SLCalculator
from bottom_engine.models import StrategyParams, ProhibitionFlags
from bottom_engine.constants import _NEW_DAYS_MIN

SYMBOLS = [
    "QUSDT", "QNTUSDT", "USUSDT", "BTWUSDT",
    "RAREUSDT", "ONEUSDT", "MARSCOINUSDT", "MUBARAKUSDT", "GRASSUSDT",
    "INXUSDT", "AZTECUSDT", "GRTUSDT", "ARXUSDT", "NILUSDT",
    "LYNUSDT", "SAGAUSDT", "PHAROSUSDT", "IRYSUSDT", "PHAUSDT",
    "NOMUSDT", "AKEUSDT", "NMRUSDT", "ONDOUSDT", "CCUSDT",
    "WUSDT", "PUMPUSDT", "ZROUSDT", "MONUSDT", "BULLAUSDT",
    "HBARUSDT", "FLOCKUSDT", "SEIUSDT", "TAKEUSDT", "AIOTUSDT",
    "JASMYUSDT", "ARKUSDT", "USELESSUSDT", "PONSUSDT", "HUMAUSDT",
    "METUSDT", "IOTAUSDT", "TRIAUSDT", "LSKUSDT", "PTBUSDT",
]

BASE_PARAMS = StrategyParams()
BASE_PARAMS.sort_mode         = "24h Ticker"
BASE_PARAMS.leverage          = 20
BASE_PARAMS.use_macro         = False
BASE_PARAMS.prohibition       = ProhibitionFlags(
    common_liq=True, common_fr=True, common_new=True, common_hunter=True,
    long_fomo=True, long_short_open=True, short_accum=True, short_long_open=True,
)
BASE_PARAMS.m4_rsi_oversold   = 30.0
BASE_PARAMS.m4_rsi_overbought = 70.0
BASE_PARAMS.m4_rsi_lookback   = 20
BASE_PARAMS.m4_rsi_rsi_diff   = 3.0
BASE_PARAMS.m4_rsi_vol_mult   = 1.5
BASE_PARAMS.m4_rsi_price_diff = 0.5

# (stop_loss%, trail_stop%) — SLCalculator.clamp() 적용 후 의미 있는 범위만 포함
# _TRAIL_CAP=0.6 제약: trail_used = min(trail_set, sl_used × 0.6)
# SL=0.8% → trail 최대 0.5%
# SL=1.0% → trail 최대 0.6%
# SL=1.3% → trail 최대 0.8%
# SL=1.5% → trail 최대 0.9%
# SL=2.0% → trail 최대 1.2%
SL_TRAIL_COMBOS = [
    (0.8, 0.4),
    (1.0, 0.4), (1.0, 0.6),
    (1.3, 0.4), (1.3, 0.6), (1.3, 0.8),   # (1.3, 0.6) = 현재 기본값
    (1.5, 0.4), (1.5, 0.6), (1.5, 0.8), (1.5, 0.9),
    (2.0, 0.4), (2.0, 0.6), (2.0, 0.8), (2.0, 1.0), (2.0, 1.2),
]

PERIOD           = "90일"
_CHECKPOINT_PATH = _ROOT / "sl_trail_sweep_checkpoint.json"
_PERIOD_DAYS     = 90


def _init_buckets(combos: list) -> list:
    buckets = []
    for sl, trail in combos:
        sl_used, trail_used = SLCalculator.clamp(
            sl, trail, BASE_PARAMS.leverage, mmr=BASE_PARAMS.mmr)
        buckets.append({
            "sl_set": sl, "trail_set": trail,
            "sl_used": sl_used, "trail_used": trail_used,
            "n": 0.0, "wins": 0.0,
            "sum_pos_pnl": 0.0, "sum_neg_pnl": 0.0, "sum_ev_r": 0.0,
        })
    return buckets


def _load_checkpoint(combos: list) -> tuple:
    if not _CHECKPOINT_PATH.exists():
        return set(), _init_buckets(combos)
    with open(_CHECKPOINT_PATH, encoding="utf-8") as f:
        ckpt = json.load(f)
    return set(ckpt["completed"]), ckpt["buckets"]


def _save_checkpoint(completed: set, buckets: list) -> None:
    with open(_CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump({"completed": list(completed), "buckets": buckets},
                  f, ensure_ascii=False)


def _finalize(buckets: list) -> list:
    results = []
    for bkt in buckets:
        n = bkt["n"]
        results.append({
            "sl_set":    bkt["sl_set"],
            "trail_set": bkt["trail_set"],
            "sl_used":   bkt["sl_used"],
            "trail_used": bkt["trail_used"],
            "n":   n,
            "wr":  (bkt["wins"] / n * 100.0) if n > 0 else 0.0,
            "ev_r": (bkt["sum_ev_r"] / n)     if n > 0 else 0.0,
            "pf":  (bkt["sum_pos_pnl"] / bkt["sum_neg_pnl"]
                    if bkt["sum_neg_pnl"] > 0 else 0.0),
        })
    return sorted(results, key=lambda r: r["ev_r"], reverse=True)


def main():
    combos = SL_TRAIL_COMBOS
    completed, buckets = _load_checkpoint(combos)

    print(f"[SL/Trail sweep] {len(SYMBOLS)}심볼 × {len(combos)}조합 × {PERIOD}")
    print(f"[고정] G1 기본값(rsi_diff=3.0, vol_mult=1.5, lb=20)")
    print(f"[변동] SL={[c[0] for c in combos]}  trail={[c[1] for c in combos]}")
    if completed:
        print(f"[체크포인트] {len(completed)}/{len(SYMBOLS)} 완료, "
              f"{len(SYMBOLS) - len(completed)}개 이어서 실행")
    print("-" * 70)

    t0 = time.time()

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
            _p = dataclasses.replace(BASE_PARAMS, stop_loss=sl, trail_stop=trail)
            res = BacktestRunner.run(sym, _p, PERIOD, preloaded=preloaded,
                                     entry_variant="M4", exit_variant="CURRENT")
            bkt     = buckets[i]
            sl_used = bkt["sl_used"]
            for tr in res.trades:
                w = tr.qty_ratio
                bkt["n"] += w
                r = (tr.pnl_pct / sl_used) if sl_used > 0 else 0.0
                bkt["sum_ev_r"] += r * w
                if tr.pnl_pct > 0:
                    bkt["wins"]        += w
                    bkt["sum_pos_pnl"] += tr.pnl_pct * w
                else:
                    bkt["sum_neg_pnl"] += abs(tr.pnl_pct) * w

        completed.add(sym)
        _save_checkpoint(completed, buckets)

    elapsed = time.time() - t0
    results  = _finalize(buckets)

    if _CHECKPOINT_PATH.exists():
        _CHECKPOINT_PATH.unlink()

    baseline = next(
        (r for r in results
         if abs(r["sl_set"] - 1.3) < 0.01 and abs(r["trail_set"] - 0.6) < 0.01),
        None,
    )

    print(f"\n[완료] 소요시간 {elapsed / 60:.1f}분  ({len(completed)}/{len(SYMBOLS)} 심볼)\n")
    if baseline:
        print(
            f"[기준선] SL={baseline['sl_used']:.1f}% trail={baseline['trail_used']:.1f}% "
            f"→ EV={baseline['ev_r']:+.4f}R  PF={baseline['pf']:.3f}  "
            f"WR={baseline['wr']:.1f}%  N={int(baseline['n'])}"
        )
    print(f"{'SL%':>5} {'trail%':>7} | {'N':>6} {'WR%':>6} {'EV(R)':>9} {'PF':>6}  비교")
    print("-" * 70)

    for r in results:
        is_baseline = (
            abs(r["sl_set"] - 1.3) < 0.01 and abs(r["trail_set"] - 0.6) < 0.01)
        diff_str = "(기준)" if is_baseline else (
            f"({r['ev_r'] - baseline['ev_r']:+.4f}R)" if baseline else "")
        flag = " ← 현재기본값" if is_baseline else ""
        print(
            f"{r['sl_used']:>5.1f} {r['trail_used']:>7.1f} | "
            f"{int(r['n']):>6} {r['wr']:>6.1f}% {r['ev_r']:>+9.4f} {r['pf']:>6.3f}  "
            f"{diff_str}{flag}"
        )

    if results:
        best = results[0]
        print("\n" + "=" * 70)
        print(f"[최우수 조합] SL={best['sl_used']:.1f}%  trail={best['trail_used']:.1f}%")
        print(
            f"  N={int(best['n'])}  WR={best['wr']:.1f}%  "
            f"EV={best['ev_r']:+.4f}R  PF={best['pf']:.3f}"
        )
        if baseline:
            print(f"  기준선 대비: {best['ev_r'] - baseline['ev_r']:+.4f}R")
        print("=" * 70)

    out_path = _ROOT / "sl_trail_sweep_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, indent=2, ensure_ascii=False)
    print(f"\n[저장] {out_path}")

    return results


if __name__ == "__main__":
    main()
