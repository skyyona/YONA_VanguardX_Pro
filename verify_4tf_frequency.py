"""
verify_4tf_frequency.py
"4TF 완전 정렬은 발생하지 않는다(0%)" 주장 검증 스크립트
앱의 실제 코드(StochRSI, FourTFConsensus)를 그대로 import하여
1m 봉을 3m/5m/15m으로 실제 집계한 뒤 정렬 발생률을 측정한다.
"""
from __future__ import annotations
import random
import sys
sys.path.insert(0, ".")

from middle.col2_chart_indicators.mtf_stochrsi import StochRSI
from bottom_engine.engine_core.fourtf_consensus import FourTFConsensus
from middle.models import OHLCVBar

SERIES     = 40
BARS_1M    = 3000
WARMUP     = 900
LOOKBACK   = 90
VOLATILITY = 0.0009


def make_1m(n: int, seed: int) -> list[OHLCVBar]:
    random.seed(seed)
    price = 100.0
    out: list[OHLCVBar] = []
    for i in range(n):
        o = price
        price *= (1 + random.gauss(0.0, VOLATILITY))
        out.append(OHLCVBar(
            open_time=i * 60_000, open=o,
            high=max(o, price) * 1.0004, low=min(o, price) * 0.9996,
            close=price, volume=1.0, quote_volume=1.0,
            close_time=i * 60_000 + 59_999,
        ))
    return out


def aggregate(bars: list[OHLCVBar], minutes: int) -> list[OHLCVBar]:
    out: list[OHLCVBar] = []
    usable = len(bars) - len(bars) % minutes
    for i in range(0, usable, minutes):
        chunk = bars[i:i + minutes]
        out.append(OHLCVBar(
            open_time=chunk[0].open_time, open=chunk[0].open,
            high=max(b.high for b in chunk), low=min(b.low for b in chunk),
            close=chunk[-1].close, volume=sum(b.volume for b in chunk),
            quote_volume=1.0, close_time=chunk[-1].close_time,
        ))
    return out


def main() -> None:
    total = 0
    at_least = {1: 0, 2: 0, 3: 0, 4: 0}
    long4 = short4 = long3 = short3 = 0
    anchor2 = anchor3 = anchor4 = 0

    for seed in range(SERIES):
        b1 = make_1m(BARS_1M, seed)
        b3, b5, b15 = aggregate(b1, 3), aggregate(b1, 5), aggregate(b1, 15)

        for i in range(WARMUP, BARS_1M):
            ind = {}
            dirs = {}
            for key, bars, m in (("tf1", b1, 1), ("tf3", b3, 3),
                                 ("tf5", b5, 5), ("tf15", b15, 15)):
                j = i // m
                r = StochRSI.calculate(bars[max(0, j - LOOKBACK):j])
                ind[key] = {"k": r.k, "d": r.d}
                dirs[key] = (1 if (r.k > r.d and r.k - r.d >= 2.0)
                             else -1 if (r.k < r.d and r.d - r.k >= 2.0) else 0)

            sig = FourTFConsensus.evaluate(ind)
            total += 1

            n = max(sig.aligned_long, sig.aligned_short)
            for t in (1, 2, 3, 4):
                if n >= t:
                    at_least[t] += 1
            if sig.long_consensus:
                long4 += 1
            if sig.short_consensus:
                short4 += 1
            if sig.aligned_long >= 3:
                long3 += 1
            if sig.aligned_short >= 3:
                short3 += 1

            for s in (1, -1):
                if dirs["tf15"] == s and dirs["tf5"] == s:
                    anchor2 += 1
                    if dirs["tf3"] == s:
                        anchor3 += 1
                        if dirs["tf1"] == s:
                            anchor4 += 1

    pct = lambda x: x / total * 100.0

    print(f"검사 시점: {total:,}개  ({SERIES}개 독립 시계열 x {BARS_1M - WARMUP:,} 봉)\n")
    print("── 정렬 수준별 발생률 ──")
    for t in (1, 2, 3, 4):
        print(f"  >= {t}/4 : {pct(at_least[t]):>6.2f}%")

    print("\n── 방향별 ──")
    print(f"  롱 4/4 완전 합의 : {pct(long4):>6.2f}%")
    print(f"  숏 4/4 완전 합의 : {pct(short4):>6.2f}%")
    print(f"  롱 3/4 이상      : {pct(long3):>6.2f}%")
    print(f"  숏 3/4 이상      : {pct(short3):>6.2f}%")

    both4 = long4 + short4
    print(f"\n  4/4 합계 : {pct(both4):.2f}%  ->  1m봉 {total / both4:.0f}개당 1회"
          f"  (~{total / both4 / 60:.1f}시간당 1회)")

    print("\n── 방향2(앵커 TF) 조건별 발생률 ──")
    print(f"  최소진입 15m+5m     : {pct(anchor2):>6.2f}%  (약 {total/anchor2:.0f}분당 1회)")
    print(f"  표준진입 +3m        : {pct(anchor3):>6.2f}%  (약 {total/anchor3:.0f}분당 1회)")
    print(f"  강화진입 +1m (=4/4) : {pct(anchor4):>6.2f}%  (약 {total/anchor4:.0f}분당 1회)")

    p = pct(both4) / 100.0
    print(f"\n── 통계 검정 ──")
    print(f"  참 발생률 {p*100:.2f}%일 때, 20개 심볼 1회 스냅샷에서")
    print(f"  4/4가 0개로 관측될 확률 = (1-{p:.4f})^20 = {(1-p)**20*100:.1f}%")
    print("  -> 스냅샷 1회의 '0개'는 '발생하지 않는다'의 증거가 되지 못한다.")


if __name__ == "__main__":
    main()
