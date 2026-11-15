"""
middle/analysis/forecast.py
가격 예고 — 선택 코인의 12시간 내 가격 흐름 사전 표시 (화면 표시 전용, 엔진·백테스트 미사용)

단일 정의: 학습(forecast_train.py)과 앱(data_manager)이 같은 compute_features()·Forecaster를 사용한다.
입력: 연속 5m 마감 봉 289개 이상(체결 매수량 포함) + 5m OI {timestamp ms: OI} (봉 마감 시각 기준 24h).
판정식·경계값·채택 여부: forecast_params.json (forecast_train.py가 학습·검증 후 작성).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from middle.models import OHLCVBar

STEP_MS     = 300_000          # 5m
BARS_NEEDED = 289              # 24h(288봉) + 기준 봉
HORIZON_BARS = 144             # 결과 판정 12h (학습·채점 공용)
PARAMS_PATH = Path(__file__).with_name("forecast_params.json")
LOG_DIR     = Path(__file__).resolve().parents[2] / "data"   # 실사용 검증 기록 (git 제외)


def log_path(version: str) -> Path:
    """판정식 버전(forecast_params.json trained_at)별 기록 파일 — 버전이 섞여 채점되지 않도록 (앱 기록·채점 공용)."""
    stamp = "".join(ch for ch in version if ch.isdigit() or ch == "T") or "unknown"
    return LOG_DIR / f"forecast_log_{stamp}.csv"

FEATURE_NAMES = (
    "r1h", "r4h", "abs_r4h", "r24", "r24_sq", "dd_high", "high_age_h", "dd_if_pumped",
    "oi1h", "oi4h", "oi24h", "oi4h_if_flat", "taker1h", "taker4h", "vol4h_vs_24h",
)

# 표시 후보 — 실제 표시 여부는 forecast_params.json labels[].adopted (학습 검증 통과) · live_status
LABEL_TEXT = {
    "peak_drop": "▼ 급등 고점 이탈 — 12시간 내 하락 전환 가능성 높음",
    "down":      "▼ 하락 우세 — 12시간 내 하락 가능성 평소보다 높음",
    "early_up":  "▲ 상승 초입 — 12시간 내 상승 가능성 평소보다 높음",
    "big_move":  "⚡ 큰 변동 임박 — 12시간 내 급등·급락 가능성 높음 (방향 미확정)",
}
NO_SIGNAL_TEXT = "─ 특이 신호 없음 — 평소 수준"
NONE_ADOPTED_TEXT = "─ 표시할 예고 없음 — 검증 기준을 통과한 판정식 없음"
INSUFFICIENT_TEXT = "─ 판단 보류 — 5분 봉·OI 24시간 연속 기록 부족 (휴장·신규 상장 등)"
OUT_OF_RANGE_TEXT = "─ 판정 범위 밖 — 이 24h 변동률 구간에는 검증된 판정식 없음"
LABEL_ORDER = ("peak_drop", "down", "early_up", "big_move")   # 여러 개 해당 시 우선순위
# 표시 경계 적용 조건 — 같은 점수라도 비교 대상(평소)이 다르다:
#   list = 1열 24h Ticker 목록(24h 변동률 상위) 종목 · all = 그 밖 (학습: 각 시점 24h 변동률 상위 1/6 표본 vs 전체)
CONTEXT_LIST, CONTEXT_ALL = "list", "all"


def _taker_log_ratio(bars: list[OHLCVBar]) -> float:
    v  = sum(b.volume for b in bars)
    tb = sum(b.taker_buy_volume for b in bars)
    return math.log((tb + 1e-9) / (v - tb + 1e-9)) if v > 0 else 0.0


def compute_features(bars: list[OHLCVBar], oi: dict[int, float]) -> dict[str, float] | None:
    """마지막 봉(bars[-1]) 마감 시점 지표. 봉이 부족·불연속이거나 OI가 없으면 None."""
    if len(bars) < BARS_NEEDED:
        return None
    w = bars[-BARS_NEEDED:]
    for a, b in zip(w, w[1:]):
        if b.open_time - a.open_time != STEP_MS:
            return None
    t_close = w[-1].close_time + 1                 # 봉 마감 시각 = OI timestamp
    o0, o1 = oi.get(t_close), oi.get(t_close - 12 * STEP_MS)
    o4, o24 = oi.get(t_close - 48 * STEP_MS), oi.get(t_close - 288 * STEP_MS)
    if not (o0 and o1 and o4 and o24):
        return None
    c = w[-1].close
    r1  = (c / w[-13].close - 1) * 100
    r4  = (c / w[-49].close - 1) * 100
    r24 = (c / w[-288].open - 1) * 100
    highs = [b.high for b in w[-288:]]
    hi = max(highs)
    dd = (c / hi - 1) * 100
    age_h = (len(highs) - 1 - max(k for k, x in enumerate(highs) if x == hi)) / 12
    v4  = sum(b.volume for b in w[-48:])
    v24 = sum(b.volume for b in w[-288:-48]) / 5
    oi4 = (o0 / o4 - 1) * 100
    return {
        "r1h": r1, "r4h": r4, "abs_r4h": abs(r4), "r24": r24, "r24_sq": r24 * r24 / 100,
        "dd_high": dd, "high_age_h": age_h, "dd_if_pumped": dd if r24 >= 15 else 0.0,
        "oi1h": (o0 / o1 - 1) * 100, "oi4h": oi4, "oi24h": (o0 / o24 - 1) * 100,
        "oi4h_if_flat": oi4 if abs(r4) < 2 else 0.0,
        "taker1h": _taker_log_ratio(w[-12:]), "taker4h": _taker_log_ratio(w[-48:]),
        "vol4h_vs_24h": math.log(v4 / v24) if v24 > 0 and v4 > 0 else 0.0,
    }


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, x))))


class Forecaster:
    """forecast_params.json 판정식으로 점수·표시 결정. 파일이 없거나 형식 오류면 비활성(표시 없음)."""

    def __init__(self, params: dict | None) -> None:
        self.params = params or {}
        self.ok = bool(params) and list(params.get("features", [])) == list(FEATURE_NAMES)

    @property
    def version(self) -> str:
        """판정식 버전 = 학습 시각 (기록 파일 이름에 사용)."""
        return str(self.params.get("trained_at", ""))

    @classmethod
    def load(cls, path: Path = PARAMS_PATH) -> "Forecaster":
        try:
            return cls(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return cls(None)

    def scores(self, feats: dict[str, float]) -> dict[str, float]:
        p = self.params
        z = [max(-6.0, min(6.0, (feats[n] - p["mu"][j]) / p["sd"][j])) for j, n in enumerate(FEATURE_NAMES)]
        return {m: _sigmoid(v["b"] + sum(wj * zj for wj, zj in zip(v["w"], z))) for m, v in p["models"].items()}

    def judge(self, feats: dict[str, float], in_list: bool = False) -> dict:
        """in_list: 1열 24h Ticker 목록(24h 변동률 상위) 종목 — 표시 경계는 학습 때 같은 조건 표본으로 정한 값을 쓴다.
        {"labels": 해당 후보 키(우선순위순), "shown": 그중 표시 가능(채택·실사용 탈락 아님), "scores", "r24", "context"}."""
        ctx = CONTEXT_LIST if in_list else CONTEXT_ALL
        if not self.ok:
            return {"labels": [], "shown": [], "scores": {}, "r24": feats.get("r24", 0.0), "context": ctx}
        sc = self.scores(feats)
        hit = [lab for lab in self._labels(ctx)
               if lab["r24_range"][0] <= feats["r24"] < lab["r24_range"][1] and sc[lab["model"]] >= lab["threshold"]]
        keys = [k for k in LABEL_ORDER if any(l["key"] == k for l in hit)]
        return {"labels": keys, "shown": [k for k in keys if self.label_shown(k, ctx)],
                "scores": sc, "r24": feats["r24"], "context": ctx}

    def _labels(self, ctx: str) -> list[dict]:
        return [l for l in self.params.get("labels", []) if l.get("context", CONTEXT_ALL) == ctx]

    def label_info(self, key: str, ctx: str = CONTEXT_ALL) -> dict | None:
        return next((l for l in self._labels(ctx) if l["key"] == key), None)

    def label_shown(self, key: str, ctx: str = CONTEXT_ALL) -> bool:
        """화면 표시 = 판정식 사용 가능 + 학습 검증 채택 + 실사용 검증 탈락 아님."""
        if not self.ok:
            return False
        lab = self.label_info(key, ctx)
        return bool(lab and lab.get("adopted") and lab.get("live_status") != "탈락")

    def display(self, result: dict) -> tuple[str, str]:
        """(문구, 상태 부연). 상승·하락 방향이 동시에 해당하면 방향 문구 대신 큰 변동(그 자체로 해당할 때만) 또는 신호 없음."""
        ctx = result.get("context", CONTEXT_ALL)
        if not any(self.label_shown(k, ctx) for k in LABEL_ORDER):
            return NONE_ADOPTED_TEXT, ""
        r24 = result.get("r24")
        if r24 is not None and not any(self.label_shown(l["key"], ctx) and l["r24_range"][0] <= r24 < l["r24_range"][1]
                                       for l in self._labels(ctx)):
            return OUT_OF_RANGE_TEXT, ""     # 이 구간을 맡는 표시 판정식이 없음 — '평소 수준'이라 말하지 않음
        shown = result.get("shown", [])
        dirs = {self.label_info(k, ctx)["direction"] for k in shown if k != "big_move"}
        if "S" in dirs and "L" in dirs:
            shown = ["big_move"] if "big_move" in shown else []
        if not shown:
            return NO_SIGNAL_TEXT, ""
        key = shown[0]
        live = self.label_info(key, ctx).get("live_status", "검증 중")
        return LABEL_TEXT[key], ("실사용 검증 중" if live == "검증 중" else "실사용 검증 통과")
