"""
bottom_engine/strategy/m4_exit.py
BT·LIVE 공통 청산 판정 — ExitDecision 데이터클래스 + M4Exit 클래스.

BT 호출:
    dec = M4Exit.evaluate(side="LONG", ..., hi=bar.high, lo=bar.low, close=bar.close,
                          k_prev=_k5m_prev_bar, k_cur=_k5m_cur,
                          profit_trigger=profit_trigger_long)

LIVE 호출 (long_position.update / short_position.update):
    dec = M4Exit.evaluate(side="LONG", ..., hi=mark, lo=mark, close=mark,
                          k_prev=0.0, k_cur=0.0,   # KD 관리는 engine 담당
                          profit_trigger=0.0)       # trail 즉시 활성

잔존 불일치 항목 (docs/exit_parity.md 참조):
    ⑦ trail_ref 갱신 기준가: BT=bar.close, LIVE=mark (미세 차이 — 동일 코드)
    ⑧ profit_trigger 도달 판정: BT=bar.close, LIVE=mark (미세 차이)
    ⑨ TRAIL 집행: BT client-side vs Binance 서버측 (구조적 차이)
    ⑩ -16% 백스탑: LIVE에만 있음 (정상 차이)
"""
from __future__ import annotations

from dataclasses import dataclass

from bottom_engine.constants import _PROFIT_TRIGGER_PCT


@dataclass
class ExitDecision:
    """M4Exit.evaluate() 반환값 — 청산 판정 결과.

    reason == ""   → 청산 없음 (new_phase / new_sl / new_trail_ref 만 사용)
    reason == "PARTIAL" → 50% 부분 청산 후 Phase3 진입 (position 유지)
    그 외           → 전량(또는 잔량) 청산
    """
    reason: str = ""             # ""|"SL"|"BEP-SL"|"PARTIAL"|"TRAIL"|"KD-EXIT"
    exit_price: float = 0.0      # 청산 체결가 (0.0 = 청산 없음)
    qty_ratio: float = 1.0       # 청산 비율 (0.5 = 부분, 1.0 = 전량)
    new_phase: int = 1           # 결과 Phase (1/2/3)
    new_sl: float = 0.0          # 갱신된 SL 가격 (0.0 = 변경 없음)
    new_trail_ref: float = 0.0   # 갱신된 trail 기준가 (long=trailing_high, short=trailing_low)
    new_profit_trigger: float = 0.0  # Phase2→3 전환 시 설정 (0.0 = 변경 없음)


class M4Exit:
    """BT·LIVE 공통 청산 판정 — CURRENT exit_variant 전용.

    Parameters
    ----------
    side           : "LONG" or "SHORT"
    phase          : 현재 Phase (1/2/3)
    entry_price    : 진입가
    sl_pct         : SL % (예: 3.7)
    trail_pct      : Trailing Stop % (예: 1.1)
    trail_ref      : trail 기준가 (LONG=trailing_high, SHORT=trailing_low); Phase3 이전엔 0.0
    profit_trigger : Phase3 trail 활성 기준가
                     0.0 → 즉시 활성 (LIVE 기본값; _sl_loop이 profit_trigger 관리)
    hi             : 최고가  (BT=bar.high,  LIVE=mark)
    lo             : 최저가  (BT=bar.low,   LIVE=mark)
    close          : 종가    (BT=bar.close, LIVE=mark)
    k_prev         : 직전 5m StochRSI K값
                     LIVE에서 KD 익절을 _sl_loop이 직접 처리할 경우 0.0 전달
    k_cur          : 현재 5m StochRSI K값 (동상)
    """

    @staticmethod
    def evaluate(
        *,
        side: str,
        phase: int,
        entry_price: float,
        sl_pct: float,
        trail_pct: float,
        trail_ref: float,
        profit_trigger: float,
        hi: float,
        lo: float,
        close: float,
        k_prev: float,
        k_cur: float,
    ) -> ExitDecision:
        if side == "LONG":
            return _eval_long(
                phase, entry_price, sl_pct, trail_pct,
                trail_ref, profit_trigger, hi, lo, close, k_prev, k_cur,
            )
        return _eval_short(
            phase, entry_price, sl_pct, trail_pct,
            trail_ref, profit_trigger, hi, lo, close, k_prev, k_cur,
        )


