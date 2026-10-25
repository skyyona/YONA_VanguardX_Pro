"""
build_backtest_cache.py — 150심볼 × 기간(90일·180일) 데이터를 pickle 캐시로 저장

저장 경로: backtest_cache/{기간}/{symbol}.pkl
  키: "1m"/"3m"/"5m"/"15m"/"1h" (list[HistoricalBar])
      "fr"/"liq" (tuple[list[int], list[float]])  — fr: 기간 전체(페이지 수집), liq: 최근 30일(Binance 상한)
      "1d" (list[HistoricalBar], 19봉 — common_new 판정용)

검증: 저장 전 TF별 연속성(누락 ≤0.5%)·최신성·TF 간 시작 시각 일치(부분 실패 vs 신규 상장 구분)·
      fr·liq 기간 포함·1d 존재를 확인. 실패 시 심볼 재시도(최대 2회), 끝내 실패하면 저장하지 않고
      기존(손상) 파일을 제거한 뒤 _meta.json "failed"에 사유 기록.
      (로더가 페이지 실패 시 부분 데이터를 반환하던 문제로 2026-10 캐시 대부분이 비거나 잘려 있었음)

체크포인트 지원: 중단 후 재실행 시 완료된 심볼 자동 스킵
  checkpoint: build_cache_checkpoint_{기간}.json (자동 관리, 전체 완료 시 삭제)

캐시 유효기간: _meta.json built_at 기준 7일
  이후 재실행 시 개별 심볼 재생성 가능

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python build_backtest_cache.py 180일           # 다운로드·검증·저장
  python build_backtest_cache.py 90일 --from-180  # 180일 캐시에서 90일 봉 수만큼 잘라 생성 (다운로드 없음)
  python build_backtest_cache.py                 # 90일 다운로드 (기존 동작)
"""
import sys
import pickle
import json
import time
import pathlib
from datetime import datetime

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from bottom_engine.backtest.backtest_runner import BacktestRunner, _TF_BARS
from bottom_engine.backtest.historical_data_loader import HistoricalDataLoader
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

_PERIODS     = {"90일": 90, "180일": 180}
PERIOD       = sys.argv[1] if len(sys.argv) > 1 else "90일"
if PERIOD not in _PERIODS:
    sys.exit(f"지원 기간: {list(_PERIODS)} (입력: {PERIOD})")
_PERIOD_DAYS = _PERIODS[PERIOD]
_FROM_180    = "--from-180" in sys.argv[2:]
_TTL_DAYS    = 7

_CACHE_DIR        = _ROOT / "backtest_cache" / PERIOD
_CHECKPOINT_PATH  = _ROOT / f"build_cache_checkpoint_{PERIOD}.json"
_META_PATH        = _CACHE_DIR / "_meta.json"

_TF_MS          = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}
_MAX_GAP_RATIO  = 0.005          # TF별 허용 누락 봉 비율
_DAY_MS         = 86_400_000
_SYMBOL_RETRY   = 2              # 검증 실패 시 심볼 재다운로드 횟수
_LIQ_DAYS       = 30             # Binance globalLongShortAccountRatio 제공 상한


def _load_checkpoint() -> set:
    if not _CHECKPOINT_PATH.exists():
        return set()
    with open(_CHECKPOINT_PATH, encoding="utf-8") as f:
        return set(json.load(f).get("completed", []))


