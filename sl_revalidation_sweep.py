"""
sl_revalidation_sweep.py — SL 재검증 (A안: 레버리지 20배 유지, SL 1.0~3.7%) — 150심볼 × 180일

_strategy.json "24h Ticker" 실거래 값이 기준선(SL 3.7 / trail 1.9 / lev 20). stop_loss만 바꾼 변형을
같은 조건으로 비교한다. SLCalculator.clamp·R cap 8%·G4 ATR 하한(SL/2)·trail 상한(SL×0.6)은
실거래와 같은 코드 경로 그대로 적용된다(엔진·전략·설정 미변경, 연구 스크립트만).
  - 20배 liq_safe 상한 = (1/20 − 0.004)×100×0.8 = 3.68% → 3.7이 상한이므로 SL ≤ 3.7만 시험
  - R cap으로 모든 변형의 1R = 자본 8% → EV(R) 직접 비교 가능

구간: 심볼별 마지막 1m 봉 기준 뒤 60일 = 검증, 그 앞 = 학습 (진입 시각 기준).
판정(과최적화 방지): ① 학습 EV가 가장 높은 SL 1개를 선정 → ② 그 1개만 검증 구간에서 확인.
  통과 기준: 검증 EV > 기준선(3.7) 검증 EV, 검증 PF − pf_ci ≥ 기준선 검증 PF, 검증 거래 ≥ 100.
  선정이 기준선(3.7)이면 "현행 유지".
함께 출력: SL별 거래 수(G4 하한 변화로 진입 수 변동), 청산 사유 구성, 왕복 비용(R), 롱·숏 분리.

캐시: backtest_cache/180일 (2026-10-25 재생성, 기간 전체 검증 완료). 네트워크 호출 차단.
결과 저장: sl_revalidation_sweep_result.json (프로젝트 루트)

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python sl_revalidation_sweep.py
"""
import dataclasses
import json
import pathlib
import pickle
import sys
import time
from collections import defaultdict
from multiprocessing import Pool

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from bottom_engine.backtest import historical_data_loader as _hdl


def _network_blocked(*_a, **_k):
    raise RuntimeError("sl_revalidation_sweep: 네트워크 호출 차단 — 캐시만 사용")


for _name in dir(_hdl.HistoricalDataLoader):
    if _name.startswith("load"):
        setattr(_hdl.HistoricalDataLoader, _name, staticmethod(_network_blocked))

from bottom_engine.backtest.backtest_runner import BacktestRunner, _SLIPPAGE, _TAKER_FEE_RATE
from bottom_engine.engine_core.sl_calculator import SLCalculator
from bottom_engine.sweep import SweepBucket
from bottom_engine.sweep.base_params import load_symbols, make_base_params, run_metadata, print_metadata

PERIOD       = "180일"
_CACHE_DIR   = _ROOT / "backtest_cache" / PERIOD
_RESULT_PATH = _ROOT / "sl_revalidation_sweep_result.json"
_TEST_DAYS   = 60
_WORKERS     = 8          # 16코어 중 절반 — 실행 중인 YONA 앱 몫 확보
_MIN_TEST_N  = 100
SL_VALUES    = (1.0, 1.5, 2.0, 2.5, 3.0, 3.4, 3.7)   # A안 — 3.7 = 기준선(현재 실거래)
_BASE_SL     = 3.7
_SELS        = ("ALL", "TRAIN", "TEST", "TEST_LONG", "TEST_SHORT")


def _run_symbol(job: tuple) -> tuple:
    """심볼 1개 × 전 SL 변형. 반환: (sym, {sl: {구간: 거래목록}}, {sl: one_r_pct})."""
    sym, sl_values = job
    base  = make_base_params()
    data  = pickle.load(open(_CACHE_DIR / f"{sym}.pkl", "rb"))
    split = data["1m"][-1].close_time - _TEST_DAYS * 86_400_000
    out, one_r = {}, {}
    for sl in sl_values:
        res = BacktestRunner.run(sym, dataclasses.replace(base, stop_loss=sl), PERIOD, preloaded=data,
                                 entry_variant="M4", exit_variant="CURRENT")
        one_r[sl] = res.one_r_pct
        tr = res.trades
        out[sl] = {
            "ALL":        tr,
            "TRAIN":      [t for t in tr if t.entry_time < split],
            "TEST":       [t for t in tr if t.entry_time >= split],
            "TEST_LONG":  [t for t in tr if t.entry_time >= split and t.side == "long"],
            "TEST_SHORT": [t for t in tr if t.entry_time >= split and t.side == "short"],
        }
    return sym, out, one_r


def _as_result(sym: str, trades: list, one_r: float):
    """SweepBucket.add 입력용 BacktestResult (trades·one_r_pct만 사용)."""
    from bottom_engine.models import BacktestResult
    return dataclasses.replace(BacktestResult(symbol=sym, sort_mode="", period_days=180),
                               trades=trades, one_r_pct=one_r)


