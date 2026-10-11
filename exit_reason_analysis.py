"""
exit_reason_analysis.py — 150심볼 × 90일 exit_reason 분포 분석

현재 24h Ticker 파라미터(SL=4.0%, trail=1.9%, lev=10, price_diff=0.1) 기준으로
Phase 작동 여부 확인: KD-EXIT / PARTIAL / TRAIL / SL / BEP-SL 비율 출력

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
from bottom_engine.engine_core.sl_calculator import SLCalculator
from bottom_engine.models import StrategyParams, ProhibitionFlags
from bottom_engine.constants import _NEW_DAYS_MIN, _MAX_R_PCT

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

PERIOD       = "180일"
_PERIOD_DAYS = 180


def _make_params() -> StrategyParams:
    p = StrategyParams()
    p.sort_mode         = "24h Ticker"
    p.leverage          = 10
    p.stop_loss         = 1.8
    p.trail_stop        = 0.7
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
    p.m4_rsi_price_diff = 0.1
    return p


def main():
    params = _make_params()
    sl_used, trail_used = SLCalculator.clamp(
        params.stop_loss, params.trail_stop, params.leverage, mmr=params.mmr)
    leff_approx = _MAX_R_PCT / sl_used if sl_used > 0 else 0.0

    print(f"[exit_reason 분포 분석] {len(SYMBOLS)}심볼 × {PERIOD}")
    print(f"[파라미터] SL={params.stop_loss}%  trail={params.trail_stop}%  "
          f"lev={params.leverage}  price_diff={params.m4_rsi_price_diff}")
    print(f"[SLCalc]   sl_used={sl_used}%  trail_used={trail_used}%  "
          f"_leff≈{leff_approx:.3f}  SL hit 손실≈{sl_used * leff_approx:.1f}% (=max_r_pct)")
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

    reason_count   = defaultdict(float)
    reason_pnl_sum = defaultdict(float)
    reason_r_sum   = defaultdict(float)
    reason_wins    = defaultdict(float)

    total_n    = 0.0
    total_wins = 0.0
    total_ev_r = 0.0

    for sym in SYMBOLS:
        res = BacktestRunner.run(
            sym, params, PERIOD,
            preloaded=preloaded_cache[sym],
            entry_variant="M4", exit_variant="CURRENT",
        )
        for tr in res.trades:
            w = tr.qty_ratio
            r = (tr.pnl_pct / sl_used) if sl_used > 0 else 0.0
            reason_count[tr.exit_reason]   += w
            reason_pnl_sum[tr.exit_reason] += tr.pnl_pct * w
            reason_r_sum[tr.exit_reason]   += r * w
            if tr.pnl_pct > 0:
                reason_wins[tr.exit_reason] += w
                total_wins += w
            total_n    += w
            total_ev_r += r * w

    elapsed = time.time() - t0

    if total_n == 0:
        print("[결과] 거래 없음")
        return

    ev   = total_ev_r / total_n
    wr   = total_wins / total_n * 100.0

    print(f"[결과]  (소요시간 {elapsed/60:.1f}분)")
    print(f"총 거래: {total_n:.0f}건  일평균={total_n/90:.2f}건  "
          f"WR={wr:.1f}%  EV={ev:+.4f}R")
    print("=" * 70)
    print(f"{'exit_reason':<14} {'건수':>6} {'비율%':>7} {'WR%':>7} "
          f"{'평균pnl%':>9} {'평균R':>8}")
    print("-" * 70)

    for reason in sorted(reason_count, key=lambda x: -reason_count[x]):
        cnt     = reason_count[reason]
        pct     = cnt / total_n * 100.0
        wr_r    = reason_wins[reason] / cnt * 100.0 if cnt > 0 else 0.0
        avg_pnl = reason_pnl_sum[reason] / cnt if cnt > 0 else 0.0
        avg_r   = reason_r_sum[reason]   / cnt if cnt > 0 else 0.0
        print(f"  {reason:<12} {cnt:>6.1f} {pct:>7.1f}% {wr_r:>7.1f}% "
              f"{avg_pnl:>+8.3f}% {avg_r:>+8.3f}R")

    print("=" * 70)
    partial_n = reason_count.get("PARTIAL", 0.0)
    trail_n   = reason_count.get("TRAIL",   0.0)
    kd_n      = reason_count.get("KD-EXIT", 0.0)
    sl_n      = reason_count.get("SL",      0.0)
    bep_n     = reason_count.get("BEP-SL",  0.0)

    print(f"  Phase3 도달 (PARTIAL+TRAIL) : {partial_n+trail_n:>5.0f}건  "
          f"({(partial_n+trail_n)/total_n*100:.1f}%)")
    print(f"  조기 청산 (KD-EXIT)         : {kd_n:>5.0f}건  "
          f"({kd_n/total_n*100:.1f}%)")
    print(f"  SL 청산                     : {sl_n:>5.0f}건  "
          f"({sl_n/total_n*100:.1f}%)")
    print(f"  BEP-SL 청산                 : {bep_n:>5.0f}건  "
          f"({bep_n/total_n*100:.1f}%)")
    print("=" * 70)


if __name__ == "__main__":
    main()
