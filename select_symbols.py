"""
select_symbols.py — Binance USDT-M Futures 거래량 상위 심볼 선택

기준:
  - USDT 영구선물(PERPETUAL) + TRADING 상태
  - 상장 90일 이상 (백테스트 기간 전체 커버)
  - 24h 거래량(quoteVolume, USDT) 기준 내림차순 상위 N개

실행 (프로젝트 루트에서):
  python select_symbols.py
"""
import json
import time
import urllib.request
import pathlib
from datetime import datetime, timezone

_BASE         = "https://fapi.binance.com"
_MIN_DAYS     = 90          # 백테스트 기간 커버 최소 상장일
_TOP_N        = 150         # 선택할 심볼 수
_ROOT         = pathlib.Path(__file__).parent
_OUT_PATH     = _ROOT / "selected_symbols.json"

_NINETY_DAYS_MS = _MIN_DAYS * 24 * 3600 * 1000


def _fetch(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def main():
    print(f"[심볼 선택] Binance USDT-M Futures — 거래량 상위 {_TOP_N}개 (상장 {_MIN_DAYS}일+)")
    print("-" * 60)

    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - _NINETY_DAYS_MS

    # 1. 전체 심볼 정보 조회
    print("  [1/3] exchangeInfo 조회 중...", flush=True)
    info = _fetch(f"{_BASE}/fapi/v1/exchangeInfo")
    all_symbols = info.get("symbols", [])

    valid: set[str] = set()
    for s in all_symbols:
        sym = s.get("symbol", "")
        if (s.get("quoteAsset") == "USDT"
                and s.get("contractType") == "PERPETUAL"
                and s.get("status") == "TRADING"
                and s.get("onboardDate", now_ms) <= cutoff_ms
                and sym.isascii()):   # URL 인코딩 문제 방지
            valid.add(sym)

    print(f"  [1/3] 전체 {len(all_symbols)}개 → USDT 영구선물+TRADING+90일+ 필터 후 {len(valid)}개")

    # 2. 24h 거래량 조회
    print("  [2/3] 24h 티커 조회 중...", flush=True)
    tickers = _fetch(f"{_BASE}/fapi/v1/ticker/24hr")

    candidates: list[tuple[str, float]] = [
        (t["symbol"], float(t.get("quoteVolume", 0)))
        for t in tickers
        if t["symbol"] in valid
    ]
    candidates.sort(key=lambda x: x[1], reverse=True)

    top = candidates[:_TOP_N]

    # 3. 결과 출력
    print(f"  [3/3] 상위 {_TOP_N}개 선택 완료")
    print("-" * 60)
    print(f"\n{'순위':>4}  {'심볼':<18} {'24h 거래량(USDT)':>18}")
    print("-" * 45)
    for rank, (sym, vol) in enumerate(top, 1):
        print(f"  {rank:>3}.  {sym:<18} {vol:>18,.0f}")

    symbols_list = [sym for sym, _ in top]
    result = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "criteria": {
            "asset": "USDT",
            "contract_type": "PERPETUAL",
            "status": "TRADING",
            "min_days_listed": _MIN_DAYS,
            "top_n_by_volume": _TOP_N,
        },
        "total_eligible": len(valid),
        "symbols": symbols_list,
    }
    with open(_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n[저장] {_OUT_PATH}")
    print(f"[결과] {len(symbols_list)}개 심볼 선택됨")
    print(f"\n  ↓ build_backtest_cache.py 에 적용할 Python 리스트:")
    print("SYMBOLS = [")
    for i in range(0, len(symbols_list), 5):
        chunk = symbols_list[i:i + 5]
        line  = "    " + ", ".join(f'"{s}"' for s in chunk) + ","
        print(line)
    print("]")


if __name__ == "__main__":
    main()
