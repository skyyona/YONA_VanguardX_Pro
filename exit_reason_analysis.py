"""
exit_reason_analysis.py — 150심볼 × 180일 exit_reason 분포 분석
현재 실거래 파라미터(SL=2.9%, trail=1.2%, leverage=20) 기준
SL 청산 평균 R 검증: 이론값 -(1 + 0.1/2.9) ≈ -1.034R

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python exit_reason_analysis.py
"""
import sys
import time
import pickle
import pathlib
from collections import defaultdict

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from bottom_engine.backtest.backtest_runner import BacktestRunner
from bottom_engine.backtest.historical_data_loader import HistoricalDataLoader
from bottom_engine.constants import _NEW_DAYS_MIN
from bottom_engine.sweep import SweepBucket, assert_sl_is_one_r
from bottom_engine.sweep.base_params import load_symbols, make_base_params

SYMBOLS      = load_symbols()
PERIOD       = "180일"
_PERIOD_DAYS = 180


def main():
    params = make_base_params()

    print(f"[exit_reason 분포 분석] {len(SYMBOLS)}심볼 × {PERIOD}")
    print(f"[파라미터] SL={params.stop_loss}%  trail={params.trail_stop}%  "
          f"lev={params.leverage}")
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

    overall_bucket = SweepBucket()
    reason_count   = defaultdict(float)
    reason_pnl_sum = defaultdict(float)
    reason_wins    = defaultdict(float)

    _assert_done = False
    for sym in SYMBOLS:
        res = BacktestRunner.run(
            sym, params, PERIOD,
            preloaded=preloaded_cache[sym],
            entry_variant="M4", exit_variant="CURRENT",
        )
        overall_bucket.add(res)
        if not _assert_done:
            ok, msg = assert_sl_is_one_r(res)
            print(f"[SL검증] {sym}: {msg}")
            _assert_done = True

        for tr in res.trades:
            reason_count[tr.exit_reason]   += tr.qty_ratio
            reason_pnl_sum[tr.exit_reason] += tr.pnl_pct
            if tr.pnl_pct > 0:
                reason_wins[tr.exit_reason] += tr.qty_ratio

    elapsed = time.time() - t0
    s = overall_bucket.summary()

    if s["n"] == 0:
        print("[결과] 거래 없음")
        return

    one_r = s["one_r_pct"]
    unavail = " ⚠판정불가" if one_r <= 0 else ""

    print(f"\n[결과]  (소요시간 {elapsed/60:.1f}분)")
    print(f"총 거래: {s['n']:.0f}건  일평균={s['n']/_PERIOD_DAYS:.2f}건  "
          f"WR={s['wr']:.1f}%  EV={s['ev_r']:+.4f}R  "
          f"PF={s['pf']:.3f} ±{s['pf_ci']:.3f}  1R={one_r:.2f}%{unavail}")
    print("=" * 70)
    print(f"{'exit_reason':<14} {'건수':>6} {'비율%':>7} {'WR%':>7} "
          f"{'평균pnl%':>9} {'평균R':>8}")
    print("-" * 70)

    for reason in sorted(reason_count, key=lambda x: -reason_count[x]):
        cnt     = reason_count[reason]
        pct     = cnt / s["n"] * 100.0
        wr_r    = reason_wins[reason] / cnt * 100.0 if cnt > 0 else 0.0
        avg_pnl = reason_pnl_sum[reason] / cnt if cnt > 0 else 0.0
        avg_r   = (reason_pnl_sum[reason] / (one_r * cnt)
                   if (one_r > 0 and cnt > 0) else 0.0)
        print(f"  {reason:<12} {cnt:>6.1f} {pct:>7.1f}% {wr_r:>7.1f}% "
              f"{avg_pnl:>+8.3f}% {avg_r:>+8.3f}R")

    print("=" * 70)
    partial_n = reason_count.get("PARTIAL", 0.0)
    trail_n   = reason_count.get("TRAIL",   0.0)
    kd_n      = reason_count.get("KD-EXIT", 0.0)
    sl_n      = reason_count.get("SL",      0.0)
    bep_n     = reason_count.get("BEP-SL",  0.0)

    print(f"  Phase3 도달 (PARTIAL+TRAIL) : {partial_n+trail_n:>5.0f}건  "
          f"({(partial_n+trail_n)/s['n']*100:.1f}%)")
    print(f"  조기 청산 (KD-EXIT)         : {kd_n:>5.0f}건  "
          f"({kd_n/s['n']*100:.1f}%)")
    print(f"  SL 청산                     : {sl_n:>5.0f}건  "
          f"({sl_n/s['n']*100:.1f}%)")
    print(f"  BEP-SL 청산                 : {bep_n:>5.0f}건  "
          f"({bep_n/s['n']*100:.1f}%)")
    print("=" * 70)


if __name__ == "__main__":
    main()
