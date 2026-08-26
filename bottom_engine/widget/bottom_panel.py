"""
YONA VanguardX Pro — Bottom Engine Module
Long Position Engine + Short Position Engine
단일 API 키 · 추세 추종 전용 · Stoch RSI 신호 기반 자동 매매
"""
from __future__ import annotations
import json
import tkinter as tk
from tkinter import ttk
import random
import math
import time
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

try:
    from middle.widget.shared_context import get_ind, request_detail, generate_ohlcv
    from bottom_engine.engine_core.fourtf_consensus import FourTFConsensus
except ImportError:
    def get_ind(_s: str) -> dict: return {}                                # type: ignore[misc]
    def request_detail(_s: str) -> None: pass                              # type: ignore[misc]
    def generate_ohlcv(_s: str, n: int = 60, interval: str = "5m") -> list: return []  # type: ignore[misc]
    class FourTFConsensus:                           # type: ignore[misc]
        @classmethod
        def evaluate(cls, _d: dict):
            from types import SimpleNamespace
            return SimpleNamespace(long_consensus=False, short_consensus=False,
                                   aligned_long=0, aligned_short=0, details={})

try:
    from bottom_engine.engine_core.trading_engine import TradingEngine
    from bottom_engine.strategy_settings.strategy_loader import StrategyLoader
    from bottom_engine.models import PositionState, ProhibitionFlags
    _HAS_ENGINE = True
except ImportError:
    TradingEngine    = None   # type: ignore[misc,assignment]
    StrategyLoader   = None   # type: ignore[misc,assignment]
    ProhibitionFlags = None   # type: ignore[misc,assignment]
    class PositionState:    # type: ignore[misc]
        OPEN = "open"
    _HAS_ENGINE = False

try:
    from bottom_engine.strategy_settings.realtrade_strategy_sort_by import get_mode_config as _get_mode_cfg
except ImportError:
    def _get_mode_cfg(m: str):   # type: ignore[misc]
        from types import SimpleNamespace
        return SimpleNamespace(
            direction_bias="both", k_long_max=20.0, k_short_min=80.0,
            quality_grade_req=None, volume_mult=None,
            atr_min=0.3, atr_max=8.0, requires_swing=False, macro_ema=False)

try:
    from bottom_engine.backtest.historical_data_loader import HistoricalDataLoader
    from bottom_engine.backtest.backtest_runner import BacktestRunner
    _HAS_BACKTEST = True
except ImportError:
    HistoricalDataLoader = None  # type: ignore[misc,assignment]
    BacktestRunner       = None  # type: ignore[misc,assignment]
    _HAS_BACKTEST = False

import threading as _threading

# ── 색상 팔레트 ──────────────────────────────────────────────────
from core.config import (
    DARK_BG, DARK_PANEL, DARK_HEADER, DARK_ROW_ODD, DARK_ROW_EVN,
    DARK_TEXT, DIM_TEXT, ACCENT_BLUE, POSITIVE, NEGATIVE, ORANGE,
    YELLOW, LONG_HDR_BG, SHORT_HDR_BG,
)

from bottom_engine.main_header.header_ui.header_ui_mixin import HeaderUiMixin
from bottom_engine.main_header.symbol_set_backtest.pop_set_ui.strategy_popup_mixin import StrategyPopupMixin
from bottom_engine.ctr_ctrl_sess.center_ctrl_mixin import CenterCtrlMixin


# ── 거래 내역 영속화 경로 (C: 보완 2) ────────────────────────────
_TRADE_HISTORY_PATH = Path(__file__).resolve().parents[2] / "trade_history.json"


def _dedup_hist(records: list) -> list:
    """entry_time+exit_time 기준 중복 제거 (첫 등장 우선)."""
    seen: set[tuple] = set()
    out: list = []
    for r in records:
        key = (r.get("entry_time", 0.0), r.get("exit_time", 0.0))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out

_BASE_SL,    _BASE_TRAIL = 2.5,  1.5


