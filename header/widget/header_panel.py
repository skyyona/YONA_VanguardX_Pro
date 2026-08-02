"""
header/widget/header_panel.py
헤더 GUI 패널 + 서비스 조율 (위젯·코디네이터 통합)
"""
from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable

from core.config import (
    DARK_BG, DARK_PANEL, DARK_TEXT, DIM_TEXT,
    POSITIVE, NEGATIVE, ORANGE, NEUTRAL,
    INITIAL_BUTTON, FORCED_BUTTON, START_BUTTON, STOP_BUTTON,
    HEADER_UPDATE_INTERVAL_SEC,
)
from header.api.binance_client import HeaderBinanceClient
from header.initial_investment.spot_balance import SpotBalance
from header.initial_investment.futures_balance import FuturesBalance
from header.initial_investment.available_balance import AvailableBalance
from header.initial_investment.transfer_service import TransferService
from header.pnl.realtime_pnl import RealtimePnl
from header.pnl.realtime_pnl_amount import RealtimePnlAmount
from header.pnl.total_trading_value import TotalTradingValue
from header.global_trading_session.kst_time import KstTime
from header.global_trading_session.session_classifier import SessionClassifier
from header.global_trading_session.btc_volume_ratio import BtcVolumeRatio
from header.status.app_status import AppStatus
from header.status.update_timer import UpdateTimer
from header.models import (
    HeaderState, HeaderStatus, PnlSnapshot, SessionSnapshot,
    TransferDirection, WalletBalanceResult, WalletQueryStatus,
)

# ── 스타일 상수 ────────────────────────────────────────────────
_ROOT_STYLE   = {"bg": DARK_BG}
_CARD_STYLE   = {"bg": DARK_PANEL, "bd": 1, "relief": "solid", "highlightthickness": 0}
_TITLE_STYLE  = {"bg": DARK_PANEL, "fg": DARK_TEXT, "font": ("Segoe UI", 8, "bold")}
_YONA_STYLE   = {"bg": DARK_PANEL, "fg": DARK_TEXT, "font": ("Segoe UI", 11, "bold")}
_VALUE_STYLE     = {"bg": DARK_PANEL, "fg": DARK_TEXT, "font": ("Segoe UI", 8)}
_PNL_VALUE_STYLE = {"bg": DARK_PANEL, "fg": DARK_TEXT, "font": ("Segoe UI", 11, "bold")}


