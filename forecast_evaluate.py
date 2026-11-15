"""
forecast_evaluate.py — 가격 예고 4주 실사용 검증 채점 (앱이 기록한 data/forecast_log_{현재 판정식 버전}.csv)

  python forecast_evaluate.py           # 채점 결과 출력·증거 파일 저장 (판정식 파일 변경 없음)
  python forecast_evaluate.py --apply   # 위 결과로 forecast_params.json labels[].live_status 갱신 (통과/탈락/검증 중)

채점: 적용 조건(list·all)·표시별 사건(같은 종목 12h 안 반복 제외) · 각 사건 이후 12h 가격(5m 봉 145개 조회)
      기준 = 같은 24h 변동률 범위 전체 기록에서 무작위 표본(최대 400) 같은 방법 채점
통과 기준 (검증 시작 전 고정):
  사건 ≥ 60 · 적중(12h 방향 ±5%)이 기준의 1.5배 이상 · 일 단위 t ≥ 2
  방향 표시(▼·▲): 방향 이익 비율 ≥ 55% · 방향 수익 중앙값 > 0 · 기간 앞뒤 절반 방향 평균 모두 > 0
  사건 < 60: 기록 기간 8주 미만이면 '검증 중'(연장), 8주 이상이면 '탈락'
수집은 IP 사용량 헤더(1분 1,500 초과 시 대기)로 앱과 같은 IP 한도를 침범하지 않는다.
운영 순서: 채점(--apply) → 재학습(forecast_train.py) — 재학습하면 새 판정식은 새 기록 파일로 다시 검증한다.
"""
import sys, csv, time, json, random, datetime, statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import rate_gate
from middle.api.binance_client import MiddleBinanceClient
from middle.data.ohlcv_data import parse_kline_row
from middle.analysis.forecast import PARAMS_PATH, LABEL_TEXT, STEP_MS, HORIZON_BARS, log_path

LOG: Path | None = None   # None = 현재 판정식 버전의 기록 파일 (forecast.log_path)
EVIDENCE = Path(r"C:\Users\User\yona_lab_gitmeta\f_github")
B = "https://fapi.binance.com"
MIN_EVENTS, MAX_WEEKS = 60, 8
cl = MiddleBinanceClient()


def _path(sym: str, t: int):
    """판정 시각 t(봉 마감) 이후 12h: (12h 수익률 %, 4h 안 최저 %, 4h 안 최고 %) — 봉 부족이면 None."""
    rate_gate.wait_if_blocked()              # 차단 중이면 해제까지 대기 (앱과 같은 차단 기록 공유)
    raw = cl._get(f"{B}/fapi/v1/klines?symbol={sym}&interval=5m&startTime={t - STEP_MS}&limit={HORIZON_BARS + 2}")
    time.sleep(0.3)
    if int(cl._last_used_weight or 0) > 1500:
        time.sleep(15)
    if not isinstance(raw, list):
        return None
    bars = []
    for k in raw:
        try:
            bars.append(parse_kline_row(k))
        except (IndexError, ValueError):
            continue
    if not bars or bars[0].close_time + 1 != t or len(bars) < HORIZON_BARS + 1:
        return None
    if bars[HORIZON_BARS].open_time - bars[0].open_time != HORIZON_BARS * STEP_MS:
        return None                                   # 점검·중단으로 봉이 빠짐 — 학습(forecast_train)과 같은 연속성 조건
    if bars[HORIZON_BARS].close_time + 1 > time.time() * 1000:
        return None                                   # 12h 미경과
    c0 = bars[0].close
    w4 = bars[1:49]
    return ((bars[HORIZON_BARS].close / c0 - 1) * 100,
            (min(b.low for b in w4) / c0 - 1) * 100, (max(b.high for b in w4) / c0 - 1) * 100)


