"""
forecast_train.py — 가격 예고 판정식 학습·검증 → middle/analysis/forecast_params.json

  python forecast_train.py collect   # 거래량 상위 150 · 최근 30일 5m 봉(체결 매수량 포함) + 5m OI 수집 (약 1시간)
  python forecast_train.py train     # 수집 자료로 학습(앞 20일)·검증(12h 간격 뒤 기간) → 판정식 파일 작성

재학습 주기: 4주(바이낸스 OI 이력 30일 한도 — 매번 새 자료). 앱 사용이 적은 시간 실행 권장.
운영 순서: 먼저 forecast_evaluate.py로 현재 판정식 실사용 채점 → 그다음 재학습.
  새 판정식(trained_at)은 새 기록 파일(data/forecast_log_{버전}.csv)에서 처음부터 실사용 검증한다 (버전 섞임 방지).
수집은 IP 사용량 헤더(1분 1,500 초과 시 대기)·futures/data 요청 간격으로 앱과 같은 IP 한도를 침범하지 않는다.
지표 = middle.analysis.forecast.compute_features (앱과 단일 정의) · 봉 파싱 = middle.data.ohlcv_data.parse_kline_row.

적용 조건: list = 각 시점 24h 변동률 상위 1/6 표본(앱 1열 24h Ticker 목록 종목) · all = 그 밖 — 조건마다 따로 경계·검증·채택.
채택 기준 (학습 전 고정, 검증 기간 사건 = 같은 종목 12h 안 반복 제외):
  사건 ≥ 30 · 적중(방향 기준 12h ±5%)이 같은 범위 기준 적중의 1.5배 이상
  방향 표시(▼·▲)는 추가로 방향 이익 비율 ≥ 55% · 방향 수익 중앙값 > 0 · 방향 수익 평균 > 0
  (평균 조건: 2026-11-10 추가 — 실사용 기준(앞뒤 절반 평균 > 0)과 일치, 평균 손실 신호 표시 방지)
교체 규칙: 새 판정식에 채택 표시가 1개 이상일 때만 기존 파일 교체 (아니면 forecast_params_candidate.json만 저장).
"""
import sys, time, json, math, pickle, random, datetime, statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from middle.api.binance_client import MiddleBinanceClient
from middle.data.ohlcv_data import parse_kline_row
from middle.models import OHLCVBar
from middle.analysis.forecast import (compute_features, FEATURE_NAMES, LABEL_TEXT, PARAMS_PATH, CONTEXT_LIST, CONTEXT_ALL,
                                      STEP_MS, BARS_NEEDED, HORIZON_BARS)

DATA_PATH = ROOT / "backtest_cache" / "forecast" / "forecast_data.pkl"
EVIDENCE  = Path(r"C:\Users\User\yona_lab_gitmeta\f_github")
B = "https://fapi.binance.com"
DAYS, N_SYMBOLS, TRAIN_DAYS = 30, 150, 20
LIST_SHARE = 6   # 24h 목록 조건 표본 = 각 시점 24h 변동률 상위 1/6 (앱 1열 목록 100/전체 약 600과 같은 비율)
INF = 1e9
# (키, 모델, 24h 변동률 범위, 학습 기간 점수 상위 비율, 방향) — 학습 전 고정, 적용 조건(list·all)마다 따로 경계·검증
CANDIDATES = (
    ("peak_drop", "dn",  (15.0, INF),  0.10, "S"),
    ("down",      "dn",  (-INF, 15.0), 0.10, "S"),
    ("early_up",  "up",  (-INF, 15.0), 0.05, "L"),
    ("big_move",  "big", (-INF, 15.0), 0.05, "A"),
)
TARGETS = {"dn": lambda f: f <= -5, "up": lambda f: f >= 5, "big": lambda f: abs(f) >= 5}


