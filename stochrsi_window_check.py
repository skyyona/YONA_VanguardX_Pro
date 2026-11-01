"""
stochrsi_window_check.py — [② 항목 4] 실거래 StochRSI 계산 봉 수 측정 (측정 전용)

실거래: middle/data/data_manager.py _KLINES_LIMITS — STAGE3·_refresh_detail·get_ohlcv 공통
        1m·3m·5m·15m·1h 200 / 4h·1d 80 → 미완성 봉 제외 199/79봉
        StochRSI.calculate_with_series (Wilder RSI14 → Stoch14 → SMA3 K → SMA3 D, K·D 소수 2자리)
백테스트: BacktestRunner._calc_kd — 같은 알고리즘, 캐시 전체 기록(180일)으로 계산

같은 마감 봉 시점에서 N봉(59·79·199·499) 실거래식 K·D와 전체 기록 K·D를 비교해 판정 불일치율 출력.
  G_K   : 5m K > k_long_max(롱 차단) / K < k_short_min(숏 차단)  — m4_entry.py:106-111
  교차   : K > D 방향 — 1m·3m·5m·15m (QualityGrader Cascade·매크로 판정 기반)
  Zone  : QualityGrader._zone_score 롱·숏 점수 (5m)               — quality_grader.py:89-108
  KD익절 : 5m K 80 하향 돌파 / 20 상향 돌파 (직전 마감 봉 대비)     — m4_exit.py·trading_engine.py

엔진·설정 변경 없음. 네트워크 호출 차단(HistoricalDataLoader.load* → 예외).
기간 전체가 채워진 캐시 심볼만 사용(빈·잘린 캐시 제외).

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python stochrsi_window_check.py
"""
import pathlib
import pickle
import sys
import time
from collections import defaultdict

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from bottom_engine.backtest import historical_data_loader as _hdl


def _network_blocked(*_a, **_k):
    raise RuntimeError("stochrsi_window_check: 네트워크 호출 차단 — 캐시만 사용")


for _name in dir(_hdl.HistoricalDataLoader):
    if _name.startswith("load"):
        setattr(_hdl.HistoricalDataLoader, _name, staticmethod(_network_blocked))

from bottom_engine.backtest.backtest_runner import BacktestRunner
from bottom_engine.engine_core.quality_grader import QualityGrader
from bottom_engine.strategy_settings.realtrade_strategy_sort_by import get_mode_config
from bottom_engine.sweep.base_params import make_base_params
from middle.col2_chart_indicators.mtf_stochrsi import StochRSI
from middle.models import OHLCVBar

PERIOD    = "180일"
SYMBOLS   = ("BTCUSDT", "SOLUSDT", "DOGEUSDT")   # 180일 캐시 중 기간 전체가 채워진 심볼
TFS       = ("1m", "3m", "5m", "15m")
WINDOWS   = (59, 79, 199, 499)
LAST_BARS = 5000                                  # TF별 최근 마감 봉 표본 수
_EXPECTED = {"1m": 259200, "3m": 86400, "5m": 51840, "15m": 17280, "1h": 3000}
_P        = (StochRSI.RSI_PERIOD, StochRSI.STOCH_PERIOD, StochRSI.SMOOTH_K, StochRSI.SMOOTH_D)


def _is_complete(data: dict) -> bool:
    return all(len(data.get(k) or []) >= 0.98 * n for k, n in _EXPECTED.items()) and bool(data.get("1d"))


def _zone(k: float) -> tuple[int, int]:
    ind = {"tf5": {"k": k}}
    return QualityGrader._zone_score(ind, "long"), QualityGrader._zone_score(ind, "short")


def _decisions(tf: str, k: float, d: float, k_prev: float, cfg) -> dict:
    out = {"cross": k > d}
    if tf == "5m":
        out["gk_long_block"]  = k > cfg.k_long_max
        out["gk_short_block"] = k < cfg.k_short_min
        out["zone"]           = _zone(k)
        out["kd_exit_long"]   = k_prev >= 80.0 and k < 80.0
        out["kd_exit_short"]  = k_prev <= 20.0 and k > 20.0
    return out


