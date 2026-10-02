"""
G1 보완 sweep — vol_mult × lookback 4조합 × 45심볼 × 90일
rsi_min_diff=3.0 고정 (어제 sweep에서 2~5 범위 내 차이 없음 확인)

기준선 포함 비교:
  vol_mult  lookback  기준선여부
  1.5       20        ← 현재 기본값(기준선)
  1.5       30
  2.0       20
  2.0       30

파라미터: _strategy.json "24h Ticker" 기준
  leverage=20, stop_loss=1.3, trail_stop=0.6, use_macro=False
  prohibition: common_liq/fr/new/hunter/long_fomo/short_accum=True

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python g1_sweep_supplement.py

결과 저장: g1_sweep_supplement_result.json (프로젝트 루트)
"""
import sys
import time
import json
import pathlib

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from bottom_engine.backtest.backtest_runner import BacktestRunner
from bottom_engine.models import StrategyParams, ProhibitionFlags

SYMBOLS = [
    "QUSDT", "QNTUSDT", "SOONUSDT", "USUSDT", "BTWUSDT",
    "RAREUSDT", "ONEUSDT", "MARSCOINUSDT", "MUBARAKUSDT", "GRASSUSDT",
    "INXUSDT", "AZTECUSDT", "GRTUSDT", "ARXUSDT", "NILUSDT",
    "LYNUSDT", "SAGAUSDT", "PHAROSUSDT", "IRYSUSDT", "PHAUSDT",
    "NOMUSDT", "AKEUSDT", "NMRUSDT", "ONDOUSDT", "CCUSDT",
    "WUSDT", "PUMPUSDT", "ZROUSDT", "MONUSDT", "BULLAUSDT",
    "HBARUSDT", "FLOCKUSDT", "SEIUSDT", "TAKEUSDT", "AIOTUSDT",
    "JASMYUSDT", "ARKUSDT", "USELESSUSDT", "PONSUSDT", "HUMAUSDT",
    "METUSDT", "IOTAUSDT", "TRIAUSDT", "LSKUSDT", "PTBUSDT",
]

# _strategy.json "24h Ticker" 기준 파라미터
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

PERIOD = "90일"


def main():
    total_combos = len(RSI_MIN_DIFFS) * len(VOL_MULTS) * len(LOOKBACKS)
    print(f"[G1 보완 sweep] {len(SYMBOLS)}심볼 × {total_combos}조합 × {PERIOD}")
    print(f"[고정] rsi_min_diff=3.0  [변동] vol_mult={VOL_MULTS}  lookback={LOOKBACKS}")
    print(f"[파라미터] leverage={BASE_PARAMS.leverage}  SL={BASE_PARAMS.stop_loss}%  trail={BASE_PARAMS.trail_stop}%  use_macro={BASE_PARAMS.use_macro}")
    print("-" * 70)

    t0 = time.time()
    results = BacktestRunner.run_g1_sweep(
        symbols       = SYMBOLS,
        base_params   = BASE_PARAMS,
        period        = PERIOD,
        rsi_min_diffs = RSI_MIN_DIFFS,
        vol_mults     = VOL_MULTS,
        lookbacks     = LOOKBACKS,
    )
    elapsed = time.time() - t0

    # 기준선: vol_mult=1.5, lookback=20 조합의 sweep 결과에서 자동 추출
    baseline = next(
        (r for r in results if abs(r["vol_mult"] - 1.5) < 0.01 and r["lookback"] == 20),
        None,
    )

    print(f"\n[완료] 소요시간 {elapsed/60:.1f}분\n")
    if baseline:
        print(f"[기준선] vol=1.5 lb=20 → EV={baseline['ev_r']:+.4f}R  PF={baseline['pf']:.3f}  WR={baseline['wr']:.1f}%  N={int(baseline['n'])}")
    print(f"{'vol_mult':>9} {'lookback':>9} | {'N':>6} {'WR%':>6} {'EV(R)':>9} {'PF':>6}  비교")
    print("-" * 70)

    for r in results:
        is_baseline = (abs(r["vol_mult"] - 1.5) < 0.01 and r["lookback"] == 20)
        flag = " ← 현재기본값" if is_baseline else ""
        if baseline and not is_baseline:
            ev_diff  = r["ev_r"] - baseline["ev_r"]
            diff_str = f"({ev_diff:+.4f}R)"
        else:
            diff_str = "(기준)"
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
            ev_gain = best["ev_r"] - baseline["ev_r"]
            print(f"  기준선 대비: {ev_gain:+.4f}R")
        print("=" * 70)

    out_path = _ROOT / "g1_sweep_supplement_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, indent=2, ensure_ascii=False)
    print(f"\n[저장] {out_path}")

    return results


if __name__ == "__main__":
    main()
