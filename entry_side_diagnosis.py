"""
entry_side_diagnosis.py — 숏 진입 점검: 진입 시점 지표 구간별 롱·숏 성과 진단 — 150심볼 × 180일 (측정 전용)

_strategy.json "24h Ticker" 실거래 값 기준(entry M4 / exit CURRENT). 진입 시점 지표는 실제 M4Entry.evaluate
호출을 관찰해 기록(판정 미변경)하고, 백테스트가 실제로 연 진입(봉마다 long·short 순 2회 호출, long 우선)을
포지션 순서와 1:1 대응시켜 포지션 성과(R = 같은 진입의 거래 행 pnl_pct 합 ÷ 1R)와 결합한다.

구간: 심볼별 마지막 1m 봉 기준 뒤 60일 = 검증, 그 앞 = 학습 (진입 시각 기준).
지표 구간(롱은 대칭 기준):
  trend·fr는 진입 판정 입력(ind)이 아닌 캐시에서 직접 계산 — 24h Ticker는 macro_ema=False라 러너가 EMA를 계산하지 않고
  (backtest_runner 181), ind["funding_rate"]는 실제 값이 아닌 차단용 표식(0/±1, 762-766)이기 때문.
  trend  : 1h EMA5 vs EMA50(BacktestRunner._calc_ema_series, 마감 1h 봉 = 러너 pos_1h 정렬) —
           진입 방향과 같은 추세(with) / 역추세(against)   (G_ema는 24h Ticker에서 꺼져 있음)
  k5     : 5m K (숏 60~70·70~80·80~90·90+ / 롱 40~30·30~20·20~10·10-)
  rsi15  : 15m RSI 50에서 진입 방향 쪽 거리 (0~5·5~10·10+)
  fr     : 진입 시점 직전 실제 펀딩비(캐시 fr, 러너 314-315와 같은 bisect) —
           진입 방향에 유리(숏: FR>0 수령 / 롱: FR<0 수령) / 불리 / 0
  atr    : 1h ATR% (1.85~3·3~5·5+) — G4 하한은 SL/2
  vol    : 1m 거래량 배수 (1.5~2·2~3·3+)
  swing  : 15m 스윙 구조 일치(swing_bear / swing_bull) 여부
  grade  : QualityGrader 등급(A~D) — 24h Ticker에서 게이트로는 꺼져 있음, 진단용 계산
엔진·설정·전략 코드 변경 없음. 네트워크 호출 차단. 결과 저장: entry_side_diagnosis_result.json

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python entry_side_diagnosis.py
"""
import bisect
import copy
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
    raise RuntimeError("entry_side_diagnosis: 네트워크 호출 차단 — 캐시만 사용")


for _name in dir(_hdl.HistoricalDataLoader):
    if _name.startswith("load"):
        setattr(_hdl.HistoricalDataLoader, _name, staticmethod(_network_blocked))

from bottom_engine.backtest.backtest_runner import BacktestRunner
from bottom_engine.engine_core.quality_grader import QualityGrader
from bottom_engine.strategy.m4_entry import M4Entry
from bottom_engine.sweep.base_params import load_symbols, make_base_params, run_metadata, print_metadata

PERIOD       = "180일"
_CACHE_DIR   = _ROOT / "backtest_cache" / PERIOD
_RESULT_PATH = _ROOT / "entry_side_diagnosis_result.json"
_TEST_DAYS   = 60
_WORKERS     = 8
_MIN_BUCKET  = 20         # 학습·검증 각 구간 최소 포지션 수 (미만은 참고용 표시)

_ORIG_EVALUATE = M4Entry.evaluate
_calls: list = []         # (side, ok, ind 사본 | None) — 워커 프로세스별


def _observe(side, ind_data, *args, **kwargs):
    ok, reason = _ORIG_EVALUATE(side, ind_data, *args, **kwargs)
    _calls.append((side, ok, copy.deepcopy(ind_data) if ok else None))
    return ok, reason


M4Entry.evaluate = staticmethod(_observe)


def _taken(calls: list) -> list:
    """실제로 열린 진입 — 봉마다 long·short 순서 2회 호출, long 우선(backtest_runner M4 진입 분기)."""
    out = []
    for i in range(0, len(calls) - 1, 2):
        (s_l, ok_l, ind_l), (s_s, ok_s, ind_s) = calls[i], calls[i + 1]
        assert (s_l, s_s) == ("long", "short"), "evaluate 호출 순서 가정 위반"
        if ok_l:
            out.append(("long", ind_l))
        elif ok_s:
            out.append(("short", ind_s))
    return out


def _features(side: str, ind: dict, e5: float, e50: float, fr: float) -> dict:
    """e5·e50·fr: 캐시에서 계산한 진입 시점 1h EMA와 실제 펀딩비(%)."""
    is_long = side == "long"
    trend = "n/a" if not (e5 > 0 and e50 > 0) else ("with" if (e5 > e50) == is_long else "against")
    k5 = float(ind.get("tf5", {}).get("k", 50.0))
    kx = (100.0 - k5) if is_long else k5            # 롱은 대칭(100−K)으로 같은 구간 사용
    kb = "90+" if kx >= 90 else "80~90" if kx >= 80 else "70~80" if kx >= 70 else "60~70"
    rd = (float(ind.get("tf15_rsi", 50.0)) - 50.0) * (1.0 if is_long else -1.0)
    rb = "10+" if rd >= 10 else "5~10" if rd >= 5 else "0~5"
    fb = "0" if fr == 0 else ("favourable" if (fr < 0) == is_long else "adverse")
    atr = float(ind.get("atr_pct", 0.0))
    ab = "5+" if atr >= 5 else "3~5" if atr >= 3 else "<3"
    vr = float(ind.get("volume_ratio", 0.0))
    vb = "3+" if vr >= 3 else "2~3" if vr >= 2 else "1.5~2"
    sw = bool(ind.get("swing_bull" if is_long else "swing_bear", False))
    grade, _ = QualityGrader.grade(ind, side)
    return {"trend": trend, "k5": kb, "rsi15": rb, "fr": fb, "atr": ab, "vol": vb,
            "swing": "match" if sw else "no", "grade": grade}


