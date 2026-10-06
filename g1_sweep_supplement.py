"""
G1 보완 sweep — vol_mult × lookback 4조합 × 44심볼 × 90일
rsi_min_diff=3.0 고정 (어제 sweep에서 2~5 범위 내 차이 없음 확인)

체크포인트 지원: 중단 후 재실행 시 완료된 심볼 자동 스킵
  checkpoint: g1_sweep_checkpoint.json (자동 관리, 전체 완료 시 삭제)

결과 저장: g1_sweep_supplement_result.json (프로젝트 루트)

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python g1_sweep_supplement.py
"""
import sys
import time
import json
import dataclasses
import pathlib

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from bottom_engine.backtest.backtest_runner import BacktestRunner
from bottom_engine.backtest.historical_data_loader import HistoricalDataLoader
from bottom_engine.models import StrategyParams, ProhibitionFlags

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
BASE_PARAMS.stop_loss         = 1.3
BASE_PARAMS.trail_stop        = 0.6
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

RSI_MIN_DIFFS = (3.0,)
VOL_MULTS     = (1.5, 2.0)
LOOKBACKS     = (20, 30)
PERIOD        = "90일"

_CHECKPOINT_PATH = _ROOT / "g1_sweep_checkpoint.json"
_PERIOD_DAYS     = {"7일": 7, "14일": 14, "30일": 30, "90일": 90}.get(PERIOD, 30)


def _init_buckets(combos: list) -> list:
    return [
        {
            "rsi_min_diff": rmd, "vol_mult": vm, "lookback": lb,
            "n": 0.0, "wins": 0.0,
            "sum_pos_pnl": 0.0, "sum_neg_pnl": 0.0, "sum_ev_r": 0.0,
        }
        for rmd, vm, lb in combos
    ]


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
            "rsi_min_diff": bkt["rsi_min_diff"],
            "vol_mult":     bkt["vol_mult"],
            "lookback":     bkt["lookback"],
            "n":    n,
            "wr":   (bkt["wins"] / n * 100.0) if n > 0 else 0.0,
            "ev_r": (bkt["sum_ev_r"] / n)      if n > 0 else 0.0,
            "pf":   (bkt["sum_pos_pnl"] / bkt["sum_neg_pnl"]
                     if bkt["sum_neg_pnl"] > 0 else 0.0),
        })
    return sorted(results, key=lambda r: r["ev_r"], reverse=True)


def main():
    combos = [
        (rmd, vm, lb)
        for rmd in RSI_MIN_DIFFS
        for vm  in VOL_MULTS
        for lb  in LOOKBACKS
    ]

    completed, buckets = _load_checkpoint(combos)
    sl_pct = BASE_PARAMS.stop_loss

    print(f"[G1 보완 sweep] {len(SYMBOLS)}심볼 × {len(combos)}조합 × {PERIOD}")
    print(f"[고정] rsi_min_diff=3.0  [변동] vol_mult={VOL_MULTS}  lookback={LOOKBACKS}")
    print(f"[파라미터] leverage={BASE_PARAMS.leverage}  SL={sl_pct}%  trail={BASE_PARAMS.trail_stop}%  use_macro={BASE_PARAMS.use_macro}")
    if completed:
        print(f"[체크포인트] {len(completed)}/{len(SYMBOLS)} 완료, {len(SYMBOLS)-len(completed)}개 이어서 실행")
    print("-" * 70)

    t0 = time.time()

    for sym in SYMBOLS:
        s_idx = SYMBOLS.index(sym)
        if sym in completed:
            print(f"  [{s_idx+1}/{len(SYMBOLS)}] {sym} 스킵 (체크포인트)", flush=True)
            continue

        print(f"  [{s_idx+1}/{len(SYMBOLS)}] {sym} 로딩중...", flush=True)
        preloaded = BacktestRunner.load_tf_bars(sym, PERIOD)
        if BASE_PARAMS.prohibition.common_fr or BASE_PARAMS.prohibition.common_liq:
            preloaded["fr"] = HistoricalDataLoader.load_funding_rate(sym)
        if BASE_PARAMS.prohibition.common_liq:
            preloaded["liq"] = HistoricalDataLoader.load_long_short_ratio(sym, _PERIOD_DAYS)

        for i, (rmd, vm, lb) in enumerate(combos):
            _p = dataclasses.replace(
                BASE_PARAMS,
                m4_rsi_rsi_diff=rmd,
                m4_rsi_vol_mult=vm,
                m4_rsi_lookback=lb,
            )
            res = BacktestRunner.run(sym, _p, PERIOD, preloaded=preloaded,
                                     entry_variant="M4", exit_variant="CURRENT")
            bkt = buckets[i]
            for t in res.trades:
                w = t.qty_ratio
                bkt["n"] += w
                r = (t.pnl_pct / sl_pct) if sl_pct > 0 else 0.0
                bkt["sum_ev_r"] += r * w
                if t.pnl_pct > 0:
                    bkt["wins"]        += w
                    bkt["sum_pos_pnl"] += t.pnl_pct * w
                else:
                    bkt["sum_neg_pnl"] += abs(t.pnl_pct) * w

        completed.add(sym)
        _save_checkpoint(completed, buckets)

    elapsed = time.time() - t0
    results  = _finalize(buckets)

    if _CHECKPOINT_PATH.exists():
        _CHECKPOINT_PATH.unlink()

    baseline = next(
        (r for r in results if abs(r["vol_mult"] - 1.5) < 0.01 and r["lookback"] == 20),
        None,
    )

    print(f"\n[완료] 소요시간 {elapsed/60:.1f}분  ({len(completed)}/{len(SYMBOLS)} 심볼)\n")
    if baseline:
        print(f"[기준선] vol=1.5 lb=20 → EV={baseline['ev_r']:+.4f}R  PF={baseline['pf']:.3f}  WR={baseline['wr']:.1f}%  N={int(baseline['n'])}")
    print(f"{'vol_mult':>9} {'lookback':>9} | {'N':>6} {'WR%':>6} {'EV(R)':>9} {'PF':>6}  비교")
    print("-" * 70)

    for r in results:
        is_baseline = (abs(r["vol_mult"] - 1.5) < 0.01 and r["lookback"] == 20)
        flag     = " ← 현재기본값" if is_baseline else ""
        diff_str = "(기준)" if is_baseline else (
            f"({r['ev_r'] - baseline['ev_r']:+.4f}R)" if baseline else ""
        )
        print(
            f"{r['vol_mult']:>9.1f} {r['lookback']:>9d} | "
            f"{int(r['n']):>6} {r['wr']:>6.1f}% {r['ev_r']:>+9.4f} {r['pf']:>6.3f}  {diff_str}{flag}"
        )

    if results:
        best = results[0]
        print("\n" + "=" * 70)
        print(f"[최우수 조합] vol_mult={best['vol_mult']:.1f}  lookback={best['lookback']}")
        print(f"  N={int(best['n'])}  WR={best['wr']:.1f}%  EV={best['ev_r']:+.4f}R  PF={best['pf']:.3f}")
        if baseline:
            print(f"  기준선 대비: {best['ev_r'] - baseline['ev_r']:+.4f}R")
        print("=" * 70)

    out_path = _ROOT / "g1_sweep_supplement_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, indent=2, ensure_ascii=False)
    print(f"\n[저장] {out_path}")

    return results


if __name__ == "__main__":
    main()