def _save_checkpoint(completed: set) -> None:
    with open(_CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump({"completed": list(completed)}, f, ensure_ascii=False)


def _update_meta(sym: str, coverage_days: float | None = None,
                 failed: list[str] | None = None) -> None:
    """성공 시 symbols[sym]에 생성 시각·포함 일수 기록, 실패 시 failed[sym]에 사유 기록."""
    meta: dict = {}
    if _META_PATH.exists():
        with open(_META_PATH, encoding="utf-8") as f:
            meta = json.load(f)
    if not meta:
        meta = {"period": PERIOD, "built_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "ttl_days": _TTL_DAYS, "symbols": {}}
    meta.setdefault("failed", {})
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    if failed:
        meta["symbols"].pop(sym, None)
        meta["failed"][sym] = {"at": now, "problems": failed}
    else:
        meta["failed"].pop(sym, None)
        meta["symbols"][sym] = {"built_at": now, "coverage_days": round(coverage_days or 0.0, 2)}
    with open(_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def _validate(data: dict, period: str, ref_ms: int | None = None) -> tuple[list[str], float]:
    """캐시 데이터 검증. (문제 목록, 1m 기준 포함 일수) 반환 — 문제 목록이 비면 저장 가능.
    ref_ms: 최신성 기준 시각(기본 현재). TF별 기대 시작 = ref − _TF_BARS[period]×봉 길이(1h는 기간보다 짧게 설정됨).
    기대보다 늦게 시작한 TF들이 같은 시각(±1일)에 시작하고 그보다 이른 데이터가 다른 TF에 없으면
    신규 상장(정상), 아니면 부분 다운로드로 판정."""
    problems: list[str] = []
    now_ms   = ref_ms or int(time.time() * 1000)
    starts: dict[str, int] = {}
    late:   dict[str, int] = {}
    for tf, step in _TF_MS.items():
        bars = data.get(tf) or []
        if not bars:
            problems.append(f"{tf} 비어 있음")
            continue
        gaps = sum((b.open_time - a.open_time) // step - 1
                   for a, b in zip(bars, bars[1:]) if b.open_time - a.open_time != step)
        if any(b.open_time <= a.open_time for a, b in zip(bars, bars[1:])):
            problems.append(f"{tf} 시간 역순·중복")
        if gaps > _MAX_GAP_RATIO * len(bars):
            problems.append(f"{tf} 누락 {gaps}봉 ({gaps / len(bars):.2%})")
        if bars[-1].close_time < now_ms - 2 * step - 60_000:
            problems.append(f"{tf} 최신 봉 지연")
        starts[tf] = bars[0].open_time
        if bars[0].open_time > now_ms - _TF_BARS[period][tf] * step + _DAY_MS:
            late[tf] = bars[0].open_time
    if late:
        listing = min(late.values())
        if max(late.values()) - listing > _DAY_MS:
            problems.append("TF별 시작 시각 불일치(부분 다운로드) " +
                            ", ".join(f"{tf}={(now_ms - s) / _DAY_MS:.1f}일" for tf, s in late.items()))
        early = [tf for tf, s in starts.items() if tf not in late and s < listing - _DAY_MS]
        if early:
            problems.append(f"부분 다운로드 — {early}는 {list(late)}보다 이전 데이터 보유")
    data_start = starts.get("1m", now_ms)
    coverage   = (now_ms - data_start) / _DAY_MS
    fr_t = (data.get("fr") or ([], []))[0]
    if not fr_t:
        problems.append("fr 비어 있음")
    elif fr_t[0] > data_start + _DAY_MS:
        problems.append(f"fr 기간 미포함 (첫 기록이 데이터 시작보다 {(fr_t[0] - data_start) / _DAY_MS:.1f}일 늦음)")
    liq_t = (data.get("liq") or ([], []))[0]
    liq_need_start = max(data_start, now_ms - _LIQ_DAYS * _DAY_MS)
    if not liq_t or liq_t[0] > liq_need_start + _DAY_MS:
        problems.append("liq 최근 30일 미포함")
    if not data.get("1d"):
        problems.append("1d 비어 있음")
    return problems, coverage


def _slice_to_period(data: dict, period: str) -> dict:
    """긴 기간 캐시를 period의 TF별 봉 수(_TF_BARS)만큼 최근 구간으로 자른 사본. fr·liq·1d는 그대로."""
    out = dict(data)
    for tf, n in _TF_BARS[period].items():
        out[tf] = list(data[tf][-n:])
    return out


def main():
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    completed = _load_checkpoint()

    print(f"[캐시 빌더] {len(SYMBOLS)}심볼 × {PERIOD}")
    print(f"[저장 경로] {_CACHE_DIR}")
    print(f"[캐시 키] 1m/3m/5m/15m/1h/1d/fr/liq (8개)")
    if completed:
        print(f"[체크포인트] {len(completed)}/{len(SYMBOLS)} 완료, "
              f"{len(SYMBOLS)-len(completed)}개 이어서 실행")
    print("-" * 70)

    t0 = time.time()

    for sym in SYMBOLS:
        s_idx = SYMBOLS.index(sym)
        if sym in completed:
            print(f"  [{s_idx+1}/{len(SYMBOLS)}] {sym} 스킵 (체크포인트)", flush=True)
            continue

        print(f"  [{s_idx+1}/{len(SYMBOLS)}] {sym} 로딩중...", flush=True)
        t_sym = time.time()
        cache_path = _CACHE_DIR / f"{sym}.pkl"

        problems: list[str] = []
        coverage = 0.0
        for attempt in range(_SYMBOL_RETRY + 1):
            if _FROM_180:
                src = _ROOT / "backtest_cache" / "180일" / f"{sym}.pkl"
                if not src.exists():
                    problems = ["180일 캐시 없음"]
                    break
                with open(src, "rb") as f:
                    preloaded = _slice_to_period(pickle.load(f), PERIOD)
            else:
                preloaded = BacktestRunner.load_tf_bars(sym, PERIOD)
                preloaded["fr"]  = HistoricalDataLoader.load_funding_rate(sym, _PERIOD_DAYS)
                preloaded["liq"] = HistoricalDataLoader.load_long_short_ratio(sym, _PERIOD_DAYS)
                preloaded["1d"]  = HistoricalDataLoader.load(sym, "1d", _NEW_DAYS_MIN + 5)
            ref_ms = (preloaded["1m"][-1].close_time + 1) if (_FROM_180 and preloaded.get("1m")) else None
            problems, coverage = _validate(preloaded, PERIOD, ref_ms)
            if not problems or _FROM_180:
                break
            print(f"      검증 실패({attempt + 1}/{_SYMBOL_RETRY + 1}): {problems}", flush=True)

        if problems:
            if cache_path.exists():
                cache_path.unlink()   # 손상 캐시가 조용히 사용되지 않도록 제거
            _update_meta(sym, failed=problems)
            completed.add(sym)
            _save_checkpoint(completed)
            print(f"  [{s_idx+1}/{len(SYMBOLS)}] {sym} 저장 안 함 — {problems}", flush=True)
            continue

        with open(cache_path, "wb") as f:
            pickle.dump(preloaded, f, protocol=pickle.HIGHEST_PROTOCOL)

        completed.add(sym)
        _save_checkpoint(completed)
        _update_meta(sym, coverage_days=coverage)

        sym_elapsed   = time.time() - t_sym
        total_elapsed = time.time() - t0
        short = f"  ※ 포함 {coverage:.1f}일(신규 상장)" if coverage < _PERIOD_DAYS - 1 else ""
        print(f"  [{s_idx+1}/{len(SYMBOLS)}] {sym} 저장 완료 "
              f"(심볼 {sym_elapsed/60:.1f}분 / 전체 {total_elapsed/60:.1f}분 경과){short}", flush=True)

    if _CHECKPOINT_PATH.exists():
        _CHECKPOINT_PATH.unlink()

    elapsed = time.time() - t0
    print(f"\n[완료] {len(SYMBOLS)}심볼 캐시 저장 완료  소요시간 {elapsed/60:.1f}분")
    print(f"[저장 경로] {_CACHE_DIR}")
    size_mb = sum(((_CACHE_DIR / f"{s}.pkl").stat().st_size / 1024 / 1024)
                  for s in SYMBOLS if (_CACHE_DIR / f"{s}.pkl").exists())
    print(f"[실제 크기] {size_mb:.1f}MB ({len(SYMBOLS)}개 파일)")


if __name__ == "__main__":
    main()