def main() -> None:
    params  = make_base_params()
    symbols = load_symbols()
    meta    = run_metadata(params, PERIOD, symbols)
    print_metadata(meta)
    if abs(params.stop_loss - _BASE_SL) > 1e-9:
        sys.exit(f"[중단] 기준선 SL이 _strategy.json({params.stop_loss})과 다름 — _BASE_SL 확인 필요")
    missing = [s for s in symbols if not (_CACHE_DIR / f"{s}.pkl").exists()]
    if missing:
        sys.exit(f"[중단] 캐시 없음 {missing} — build_backtest_cache.py 180일 실행 필요")
    print(f"[SL 재검증 A안] {len(symbols)}심볼 × {PERIOD}  lev={params.leverage}  trail 설정={params.trail_stop}  "
          f"SL {SL_VALUES}  검증=뒤 {_TEST_DAYS}일  worker={_WORKERS}")
    print("-" * 104)

    buckets = {sl: {sel: SweepBucket() for sel in _SELS} for sl in SL_VALUES}
    reasons = {sl: defaultdict(float) for sl in SL_VALUES}
    t0 = time.time()
    with Pool(_WORKERS) as pool:
        jobs = [(s, SL_VALUES) for s in symbols]
        for i, (sym, out, one_r) in enumerate(pool.imap_unordered(_run_symbol, jobs), 1):
            for sl, sels in out.items():
                for sel, trades in sels.items():
                    buckets[sl][sel].add(_as_result(sym, trades, one_r[sl]))
                for t in sels["ALL"]:
                    reasons[sl][t.exit_reason] += t.qty_ratio
            if i % 10 == 0 or i == len(symbols):
                print(f"  {i}/{len(symbols)} 심볼 완료 ({(time.time() - t0) / 60:.1f}분)", flush=True)

    summ = {sl: {sel: b.summary() for sel, b in sels.items()} for sl, sels in buckets.items()}
    print("-" * 104)
    print(f"{'SL%':>5} {'trail':>6} {'G4 ATR≥':>8} {'비용R':>7} {'구간':<10} {'n':>6} {'WR%':>6} {'EV(R)':>9} {'PF':>7} {'±CI':>6}")
    rows = []
    for sl in SL_VALUES:
        sl_used, trail_used = SLCalculator.clamp(sl, params.trail_stop, params.leverage, mmr=params.mmr)
        one_r = summ[sl]["ALL"]["one_r_pct"]
        cost_r = (2 * (one_r / sl_used) * (_TAKER_FEE_RATE + _SLIPPAGE) * 100 / one_r) if one_r else 0.0
        for sel in _SELS:
            s = summ[sl][sel]
            print(f"{sl:5.1f} {trail_used:6.1f} {max(0.1, sl_used / 2):8.2f} {cost_r:7.4f} {sel:<10} "
                  f"{s['n']:6.1f} {s['wr']:6.1f} {s['ev_r']:+9.4f} {s['pf']:7.3f} {s['pf_ci']:6.3f}")
        r = reasons[sl]
        print(f"{'':>30} 청산: " + "  ".join(f"{k} {v:.1f}" for k, v in sorted(r.items(), key=lambda x: -x[1])))
        rows.append({"sl": sl, "sl_used": sl_used, "trail_used": trail_used, "cost_r": cost_r,
                     "g4_atr_min": max(0.1, sl_used / 2), "summary": summ[sl], "exit_reasons": dict(r)})
        print("-" * 104)

    chosen = max(SL_VALUES, key=lambda sl: summ[sl]["TRAIN"]["ev_r"])
    base_te, ch_te = summ[_BASE_SL]["TEST"], summ[chosen]["TEST"]
    checks = {
        "test_ev_gt_base": ch_te["ev_r"] > base_te["ev_r"],
        "test_pf_ci_low_ge_base_pf": (ch_te["pf"] - ch_te["pf_ci"]) >= base_te["pf"],
        "test_n_ge_100": ch_te["n"] >= _MIN_TEST_N,
    }
    if chosen == _BASE_SL:
        verdict = "현행 유지 (학습 구간 최우수 = 기준선 3.7)"
    else:
        verdict = "통과 — 변경 제안 대상" if all(checks.values()) else "미통과 — 현행 유지"
    print(f"[선정] 학습 EV 최우수 SL = {chosen}  (학습 EV {summ[chosen]['TRAIN']['ev_r']:+.4f}R)")
    print(f"[검증] 선정 SL {chosen}: 검증 EV {ch_te['ev_r']:+.4f}R PF {ch_te['pf']:.3f}±{ch_te['pf_ci']:.3f} n={ch_te['n']:.0f}"
          f"  vs 기준선 3.7: EV {base_te['ev_r']:+.4f}R PF {base_te['pf']:.3f}")
    print(f"[판정] {verdict}  {checks}")
    elapsed = time.time() - t0
    with open(_RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump({"metadata": meta, "test_days": _TEST_DAYS, "elapsed_sec": round(elapsed, 1),
                   "variants": rows, "chosen_by_train": chosen, "checks": checks, "verdict": verdict},
                  f, ensure_ascii=False, indent=2)
    print(f"[완료] {elapsed / 60:.1f}분  결과 저장: {_RESULT_PATH.name}")


if __name__ == "__main__":
    main()
