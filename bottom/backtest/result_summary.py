"""
bottom/backtest/result_summary.py
백테스팅 결과 분석 — 승률·수익률·MDD 계산
"""
from __future__ import annotations

from bottom.models import BacktestResult, BacktestTrade


class ResultSummary:
    """백테스팅 거래 목록 → 성과 지표 계산."""

    @staticmethod
    def build(symbol: str, sort_mode: str, period_days: int,
              trades: list[BacktestTrade]) -> BacktestResult:
        result = BacktestResult(
            symbol=symbol, sort_mode=sort_mode,
            period_days=period_days, trades=trades,
        )
        if not trades:
            return result

        wins   = [t for t in trades if t.pnl_pct > 0]
        losses = [t for t in trades if t.pnl_pct <= 0]

        result.total_trades = len(trades)
        result.win_trades   = len(wins)
        result.loss_trades  = len(losses)
        result.win_rate     = round(len(wins) / len(trades) * 100, 2)
        result.total_return = round(sum(t.pnl_pct for t in trades), 3)
        result.max_profit   = round(max(t.pnl_pct for t in trades), 3)
        _equity = 0.0
        _peak   = 0.0
        _mdd    = 0.0
        for _t in trades:
            _equity += _t.pnl_pct
            if _equity > _peak:
                _peak = _equity
            _dd = _peak - _equity
            if _dd > _mdd:
                _mdd = _dd
        result.max_drawdown = round(_mdd, 3)
        result.avg_profit   = round(sum(t.pnl_pct for t in wins)   / max(len(wins),   1), 3)
        result.avg_loss     = round(sum(t.pnl_pct for t in losses) / max(len(losses), 1), 3)

        return result