# ── Long CURRENT 청산 판정 ────────────────────────────────────────────

def _eval_long(
    phase: int, entry: float, sl_pct: float, trail_pct: float,
    trail_ref: float, profit_trigger: float,
    hi: float, lo: float, close: float,
    k_prev: float, k_cur: float,
) -> ExitDecision:
    R = entry * sl_pct / 100.0

    if phase == 1:
        sl_p1 = entry * (1.0 - sl_pct / 100.0)
        # [P1] SL 도달 — intrabar bar.low 기준 (LIVE: mark)
        if lo <= sl_p1:
            return ExitDecision(reason="SL", exit_price=sl_p1, qty_ratio=1.0, new_phase=1)
        # [A-4] Phase1→2: bar.high ≥ entry+R
        new_phase = 2 if (R > 0 and hi >= entry + R) else 1
        new_sl    = entry if new_phase == 2 else sl_p1
        # [A-5] K80 하향 돌파 익절 — Phase 무관 체크
        if k_prev >= 80.0 and k_cur < 80.0:
            return ExitDecision(reason="KD-EXIT", exit_price=close, qty_ratio=1.0, new_phase=1)
        return ExitDecision(new_phase=new_phase, new_sl=new_sl)

    if phase == 2:
        # [P1] BEP-SL — bar.low ≤ entry
        if lo <= entry:
            return ExitDecision(reason="BEP-SL", exit_price=entry, qty_ratio=1.0, new_phase=1)
        # [A-5] K80 하향 돌파 익절
        if k_prev >= 80.0 and k_cur < 80.0:
            return ExitDecision(reason="KD-EXIT", exit_price=close, qty_ratio=1.0, new_phase=1)
        # [A-4][P5] Phase2→3: bar.high ≥ entry+1.5R → 50% PARTIAL 익절
        if R > 0 and hi >= entry + R * 1.5:
            partial_price = entry + R * 1.5
            new_trail     = hi
            new_trigger   = hi * (1.0 + _PROFIT_TRIGGER_PCT / 100.0)
            return ExitDecision(
                reason="PARTIAL", exit_price=partial_price, qty_ratio=0.5,
                new_phase=3, new_trail_ref=new_trail, new_profit_trigger=new_trigger,
                new_sl=entry,
            )
        return ExitDecision(new_phase=2, new_sl=entry)

    # phase == 3
    # trail_active: profit_trigger ≤ 0 (즉시 활성) 또는 현재가 ≥ profit_trigger
    trail_active = (profit_trigger <= 0.0 or close >= profit_trigger)
    if trail_active:
        # trail_ref 갱신 (BT=close, LIVE=mark — 동일 코드, 미세 차이만 존재)
        new_trail = max(trail_ref, close) if trail_ref > 0.0 else close
        trail_sl  = new_trail * (1.0 - trail_pct / 100.0)
        # [P1] TRAIL 도달 — bar.low ≤ trail_sl
        if lo <= trail_sl:
            return ExitDecision(reason="TRAIL", exit_price=trail_sl, qty_ratio=0.5, new_phase=1)
        # [A-5][P8][P10] TRAIL 없을 때만 K80 체크
        if k_prev >= 80.0 and k_cur < 80.0:
            return ExitDecision(reason="KD-EXIT", exit_price=close, qty_ratio=0.5, new_phase=1)
        return ExitDecision(new_phase=3, new_trail_ref=new_trail, new_sl=trail_sl)
    else:
        # [P10] profit_trigger 미달 — BEP SL 유지
        if lo <= entry:
            return ExitDecision(reason="BEP-SL", exit_price=entry, qty_ratio=0.5, new_phase=1)
        if k_prev >= 80.0 and k_cur < 80.0:
            return ExitDecision(reason="KD-EXIT", exit_price=close, qty_ratio=0.5, new_phase=1)
        return ExitDecision(new_phase=3, new_sl=entry)