def _run_symbol(sym: str) -> list:
    """심볼 1개 실행 → [(side, period, R, features)] 포지션 목록."""
    params = make_base_params()
    data   = pickle.load(open(_CACHE_DIR / f"{sym}.pkl", "rb"))
    split  = data["1m"][-1].close_time - _TEST_DAYS * 86_400_000
    _calls.clear()
    res = BacktestRunner.run(sym, params, PERIOD, preloaded=data, entry_variant="M4", exit_variant="CURRENT")
    if not res.one_r_pct:
        return []
    rows = defaultdict(float)
    for t in res.trades:
        rows[(t.entry_time, t.side)] += t.pnl_pct
    positions = sorted((t for t in res.trades if t.exit_reason != "PARTIAL"), key=lambda t: t.entry_time)
    taken     = _taken(_calls)
    assert len(taken) >= len(positions), f"{sym} 진입 관찰 수 부족"
    closes_1h = [b.close for b in data["1h"]]
    times_1h  = [b.close_time for b in data["1h"]]
    ema5_1h   = BacktestRunner._calc_ema_series(closes_1h, 5)
    ema50_1h  = BacktestRunner._calc_ema_series(closes_1h, 50)
    fr_times, fr_pct = data["fr"]
    out = []
    for p, (side, ind) in zip(positions, taken):
        assert side == p.side, f"{sym} 진입 순서 매핑 오류"
        r     = rows[(p.entry_time, p.side)] / res.one_r_pct
        pos1h = max(0, bisect.bisect_right(times_1h, p.entry_time) - 1)
        fpos  = bisect.bisect_right(fr_times, p.entry_time) - 1
        fr    = fr_pct[fpos] if fpos >= 0 else 0.0
        out.append((p.side, "TEST" if p.entry_time >= split else "TRAIN", r,
                    _features(side, ind, ema5_1h[pos1h], ema50_1h[pos1h], fr)))
    return out


def _stat(rs: list) -> dict:
    n = len(rs)
    if not n:
        return {"n": 0, "wr": 0.0, "ev_r": 0.0}
    return {"n": n, "wr": sum(1 for r in rs if r > 0) / n * 100.0, "ev_r": sum(rs) / n}


def main() -> None:
    params  = make_base_params()
    symbols = load_symbols()
    meta    = run_metadata(params, PERIOD, symbols)
    print_metadata(meta)
    missing = [s for s in symbols if not (_CACHE_DIR / f"{s}.pkl").exists()]
    if missing:
        sys.exit(f"[중단] 캐시 없음 {missing}")
    t0 = time.time()
    with Pool(_WORKERS) as pool:
        positions = [p for chunk in pool.imap_unordered(_run_symbol, symbols) for p in chunk]
    print(f"[진입 지표 구간별 진단] {len(symbols)}심볼 × {PERIOD}  포지션 {len(positions)}건  "
          f"({(time.time() - t0) / 60:.1f}분)  R = 포지션 단위(부분 청산 합산)")
    result = {"metadata": meta, "test_days": _TEST_DAYS, "positions": len(positions), "sides": {}}
    for side in ("short", "long"):
        sp = [p for p in positions if p[0] == side]
        tot = {per: _stat([p[2] for p in sp if p[1] == per]) for per in ("TRAIN", "TEST")}
        print("=" * 104)
        print(f"[{side.upper()}] 전체 학습 n={tot['TRAIN']['n']} EV={tot['TRAIN']['ev_r']:+.3f}R / "
              f"검증 n={tot['TEST']['n']} EV={tot['TEST']['ev_r']:+.3f}R")
        print(f"{'지표':<7} {'구간':<11} {'학습 n':>6} {'WR%':>6} {'EV(R)':>8}   {'검증 n':>6} {'WR%':>6} {'EV(R)':>8}   비고")
        side_res = {"total": tot, "features": {}}
        for feat in ("trend", "k5", "rsi15", "fr", "atr", "vol", "swing", "grade"):
            buckets = sorted({p[3][feat] for p in sp})
            side_res["features"][feat] = {}
            for b in buckets:
                st = {per: _stat([p[2] for p in sp if p[1] == per and p[3][feat] == b]) for per in ("TRAIN", "TEST")}
                side_res["features"][feat][b] = st
                small = st["TRAIN"]["n"] < _MIN_BUCKET or st["TEST"]["n"] < _MIN_BUCKET
                both_neg = st["TRAIN"]["ev_r"] < 0 and st["TEST"]["ev_r"] < 0
                note = "표본 부족" if small else ("학습·검증 모두 음수" if both_neg else "")
                print(f"{feat:<7} {b:<11} {st['TRAIN']['n']:6d} {st['TRAIN']['wr']:6.1f} {st['TRAIN']['ev_r']:+8.3f}   "
                      f"{st['TEST']['n']:6d} {st['TEST']['wr']:6.1f} {st['TEST']['ev_r']:+8.3f}   {note}")
        result["sides"][side] = side_res
    with open(_RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[완료] {(time.time() - t0) / 60:.1f}분  결과 저장: {_RESULT_PATH.name}")


if __name__ == "__main__":
    main()