# ── 수집 ─────────────────────────────────────────────────────
def collect() -> None:
    cl = MiddleBinanceClient()

    def get(url: str, pause: float):
        for _ in range(2):
            r = cl._get(url)
            time.sleep(pause)
            if int(cl._last_used_weight or 0) > 1500:
                time.sleep(15)
            if r is not None:
                return r
            time.sleep(30)
        return None

    now = int(time.time() * 1000) // STEP_MS * STEP_MS
    start = now - DAYS * 86_400_000
    tk = sorted([t for t in (cl.fetch_all_tickers() or []) if t["symbol"].endswith("USDT")],
                key=lambda t: -float(t["quoteVolume"]))
    syms = [t["symbol"] for t in tk[:N_SYMBOLS]]
    data, t0 = {}, time.time()
    for n, s in enumerate(syms):
        rows, st_ = [], start
        while st_ < now:
            r = get(f"{B}/fapi/v1/klines?symbol={s}&interval=5m&startTime={st_}&limit=1000", 0.5) or []
            if not r:
                break
            rows += r
            st_ = int(r[-1][0]) + STEP_MS
            if len(r) < 1000:
                break
        bars = []
        for k in rows[:-1]:                      # 마지막 원소 = 진행 중 봉 (ohlcv_data._parse_klines와 같은 규칙)
            try:
                b = parse_kline_row(k)
            except (IndexError, ValueError):
                continue
            if not bars or b.open_time > bars[-1].open_time:
                bars.append(b)
        oi, en = {}, now
        while en > start:                         # startTime만 주면 최신 500개 → endTime으로 과거 방향 이동
            r = get(f"{B}/futures/data/openInterestHist?symbol={s}&period=5m&endTime={en}&limit=500", 0.6) or []
            if not r:
                break
            for x in r:
                try:
                    oi[int(x["timestamp"])] = float(x["sumOpenInterest"])
                except (KeyError, TypeError, ValueError):
                    continue
            nxt = int(r[0]["timestamp"]) - STEP_MS
            if nxt >= en or len(r) < 500:
                break
            en = nxt
        data[s] = {"bars": [(b.open_time, b.open, b.high, b.low, b.close, b.volume, b.quote_volume,
                             b.close_time, b.taker_buy_volume) for b in bars], "oi": oi}
        if n % 25 == 0:
            print(f"  수집 {n}/{len(syms)} {time.time()-t0:.0f}초 · {s} 봉 {len(bars)} · OI {len(oi)}", flush=True)
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    pickle.dump({"collected_at": now, "symbols": syms, "data": data}, open(DATA_PATH, "wb"))
    print(f"수집 완료 {time.time()-t0:.0f}초 · {len(data)}종목 → {DATA_PATH}")


# ── 학습·검증 ────────────────────────────────────────────────
def _samples(D: dict) -> list[tuple]:
    """(t, sym, feats, f12, i, bars) — 15분 마감 시점마다, 이후 12h 연속 봉이 있는 경우만."""
    out = []
    for s, d in D.items():
        bars = [OHLCVBar(*x) for x in d["bars"]]
        oi = d["oi"]
        for i in range(BARS_NEEDED - 1, len(bars) - HORIZON_BARS):
            t_close = bars[i].close_time + 1
            if t_close % 900_000:
                continue
            if bars[i + HORIZON_BARS].open_time - bars[i].open_time != HORIZON_BARS * STEP_MS:
                continue
            feats = compute_features(bars[i - BARS_NEEDED + 1:i + 1], oi)
            if feats is None:
                continue
            f12 = (bars[i + HORIZON_BARS].close / bars[i].close - 1) * 100
            out.append((t_close, s, feats, f12, i, bars))
    return out


