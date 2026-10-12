"""
common_liq sweep — 150심볼 × 2조합(ON/OFF) × 90일
현재 확정 파라미터(SL=3.0%, price_diff=0.3) 기준으로
G8(청산 근접도 필터) 효과 검증

결과 저장: common_liq_sweep_result.json (프로젝트 루트)

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python common_liq_sweep.py
"""
import sys
import time
import json
import pickle
import pathlib

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from bottom_engine.backtest.backtest_runner import BacktestRunner
from bottom_engine.backtest.historical_data_loader import HistoricalDataLoader
from bottom_engine.models import ProhibitionFlags
from bottom_engine.constants import _NEW_DAYS_MIN
from bottom_engine.sweep import SweepBucket, assert_sl_is_one_r
from bottom_engine.sweep.base_params import load_symbols, make_base_params

SYMBOLS = load_symbols()

PERIOD       = "90일"
_PERIOD_DAYS = 90

# common_liq sweep 고정값 (make_base_params 덮어쓰기)
_SL    = 3.0
_TRAIL = 0.4

COMBOS = [
    (True,  "common_liq=ON  (G8 기준선)"),
    (False, "common_liq=OFF (G8 제거)"),
]


def _make_params(common_liq_flag: bool):
    p = make_base_params()
    p.stop_loss   = _SL
    p.trail_stop  = _TRAIL
    p.prohibition = ProhibitionFlags(
        common_liq    = common_liq_flag,
        common_fr     = True,
        common_new    = True,
        common_hunter = True,
        long_fomo     = True,
        long_short_open  = True,
        short_accum      = True,
        short_long_open  = True,
    )
    return p


def _run_all_symbols(common_liq_flag: bool, preloaded_cache: dict) -> SweepBucket:
    params = _make_params(common_liq_flag)
    bkt = SweepBucket()
    _assert_done = False
    for sym in SYMBOLS:
        res = BacktestRunner.run(sym, params, PERIOD,
                                 preloaded=preloaded_cache[sym],
                                 entry_variant="M4", exit_variant="CURRENT")
        bkt.add(res)
        if not _assert_done:
            ok, msg = assert_sl_is_one_r(res)
            print(f"  [SL검증] {sym}: {msg}")
            _assert_done = True
    return bkt


def main():
    print(f"[common_liq sweep] {len(SYMBOLS)}심볼 × 2조합 × {PERIOD}")
    print(f"[고정] leverage=20  SL={_SL}%  trail={_TRAIL}%")
    print("-" * 70)

    t0 = time.time()
    preloaded_cache: dict = {}
    for sym in SYMBOLS:
        _cache_path = _ROOT / "backtest_cache" / PERIOD / f"{sym}.pkl"
        if _cache_path.exists():
            with open(_cache_path, "rb") as _f:
                preloaded_cache[sym] = pickle.load(_f)
        else:
            print(f"  캐시 없음: {sym} — API 로딩중...", flush=True)
            preloaded_cache[sym] = BacktestRunner.load_tf_bars(sym, PERIOD)
            preloaded_cache[sym]["fr"]  = HistoricalDataLoader.load_funding_rate(sym)
            preloaded_cache[sym]["liq"] = HistoricalDataLoader.load_long_short_ratio(sym, _PERIOD_DAYS)
            preloaded_cache[sym]["1d"]  = HistoricalDataLoader.load(sym, "1d", _NEW_DAYS_MIN + 5)

    print(f"[캐시 로드 완료] {time.time() - t0:.1f}초\n")

    results = []
    for liq_flag, label in COMBOS:
        t1 = time.time()
        bkt = _run_all_symbols(liq_flag, preloaded_cache)
        s = bkt.summary()
        results.append({
            "label": label, "common_liq": liq_flag,
            "one_r_pct": s["one_r_pct"],
            "n": s["n"], "wr": s["wr"], "ev_r": s["ev_r"],
            "pf": s["pf"], "pf_ci": s["pf_ci"],
        })
        unavail = " ⚠판정불가" if s["one_r_pct"] <= 0 else ""
        print(f"  {label}")
        print(f"    N={s['n']:.0f}  WR={s['wr']:.1f}%  EV={s['ev_r']:+.4f}R  "
              f"PF={s['pf']:.3f} ±{s['pf_ci']:.3f}  1R={s['one_r_pct']:.2f}%"
              f"{unavail}  ({time.time()-t1:.1f}초)\n")

    elapsed = time.time() - t0
    baseline = results[0]
    best     = max(results, key=lambda r: r["ev_r"])

    print("=" * 70)
    print(f"[결과 비교]  (소요시간 {elapsed/60:.1f}분)")
    print(f"{'조합':<42} {'N':>6} {'WR%':>6} {'EV(R)':>9} {'PF':>6} {'PF±CI':>8}  diff")
    print("-" * 80)
    for r in results:
        diff = "" if r is baseline else f"({r['ev_r'] - baseline['ev_r']:+.4f}R)"
        flag = " ← 기준선" if r is baseline else ""
        state = "ON " if r["common_liq"] else "OFF"
        unavail = " ⚠판정불가" if r["one_r_pct"] <= 0 else ""
        print(f"  {state}   {r['label'][13:]:<36}"
              f"{r['n']:>6.0f} {r['wr']:>6.1f}% {r['ev_r']:>+9.4f} {r['pf']:>6.3f} "
              f"±{r['pf_ci']:>6.3f}  {diff}{flag}{unavail}")
    print(f"\n[최우수] {best['label']}  EV={best['ev_r']:+.4f}R")
    print("=" * 70)

    out = _ROOT / "common_liq_sweep_result.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, indent=2, ensure_ascii=False)
    print(f"\n[저장] {out}")

    return results


if __name__ == "__main__":
    main()
