"""
bottom_engine/sweep/aggregator.py
스윕·분석 스크립트 공통 집계 모듈 — n / WR / EV(R) / PF 단일 산출 소스.

정의 (models.py:156 계약 준수 — qty_ratio 를 pnl_pct 에 재적용 금지):
  n    = Σ qty_ratio                        — 진입 건수 (부분청산 합이 1.0)
  WR   = Σ_{pnl_pct>0} qty_ratio / n × 100
  EV   = Σ pnl_pct / (one_r_pct × n)        — 진입 1건당 R
  PF   = Σ pnl_pct⁺ / Σ |pnl_pct⁻|
  PF CI= ± 2 × PF / √n                      — 95% 근사 신뢰구간 폭

1R(one_r_pct)은 BacktestResult 가 전달한 값만 사용한다.
L_eff 를 이 모듈에서 재계산하지 않는다 — backtest_runner 가 단일 소스다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SweepBucket:
    """단일 스윕 셀의 집계 누적기."""

    n:           float = 0.0   # Σ qty_ratio
    wins:        float = 0.0   # Σ qty_ratio where pnl_pct > 0
    sum_pnl:     float = 0.0   # Σ pnl_pct
    sum_pos_pnl: float = 0.0   # Σ pnl_pct (pnl_pct > 0)
    sum_neg_pnl: float = 0.0   # Σ |pnl_pct| (pnl_pct <= 0)
    one_r_pct:   float = 0.0   # 1R (%) — 첫 유효 result 에서 고정

    def add(self, result) -> None:
        """BacktestResult 1개를 누적.

        one_r_pct == 0.0 인 result(데이터 부족 조기 반환)는 건너뛴다.
        셀 내 심볼 간 1R 이 다르면 집계가 무의미하므로 ValueError 를 올린다.
        """
        r1 = getattr(result, "one_r_pct", 0.0)
        if r1 <= 0.0:
            return
        if self.one_r_pct == 0.0:
            self.one_r_pct = r1
        elif abs(self.one_r_pct - r1) > 1e-9:
            raise ValueError(
                f"1R 불일치: 누적={self.one_r_pct:.8f} 신규={r1:.8f} "
                f"(symbol={getattr(result, 'symbol', '?')}) "
                f"— 동일 셀 내 파라미터가 달라 집계할 수 없습니다")
        for t in result.trades:
            self.n       += t.qty_ratio
            self.sum_pnl += t.pnl_pct
            if t.pnl_pct > 0:
                self.wins        += t.qty_ratio
                self.sum_pos_pnl += t.pnl_pct
            else:
                self.sum_neg_pnl += abs(t.pnl_pct)

    def summary(self) -> dict:
        """집계 결과 dict 반환. 거래 0건이면 전부 0.0.

        pf == 0.0 은 두 가지 의미를 가진다: 거래 0건, 또는 손실 0건(PF 정의 불가).
        pf_ci 는 n 이 작을 때 신뢰 불가를 드러내기 위해 항상 함께 반환한다.
        """
        if self.n <= 0.0 or self.one_r_pct <= 0.0:
            return {"n": 0.0, "wr": 0.0, "ev_r": 0.0, "pf": 0.0,
                    "pf_ci": 0.0, "one_r_pct": self.one_r_pct}
        pf = (self.sum_pos_pnl / self.sum_neg_pnl) if self.sum_neg_pnl > 0 else 0.0
        return {
            "n":         self.n,
            "wr":        self.wins / self.n * 100.0,
            "ev_r":      self.sum_pnl / (self.one_r_pct * self.n),
            "pf":        pf,
            "pf_ci":     2.0 * pf / (self.n ** 0.5),
            "one_r_pct": self.one_r_pct,
        }


def assert_sl_is_one_r(result, tol: float = 0.01) -> tuple[bool, str]:
    """SL 청산의 평균 R 이 이론값과 일치하는지 검증 — 정의 결함 재발 감시용.

    SL 청산은 정의상 -1R 이며, 왕복 비용만큼 추가 손실이 난다.
        R_SL = -(1 + cost/1R),  cost = 2 × L_eff × (fee+slip) × 100 = 0.1 × L_eff
        cost/1R = 0.1 × L_eff / (sl_used × L_eff) = 0.1 / sl_used
    따라서 이론값 = -(1 + 0.1 / sl_used).
    sl_used 는 one_r_pct / l_eff 로 역산한다(별도 전달 불필요).

    반환: (통과 여부, 메시지)
    """
    l_eff = getattr(result, "l_eff", 0.0)
    r1    = getattr(result, "one_r_pct", 0.0)
    if l_eff <= 0.0 or r1 <= 0.0:
        return True, "1R 미산출 — 검증 건너뜀"
    sl_used = r1 / l_eff
    sl_tr = [t for t in result.trades if t.exit_reason == "SL"]
    if not sl_tr:
        return True, "SL 청산 0건 — 검증 건너뜀"
    actual   = sum(t.pnl_pct for t in sl_tr) / sum(t.qty_ratio for t in sl_tr) / r1
    expected = -(1.0 + 0.1 / sl_used)
    ok = abs(actual - expected) <= tol
    return ok, (f"SL 평균 R: 실측={actual:+.4f} 이론={expected:+.4f} "
                f"차이={actual - expected:+.4f} (허용 ±{tol}) "
                f"{'OK' if ok else '★불일치★'} [n={len(sl_tr)}]")