def main() -> None:
    params = make_base_params()
    cfg    = get_mode_config(params.sort_mode)
    print(f"[StochRSI 봉 수 측정] {PERIOD} 캐시 {SYMBOLS}  TF {TFS}  N {WINDOWS}  표본 TF별 최근 {LAST_BARS}봉")
    print(f"[판정 기준] mode={params.sort_mode}  k_long_max={cfg.k_long_max}  k_short_min={cfg.k_short_min}")
    print("-" * 96)

    # (tf, N) → 집계
    agg: dict = defaultdict(lambda: {"n": 0, "abs_sum": 0.0, "abs_max": 0.0, "mis": defaultdict(int)})
    t0 = time.time()
    for sym in SYMBOLS:
        data = pickle.load(open(_ROOT / "backtest_cache" / PERIOD / f"{sym}.pkl", "rb"))
        if not _is_complete(data):
            print(f"  {sym}: 캐시 불완전 — 제외")
            continue
        for tf in TFS:
            bars   = data[tf][:-1]   # 캐시 생성 시점 진행 중이었을 수 있는 마지막 봉 제외
            closes = [b.close for b in bars]
            ks, ds = BacktestRunner._calc_kd(closes, *_P)
            off    = len(bars) - len(ks)
            obars  = [OHLCVBar(b.open_time, b.open, b.high, b.low, b.close, b.volume, 0.0, b.close_time)
                      for b in bars]
            start  = max(len(bars) - LAST_BARS, off + 1, max(WINDOWS))
            for n in WINDOWS:
                a = agg[(tf, n)]
                prev_live = None
                prev_bt   = None
                for j in range(start, len(bars)):
                    live, _ = StochRSI.calculate_with_series(obars[j - n + 1: j + 1])
                    bk, bd  = ks[j - off], ds[j - off]
                    if prev_live is None:
                        prev_live, prev_bt = live.k, bk
                        continue
                    dl = _decisions(tf, live.k, live.d, prev_live, cfg)
                    db = _decisions(tf, bk, bd, prev_bt, cfg)
                    diff = abs(live.k - bk)
                    a["n"]       += 1
                    a["abs_sum"] += diff
                    a["abs_max"]  = max(a["abs_max"], diff)
                    for key in dl:
                        if dl[key] != db[key]:
                            a["mis"][key] += 1
                    prev_live, prev_bt = live.k, bk
        print(f"  {sym} 완료 ({time.time() - t0:.0f}s)", flush=True)

    print("-" * 96)
    print(f"{'TF':>4} {'N':>4} {'표본':>7} {'|ΔK|평균':>9} {'|ΔK|최대':>9} {'교차':>7} "
          f"{'G_K롱':>7} {'G_K숏':>7} {'Zone':>7} {'KD롱':>7} {'KD숏':>7}   (불일치율 %)")
    for tf in TFS:
        for n in WINDOWS:
            a = agg[(tf, n)]
            if not a["n"]:
                continue
            pct = {k: v / a["n"] * 100.0 for k, v in a["mis"].items()}

            def _f(key: str) -> str:
                return f"{pct.get(key, 0.0):7.2f}" if (tf == "5m" or key == "cross") else f"{'-':>7}"
            print(f"{tf:>4} {n:>4} {a['n']:>7} {a['abs_sum'] / a['n']:9.3f} {a['abs_max']:9.2f} {_f('cross')} "
                  f"{_f('gk_long_block')} {_f('gk_short_block')} {_f('zone')} "
                  f"{_f('kd_exit_long')} {_f('kd_exit_short')}")
    print("-" * 96)
    print("실거래 현재: 1m·3m·5m·15m=199봉 (상위 갱신·상세 갱신 동일)")
    print(f"총 소요 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