# ── Short CURRENT 청산 판정 ───────────────────────────────────────────

def _eval_short(
    phase: int, entry: float, sl_pct: float, trail_pct: float,
    trail_ref: float, profit_trigger: float,
    hi: float, lo: float, close: float,
    k_prev: float, k_cur: float,
) -> ExitDecision:
    R = entry * sl_pct / 100.0

    if phase == 1:
        sl_p1 = entry * (1.0 + sl_pct / 100.0)
        # [P1] SL 도달 — intrabar bar.high 기준 (LIVE: mark)
        if hi >= sl_p1:
            return ExitDecision(reason="SL", exit_price=sl_p1, qty_ratio=1.0, new_phase=1)
        # [A-4] Phase1→2: bar.low ≤ entry−R
        new_phase = 2 if (R > 0 and lo <= entry - R) else 1
        new_sl    = entry if new_phase == 2 else sl_p1
        # [A-5] K20 상향 돌파 익절 — Phase 무관 체크
        if k_prev <= 20.0 and k_cur > 20.0:
            return ExitDecision(reason="KD-EXIT", exit_price=close, qty_ratio=1.0, new_phase=1)
        return ExitDecision(new_phase=new_phase, new_sl=new_sl)

    if phase == 2:
        # [P1] BEP-SL — bar.high ≥ entry
        if hi >= entry:
            return ExitDecision(reason="BEP-SL", exit_price=entry, qty_ratio=1.0, new_phase=1)
        # [A-5] K20 상향 돌파 익절
        if k_prev <= 20.0 and k_cur > 20.0:
            return ExitDecision(reason="KD-EXIT", exit_price=close, qty_ratio=1.0, new_phase=1)
        # [A-4][P5] Phase2→3: bar.low ≤ entry−1.5R → 50% PARTIAL 익절
        if R > 0 and lo <= entry - R * 1.5:
            partial_price = entry - R * 1.5
            new_trail     = lo
            new_trigger   = lo * (1.0 - _PROFIT_TRIGGER_PCT / 100.0)
            return ExitDecision(
                reason="PARTIAL", exit_price=partial_price, qty_ratio=0.5,
                new_phase=3, new_trail_ref=new_trail, new_profit_trigger=new_trigger,
                new_sl=entry,
            )
        return ExitDecision(new_phase=2, new_sl=entry)

    # phase == 3
    # SHORT trail_active: profit_trigger ≤ 0 또는 현재가 ≤ profit_trigger
    trail_active = (profit_trigger <= 0.0 or close <= profit_trigger)
    if trail_active:
        # trail_ref = trailing_low (SHORT: 최저가 추적)
        new_trail = min(trail_ref, close) if trail_ref > 0.0 else close
        trail_sl  = new_trail * (1.0 + trail_pct / 100.0)
        # [P1] TRAIL 도달 — bar.high ≥ trail_sl
        if hi >= trail_sl:
            return ExitDecision(reason="TRAIL", exit_price=trail_sl, qty_ratio=0.5, new_phase=1)
        # [A-5][P8][P10] TRAIL 없을 때만 K20 체크
        if k_prev <= 20.0 and k_cur > 20.0:
            return ExitDecision(reason="KD-EXIT", exit_price=close, qty_ratio=0.5, new_phase=1)
        return ExitDecision(new_phase=3, new_trail_ref=new_trail, new_sl=trail_sl)
    else:
        # [P10] profit_trigger 미달 — BEP SL 유지
        if hi >= entry:
            return ExitDecision(reason="BEP-SL", exit_price=entry, qty_ratio=0.5, new_phase=1)
        if k_prev <= 20.0 and k_cur > 20.0:
            return ExitDecision(reason="KD-EXIT", exit_price=close, qty_ratio=0.5, new_phase=1)
        return ExitDecision(new_phase=3, new_sl=entry)
