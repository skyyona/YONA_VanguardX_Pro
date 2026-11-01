"""
live_backtest_reconcile.py — [② 항목 5] 실거래 기록 ↔ 같은 구간 백테스트 1:1 대조 (읽기 전용)

trade_history.json의 실거래 거래마다 같은 심볼·[진입 전 준비 구간 ~ 청산 후] 공개 시세를 받아
BacktestRunner(entry_variant="M4", exit_variant="CURRENT" — 실거래 동일 경로)를 실행하고 대조:
  진입: 같은 방향 백테스트 진입 유무·시각 차이·진입가 차이
  청산: 사유 일치(실거래 "SL"+phase → SL / BEP-SL / TRAIL), 시각·청산가 차이
  R   : 가격 기준 R = 방향 × (청산가 − 진입가)/진입가 ÷ (SL%/100)  — 양쪽 같은 정의(비용 제외)

주의
  - 거래 기록에 당시 전략 설정이 없어 현재 _strategy.json 설정으로 실행(출력에 명시).
  - 롱숏비(liq)는 Binance가 최근 30일만 제공 → 그 이전 구간은 백테스트 기본 처리.
  - 시세는 직접 페이지 조회(1초 간격·재시도·연속성 검증). 누락·불연속이면 해당 거래 대조 중단.
    (HistoricalDataLoader.load_bars는 페이지 실패 시 부분 데이터를 그대로 반환하므로 사용하지 않음)
알려진 차이(대조 시 감안)
  - KD 익절: 실거래는 봉 마감 후 최대 약 60초 뒤(지표 캐시 STAGE3 주기) 마크가 청산, 백테스트는 봉 종가
  - docs/exit_parity.md ⑦ trail_ref(마크가 vs 종가) ⑧ profit_trigger ⑨ TRAIL 체결 방식 ⑩ -16% 백스탑
    ⑰ 백테스트는 포지션 점유 무시(심볼별 독립 실행) → 거래 수 과대
  - 실거래 StochRSI는 1m·3m·5m·15m·1h 199봉 / 4h·1d 79봉 Wilder 시드(stochrsi_window_check.py 측정), 백테스트는 로드 구간 전체 시드
  - 실거래 KD 익절 k_prev는 직전 SL 루프 틱(1초), 백테스트는 직전 1m 봉

실행 (프로젝트 루트에서):
  cd C:/Users/User/YONA_VanguardX_Pro
  python live_backtest_reconcile.py
"""
import json
import pathlib
import sys
import time
from datetime import datetime, timezone

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from bottom_engine.backtest.backtest_runner import BacktestRunner
from bottom_engine.backtest.historical_data_loader import HistoricalDataLoader
from bottom_engine.sweep.base_params import make_base_params

TRADE_HISTORY    = _ROOT / "trade_history.json"
PERIOD           = "90일"        # BacktestRunner period 인자 (1h 폴백 한도·period_days 표기용)
WARMUP_DAYS      = 3             # 진입 전 준비 구간 (1m 200봉·1h EMA50·RSI 시드)
AFTER_MIN        = 120           # 청산 후 여유 구간 (분)
MATCH_WINDOW_SEC = 30 * 60       # 같은 진입으로 볼 시각 차이 한도
PAGE_LIMIT       = 1500          # klines 1회 최대 (가중치 10)
PAGE_SLEEP_SEC   = 1.0           # 페이지 간격 → 최대 600 가중치/분 (실행 중인 YONA 앱 사용량 고려)
PAGE_RETRY       = 3
TF_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}


