"""
bottom/engine_core/trading_engine.py
거래 엔진 — SL 루프(1초) + 신호 루프(1m봉 마감 동기화) 분리형

포지션 없음: SL 루프 API 호출 없음 / 신호 루프 1m봉 마감마다 4TF 신호 평가
포지션 보유: SL 루프 1초마다 mark price → SL/Trailing 체크·청산
"""
from __future__ import annotations

import threading
import time
import winsound
from dataclasses import dataclass

from bottom_engine.api.binance_client import BottomBinanceClient
from bottom_engine.models import (
    OrderResult, Position, PositionSide, PositionState, StrategyParams
)
from bottom_engine.engine_core.risk_manager import RiskManager, MAX_PORTFOLIO_LOSS_PCT, MAX_DAILY_LOSS_PCT
from bottom_engine.engine_core.daily_loss_tracker import DailyLossTracker
from bottom_engine.engine_core.sl_calculator import SLCalculator
from bottom_engine.long_engine.long_condition import LongCondition
from bottom_engine.long_engine.long_order import LongOrder
from bottom_engine.long_engine.long_position import LongPosition
from bottom_engine.short_engine.short_condition import ShortCondition
from bottom_engine.short_engine.short_order import ShortOrder
from bottom_engine.short_engine.short_position import ShortPosition

SL_INTERVAL_SEC  = 1   # SL/Trailing 체크 주기 — 포지션 보유 중
_DATA_SETTLE_SEC = 2   # 봉 마감 후 API 갱신 완료 대기 (초) — 7TF 병렬화 후 실측 1초 내외
_BALANCE_TTL_SEC    = 30  # 잔고 캐시 유효 시간 (초)
_MAX_CONSECUTIVE_LOSSES = 3    # N연패 시 쿨다운 진입
_LOSS_COOLDOWN_SEC      = 300  # 쿨다운 지속 시간 (초) — 5분
_POS_SYNC_INTERVAL_SEC  = 10   # Binance 실제 포지션 동기화 주기 (초) — 외부 강제 청산 감지


@dataclass
class EngineState:
    running:      bool  = False
    symbol:       str   = ""
    long_pos:     Position | None = None
    short_pos:    Position | None = None
    last_signal:  str   = ""
    tick_count:   int   = 0
    error_msg:    str   = ""
    last_balance:        float | None = None  # start() 성공 시 확인된 USDT 잔고 (UI 표시용)
    initial_balance:     float = 0.0          # start() 기준 잔고 — current_loss_pct 계산용
    last_blocked_reason: str  = ""            # 마지막 진입 차단 사유 (G0~G8 게이트)
    last_blocked_side:   str  = ""            # "long" | "short" | ""
    last_blocked_long:   str  = ""            # 롱 전용 차단 사유
    last_blocked_short:  str  = ""            # 숏 전용 차단 사유
    next_scan_at:        float = 0.0          # 다음 신호 스캔 예정 UTC 타임스탬프 (UI 카운트다운용)


