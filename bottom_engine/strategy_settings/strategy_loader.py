"""
bottom/strategy_settings/strategy_loader.py
Sort by별 롱/숏 전략 설정 로드·저장 (JSON 파일 기반 영속화)
bottom_panel.py의 _confirm_strategy() 에서 _applied_params 를 받아 저장
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from bottom_engine.models import StrategyParams

_STRATEGY_PATH = Path(__file__).parent / "_strategy.json"


class StrategyLoader:
    """Sort by 모드별 전략 설정 로드·저장."""

    @staticmethod
    def save(params: StrategyParams) -> None:
        """현재 전략 설정을 Sort by 모드별로 JSON에 저장."""
        data = _load_raw()
        data[params.sort_mode] = {
            "funds_pct":      params.funds_pct,
            "leverage":       params.leverage,
            "stop_loss":      params.stop_loss,
            "trail_stop":     params.trail_stop,
            "prohibition":    params.prohibition.to_dict(),
            "use_macro":      params.use_macro,
            "consensus_mode": params.consensus_mode,  # [B-4]
        }
        _save_raw(data)

    @staticmethod
    def load(sort_mode: str) -> StrategyParams | None:
        """Sort by 모드에 저장된 전략 설정 로드. 없으면 None."""
        data = _load_raw()
        raw  = data.get(sort_mode)
        if not raw:
            return None
        p = StrategyParams(sort_mode=sort_mode)
        p.funds_pct  = int(raw.get("funds_pct", 100))
        p.leverage   = int(raw.get("leverage", 10))
        p.stop_loss  = float(raw.get("stop_loss", 2.5))
        p.trail_stop = float(raw.get("trail_stop", 1.5))
        from bottom_engine.models import ProhibitionFlags
        p.prohibition = ProhibitionFlags.from_dict(raw.get("prohibition", {}))
        p.use_macro      = bool(raw.get("use_macro", True))
        p.consensus_mode = str(raw.get("consensus_mode", "4/4"))  # [B-4]
        return p

    @staticmethod
    def load_or_default(sort_mode: str) -> StrategyParams:
        """저장된 설정 로드, 없으면 기본값."""
        return StrategyLoader.load(sort_mode) or StrategyParams(sort_mode=sort_mode)

    @staticmethod
    def save_from_applied(applied_params: dict, sort_mode: str) -> StrategyParams:
        """bottom_panel.py의 _applied_params dict → 저장 후 StrategyParams 반환."""
        p = StrategyParams.from_applied_params(applied_params, sort_mode)
        StrategyLoader.save(p)
        return p

    @staticmethod
    def all_modes() -> list[str]:
        """저장된 모드 목록."""
        return list(_load_raw().keys())


def _load_raw() -> dict:
    try:
        return json.loads(_STRATEGY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_raw(data: dict) -> None:
    try:
        _STRATEGY_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        raise OSError(f"전략 저장 실패 — {_STRATEGY_PATH.name}: {e}") from e