class HeaderPanel:
    """헤더 모듈의 GUI 패널 겸 서비스 코디네이터."""

    def __init__(self, root: tk.Toplevel | tk.Tk) -> None:
        self._root = root
        self._root.configure(**_ROOT_STYLE)

        # ── 서비스 인스턴스 ──────────────────────────────────
        self._client   = HeaderBinanceClient()
        self._spot_bal = SpotBalance(self._client)
        self._fut_bal  = FuturesBalance(self._client)
        self._avail_bal = AvailableBalance(self._client)
        self._transfer = TransferService(self._client)
        self._total_val = TotalTradingValue()
        self._kst_time  = KstTime()
        self._session   = SessionClassifier()
        self._btc_vol   = BtcVolumeRatio(self._client)
        self._status    = AppStatus()
        self._timer     = UpdateTimer(HEADER_UPDATE_INTERVAL_SEC, self._tick)

        # ── GUI 빌드 (상/하 패딩 최소화 → 중단/하단 공간 확보) ──
        self._frame = tk.Frame(root, bg=DARK_PANEL, pady=1)
        self._frame.pack(fill="both", expand=True, padx=8, pady=1)
        self._cards = [tk.Frame(self._frame, **_CARD_STYLE, padx=8, pady=1) for _ in range(7)]
        self._build_components()
        self._grid_layout()

        self._last_state = self._build_state()

    # ── 공개 인터페이스 ──────────────────────────────────────
    def initialize(self) -> None:
        self._last_state = self._build_state()
        self.render()

    def start(self) -> None:
        self._status.set_running()
        self._timer.start()
        threading.Thread(target=self._tick, daemon=True).start()

    def stop(self) -> None:
        self._status.set_idle()
        self._timer.stop()
        self._tick()

    def forced_liquidation(self) -> None:
        """포지션 강제 청산 전용 — 헤더는 계속 작동. bottom_panel이 직접 처리."""
        pass

    def bind_actions(
        self,
        on_set_initial_investment: Callable[[], None],
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_forced_liquidation: Callable[[], None],
    ) -> None:
        self._btn_invest.configure(command=on_set_initial_investment)
        self._btn_start.configure(command=on_start)
        self._btn_stop.configure(command=on_stop)
        self._btn_forced.configure(command=on_forced_liquidation)

    # ── 잔고 조회 (다이얼로그용) ─────────────────────────────
    def get_spot_balance(self) -> WalletBalanceResult:
        return self._spot_bal.fetch()

    def get_futures_balance(self) -> WalletBalanceResult:
        return self._fut_bal.fetch()

    def get_available_balance(self) -> WalletBalanceResult:
        return self._avail_bal.fetch()

    def do_transfer_bg(
        self, transfer_amount: float, direction: TransferDirection
    ) -> WalletBalanceResult:
        """백그라운드 스레드 전용 — API 호출만 수행 (Tkinter 위젯 접근 없음)."""
        return self._transfer.apply_initial_investment(transfer_amount, direction)

    def on_transfer_done(self) -> None:
        """이체 완료 후 헤더 UI 갱신."""
        threading.Thread(target=self._tick, daemon=True).start()

    def get_state(self) -> HeaderState:
        return self._last_state

    # ── 렌더링 ──────────────────────────────────────────────
    def render(self) -> None:
        state  = self._last_state
        color  = self._status.color()
        self._lbl_yona_top.configure(fg=color)
        self._lbl_yona_bot.configure(fg=color)
        _status_map = {
            HeaderStatus.RUNNING: ("LIVE",  POSITIVE),
            HeaderStatus.IDLE:    ("IDLE",  DIM_TEXT),
            HeaderStatus.ERROR:   ("ERROR", NEGATIVE),
        }
        _stxt, _scol = _status_map.get(state.status, ("IDLE", DIM_TEXT))
        self._lbl_status.configure(text=_stxt, fg=_scol)

        if state.status == HeaderStatus.IDLE:
            self._btn_invest.configure(state="disabled", bg="#2A2A2A", disabledforeground="#555555")
            self._lbl_invest_val.configure(text="—", fg=NEUTRAL)
            self._lbl_pnl_pct.configure(text="—", fg=NEUTRAL)
            self._lbl_pnl_amt.configure(text="—", fg=NEUTRAL)
            self._lbl_total.configure(text="—", fg=NEUTRAL)
        elif state.status == HeaderStatus.ERROR:
            # API 통신 오류 — 버튼은 활성 유지, 수치는 오류 표시
            self._btn_invest.configure(state="normal", bg=INITIAL_BUTTON, fg="#000000")
            self._lbl_invest_val.configure(
                text=f"{state.initial_investment_usdt:.2f} USDT", fg=NEUTRAL)
            self._lbl_pnl_pct.configure(text="통신 오류", fg=NEGATIVE)
            self._lbl_pnl_amt.configure(text="통신 오류", fg=NEGATIVE)
            self._lbl_total.configure(text="재연결 중...", fg=ORANGE)
        else:
            self._btn_invest.configure(state="normal", bg=INITIAL_BUTTON, fg="#000000")
            self._lbl_invest_val.configure(
                text=f"{state.initial_investment_usdt:.2f} USDT", fg=NEUTRAL)
            pnl_col = POSITIVE if state.pnl.pnl_amount_usdt > 0 else (NEGATIVE if state.pnl.pnl_amount_usdt < 0 else NEUTRAL)
            self._lbl_pnl_pct.configure(text=f"{state.pnl.pnl_percent:.2f}%", fg=pnl_col)
            self._lbl_pnl_amt.configure(text=f"{state.pnl.pnl_amount_usdt:.2f} USDT", fg=pnl_col)
            self._lbl_total.configure(text=f"{state.pnl.total_trading_value_usdt:.2f} USDT", fg=pnl_col)

        self._lbl_kst.configure(text=state.session.kst_datetime_label)
        self._lbl_session.configure(text=state.session.session_status_label)
        hint = state.session.volume_hint
        vol_col = ORANGE if hint == "very_high" else (POSITIVE if hint == "high" else (NEGATIVE if hint == "low" else NEUTRAL))
        self._lbl_vol.configure(text=f"  {state.session.volume_label}", fg=vol_col)

    # ── 내부 ────────────────────────────────────────────────
    def _tick(self) -> None:
        current = self._status.get()
        if current in (HeaderStatus.RUNNING, HeaderStatus.ERROR):
            result = self._client.fetch_futures_total_balance_with_status()
            if result.status == WalletQueryStatus.OK:
                # 정상 응답: ERROR였다면 RUNNING으로 자동 복구
                if current == HeaderStatus.ERROR:
                    self._status.set_running()
                self._total_val.update(result.value_usdt)
            elif result.status == WalletQueryStatus.COMM_ERROR:
                # 통신 오류: ERROR 상태로 전환 (수치 갱신 중단)
                self._status.set_error()
            # NO_API_KEY는 키 미설정 — 상태 변경 없이 현재 유지
        self._last_state = self._build_state()
        try:
            self._root.after(0, self.render)
        except tk.TclError:
            pass

    def _build_state(self) -> HeaderState:
        initial = self._transfer.get_initial_investment()
        total   = self._total_val.get()
        pnl = PnlSnapshot(
            pnl_percent=RealtimePnl.calculate(initial, total),
            pnl_amount_usdt=RealtimePnlAmount.calculate(initial, total),
            total_trading_value_usdt=round(total, 4),
        )
        now  = self._kst_time.now()
        vol_label, vol_hint = self._btc_vol.fetch() if self._status.get() == HeaderStatus.RUNNING else ("—", "normal")
        session = SessionSnapshot(
            kst_datetime_label=self._kst_time.label(),
            session_status_label=self._session.classify(now.time()),
            volume_label=vol_label,
            volume_hint=vol_hint,
        )
        return HeaderState(
            status=self._status.get(),
            initial_investment_usdt=initial,
            pnl=pnl,
            session=session,
        )

    def _build_components(self) -> None:
        c = self._cards
        self._lbl_yona_top = tk.Label(c[0], text="YONA", justify="center", anchor="center", **_YONA_STYLE)
        self._lbl_bot_row   = tk.Frame(c[0], bg=DARK_PANEL)
        self._lbl_bot_inner = tk.Frame(self._lbl_bot_row, bg=DARK_PANEL)
        self._lbl_yona_bot  = tk.Label(self._lbl_bot_inner, text="Vanguard X Pro", anchor="w", **_TITLE_STYLE)
        self._lbl_status    = tk.Label(self._lbl_bot_inner, text="IDLE", anchor="w",
                                       bg=DARK_PANEL, fg=DIM_TEXT, font=("Segoe UI", 8, "bold"))

        self._btn_invest    = tk.Button(c[1], text="Initial Investment",
                                        bg=INITIAL_BUTTON, activebackground=INITIAL_BUTTON,
                                        fg="#000000", activeforeground="#000000",
                                        relief="flat", padx=6, pady=1,
                                        font=("Segoe UI", 8, "bold"))
        self._lbl_invest_val = tk.Label(c[1], text="0.00 USDT", **_VALUE_STYLE)

        tk.Label(c[2], text="Real-Time P&L", **_TITLE_STYLE).grid(row=0, column=0, sticky="ew", pady=(1,1))
        self._lbl_pnl_pct = tk.Label(c[2], text="0.00%", **_VALUE_STYLE)

        tk.Label(c[3], text="Real-Time P&L Amount", **_TITLE_STYLE).grid(row=0, column=0, sticky="ew", pady=(1,1))
        self._lbl_pnl_amt = tk.Label(c[3], text="0.00 USDT", **_VALUE_STYLE)

        tk.Label(c[4], text="Total Trading Value", **_TITLE_STYLE).grid(row=0, column=0, sticky="ew", pady=(1,1))
        self._lbl_total = tk.Label(c[4], text="0.00 USDT", **_VALUE_STYLE)

        tk.Label(c[5], text="Global trading session", **_TITLE_STYLE).grid(row=0, column=0, sticky="ew", pady=(1,1))
        self._sess_row  = tk.Frame(c[5], bg=DARK_PANEL)
        self._lbl_kst   = tk.Label(self._sess_row, text="0000-00-00 AM 00:00:00 KST", **_VALUE_STYLE)
        self._lbl_session = tk.Label(self._sess_row, text="No Active Session", **_VALUE_STYLE)
        self._lbl_vol   = tk.Label(self._sess_row, text="", **_VALUE_STYLE)

        # [forced liquidation]: 다른 카드의 제목 라벨과 동일한 높이로 통일
        # font, pady를 _TITLE_STYLE에 맞춰 소형화 → 구조적 일관성 확보
        self._btn_forced = tk.Button(c[6], text="forced liquidation",
                                     bg=FORCED_BUTTON, activebackground=FORCED_BUTTON,
                                     fg="#ffffff", activeforeground="#ffffff",
                                     relief="flat", padx=6, pady=1,
                                     font=("Segoe UI", 8, "bold"))
        # btn_row를 고정 높이 래퍼로 감싸 — 텍스트 크기 유지하며 버튼 높이 제어
        # grid_propagate(False): grid 환경에서 height 고정 (pack_propagate와 다름)
        self._btn_row_wrap = tk.Frame(c[6], bg=DARK_PANEL, height=18)
        self._btn_row_wrap.grid_propagate(False)   # grid 환경에서 18px 고정
        self._btn_row   = tk.Frame(self._btn_row_wrap, bg=DARK_PANEL)
        self._btn_start = tk.Button(self._btn_row, text="START",
                                    bg=START_BUTTON, activebackground=START_BUTTON,
                                    fg="#000000", activeforeground="#000000",
                                    relief="flat", padx=8, pady=0,
                                    font=("Segoe UI", 8, "bold"))
        self._btn_stop  = tk.Button(self._btn_row, text="STOP",
                                    bg=STOP_BUTTON, activebackground=STOP_BUTTON,
                                    fg="#ffffff", activeforeground="#ffffff",
                                    relief="flat", padx=8, pady=0,
                                    font=("Segoe UI", 8, "bold"))

    def _grid_layout(self) -> None:
        for i, card in enumerate(self._cards):
            card.grid(row=0, column=i, sticky="ew", padx=4, pady=1)
            self._frame.grid_columnconfigure(i, weight=1)

        c = self._cards
        self._lbl_yona_top.grid(row=0, column=0, sticky="ew", pady=(2,1))
        self._lbl_bot_row.grid(row=1, column=0, sticky="ew", pady=(1,2))
        self._lbl_bot_inner.pack(expand=True)
        self._lbl_yona_bot.pack(side="left")
        self._lbl_status.pack(side="left", padx=(6, 0))
        c[0].grid_columnconfigure(0, weight=1)

        self._btn_invest.grid(row=0, column=0, sticky="ew", pady=(1,1))
        self._lbl_invest_val.grid(row=1, column=0, sticky="ew", pady=(0,1))
        c[1].grid_columnconfigure(0, weight=1)

        self._lbl_pnl_pct.grid(row=1, column=0, sticky="ew", pady=(0,1))
        c[2].grid_columnconfigure(0, weight=1)

        self._lbl_pnl_amt.grid(row=1, column=0, sticky="ew", pady=(0,1))
        c[3].grid_columnconfigure(0, weight=1)

        self._lbl_total.grid(row=1, column=0, sticky="ew", pady=(0,1))
        c[4].grid_columnconfigure(0, weight=1)

        self._sess_row.grid(row=1, column=0, sticky="ew", pady=(0,1))
        self._lbl_kst.grid(row=0, column=0, sticky="w")
        self._lbl_session.grid(row=0, column=1, sticky="w", padx=(8,0))
        self._lbl_vol.grid(row=0, column=2, sticky="e")
        self._sess_row.grid_columnconfigure(0, weight=1)
        self._sess_row.grid_columnconfigure(1, weight=1)
        self._sess_row.grid_columnconfigure(2, weight=1)
        c[5].grid_columnconfigure(0, weight=1)

        self._btn_forced.grid(row=0, column=0, sticky="ew", pady=(1,1))
        self._btn_row_wrap.grid(row=1, column=0, sticky="ew", pady=(0,1))
        # btn_row: 래퍼(18px) 전체 채움
        self._btn_row.pack(fill="both", expand=True)
        # START/STOP: 18px 공간을 nsew로 채움 → 텍스트 세로 중앙(anchor=center 기본값)
        self._btn_start.grid(row=0, column=0, sticky="nsew")
        self._btn_stop.grid(row=0, column=1, sticky="nsew")
        self._btn_row.grid_columnconfigure(0, weight=1)
        self._btn_row.grid_columnconfigure(1, weight=1)
        self._btn_row.grid_rowconfigure(0, weight=1)   # row 높이 동적 채움 → 텍스트 중앙
        c[6].grid_columnconfigure(0, weight=1)