class TradingEngine:
    """SL 루프(1초) + 신호 루프(1m봉 마감 동기화) 분리형 거래 엔진.
    bottom/.env API 키 설정 후 실제 Binance Futures 주문 실행.
    """

    def __init__(
        self,
        data_provider: "callable | None" = None,
        sel_refresher: "callable | None" = None,
    ) -> None:
        """
        data_provider: symbol → ind_data dict (MiddleDataManager.get_ind)
        sel_refresher: symbol → None  (MiddleDataManager.request_selected)
                       신호 루프 1m봉 마감마다 호출 → 배정 심볼 klines 갱신
        """
        self._client        = BottomBinanceClient()
        self._data_provider = data_provider
        self._sel_refresher = sel_refresher
        self._params:  StrategyParams | None = None
        self._state  = EngineState()
        self._lock   = threading.Lock()
        self._stop_event  = threading.Event()
        self._sl_thread:  threading.Thread | None = None
        self._sig_thread: threading.Thread | None = None
        # 잔고 캐시
        self._balance_cache: "float | None" = None
        self._balance_ts:    float = 0.0
        # 레버리지 캐시 — 심볼·값이 바뀔 때만 REST 1회
        self._last_leverage_sym: str = ""
        self._last_leverage_val: int = 0
        # Binance SL 주문 ID — Phase 전환 시 취소·교체, 앱 재시작 시 복구
        self._sl_order_id_long:  str = ""
        self._sl_order_id_short: str = ""
        # Trailing Stop 배치 완료 플래그 — Phase3 trailing 재시도 제어
        self._trailing_placed_long:  bool = False
        self._trailing_placed_short: bool = False
        # 연속 손실 쿨다운 — [B] 연속 손절 차단
        self._consecutive_losses:  int   = 0
        self._loss_cooldown_until: float = 0.0
        # 서버 시간 주기 동기화 — clock drift 방지
        self._last_time_sync:      float = 0.0
        # Binance 실제 포지션 동기화 타임스탬프 — 외부 강제 청산 감지
        self._last_pos_sync_ts:    float = 0.0

    # ── 공개 인터페이스 ────────────────────────────────────────
    @property
    def is_live(self) -> bool:
        """API 키가 설정되어 실거래 가능한 상태인지 반환."""
        return self._client.is_live

    def configure(self, params: StrategyParams, symbol: str) -> None:
        """전략 파라미터와 대상 심볼 설정."""
        self._params = params
        with self._lock:
            self._state.symbol               = symbol
            self._state.long_pos             = Position(symbol=symbol, side=PositionSide.LONG)
            self._state.short_pos            = Position(symbol=symbol, side=PositionSide.SHORT)
            self._state.last_blocked_reason  = ""
            self._state.last_blocked_side    = ""
            self._state.next_scan_at         = 0.0
        # SL 주문 ID 초기화 (포지션 리셋에 맞춰 클리어)
        self._sl_order_id_long  = ""
        self._sl_order_id_short = ""
        self._trailing_placed_long  = False
        self._trailing_placed_short = False
        # 레버리지 — 심볼·값 변경 시 Binance에 즉시 반영
        lev = params.leverage
        if symbol and (symbol != self._last_leverage_sym or lev != self._last_leverage_val):
            if self._client.set_leverage(symbol, lev):
                self._last_leverage_sym = symbol
                self._last_leverage_val = lev
            else:
                self._last_leverage_sym = ""
                self._last_leverage_val = 0
                _lev_err = self._client._last_api_error or "응답 없음"
                with self._lock:
                    self._state.error_msg = f"[경고] 레버리지 설정 실패 ({_lev_err}) — Binance 응답 확인 필요"
        # MMR 캐시 선행 채우기 — _auto_calc() 에서 get_mmr_cached() 가 캐시 히트하도록
        if symbol:
            self._client.get_mmr(symbol)

    def get_mmr(self, symbol: str) -> float:
        """워커 스레드 전용 MMR 조회 — 네트워크 호출 발생. UI 스레드에서는 get_mmr_cached() 사용."""
        return self._client.get_mmr(symbol)

    def get_mmr_cached(self, symbol: str) -> float:
        """UI 스레드 전용 MMR 조회 — 네트워크 없이 캐시만 참조."""
        return self._client.get_mmr_cached(symbol)

    def update_params(self, params: StrategyParams) -> None:
        """포지션 추적을 유지한 채 파라미터만 교체 (포지션 보유 중 안전 갱신)."""
        # [C-3] Phase1 SL 재등록 가격 — lock 안에서 계산, lock 밖에서 Binance 호출
        _reregister_long_sl  = 0.0
        _reregister_short_sl = 0.0
        with self._lock:
            self._params = params
            sym = self._state.symbol
            lp  = self._state.long_pos
            sp  = self._state.short_pos
            # [C-2] liq_safe 상한 클램프 — get_mmr_cached()는 캐시 조회이므로 lock 안에서 안전
            _mmr = self._client.get_mmr_cached(sym) if sym else params.mmr
            _sl_up, _trail_up = SLCalculator.clamp(
                params.stop_loss, params.trail_stop, params.leverage, mmr=_mmr)
            if lp and lp.state == PositionState.OPEN:
                lp.stop_loss_pct  = _sl_up
                lp.trail_stop_pct = _trail_up
                # [C-3] Phase1만 재등록 (Phase2=BEP, Phase3=Trailing은 불변)
                if lp.phase == 1:
                    new_sl = round(lp.entry_price * (1 - _sl_up / 100), 8)
                    lp.current_sl       = new_sl
                    _reregister_long_sl = new_sl
            if sp and sp.state == PositionState.OPEN:
                sp.stop_loss_pct  = _sl_up
                sp.trail_stop_pct = _trail_up
                # [C-3] Phase1만 재등록
                if sp.phase == 1:
                    new_sl = round(sp.entry_price * (1 + _sl_up / 100), 8)
                    sp.current_sl        = new_sl
                    _reregister_short_sl = new_sl
        # 레버리지 — 심볼·값 변경 시 Binance에 즉시 반영 (REST는 lock 밖에서 호출)
        lev = params.leverage
        if sym and (sym != self._last_leverage_sym or lev != self._last_leverage_val):
            if self._client.set_leverage(sym, lev):
                self._last_leverage_sym = sym
                self._last_leverage_val = lev
            else:
                with self._lock:
                    self._state.error_msg = "[경고] 레버리지 변경 실패 — Binance 연결 확인 필요"
        # [C-3] Phase1 SL Binance 재등록 — 새 주문 성공 시에만 기존 취소 (안전 교체)
        if sym and _reregister_long_sl > 0:
            self._update_binance_sl_long(_reregister_long_sl)
        if sym and _reregister_short_sl > 0:
            self._update_binance_sl_short(_reregister_short_sl)

    def start(self) -> bool:
        """엔진 시작. 반환: 성공 여부."""
        if self._state.running:
            return False
        if self._params is None:
            with self._lock:
                self._state.error_msg = "전략 미설정 — 전략 선택 후 거래 활성화"
            return False
        # API 키 확인
        if not self._client._has_keys:
            with self._lock:
                self._state.error_msg = "API 키 미설정 — bottom/.env 확인 필요"
            return False
        # 잔고 확인
        balance = self._client.get_account_balance()
        if balance is None:
            with self._lock:
                self._state.error_msg = "잔고 조회 실패 — 네트워크 또는 API 키 확인"
            return False
        if balance == 0.0:
            with self._lock:
                self._state.error_msg = "잔고 없음 — USDT 입금 후 거래 가능"
            return False
        allocated = balance * self._params.funds_pct / 100.0
        if allocated < 5.0:
            with self._lock:
                self._state.error_msg = (
                    f"운용 자금 {allocated:.2f} USDT"
                    f"  (잔고 {balance:.2f} USDT × {self._params.funds_pct}%)"
                    f"  —  최소 5 USDT 필요, 거래 불가")
            return False
        # 포지션 모드 확인 — running 설정 전에 체크해야 실패 시 상태 오염 방지
        sym  = self._state.symbol
        mode = self._client.is_one_way_mode()
        if mode is False:
            with self._lock:
                self._state.error_msg = "[오류] 헤지 모드 계정 감지 — Binance 설정에서 단방향(One-way) 모드로 변경 필요"
            return False
        with self._lock:
            self._state.error_msg        = ""       # 이전 에러 클리어
            self._state.last_balance     = balance  # UI 잔고 표시용
            self._state.initial_balance  = balance  # 기준 잔고 저장 — current_loss_pct 계산용
        self._stop_event.clear()
        lev = self._params.leverage
        # 포지션 선조회 — 포지션 존재 시 레버리지 변경 건너뜀 (Binance 거부 방지)
        _pre_pos_data = self._client.get_position(sym) if sym else None
        _has_pos = (
            _pre_pos_data is not None and
            float(_pre_pos_data.get("positionAmt", 0.0)) != 0.0
        )
        if sym and not _has_pos and (sym != self._last_leverage_sym or lev != self._last_leverage_val):
            # 심볼 최대 레버리지 사전 조회 — 설정값 초과 시 자동 클램핑 (-4028 방지)
            _max_lev = self._client.get_leverage_bracket(sym)
            if _max_lev is not None and lev > _max_lev:
                with self._lock:
                    self._state.error_msg = (
                        f"[경고] {sym} 최대 허용 레버리지 {_max_lev}x — "
                        f"설정값 {lev}x → {_max_lev}x 자동 조정")
                lev = _max_lev
            if not self._client.set_leverage(sym, lev):
                _lev_err = self._client._last_api_error or "응답 없음"
                with self._lock:
                    self._state.error_msg = (
                        f"[오류] 레버리지 설정 실패 ({_lev_err}) — "
                        "Binance 계정에서 수동 확인 후 재시작")
                return False
            self._last_leverage_sym = sym
            self._last_leverage_val = lev
        # 마진 타입 ISOLATED 강제 설정 — CROSSED 모드 실거래 위험 방지
        if sym:
            if not self._client.set_margin_type(sym, "ISOLATED"):
                with self._lock:
                    self._state.error_msg = (
                        "[오류] ISOLATED 마진 타입 설정 실패 — "
                        "Binance 계정에서 수동 확인 후 재시작")
                return False
        self._state.running = True
        # Binance SL 주문 ID 복구 — 앱 재시작 후 기존 등록 주문 이어받기
        self._sl_order_id_long  = ""
        self._sl_order_id_short = ""
        self._trailing_placed_long  = False
        self._trailing_placed_short = False
        if sym:
            _open_orders = self._client.get_open_orders(sym)
            if _open_orders is None:
                with self._lock:
                    self._state.error_msg = (
                        "[오류] 미체결 주문 조회 실패 — "
                        "SL 주문 복구 불가, 네트워크 확인 후 재시작")
                self._state.running = False
                return False
            for o in _open_orders:
                otype = o.get("type", "")
                if otype not in ("STOP_MARKET", "TRAILING_STOP_MARKET"):
                    continue
                oid  = str(o.get("orderId", ""))
                side = o.get("side", "")
                if not oid:
                    continue
                if side == "SELL" and not self._sl_order_id_long:
                    self._sl_order_id_long  = oid
                elif side == "BUY" and not self._sl_order_id_short:
                    self._sl_order_id_short = oid
        # 실제 Binance 포지션 동기화 — 진입 체결 후 SL 등록 전 크래시 시나리오 복구
        if sym and self._params:
            try:
                pos_data = _pre_pos_data  # start() 초반 선조회 결과 재사용 (API 호출 절약)
                if pos_data:
                    pos_amt     = float(pos_data.get("positionAmt", 0.0))
                    entry_price = float(pos_data.get("entryPrice", 0.0))
                    # [C-2] 복구 포지션 SL에도 liq_safe 클램프 적용 — REST는 lock 밖에서 안전
                    _rec_mmr = self._client.get_mmr(sym)
                    _rec_sl, _rec_trail = SLCalculator.clamp(
                        self._params.stop_loss, self._params.trail_stop,
                        self._params.leverage, mmr=_rec_mmr)
                    if pos_amt > 0.0 and entry_price > 0.0:
                        with self._lock:
                            lp = self._state.long_pos
                            if lp is None or lp.state != PositionState.OPEN:
                                recovered = LongPosition.open(
                                    sym, entry_price, pos_amt, self._params,
                                    sl_pct=_rec_sl, trail_pct=_rec_trail)
                                recovered.phase = 1
                                self._state.long_pos = recovered
                        if not self._sl_order_id_long:
                            with self._lock:
                                lp_now = self._state.long_pos
                            if lp_now and lp_now.state == PositionState.OPEN:
                                tick      = self._client.get_price_precision(sym)
                                sl_price  = self._round_price_to_tick(lp_now.current_sl, tick)
                                _rec_mark = self._client.get_mark_price(sym) or 0.0
                                if sl_price > 0 and (_rec_mark <= 0 or sl_price < _rec_mark):
                                    oid = self._client.place_stop_market(sym, "SELL", sl_price)
                                    self._sl_order_id_long = oid
                    elif pos_amt < 0.0 and entry_price > 0.0:
                        with self._lock:
                            sp = self._state.short_pos
                            if sp is None or sp.state != PositionState.OPEN:
                                recovered = ShortPosition.open(
                                    sym, entry_price, abs(pos_amt), self._params,
                                    sl_pct=_rec_sl, trail_pct=_rec_trail)
                                recovered.phase = 1
                                self._state.short_pos = recovered
                        if not self._sl_order_id_short:
                            with self._lock:
                                sp_now = self._state.short_pos
                            if sp_now and sp_now.state == PositionState.OPEN:
                                tick      = self._client.get_price_precision(sym)
                                sl_price  = self._round_price_to_tick(sp_now.current_sl, tick)
                                _rec_mark = self._client.get_mark_price(sym) or 0.0
                                if sl_price > 0 and (_rec_mark <= 0 or sl_price > _rec_mark):
                                    oid = self._client.place_stop_market(sym, "BUY", sl_price)
                                    self._sl_order_id_short = oid
            except Exception as e:
                with self._lock:
                    self._state.error_msg = f"[경보] 포지션 복구 실패 — {e}  수동 포지션 확인 후 재시작"
                self._state.running = False
                return False
        # SL 루프 + 신호 루프 각각 별도 스레드
        self._sl_thread  = threading.Thread(
            target=self._sl_loop, daemon=True, name="sl_loop")
        self._sig_thread = threading.Thread(
            target=self._signal_loop, daemon=True, name="signal_loop")
        self._sl_thread.start()
        self._sig_thread.start()
        return True

    def stop(self) -> None:
        """엔진 중지 (두 스레드 모두 즉시 종료)."""
        self._stop_event.set()
        self._state.running = False
        with self._lock:
            self._state.error_msg           = ""
            self._state.last_blocked_reason = ""
            self._state.last_blocked_side   = ""
            self._state.last_blocked_long   = ""
            self._state.last_blocked_short  = ""
            self._state.next_scan_at        = 0.0

    def force_close_all(self) -> dict:
        """열린 포지션 전체를 즉시 시장가로 강제 청산 (엔진 중지는 호출자 책임).

        반환: {"long": "성공"|"실패"|"없음", "short": "성공"|"실패"|"없음"}
        """
        sym  = self._state.symbol
        mark = 0.0
        if sym:
            mark = self._client.get_mark_price(sym) or 0.0

        results: dict = {"long": "없음", "short": "없음"}

        if mark <= 0:
            with self._lock:
                self._state.error_msg = "강제 청산 실패: mark price 조회 불가"
            results["long"]  = "실패"
            results["short"] = "실패"
            return results

        with self._lock:
            lp = self._state.long_pos
            sp = self._state.short_pos

        if lp and lp.state == PositionState.OPEN:
            with self._lock:
                self._state.error_msg = ""
            self._close_long("강제 청산", mark)
            with self._lock:
                results["long"] = "성공" if not self._state.error_msg else "실패"

        if sp and sp.state == PositionState.OPEN:
            with self._lock:
                self._state.error_msg = ""
            self._close_short("강제 청산", mark)
            with self._lock:
                results["short"] = "성공" if not self._state.error_msg else "실패"

        return results

    def has_open_positions(self) -> bool:
        """열린 포지션(롱 또는 숏) 존재 여부 반환."""
        with self._lock:
            lp = self._state.long_pos
            sp = self._state.short_pos
        return bool(
            (lp and lp.state == PositionState.OPEN) or
            (sp and sp.state == PositionState.OPEN)
        )

    def get_state(self) -> EngineState:
        """현재 엔진 상태 반환 (UI 폴링용)."""
        return self._state

    # ── SL 루프 ── 1초 주기, 포지션 있을 때만 API 호출 ─────────
    def _sl_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                _now_sync = time.time()
                _need_resync = (
                    (_now_sync - self._last_time_sync >= 900) or
                    ("-1021" in self._client._last_api_error)
                )
                if _need_resync:
                    self._client._sync_server_time()
                    self._last_time_sync = _now_sync
                with self._lock:
                    lp = self._state.long_pos
                    sp = self._state.short_pos

                has_long  = (lp and lp.state == PositionState.OPEN)
                has_short = (sp and sp.state == PositionState.OPEN)

                if has_long or has_short:
                    _now_ps = time.time()
                    if _now_ps - self._last_pos_sync_ts >= _POS_SYNC_INTERVAL_SEC:
                        self._sync_position_with_binance()
                        self._last_pos_sync_ts = _now_ps
                        with self._lock:
                            lp = self._state.long_pos
                            sp = self._state.short_pos
                        has_long  = (lp and lp.state == PositionState.OPEN)
                        has_short = (sp and sp.state == PositionState.OPEN)
                    mark = self._client.get_mark_price(self._state.symbol) or 0.0
                    if mark <= 0 and self._client._rate_limited_until > time.time():
                        with self._lock:
                            _rem = int(self._client._rate_limited_until - time.time())
                            self._state.error_msg = f"[경보] Binance API 차단 — {_rem}초 후 해제. SL 감시 일시 중단"
                        self._stop_event.wait(SL_INTERVAL_SEC)
                        continue
                    if mark > 0:
                        # KD 익절용 ind_data — DataManager 캐시 조회 (추가 API 없음)
                        _ind_kd: dict = {}
                        if self._data_provider:
                            try:
                                _ind_kd = self._data_provider(self._state.symbol)
                            except Exception as e:
                                with self._lock:
                                    self._state.error_msg = f"[경고] 지표 데이터 조회 실패 — {e}  KD 익절 스킵"
                        if has_long:
                            old_phase_l = lp.phase
                            with self._lock:
                                updated = LongPosition.update(lp, mark)
                                self._state.long_pos = updated
                                self._state.tick_count += 1
                            # Phase 전환 감지 → Binance SL 갱신
                            if updated.phase == 2 and old_phase_l == 1:
                                # Phase1 → Phase2: BEP STOP_MARKET으로 교체
                                self._beep((659, 100), (880, 180))
                                self._update_binance_sl_long(updated.entry_price, mark)
                            elif updated.phase == 3 and not updated.partial_closed and not updated.partial_in_progress:
                                # Phase2 → Phase3: 50% 부분 청산 후 trailing stop 등록
                                self._beep((523, 80), (659, 80), (784, 80), (1047, 180))
                                self._partial_close_long(mark)
                                with self._lock:
                                    lp_now = self._state.long_pos
                                remaining = (lp_now.quantity
                                             if lp_now and lp_now.state == PositionState.OPEN
                                             else 0.0)
                                if remaining > 0:
                                    sym = self._state.symbol
                                    oid = self._client.place_trailing_stop(
                                        sym, "SELL", updated.trail_stop_pct, remaining)
                                    if oid:
                                        if self._sl_order_id_long:
                                            self._client.cancel_order(sym, self._sl_order_id_long)
                                        self._sl_order_id_long = oid
                                        self._trailing_placed_long = True
                                    else:
                                        with self._lock:
                                            self._state.error_msg = "[경보] 롱 Trailing Stop 등록 실패 — Binance 연결 확인 필요"
                            elif updated.phase == 3 and updated.partial_closed and not self._trailing_placed_long:
                                # Phase3 trailing 재시도 — 이전 루프에서 배치 실패한 경우
                                with self._lock:
                                    lp_now = self._state.long_pos
                                remaining = (lp_now.quantity
                                             if lp_now and lp_now.state == PositionState.OPEN
                                             else 0.0)
                                if remaining > 0:
                                    sym = self._state.symbol
                                    oid = self._client.place_trailing_stop(
                                        sym, "SELL", updated.trail_stop_pct, remaining)
                                    if oid:
                                        if self._sl_order_id_long:
                                            self._client.cancel_order(sym, self._sl_order_id_long)
                                        self._sl_order_id_long = oid
                                        self._trailing_placed_long = True
                                    else:
                                        with self._lock:
                                            self._state.error_msg = "[경보] 롱 Trailing Stop 재시도 실패 — Binance 연결 확인 필요"
                            # KD 역전 익절 — 롱 (Phase3 전용, 과매수 구간 하향 이탈)
                            if _ind_kd and updated.phase == 3 and not RiskManager.should_stop_loss(updated, mark):
                                _tf1 = _ind_kd.get("tf1", {})
                                _k1m = float(_tf1.get("k", 50.0))
                                _d1m = float(_tf1.get("d", 50.0))
                                if _k1m > 80.0 and _k1m < _d1m and (_d1m - _k1m) >= 2.0:
                                    self._close_long("KD 역전 익절", mark)
                            if RiskManager.should_stop_loss(updated, mark):
                                self._close_long("SL 도달", mark)

                        if has_short:
                            old_phase_s = sp.phase
                            with self._lock:
                                updated = ShortPosition.update(sp, mark)
                                self._state.short_pos = updated
                            # Phase 전환 감지 → Binance SL 갱신
                            if updated.phase == 2 and old_phase_s == 1:
                                # Phase1 → Phase2: BEP STOP_MARKET으로 교체
                                self._beep((659, 100), (880, 180))
                                self._update_binance_sl_short(updated.entry_price, mark)
                            elif updated.phase == 3 and not updated.partial_closed and not updated.partial_in_progress:
                                # Phase2 → Phase3: 50% 부분 청산 후 trailing stop 등록
                                self._beep((523, 80), (659, 80), (784, 80), (1047, 180))
                                self._partial_close_short(mark)
                                with self._lock:
                                    sp_now = self._state.short_pos
                                remaining = (sp_now.quantity
                                             if sp_now and sp_now.state == PositionState.OPEN
                                             else 0.0)
                                if remaining > 0:
                                    sym = self._state.symbol
                                    oid = self._client.place_trailing_stop(
                                        sym, "BUY", updated.trail_stop_pct, remaining)
                                    if oid:
                                        if self._sl_order_id_short:
                                            self._client.cancel_order(sym, self._sl_order_id_short)
                                        self._sl_order_id_short = oid
                                        self._trailing_placed_short = True
                                    else:
                                        with self._lock:
                                            self._state.error_msg = "[경보] 숏 Trailing Stop 등록 실패 — Binance 연결 확인 필요"
                            elif updated.phase == 3 and updated.partial_closed and not self._trailing_placed_short:
                                # Phase3 trailing 재시도 — 이전 루프에서 배치 실패한 경우
                                with self._lock:
                                    sp_now = self._state.short_pos
                                remaining = (sp_now.quantity
                                             if sp_now and sp_now.state == PositionState.OPEN
                                             else 0.0)
                                if remaining > 0:
                                    sym = self._state.symbol
                                    oid = self._client.place_trailing_stop(
                                        sym, "BUY", updated.trail_stop_pct, remaining)
                                    if oid:
                                        if self._sl_order_id_short:
                                            self._client.cancel_order(sym, self._sl_order_id_short)
                                        self._sl_order_id_short = oid
                                        self._trailing_placed_short = True
                                    else:
                                        with self._lock:
                                            self._state.error_msg = "[경보] 숏 Trailing Stop 재시도 실패 — Binance 연결 확인 필요"
                            # KD 역전 익절 — 숏 (Phase3 전용, 과매도 구간 상향 돌파)
                            if _ind_kd and updated.phase == 3 and not RiskManager.should_stop_loss(updated, mark):
                                _tf1 = _ind_kd.get("tf1", {})
                                _k1m = float(_tf1.get("k", 50.0))
                                _d1m = float(_tf1.get("d", 50.0))
                                if _k1m < 20.0 and _k1m > _d1m and (_k1m - _d1m) >= 2.0:
                                    self._close_short("KD 역전 익절", mark)
                            if RiskManager.should_stop_loss(updated, mark):
                                self._close_short("SL 도달", mark)
                # 포지션 없으면 API 호출 없이 1초 sleep 만 실행

            except Exception as e:
                with self._lock:
                    self._state.error_msg = str(e)

            self._stop_event.wait(SL_INTERVAL_SEC)

    # ── 신호 루프 ── 1m 봉 마감 동기화, 봉 마감마다 4TF 신호 평가 ──
    def _signal_loop(self) -> None:
        # 다음 1m 봉 마감 직후로 초기 동기화 (최초 1회)
        now_sec  = time.time() % 60
        wait_sec = 60.0 - now_sec   # 분봉 마감까지만 대기 (settle은 루프 내부에서)
        if self._stop_event.wait(wait_sec):
            return

        while not self._stop_event.is_set():
            try:
                sym = self._state.symbol
                # 1m 봉 마감 직후: klines 갱신 요청 (백그라운드 비차단)
                if sym and self._sel_refresher:
                    try:
                        self._sel_refresher(sym)
                    except Exception as e:
                        with self._lock:
                            self._state.error_msg = f"[경고] klines 갱신 요청 실패 — {e}"

                # API 갱신 완료 대기 (_DATA_SETTLE_SEC 초)
                if self._stop_event.wait(_DATA_SETTLE_SEC):
                    break

                with self._lock:
                    lp = self._state.long_pos
                    sp = self._state.short_pos

                has_long  = (lp and lp.state == PositionState.OPEN)
                has_short = (sp and sp.state == PositionState.OPEN)

                if not (has_long and has_short):
                    ind = self._get_ind_data()

                    if not ind:
                        # _get_ind_data() 내부에서 이미 reason 기록 — 미기록 상태면 기본 메시지
                        with self._lock:
                            if not self._state.last_blocked_reason:
                                self._state.last_blocked_reason = (
                                    "지표 데이터 없음 — 중단 모듈 초기화 대기")
                                self._state.last_blocked_side = ""
                    elif not ind.get("_data_ready", True):
                        with self._lock:
                            self._state.last_blocked_reason = "실시간 지표 미준비 — 초기화 대기 중"
                            self._state.last_blocked_side   = ""
                    else:
                        mark = 0.0  # 진입 신호 발생 시에만 REST 1회 조회
                        days = ind.get("_days_listed", 9999)
                        _blk_long  = ""
                        _blk_short = ""
                        _long_entered_this_cycle = False

                        if not has_long:
                            ok, reason = LongCondition.evaluate(
                                ind, self._params, has_short_open=has_short,
                                days_listed=days)
                            if ok:
                                if mark == 0.0:
                                    mark = self._client.get_mark_price(sym) or 0.0
                                if mark > 0:
                                    entered = self._enter_long(mark, ind)
                                    if entered:
                                        _long_entered_this_cycle = True
                                        with self._lock:
                                            self._state.last_signal        = "롱 진입"
                                            self._state.last_blocked_long  = ""
                                            self._state.last_blocked_short = ""
                                            self._state.last_blocked_reason = ""
                                            self._state.last_blocked_side   = ""
                                            lp_now = self._state.long_pos
                                            has_long = bool(
                                                lp_now and lp_now.state == PositionState.OPEN)
                                else:
                                    _blk_long = "G 필터 통과 — Mark Price 조회 실패 (Binance 연결 확인)"
                            else:
                                _blk_long = reason

                        if not has_short and not _long_entered_this_cycle:
                            ok, reason = ShortCondition.evaluate(
                                ind, self._params, has_long_open=has_long,
                                days_listed=days)
                            if ok:
                                if mark == 0.0:
                                    mark = self._client.get_mark_price(sym) or 0.0
                                if mark > 0:
                                    entered = self._enter_short(mark, ind)
                                    if entered:
                                        with self._lock:
                                            self._state.last_signal        = "숏 진입"
                                            self._state.last_blocked_long  = ""
                                            self._state.last_blocked_short = ""
                                            self._state.last_blocked_reason = ""
                                            self._state.last_blocked_side   = ""
                                else:
                                    _blk_short = "G 필터 통과 — Mark Price 조회 실패 (Binance 연결 확인)"
                            else:
                                _blk_short = reason

                        # 롱/숏 차단 사유 일괄 갱신 — 롱 우선 표시
                        if _blk_long or _blk_short:
                            with self._lock:
                                self._state.last_blocked_long  = _blk_long
                                self._state.last_blocked_short = _blk_short
                                if _blk_long:
                                    self._state.last_blocked_reason = _blk_long
                                    self._state.last_blocked_side   = "long"
                                else:
                                    self._state.last_blocked_reason = _blk_short
                                    self._state.last_blocked_side   = "short"

            except Exception as e:
                with self._lock:
                    self._state.error_msg = str(e)

            # 다음 1m 봉 마감까지 동적 대기 — 처리 시간 drift 보정
            _next_close = (int(time.time() // 60) + 1) * 60
            self._state.next_scan_at = _next_close      # UI 카운트다운용
            if self._stop_event.wait(max(0.0, _next_close - time.time())):
                break

    # ── 진입 ─────────────────────────────────────────────────
    def _enter_long(self, mark: float, ind: dict | None = None) -> bool:
        # [B] 연속 손실 쿨다운 체크
        if time.time() < self._loss_cooldown_until:
            remaining = int(self._loss_cooldown_until - time.time())
            with self._lock:
                self._state.error_msg = f"[쿨다운] {_MAX_CONSECUTIVE_LOSSES}연속 손절 — {remaining}초 후 재개"
            return False
        with self._lock:
            lp      = self._state.long_pos
            sp      = self._state.short_pos
            init_b  = self._state.initial_balance
        balance = self._get_balance()
        if balance is None:
            with self._lock:
                self._state.error_msg = "잔고 조회 실패 — 진입 차단"
            return False
        # [C] 일일 손실 한도 게이트 (KST 자정 기준, 재시작 내성)
        DailyLossTracker.ensure_initialized(balance)
        _daily_loss_pct = DailyLossTracker.loss_pct(balance)
        if RiskManager.should_daily_stop(_daily_loss_pct):
            self.stop()
            with self._lock:
                self._state.error_msg = (
                    f"[긴급] 일일 손실 한도(-{MAX_DAILY_LOSS_PCT:.0f}%) 초과 — 엔진 자동 정지")
            return False
        current_loss_pct = (
            (balance - init_b) / init_b * 100.0 if init_b > 0 else 0.0)
        rr = RiskManager.validate_entry(
            self._params, PositionSide.LONG, lp, sp,
            portfolio_usdt=balance,
            current_loss_pct=current_loss_pct)
        if not rr.allowed:
            # [A] 포트폴리오 손실 한도 초과 시 엔진 자동 정지
            if RiskManager.should_auto_stop(current_loss_pct):
                self.stop()
                with self._lock:
                    self._state.error_msg = (
                        f"[긴급] 포트폴리오 손실 한도(-{MAX_PORTFOLIO_LOSS_PCT:.0f}%) 초과 — 엔진 자동 정지")
            else:
                with self._lock:
                    self._state.error_msg = rr.reason
            return False
        prec    = self._client.get_qty_precision(self._state.symbol)
        min_qty = self._client.get_min_qty(self._state.symbol)
        qty     = RiskManager.calc_position_size(self._params, mark, balance,
                                                 qty_precision=prec)
        qty = self._client.floor_qty(self._state.symbol, qty)
        # [C-2] R-cap 사전 계산 — 사용자 설정 SL에 liq_safe 상한 적용 후 무조건 적용
        _mmr          = self._client.get_mmr(self._state.symbol)
        _sl_used, _trail_used = SLCalculator.clamp(
            self._params.stop_loss, self._params.trail_stop,
            self._params.leverage, mmr=_mmr)
        qty = RiskManager.apply_r_cap(qty, mark, _sl_used, balance)
        qty = self._client.floor_qty(self._state.symbol, qty)
        if qty <= 0:
            with self._lock:
                self._state.error_msg = "수량 계산 실패 — exchangeInfo 조회 불가, 진입 차단"
            return False
        if min_qty > 0 and qty < min_qty:
            with self._lock:
                self._state.error_msg = (
                    f"수량 {qty:.{prec}f} < 최소 주문 수량 {min_qty}"
                    f"  —  Designated Funds 또는 레버리지 확인")
            return False
        result = LongOrder.execute(self._client, self._state.symbol, qty, self._params, mark)
        if not result.success:
            _err = result.error or ""
            _sym = self._state.symbol
            _no_retry = ("Rate Limited" in _err or "418" in _err or
                         "[-2010]" in _err or "[-1111]" in _err or "[-1003]" in _err)
            if not _no_retry:
                if "503" in _err:
                    try:
                        _pos = self._client.get_position(_sym)
                        if _pos is not None:
                            _amt = float(_pos.get("positionAmt", 0.0))
                            _ep  = float(_pos.get("entryPrice",  0.0))
                            if _amt > 0.0 and _ep > 0.0:
                                result = OrderResult(True, fill_price=_ep, quantity=_amt)
                            elif _amt == 0.0:
                                time.sleep(1.5)
                                result = LongOrder.execute(
                                    self._client, _sym, qty, self._params, mark)
                    except Exception as e:
                        with self._lock:
                            self._state.error_msg = (
                                f"[경보] 503 재시도 중 포지션 확인 실패 — {e}  "
                                "수동 포지션 확인 필요")
                elif ("-1008" in _err or "timed out" in _err
                      or "URLError" in _err):
                    # 결과 불명 — 재주문 전 실제 포지션 확인 (이중 진입 방지)
                    time.sleep(2.0)
                    try:
                        _pos = self._client.get_position(_sym)
                    except Exception:
                        _pos = None
                    if _pos is None:
                        with self._lock:
                            self._state.error_msg = (
                                "[경보] 주문 결과 불명 + 포지션 조회 실패 — "
                                "재주문 중단. Binance에서 수동 확인 필요")
                    else:
                        _amt = float(_pos.get("positionAmt", 0.0))
                        _ep  = float(_pos.get("entryPrice",  0.0))
                        if _amt > 0.0 and _ep > 0.0:
                            result = OrderResult(True, fill_price=_ep,
                                                 quantity=_amt)
                        elif _amt == 0.0:
                            result = LongOrder.execute(
                                self._client, _sym, qty, self._params, mark)
        if result.success:
            pos = LongPosition.open(
                self._state.symbol, result.fill_price, result.quantity,
                self._params,
                sl_pct=_sl_used,
                trail_pct=_trail_used,
            )
            with self._lock:
                self._state.long_pos = pos
            self._beep((1319, 200), (1047, 340))
            self._invalidate_balance()
            # Binance STOP_MARKET SL 등록 — Phase1 초기 SL (Binance UI TP/SL 표시)
            sym      = self._state.symbol
            tick     = self._client.get_price_precision(sym)
            sl_price = self._round_price_to_tick(pos.current_sl, tick)
            if sl_price > 0:
                if sl_price >= mark:
                    with self._lock:
                        self._state.error_msg = (
                            f"[경보] 롱 SL 등록 불가 — SL({sl_price:.4f}) ≥ 마크가({mark:.4f}): 수동 확인 필요")
                    return True
                oid = self._client.place_stop_market(sym, "SELL", sl_price)
                self._sl_order_id_long = oid
                if not oid:
                    with self._lock:
                        self._state.error_msg = "[경보] 롱 SL 주문 등록 실패 — Binance 연결·잔고 확인 필요"
            return True
        else:
            with self._lock:
                self._state.error_msg = result.error or "롱 주문 실패"
            return False

    def _enter_short(self, mark: float, ind: dict | None = None) -> bool:
        # [B] 연속 손실 쿨다운 체크
        if time.time() < self._loss_cooldown_until:
            remaining = int(self._loss_cooldown_until - time.time())
            with self._lock:
                self._state.error_msg = f"[쿨다운] {_MAX_CONSECUTIVE_LOSSES}연속 손절 — {remaining}초 후 재개"
            return False
        with self._lock:
            lp      = self._state.long_pos
            sp      = self._state.short_pos
            init_b  = self._state.initial_balance
        balance = self._get_balance()
        if balance is None:
            with self._lock:
                self._state.error_msg = "잔고 조회 실패 — 진입 차단"
            return False
        # [C] 일일 손실 한도 게이트 (KST 자정 기준, 재시작 내성)
        DailyLossTracker.ensure_initialized(balance)
        _daily_loss_pct = DailyLossTracker.loss_pct(balance)
        if RiskManager.should_daily_stop(_daily_loss_pct):
            self.stop()
            with self._lock:
                self._state.error_msg = (
                    f"[긴급] 일일 손실 한도(-{MAX_DAILY_LOSS_PCT:.0f}%) 초과 — 엔진 자동 정지")
            return False
        current_loss_pct = (
            (balance - init_b) / init_b * 100.0 if init_b > 0 else 0.0)
        rr = RiskManager.validate_entry(
            self._params, PositionSide.SHORT, lp, sp,
            portfolio_usdt=balance,
            current_loss_pct=current_loss_pct)
        if not rr.allowed:
            # [A] 포트폴리오 손실 한도 초과 시 엔진 자동 정지
            if RiskManager.should_auto_stop(current_loss_pct):
                self.stop()
                with self._lock:
                    self._state.error_msg = (
                        f"[긴급] 포트폴리오 손실 한도(-{MAX_PORTFOLIO_LOSS_PCT:.0f}%) 초과 — 엔진 자동 정지")
            else:
                with self._lock:
                    self._state.error_msg = rr.reason
            return False
        prec    = self._client.get_qty_precision(self._state.symbol)
        min_qty = self._client.get_min_qty(self._state.symbol)
        qty     = RiskManager.calc_position_size(self._params, mark, balance,
                                                 qty_precision=prec)
        qty = self._client.floor_qty(self._state.symbol, qty)
        # [C-2] R-cap 사전 계산 — 사용자 설정 SL에 liq_safe 상한 적용 후 무조건 적용
        _mmr          = self._client.get_mmr(self._state.symbol)
        _sl_used, _trail_used = SLCalculator.clamp(
            self._params.stop_loss, self._params.trail_stop,
            self._params.leverage, mmr=_mmr)
        qty = RiskManager.apply_r_cap(qty, mark, _sl_used, balance)
        qty = self._client.floor_qty(self._state.symbol, qty)
        if qty <= 0:
            with self._lock:
                self._state.error_msg = "수량 계산 실패 — exchangeInfo 조회 불가, 진입 차단"
            return False
        if min_qty > 0 and qty < min_qty:
            with self._lock:
                self._state.error_msg = (
                    f"수량 {qty:.{prec}f} < 최소 주문 수량 {min_qty}"
                    f"  —  Designated Funds 또는 레버리지 확인")
            return False
        result = ShortOrder.execute(self._client, self._state.symbol, qty, self._params, mark)
        if not result.success:
            _err = result.error or ""
            _sym = self._state.symbol
            _no_retry = ("Rate Limited" in _err or "418" in _err or
                         "[-2010]" in _err or "[-1111]" in _err or "[-1003]" in _err)
            if not _no_retry:
                if "503" in _err:
                    try:
                        _pos = self._client.get_position(_sym)
                        if _pos is not None:
                            _amt = float(_pos.get("positionAmt", 0.0))
                            _ep  = float(_pos.get("entryPrice",  0.0))
                            if _amt < 0.0 and _ep > 0.0:
                                result = OrderResult(True, fill_price=_ep, quantity=abs(_amt))
                            elif _amt == 0.0:
                                time.sleep(1.5)
                                result = ShortOrder.execute(
                                    self._client, _sym, qty, self._params, mark)
                    except Exception as e:
                        with self._lock:
                            self._state.error_msg = (
                                f"[경보] 503 재시도 중 포지션 확인 실패 — {e}  "
                                "수동 포지션 확인 필요")
                elif ("-1008" in _err or "timed out" in _err
                      or "URLError" in _err):
                    # 결과 불명 — 재주문 전 실제 포지션 확인 (이중 진입 방지)
                    time.sleep(2.0)
                    try:
                        _pos = self._client.get_position(_sym)
                    except Exception:
                        _pos = None
                    if _pos is None:
                        with self._lock:
                            self._state.error_msg = (
                                "[경보] 주문 결과 불명 + 포지션 조회 실패 — "
                                "재주문 중단. Binance에서 수동 확인 필요")
                    else:
                        _amt = float(_pos.get("positionAmt", 0.0))
                        _ep  = float(_pos.get("entryPrice",  0.0))
                        if _amt < 0.0 and _ep > 0.0:
                            result = OrderResult(True, fill_price=_ep,
                                                 quantity=abs(_amt))
                        elif _amt == 0.0:
                            result = ShortOrder.execute(
                                self._client, _sym, qty, self._params, mark)
        if result.success:
            pos = ShortPosition.open(
                self._state.symbol, result.fill_price, result.quantity,
                self._params,
                sl_pct=_sl_used,
                trail_pct=_trail_used,
            )
            with self._lock:
                self._state.short_pos = pos
            self._beep((1319, 200), (1047, 340))
            self._invalidate_balance()
            # Binance STOP_MARKET SL 등록 — Phase1 초기 SL (Binance UI TP/SL 표시)
            sym      = self._state.symbol
            tick     = self._client.get_price_precision(sym)
            sl_price = self._round_price_to_tick(pos.current_sl, tick)
            if sl_price > 0:
                if sl_price <= mark:
                    with self._lock:
                        self._state.error_msg = (
                            f"[경보] 숏 SL 등록 불가 — SL({sl_price:.4f}) ≤ 마크가({mark:.4f}): 수동 확인 필요")
                    return True
                oid = self._client.place_stop_market(sym, "BUY", sl_price)
                self._sl_order_id_short = oid
                if not oid:
                    with self._lock:
                        self._state.error_msg = "[경보] 숏 SL 주문 등록 실패 — Binance 연결·잔고 확인 필요"
            return True
        else:
            with self._lock:
                self._state.error_msg = result.error or "숏 주문 실패"
            return False

    # ── 부분 청산 (Phase3 전환 시 50% 익절) ──────────────────
    def _partial_close_long(self, mark: float) -> None:
        """롱 Phase3 전환 시 50% 부분 청산 — partial_in_progress로 중복 차단, 실패 시 재시도 허용."""
        with self._lock:
            lp = self._state.long_pos
            if not (lp and lp.state == PositionState.OPEN):
                return
            if lp.partial_in_progress:
                return
            lp.partial_in_progress = True
            self._state.long_pos = lp

        half_qty = self._client.floor_qty(self._state.symbol, lp.quantity / 2)
        if half_qty <= 0:
            with self._lock:
                lp = self._state.long_pos
                if lp:
                    lp.partial_in_progress = False
                    self._state.long_pos = lp
            return
        result = self._client.close_position(
            self._state.symbol, "long", half_qty, mark)
        with self._lock:
            lp = self._state.long_pos
            if lp and lp.state == PositionState.OPEN:
                if result.success:
                    lp.quantity = self._client.floor_qty(
                        self._state.symbol, lp.quantity - half_qty)
                    lp.partial_closed      = True
                    lp.partial_in_progress = False
                    self._state.last_signal = "롱 50% 부분 익절 (Phase3 트레일링 전환)"
                else:
                    lp.partial_in_progress = False
                    self._state.error_msg  = f"롱 부분 청산 실패: {result.error}"
                self._state.long_pos = lp
        if result.success:
            self._invalidate_balance()

    def _partial_close_short(self, mark: float) -> None:
        """숏 Phase3 전환 시 50% 부분 청산 — partial_in_progress로 중복 차단, 실패 시 재시도 허용."""
        with self._lock:
            sp = self._state.short_pos
            if not (sp and sp.state == PositionState.OPEN):
                return
            if sp.partial_in_progress:
                return
            sp.partial_in_progress = True
            self._state.short_pos = sp

        half_qty = self._client.floor_qty(self._state.symbol, sp.quantity / 2)
        if half_qty <= 0:
            with self._lock:
                sp = self._state.short_pos
                if sp:
                    sp.partial_in_progress = False
                    self._state.short_pos = sp
            return
        result = self._client.close_position(
            self._state.symbol, "short", half_qty, mark)
        with self._lock:
            sp = self._state.short_pos
            if sp and sp.state == PositionState.OPEN:
                if result.success:
                    sp.quantity = self._client.floor_qty(
                        self._state.symbol, sp.quantity - half_qty)
                    sp.partial_closed      = True
                    sp.partial_in_progress = False
                    self._state.last_signal = "숏 50% 부분 익절 (Phase3 트레일링 전환)"
                else:
                    sp.partial_in_progress = False
                    self._state.error_msg  = f"숏 부분 청산 실패: {result.error}"
                self._state.short_pos = sp
        if result.success:
            self._invalidate_balance()

    # ── 청산 ─────────────────────────────────────────────────
    def _close_long(self, reason: str, mark: float = 0.0) -> None:
        with self._lock:
            lp = self._state.long_pos
        if not (lp and lp.state == PositionState.OPEN):
            return
        result = self._client.close_position(
            self._state.symbol, "long", lp.quantity, mark)
        if result.success:
            exit_p = result.fill_price if result.fill_price > 0 else mark
            with self._lock:
                self._state.long_pos    = LongPosition.close(lp, exit_price=exit_p, exit_reason=reason)
                self._state.last_signal = f"롱 청산({reason})"
            self._invalidate_balance()
            # 청산 완료 후 잔여 Binance SL 주문 취소
            if self._sl_order_id_long:
                self._client.cancel_order(self._state.symbol, self._sl_order_id_long)
                self._sl_order_id_long = ""
            self._trailing_placed_long = False
            # [B] 연속 손실 카운터 갱신 — 문자열이 아니라 실현 손익 기준 판정
            #     (Phase2 BEP 스탑 청산이 손절로 오분류되는 문제 수정)
            with self._lock:
                _closed_l = self._state.long_pos
            _is_loss = bool(_closed_l and _closed_l.pnl_usdt < 0)
            if _is_loss:
                self._beep((220, 220), (165, 220), (110, 460))
                self._consecutive_losses += 1
            else:
                self._beep((784, 100), (784, 100), (1047, 100), (784, 100), (1047, 100), (1319, 380))
                self._consecutive_losses = 0
            if self._consecutive_losses >= _MAX_CONSECUTIVE_LOSSES:
                self._loss_cooldown_until = time.time() + _LOSS_COOLDOWN_SEC
                self._consecutive_losses = 0
            # [B4] 청산 직후 일일 손실 한도 재확인 — _invalidate_balance() 이미 호출됨
            if _is_loss:
                _post_b = self._get_balance()
                if _post_b is not None and RiskManager.should_daily_stop(
                        DailyLossTracker.loss_pct(_post_b)):
                    self.stop()
                    with self._lock:
                        self._state.error_msg = (
                            f"[긴급] 일일 손실 한도(-{MAX_DAILY_LOSS_PCT:.0f}%) 초과 — 엔진 자동 정지")
        else:
            # Binance SL이 먼저 발동해 포지션이 이미 없는 경우 확인
            try:
                actual = self._client.get_position(self._state.symbol)
                if actual is not None and float(actual.get("positionAmt", 1)) == 0.0:
                    with self._lock:
                        self._state.long_pos    = LongPosition.close(
                            lp, exit_price=mark, exit_reason="Binance SL 발동")
                        self._state.last_signal = "롱 청산(Binance SL 발동)"
                    self._invalidate_balance()
                    self._sl_order_id_long = ""
                    self._trailing_placed_long = False
                    # [B] Binance SL 발동 — mark vs entry로 손절 여부 판단
                    if mark > 0 and lp.entry_price > 0 and mark < lp.entry_price:
                        self._consecutive_losses += 1
                    else:
                        self._consecutive_losses = 0
                    if self._consecutive_losses >= _MAX_CONSECUTIVE_LOSSES:
                        self._loss_cooldown_until = time.time() + _LOSS_COOLDOWN_SEC
                        self._consecutive_losses = 0
                    return
            except Exception as e:
                with self._lock:
                    self._state.error_msg = (
                        f"[경보] 롱 청산 실패 + 포지션 상태 조회 불가 — {e}  "
                        "Binance에서 실제 포지션 수동 확인 필요")
                return
            with self._lock:
                self._state.error_msg = f"롱 청산 실패: {result.error}"

    def _close_short(self, reason: str, mark: float = 0.0) -> None:
        with self._lock:
            sp = self._state.short_pos
        if not (sp and sp.state == PositionState.OPEN):
            return
        result = self._client.close_position(
            self._state.symbol, "short", sp.quantity, mark)
        if result.success:
            exit_p = result.fill_price if result.fill_price > 0 else mark
            with self._lock:
                self._state.short_pos   = ShortPosition.close(sp, exit_price=exit_p, exit_reason=reason)
                self._state.last_signal = f"숏 청산({reason})"
            self._invalidate_balance()
            # 청산 완료 후 잔여 Binance SL 주문 취소
            if self._sl_order_id_short:
                self._client.cancel_order(self._state.symbol, self._sl_order_id_short)
                self._sl_order_id_short = ""
            self._trailing_placed_short = False
            # [B] 연속 손실 카운터 갱신 — 문자열이 아니라 실현 손익 기준 판정
            #     (Phase2 BEP 스탑 청산이 손절로 오분류되는 문제 수정)
            with self._lock:
                _closed_s = self._state.short_pos
            _is_loss = bool(_closed_s and _closed_s.pnl_usdt < 0)
            if _is_loss:
                self._beep((220, 220), (165, 220), (110, 460))
                self._consecutive_losses += 1
            else:
                self._beep((784, 100), (784, 100), (1047, 100), (784, 100), (1047, 100), (1319, 380))
                self._consecutive_losses = 0
            if self._consecutive_losses >= _MAX_CONSECUTIVE_LOSSES:
                self._loss_cooldown_until = time.time() + _LOSS_COOLDOWN_SEC
                self._consecutive_losses = 0
            # [B4] 청산 직후 일일 손실 한도 재확인 — _invalidate_balance() 이미 호출됨
            if _is_loss:
                _post_b = self._get_balance()
                if _post_b is not None and RiskManager.should_daily_stop(
                        DailyLossTracker.loss_pct(_post_b)):
                    self.stop()
                    with self._lock:
                        self._state.error_msg = (
                            f"[긴급] 일일 손실 한도(-{MAX_DAILY_LOSS_PCT:.0f}%) 초과 — 엔진 자동 정지")
        else:
            # Binance SL이 먼저 발동해 포지션이 이미 없는 경우 확인
            try:
                actual = self._client.get_position(self._state.symbol)
                if actual is not None and float(actual.get("positionAmt", 1)) == 0.0:
                    with self._lock:
                        self._state.short_pos   = ShortPosition.close(
                            sp, exit_price=mark, exit_reason="Binance SL 발동")
                        self._state.last_signal = "숏 청산(Binance SL 발동)"
                    self._invalidate_balance()
                    self._sl_order_id_short = ""
                    self._trailing_placed_short = False
                    # [B] Binance SL 발동 — mark vs entry로 손절 여부 판단
                    if mark > 0 and sp.entry_price > 0 and mark > sp.entry_price:
                        self._consecutive_losses += 1
                    else:
                        self._consecutive_losses = 0
                    if self._consecutive_losses >= _MAX_CONSECUTIVE_LOSSES:
                        self._loss_cooldown_until = time.time() + _LOSS_COOLDOWN_SEC
                        self._consecutive_losses = 0
                    return
            except Exception as e:
                with self._lock:
                    self._state.error_msg = (
                        f"[경보] 숏 청산 실패 + 포지션 상태 조회 불가 — {e}  "
                        "Binance에서 실제 포지션 수동 확인 필요")
                return
            with self._lock:
                self._state.error_msg = f"숏 청산 실패: {result.error}"

    # ── 효과음 ───────────────────────────────────────────────────
    @staticmethod
    def _beep(*pairs: tuple) -> None:
        """비차단 효과음 재생 — (주파수Hz, 지속ms) 쌍 목록을 데몬 스레드로 순차 재생."""
        def _play():
            for freq, dur in pairs:
                winsound.Beep(freq, dur)
                time.sleep(0.035)
        threading.Thread(target=_play, daemon=True).start()

    # ── Binance SL 주문 관리 헬퍼 ────────────────────────────────
    @staticmethod
    def _round_price_to_tick(price: float, tick_size: float) -> float:
        """tickSize 단위로 가격 반올림 (Binance stopPrice PRICE_FILTER 요건 충족)."""
        if tick_size <= 0:
            return round(price, 8)
        return round(round(price / tick_size) * tick_size, 8)

    def _update_binance_sl_long(self, new_sl_price: float, mark: float = 0.0) -> None:
        """롱 포지션 Binance STOP_MARKET SL 교체 (새 SL 등록 성공 시에만 기존 취소)."""
        sym      = self._state.symbol
        old_id   = self._sl_order_id_long
        tick     = self._client.get_price_precision(sym)
        sl_price = self._round_price_to_tick(new_sl_price, tick)
        if mark > 0 and sl_price >= mark:
            with self._lock:
                self._state.error_msg = f"[경보] 롱 SL 갱신 불가 — SL({sl_price:.4f}) ≥ 마크가({mark:.4f})"
            return
        oid = self._client.place_stop_market(sym, "SELL", sl_price)
        if oid:
            if old_id:
                self._client.cancel_order(sym, old_id)
            self._sl_order_id_long = oid
        else:
            with self._lock:
                self._state.error_msg = "[경보] 롱 SL 갱신 실패 — Binance 연결 확인 필요"

    def _update_binance_sl_short(self, new_sl_price: float, mark: float = 0.0) -> None:
        """숏 포지션 Binance STOP_MARKET SL 교체 (새 SL 등록 성공 시에만 기존 취소)."""
        sym      = self._state.symbol
        old_id   = self._sl_order_id_short
        tick     = self._client.get_price_precision(sym)
        sl_price = self._round_price_to_tick(new_sl_price, tick)
        if mark > 0 and sl_price <= mark:
            with self._lock:
                self._state.error_msg = f"[경보] 숏 SL 갱신 불가 — SL({sl_price:.4f}) ≤ 마크가({mark:.4f})"
            return
        oid = self._client.place_stop_market(sym, "BUY", sl_price)
        if oid:
            if old_id:
                self._client.cancel_order(sym, old_id)
            self._sl_order_id_short = oid
        else:
            with self._lock:
                self._state.error_msg = "[경보] 숏 SL 갱신 실패 — Binance 연결 확인 필요"

    # ── 잔고 캐시 ─────────────────────────────────────────────
    def _get_balance(self) -> "float | None":
        """30초 캐시. 주문 체결 후 _invalidate_balance()로 강제 갱신. 실패 시 None (캐시·타임스탬프 갱신 안 함)."""
        now = time.time()
        if self._balance_ts > 0 and now - self._balance_ts < _BALANCE_TTL_SEC:
            return self._balance_cache
        val = self._client.get_account_balance()
        if val is not None:
            self._balance_cache = val
            self._balance_ts    = now
        return val

    def _sync_position_with_binance(self) -> None:
        """Binance 실제 포지션과 로컬 상태 동기화 (외부 강제 청산 감지용).
        positionAmt == 0.0 이면 로컬 OPEN 포지션을 CLOSED 처리."""
        sym = self._state.symbol
        if not sym:
            return
        try:
            actual = self._client.get_position(sym)
            if actual is None:
                return
            pos_amt = float(actual.get("positionAmt", 0.0))
            with self._lock:
                lp = self._state.long_pos
                sp = self._state.short_pos
            mark = self._client.get_mark_price(sym) or 0.0
            # -16% 미실현 손실 백스탑 — R×2 초과 시 즉시 시장가 청산
            if mark > 0:
                _unreal = float(actual.get("unRealizedProfit", 0.0))
                _bal    = self._get_balance()
                if _bal and _bal > 0 and _unreal / _bal * 100.0 < -16.0:
                    _unreal_pct = _unreal / _bal * 100.0
                    if lp and lp.state == PositionState.OPEN:
                        self._close_long(f"미실현 {_unreal_pct:.1f}% 백스탑", mark)
                    if sp and sp.state == PositionState.OPEN:
                        self._close_short(f"미실현 {_unreal_pct:.1f}% 백스탑", mark)
                    return
            if lp and lp.state == PositionState.OPEN and pos_amt == 0.0:
                with self._lock:
                    self._state.long_pos    = LongPosition.close(
                        lp, exit_price=mark, exit_reason="외부 강제 청산")
                    self._state.last_signal = "롱 강제 청산(외부)"
                self._invalidate_balance()
                if self._sl_order_id_long:
                    self._client.cancel_order(sym, self._sl_order_id_long)
                    self._sl_order_id_long = ""
                self._trailing_placed_long = False
            if sp and sp.state == PositionState.OPEN and pos_amt == 0.0:
                with self._lock:
                    self._state.short_pos   = ShortPosition.close(
                        sp, exit_price=mark, exit_reason="외부 강제 청산")
                    self._state.last_signal = "숏 강제 청산(외부)"
                self._invalidate_balance()
                if self._sl_order_id_short:
                    self._client.cancel_order(sym, self._sl_order_id_short)
                    self._sl_order_id_short = ""
                self._trailing_placed_short = False
        except Exception as e:
            with self._lock:
                self._state.error_msg = f"[경보] 포지션 동기화 실패 — {e}"

    def _invalidate_balance(self) -> None:
        """주문 체결 직후 캐시 무효화 → 다음 진입 시 REST 재조회."""
        self._balance_ts = 0.0

    # ── 지표 데이터 ──────────────────────────────────────────
    def _get_ind_data(self) -> dict:
        if not self._data_provider:
            with self._lock:
                self._state.last_blocked_reason = "데이터 제공자 미연결 — 중단 모듈 확인"
                self._state.last_blocked_side   = ""
            return {}
        try:
            return self._data_provider(self._state.symbol)
        except Exception as e:
            with self._lock:
                self._state.last_blocked_reason = f"지표 데이터 오류: {e}"
                self._state.last_blocked_side   = ""
            return {}
