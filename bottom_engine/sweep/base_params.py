"""
bottom_engine/sweep/base_params.py
스윕 공통 기준 — 전 스윕이 동일 파라미터·동일 심볼을 쓰도록 단일 선언.

기준 파라미터는 _strategy.json "24h Ticker" 를 직접 읽는다.
파라미터 변경 시 _strategy.json 만 수정하면 전 스윕에 자동 반영된다.
base_params.py 는 수정하지 않는다.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from bottom_engine.models import StrategyParams
from bottom_engine.strategy_settings.strategy_loader import StrategyLoader

PERIOD    = "90일"
SORT_MODE = "24h Ticker"

_ROOT         = Path(__file__).resolve().parents[2]
_SYMBOLS_PATH = _ROOT / "selected_symbols.json"


def load_symbols() -> list[str]:
    """selected_symbols.json 의 심볼 목록 반환."""
    with open(_SYMBOLS_PATH, encoding="utf-8") as f:
        return list(json.load(f)["symbols"])


def make_base_params() -> StrategyParams:
    """스윕 기준 파라미터 — _strategy.json '24h Ticker' 를 직접 읽어 자동 동기화.

    모드가 없거나 파일을 읽지 못하면 즉시 RuntimeError (기본값으로 조용히 진행 금지).
    """
    p = StrategyLoader.load(SORT_MODE)
    if p is None:
        raise RuntimeError(
            f"_strategy.json 에서 '{SORT_MODE}' 설정을 읽지 못했습니다 — 스윕 중단")
    return p


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=_ROOT, capture_output=True,
            text=True, timeout=10, check=True).stdout.strip()
    except Exception:
        return ""


def run_metadata(params: StrategyParams, period: str, symbols: list[str]) -> dict:
    """결과 파일·콘솔 기록용 측정 조건 — 커밋 해시와 전체 파라미터."""
    return {
        "commit":        _git("rev-parse", "--short", "HEAD") or "unknown",
        "dirty":         bool(_git("status", "--porcelain")),
        "run_at":        datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "period":        period,
        "symbols_count": len(symbols),
        "params":        asdict(params),
    }


def print_metadata(meta: dict) -> None:
    """측정 조건 헤더 출력 — dirty 상태면 경고."""
    p = meta["params"]
    print(f"[측정 조건] commit={meta['commit']}"
          f"{'  ⚠ 커밋 안 된 변경 있음' if meta['dirty'] else ''}")
    print(f"[측정 조건] {meta['symbols_count']}심볼 × {meta['period']}  "
          f"lev={p['leverage']}  SL={p['stop_loss']}%  trail={p['trail_stop']}%  "
          f"vol_mult={p['m4_rsi_vol_mult']}  use_macro={p['use_macro']}")
