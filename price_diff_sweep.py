"""
price_diff sweep — 150심볼 × 4조합 × 90일
G1 RSI 다이버전스 가격 반등 강도 임계값(price_min_diff) 효과 검증

비교 조합:
  0.3% → 0.2% → 0.1% → 0.0% (가격 조건 면제)

결과 저장: price_diff_sweep_result.json (프로젝트 루트)

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python price_diff_sweep.py
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
from bottom_engine.engine_core.sl_calculator import SLCalculator
from bottom_engine.models import StrategyParams, ProhibitionFlags
from bottom_engine.constants import _NEW_DAYS_MIN

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT", "XRPUSDT",
    "RLCUSDT", "NEARUSDT", "DOGEUSDT", "HYPEUSDT", "BRUSDT",
    "ORCAUSDT", "NMRUSDT", "SUIUSDT", "BNBUSDT", "UNIUSDT",
    "PUMPUSDT", "ADAUSDT", "QNTUSDT", "AVAXUSDT", "WLDUSDT",
    "ENAUSDT", "SANDUSDT", "TAOUSDT", "1000PEPEUSDT", "CAPUSDT",
    "FILUSDT", "AAVEUSDT", "ONDOUSDT", "LINKUSDT", "USUSDT",
    "GTCUSDT", "TRUMPUSDT", "INJUSDT", "ARBUSDT", "PENGUUSDT",
    "ZROUSDT", "MINAUSDT", "LTCUSDT", "API3USDT", "ASTERUSDT",
    "FETUSDT", "DOTUSDT", "GRIFFAINUSDT", "BCHUSDT", "PAXGUSDT",
    "XLMUSDT", "APTUSDT", "MOVRUSDT", "LITUSDT", "ETHFIUSDT",
    "TRBUSDT", "PROMUSDT", "TIAUSDT", "RENDERUSDT", "LYNUSDT",
    "RAYSOLUSDT", "XAUTUSDT", "BTWUSDT", "1000SHIBUSDT", "HBARUSDT",
    "XPLUSDT", "DASHUSDT", "MONUSDT", "OPUSDT", "ICPUSDT",
    "AINUSDT", "TRXUSDT", "XMRUSDT", "PARTIUSDT", "METUSDT",
    "VIRTUALUSDT", "JUPUSDT", "NILUSDT", "MUBARAKUSDT", "EDUUSDT",
    "USELESSUSDT", "STRKUSDT", "ETCUSDT", "FARTCOINUSDT", "MAGICUSDT",
    "CRVUSDT", "C98USDT", "VVVUSDT", "JTOUSDT", "GRASSUSDT",
    "AEROUSDT", "PENDLEUSDT", "1000BONKUSDT", "LDOUSDT", "VTHOUSDT",
    "ACEUSDT", "SEIUSDT", "POLUSDT", "WLFIUSDT", "STXUSDT",
    "SYNUSDT", "RESOLVUSDT", "AKEUSDT", "WIFUSDT", "AXSUSDT",
    "CHIPUSDT", "LSKUSDT", "NIGHTUSDT", "ORDIUSDT", "GRAMUSDT",
    "ATOMUSDT", "BULLAUSDT", "ONEUSDT", "ARUSDT", "SKYUSDT",
    "PYTHUSDT", "MANAUSDT", "HEMIUSDT", "GALAUSDT", "BOMEUSDT",
    "UMAUSDT", "ARKUSDT", "ALGOUSDT", "MAGMAUSDT", "ZAMAUSDT",
    "EIGENUSDT", "FLUXUSDT", "OGNUSDT", "SAGAUSDT", "CAKEUSDT",
    "ZENUSDT", "VELVETUSDT", "LPTUSDT", "HUMAUSDT", "PHAUSDT",
    "BIOUSDT", "MIRAUSDT", "COTIUSDT", "AIAUSDT", "LABUSDT",
    "SOONUSDT", "0GUSDT", "ALICEUSDT", "MORPHOUSDT", "1000FLOKIUSDT",
    "ESPUSDT", "CLOUSDT", "4USDT", "FLUIDUSDT", "DIAUSDT",
    "2ZUSDT", "ENJUSDT", "RVNUSDT", "CCUSDT", "MYXUSDT",
]

PERIOD       = "90일"
_PERIOD_DAYS = 90

COMBOS = [
    (0.3, "price_diff=0.3% (기준선)"),
    (0.2, "price_diff=0.2%"),
    (0.1, "price_diff=0.1%"),
    (0.0, "price_diff=0.0% (가격조건 면제)"),
]


def _init_bucket() -> dict:
    return {"n": 0.0, "wins": 0.0, "sum_pos_pnl": 0.0, "sum_neg_pnl": 0.0, "sum_ev_r": 0.0}


def _make_params(price_diff_val: float) -> StrategyParams:
    p = StrategyParams()
    p.sort_mode         = "24h Ticker"
    p.leverage          = 20
    p.stop_loss         = 3.0
    p.trail_stop        = 0.4
    p.use_macro         = False
    p.prohibition       = ProhibitionFlags(
        common_liq    = True,
        common_fr     = True,
        common_new    = True,
        common_hunter = True,
        long_fomo     = True,
        long_short_open  = True,
        short_accum      = True,
        short_long_open  = True,
    )
    p.m4_rsi_oversold   = 30.0
    p.m4_rsi_overbought = 70.0
    p.m4_rsi_lookback   = 20
    p.m4_rsi_rsi_diff   = 3.0
    p.m4_rsi_vol_mult   = 1.5
    p.m4_rsi_price_diff = price_diff_val
    return p


def _run_all_symbols(price_diff_val: float, preloaded_cache: dict) -> dict:
    params = _make_params(price_diff_val)
    bkt = _init_bucket()
    sl_used, _ = SLCalculator.clamp(
        params.stop_loss, params.trail_stop,
        params.leverage, mmr=params.mmr)

    for sym in SYMBOLS:
        preloaded = preloaded_cache[sym]
        res = BacktestRunner.run(sym, params, PERIOD, preloaded=preloaded,
                                 entry_variant="M4", exit_variant="CURRENT")
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

    return bkt


def main():
    print(f"[price_diff sweep] {len(SYMBOLS)}심볼 × {len(COMBOS)}조합 × {PERIOD}")
    print(f"[고정] leverage=20  SL=3.0%  trail=0.4%  common_liq=ON(K=0.75)")
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
    for pd_val, label in COMBOS:
        t1 = time.time()
        bkt = _run_all_symbols(pd_val, preloaded_cache)
        n  = bkt["n"]
        ev = (bkt["sum_ev_r"] / n) if n > 0 else 0.0
        wr = (bkt["wins"] / n * 100.0) if n > 0 else 0.0
        pf = (bkt["sum_pos_pnl"] / bkt["sum_neg_pnl"]
              if bkt["sum_neg_pnl"] > 0 else 0.0)
        results.append({"label": label, "price_diff": pd_val,
                        "n": int(n), "wr": wr, "ev_r": ev, "pf": pf})
        print(f"  {label}")
        print(f"    N={int(n)}  WR={wr:.1f}%  EV={ev:+.4f}R  PF={pf:.3f}"
              f"  ({time.time()-t1:.1f}초)\n")

    elapsed = time.time() - t0
    baseline = results[0]
    best     = max(results, key=lambda r: r["ev_r"])

    print("=" * 70)
    print(f"[결과 비교]  (소요시간 {elapsed/60:.1f}분)")
    print(f"{'조합':<36} {'N':>6} {'일평균':>6} {'WR%':>6} {'EV(R)':>9} {'PF':>6}  diff")
    print("-" * 70)
    for r in results:
        diff = "" if r is baseline else f"({r['ev_r'] - baseline['ev_r']:+.4f}R)"
        flag = " ← 기준선" if r is baseline else ""
        daily = r["n"] / 90.0
        print(f"  {r['label']:<34}"
              f"{r['n']:>6} {daily:>6.2f} {r['wr']:>6.1f}% {r['ev_r']:>+9.4f} {r['pf']:>6.3f}  {diff}{flag}")
    print(f"\n[최우수] {best['label']}  EV={best['ev_r']:+.4f}R")
    print("=" * 70)

    out = _ROOT / "price_diff_sweep_result.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, indent=2, ensure_ascii=False)
    print(f"\n[저장] {out}")

    return results


if __name__ == "__main__":
    main()
