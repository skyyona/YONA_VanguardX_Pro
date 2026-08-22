"""
bottom/backtest/param_deriver.py
백테스트 결과에서 Wilson 하한 → Fractional Kelly → R 기반 최적 사이징 파라미터 도출.

사용 예:
    from bottom_engine.backtest.param_deriver import derive_params
    result = derive_params(trades, portfolio_usdt=1000.0)
    print(result["note"])
"""
from __future__ import annotations

import math

# Fractional Kelly 배수 — 전체 Kelly의 1/4 적용 (과도한 레버리지 억제)
_KELLY_FRACTION = 0.25
# Wilson 구간 신뢰수준 95% 대응 z값
_Z_95 = 1.96
# 단일 거래 최대 위험 상한 (%)
_MAX_R_PCT = 8.0
# Wilson 신뢰 구간 유효 최소 표본 수 — n<100 이면 구간이 너무 넓어 실용성 없음
_MIN_SAMPLE = 100


def _wilson_lower(wins: int, n: int, z: float = _Z_95) -> float:
    """Wilson 하한 신뢰구간.

    소규모 샘플 편의 보정 — 단순 승률보다 보수적인 추정치를 반환한다.
    """
    if n <= 0:
        return 0.0
    p_hat  = wins / n
    denom  = 1.0 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n))) / denom
    return max(0.0, center - margin)


def _kelly(win_prob: float, avg_win_r: float, avg_loss_r: float,
           fraction: float = _KELLY_FRACTION) -> float:
    """Fractional Kelly 공식.

    f* = fraction × (p × b − (1−p)) / b
    b  = avg_win_r / avg_loss_r
    """
    if avg_loss_r <= 0 or avg_win_r <= 0:
        return 0.0
    b      = avg_win_r / avg_loss_r
    f_full = (win_prob * b - (1 - win_prob)) / b
    return max(0.0, f_full * fraction)


def derive_params(trades: list, portfolio_usdt: float = 1000.0) -> dict:
    """백테스트 거래 목록에서 최적 사이징 파라미터를 도출한다.

    Parameters
    ----------
    trades : list[BacktestTrade]
        pnl_pct 필드를 사용한다.
    portfolio_usdt : float
        기준 포트폴리오 크기 (USDT).

    Returns
    -------
    dict with keys:
        win_rate_raw          단순 승률
        win_rate_wilson       Wilson 하한 승률 (보수적 추정)
        avg_win_r             평균 수익 R
        avg_loss_r            평균 손실 R (양수값)
        kelly_fraction        Fractional Kelly 비율 (0~1)
        r_per_trade_pct       추천 단일 거래 위험 비율 (%)
        max_r_per_trade_usdt  포트폴리오 기준 최대 위험 USDT
        note                  요약 문자열
    """
    if not trades:
        return {"note": "거래 없음 — 데이터 부족"}

    win_trades  = [t for t in trades if t.pnl_pct > 0]
    loss_trades = [t for t in trades if t.pnl_pct <= 0]
    wins        = [t.pnl_pct for t in win_trades]
    losses      = [t.pnl_pct for t in loss_trades]
    n           = sum(t.qty_ratio for t in trades)
    n_win       = sum(t.qty_ratio for t in win_trades)

    if n < _MIN_SAMPLE:
        return {"note": f"샘플 {round(n)}건 — Wilson 신뢰 구간 최소 {_MIN_SAMPLE}건 필요"}

    win_rate_raw    = n_win / n
    win_rate_wilson = _wilson_lower(n_win, n)

    avg_win_r  = (sum(wins)    / max(sum(t.qty_ratio for t in win_trades),  1e-9)
                  if win_trades else 0.0)
    avg_loss_r = (-sum(losses) / max(sum(t.qty_ratio for t in loss_trades), 1e-9)
                  if loss_trades else 0.0)

    kelly  = _kelly(win_rate_wilson, avg_win_r, avg_loss_r)
    r_pct  = min(kelly * 100.0, _MAX_R_PCT)

    return {
        "win_rate_raw":         round(win_rate_raw,    4),
        "win_rate_wilson":      round(win_rate_wilson, 4),
        "avg_win_r":            round(avg_win_r,  2),
        "avg_loss_r":           round(avg_loss_r, 2),
        "kelly_fraction":       round(kelly,  4),
        "r_per_trade_pct":      round(r_pct,  2),
        "max_r_per_trade_usdt": round(portfolio_usdt * r_pct / 100.0, 2),
        "note": (
            f"샘플 {round(n)}건 | Wilson승률 {win_rate_wilson:.1%} "
            f"| Kelly×{_KELLY_FRACTION}={kelly:.1%} → R{r_pct:.2f}%"
        ),
    }