def _list_members(rows: list[tuple]) -> set[tuple]:
    """(t, sym) — 각 시점 표본 중 24h 변동률 상위 1/LIST_SHARE (앱: 1열 24h Ticker 목록 종목)."""
    by_t: dict[int, list] = {}
    for r in rows:
        by_t.setdefault(r[0], []).append(r)
    out = set()
    for t, rs in by_t.items():
        k = max(1, -(-len(rs) // LIST_SHARE))
        out.update((t, r[1]) for r in sorted(rs, key=lambda r: -r[2]["r24"])[:k])
    return out


def _fit(Z: list[list[float]], y: list[int], epochs: int = 4, lr: float = 0.05, l2: float = 1e-4):
    random.seed(7)
    nf = len(Z[0]); w = [0.0] * nf
    pr = max(1e-6, min(1 - 1e-6, sum(y) / len(y))); b = math.log(pr / (1 - pr))
    idx = list(range(len(Z)))
    for ep in range(epochs):
        random.shuffle(idx); a = lr / (1 + ep)
        for k in idx:
            x = Z[k]; s = b + sum(w[j] * x[j] for j in range(nf))
            g = 1 / (1 + math.exp(-max(-30, min(30, s)))) - y[k]
            b -= a * g
            for j in range(nf):
                w[j] -= a * (g * x[j] + l2 * w[j])
    return w, b


def _adverse(bars, i, side, n=48, pct=3.0) -> bool:
    c = bars[i].close
    for j in range(i + 1, min(i + n + 1, len(bars))):
        if side > 0 and bars[j].low <= c * (1 - pct / 100): return True
        if side < 0 and bars[j].high >= c * (1 + pct / 100): return True
    return False


def train() -> None:
    P = pickle.load(open(DATA_PATH, "rb"))
    rows = sorted(_samples(P["data"]), key=lambda r: r[0])
    t_split = rows[0][0] + TRAIN_DAYS * 86_400_000
    train_r = [r for r in rows if r[0] < t_split]
    test_r  = [r for r in rows if r[0] >= t_split + HORIZON_BARS * STEP_MS]   # 학습 결과 기간과 겹치지 않게 12h 간격
    nf = len(FEATURE_NAMES)
    mu = [st.mean(r[2][n] for r in train_r) for n in FEATURE_NAMES]
    sd = [st.pstdev([r[2][n] for r in train_r]) or 1.0 for n in FEATURE_NAMES]
    z = lambda f: [max(-6.0, min(6.0, (f[n] - mu[j]) / sd[j])) for j, n in enumerate(FEATURE_NAMES)]
    Ztr = [z(r[2]) for r in train_r]; Zte = [z(r[2]) for r in test_r]
    models = {}
    for m, cond in TARGETS.items():
        w, b = _fit(Ztr, [1 if cond(r[3]) else 0 for r in train_r])
        models[m] = {"w": w, "b": b}
    sig = lambda m, x: 1 / (1 + math.exp(-max(-30, min(30, models[m]["b"] + sum(a * c for a, c in zip(models[m]["w"], x))))))
    fmt = lambda ms: datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")
    out = [f"# {datetime.datetime.now():%Y-%m-%d %H:%M:%S} 가격 예고 학습·검증 · 종목 {len(P['data'])} · "
           f"학습 {len(train_r)} ({fmt(train_r[0][0])}~{fmt(train_r[-1][0])}) · 검증 {len(test_r)} ({fmt(test_r[0][0])}~{fmt(test_r[-1][0])})"]
    labels = []
    in_list = _list_members(rows)
    ctx_of = lambda r: CONTEXT_LIST if (r[0], r[1]) in in_list else CONTEXT_ALL
    for (key, m, (lo, hi), q, side), ctx in [(c, x) for x in (CONTEXT_LIST, CONTEXT_ALL) for c in CANDIDATES]:
        tr = sorted(sig(m, x) for x, r in zip(Ztr, train_r) if ctx_of(r) == ctx and lo <= r[2]["r24"] < hi)
        thr = tr[int(len(tr) * (1 - q))] if tr else 1.0   # 학습 표본 없음 → 해당 없음 (점수 < 1)
        te = [(sig(m, x), r) for x, r in zip(Zte, test_r) if ctx_of(r) == ctx and lo <= r[2]["r24"] < hi]
        hit = TARGETS[m]
        base = sum(hit(r[3]) for _, r in te) / len(te) * 100 if te else 0.0
        last, ev = {}, []
        for p, r in sorted(((p, r) for p, r in te if p >= thr), key=lambda x: x[1][0]):
            if r[0] - last.get(r[1], -10**15) >= HORIZON_BARS * STEP_MS:
                last[r[1]] = r[0]; ev.append(r)
        sg = {"S": -1, "L": 1, "A": 1}[side]
        n = len(ev)
        stats = {"events": n, "base_hit_pct": round(base, 2)}
        adopted = False
        if n:
            hr = sum(hit(r[3]) for r in ev) / n * 100
            dr = [sg * r[3] for r in ev]
            days = {}
            for r, v in zip(ev, dr):      # 방향 표시 = 방향 수익, 큰 변동 = 적중 − 기준 (forecast_evaluate.py와 같은 정의)
                days.setdefault(r[0] // 86_400_000, []).append(
                    (100.0 if hit(r[3]) else 0.0) - base if side == "A" else v)
            dm = [st.mean(v) for v in days.values()]
            tval = st.mean(dm) / (st.stdev(dm) / len(dm) ** 0.5) if len(dm) > 2 and st.stdev(dm) > 0 else 0.0
            mid = test_r[0][0] + (test_r[-1][0] - test_r[0][0]) // 2
            h1 = [v for r, v in zip(ev, dr) if r[0] < mid]; h2 = [v for r, v in zip(ev, dr) if r[0] >= mid]
            stats.update({
                "hit_pct": round(hr, 2), "lift": round(hr / base, 2) if base else 0.0,
                "dir_mean_pct": round(st.mean(dr), 3), "dir_median_pct": round(st.median(dr), 3),
                "dir_profit_ratio_pct": round(sum(v > 0 for v in dr) / n * 100, 1),
                "adverse3_4h_pct": round(sum(_adverse(r[5], r[4], sg if side != "A" else 1) for r in ev) / n * 100, 1),
                "days": len(days), "day_t": round(tval, 2), "symbols": len({r[1] for r in ev}),
                "half1_dir_mean_pct": round(st.mean(h1), 3) if h1 else None,
                "half2_dir_mean_pct": round(st.mean(h2), 3) if h2 else None,
            })
            adopted = n >= 30 and base > 0 and hr / base >= 1.5 and (
                side == "A" or (stats["dir_profit_ratio_pct"] >= 55.0 and stats["dir_median_pct"] > 0
                                and stats["dir_mean_pct"] > 0))
        labels.append({"key": key, "context": ctx, "model": m, "r24_range": [lo, hi], "quantile": q, "threshold": thr,
                       "direction": side, "adopted": adopted, "live_status": "검증 중" if adopted else "미채택",
                       "test": stats})
        out.append(f"[{ctx}·{key}] {'채택' if adopted else '미채택'} · {LABEL_TEXT[key]} · 경계 {thr:.4f} · {json.dumps(stats, ensure_ascii=False)}")
    params = {"version": 1, "trained_at": datetime.datetime.now().isoformat(timespec="seconds"),
              "train_period": [fmt(train_r[0][0]), fmt(train_r[-1][0])], "test_period": [fmt(test_r[0][0]), fmt(test_r[-1][0])],
              "symbols": len(P["data"]), "features": list(FEATURE_NAMES), "mu": mu, "sd": sd, "models": models, "labels": labels}
    cand = PARAMS_PATH.with_name("forecast_params_candidate.json")
    cand.write_text(json.dumps(params, ensure_ascii=False, indent=1), encoding="utf-8")
    replace = any(l["adopted"] for l in labels) or not PARAMS_PATH.exists()
    if replace:
        PARAMS_PATH.write_text(json.dumps(params, ensure_ascii=False, indent=1), encoding="utf-8")
    out.append(f"판정식 파일: {'교체 ' + str(PARAMS_PATH) if replace else '기존 유지 (채택 표시 없음) · 후보 ' + str(cand)}")
    text = "\n".join(out); print(text)
    (EVIDENCE / f"yona_forecast_train_{datetime.datetime.now():%Y%m%d_%H%M}.log").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    {"collect": collect, "train": train}[sys.argv[1] if len(sys.argv) > 1 else "train"]()
