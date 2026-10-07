"""
build_backtest_cache.py — 44심볼 × 90일 데이터를 pickle 캐시로 저장

저장 경로: backtest_cache/90일/{symbol}.pkl
  키: "1m"/"3m"/"5m"/"15m"/"1h" (list[HistoricalBar])
      "fr"/"liq" (tuple[list[int], list[float]])
      "1d" (list[HistoricalBar], 19봉 — common_new 판정용)

체크포인트 지원: 중단 후 재실행 시 완료된 심볼 자동 스킵
  checkpoint: build_cache_checkpoint.json (자동 관리, 전체 완료 시 삭제)

캐시 유효기간: _meta.json built_at 기준 7일
  이후 재실행 시 개별 심볼 재생성 가능

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python build_backtest_cache.py
"""
import sys
import pickle
import json
import time
import pathlib
from datetime import datetime

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from bottom_engine.backtest.backtest_runner import BacktestRunner
from bottom_engine.backtest.historical_data_loader import HistoricalDataLoader
from bottom_engine.constants import _NEW_DAYS_MIN

SYMBOLS = [
    "QUSDT", "QNTUSDT", "USUSDT", "BTWUSDT",
    "RAREUSDT", "ONEUSDT", "MARSCOINUSDT", "MUBARAKUSDT", "GRASSUSDT",
    "INXUSDT", "AZTECUSDT", "GRTUSDT", "ARXUSDT", "NILUSDT",
    "LYNUSDT", "SAGAUSDT", "PHAROSUSDT", "IRYSUSDT", "PHAUSDT",
    "NOMUSDT", "AKEUSDT", "NMRUSDT", "ONDOUSDT", "CCUSDT",
    "WUSDT", "PUMPUSDT", "ZROUSDT", "MONUSDT", "BULLAUSDT",
    "HBARUSDT", "FLOCKUSDT", "SEIUSDT", "TAKEUSDT", "AIOTUSDT",
    "JASMYUSDT", "ARKUSDT", "USELESSUSDT", "PONSUSDT", "HUMAUSDT",
    "METUSDT", "IOTAUSDT", "TRIAUSDT", "LSKUSDT", "PTBUSDT",
]

PERIOD       = "90일"
_PERIOD_DAYS = 90
_TTL_DAYS    = 7

_CACHE_DIR        = _ROOT / "backtest_cache" / PERIOD
_CHECKPOINT_PATH  = _ROOT / "build_cache_checkpoint.json"
_META_PATH        = _CACHE_DIR / "_meta.json"


def _load_checkpoint() -> set:
    if not _CHECKPOINT_PATH.exists():
        return set()
    with open(_CHECKPOINT_PATH, encoding="utf-8") as f:
        return set(json.load(f).get("completed", []))


def _save_checkpoint(completed: set) -> None:
    with open(_CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump({"completed": list(completed)}, f, ensure_ascii=False)


def _update_meta(sym: str) -> None:
    meta: dict = {}
    if _META_PATH.exists():
        with open(_META_PATH, encoding="utf-8") as f:
            meta = json.load(f)
    if not meta:
        meta = {"period": PERIOD, "built_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "ttl_days": _TTL_DAYS, "symbols": {}}
    meta["symbols"][sym] = {"built_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
    with open(_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


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

        preloaded = BacktestRunner.load_tf_bars(sym, PERIOD)
        preloaded["fr"]  = HistoricalDataLoader.load_funding_rate(sym)
        preloaded["liq"] = HistoricalDataLoader.load_long_short_ratio(sym, _PERIOD_DAYS)
        preloaded["1d"]  = HistoricalDataLoader.load(sym, "1d", _NEW_DAYS_MIN + 5)

        cache_path = _CACHE_DIR / f"{sym}.pkl"
        with open(cache_path, "wb") as f:
            pickle.dump(preloaded, f, protocol=pickle.HIGHEST_PROTOCOL)

        completed.add(sym)
        _save_checkpoint(completed)
        _update_meta(sym)

        sym_elapsed   = time.time() - t_sym
        total_elapsed = time.time() - t0
        print(f"  [{s_idx+1}/{len(SYMBOLS)}] {sym} 저장 완료 "
              f"(심볼 {sym_elapsed/60:.1f}분 / 전체 {total_elapsed/60:.1f}분 경과)", flush=True)

    if _CHECKPOINT_PATH.exists():
        _CHECKPOINT_PATH.unlink()

    elapsed = time.time() - t0
    print(f"\n[완료] {len(SYMBOLS)}심볼 캐시 저장 완료  소요시간 {elapsed/60:.1f}분")
    print(f"[저장 경로] {_CACHE_DIR}")
    size_mb = sum(((_CACHE_DIR / f"{s}.pkl").stat().st_size / 1024 / 1024)
                  for s in SYMBOLS if (_CACHE_DIR / f"{s}.pkl").exists())
    print(f"[실제 크기] {size_mb:.1f}MB (44개 파일)")


if __name__ == "__main__":
    main()