def main(apply: bool) -> None:
    params = json.loads(PARAMS_PATH.read_text(encoding="utf-8"))
    log = LOG if LOG is not None else log_path(str(params.get("trained_at", "")))
    raw = list(csv.DictReader(open(log, encoding="utf-8")))
    seen, rows = set(), []
    for r in raw:                          # 같은 판정 시점·종목은 한 번만 (2026-11-10 시작 직후 중복 기록 93행 포함)
        k = (r["t_close"], r["symbol"])
        if k not in seen:
            seen.add(k); rows.append(r)
    ts = [int(r["t_close"]) for r in rows]
    span_days = (max(ts) - min(ts)) / 86_400_000 if ts else 0.0
    fmt = lambda ms: datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")
    out = [f"# {datetime.datetime.now():%Y-%m-%d %H:%M:%S} 가격 예고 실사용 채점 · {log.name} · 기록 {len(rows)}행 (중복 제외 {len(raw) - len(rows)}) · "
           f"{fmt(min(ts)) if ts else '-'} ~ {fmt(max(ts)) if ts else '-'} ({span_days:.1f}일) · 판정식 {params.get('trained_at')}"]
    random.seed(11)
    for lab in params["labels"]:
        if not lab.get("adopted"):
            out.append(f"[{lab.get('context', 'all')}·{lab['key']}] 학습 검증 미채택 — 채점 생략"); continue
        key, side, ctx = lab["key"], lab["direction"], lab.get("context", "all")
        lo, hi = lab["r24_range"]
        hit = {"S": lambda f: f <= -5, "L": lambda f: f >= 5, "A": lambda f: abs(f) >= 5}[side]
        sg = -1 if side == "S" else 1
        last, ev = {}, []
        for r in sorted((r for r in rows if r["context"] == ctx and key in r["labels"].split("|")),
                        key=lambda r: int(r["t_close"])):
            t = int(r["t_close"])
            if t - last.get(r["symbol"], -10**15) >= HORIZON_BARS * STEP_MS:
                last[r["symbol"]] = t; ev.append(r)
        pool = [r for r in rows if r["context"] == ctx and lo <= float(r["r24"]) < hi]
        base_rows = random.sample(pool, min(400, len(pool)))
        evp = [(r, _path(r["symbol"], int(r["t_close"]))) for r in ev]
        evp = [(r, p) for r, p in evp if p is not None]
        bp = [p for p in (_path(r["symbol"], int(r["t_close"])) for r in base_rows) if p is not None]
        n = len(evp)
        base = sum(hit(p[0]) for p in bp) / len(bp) * 100 if bp else 0.0
        status, s = "검증 중", {"events": n, "base_hit_pct": round(base, 2), "base_samples": len(bp)}
        if n:
            hr = sum(hit(p[0]) for _, p in evp) / n * 100
            dr = [sg * p[0] for _, p in evp]
            days = {}
            for (r, p), v in zip(evp, dr):
                days.setdefault(int(r["t_close"]) // 86_400_000, []).append(
                    (100.0 if hit(p[0]) else 0.0) - base if side == "A" else v)
            dm = [st.mean(v) for v in days.values()]
            tval = st.mean(dm) / (st.stdev(dm) / len(dm) ** 0.5) if len(dm) > 2 and st.stdev(dm) > 0 else 0.0
            mid = min(ts) + (max(ts) - min(ts)) // 2
            h1 = [v for (r, _), v in zip(evp, dr) if int(r["t_close"]) < mid]
            h2 = [v for (r, _), v in zip(evp, dr) if int(r["t_close"]) >= mid]
            adv = [(p[1] <= -3 if side != "S" else p[2] >= 3) for _, p in evp]
            s.update({"hit_pct": round(hr, 2), "lift": round(hr / base, 2) if base else 0.0,
                      "dir_mean_pct": round(st.mean(dr), 3), "dir_median_pct": round(st.median(dr), 3),
                      "dir_profit_ratio_pct": round(sum(v > 0 for v in dr) / n * 100, 1),
                      "adverse3_4h_pct": round(sum(adv) / n * 100, 1), "days": len(days), "day_t": round(tval, 2),
                      "half1_dir_mean_pct": round(st.mean(h1), 3) if h1 else None,
                      "half2_dir_mean_pct": round(st.mean(h2), 3) if h2 else None})
            if n >= MIN_EVENTS:
                ok = base > 0 and hr / base >= 1.5 and tval >= 2
                if side != "A":
                    ok = ok and s["dir_profit_ratio_pct"] >= 55 and s["dir_median_pct"] > 0 and bool(h1) and bool(h2) \
                         and st.mean(h1) > 0 and st.mean(h2) > 0
                status = "통과" if ok else "탈락"
        if n < MIN_EVENTS:
            status = "탈락" if span_days >= MAX_WEEKS * 7 else "검증 중"
        lab["live_test"] = s
        if apply:
            lab["live_status"] = status
        out.append(f"[{ctx}·{key}] {status} · {LABEL_TEXT[key]} · {json.dumps(s, ensure_ascii=False)}")
    if apply:
        PARAMS_PATH.write_text(json.dumps(params, ensure_ascii=False, indent=1), encoding="utf-8")
        out.append(f"판정식 파일 live_status 갱신: {PARAMS_PATH}")
    text = "\n".join(out); print(text)
    (EVIDENCE / f"yona_forecast_evaluate_{datetime.datetime.now():%Y%m%d_%H%M}.log").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    rate_gate.install()   # 바이낸스 429/418 공통 차단 (앱과 차단 기록 공유)
    main("--apply" in sys.argv[1:])