# ══════════════════════════════════════════════════════════════════
class BottomModuleMockup(CenterCtrlMixin, StrategyPopupMixin, HeaderUiMixin, tk.Frame):
    def __init__(self, master: tk.Misc,
                 shared_sym: tk.StringVar | None = None,
                 shared_sort_mode: tk.StringVar | None = None) -> None:
        super().__init__(master, bg=DARK_HEADER)
        # Toplevel 전용 메서드(title/geometry/minsize) 제거 — 단일 창 통합 GUI

        self._trading_active  = False
        self._strategy_ready  = False          # 전략 설정 완료 여부
        self._applied_params  : dict | None = None   # 확정 적용된 파라미터 값
        self._prohibited_vars : dict[str, tk.BooleanVar] = {}   # 절대 거래 금지 체크 상태
        self._use_macro_var   = tk.BooleanVar(value=True)        # 거시적 추세 연동 여부
        self._funds_var = tk.IntVar(value=100)
        self._lev_var   = tk.IntVar(value=10)
        self._sl_var       = tk.DoubleVar(value=_BASE_SL)
        self._trail_var    = tk.DoubleVar(value=_BASE_TRAIL)
        self._strategy_btn  : tk.Button | None = None
        self._strategy_msg  : tk.Label  | None = None
        self._funds_lev_btn : tk.Button | None = None
        self._sl_trail_btn  : tk.Button | None = None
        self._applied_sort_mode: str = "24h Ticker"

        # middle module 과 공유하는 심볼 변수 — 없으면 독립 동작
        self._shared_sym = shared_sym if shared_sym is not None \
                           else tk.StringVar(self, value="")
        self._shared_sym.trace_add("write", self._on_symbol_received)

        # middle module 과 공유하는 Sort by 모드 변수 — 없으면 독립 동작
        self._shared_sort_mode = shared_sort_mode

        # ── 중앙 컨트롤 세션 — 실데이터 폴링 위젯 참조 ──────────
        self._pos_ind:        dict            = {}
        self._pos_glow:       dict            = {}
        self._macro_f:        tk.Frame | None = None
        self._macro_tf_row:   tk.Frame | None = None
        self._macro_ico_lbl:  tk.Label | None = None
        self._macro_tf_lbls:  dict            = {}
        self._tf_anim:        dict            = {}
        self._tf_tick_fn:     object          = None
        self._tf_ticking:     bool            = False
        self._app_started:    bool            = False
        self._center_running: bool            = False
        self._pnl_running:    bool            = False  # 1초 P&L 폴링 루프 플래그
        self._long_panel:     dict            = {}   # 롱 패널 위젯 참조
        self._short_panel:    dict            = {}   # 숏 패널 위젯 참조
        self._exit_cache:     dict            = {}   # {side: {entry,exit,pnl,reason,until}}
        self._param_info_lbl: tk.Label | None = None  # 전략 파라미터 요약 라벨
        self._last_sig_lbl:   tk.Label | None = None  # 엔진 최근 액션 라벨
        self._long_trade_history:  list[dict] = []   # 롱 거래 완료 내역
        self._short_trade_history: list[dict] = []   # 숏 거래 완료 내역
        self._recorded_trades:     set[tuple]  = set()   # (side, entry_time, exit_time) 중복 방지
        self._load_trade_history()  # [C] 파일에서 이전 거래 내역 복원 (보완 2)

        # ── 잔고 UI 상태 ──────────────────────────────────────────
        self._ui_balance:      float | None = None   # 마지막 확인된 USDT 가용 잔고
        self._prev_long_open:  bool         = False   # 직전 poll_pnl 롱 OPEN 여부
        self._prev_short_open: bool         = False   # 직전 poll_pnl 숏 OPEN 여부

        # ── 거래 엔진 인스턴스 ────────────────────────────────────
        self._engine: "TradingEngine | None" = (
            TradingEngine(data_provider=get_ind, sel_refresher=request_detail)
            if _HAS_ENGINE else None
        )

        # ── 좌우 테두리 선 (콘텐츠보다 먼저 pack → 전체 높이 확보) ──
        tk.Frame(self, bg=DARK_HEADER, width=8).pack(side="left",  fill="y")
        tk.Frame(self, bg=DARK_HEADER, width=8).pack(side="right", fill="y")

        self._build_strategy_header()
        self._build_engine_panels()

    # ══════════════════════════════════════════════════════════════
    # 1단 — 전략 헤더 바 (1행 4섹션)
    # ══════════════════════════════════════════════════════════════
    def _toggle_trading(self) -> None:
        if not _HAS_ENGINE:
            return
        self._trading_active = not self._trading_active
        if self._trading_active:
            self._ui_balance = None   # 이전 세션 잔고 초기화
            ok = True
            if self._engine is not None:
                ok = self._engine.start()
            if ok:
                self._trade_btn.configure(
                    text="  거래  정지  ",
                    bg="#2A0A0F", fg=NEGATIVE,
                    activebackground="#3A0A14", activeforeground=NEGATIVE)
                self._clear_btn.configure(state="disabled")
                self._update_last_signal_lbl()   # start() 확인 잔고 즉시 표시
            else:
                # API 키 오류·잔고 부족 등 start() 실패 → 즉시 롤백
                self._trading_active = False
                self._trade_btn.configure(
                    text="  거래 활성화  ",
                    bg="#0A2A12", fg=POSITIVE,
                    activebackground="#0A3A18", activeforeground=POSITIVE)
                if self._engine is not None:
                    err = self._engine.get_state().error_msg
                    if err:
                        from tkinter import messagebox as _mb
                        _mb.showwarning("거래 시작 불가", err)
        else:
            if self._engine is not None and self._engine.has_open_positions():
                # 포지션 보유 중 → 강제 청산 후 정지
                self._trade_btn.configure(
                    text="  청산 중...  ",
                    bg="#2A1A00", fg=YELLOW,
                    activebackground="#2A1A00", activeforeground=YELLOW,
                    state="disabled")

                def _on_stop_success():
                    if self._engine is not None:
                        self._engine.stop()
                    self._clear_symbol()

                def _on_stop_fail(results: dict):
                    self._trading_active = True
                    self._trade_btn.configure(
                        text="  거래  정지  ",
                        bg="#2A0A0F", fg=NEGATIVE,
                        activebackground="#3A0A14", activeforeground=NEGATIVE,
                        state="normal")
                    self._on_force_close_done(results)

                def _bg():
                    results = self._engine.force_close_all()
                    any_fail = (results.get("long") == "실패"
                                or results.get("short") == "실패")
                    if any_fail:
                        self.after(0, lambda: _on_stop_fail(results))
                    else:
                        self.after(0, _on_stop_success)

                _threading.Thread(target=_bg, daemon=True).start()
                return
            # 포지션 없음 → 즉시 정지
            if self._engine is not None:
                self._engine.stop()
            self._clear_symbol()
            return
        self._update_engine_panels()

    # ─── middle module 으로부터 심볼 수신 ────────────────────────
    def _on_symbol_received(self, *_) -> None:
        sym = self._shared_sym.get()
        if sym:
            # 심볼 라벨 갱신 + 플래시
            self._sym_lbl.configure(text=sym, fg=POSITIVE, bg="#0A2A12")
            self.after(600, lambda: self._sym_lbl.configure(bg=DARK_HEADER))
            # [Clear] 활성
            self._clear_btn.configure(
                state="normal", fg=NEGATIVE,
                bg="#2A1010", activebackground="#3A1414")
            # [🧠 전략설정] 활성 (심볼 배정 시 활성)
            self._strategy_btn.configure(
                state="normal", cursor="hand2",
                bg=DARK_PANEL, fg=ACCENT_BLUE,
                activebackground="#252525", activeforeground=ACCENT_BLUE)
            # [거래 활성화]: 전략 설정까지 완료된 경우에만 활성
            if self._strategy_ready:
                self._trade_btn.configure(
                    state="normal", cursor="hand2",
                    bg="#0A2A12", fg=POSITIVE,
                    activebackground="#0A3A18", activeforeground=POSITIVE)
            # ── 중앙 컨트롤 세션 실데이터 폴링 + 4TF 차트 시작 ──
            request_detail(sym)
            if not self._center_running:
                self._center_running = True
                self.after(500, self._poll_center)
            if not self._tf_ticking and self._tf_tick_fn is not None:
                self._tf_ticking = True
                self.after(100, self._tf_tick_fn)
            if not self._pnl_running:
                self._pnl_running = True
                self.after(1000, self._poll_pnl)
            self.after(1500, self._update_price_charts)   # 첫 배정 즉시 로드
        else:
            # 미배치 상태 전체 초기화
            self._sym_lbl.configure(text="— 미배치 —",
                                     fg=DIM_TEXT, bg=DARK_HEADER)
            self._clear_btn.configure(
                state="disabled", fg="#888888",
                bg="#2A1A1A", activebackground="#2A1A1A")
            # [🧠 전략설정] 비활성
            self._strategy_btn.configure(
                state="disabled", cursor="arrow",
                bg="#252525", fg="#888888",
                activebackground="#303030", activeforeground=DARK_TEXT)
            # 전략 상태 초기화
            self._strategy_ready = False
            self._strategy_msg.configure(
                text="  — 전략 미설정 —  ", fg=DIM_TEXT)
            # 거래 중이면 정지
            if self._trading_active:
                self._trading_active = False
                self._trade_btn.configure(text="  거래 활성화  ")
            # [거래 활성화] 비활성
            self._trade_btn.configure(
                state="disabled", cursor="arrow",
                bg="#252525", fg="#888888",
                activebackground="#303030", activeforeground=DARK_TEXT)
            # ── 중앙 컨트롤 세션 정지 + 초기화 ──────────────
            self._center_running = False
            self._reset_center()

    def _restore_strategy_vars(self, sort_mode: str) -> str | None:
        """sort_mode에 저장된 전략 설정을 UI vars에 복원한다. consensus_mode 반환."""
        if StrategyLoader is None:
            return None
        loaded = StrategyLoader.load(sort_mode)
        if loaded is None:
            return None
        self._funds_var.set(int(loaded.funds_pct))
        self._lev_var.set(int(loaded.leverage))
        self._sl_var.set(float(loaded.stop_loss))
        self._trail_var.set(float(loaded.trail_stop))
        self._use_macro_var.set(bool(loaded.use_macro))
        for k, v in loaded.prohibition.to_dict().items():
            if k in self._prohibited_vars:
                self._prohibited_vars[k].set(bool(v))
            else:
                self._prohibited_vars[k] = tk.BooleanVar(value=bool(v))
        return loaded.consensus_mode  # [B-4] 호출부에서 _consensus_var 갱신용

    # ══════════════════════════════════════════════════════════════
    # 전략 설정 & 백테스팅 팝업창 (단일 페이지)
    # ══════════════════════════════════════════════════════════════
    # ─── 전략 확정 ───────────────────────────────────────────────
    def _confirm_strategy(self, win: tk.Toplevel,
                          sort_mode: str = "24h Ticker",
                          consensus_mode: str = "4/4") -> None:
        # ── 방안 A: 포지션 보유 중 전략 전체 재설정 차단 ──────────
        if self._engine is not None and self._engine.has_open_positions():
            from tkinter import messagebox as _mb
            _mb.showwarning(
                "포지션 보유 중",
                "현재 포지션이 열려 있어 전략을 재설정할 수 없습니다.\n"
                "포지션 청산 후 재시도하세요.")
            return
        funds, lev, sl, trail = self._current_params()
        prohibited = {k: v.get() for k, v in self._prohibited_vars.items()}
        self._applied_params = {"funds": funds, "leverage": lev,
                                "sl": sl, "trail": trail,
                                "use_macro": self._use_macro_var.get(),
                                "prohibited": prohibited,
                                "consensus_mode": consensus_mode}
        self._applied_sort_mode = sort_mode
        self._strategy_ready = True
        self._strategy_msg.configure(
            text=f"  ✓ 전략설정완료   {sort_mode}   {consensus_mode}  ", fg=POSITIVE)
        self._trade_btn.configure(
            state="normal", cursor="hand2",
            bg="#0A2A12", fg=POSITIVE,
            activebackground="#0A3A18", activeforeground=POSITIVE)
        self._funds_lev_btn.configure(
            text=f"  ✓  Funds {funds}%   |   {lev}x  ",
            bg="#0D2A1A", fg=POSITIVE,
            activebackground="#0A3A18", activeforeground=POSITIVE)
        self._sl_trail_btn.configure(
            text=f"  ✓  SL {sl:.1f}%   |   Trail {trail:.1f}%  ",
            bg="#0D2A1A", fg=POSITIVE,
            activebackground="#0A3A18", activeforeground=POSITIVE)

        # ── TradingEngine 파라미터 반영 ───────────────────────────
        # sort_mode: 전략 창에서 사용자가 선택한 Sort by 모드 (람다로 전달)
        if self._engine is not None and StrategyLoader is not None:
            try:
                params = StrategyLoader.save_from_applied(
                    self._applied_params, sort_mode)
                sym = self._shared_sym.get()
                if sym:
                    self._engine.configure(params, sym)
            except Exception as e:
                from tkinter import messagebox as _mb
                _mb.showerror(
                    "전략 적용 오류",
                    f"엔진 설정 중 오류가 발생했습니다:\n{e}\n\n전략을 다시 설정해 주세요.")
                self._strategy_ready = False
                self._strategy_msg.configure(
                    text="  — 설정 오류, 재설정 필요 —  ", fg=NEGATIVE)
                self._trade_btn.configure(
                    state="disabled",
                    bg="#252525", fg="#888888",
                    activebackground="#303030", activeforeground=DARK_TEXT,
                    cursor="arrow")
                return

        self._update_param_info_lbl()
        win.destroy()

    # ══════════════════════════════════════════════════════════════
    # 헤더 버튼 팝업 — Designated Funds & Applied Leverage
    # ══════════════════════════════════════════════════════════════
    # ══════════════════════════════════════════════════════════════
    # 3단 — 엔진 패널 (Long | Short)
    # ══════════════════════════════════════════════════════════════
    def _build_engine_panels(self) -> None:
        ef = tk.Frame(self, bg=DARK_BG)
        ef.pack(fill="both", expand=True)

        # 1열·3열의 폭이 내부 텍스트 길이(활성/비활성 상태 문구 등)에 따라
        # 서로 달라지는 것을 막기 위해, pack 의 자동 분배 대신 place 로
        # "(전체 - 중앙고정폭 - 구분선×2) ÷ 2" 를 직접 계산해 항상 동일하게 고정한다.
        CENTER_W = 360
        DIV_W    = 2

        self._long_f   = tk.Frame(ef, bg=DARK_BG)
        div_l          = tk.Frame(ef, bg="#333333")
        self._center_f = tk.Frame(ef, bg=DARK_BG)
        div_r          = tk.Frame(ef, bg="#333333")
        self._short_f  = tk.Frame(ef, bg=DARK_BG)

        def _layout_engine_panels(event=None) -> None:
            W = ef.winfo_width()
            H = ef.winfo_height()
            if W < 80 or H < 10:
                return
            side_w = max(0, (W - CENTER_W - DIV_W * 2) // 2)
            x = 0
            self._long_f.place(x=x, y=0, width=side_w, height=H)
            x += side_w
            div_l.place(x=x, y=0, width=DIV_W, height=H)
            x += DIV_W
            self._center_f.place(x=x, y=0, width=CENTER_W, height=H)
            x += CENTER_W
            div_r.place(x=x, y=0, width=DIV_W, height=H)
            x += DIV_W
            self._short_f.place(x=x, y=0, width=W - x, height=H)
        ef.bind("<Configure>", _layout_engine_panels)

        # 초기 상태: 거래 활성화 전까지 양쪽 모두 비활성
        _long_active  = False
        _short_active = False

        self._build_engine(
            parent       = self._long_f,
            side         = "long",
            title        = "Long  Position",
            hdr_bg       = LONG_HDR_BG,
            hdr_fg       = POSITIVE,
            engine_state = "🟢  4TF 불리시 정렬 — 롱 엔진 활성",
            state_col    = POSITIVE,
            status_lbl   = ("4TF K>D 정렬 완료  |  진입 대기" if _long_active
                            else "4TF 불리시 대기  |  엔진 대기 중"),
            status_col   = POSITIVE if _long_active else DIM_TEXT,
            pred_txt     = ("1m 과매도 진입 신호 대기 중" if _long_active
                            else "롱 엔진 대기  —  전략 우선순위 외"),
            pred_col     = POSITIVE if _long_active else DIM_TEXT,
            pnl_pct      = 2.3 if _long_active else 0.0,
            total_usdt   = 0.152 if _long_active else 0.000,
            is_active    = _long_active,
        )
        self._build_center_panel(self._center_f)
        self._build_engine(
            parent       = self._short_f,
            side         = "short",
            title        = "Short  Position",
            hdr_bg       = SHORT_HDR_BG,
            hdr_fg       = NEGATIVE,
            engine_state = "🔴  4TF K<D 정렬 — 숏 엔진 활성",
            state_col    = NEGATIVE,
            status_lbl   = ("4TF K<D 정렬 완료  |  진입 대기" if _short_active
                            else "4TF K<D 미정렬  |  잠금 대기 중"),
            status_col   = NEGATIVE if _short_active else DIM_TEXT,
            pred_txt     = ("1m 과매수 진입 신호 대기 중" if _short_active
                            else "숏 엔진 대기  —  전략 우선순위 외"),
            pred_col     = NEGATIVE if _short_active else DIM_TEXT,
            pnl_pct      = -1.4 if _short_active else 0.0,
            total_usdt   = 0.098 if _short_active else 0.000,
            is_active    = _short_active,
        )

    # ──────────────────────────────────────────────────────────────
    def _build_engine(self, parent, side, title, hdr_bg, hdr_fg,
                      engine_state, state_col,
                      status_lbl, status_col,
                      pred_txt, pred_col, pnl_pct, total_usdt,
                      is_active: bool) -> None:

        pnl_col = POSITIVE if pnl_pct > 0 else (NEGATIVE if pnl_pct < 0 else DIM_TEXT)

        # ── ① 푸터 (bottom 먼저 pack) ─────────────────────────────
        footer = tk.Frame(parent, bg=DARK_HEADER, pady=5)
        footer.pack(side="bottom", fill="x")
        tk.Frame(footer, bg="#333333", height=1).pack(fill="x")
        foot_body = tk.Frame(footer, bg=DARK_HEADER)
        foot_body.pack(fill="x", pady=(4, 0))

        lfoot = tk.Frame(foot_body, bg=DARK_HEADER)
        lfoot.pack(side="left", fill="x", expand=True)
        _foot_gain_title_lbl = tk.Label(lfoot, text="Total Slot Gain / Loss",
                 bg=DARK_HEADER, fg=DIM_TEXT,
                 font=("Segoe UI", 7, "bold"))
        _foot_gain_title_lbl.pack()
        sign = "+" if total_usdt > 0 else ""
        _foot_usdt_lbl = tk.Label(lfoot, text=f"{sign}{total_usdt:.3f}   USDT",
                 bg=DARK_HEADER, fg=pnl_col,
                 font=("Consolas", 10, "bold"))
        _foot_usdt_lbl.pack()

        tk.Frame(foot_body, bg="#3A3A3A", width=1).pack(side="left", fill="y", padx=6)

        rfoot = tk.Frame(foot_body, bg=DARK_HEADER)
        rfoot.pack(side="left", fill="x", expand=True)
        _foot_pnl_title_lbl = tk.Label(rfoot, text="P & L",
                 bg=DARK_HEADER, fg=DIM_TEXT,
                 font=("Segoe UI", 7, "bold"))
        _foot_pnl_title_lbl.pack()
        psign = "+" if pnl_pct > 0 else ""
        _foot_pnl_lbl = tk.Label(rfoot, text=f"{psign}{pnl_pct:.2f}%",
                 bg=DARK_HEADER, fg=pnl_col,
                 font=("Consolas", 10, "bold"))
        _foot_pnl_lbl.pack()

        # ── ② 헤더 — 활성/비활성 상태에 따라 스타일 동기화 ─────────
        if is_active:
            _hdr_bg, _title_fg = hdr_bg, hdr_fg
            _state_txt, _state_col = engine_state, state_col
        else:
            _hdr_bg, _title_fg = DARK_HEADER, DIM_TEXT
            _state_txt, _state_col = "⏸  비활성  —  대기 중", DIM_TEXT

        hdr = tk.Frame(parent, bg=_hdr_bg, pady=6)
        hdr.pack(fill="x")
        _title_lbl = tk.Label(hdr, text=f"  {title}", bg=_hdr_bg, fg=_title_fg,
                 font=("Segoe UI", 10, "bold"))
        _title_lbl.pack(side="left", padx=(6, 0))
        _hist_btn = tk.Button(
            hdr, text="거래 내역", bg=_hdr_bg, fg=DIM_TEXT,
            activebackground=_hdr_bg, activeforeground=ACCENT_BLUE,
            bd=0, relief="flat", font=("Segoe UI", 8), cursor="hand2",
            command=lambda: _toggle_hist())
        _hist_btn.pack(side="right", padx=(0, 10))
        _state_lbl = tk.Label(hdr, text=_state_txt, bg=_hdr_bg, fg=_state_col,
                 font=("Segoe UI", 8, "bold"))
        _state_lbl.pack(side="right", padx=(0, 18))

        # ── ③ 바디: 차트+모니터링 뷰 ↔ 거래 내역 뷰 (탭 전환) ──────
        body = tk.Frame(parent, bg=DARK_BG)
        body.pack(fill="both", expand=True)

        # 차트+모니터링 뷰 (기본 표시)
        chart_mon_f = tk.Frame(body, bg=DARK_BG)
        chart_mon_f.place(x=0, y=0, relwidth=1, relheight=1)

        # 거래 내역 뷰 (버튼 클릭 시 표시 — 초기 숨김)
        hist_f    = tk.Frame(body, bg=DARK_BG)
        _hist_view = [False]   # [0]: True=거래내역 표시 중, False=차트 표시 중

        def _show_chart():
            _hist_view[0] = False
            hist_f.place_forget()
            chart_mon_f.place(x=0, y=0, relwidth=1, relheight=1)
            try:
                _hist_btn.configure(fg=DIM_TEXT)
            except Exception:
                pass
            body.after(10, _layout_body)

        def _show_history():
            _hist_view[0] = True
            chart_mon_f.place_forget()
            hist_f.place(x=0, y=0, relwidth=1, relheight=1)
            try:
                _hist_btn.configure(fg=ACCENT_BLUE)
            except Exception:
                pass
            _redraw_hist()

        def _toggle_hist():
            if _hist_view[0]:
                _show_chart()
            else:
                _show_history()

        CHART_RATIO = 0.6   # 차트 : 모니터링 = 6 : 4
        DIV_W = 2

        chart_wrap = tk.Frame(chart_mon_f, bg="#0D0D0D")
        divider    = tk.Frame(chart_mon_f, bg="#2A2A2A")
        mon_col    = tk.Frame(chart_mon_f, bg=DARK_PANEL)

        def _layout_body(event=None) -> None:
            W = body.winfo_width()
            H = body.winfo_height()
            if W < 40 or H < 10:
                return
            chart_w = int((W - DIV_W) * CHART_RATIO)
            mon_w   = W - DIV_W - chart_w
            chart_wrap.place(x=0, y=0, width=chart_w, height=H)
            divider.place(x=chart_w, y=0, width=DIV_W, height=H)
            mon_col.place(x=chart_w + DIV_W, y=0, width=mon_w, height=H)
        body.bind("<Configure>", _layout_body)
        chart_mon_f.bind("<Configure>", _layout_body)

        # ── 가격 차트 (좌, 비율 6) ───────────────────────────────
        _chart_cv = self._init_price_chart(chart_wrap)

        # 엔진 상태
        _status_lbl_w = tk.Label(mon_col, text=status_lbl,
                 bg=DARK_PANEL, fg=status_col,
                 font=("Segoe UI", 8, "bold"),
                 anchor="w", wraplength=178)
        _status_lbl_w.pack(fill="x", padx=8, pady=(10, 0))

        # P&L 진행 바
        pnl_row = tk.Frame(mon_col, bg=DARK_PANEL)
        pnl_row.pack(fill="x", padx=8, pady=(6, 0))
        psign2 = "+" if pnl_pct > 0 else ""
        _pnl_text_lbl = tk.Label(pnl_row, text=f"{psign2}{pnl_pct:.1f}%",
                 bg=DARK_PANEL, fg=pnl_col,
                 font=("Consolas", 8, "bold"), width=7, anchor="w")
        _pnl_text_lbl.pack(side="left")
        pnl_cv = tk.Canvas(pnl_row, bg="#1A1A1A", width=1, height=10, highlightthickness=0)
        pnl_cv.pack(side="left", fill="x", expand=True)
        ratio = min(abs(pnl_pct) / 10.0, 1.0)
        def _draw_pnl(e=None, cv=pnl_cv, r=ratio, c=pnl_col):
            cv.delete("all")
            w = cv.winfo_width()
            if w < 4: return
            cv.create_rectangle(0, 2, w, 8, fill="#2A2A2A", outline="")
            if r > 0:
                cv.create_rectangle(0, 2, int(w * r), 8, fill=c, outline="")
        pnl_cv.bind("<Configure>", _draw_pnl)
        pnl_cv.after(30, _draw_pnl)

        # 실시간 모니터링 표시줄
        dot     = "●" if is_active else "○"
        dot_col = (POSITIVE if side == "long" else NEGATIVE) if is_active else DIM_TEXT
        mon_row = tk.Frame(mon_col, bg=DARK_PANEL)
        mon_row.pack(fill="x", padx=8, pady=(4, 0))
        tk.Label(mon_row, text="실시간 거래 모니터링",
                 bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 7)).pack(side="left")
        _dot_lbl_w = tk.Label(mon_row, text=dot, bg=DARK_PANEL, fg=dot_col,
                 font=("Segoe UI", 8))
        _dot_lbl_w.pack(side="right")

        # 예측 텍스트 (나머지 공간)
        pred_f = tk.Frame(mon_col, bg="#111111")
        pred_f.pack(fill="both", expand=True, padx=0, pady=(6, 0))
        _pred_lbl_w = tk.Label(pred_f, text=pred_txt, bg="#111111", fg=pred_col,
                 font=("Segoe UI", 9, "bold"),
                 anchor="center", wraplength=178, justify="center")
        _pred_lbl_w.pack(fill="both", expand=True, padx=6)

        # ── 거래 내역 뷰 구성 ────────────────────────────────────
        # 상단: 뒤로가기 + 요약 바 + 초기화 버튼 (한 행)
        _hist_top = tk.Frame(hist_f, bg=DARK_HEADER)
        _hist_top.pack(fill="x")
        tk.Button(
            _hist_top, text="← 차트",
            bg=DARK_HEADER, fg=ACCENT_BLUE,
            activebackground=DARK_HEADER, activeforeground=DARK_TEXT,
            bd=0, relief="flat", font=("Segoe UI", 7), cursor="hand2",
            command=_show_chart).pack(side="left", padx=(6, 0), pady=2)

        def _clear_history():
            target = (self._long_trade_history if side == "long"
                      else self._short_trade_history)
            if not target:
                return
            from tkinter import messagebox as _mb
            if not _mb.askyesno(
                    "초기화 확인",
                    f"{title.strip()} 거래 내역 {len(target)}건을 모두 삭제합니다.\n"
                    "이 작업은 되돌릴 수 없습니다. 계속하시겠습니까?"):
                return
            target.clear()
            self._recorded_trades = {
                k for k in self._recorded_trades if k[0] != side
            }
            self._save_trade_history()
            _redraw_hist()

        tk.Button(
            _hist_top, text="초기화",
            bg=DARK_HEADER, fg="#FF6666",
            activebackground=DARK_HEADER, activeforeground="#FF4444",
            bd=0, relief="flat", font=("Segoe UI", 7), cursor="hand2",
            command=_clear_history).pack(side="right", padx=(0, 6), pady=2)
        _hist_sum_lbl = tk.Label(
            _hist_top, text="— 거래 내역 없음 —",
            bg=DARK_HEADER, fg=DIM_TEXT,
            font=("Consolas", 7), anchor="center")
        _hist_sum_lbl.pack(side="left", fill="x", expand=True, padx=4)
        tk.Frame(hist_f, bg="#1A1A2A", height=1).pack(fill="x")

        # 컬럼 헤더 행
        _COL_CONF = [
            ("시각",    10, "center"),
            ("심볼",     9, "center"),
            ("진입가",   9, "e"),
            ("청산가",   9, "e"),
            ("수익률",   8, "e"),
            ("수익금",   9, "e"),
            ("누적손익",  9, "e"),
            ("보유",     6, "center"),
            ("청산사유",  0, "w"),
        ]
        col_hdr_f = tk.Frame(hist_f, bg="#0F0F1A")
        col_hdr_f.pack(fill="x")
        for _cn, _cw, _ca in _COL_CONF:
            _kw = {"bg": "#0F0F1A", "fg": DIM_TEXT,
                   "font": ("Consolas", 6, "bold"), "anchor": _ca}
            if _cw == 0:
                tk.Label(col_hdr_f, text=_cn, **_kw).pack(
                    side="left", fill="x", expand=True, padx=2)
            else:
                tk.Label(col_hdr_f, text=_cn, width=_cw, **_kw).pack(
                    side="left", padx=1)
        tk.Frame(hist_f, bg="#2A2A3A", height=1).pack(fill="x")

        # 스크롤 가능 테이블 영역
        _hist_outer = tk.Frame(hist_f, bg=DARK_BG)
        _hist_outer.pack(fill="both", expand=True)
        _hist_cv   = tk.Canvas(_hist_outer, bg=DARK_BG, highlightthickness=0)
        _hist_sb   = tk.Scrollbar(_hist_outer, orient="vertical",
                                  command=_hist_cv.yview)
        _hist_cv.configure(yscrollcommand=_hist_sb.set)
        _hist_sb.pack(side="right", fill="y")
        _hist_cv.pack(side="left", fill="both", expand=True)
        _hist_inner = tk.Frame(_hist_cv, bg=DARK_BG)
        _hist_win   = _hist_cv.create_window((0, 0), window=_hist_inner, anchor="nw")
        _hist_inner.bind("<Configure>",
                         lambda e: _hist_cv.configure(
                             scrollregion=_hist_cv.bbox("all")))
        _hist_cv.bind("<Configure>",
                      lambda e: _hist_cv.itemconfigure(_hist_win, width=e.width))

        def _fmt_ts(ts: float) -> str:
            if ts <= 0:
                return "—"
            try:
                import datetime as _dt
                return _dt.datetime.fromtimestamp(ts).strftime("%m/%d %H:%M")
            except Exception:
                return "—"

        def _fmt_hold(et: float, xt: float) -> str:
            if et <= 0 or xt <= 0:
                return "—"
            s = int(xt - et)
            if s < 60:
                return f"{s}s"
            if s < 3600:
                return f"{s // 60}m"
            return f"{s // 3600}h{(s % 3600) // 60}m"

        def _fmt_reason(rec: dict) -> str:
            reason = rec.get("reason", "")
            phase  = rec.get("phase", 1)
            pc     = rec.get("partial_closed", False)
            if reason == "강제 청산":
                return f"강제청산(P{phase})"
            if "SL" in reason or "손절" in reason:
                if phase == 1:
                    return "Phase1 손절"
                if phase == 2:
                    return "Phase2 BEP"
                if phase == 3:
                    return "P3+부분익절" if pc else "Phase3 트레일"
            return reason or "청산"

        def _redraw_hist():
            hist_data = (self._long_trade_history if side == "long"
                         else self._short_trade_history)
            if not hist_data:
                _hist_sum_lbl.configure(text="— 거래 내역 없음 —", fg=DIM_TEXT)
            else:
                total    = len(hist_data)
                wins     = sum(1 for t in hist_data if t["pnl_pct"] > 0)
                wr       = wins / total * 100
                cum_pct  = sum(t["pnl_pct"]  for t in hist_data)
                cum_usdt = sum(t["pnl_usdt"] for t in hist_data)
                sc = POSITIVE if cum_usdt >= 0 else NEGATIVE
                _hist_sum_lbl.configure(
                    text=(f"총 {total}거래  │  승률 {wr:.1f}%"
                          f"  │  {cum_pct:+.2f}%  │  {cum_usdt:+.2f}U"),
                    fg=sc)
            for w in _hist_inner.winfo_children():
                w.destroy()
            cum = 0.0
            for i, rec in enumerate(hist_data):
                cum    += rec["pnl_usdt"]
                pc_val  = rec["pnl_pct"]
                pu_val  = rec["pnl_usdt"]
                bg      = DARK_ROW_ODD if i % 2 == 0 else DARK_ROW_EVN
                pc_col  = POSITIVE if pc_val > 0 else (NEGATIVE if pc_val < 0 else DIM_TEXT)
                cu_col  = POSITIVE if cum   >= 0 else NEGATIVE
                row     = tk.Frame(_hist_inner, bg=bg)
                row.pack(fill="x")
                cells = [
                    (_fmt_ts(rec.get("entry_time", 0)),           10, "center", DIM_TEXT),
                    (rec.get("symbol", "—"),                        9, "center", DARK_TEXT),
                    (f"{rec['entry']:.4g}",                         9, "e",      DARK_TEXT),
                    (f"{rec['exit']:.4g}",                          9, "e",      DARK_TEXT),
                    (f"{pc_val:+.2f}%",                             8, "e",      pc_col),
                    (f"{pu_val:+.3f}U",                             9, "e",      pc_col),
                    (f"{cum:+.3f}U",                                9, "e",      cu_col),
                    (_fmt_hold(rec.get("entry_time", 0),
                               rec.get("exit_time",  0)),           6, "center", DIM_TEXT),
                    (_fmt_reason(rec),                              0, "w",      DIM_TEXT),
                ]
                for txt, cw, anch, fg in cells:
                    kw = {"bg": bg, "fg": fg,
                          "font": ("Consolas", 7), "anchor": anch, "padx": 1}
                    if cw == 0:
                        tk.Label(row, text=txt, **kw).pack(
                            side="left", fill="x", expand=True)
                    else:
                        tk.Label(row, text=txt, width=cw, **kw).pack(side="left")
            try:
                _hist_cv.update_idletasks()
                _hist_cv.configure(scrollregion=_hist_cv.bbox("all"))
            except Exception:
                pass
        # ── 패널 위젯 참조 저장 ──────────────────────────────────
        _panel_ref = {
            "hdr":           hdr,
            "title_lbl":     _title_lbl,
            "state_lbl":     _state_lbl,
            "status_lbl":    _status_lbl_w,
            "dot_lbl":       _dot_lbl_w,
            "pred_lbl":      _pred_lbl_w,
            "chart_cv":      _chart_cv,
            "hdr_bg":        hdr_bg,
            "hdr_fg":        hdr_fg,
            "engine_state":  engine_state,
            "state_col":     state_col,
            # 1초 P&L 폴링 갱신 대상 위젯
            "pnl_text_lbl":       _pnl_text_lbl,
            "pnl_bar_cv":         pnl_cv,
            "foot_gain_title_lbl": _foot_gain_title_lbl,
            "foot_pnl_title_lbl":  _foot_pnl_title_lbl,
            "foot_usdt_lbl":      _foot_usdt_lbl,
            "foot_pnl_lbl":       _foot_pnl_lbl,
            "hist_redraw":        _redraw_hist,
        }
        if side == "long":
            self._long_panel = _panel_ref
        else:
            self._short_panel = _panel_ref

    def on_app_start(self) -> None:
        """헤더 [START] 버튼 클릭 시 — 대기 모드 진입."""
        self._app_started = True
        if self._pos_ind and not self._shared_sym.get():
            self._pos_ind["lbl"].configure(
                text="코인 심볼 및 전략을 선택하세요!", fg=YELLOW)

    def on_app_stop(self) -> None:
        """헤더 [STOP] 버튼 클릭 시 — 대기 모드 해제."""
        self._app_started = False
        if self._trading_active:
            self._trading_active = False
            self._trade_btn.configure(
                text="  거래 활성화  ",
                bg="#252525", fg="#888888",
                activebackground="#303030", activeforeground=DARK_TEXT,
                state="disabled", cursor="arrow")
            if self._engine is not None:
                self._engine.stop()
        self._update_engine_panels()
        if not self._shared_sym.get():
            self._update_position_indicator(None)

    def force_close_all_positions(self) -> None:
        """헤더 [forced liquidation] — 포지션 강제 청산 → 엔진 정지 → 심볼 유지."""
        if self._engine is None:
            return
        if not self._engine.has_open_positions():
            return

        def _on_liq_success():
            self._trading_active = False
            if self._engine is not None:
                self._engine.stop()
            self._trade_btn.configure(
                text="  거래 활성화  ",
                bg="#0A2A12", fg=POSITIVE,
                activebackground="#0A3A18", activeforeground=POSITIVE,
                state="normal")
            if self._shared_sym.get():
                self._clear_btn.configure(state="normal")
            if self._last_sig_lbl is not None:
                try:
                    self._last_sig_lbl.configure(
                        text="🔴  강제 청산 완료", fg=YELLOW)
                except Exception:
                    pass
            self._update_engine_panels()

        def _on_liq_fail(results: dict):
            self._on_force_close_done(results)

        def _bg() -> None:
            results = self._engine.force_close_all()
            any_fail = (results.get("long") == "실패" or results.get("short") == "실패")
            if any_fail:
                self.after(0, lambda: _on_liq_fail(results))
            else:
                self.after(0, _on_liq_success)

        _threading.Thread(target=_bg, daemon=True).start()

    def _on_force_close_done(self, results: dict) -> None:
        """강제 청산 결과 UI 반영 (메인 스레드 전용)."""
        for side, panel in (("long", self._long_panel), ("short", self._short_panel)):
            if panel is None:
                continue
            res = results.get(side, "없음")
            if res == "없음":
                continue
            try:
                if res == "성공":
                    panel["status_lbl"].configure(
                        text="🔴  강제 청산 완료  |  포지션 없음", fg=YELLOW)
                    panel["pred_lbl"].configure(
                        text="강제 청산 완료\n신규 신호 대기 중", fg=YELLOW)
                else:
                    panel["status_lbl"].configure(
                        text="⚠  강제 청산 실패  —  수동 확인 필요", fg=NEGATIVE)
                    panel["pred_lbl"].configure(
                        text="강제 청산 실패\n재시도 필요", fg=NEGATIVE)
            except Exception:
                pass
        if self._last_sig_lbl is not None:
            long_r  = results.get("long",  "없음")
            short_r = results.get("short", "없음")
            any_success = (long_r == "성공" or short_r == "성공")
            any_fail    = (long_r == "실패" or short_r == "실패")
            try:
                if any_success and not any_fail:
                    self._last_sig_lbl.configure(
                        text="🔴  강제 청산 완료", fg=YELLOW)
                elif any_fail:
                    self._last_sig_lbl.configure(
                        text="⚠  강제 청산 실패  —  수동 확인 필요", fg=NEGATIVE)
            except Exception:
                pass

    def force_stop_with_liquidation(
        self,
        on_success: "callable",
        on_fail:    "callable",
    ) -> None:
        """[STOP] 버튼 전용 — 포지션 강제 청산 후 성공 시 on_success(), 실패 시 on_fail(results)."""
        if self._engine is None:
            on_success()
            return
        def _bg() -> None:
            results  = self._engine.force_close_all()
            any_fail = (results.get("long") == "실패" or results.get("short") == "실패")
            if any_fail:
                self.after(0, lambda: on_fail(results))
            else:
                self.after(0, on_success)
        _threading.Thread(target=_bg, daemon=True).start()

    # ──────────────────────────────────────────────────────────────
    # [C] 거래 내역 파일 영속화 (보완 2)
    # ──────────────────────────────────────────────────────────────
    def _load_trade_history(self) -> None:
        """앱 시작 시 trade_history.json에서 이전 거래 내역을 복원."""
        try:
            if _TRADE_HISTORY_PATH.exists():
                data = json.loads(
                    _TRADE_HISTORY_PATH.read_text(encoding="utf-8")
                )
                raw_long  = data.get("long",  [])
                raw_short = data.get("short", [])
                self._long_trade_history  = _dedup_hist(raw_long)
                self._short_trade_history = _dedup_hist(raw_short)
                if (len(self._long_trade_history) != len(raw_long) or
                        len(self._short_trade_history) != len(raw_short)):
                    self._save_trade_history()
        except Exception:
            pass
        for rec in self._long_trade_history:
            self._recorded_trades.add(("long",  rec.get("entry_time", 0.0), rec.get("exit_time", 0.0)))
        for rec in self._short_trade_history:
            self._recorded_trades.add(("short", rec.get("entry_time", 0.0), rec.get("exit_time", 0.0)))

    def _save_trade_history(self) -> None:
        """거래 완료 직후 trade_history.json에 전체 내역을 저장."""
        try:
            data = {
                "long":  self._long_trade_history,
                "short": self._short_trade_history,
            }
            _TRADE_HISTORY_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).error(
                "거래 내역 저장 실패 — %s: %s", _TRADE_HISTORY_PATH.name, e)

    # ──────────────────────────────────────────────────────────────
    def _record_trade(
        self, side: str, symbol: str,
        entry: float, exit_p: float,
        pnl_pct: float, pnl_usdt: float,
        reason: str, phase: int, partial_closed: bool,
        entry_time: float, exit_time: float,
    ) -> None:
        """청산 완료 시 거래 내역 리스트에 추가하고 거래 내역 뷰를 갱신."""
        record = {
            "symbol":         symbol,
            "entry":          entry,
            "exit":           exit_p,
            "pnl_pct":        pnl_pct,
            "pnl_usdt":       pnl_usdt,
            "reason":         reason,
            "phase":          phase,
            "partial_closed": partial_closed,
            "entry_time":     entry_time,
            "exit_time":      exit_time,
        }
        if side == "long":
            self._long_trade_history.insert(0, record)
        else:
            self._short_trade_history.insert(0, record)
        self._save_trade_history()  # [C] 파일에 즉시 저장 (보완 2)
        panel = self._long_panel if side == "long" else self._short_panel
        redraw_fn = panel.get("hist_redraw") if panel else None
        if redraw_fn:
            try:
                redraw_fn()
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════
    # 1초 P&L 폴링 루프 — 하단 푸터 + 모니터링 진행 바 갱신
    # ══════════════════════════════════════════════════════════════
    def _poll_pnl(self) -> None:
        """1초 주기 P&L 갱신 루프 — 엔진 포지션 상태만 읽어 4개 위젯 갱신."""
        if not self._pnl_running:
            return
        try:
            _state    = self._engine.get_state() if self._engine else None
            long_pos  = _state.long_pos  if _state else None
            short_pos = _state.short_pos if _state else None

            for side, panel, pos in (
                ("long",  self._long_panel,  long_pos),
                ("short", self._short_panel, short_pos),
            ):
                if not panel:
                    continue
                # 포지션 보유 중이면 실제 값, 아니면 0
                try:
                    if pos is not None and pos.state == PositionState.OPEN:
                        pnl   = pos.pnl_pct
                        usdt  = pos.pnl_usdt
                    else:
                        pnl, usdt = 0.0, 0.0
                except Exception:
                    pnl, usdt = 0.0, 0.0

                pnl_col = (POSITIVE if pnl > 0 else
                           NEGATIVE if pnl < 0 else DIM_TEXT)

                # ① 모니터링 영역 P&L% 텍스트
                txt_lbl = panel.get("pnl_text_lbl")
                if txt_lbl:
                    sign = "+" if pnl > 0 else ""
                    txt_lbl.configure(
                        text=f"{sign}{pnl:.1f}%", fg=pnl_col)

                # ② 모니터링 영역 P&L 진행 바
                bar_cv = panel.get("pnl_bar_cv")
                if bar_cv:
                    ratio = min(abs(pnl) / 10.0, 1.0)
                    bar_cv.delete("all")
                    w = bar_cv.winfo_width()
                    if w >= 4:
                        bar_cv.create_rectangle(
                            0, 2, w, 8, fill="#2A2A2A", outline="")
                        if ratio > 0:
                            bar_cv.create_rectangle(
                                0, 2, int(w * ratio), 8,
                                fill=pnl_col, outline="")

                # ③ 하단 푸터 제목 라벨 — 포지션 보유 시 활성화 색상
                title_col = (DARK_TEXT
                             if pos is not None and pos.state == PositionState.OPEN
                             else DIM_TEXT)
                gain_title = panel.get("foot_gain_title_lbl")
                if gain_title:
                    gain_title.configure(fg=title_col)
                pnl_title = panel.get("foot_pnl_title_lbl")
                if pnl_title:
                    pnl_title.configure(fg=title_col)

                # ④ 하단 푸터 Total Slot Gain / Loss (USDT)
                usdt_lbl = panel.get("foot_usdt_lbl")
                if usdt_lbl:
                    sign = "+" if usdt > 0 else ""
                    usdt_lbl.configure(
                        text=f"{sign}{usdt:.3f}   USDT", fg=pnl_col)

                # ⑤ 하단 푸터 P & L (%)
                pnl_lbl = panel.get("foot_pnl_lbl")
                if pnl_lbl:
                    sign = "+" if pnl > 0 else ""
                    pnl_lbl.configure(
                        text=f"{sign}{pnl:.2f}%", fg=pnl_col)

            # ── 포지션 OPEN → 청산 완료 전환 감지 → 잔고 1회 재조회 ──
            cur_long_open  = (long_pos  is not None
                              and long_pos.state  == PositionState.OPEN)
            cur_short_open = (short_pos is not None
                              and short_pos.state == PositionState.OPEN)
            if ((self._prev_long_open  and not cur_long_open) or
                    (self._prev_short_open and not cur_short_open)):
                self._refresh_ui_balance_bg()
            self._prev_long_open  = cur_long_open
            self._prev_short_open = cur_short_open

        except tk.TclError:
            self._pnl_running = False
            return
        except Exception:
            pass
        try:
            self.after(1000, self._poll_pnl)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    # 롱/숏 엔진 패널 실시간 갱신
    # ══════════════════════════════════════════════════════════════
    def _update_engine_panels(self) -> None:
        """거래 활성화 상태·방향에 따라 롱/숏 패널 갱신."""
        sym = self._shared_sym.get()
        ind = get_ind(sym) if sym else {}

        _state    = self._engine.get_state() if self._engine else None
        err_msg   = (_state.error_msg        or "") if _state else ""
        blk_long  = (_state.last_blocked_long  or "") if _state else ""
        blk_short = (_state.last_blocked_short or "") if _state else ""

        if not self._trading_active or not sym:
            trading_on = False
            direction  = None
        else:
            trading_on = True
            use_macro  = (self._applied_params or {}).get("use_macro", True)
            if use_macro:
                score     = self._calc_macro_score(ind)
                direction = ("long"  if score >= 1 else
                             "short" if score <= -1 else None)
            else:
                sig       = FourTFConsensus.evaluate(ind)
                direction = ("long"  if sig.aligned_long  >= 3 else
                             "short" if sig.aligned_short >= 3 else None)

        for side, panel in (("long", self._long_panel), ("short", self._short_panel)):
            if not panel:
                continue
            pos = None
            if _state is not None:
                pos = _state.long_pos if side == "long" else _state.short_pos
            try:
                blk = blk_long if side == "long" else blk_short
                self._refresh_engine_panel(panel, side, trading_on, direction, ind, pos, err_msg, blk)
            except tk.TclError:
                pass

    def _refresh_engine_panel(self, panel: dict, side: str,
                              trading_on: bool, direction: str | None,
                              ind: dict,
                              pos=None, err: str = "", blk: str = "") -> None:
        """개별 엔진 패널 위젯 갱신."""
        tf1    = ind.get("tf1", {})
        k1, d1 = tf1.get("k", 50.0), tf1.get("d", 50.0)
        if ind:
            try:
                sig        = FourTFConsensus.evaluate(ind)
                al         = sig.aligned_long  if side == "long" else sig.aligned_short
                al_opp     = sig.aligned_short if side == "long" else sig.aligned_long
                full_align = sig.long_consensus if side == "long" else sig.short_consensus
                details    = sig.details
            except Exception:
                al, al_opp, full_align, details = 0, 0, False, {}
        else:
            al, al_opp, full_align, details = 0, 0, False, {}

        # ── 포지션 상태 파악 ──────────────────────────────────────
        try:
            pos_state = pos.state if pos is not None else None
        except Exception:
            pos_state = None

        pos_open = (pos_state == PositionState.OPEN)
        cached   = self._exit_cache.get(side)
        pos_closed = (cached is not None and time.time() < cached.get("until", 0))

        # ── ① 포지션 OPEN: 실데이터 기반 우선 표시 ──────────────
        if trading_on and pos_open:
            try:
                entry = pos.entry_price
                sl    = pos.current_sl
                phase = pos.phase
                pc    = pos.partial_closed
                qty   = pos.quantity
                et    = getattr(pos, "entry_time", 0.0)
            except Exception:
                entry, sl, phase, pc, qty, et = 0.0, 0.0, 1, False, 0.0, 0.0

            elapsed_s = max(0, int(time.time() - et)) if et > 0 else 0
            if elapsed_s < 60:
                elapsed = f"{elapsed_s}s"
            elif elapsed_s < 3600:
                elapsed = f"{elapsed_s // 60}m {elapsed_s % 60}s"
            else:
                elapsed = f"{elapsed_s // 3600}h {(elapsed_s % 3600) // 60}m"

            if phase == 1:
                phase_txt = "Phase1  초기 SL"
            elif phase == 2:
                phase_txt = "Phase2  BEP 이동 완료"
            elif phase == 3 and not pc:
                phase_txt = "Phase3  트레일링  50% 익절 진행"
            else:
                phase_txt = "Phase3  트레일링  50% 익절 완료"

            _hbg, _tfg = panel["hdr_bg"], panel["hdr_fg"]
            if side == "long":
                _st  = "🟢  롱 포지션 보유 중";  _sc = POSITIVE
                _sl  = (f"📈  진입가 {entry:.4g}  |  SL {sl:.4g}\n수량 {qty:.4g}  |  {phase_txt}"
                        if entry > 0 else "📈  롱 포지션 보유 중")
                _slc = POSITIVE
            else:
                _st  = "🔴  숏 포지션 보유 중";  _sc = NEGATIVE
                _sl  = (f"📉  진입가 {entry:.4g}  |  SL {sl:.4g}\n수량 {qty:.4g}  |  {phase_txt}"
                        if entry > 0 else "📉  숏 포지션 보유 중")
                _slc = NEGATIVE
            _dot = "●";  _dc = POSITIVE if side == "long" else NEGATIVE
            _pt  = f"{phase_txt}\n보유 {elapsed}"
            _pc  = POSITIVE if side == "long" else NEGATIVE

        # ── ② 포지션 CLOSED 30초 오버레이: 청산 결과 표시 ────────
        elif trading_on and pos_closed:
            ep      = cached.get("exit",   0.0)
            pnl     = cached.get("pnl",    0.0)
            reason  = cached.get("reason", "청산")
            pnl_col = POSITIVE if pnl > 0 else (NEGATIVE if pnl < 0 else DIM_TEXT)

            _hbg, _tfg = DARK_HEADER, DIM_TEXT
            _st   = "⏸  청산 완료  —  신호 대기";  _sc = DIM_TEXT
            _sl   = (f"🔴  {reason}  |  체결가 {ep:.4g}"
                     if ep > 0 else f"🔴  {reason}")
            _slc  = YELLOW
            _dot  = "○";  _dc = DIM_TEXT
            _pt   = f"{pnl:+.2f}%\n신규 신호 대기 중"
            _pc   = pnl_col

        # ── ③-예외 엔진 정지 + 포지션 OPEN (청산 처리 중 또는 엣지케이스) ──
        elif not trading_on and pos_open:
            try:
                entry = pos.entry_price
                sl    = pos.current_sl
                phase = pos.phase
                pc    = pos.partial_closed
            except Exception:
                entry, sl, phase, pc = 0.0, 0.0, 1, False
            if phase == 1:              phase_txt = "Phase1  초기 SL"
            elif phase == 2:            phase_txt = "Phase2  BEP 이동 완료"
            elif phase == 3 and not pc: phase_txt = "Phase3  트레일링  50% 익절 진행"
            else:                       phase_txt = "Phase3  트레일링  50% 익절 완료"
            _hbg, _tfg = DARK_HEADER, YELLOW
            if side == "long":
                _st  = "⚠  청산 중  —  롱 포지션 유지 중";  _sc  = YELLOW
                _sl  = (f"📌  진입가 {entry:.4g}  |  SL {sl:.4g}  (Binance 보호 중)"
                        if entry > 0 else "📌  롱 포지션 유지 중  (Binance 보호 중)")
                _slc = YELLOW
            else:
                _st  = "⚠  청산 중  —  숏 포지션 유지 중";  _sc  = YELLOW
                _sl  = (f"📌  진입가 {entry:.4g}  |  SL {sl:.4g}  (Binance 보호 중)"
                        if entry > 0 else "📌  숏 포지션 유지 중  (Binance 보호 중)")
                _slc = YELLOW
            _dot = "●";  _dc = YELLOW
            _pt  = f"{phase_txt}\n청산 처리 중...";  _pc = YELLOW

        # ── ③ 거래 비활성 ─────────────────────────────────────────
        elif not trading_on:
            _hbg, _tfg = DARK_HEADER, DIM_TEXT
            _st  = "⏸  비활성  —  대기 중";  _sc  = DIM_TEXT
            _sl  = ("4TF 불리시 대기  |  엔진 대기 중" if side == "long"
                    else "4TF K<D 대기  |  엔진 대기 중");  _slc = DIM_TEXT
            _dot, _dc = "○", DIM_TEXT
            _pt  = ("롱 엔진 대기  —  전략 우선순위 외" if side == "long"
                    else "숏 엔진 대기  —  전략 우선순위 외");  _pc = DIM_TEXT

        # ── ④ IDLE — 4TF 방향 기반 대기 텍스트 ──────────────────
        elif direction == side:
            _hbg, _tfg = panel["hdr_bg"], panel["hdr_fg"]
            _st,  _sc  = panel["engine_state"], panel["state_col"]
            _tf_parts  = [f"{tf}{details[tf]['dir']}" for tf in ("1m", "3m", "5m", "15m") if tf in details]
            _tf_str    = "  ".join(_tf_parts) if _tf_parts else f"{al}/4"
            if full_align:
                _sl  = f"{_tf_str}  |  진입 대기"
                _slc = POSITIVE if side == "long" else NEGATIVE
            else:
                _sl, _slc = f"{_tf_str}  |  진입 신호 탐색", YELLOW
            _dot = "●";  _dc = POSITIVE if side == "long" else NEGATIVE
            if   blk:      _pt, _pc = blk,                             YELLOW
            elif k1 < 20:  _pt, _pc = "1m 과매도 진입 신호 대기 중", POSITIVE
            elif k1 > 80:  _pt, _pc = "1m 과매수  —  진입 보류",     YELLOW
            else:          _pt, _pc = f"1m K {k1:.0f}  D {d1:.0f}  —  신호 탐색 중", ACCENT_BLUE

        elif direction is not None:
            _hbg, _tfg = DARK_HEADER, DIM_TEXT
            _st  = ("🔒  숏 추세 — 롱 엔진 잠금" if side == "long"
                    else "🔒  롱 추세 — 숏 엔진 잠금");  _sc  = DIM_TEXT
            _sl  = (f"숏 {al_opp}/4 정렬  —  롱 진입 금지" if side == "long"
                    else f"롱 {al_opp}/4 정렬  —  숏 진입 금지");  _slc = DIM_TEXT
            _dot, _dc = "○", DIM_TEXT
            _pt  = (f"숏 추세 {al_opp}/4 진행 중\n롱 엔진 대기" if side == "long"
                    else f"롱 추세 {al_opp}/4 진행 중\n숏 엔진 대기");  _pc = DIM_TEXT

        else:
            _hbg, _tfg = DARK_HEADER, DIM_TEXT
            _st  = "⏸  4TF 합의 대기  —  엔진 대기 중";  _sc  = DIM_TEXT
            _sl  = "4TF 방향 미확정  |  진입 신호 대기";  _slc = DIM_TEXT
            _dot, _dc = "○", DIM_TEXT
            _pt, _pc  = (blk, YELLOW) if blk else ("4TF 합의 대기 중", DIM_TEXT)

        # ── 에러 오버레이 (포지션 없을 때 항상, 비활성 시 강조 표시) ─
        if err and not pos_open and not pos_closed:
            _sl  = f"⚠  {err[:55]}"
            _slc = NEGATIVE
            if not trading_on:                    # 비활성 + 잔고 에러 강조
                _hbg = "#2A0A0F"
                _tfg = NEGATIVE
                _st  = "⛔  거래 불가  —  자금 부족"
                _sc  = NEGATIVE
                _dot = "○";  _dc = NEGATIVE
                _pt  = "Designated Funds 비율 또는\n잔고를 확인하세요"
                _pc  = DIM_TEXT

        # ── 위젯 적용 ─────────────────────────────────────────────
        hdr = panel["hdr"]
        hdr.configure(bg=_hbg)
        for _ch in hdr.winfo_children():
            try: _ch.configure(bg=_hbg)
            except tk.TclError: pass
        panel["title_lbl"].configure(fg=_tfg)
        panel["state_lbl"].configure(text=_st, fg=_sc)
        panel["status_lbl"].configure(text=_sl, fg=_slc)
        panel["dot_lbl"].configure(text=_dot, fg=_dc)
        panel["pred_lbl"].configure(text=_pt, fg=_pc)

    # ──────────────────────────────────────────────────────────────
    # 실OHLCV 가격 차트 (롱/숏 패널 공용)
    # ──────────────────────────────────────────────────────────────
    def _init_price_chart(self, parent: tk.Frame) -> tk.Canvas:
        """가격 차트 캔버스 생성 — 초기 플레이스홀더 상태."""
        cv = tk.Canvas(parent, bg="#0D0D0D", highlightthickness=0)
        cv.pack(fill="both", expand=True)

        def _ph(e=None) -> None:
            cv.delete("all")
            W = cv.winfo_width();  H = cv.winfo_height()
            if W < 10 or H < 10:
                return
            cv.create_text(W // 2, H // 2,
                           text="— 심볼 선택 후 로드 —",
                           fill=DIM_TEXT, font=("Segoe UI", 9))
        cv.bind("<Configure>", _ph)
        cv.after(80, _ph)
        return cv

    def _redraw_price_chart(self, cv: tk.Canvas, ohlcv: list,
                             entry_price: float = 0.0,
                             sl_price:    float = 0.0,
                             pnl_pct:     float = 0.0,
                             side:        str   = "",
                             exit_price:  float = 0.0,
                             exit_reason: str   = "") -> None:
        """실OHLCV 캔들 차트 갱신 + 포지션 오버레이.
        entry_price > 0, exit_price == 0: OPEN 상태 — 진입선·SL선·P&L
        entry_price > 0, exit_price  > 0: CLOSED 상태 — 진입선·청산선·최종P&L
        """
        try:
            cv.delete("all")
            W = cv.winfo_width();  H = cv.winfo_height()
            if W < 20 or H < 20:
                return
            if not ohlcv:
                cv.create_text(W // 2, H // 2, text="데이터 로딩 중...",
                               fill=DIM_TEXT, font=("Segoe UI", 9))
                return

            PAD_L, PAD_R, PAD_T, PAD_B = 2, 36, 6, 4
            has_pos    = entry_price > 0
            is_closed  = has_pos and exit_price > 0

            # ── 가격 범위 (진입가·SL·청산가 포함) ────────────────
            n  = len(ohlcv)
            lo = min(c["l"] for c in ohlcv)
            hi = max(c["h"] for c in ohlcv)
            if has_pos:
                lo = min(lo, entry_price * 0.995)
                hi = max(hi, entry_price * 1.005)
            if sl_price > 0:
                lo = min(lo, sl_price * 0.995)
            if exit_price > 0:
                lo = min(lo, exit_price * 0.995)
                hi = max(hi, exit_price * 1.005)
            rng = hi - lo or (hi * 0.001) or 1.0

            def py(p: float) -> float:
                return PAD_T + (1.0 - (p - lo) / rng) * (H - PAD_T - PAD_B)

            bw     = (W - PAD_L - PAD_R) / max(n, 1)
            body_w = max(1.0, bw * 0.55)

            # ── 그리드 (4단) ─────────────────────────────────
            for step in range(5):
                y = PAD_T + step * (H - PAD_T - PAD_B) / 4
                p = hi - step * rng / 4
                cv.create_line(PAD_L, y, W - PAD_R, y, fill="#1A1A1A", width=1)
                cv.create_text(W - 1, y, text=f"{p:,.2f}",
                               fill="#3A3A3A", font=("Consolas", 5), anchor="ne")

            # ── P&L 구간 채우기 ───────────────────────────────
            if has_pos:
                # CLOSED: 진입가 ~ 청산가 / OPEN: 진입가 ~ 현재가
                ref_price = exit_price if is_closed else ohlcv[-1]["c"]
                y_entry   = py(entry_price)
                y_ref     = py(ref_price)
                fy1, fy2  = sorted([y_entry, y_ref])
                is_profit = (ref_price >= entry_price and side == "long") or \
                            (ref_price <= entry_price and side == "short")
                zone_col  = "#0A3020" if is_profit else "#300A0A"
                cv.create_rectangle(PAD_L, fy1, W - PAD_R, fy2,
                                     fill=zone_col, outline="")

            # ── 캔들 ─────────────────────────────────────────
            for i, bar in enumerate(ohlcv):
                x   = PAD_L + (i + 0.5) * bw
                o   = bar["o"];  h_p = bar["h"]
                l_p = bar["l"];  c   = bar["c"]
                col = POSITIVE if c >= o else NEGATIVE
                cv.create_line(x, py(h_p), x, py(l_p), fill=col, width=1)
                y1, y2 = sorted([py(o), py(c)])
                if y2 - y1 < 1:
                    y2 = y1 + 1
                cv.create_rectangle(x - body_w / 2, y1,
                                     x + body_w / 2, y2,
                                     fill=col, outline="")

            # ── 최신 종가 점선 + 가격 ─────────────────────────
            last_c  = ohlcv[-1]["c"]
            y_last  = py(last_c)
            cv.create_line(PAD_L, y_last, W - PAD_R, y_last,
                           fill="#3A3A3A", width=1, dash=(2, 4))
            col_last = POSITIVE if ohlcv[-1]["c"] >= ohlcv[-1]["o"] else NEGATIVE
            cv.create_text(W - 1, y_last, text=f"{last_c:,.2f}",
                           fill=col_last, font=("Consolas", 6, "bold"), anchor="ne")

            # ── 포지션 오버레이 ───────────────────────────────
            if has_pos:
                entry_col = POSITIVE if side == "long" else NEGATIVE
                y_entry   = py(entry_price)

                # 진입가 수평선 + 라벨
                cv.create_line(PAD_L, y_entry, W - PAD_R, y_entry,
                               fill=entry_col, width=1)
                cv.create_text(PAD_L + 2, y_entry,
                               text=f"진입  {entry_price:,.2f}",
                               fill=entry_col,
                               font=("Consolas", 5, "bold"), anchor="sw")

                if is_closed:
                    # 청산가 수평선 + 사유 라벨 (흰색 실선)
                    y_exit = py(exit_price)
                    cv.create_line(PAD_L, y_exit, W - PAD_R, y_exit,
                                   fill="#DDDDDD", width=1)
                    reason_lbl = exit_reason if exit_reason else "청산"
                    cv.create_text(PAD_L + 2, y_exit,
                                   text=f"청산  {exit_price:,.2f}  [{reason_lbl}]",
                                   fill="#DDDDDD",
                                   font=("Consolas", 5, "bold"), anchor="nw")
                else:
                    # SL 점선 + 라벨 (주황색)
                    if sl_price > 0:
                        y_sl = py(sl_price)
                        cv.create_line(PAD_L, y_sl, W - PAD_R, y_sl,
                                       fill="#FF8800", width=1, dash=(3, 3))
                        cv.create_text(PAD_L + 2, y_sl,
                                       text="SL", fill="#FF8800",
                                       font=("Consolas", 5), anchor="nw")

                # P&L% 상단 중앙 표시
                sign    = "+" if pnl_pct >= 0 else ""
                pnl_col = (POSITIVE if pnl_pct > 0
                           else (NEGATIVE if pnl_pct < 0 else DIM_TEXT))
                closed_tag = "  [종료]" if is_closed else ""
                cv.create_text(W // 2, PAD_T,
                               text=f"{sign}{pnl_pct:.2f}%{closed_tag}",
                               fill=pnl_col,
                               font=("Consolas", 8, "bold"), anchor="n")
        except Exception:
            pass

    def _update_price_charts(self) -> None:
        """선택 심볼 실OHLCV 데이터로 롱/숏 차트 갱신 (2초 폴링마다 호출).
        OPEN: 진입가·SL·P&L 오버레이.
        CLOSED(30초): 청산가·청산사유·P&L 오버레이.
        """
        now   = time.time()
        sym   = self._shared_sym.get()
        ohlcv = generate_ohlcv(sym, n=60, interval="5m") if sym else []

        _state     = self._engine.get_state() if self._engine else None
        _long_pos  = _state.long_pos  if _state else None
        _short_pos = _state.short_pos if _state else None

        pairs = (
            ("long",  self._long_panel,  _long_pos),
            ("short", self._short_panel, _short_pos),
        )
        for side, panel, pos in pairs:
            cv = panel.get("chart_cv") if panel else None
            if not cv:
                continue
            try:
                if not sym:
                    cv.delete("all")
                    W = cv.winfo_width();  H = cv.winfo_height()
                    if W > 10 and H > 10:
                        cv.create_text(W // 2, H // 2,
                                       text="— 심볼 선택 후 로드 —",
                                       fill=DIM_TEXT, font=("Segoe UI", 9))
                    continue

                try:
                    pos_state = pos.state if pos is not None else None
                except Exception:
                    pos_state = None

                if pos_state == PositionState.OPEN:
                    # 포지션 활성 → exit_cache 초기화(재진입 시 이전 캐시 제거)
                    self._exit_cache.pop(side, None)
                    self._redraw_price_chart(cv, ohlcv,
                                             entry_price=pos.entry_price,
                                             sl_price=pos.current_sl,
                                             pnl_pct=pos.pnl_pct,
                                             side=side)
                    continue

                if pos_state == PositionState.CLOSED:
                    # 최초 CLOSED 감지 시 exit_cache 저장 + 거래 내역 기록
                    if side not in self._exit_cache:
                        try:
                            ep  = pos.exit_price     if pos.exit_price  > 0 else 0.0
                            er  = pos.exit_reason    if pos.exit_reason else ""
                            et  = getattr(pos, "entry_time",     0.0)
                            xt  = getattr(pos, "exit_time",      0.0)
                            ph  = getattr(pos, "phase",          1)
                            pc  = getattr(pos, "partial_closed", False)
                            pu  = pos.pnl_usdt
                        except AttributeError:
                            ep, er, et, xt, ph, pc, pu = 0.0, "", 0.0, 0.0, 1, False, 0.0
                        if ep > 0:
                            self._exit_cache[side] = {
                                "entry":  pos.entry_price,
                                "exit":   ep,
                                "pnl":    pos.pnl_pct,
                                "reason": er,
                                "until":  now + 30.0,
                            }
                            _rec_key = (side, et, xt)
                            if _rec_key not in self._recorded_trades:
                                self._recorded_trades.add(_rec_key)
                                self._record_trade(
                                    side, sym,
                                    pos.entry_price, ep,
                                    pos.pnl_pct, pu,
                                    er, ph, pc, et, xt)

                # IDLE 또는 PENDING → exit_cache 제거
                if pos_state not in (PositionState.OPEN, PositionState.CLOSED):
                    self._exit_cache.pop(side, None)

                cached = self._exit_cache.get(side)
                if cached and now < cached["until"]:
                    self._redraw_price_chart(cv, ohlcv,
                                             entry_price=cached["entry"],
                                             sl_price=0.0,
                                             pnl_pct=cached["pnl"],
                                             side=side,
                                             exit_price=cached["exit"],
                                             exit_reason=cached["reason"])
                else:
                    if cached and now >= cached["until"]:
                        self._exit_cache.pop(side, None)
                    self._redraw_price_chart(cv, ohlcv)
            except tk.TclError:
                pass

    # ──────────────────────────────────────────────────────────────
    def _draw_chart(self, parent: tk.Frame, side: str, color: str) -> None:
        if HAS_MPL:
            self._draw_mpl_chart(parent, side, color)
        else:
            self._draw_canvas_chart(parent, side, color)

    def _draw_mpl_chart(self, parent: tk.Frame, side: str, color: str) -> None:
        random.seed(42 if side == "long" else 77)
        n      = 40
        trend  = 0.25 if side == "long" else -0.25
        price  = 95000.0
        candles = []
        for _ in range(n):
            op = price
            cl = op + random.gauss(trend, 0.8) * (price * 0.0005)
            hi = max(op, cl) + abs(random.gauss(0, 0.3)) * (price * 0.0003)
            lo = min(op, cl) - abs(random.gauss(0, 0.3)) * (price * 0.0003)
            candles.append((op, cl, hi, lo))
            price = cl

        dpi = 88
        fig = Figure(figsize=(4, 2.5), dpi=dpi, facecolor="#0D0D0D")
        ax  = fig.add_subplot(111)
        ax.set_facecolor("#0D0D0D")
        fig.subplots_adjust(left=0.02, right=0.90, top=0.92, bottom=0.06)
        for sp in ax.spines.values():
            sp.set_color("#2A2A2A")
        ax.tick_params(colors="#555555", labelsize=6)
        ax.yaxis.tick_right()
        ax.grid(True, color="#1C1C1C", linewidth=0.4, linestyle="--", alpha=0.6)

        w = 0.5
        for i, (op, cl, hi, lo) in enumerate(candles):
            c = POSITIVE if cl >= op else NEGATIVE
            ax.plot([i, i], [lo, hi], color=c, linewidth=0.7, alpha=0.6)
            bh = abs(cl - op) or abs(hi - lo) * 0.05
            import matplotlib.patches as mptch
            ax.add_patch(mptch.FancyBboxPatch(
                (i - w/2, min(op, cl)), w, bh,
                boxstyle="square,pad=0",
                linewidth=0, facecolor=c, alpha=0.85))

        ax.set_xlim(-1, n)
        cv = FigureCanvasTkAgg(fig, master=parent)
        cv.draw()
        cv.get_tk_widget().pack(fill="both", expand=True)

    def _draw_canvas_chart(self, parent: tk.Frame, side: str, color: str) -> None:
        cv = tk.Canvas(parent, bg="#0D0D0D", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        random.seed(42 if side == "long" else 77)

        def _draw(e=None):
            cv.delete("all")
            W = cv.winfo_width();  H = cv.winfo_height()
            if W < 20 or H < 20: return
            n     = 35
            trend = 0.25 if side == "long" else -0.25
            price = 100.0
            cands = []
            for _ in range(n):
                op = price
                cl = op + random.gauss(trend, 1.0)
                hi = max(op, cl) + abs(random.gauss(0, 0.4))
                lo = min(op, cl) - abs(random.gauss(0, 0.4))
                cands.append((op, cl, hi, lo))
                price = cl

            mn = min(c[3] for c in cands)
            mx = max(c[2] for c in cands)
            rng = mx - mn or 1
            bw  = max(4, (W - 16) // n)

            def py(p): return int(H * 0.92 - (p - mn) / rng * H * 0.82)

            for i, (op, cl, hi, lo) in enumerate(cands):
                x  = 8 + i * bw + bw // 2
                c  = POSITIVE if cl >= op else NEGATIVE
                cv.create_line(x, py(hi), x, py(lo), fill=c, width=1)
                y1, y2 = sorted([py(op), py(cl)])
                if y2 - y1 < 1: y2 = y1 + 1
                cv.create_rectangle(x - bw//2 + 1, y1,
                                    x + bw//2 - 1, y2, fill=c, outline="")

        cv.bind("<Configure>", _draw)
        cv.after(60, _draw)


# ── Entry ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    _root = tk.Tk()
    _root.withdraw()
    app = BottomModuleMockup(_root)
    app.mainloop()
