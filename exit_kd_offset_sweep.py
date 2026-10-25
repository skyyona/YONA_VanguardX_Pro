"""
exit_kd_offset_sweep.py — [④ 항목 8] KD 익절 최소 수익 조건 A/B — 150심볼 × 180일

_strategy.json "24h Ticker" 실거래 값이 기준선(A안: 2026-10-25 SL 3.7 / trail 1.9 / lev 20).
Phase1 KD 익절(K80 하향·K20 상향 돌파)은 현재 "청산가 ≥ 진입가(0R)"일 때만 청산
(m4_exit.py 112·177, trading_engine.py 584-585·643 부근). 이 조건을 0.25R·0.5R·0.75R로 올린 변형을
양방향 / 롱만 적용으로 비교한다.

반대 방향(relax 모드): 조건을 −0.25R·−0.5R·−0.75R·제한 없음으로 낮춰, 손실 구간 KD 돌파에서도
청산하는 변형을 같은 방식으로 비교한다.

연구 분기로만 구현 — M4Exit·BacktestRunner·실거래 코드 미변경. Phase1 KD 기준선 thr(R, 기본 0):
  상향(thr > 0): 실제 M4Exit.evaluate 결과가 Phase1 KD-EXIT이고 그 시점 수익(R) < thr이면,
    같은 입력에 K값만 중립(50/50 — 80·20 돌파 불가)으로 다시 실제 evaluate를 호출해
    "KD 익절 없음" 판정(Phase 전환·SL 갱신 포함)을 그대로 사용한다.
  하향(thr < 0 또는 None=제한 없음): 실제 evaluate가 Phase1에서 청산 없음·Phase 유지로 판정했고
    같은 봉에 KD 돌파가 있었으며 손실 구간(롱 종가<진입가, 숏 종가>진입가)이고 수익(R) ≥ thr이면,
    m4_exit.py 113·178과 같은 형태의 KD-EXIT(종가 전량 청산)를 반환한다. SL 판정이 먼저이므로 SL 봉은 해당 없음.
Phase2·3 KD 익절은 변경하지 않고, 기준선의 Phase별 KD 건수·평균 R만 집계(적용 여부는 측정 후 결정).

구간: 심볼별 마지막 1m 봉 기준 뒤 60일 = 검증, 그 앞 = 학습 (진입 시각 기준).
통과 기준(작업 지시서): 검증 EV > 기준선 검증 EV, 검증 PF 신뢰구간 하단(PF − pf_ci) ≥ 기준선 검증 PF,
검증 거래 수 ≥ 100. 통과 시에만 m4_exit.py·trading_engine.py(롱·숏) 동시 수정 계획을 제안.

캐시: backtest_cache/180일 (2026-10-25 재생성, 기간 전체 검증 완료). 네트워크 호출 차단.
결과 저장: exit_kd_offset_sweep_result.json / relax 모드 exit_kd_offset_sweep_relax_result.json (프로젝트 루트)

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python exit_kd_offset_sweep.py          # 상향(0.25·0.5·0.75R)
  python exit_kd_offset_sweep.py relax    # 하향(−0.25·−0.5·−0.75R·제한 없음)
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
    raise RuntimeError("exit_kd_offset_sweep: 네트워크 호출 차단 — 캐시만 사용")


for _name in dir(_hdl.HistoricalDataLoader):
    if _name.startswith("load"):
        setattr(_hdl.HistoricalDataLoader, _name, staticmethod(_network_blocked))

from bottom_engine.backtest.backtest_runner import BacktestRunner
from bottom_engine.strategy.m4_exit import ExitDecision, M4Exit
from bottom_engine.sweep import SweepBucket
from bottom_engine.sweep.base_params import load_symbols, make_base_params, run_metadata, print_metadata

PERIOD       = "180일"
_CACHE_DIR   = _ROOT / "backtest_cache" / PERIOD
_MODE        = sys.argv[1] if len(sys.argv) > 1 else "raise"
if _MODE not in ("raise", "relax"):
    sys.exit(f"지원 모드: raise(기본)·relax (입력: {_MODE})")
_RESULT_PATH = _ROOT / ("exit_kd_offset_sweep_result.json" if _MODE == "raise"
                        else "exit_kd_offset_sweep_relax_result.json")
_TEST_DAYS   = 60
_WORKERS     = 8          # 16코어 중 절반 — 실행 중인 YONA 앱 몫 확보
_MIN_TEST_N  = 100
_NEUTRAL_K   = 50.0       # 80·20 어느 쪽도 돌파 불가

# (이름, Phase1 KD 기준선 R(None = 제한 없음), 적용 방향) — 0R = 기준선(현재 조건 그대로)
_RAISE_VARIANTS = [
    ("base_0R",     0.00, "both"),
    ("both_0.25R",  0.25, "both"),
    ("both_0.5R",   0.50, "both"),
    ("both_0.75R",  0.75, "both"),
    ("long_0.25R",  0.25, "long"),
    ("long_0.5R",   0.50, "long"),
    ("long_0.75R",  0.75, "long"),
]
_RELAX_VARIANTS = [
    ("base_0R",       0.00, "both"),
    ("both_-0.25R",  -0.25, "both"),
    ("both_-0.5R",   -0.50, "both"),
    ("both_-0.75R",  -0.75, "both"),
    ("both_noguard",  None, "both"),
    ("long_-0.25R",  -0.25, "long"),
    ("long_-0.5R",   -0.50, "long"),
    ("long_-0.75R",  -0.75, "long"),
]
VARIANTS = _RAISE_VARIANTS if _MODE == "raise" else _RELAX_VARIANTS
_SELS = ("ALL", "LONG", "SHORT", "TRAIN", "TEST", "TEST_LONG", "TEST_SHORT")

_ORIG_EVALUATE = M4Exit.evaluate
_active: dict = {"offset": 0.0, "dir": "both", "kd": None}


def _kd_cross(side: str, k_prev: float, k_cur: float) -> bool:
    """m4_exit.py KD 돌파 조건 — 롱 K80 하향(112), 숏 K20 상향(177)."""
    if side == "LONG":
        return k_prev >= 80.0 and k_cur < 80.0
    return k_prev <= 20.0 and k_cur > 20.0


def _evaluate_with_offset(**kw):
    """실제 M4Exit.evaluate 호출 후 Phase1 KD 기준선(thr)만 변형 — 모듈 docstring 참조."""
    dec     = _ORIG_EVALUATE(**kw)
    thr     = _active["offset"]
    applies = kw["phase"] == 1 and (_active["dir"] == "both" or kw["side"] == "LONG")
    sign    = 1.0 if kw["side"] == "LONG" else -1.0
    if dec.reason == "KD-EXIT":
        gross = sign * (dec.exit_price - kw["entry_price"]) / kw["entry_price"] * 100.0 / kw["sl_pct"]
        if applies and thr is not None and thr > 0.0 and gross < thr:
            return _ORIG_EVALUATE(**{**kw, "k_prev": _NEUTRAL_K, "k_cur": _NEUTRAL_K})
    elif (applies and (thr is None or thr < 0.0) and dec.reason == "" and dec.new_phase == 1
            and _kd_cross(kw["side"], kw["k_prev"], kw["k_cur"])):
        gross = sign * (kw["close"] - kw["entry_price"]) / kw["entry_price"] * 100.0 / kw["sl_pct"]
        if not (gross < 0.0 and (thr is None or gross >= thr)):
            return dec
        dec = ExitDecision(reason="KD-EXIT", exit_price=kw["close"], qty_ratio=1.0, new_phase=1)
    else:
        return dec
    kd = _active["kd"]
    kd[(kw["side"], kw["phase"])][0] += dec.qty_ratio
    kd[(kw["side"], kw["phase"])][1] += gross * dec.qty_ratio
    return dec


M4Exit.evaluate = staticmethod(_evaluate_with_offset)


def _run_symbol(job: tuple) -> tuple:
    """심볼 1개 × 전 변형 실행. job=(sym, variants) — spawn 워커에 변형 목록을 명시 전달.
    반환: (sym, {변형: {구간: 거래목록}}, one_r_pct, {변형: KD Phase 집계})."""
    sym, variants = job
    params = make_base_params()
    data   = pickle.load(open(_CACHE_DIR / f"{sym}.pkl", "rb"))
    split  = data["1m"][-1].close_time - _TEST_DAYS * 86_400_000
    out, kd_out, one_r = {}, {}, 0.0
    for name, offset, direction in variants:
        _active.update(offset=offset, dir=direction, kd=defaultdict(lambda: [0.0, 0.0]))
        res = BacktestRunner.run(sym, params, PERIOD, preloaded=data,
                                 entry_variant="M4", exit_variant="CURRENT")
        one_r = res.one_r_pct or one_r
        tr = res.trades
        out[name] = {
            "ALL":        tr,
            "LONG":       [t for t in tr if t.side == "long"],
            "SHORT":      [t for t in tr if t.side == "short"],
            "TRAIN":      [t for t in tr if t.entry_time < split],
            "TEST":       [t for t in tr if t.entry_time >= split],
            "TEST_LONG":  [t for t in tr if t.entry_time >= split and t.side == "long"],
            "TEST_SHORT": [t for t in tr if t.entry_time >= split and t.side == "short"],
        }
        kd_out[name] = {f"{s}_P{p}": v for (s, p), v in _active["kd"].items()}
    return sym, out, one_r, kd_out


def main() -> None:
    params  = make_base_params()
    symbols = load_symbols()
    meta    = run_metadata(params, PERIOD, symbols)
    print_metadata(meta)
    missing = [s for s in symbols if not (_CACHE_DIR / f"{s}.pkl").exists()]
    if missing:
        sys.exit(f"[중단] 캐시 없음 {missing} — build_backtest_cache.py 180일 실행 필요")
    print(f"[KD 익절 최소 수익 A/B — {_MODE}] {len(symbols)}심볼 × {PERIOD}  변형 {len(VARIANTS)}개  "
          f"검증=뒤 {_TEST_DAYS}일  worker={_WORKERS}")
    print("-" * 100)

    buckets = {name: {sel: SweepBucket() for sel in _SELS} for name, _, _ in VARIANTS}
    kd_agg  = {name: defaultdict(lambda: [0.0, 0.0]) for name, _, _ in VARIANTS}
    reasons = {name: defaultdict(float) for name, _, _ in VARIANTS}
    t0 = time.time()
    with Pool(_WORKERS) as pool:
        jobs = [(s, VARIANTS) for s in symbols]
        for i, (sym, out, one_r, kd_out) in enumerate(pool.imap_unordered(_run_symbol, jobs), 1):
            for name, sels in out.items():
                for sel, trades in sels.items():
                    buckets[name][sel].add(_as_result(sym, trades, one_r))
                for t in sels["ALL"]:
                    reasons[name][t.exit_reason] += t.qty_ratio
                for k, (n, r) in kd_out[name].items():
                    kd_agg[name][k][0] += n
                    kd_agg[name][k][1] += r
            if i % 10 == 0 or i == len(symbols):
                print(f"  {i}/{len(symbols)} 심볼 완료 ({(time.time() - t0) / 60:.1f}분)", flush=True)

    summ = {name: {sel: b.summary() for sel, b in sels.items()} for name, sels in buckets.items()}
    base = summ["base_0R"]["TEST"]
    print("-" * 100)
    print(f"{'변형':<12} {'구간':<10} {'n':>6} {'WR%':>6} {'EV(R)':>9} {'PF':>7} {'±CI':>6}")
    results = []
    for name, offset, direction in VARIANTS:
        for sel in ("ALL", "TRAIN", "TEST", "TEST_LONG", "TEST_SHORT"):
            s = summ[name][sel]
            print(f"{name:<12} {sel:<10} {s['n']:6.1f} {s['wr']:6.1f} {s['ev_r']:+9.4f} {s['pf']:7.3f} {s['pf_ci']:6.3f}")
        te = summ[name]["TEST"]
        checks = {
            "test_ev_gt_base": te["ev_r"] > base["ev_r"],
            "test_pf_ci_low_ge_base_pf": (te["pf"] - te["pf_ci"]) >= base["pf"],
            "test_n_ge_100": te["n"] >= _MIN_TEST_N,
        }
        passed = name != "base_0R" and all(checks.values())
        print(f"{'':<12} 판정: {'통과' if passed else ('기준선' if name == 'base_0R' else '미통과')}  {checks}")
        results.append({"variant": name, "offset_r": offset, "direction": direction,
                        "summary": summ[name], "checks": checks, "passed": passed,
                        "exit_reasons": dict(reasons[name])})
        print("-" * 100)

    print("[기준선 Phase별 KD 익절] (건수 qty가중, 평균 총R — 비용 제외)")
    for k in sorted(kd_agg["base_0R"]):
        n, r = kd_agg["base_0R"][k]
        print(f"  {k:<10} n={n:7.1f}  평균R={r / n if n else 0.0:+.3f}")
    elapsed = time.time() - t0
    with open(_RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump({"metadata": meta, "test_days": _TEST_DAYS, "elapsed_sec": round(elapsed, 1),
                   "variants": results,
                   "baseline_kd_by_phase": {k: {"n": v[0], "sum_gross_r": v[1]}
                                            for k, v in kd_agg["base_0R"].items()}},
                  f, ensure_ascii=False, indent=2)
    print(f"[완료] {elapsed / 60:.1f}분  결과 저장: {_RESULT_PATH.name}")


def _as_result(sym: str, trades: list, one_r: float):
    """SweepBucket.add 입력용 BacktestResult (trades·one_r_pct만 사용)."""
    from bottom_engine.models import BacktestResult
    return dataclasses.replace(BacktestResult(symbol=sym, sort_mode="", period_days=180),
                               trades=trades, one_r_pct=one_r)


if __name__ == "__main__":
    main()
