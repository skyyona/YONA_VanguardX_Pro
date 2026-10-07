"""
price_diff_sweep.py — m4_rsi_price_diff 7조합 × 44심볼 × 90일
leverage=20, SL=2.0%, trail=0.4% 고정 (SL/trail sweep 최우수 조합)
G1 파라미터 고정: rsi_min_diff=3.0, vol_mult=1.5, lookback=20
  price_diff=0.0 → 조건 비활성(하위 호환)
  price_diff=0.5 → 현재 기본값

체크포인트 지원: 중단 후 재실행 시 완료된 심볼 자동 스킵
  checkpoint: price_diff_sweep_checkpoint.json (자동 관리, 전체 완료 시 삭제)

결과 저장: price_diff_sweep_result.json (프로젝트 루트)

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python price_diff_sweep.py
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
BASE_PARAMS.stop_loss         = 2.0
BASE_PARAMS.trail_stop        = 0.4
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

PRICE_DIFFS = (0.0, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0)  # 0.5 = 현재 기본값

PERIOD           = "90일"
_CHECKPOINT_PATH = _ROOT / "price_diff_sweep_checkpoint.json"
_PERIOD_DAYS     = 90
_SL_PCT          = BASE_PARAMS.stop_loss  # R 계산 기준


def _init_buckets() -> list:
    return [
        {
            "price_diff": pd,
            "n": 0.0, "wins": 0.0,
            "sum_pos_pnl": 0.0, "sum_neg_pnl": 0.0, "sum_ev_r": 0.0,
        }
        for pd in PRICE_DIFFS
    ]


def _load_checkpoint() -> tuple:
    if not _CHECKPOINT_PATH.exists():
        return set(), _init_buckets()
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
            "price_diff": bkt["price_diff"],
            "n":    n,
            "wr":   (bkt["wins"] / n * 100.0) if n > 0 else 0.0,
            "ev_r": (bkt["sum_ev_r"] / n)      if n > 0 else 0.0,
            "pf":   (bkt["sum_pos_pnl"] / bkt["sum_neg_pnl"]
                     if bkt["sum_neg_pnl"] > 0 else 0.0),
        })
    return sorted(results, key=lambda r: r["ev_r"], reverse=True)


def main():
    completed, buckets = _load_checkpoint()

    print(f"[price_diff sweep] {len(SYMBOLS)}심볼 × {len(PRICE_DIFFS)}조합 × {PERIOD}")
    print(f"[고정] leverage={BASE_PARAMS.leverage}  SL={BASE_PARAMS.stop_loss}%  "
          f"trail={BASE_PARAMS.trail_stop}%  rsi_diff=3.0  vol_mult=1.5  lb=20")
    print(f"[변동] price_diff={PRICE_DIFFS}  (0.5 = 현재 기본값, 0.0 = 비활성)")
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

        for i, pd in enumerate(PRICE_DIFFS):
            _p = dataclasses.replace(BASE_PARAMS, m4_rsi_price_diff=pd)
            res = BacktestRunner.run(sym, _p, PERIOD, preloaded=preloaded,
                                     entry_variant="M4", exit_variant="CURRENT")
            bkt = buckets[i]
            for tr in res.trades:
                w = tr.qty_ratio
                bkt["n"] += w
                r = (tr.pnl_pct / _SL_PCT) if _SL_PCT > 0 else 0.0
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
        (r for r in results if abs(r["price_diff"] - 0.5) < 0.001),
        None,
    )

    print(f"\n[완료] 소요시간 {elapsed / 60:.1f}분  ({len(completed)}/{len(SYMBOLS)} 심볼)\n")
    if baseline:
        print(
            f"[기준선] price_diff=0.5 → EV={baseline['ev_r']:+.4f}R  "
            f"PF={baseline['pf']:.3f}  WR={baseline['wr']:.1f}%  N={int(baseline['n'])}"
        )
    print(f"{'price_diff':>11} | {'N':>6} {'WR%':>6} {'EV(R)':>9} {'PF':>6}  비교")
    print("-" * 70)

    for r in results:
        is_baseline = abs(r["price_diff"] - 0.5) < 0.001
        is_disabled = abs(r["price_diff"]) < 0.001
        diff_str = "(기준)" if is_baseline else (
            f"({r['ev_r'] - baseline['ev_r']:+.4f}R)" if baseline else "")
        flag = " ← 현재기본값" if is_baseline else (" ← 비활성" if is_disabled else "")
        print(
            f"{r['price_diff']:>11.1f} | "
            f"{int(r['n']):>6} {r['wr']:>6.1f}% {r['ev_r']:>+9.4f} {r['pf']:>6.3f}  "
            f"{diff_str}{flag}"
        )

    if results:
        best = results[0]
        print("\n" + "=" * 70)
        print(f"[최우수 조합] price_diff={best['price_diff']:.1f}")
        print(
            f"  N={int(best['n'])}  WR={best['wr']:.1f}%  "
            f"EV={best['ev_r']:+.4f}R  PF={best['pf']:.3f}"
        )
        if baseline:
            print(f"  기준선(price_diff=0.5) 대비: {best['ev_r'] - baseline['ev_r']:+.4f}R")
        print("=" * 70)

    out_path = _ROOT / "price_diff_sweep_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, indent=2, ensure_ascii=False)
    print(f"\n[저장] {out_path}")

    return results


if __name__ == "__main__":
    main()