def _fmt(ts_sec: float) -> str:
    return datetime.fromtimestamp(ts_sec, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _load_range(symbol: str, tf: str, start_ms: int, end_ms: int) -> list:
    """[start_ms, end_ms] 구간 마감 봉을 역방향 페이지로 로드. 실패·불연속이면 RuntimeError."""
    step  = TF_MS[tf]
    pages = []
    end   = end_ms
    while True:
        page = []
        for attempt in range(PAGE_RETRY):
            page = HistoricalDataLoader.load(symbol, tf, PAGE_LIMIT, end)
            if page:
                break
            time.sleep(PAGE_SLEEP_SEC * (attempt + 2))
        if not page:
            raise RuntimeError(f"{symbol} {tf} 페이지 로드 실패 (endTime={end})")
        pages.append(page)
        time.sleep(PAGE_SLEEP_SEC)
        if page[0].open_time <= start_ms or len(page) < PAGE_LIMIT:
            break
        end = page[0].open_time - 1
    bars = [b for p in reversed(pages) for b in p if start_ms <= b.open_time and b.close_time <= end_ms]
    if not bars or bars[0].open_time > start_ms + step:
        raise RuntimeError(f"{symbol} {tf} 시작 구간 미포함 (상장 이전이거나 데이터 없음)")
    for a, b in zip(bars, bars[1:]):
        if b.open_time - a.open_time != step:
            raise RuntimeError(f"{symbol} {tf} 불연속 {a.open_time}→{b.open_time}")
    return bars


def _live_reason_to_bt(reason: str, phase: int, partial_closed: bool) -> str:
    """실거래 사유 → 백테스트 사유 체계. 실거래는 SL·BEP·트레일을 'SL'+phase로 기록(bottom_panel 777-790)."""
    if "SL" in reason or "손절" in reason:
        if phase == 1:
            return "SL"
        if phase == 2:
            return "BEP-SL"
        return "TRAIL" if not partial_closed else "TRAIL|BEP-SL"
    return reason


def _price_r(side: str, entry: float, exit_p: float, sl_pct: float) -> float:
    sign = 1.0 if side == "long" else -1.0
    return sign * (exit_p - entry) / entry / (sl_pct / 100.0)


def main() -> None:
    if not TRADE_HISTORY.exists():
        print("trade_history.json 없음 — 대조할 실거래 없음")
        return
    hist   = json.loads(TRADE_HISTORY.read_text(encoding="utf-8"))
    trades = [("long", r) for r in hist.get("long", [])] + [("short", r) for r in hist.get("short", [])]
    params = make_base_params()
    print(f"[실거래↔백테스트 대조] 실거래 {len(trades)}건  설정: 현재 {params.sort_mode} "
          f"SL={params.stop_loss}% trail={params.trail_stop}% lev={params.leverage} (거래 당시 설정 미기록)")
    print("-" * 100)

    rows = []
    for side, rec in sorted(trades, key=lambda x: x[1].get("entry_time", 0.0)):
        sym = rec["symbol"]
        et, xt = float(rec["entry_time"]), float(rec["exit_time"])
        print(f"■ {sym} {side}  진입 {_fmt(et)}  청산 {_fmt(xt)}  사유 {rec.get('reason')!r} P{rec.get('phase')}")
        start_ms = int((et - WARMUP_DAYS * 86400) * 1000)
        end_ms   = int((xt + AFTER_MIN * 60) * 1000)
        try:
            data = {tf: _load_range(sym, tf, start_ms, end_ms) for tf in TF_MS}
            fr_days    = int((time.time() - et) / 86400) + WARMUP_DAYS + 2
            fr_t, fr_v = HistoricalDataLoader.load_funding_rate(sym, period_days=fr_days)
            data["fr"] = ([t for t in fr_t if t <= end_ms], [v for t, v in zip(fr_t, fr_v) if t <= end_ms])
            data["liq"] = HistoricalDataLoader.load_long_short_ratio(sym, period_days=30)
            d1 = HistoricalDataLoader.load(sym, "1d", PAGE_LIMIT)
            data["1d"] = [b for b in d1 if b.open_time <= int(et * 1000)]
        except RuntimeError as e:
            print(f"   대조 중단: {e}")
            rows.append({"sym": sym, "side": side, "status": "데이터 오류"})
            continue
        liq_t = data["liq"][0]
        if not liq_t or liq_t[0] > int(et * 1000):
            print("   주의: 진입 시점 롱숏비(liq) 기록 없음 (Binance 최근 30일 한도) — common_liq 판정 다를 수 있음")
        res = BacktestRunner.run(sym, params, PERIOD, preloaded=data,
                                 entry_variant="M4", exit_variant="CURRENT")
        sl_used = res.one_r_pct / res.l_eff if res.l_eff else params.stop_loss
        bt_pos  = [t for t in res.trades if t.side == side and t.exit_reason != "PARTIAL"]
        best    = min(bt_pos, key=lambda t: abs(t.entry_time / 1000.0 - et), default=None)
        live_r  = _price_r(side, rec["entry"], rec["exit"], sl_used)
        exp_rsn = _live_reason_to_bt(rec.get("reason", ""), int(rec.get("phase", 1)),
                                     bool(rec.get("partial_closed", False)))
        print(f"   백테스트 같은 방향 진입 {len(bt_pos)}건 (구간 내), SL 사용값 {sl_used:.3f}%")
        if best is None or abs(best.entry_time / 1000.0 - et) > MATCH_WINDOW_SEC:
            print(f"   결과: 백테스트 진입 없음 (±{MATCH_WINDOW_SEC // 60}분)  실거래 R {live_r:+.3f}")
            rows.append({"sym": sym, "side": side, "status": "미일치(진입 없음)", "live_r": live_r})
            continue
        bt_r  = _price_r(side, best.entry_price, best.exit_price, sl_used)
        match = best.exit_reason in exp_rsn.split("|")
        print(f"   진입 시각 차 {best.entry_time / 1000.0 - et:+.0f}s  진입가 차 "
              f"{(best.entry_price - rec['entry']) / rec['entry'] * 100:+.4f}%")
        print(f"   청산: 실거래 {exp_rsn} / 백테스트 {best.exit_reason} → {'일치' if match else '불일치'}  "
              f"시각 차 {best.exit_time / 1000.0 - xt:+.0f}s  청산가 차 "
              f"{(best.exit_price - rec['exit']) / rec['exit'] * 100:+.4f}%")
        print(f"   R: 실거래 {live_r:+.3f} / 백테스트 {bt_r:+.3f}  차 {bt_r - live_r:+.3f}")
        rows.append({"sym": sym, "side": side, "status": "대조", "reason_match": match,
                     "dt_entry": best.entry_time / 1000.0 - et, "dr": bt_r - live_r})

    print("-" * 100)
    done = [r for r in rows if r["status"] == "대조"]
    print(f"[요약] 실거래 {len(rows)}건 / 대조 {len(done)}건 / 진입 미일치 "
          f"{sum(1 for r in rows if r['status'].startswith('미일치'))}건 / 데이터 오류 "
          f"{sum(1 for r in rows if r['status'] == '데이터 오류')}건")
    if done:
        print(f"  청산 사유 일치 {sum(r['reason_match'] for r in done)}/{len(done)}  "
              f"R 차 평균 {sum(r['dr'] for r in done) / len(done):+.3f}  "
              f"최대 |R 차| {max(abs(r['dr']) for r in done):.3f}  "
              f"진입 시각 차 평균 {sum(r['dt_entry'] for r in done) / len(done):+.0f}s")


if __name__ == "__main__":
    main()
