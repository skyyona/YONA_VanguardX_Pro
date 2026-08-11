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
    from bottom.engine_core.fourtf_consensus import FourTFConsensus
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
    from bottom.engine_core.trading_engine import TradingEngine
    from bottom.strategy_settings.strategy_loader import StrategyLoader
    from bottom.models import PositionState, ProhibitionFlags
    _HAS_ENGINE = True
except ImportError:
    TradingEngine    = None   # type: ignore[misc,assignment]
    StrategyLoader   = None   # type: ignore[misc,assignment]
    ProhibitionFlags = None   # type: ignore[misc,assignment]
    class PositionState:    # type: ignore[misc]
        OPEN = "open"
    _HAS_ENGINE = False

try:
    from bottom.engine_core.sort_mode_config import get_mode_config as _get_mode_cfg
except ImportError:
    def _get_mode_cfg(m: str):   # type: ignore[misc]
        from types import SimpleNamespace
        return SimpleNamespace(
            direction_bias="both", k_long_max=20.0, k_short_min=80.0,
            quality_grade_req=None, volume_mult=None,
            atr_min=0.3, atr_max=8.0, requires_swing=False, macro_ema=False)

try:
    from bottom.backtest.historical_data_loader import HistoricalDataLoader
    from bottom.backtest.backtest_runner import BacktestRunner
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


# ── 헥스 색상 보간 (발광 펄스 애니메이션용) ───────────────────────
def _lerp_hex(c0: str, c1: str, t: float) -> str:
    r0, g0, b0 = int(c0[1:3], 16), int(c0[3:5], 16), int(c0[5:7], 16)
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r = int(r0 + (r1 - r0) * t)
    g = int(g0 + (g1 - g0) * t)
    b = int(b0 + (b1 - b0) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


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

TF_KEYS = ["1m", "3m", "5m", "15m"]
TF_W    = 76   # 각 TF 컬럼 너비(px)

_BASE_SL,    _BASE_TRAIL = 2.5,  1.5


def _backtest_result_to_dict(result: "BacktestResult") -> dict:  # type: ignore[name-defined]
    """BacktestResult → _populate_tab2() 가 기대하는 dict 구조로 변환."""
    long_trades  = [t for t in result.trades if t.side == "long"]
    short_trades = [t for t in result.trades if t.side == "short"]

    def _side_stats(trades: list, period_days: int) -> dict:
        if not trades:
            return {"count": 0, "hit": "0%", "avg": "—", "max": "—",
                    "total": "—", "rr_ratio": "—", "profit_factor": "—",
                    "avg_loss": "—", "avg_hold": "—",
                    "max_consec_loss": "0회", "daily_freq": "0.00회"}
        wins   = [t for t in trades if t.pnl_pct > 0]
        losses = [t for t in trades if t.pnl_pct <= 0]
        wr      = len(wins) / len(trades) * 100
        avg_w   = sum(t.pnl_pct for t in wins)   / max(len(wins),   1)
        avg_l   = sum(t.pnl_pct for t in losses) / max(len(losses), 1)
        mx      = max(t.pnl_pct for t in trades)
        tot     = sum(t.pnl_pct for t in trades)
        rr      = abs(avg_w / avg_l) if avg_l != 0 else 0
        pf_num  = sum(t.pnl_pct for t in wins)
        pf_den  = abs(sum(t.pnl_pct for t in losses)) if losses else 0
        pf      = pf_num / pf_den if pf_den > 0 else 0
        hold_ms = [t.exit_time - t.entry_time for t in trades
                   if t.exit_time > t.entry_time]
        avg_min = (sum(hold_ms) / len(hold_ms) / 60000) if hold_ms else 0
        consec = max_consec = 0
        for t in trades:
            if t.pnl_pct <= 0:
                consec += 1; max_consec = max(max_consec, consec)
            else:
                consec = 0
        freq = len(trades) / max(period_days, 1)
        return {
            "count":           len(trades),
            "hit":             f"{wr:.0f}%",
            "avg":             f"{avg_w:+.1f}%" if wins   else "—",
            "max":             f"{mx:+.1f}%",
            "total":           f"{tot:+.1f}%",
            "rr_ratio":        f"{rr:.1f} : 1"  if losses else "—",
            "profit_factor":   f"{pf:.2f}"       if losses else "—",
            "avg_loss":        f"{avg_l:.1f}%"   if losses else "—",
            "avg_hold":        f"{avg_min:.0f}분",
            "max_consec_loss": f"{max_consec}회",
            "daily_freq":      f"{freq:.2f}회",
        }

    pd_ = result.period_days
    return {
        "long_align":  len(long_trades),
        "short_align": len(short_trades),
        "next_est":    "—",
        "long":        _side_stats(long_trades,  pd_),
        "short":       _side_stats(short_trades, pd_),
        "total": {
            "return": f"{result.total_return:+.1f}%",
            "win":    f"{result.win_rate:.0f}%",
            "max":    f"{result.max_profit:+.1f}%",
            "mdd":    f"-{result.max_drawdown:.1f}%",
        },
    }


# ══════════════════════════════════════════════════════════════════
class BottomModuleMockup(tk.Frame):
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
        if self._shared_sort_mode is not None:
            self._shared_sort_mode.trace_add("write", self._on_sort_mode_watch)

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
    def _build_strategy_header(self) -> None:
        hdr = tk.Frame(self, bg=DARK_HEADER, pady=1)
        hdr.pack(fill="x")

        # ┌─ 섹션① 좌: Selected Symbol → [심볼] [Clear] ────────────
        sec1 = tk.Frame(hdr, bg=DARK_HEADER)
        sec1.pack(side="left", padx=(14, 0))

        tk.Label(sec1, text="Selected  Symbol", bg=DARK_HEADER, fg=DIM_TEXT,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Label(sec1, text="  →  ", bg=DARK_HEADER, fg=DIM_TEXT,
                 font=("Segoe UI", 8)).pack(side="left")

        self._sym_lbl = tk.Label(sec1, text="— 미배치 —",
                                  bg=DARK_HEADER, fg=DIM_TEXT,
                                  font=("Segoe UI", 10, "bold"))
        self._sym_lbl.pack(side="left")

        self._clear_btn = tk.Button(
            sec1, text="  ✖  Clear  ",
            bg="#2A1A1A", fg="#666666",
            activebackground="#3A1A1A", activeforeground=NEGATIVE,
            font=("Segoe UI", 8, "bold"), relief="flat", padx=8, pady=1,
            cursor="hand2", state="disabled",
            command=self._clear_symbol)
        self._clear_btn.pack(side="left", padx=(10, 0))

        # ┌─ 섹션④ 우: [거래 활성화] ── 심볼+전략 모두 충족 시만 활성 ─
        sec4 = tk.Frame(hdr, bg=DARK_HEADER)
        sec4.pack(side="right", padx=(0, 14))
        self._trade_btn = tk.Button(
            sec4, text="  거래 활성화  ",
            bg="#252525", fg="#888888",
            activebackground="#303030", activeforeground=DARK_TEXT,
            font=("Segoe UI", 9, "bold"), relief="flat", padx=8, pady=2,
            cursor="arrow", state="disabled",
            command=self._toggle_trading)
        self._trade_btn.pack(anchor="center")

        # ┌─ 섹션② 중: fill="x"+expand 로 남은 공간 확보 ─────────
        # inner 프레임을 expand=True(fill 없음) 으로 pack → 자동 중앙 정렬
        # 구분선(padx=10)으로 버튼 간 균일 간격 확보
        sec_mid = tk.Frame(hdr, bg=DARK_HEADER)
        sec_mid.pack(side="left", fill="x", expand=True)

        tk.Frame(sec_mid, bg=DARK_HEADER).pack(side="left", expand=True)

        inner = tk.Frame(sec_mid, bg=DARK_HEADER)
        inner.pack(side="left")

        tk.Frame(sec_mid, bg=DARK_HEADER).pack(side="left", expand=True)

        self._strategy_btn = tk.Button(
            inner,
            text="  Selected Coin Symbol Stoch RSI Strategy  /  Applied Backtest  ",
            bg="#252525", fg="#888888",
            activebackground="#303030", activeforeground=DARK_TEXT,
            font=("Segoe UI", 8, "bold"), relief="flat", padx=8, pady=2,
            cursor="arrow", state="disabled",
            command=self._open_strategy_window)
        self._strategy_btn.pack(side="left")

        tk.Frame(inner, bg="#333333", width=1).pack(
            side="left", fill="y", pady=4, padx=10)

        self._strategy_msg = tk.Label(
            inner, text="  — 전략 미설정 —  ",
            bg=DARK_HEADER, fg=DIM_TEXT,
            font=("Segoe UI", 8, "bold"), width=22)
        self._strategy_msg.pack(side="left")

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

    def _clear_symbol(self) -> None:
        if self._trading_active:
            return
        self._shared_sym.set("")

    def _on_sort_mode_watch(self, *_) -> None:
        """Sort by 모드 변경 감지 → 전략 재확정 필요 경고 표시."""
        if not self._strategy_ready:
            return
        if self._shared_sort_mode is None:
            return
        new_mode = self._shared_sort_mode.get()
        if new_mode and new_mode != self._applied_sort_mode:
            if self._strategy_msg is not None:
                self._strategy_msg.configure(
                    text=f"  ⚠ Sort [{new_mode}] 변경 — 전략 재확정 필요  ",
                    fg=ORANGE)

    def _restore_strategy_vars(self, sort_mode: str) -> None:
        """sort_mode에 저장된 전략 설정을 UI vars에 복원한다."""
        if StrategyLoader is None:
            return
        loaded = StrategyLoader.load(sort_mode)
        if loaded is None:
            return
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

    # ══════════════════════════════════════════════════════════════
    # 전략 설정 & 백테스팅 팝업창 (단일 페이지)
    # ══════════════════════════════════════════════════════════════
    def _open_strategy_window(self) -> None:
        sym = self._shared_sym.get()
        if not sym:
            return

        win = tk.Toplevel(self)
        win.title(f"🧠  {sym} — 4TF 완전 정렬 Stoch RSI 전략 설정 및 백테스팅")
        win.configure(bg=DARK_BG)
        win.geometry("1320x640")
        win.minsize(1200, 560)
        win.grab_set()

        avail_days_ref:      list = [90]
        _bars_ref:           list = [[]]    # [list[HistoricalBar]] — 로딩 완료 후 채워짐
        _data_fetched_ref:   list = [False] # [bool] — 로딩 완료 플래그
        _selected_sort_ref:  list = ["24h Ticker"]  # 전략 창 내 Sort by 선택값

        # ── ① 하단 푸터 — 3단 구조 (side="bottom" 역순 pack) ─────

        # [최하단] 전략 확정 행
        footer_confirm = tk.Frame(win, bg=DARK_HEADER, pady=6)
        footer_confirm.pack(fill="x", side="bottom")
        tk.Frame(footer_confirm, bg="#2A2A2A", height=1).pack(fill="x")
        tk.Button(footer_confirm,
                  text="  ✅  전략 확정 및 적용  ",
                  bg="#0A2A12", fg=POSITIVE,
                  activebackground="#0A3A18", activeforeground=POSITIVE,
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=14, pady=4,
                  cursor="hand2",
                  command=lambda: self._confirm_strategy(win, _selected_sort_ref[0])
                  ).pack(anchor="center", pady=(4, 0))

        # [중간] 백테스팅 결과 요약 (항상 표시 — 백테스팅 전: "—", 후: 실제값)
        footer_mid = tk.Frame(win, bg=DARK_PANEL, pady=4)
        footer_mid.pack(fill="x", side="bottom")
        tk.Frame(footer_mid, bg="#2A2A2A", height=1).pack(fill="x")

        _stat_label_items = [
            ("4TF 정렬 적중도",       "hit"),
            ("단일 거래 최대 수익률", "max"),
            ("기간 총 수익률",        "total"),
        ]
        _stat_rows: list[dict] = []
        for lbl_text, key in _stat_label_items:
            sr = tk.Frame(footer_mid, bg=DARK_PANEL)
            sr.pack(fill="x", padx=16, pady=1)
            tk.Label(sr, text=f"  ●  {lbl_text}",
                     bg=DARK_PANEL, fg=DIM_TEXT,
                     font=("Segoe UI", 7, "bold"),
                     width=22, anchor="w").pack(side="left")
            long_lbl = tk.Label(sr, text="롱 :   —",
                                bg=DARK_PANEL, fg=DIM_TEXT,
                                font=("Consolas", 8, "bold"),
                                width=14, anchor="center")
            long_lbl.pack(side="left", padx=(12, 4))
            short_lbl = tk.Label(sr, text="숏 :   —",
                                 bg=DARK_PANEL, fg=DIM_TEXT,
                                 font=("Consolas", 8, "bold"),
                                 width=14, anchor="center")
            short_lbl.pack(side="left", padx=(4, 0))
            _stat_rows.append({"long": long_lbl, "short": short_lbl, "key": key})

        tk.Frame(footer_mid, bg="#2A2A2A", height=1).pack(fill="x")

        # [상단] 백테스팅 버튼 행
        footer_row1 = tk.Frame(win, bg=DARK_HEADER, pady=6)
        footer_row1.pack(fill="x", side="bottom")
        tk.Frame(footer_row1, bg="#2A2A2A", height=1).pack(fill="x")

        _ap = self._applied_params
        if self._strategy_ready and _ap is not None:
            _fl_text = f"  ✓  Funds {_ap['funds']}%   |   {_ap['leverage']}x  "
            _sl_text = f"  ✓  SL {_ap['sl']:.1f}%   |   Trail {_ap['trail']:.1f}%  "
            _btn_kw  = dict(bg="#0D2A1A", fg=POSITIVE,
                            activebackground="#0A3A18", activeforeground=POSITIVE)
        else:
            _fl_text = "  Designated Funds  &  Applied Leverage  "
            _sl_text = "  Stop Loss  &  Trailing Stop  "
            _btn_kw  = dict(bg=DARK_PANEL, fg=DIM_TEXT,
                            activebackground="#252525", activeforeground=DARK_TEXT)

        self._funds_lev_btn = tk.Button(
            footer_row1, text=_fl_text,
            font=("Segoe UI", 8, "bold"), relief="flat", padx=8, pady=4,
            cursor="hand2",
            command=self._open_funds_lev_window, **_btn_kw)
        self._funds_lev_btn.pack(side="left", padx=(12, 0), pady=(4, 0))

        tk.Frame(footer_row1, bg="#333333", width=1).pack(
            side="left", fill="y", pady=6, padx=6)

        self._sl_trail_btn = tk.Button(
            footer_row1, text=_sl_text,
            font=("Segoe UI", 8, "bold"), relief="flat", padx=8, pady=4,
            cursor="hand2",
            command=self._open_sl_trail_window, **_btn_kw)
        self._sl_trail_btn.pack(side="left", pady=(4, 0))

        tk.Frame(footer_row1, bg="#333333", width=1).pack(
            side="left", fill="y", pady=6, padx=6)

        bt_btn = tk.Button(footer_row1, text="  ▶  백테스팅  ",
                           bg=DARK_PANEL, fg=ACCENT_BLUE,
                           activebackground="#252525", activeforeground=ACCENT_BLUE,
                           font=("Segoe UI", 8, "bold"), relief="flat",
                           padx=10, pady=4, cursor="hand2",
                           state="disabled")
        bt_btn.pack(side="left", padx=(12, 0), pady=(4, 0))

        # 합의 모드 선택 Combobox — 방안 A
        _consensus_var = tk.StringVar(value="4/4")
        _consensus_cb = ttk.Combobox(
            footer_row1,
            textvariable=_consensus_var,
            values=["3/4", "4/4", "anchor3", "anchor2"],
            state="readonly", width=8,
            font=("Segoe UI", 7),
        )
        _consensus_cb.pack(side="left", padx=(8, 0), pady=(4, 0))

        # 4모드 비교 버튼 — 방안 B
        cmp_btn = tk.Button(footer_row1, text="  📊  4모드 비교  ",
                            bg=DARK_PANEL, fg=DIM_TEXT,
                            activebackground="#252525",
                            activeforeground=DARK_TEXT,
                            font=("Segoe UI", 8), relief="flat",
                            padx=8, pady=4, cursor="hand2",
                            state="disabled")
        cmp_btn.pack(side="left", padx=(6, 0), pady=(4, 0))

        restart_btn = tk.Button(footer_row1, text="  🔄  재실행  ",
                                bg=DARK_PANEL, fg=DIM_TEXT,
                                activebackground="#2A2A2A",
                                activeforeground=DARK_TEXT,
                                font=("Segoe UI", 8), relief="flat",
                                padx=10, pady=4, cursor="hand2")
        restart_btn.pack(side="right", padx=(0, 12), pady=(4, 0))

        # ── ② 헤더 바 ────────────────────────────────────────────
        hdr = tk.Frame(win, bg=DARK_HEADER, pady=8)
        hdr.pack(fill="x")

        # 좌: 심볼
        tk.Label(hdr, text=f"  Selected Symbol  →  ",
                 bg=DARK_HEADER, fg=DIM_TEXT,
                 font=("Segoe UI", 7, "bold")).pack(side="left")
        tk.Label(hdr, text=sym,
                 bg=DARK_HEADER, fg=POSITIVE,
                 font=("Segoe UI", 10, "bold")).pack(side="left")

        # 우: 상태 메시지
        status_lbl = tk.Label(hdr, text="  —  ",
                              bg=DARK_HEADER, fg=DIM_TEXT,
                              font=("Segoe UI", 8, "bold"))
        status_lbl.pack(side="right", padx=(0, 16))

        # 중: [데이터 로딩] 버튼 + 프로그레스 바
        center_f = tk.Frame(hdr, bg=DARK_HEADER)
        center_f.pack(side="left", expand=True)

        load_btn = tk.Button(center_f, text="  📥  데이터 로딩  ",
                             bg=DARK_PANEL, fg=ACCENT_BLUE,
                             activebackground="#252525",
                             activeforeground=ACCENT_BLUE,
                             font=("Segoe UI", 8, "bold"),
                             relief="flat", padx=8, pady=4,
                             cursor="hand2")
        load_btn.pack(side="left", padx=(24, 10))

        prog_cv = tk.Canvas(center_f, bg="#1A1A1A", height=14, width=200,
                            highlightthickness=1,
                            highlightbackground="#333333")
        prog_cv.pack(side="left")

        # ── ③ 기간 바 ────────────────────────────────────────────
        period_bar = tk.Frame(win, bg=DARK_PANEL, pady=5)
        period_bar.pack(fill="x")
        period_lbl = tk.Label(period_bar, text="  분석 기간  —",
                              bg=DARK_PANEL, fg=DIM_TEXT,
                              font=("Segoe UI", 8, "bold"))
        period_lbl.pack(side="left", padx=(14, 0))
        period_sub = tk.Label(period_bar,
                              text="  (데이터 로딩 후 자동 감지)",
                              bg=DARK_PANEL, fg=DIM_TEXT,
                              font=("Segoe UI", 7))
        period_sub.pack(side="left", padx=(4, 0))

        # ── ④ 탭 바 ──────────────────────────────────────────────
        tab_bar_f = tk.Frame(win, bg=DARK_HEADER)
        tab_bar_f.pack(fill="x")
        tk.Frame(tab_bar_f, bg="#2A2A2A", height=1).pack(
            fill="x", side="bottom")

        _TAB_SEL   = {"bg": DARK_PANEL,  "fg": ACCENT_BLUE,
                      "activebackground": DARK_PANEL,
                      "activeforeground": ACCENT_BLUE,
                      "font": ("Segoe UI", 8, "bold")}
        _TAB_UNSEL = {"bg": DARK_HEADER, "fg": DIM_TEXT,
                      "activebackground": "#303030",
                      "activeforeground": DARK_TEXT,
                      "font": ("Segoe UI", 8)}
        _TAB_DIS   = {"bg": DARK_HEADER, "fg": "#3A3A3A",
                      "activebackground": DARK_HEADER,
                      "activeforeground": "#3A3A3A",
                      "font": ("Segoe UI", 8)}

        tab1_btn = tk.Button(tab_bar_f,
                             text="  📋  Sort by 일치 4TF 완전 합의 전략 설정  ",
                             relief="flat", padx=10, pady=6,
                             cursor="arrow", state="disabled",
                             **_TAB_DIS)
        tab1_btn.pack(side="left")
        tk.Frame(tab_bar_f, bg="#333333", width=1).pack(
            side="left", fill="y", pady=4)
        tab_ban_btn = tk.Button(tab_bar_f,
                             text="  ⛔  절대 거래 금지 체크 항목  ",
                             relief="flat", padx=10, pady=6,
                             cursor="arrow", state="disabled",
                             **_TAB_DIS)
        tab_ban_btn.pack(side="left")
        tk.Frame(tab_bar_f, bg="#333333", width=1).pack(
            side="left", fill="y", pady=4)
        tab2_btn = tk.Button(tab_bar_f,
                             text="  📊  4TF 완전 합의 백테스팅  ",
                             relief="flat", padx=10, pady=6,
                             cursor="arrow", state="disabled",
                             **_TAB_DIS)
        tab2_btn.pack(side="left")

        # ── ⑤ 탭 콘텐츠 영역 ─────────────────────────────────────
        tab_content = tk.Frame(win, bg=DARK_BG)
        tab_content.pack(fill="both", expand=True)

        tab1_frame   = tk.Frame(tab_content, bg=DARK_BG)
        tab_ban_frame = tk.Frame(tab_content, bg=DARK_BG)
        tab2_frame   = tk.Frame(tab_content, bg=DARK_BG)
        tab1_frame.pack(fill="both", expand=True)

        hint_lbl_ref:  list = [None]
        ban_hint_ref:  list = [None]
        tab2_hint_ref: list = [None]
        _auto_filter_refresh_ref: list = [None]   # 자동 필터 재렌더링 함수 참조

        def _make_hint_lbl() -> None:
            lbl = tk.Label(tab1_frame,
                           text="[📥 데이터 로딩] 버튼을 클릭하면\n"
                                "선택한 코인 심볼의 4TF 완전 정렬 조건을 분석합니다",
                           bg=DARK_BG, fg=DIM_TEXT,
                           font=("Segoe UI", 10), justify="center")
            lbl.pack(expand=True)
            hint_lbl_ref[0] = lbl

        def _make_ban_hint() -> None:
            lbl = tk.Label(tab_ban_frame,
                           text="[📥 데이터 로딩] 버튼을 클릭하면\n"
                                "이 전략에 적용할 절대 거래 금지 조건을 설정할 수 있습니다",
                           bg=DARK_BG, fg=DIM_TEXT,
                           font=("Segoe UI", 10), justify="center")
            lbl.pack(expand=True)
            ban_hint_ref[0] = lbl

        def _make_tab2_hint() -> None:
            lbl = tk.Label(tab2_frame,
                           text="[▶ 백테스팅] 버튼을 클릭하면\n"
                                "4TF 완전 정렬 백테스팅 결과가 이 탭에 표시됩니다",
                           bg=DARK_BG, fg=DIM_TEXT,
                           font=("Segoe UI", 10), justify="center")
            lbl.pack(expand=True)
            tab2_hint_ref[0] = lbl

        _make_hint_lbl()
        _make_ban_hint()
        _make_tab2_hint()

        _TAB_FRAMES = {1: tab1_frame, 2: tab2_frame, 3: tab_ban_frame}
        _TAB_BTNS   = {1: tab1_btn,   2: tab2_btn,   3: tab_ban_btn}

        def _show_tab(n: int) -> None:
            for i, f in _TAB_FRAMES.items():
                if i != n:
                    f.pack_forget()
            _TAB_FRAMES[n].pack(fill="both", expand=True)

            for i, b in _TAB_BTNS.items():
                if i == n:
                    b.configure(**_TAB_SEL)
                elif str(b["state"]) == "disabled":
                    b.configure(**_TAB_DIS)
                else:
                    b.configure(**_TAB_UNSEL)

        # ── 로딩 애니메이션 ──────────────────────────────────────
        def _animate(step: int, total: int = 40) -> None:
            ratio = step / total
            W = prog_cv.winfo_width() or 200
            prog_cv.delete("all")
            prog_cv.create_rectangle(
                0, 0, int(W * ratio), 14, fill=ACCENT_BLUE, outline="")
            prog_cv.create_text(
                W // 2, 7, text=f"{int(ratio * 100)}%",
                fill="#FFFFFF", font=("Consolas", 7, "bold"))
            if step < total:
                prog_cv.after(55, lambda: _animate(step + 1, total))
            else:
                status_lbl.configure(
                    text="  데이터 로딩 완료  ", fg=POSITIVE)
                prog_cv.after(500, _start_analysis)

        def _start_analysis() -> None:
            """데이터 로딩 완료 대기 → 완료 시 _analysis_done() 호출."""
            status_lbl.configure(text="  패턴 분석 중...  ", fg=YELLOW)
            _check_data_ready()

        def _check_data_ready() -> None:
            """_data_fetched_ref[0]이 True가 될 때까지 100ms 폴링."""
            if _data_fetched_ref[0]:
                prog_cv.after(0, _analysis_done)
            else:
                prog_cv.after(100, _check_data_ready)

        def _get_avail_days() -> int:
            """로딩된 HistoricalBar 목록으로부터 실제 가용 일수 계산."""
            bars = _bars_ref[0]
            if not bars:
                return 0
            span_ms = bars[-1].close_time - bars[0].open_time
            return max(1, int(span_ms / 86_400_000))

        def _get_period_key(avail: int) -> str:
            if avail >= 90: return "90일"
            if avail >= 30: return "30일"
            if avail >= 14: return "14일"
            return "7일"

        def _analysis_done() -> None:
            if not _bars_ref[0]:
                status_lbl.configure(text="  데이터 없음 — 다시 시도해 주세요  ", fg=NEGATIVE)
                load_btn.configure(state="normal", cursor="hand2")
                return

            avail = _get_avail_days()
            avail_days_ref[0] = avail

            if avail >= 90:
                period_lbl.configure(
                    text="  분석 기간  90일 기준", fg=ACCENT_BLUE)
                period_sub.configure(
                    text="  (90일치 데이터 기준 — 신뢰도 높음)", fg=DIM_TEXT)
            elif avail >= 14:
                period_lbl.configure(
                    text=f"  분석 기간  {avail}일 기준"
                         f"  (상장 {avail}일차 심볼)", fg=YELLOW)
                period_sub.configure(
                    text="  ⚠️ 90일 미만 — 가용 데이터 전체 기간으로 분석",
                    fg=YELLOW)
            else:
                period_lbl.configure(
                    text=f"  분석 기간  {avail}일 기준  ⚠️ 데이터 부족",
                    fg=NEGATIVE)
                period_sub.configure(
                    text="  ⚠️ 상장 14일 미만 — 분석 신뢰도 매우 낮음",
                    fg=NEGATIVE)

            status_lbl.configure(text="  패턴 분석 완료  ✓  ", fg=POSITIVE)
            if hint_lbl_ref[0]:
                hint_lbl_ref[0].pack_forget()
            _populate_tab1()

            if ban_hint_ref[0]:
                ban_hint_ref[0].pack_forget()
            _populate_tab_ban()

            tab1_btn.configure(state="normal", cursor="hand2", **_TAB_SEL)
            tab_ban_btn.configure(state="normal", cursor="hand2", **_TAB_UNSEL)
            tab2_btn.configure(state="disabled", cursor="arrow", **_TAB_DIS)
            _show_tab(1)
            load_btn.configure(state="normal", cursor="hand2",
                               text="  🔄  재로딩  ")
            bt_btn.configure(state="normal", cursor="hand2")
            cmp_btn.configure(state="normal", cursor="hand2")

        def _populate_tab1() -> None:
            for w in tab1_frame.winfo_children():
                w.destroy()

            def _sec_hdr(parent: tk.Frame, text: str) -> None:
                f = tk.Frame(parent, bg=DARK_HEADER, pady=3)
                f.pack(fill="x", pady=(8, 0))
                tk.Label(f, text=f"  {text}",
                         bg=DARK_HEADER, fg=ACCENT_BLUE,
                         font=("Segoe UI", 8, "bold")).pack(
                             side="left", padx=6)

            def _cond_row(parent: tk.Frame, icon: str, icon_col: str,
                          cond: str, cond_col: str, desc: str) -> None:
                rw = tk.Frame(parent, bg=DARK_PANEL, pady=4)
                rw.pack(fill="x")
                tk.Label(rw, text=f"  {icon}",
                         bg=DARK_PANEL, fg=icon_col,
                         font=("Segoe UI", 9)).pack(side="left", padx=(8, 4))
                tk.Label(rw, text=cond,
                         bg=DARK_PANEL, fg=cond_col,
                         font=("Consolas", 8, "bold")).pack(side="left")
                tk.Label(rw, text=f"  ({desc})",
                         bg=DARK_PANEL, fg=DIM_TEXT,
                         font=("Segoe UI", 7)).pack(side="left")

            def _state_row(parent: tk.Frame, cond: str,
                           result: str, res_col: str) -> None:
                rw = tk.Frame(parent, bg=DARK_PANEL, pady=3)
                rw.pack(fill="x")
                tk.Label(rw, text=f"  ●  {cond}",
                         bg=DARK_PANEL, fg=DIM_TEXT,
                         font=("Segoe UI", 7),
                         width=24, anchor="w").pack(side="left", padx=(8, 2))
                tk.Label(rw, text=result,
                         bg=DARK_PANEL, fg=res_col,
                         font=("Segoe UI", 7, "bold")).pack(side="left")

            SORT_OPTIONS = ["24h Ticker", "Sharp rise", "Sharp decline",
                            "Volatility", "4TF Optimization", "Newly Listed"]

            # ── 거시적 추세 연동 토글 ────────────────────────────────
            macro_bar = tk.Frame(tab1_frame, bg=DARK_HEADER, pady=5)
            macro_bar.pack(fill="x")
            tk.Checkbutton(
                macro_bar,
                text="  ☑  거시적 추세(1H · 4H · 1D) 방향 연동"
                     "  —  체크 해제 시 국지적 4TF 과반(3/4 이상) 기준으로만 판단",
                variable=self._use_macro_var,
                bg=DARK_HEADER, fg=DARK_TEXT,
                activebackground=DARK_HEADER, activeforeground=DARK_TEXT,
                selectcolor=DARK_PANEL,
                font=("Segoe UI", 8), relief="flat", cursor="hand2",
            ).pack(anchor="w", padx=10)

            # ── 안내 배너 (선택된 Sort by 항목 표시) ───────────────────
            info_bar = tk.Frame(tab1_frame, bg="#1A1008", pady=4)
            info_bar.pack(fill="x")
            info_lbl = tk.Label(info_bar, text="",
                                 bg="#1A1008", fg=YELLOW,
                                 font=("Segoe UI", 7, "bold"))
            info_lbl.pack(anchor="center")

            # ── 3컬럼 컨테이너 (Sort by 사이드바 | 롱 | 숏) ─────────────
            body_3col = tk.Frame(tab1_frame, bg=DARK_BG)
            body_3col.pack(fill="both", expand=True)

            sortby_col = tk.Frame(body_3col, bg=DARK_PANEL, width=150)
            sortby_col.pack(side="left", fill="y")
            sortby_col.pack_propagate(False)
            tk.Frame(body_3col, bg="#333333", width=1).pack(
                side="left", fill="y")

            long_col = tk.Frame(body_3col, bg=DARK_BG)
            long_col.pack(side="left", fill="both", expand=True)
            tk.Frame(body_3col, bg="#333333", width=1).pack(
                side="left", fill="y")
            short_col = tk.Frame(body_3col, bg=DARK_BG)
            short_col.pack(side="left", fill="both", expand=True)

            # ── Sort by 사이드바 ────────────────────────────────────
            sb_hdr = tk.Frame(sortby_col, bg=DARK_HEADER, pady=6)
            sb_hdr.pack(fill="x")
            tk.Label(sb_hdr, text="  Sort by  항목",
                     bg=DARK_HEADER, fg=ACCENT_BLUE,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w")

            sort_btns: dict[str, tk.Button] = {}

            def _select_sort_item(mode: str) -> None:
                _selected_sort_ref[0] = mode   # 전략 창 내 선택값 저장 → 백테스팅·확정에 전달
                self._restore_strategy_vars(mode)
                for opt, b in sort_btns.items():
                    sel = (opt == mode)
                    b.configure(
                        bg="#1E2A1E" if sel else DARK_PANEL,
                        fg=POSITIVE if sel else DARK_TEXT,
                        font=("Segoe UI", 8, "bold" if sel else "normal"))
                cfg = _get_mode_cfg(mode)
                _bias_map = {
                    "both":       "롱·숏 양방향",
                    "long_only":  "롱 전용",
                    "short_only": "숏 전용",
                }
                _bias_str = _bias_map.get(cfg.direction_bias, "양방향")
                _extra = ""
                if cfg.quality_grade_req is not None:
                    _extra += f"  |  {cfg.quality_grade_req}등급+"
                if cfg.volume_mult is not None:
                    _extra += f"  |  거래량 {cfg.volume_mult:.1f}x+"
                if cfg.macro_ema:
                    _extra += "  |  EMA 거시"
                if cfg.requires_swing:
                    _extra += "  |  스윙 구조"
                info_lbl.configure(
                    text=(f"ℹ️   [{mode}]  {_bias_str}"
                          f"  |  K롱<{cfg.k_long_max:.0f} · K숏>{cfg.k_short_min:.0f}"
                          f"  |  ATR {cfg.atr_min:.1f}~{cfg.atr_max:.1f}%{_extra}"))
                _render_strategy_cols(mode)
                if _auto_filter_refresh_ref[0] is not None:
                    _auto_filter_refresh_ref[0]()

            for opt in SORT_OPTIONS:
                b = tk.Button(sortby_col, text=f"  {opt}",
                              bg=DARK_PANEL, fg=DARK_TEXT,
                              activebackground="#2A3A2A",
                              activeforeground=POSITIVE,
                              font=("Segoe UI", 8), relief="flat",
                              anchor="w", padx=8, pady=6,
                              cursor="hand2",
                              command=lambda o=opt: _select_sort_item(o))
                b.pack(fill="x", pady=1)
                sort_btns[opt] = b

            # ── 롱/숏 전략 내용 렌더링 (Sort by 모드별) ────────────
            def _render_strategy_cols(mode: str) -> None:
                for w in long_col.winfo_children():
                    w.destroy()
                for w in short_col.winfo_children():
                    w.destroy()

                cfg = _get_mode_cfg(mode)

                def _extra_filter_row(parent: tk.Frame, label: str,
                                      value: str, col: str) -> None:
                    rw = tk.Frame(parent, bg=DARK_PANEL, pady=3)
                    rw.pack(fill="x")
                    tk.Label(rw, text="  ▸",
                             bg=DARK_PANEL, fg=col,
                             font=("Segoe UI", 8, "bold")).pack(side="left", padx=(8, 2))
                    tk.Label(rw, text=label,
                             bg=DARK_PANEL, fg=DIM_TEXT,
                             font=("Segoe UI", 7), width=14, anchor="w").pack(side="left")
                    tk.Label(rw, text=value,
                             bg=DARK_PANEL, fg=col,
                             font=("Consolas", 7, "bold")).pack(side="left")

                # ── 롱 포지션 컬럼 ──────────────────────────────────
                col_hdr_l = tk.Frame(long_col, bg=LONG_HDR_BG, pady=6)
                col_hdr_l.pack(fill="x")
                tk.Label(col_hdr_l, text="  📈  롱 포지션 진입 / 익절 조건",
                         bg=LONG_HDR_BG, fg=POSITIVE,
                         font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)

                if cfg.direction_bias == "short_only":
                    # 이 모드에서 롱 진입은 자동 차단
                    blk = tk.Frame(long_col, bg="#1A0A0A", pady=16)
                    blk.pack(fill="both", expand=True)
                    tk.Label(blk,
                             text="⛔  이 모드는 숏 전용\n롱 진입 자동 차단",
                             bg="#1A0A0A", fg=NEGATIVE,
                             font=("Segoe UI", 9, "bold"),
                             justify="center").pack(anchor="center", expand=True)
                else:
                    _sec_hdr(long_col, "4TF 완전 정렬 조건  (모두 충족 시 롱 엔진 활성)")
                    for tf in TF_KEYS:
                        rw = tk.Frame(long_col, bg=DARK_PANEL, pady=4)
                        rw.pack(fill="x")
                        tk.Label(rw, text=f"  ●  {tf}",
                                 bg=DARK_PANEL, fg=ACCENT_BLUE,
                                 font=("Segoe UI", 8, "bold"),
                                 width=7, anchor="w").pack(side="left", padx=(8, 2))
                        tk.Label(rw, text="K > D",
                                 bg=DARK_PANEL, fg=POSITIVE,
                                 font=("Consolas", 8, "bold")).pack(side="left")
                        tk.Label(rw, text="  (불리시 정렬)",
                                 bg=DARK_PANEL, fg=DIM_TEXT,
                                 font=("Segoe UI", 7)).pack(side="left")

                    _sec_hdr(long_col, "진입 조건  (4TF 정렬 상태에서)")
                    _cond_row(long_col, "▶", POSITIVE,
                              f"5m  K < {cfg.k_long_max:.0f}", POSITIVE,
                              f"과매도 구간 진입 (K 상한 {cfg.k_long_max:.0f})")
                    _cond_row(long_col, "▶", POSITIVE,
                              "K  ↑  D  상향 돌파", POSITIVE, "K선 D선 상향 돌파 + 스프레드 ≥ 2.0")

                    _sec_hdr(long_col, "모드별 추가 필터")
                    _extra_filter_row(long_col, "ATR% 범위",
                                      f"{cfg.atr_min:.1f}% ~ {cfg.atr_max:.1f}%", ACCENT_BLUE)
                    if cfg.quality_grade_req is not None:
                        _extra_filter_row(long_col, "품질 등급",
                                          f"{cfg.quality_grade_req} 등급 이상", YELLOW)
                    if cfg.volume_mult is not None:
                        _extra_filter_row(long_col, "거래량 배수",
                                          f"{cfg.volume_mult:.1f}x 이상", YELLOW)
                    if cfg.macro_ema:
                        _extra_filter_row(long_col, "EMA 거시",
                                          "EMA5 > EMA50", POSITIVE)
                    if cfg.requires_swing:
                        _extra_filter_row(long_col, "스윙 구조",
                                          "15m 상승 고저점 구조", POSITIVE)

                    _sec_hdr(long_col, "익절 조건")
                    _cond_row(long_col, "◀", NEGATIVE,
                              "1m  K > 80", NEGATIVE, "과매수 구간 도달")
                    _cond_row(long_col, "◀", NEGATIVE,
                              "K  ↓  D  하향 이탈", NEGATIVE, "K선 D선 하향 이탈 → 익절")

                    _sec_hdr(long_col, "엔진 상태 전환")
                    _state_row(long_col, "4TF K>D 정렬 감지",
                               "→  롱 엔진 활성화", POSITIVE)
                    _state_row(long_col, "4TF 정렬 해제 시",
                               "→  롱 엔진 대기", DIM_TEXT)
                    _state_row(long_col, "4TF K<D 정렬 감지",
                               "→  롱 엔진 잠금", NEGATIVE)

                # ── 숏 포지션 컬럼 ──────────────────────────────────
                col_hdr_r = tk.Frame(short_col, bg=SHORT_HDR_BG, pady=6)
                col_hdr_r.pack(fill="x")
                tk.Label(col_hdr_r, text="  📉  숏 포지션 진입 / 익절 조건",
                         bg=SHORT_HDR_BG, fg=NEGATIVE,
                         font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)

                if cfg.direction_bias == "long_only":
                    # 이 모드에서 숏 진입은 자동 차단
                    blk = tk.Frame(short_col, bg="#1A0A0A", pady=16)
                    blk.pack(fill="both", expand=True)
                    tk.Label(blk,
                             text="⛔  이 모드는 롱 전용\n숏 진입 자동 차단",
                             bg="#1A0A0A", fg=NEGATIVE,
                             font=("Segoe UI", 9, "bold"),
                             justify="center").pack(anchor="center", expand=True)
                else:
                    _sec_hdr(short_col, "4TF 완전 정렬 조건  (모두 충족 시 숏 엔진 활성)")
                    for tf in TF_KEYS:
                        rw = tk.Frame(short_col, bg=DARK_PANEL, pady=4)
                        rw.pack(fill="x")
                        tk.Label(rw, text=f"  ●  {tf}",
                                 bg=DARK_PANEL, fg=ACCENT_BLUE,
                                 font=("Segoe UI", 8, "bold"),
                                 width=7, anchor="w").pack(side="left", padx=(8, 2))
                        tk.Label(rw, text="K < D",
                                 bg=DARK_PANEL, fg=NEGATIVE,
                                 font=("Consolas", 8, "bold")).pack(side="left")
                        tk.Label(rw, text="  (베어리시 정렬)",
                                 bg=DARK_PANEL, fg=DIM_TEXT,
                                 font=("Segoe UI", 7)).pack(side="left")

                    _sec_hdr(short_col, "진입 조건  (4TF 정렬 상태에서)")
                    _cond_row(short_col, "▶", NEGATIVE,
                              f"5m  K > {cfg.k_short_min:.0f}", NEGATIVE,
                              f"과매수 구간 진입 (K 하한 {cfg.k_short_min:.0f})")
                    _cond_row(short_col, "▶", NEGATIVE,
                              "K  ↓  D  하향 이탈", NEGATIVE, "K선 D선 하향 이탈 + 스프레드 ≥ 2.0")

                    _sec_hdr(short_col, "모드별 추가 필터")
                    _extra_filter_row(short_col, "ATR% 범위",
                                      f"{cfg.atr_min:.1f}% ~ {cfg.atr_max:.1f}%", ACCENT_BLUE)
                    if cfg.quality_grade_req is not None:
                        _extra_filter_row(short_col, "품질 등급",
                                          f"{cfg.quality_grade_req} 등급 이상", YELLOW)
                    if cfg.volume_mult is not None:
                        _extra_filter_row(short_col, "거래량 배수",
                                          f"{cfg.volume_mult:.1f}x 이상", YELLOW)
                    if cfg.macro_ema:
                        _extra_filter_row(short_col, "EMA 거시",
                                          "EMA5 < EMA50", NEGATIVE)
                    if cfg.requires_swing:
                        _extra_filter_row(short_col, "스윙 구조",
                                          "15m 하락 고저점 구조", NEGATIVE)

                    _sec_hdr(short_col, "익절 조건")
                    _cond_row(short_col, "◀", POSITIVE,
                              "1m  K < 20", POSITIVE, "과매도 구간 도달")
                    _cond_row(short_col, "◀", POSITIVE,
                              "K  ↑  D  상향 돌파", POSITIVE, "K선 D선 상향 돌파 → 익절")

                    _sec_hdr(short_col, "엔진 상태 전환")
                    _state_row(short_col, "4TF K<D 정렬 감지",
                               "→  숏 엔진 활성화", NEGATIVE)
                    _state_row(short_col, "4TF 정렬 해제 시",
                               "→  숏 엔진 대기", DIM_TEXT)
                    _state_row(short_col, "4TF K>D 정렬 감지",
                               "→  숏 엔진 잠금", POSITIVE)

            # ── 초기 선택값: 중단 모듈의 현재 Sort by 모드와 동기화 ──────
            initial_mode = "24h Ticker"
            if self._shared_sort_mode is not None:
                cur = self._shared_sort_mode.get()
                if cur in SORT_OPTIONS:
                    initial_mode = cur
            _selected_sort_ref[0] = initial_mode   # 초기값 동기화
            _select_sort_item(initial_mode)

            # ── 하단 공지 바 ─────────────────────────────────────────
            notice = tk.Frame(tab1_frame, bg="#1A1008", pady=6)
            notice.pack(fill="x", side="bottom")
            tk.Label(notice,
                     text="⚡  동시 거래 절대 금지  —  "
                          "4TF 미정렬 시 양쪽 엔진 모두 대기",
                     bg="#1A1008", fg=YELLOW,
                     font=("Segoe UI", 8, "bold")).pack(anchor="center")

        # ── 절대 거래 금지 체크 항목 탭 ────────────────────────────
        def _populate_tab_ban() -> None:
            for w in tab_ban_frame.winfo_children():
                w.destroy()

            info_bar = tk.Frame(tab_ban_frame, bg="#1A1008", pady=4)
            info_bar.pack(fill="x")
            tk.Label(info_bar,
                     text="⛔  체크한 조건이 발생하면, 이 전략은 해당 조건에 한해 "
                          "롱·숏 모두 거래를 절대 실행하지 않습니다",
                     bg="#1A1008", fg=YELLOW,
                     font=("Segoe UI", 7, "bold")).pack(anchor="center")

            canvas_f = tk.Frame(tab_ban_frame, bg=DARK_BG)
            canvas_f.pack(fill="both", expand=True)
            ban_canvas = tk.Canvas(canvas_f, bg=DARK_BG, highlightthickness=0)
            ban_sb = tk.Scrollbar(canvas_f, orient="vertical",
                                   command=ban_canvas.yview)
            ban_canvas.configure(yscrollcommand=ban_sb.set)
            ban_sb.pack(side="right", fill="y")
            ban_canvas.pack(side="left", fill="both", expand=True)

            inner = tk.Frame(ban_canvas, bg=DARK_BG)
            inner_id = ban_canvas.create_window(
                (0, 0), window=inner, anchor="nw")

            def _resize(e):
                ban_canvas.configure(scrollregion=ban_canvas.bbox("all"))
                ban_canvas.itemconfig(inner_id, width=e.width)
            ban_canvas.bind("<Configure>", _resize)

            # ── Sort by 모드 자동 적용 필터 (읽기 전용) ─────────
            # Sort by 변경 시 내부만 재렌더링하는 컨테이너
            auto_filter_outer = tk.Frame(inner, bg=DARK_BG)
            auto_filter_outer.pack(fill="x")

            def _refresh_auto_filter() -> None:
                for w in auto_filter_outer.winfo_children():
                    w.destroy()

                cur_mode = _selected_sort_ref[0]   # 팝업 내 선택된 Sort by 모드
                cfg_ban  = _get_mode_cfg(cur_mode)

                auto_hdr = tk.Frame(auto_filter_outer, bg="#0A1A10", pady=4)
                auto_hdr.pack(fill="x", pady=(0, 0))
                tk.Label(auto_hdr,
                         text=f"  ✦  [{cur_mode}]  모드 자동 적용 필터  —  읽기 전용 (사용자 변경 불가)",
                         bg="#0A1A10", fg=ACCENT_BLUE,
                         font=("Segoe UI", 7, "bold")).pack(side="left", padx=6)

                def _auto_row(label: str, value: str, col: str = DARK_TEXT) -> None:
                    rw = tk.Frame(auto_filter_outer, bg="#0D150F", pady=3)
                    rw.pack(fill="x")
                    tk.Label(rw, text="  ▸",
                             bg="#0D150F", fg=ACCENT_BLUE,
                             font=("Segoe UI", 8)).pack(side="left", padx=(8, 2))
                    tk.Label(rw, text=label,
                             bg="#0D150F", fg=DIM_TEXT,
                             font=("Segoe UI", 7), width=14, anchor="w").pack(side="left")
                    tk.Label(rw, text=value,
                             bg="#0D150F", fg=col,
                             font=("Consolas", 7, "bold")).pack(side="left")

                _bias_label = {
                    "both":       "롱·숏 양방향",
                    "long_only":  "롱 전용  (숏 자동 차단)",
                    "short_only": "숏 전용  (롱 자동 차단)",
                }.get(cfg_ban.direction_bias, "양방향")
                _auto_row("진입 방향", _bias_label, YELLOW)

                if cfg_ban.direction_bias != "short_only":
                    _auto_row("K 롱 상한",
                              f"K < {cfg_ban.k_long_max:.0f}  (과매도 구간)", POSITIVE)
                if cfg_ban.direction_bias != "long_only":
                    _auto_row("K 숏 하한",
                              f"K > {cfg_ban.k_short_min:.0f}  (과매수 구간)", NEGATIVE)

                _auto_row("ATR% 범위",
                          f"{cfg_ban.atr_min:.1f}% ~ {cfg_ban.atr_max:.1f}%", ACCENT_BLUE)

                if cfg_ban.quality_grade_req is not None:
                    _auto_row("품질 등급",
                              f"{cfg_ban.quality_grade_req} 등급 이상 필수", YELLOW)
                if cfg_ban.volume_mult is not None:
                    _auto_row("거래량 배수",
                              f"{cfg_ban.volume_mult:.1f}x 이상 필수", YELLOW)
                if cfg_ban.macro_ema:
                    _auto_row("EMA 거시",
                              "EMA5 vs EMA50 방향 확인", ACCENT_BLUE)
                if cfg_ban.requires_swing:
                    _auto_row("스윙 구조",
                              "15m 고저점 구조 확인 필수", ACCENT_BLUE)

                ban_canvas.configure(scrollregion=ban_canvas.bbox("all"))

            _refresh_auto_filter()
            _auto_filter_refresh_ref[0] = _refresh_auto_filter

            # 구분선
            tk.Frame(inner, bg="#2A3A2A", height=1).pack(fill="x", pady=(6, 2))

            def _ban_sec_hdr(text: str) -> None:
                f = tk.Frame(inner, bg=DARK_HEADER, pady=3)
                f.pack(fill="x", pady=(8, 0))
                tk.Label(f, text=f"  {text}",
                         bg=DARK_HEADER, fg=ACCENT_BLUE,
                         font=("Segoe UI", 8, "bold")).pack(side="left", padx=6)

            def _ban_row(key: str, desc: str) -> None:
                rw = tk.Frame(inner, bg=DARK_PANEL, pady=4)
                rw.pack(fill="x")
                _default = (getattr(ProhibitionFlags(), key, False)
                            if ProhibitionFlags is not None else False)
                var = self._prohibited_vars.setdefault(
                    key, tk.BooleanVar(value=_default))

                icon_lbl = tk.Label(rw, text="—", bg=DARK_PANEL, fg=DIM_TEXT,
                                     font=("Segoe UI", 9), width=2)
                desc_lbl = tk.Label(rw, text=f"  {desc}",
                                     bg=DARK_PANEL, fg=DARK_TEXT,
                                     font=("Segoe UI", 8), anchor="w")

                def _refresh() -> None:
                    if var.get():
                        rw.configure(bg="#2A0A0F")
                        icon_lbl.configure(bg="#2A0A0F", fg=NEGATIVE,
                                            text="⛔")
                        desc_lbl.configure(bg="#2A0A0F", fg=NEGATIVE,
                                            font=("Segoe UI", 8, "bold"))
                    else:
                        rw.configure(bg=DARK_PANEL)
                        icon_lbl.configure(bg=DARK_PANEL, fg=DIM_TEXT,
                                            text="—")
                        desc_lbl.configure(bg=DARK_PANEL, fg=DARK_TEXT,
                                            font=("Segoe UI", 8, "normal"))

                cb = tk.Checkbutton(rw, variable=var, bg=DARK_PANEL,
                                     activebackground=DARK_PANEL,
                                     selectcolor="#2A0A0F",
                                     highlightthickness=0, bd=0,
                                     command=_refresh)
                cb.pack(side="left", padx=(8, 2))
                icon_lbl.pack(side="left", padx=(2, 4))
                desc_lbl.pack(side="left", fill="x", expand=True, padx=(0, 8))
                _refresh()

            _ban_sec_hdr("공통 조건  (체크 시 롱·숏 양방향 거래 금지)")
            _ban_row("common_macro",  "거시 추세 (1H · 4H · 1D) 반대 방향 거래 금지")
            _ban_row("common_4tf",    "4TF 완전 정렬 미충족 상태  —  해제 시 3/4 과반 기준 완화")
            _ban_row("common_liq",    "청산 근접도 위험 구간 진입 (강제 청산가 근접)")
            _ban_row("common_atr",    "ATR%  과도 변동성 구간  (8% 초과)")
            _ban_row("common_fr",     "FR(펀딩비)  임계치 초과  —  과열 신호")
            _ban_row("common_new",    "신규 상장 심볼  —  가용 데이터 14일 미만")
            _ban_row("common_hunter", "Player Detection  '청산 헌터'  태그 감지")

            _ban_sec_hdr("롱 포지션 전용 금지 조건")
            _ban_row("long_fomo",      "Player Detection  'FOMO 극단'  태그 감지 시 롱 진입 금지")
            _ban_row("long_short_open", "숏 포지션 보유 중  동시 롱 진입 금지")

            _ban_sec_hdr("숏 포지션 전용 금지 조건")
            _ban_row("short_accum",    "Player Detection  '세력 매집'  태그 감지 시 숏 진입 금지")
            _ban_row("short_long_open", "롱 포지션 보유 중  동시 숏 진입 금지")

        # ── 백테스팅 실행 ─────────────────────────────────────────
        def _do_backtest() -> None:
            bt_btn.configure(state="disabled", cursor="arrow")
            cmp_btn.configure(state="disabled", cursor="arrow")
            status_lbl.configure(text="  백테스팅 실행 중...  ", fg=YELLOW)

            funds, lev, sl, trail = self._current_params()
            from bottom.models import StrategyParams as _SP, ProhibitionFlags as _PF
            params = _SP(
                sort_mode   = _selected_sort_ref[0],   # 전략 창 내 선택된 Sort by 모드
                funds_pct   = int(funds),
                leverage    = int(lev),
                stop_loss   = float(sl),
                trail_stop  = float(trail),
                prohibition = _PF.from_dict(
                                {k: v.get() for k, v in self._prohibited_vars.items()}),
                use_macro   = self._use_macro_var.get(),
            )

            def _run() -> None:
                try:
                    if _HAS_BACKTEST and BacktestRunner is not None:
                        from bottom.backtest.param_deriver import derive_params
                        period_key = _get_period_key(avail_days_ref[0])
                        mode       = _consensus_var.get()
                        result_obj = BacktestRunner.run(sym, params, period_key, mode)
                        res = _backtest_result_to_dict(result_obj)
                        res["derived"] = derive_params(result_obj.trades)
                    else:
                        res = {}
                except Exception:
                    res = {}
                win.after(0, lambda r=res: _backtest_done(r))

            _threading.Thread(target=_run, daemon=True).start()

        def _backtest_done(res: dict) -> None:
            long_r  = res.get("long",  {})
            short_r = res.get("short", {})
            win_str = res.get("total", {}).get("win", "—")
            status_lbl.configure(
                text=f"  4TF 정렬 백테스팅 완료  ✓   적중도 {win_str}  ",
                fg=POSITIVE)

            for w in tab2_frame.winfo_children():
                w.destroy()
            _populate_tab2(res)
            tab2_btn.configure(state="normal", cursor="hand2")
            tab1_btn.configure(**_TAB_UNSEL)
            _show_tab(2)
            bt_btn.configure(state="normal", cursor="hand2",
                             text="  🔄  백테스팅 재실행  ")
            cmp_btn.configure(state="normal", cursor="hand2")

            for row_d in _stat_rows:
                key = row_d["key"]
                lv  = long_r.get(key,  "—")
                sv  = short_r.get(key, "—")
                lc  = (POSITIVE if "+" in str(lv) else
                       ACCENT_BLUE if "%" in str(lv) else DIM_TEXT)
                sc  = (POSITIVE if "+" in str(sv) else
                       ACCENT_BLUE if "%" in str(sv) else DIM_TEXT)
                row_d["long"].configure( text=f"롱 :  {lv}", fg=lc)
                row_d["short"].configure(text=f"숏 :  {sv}", fg=sc)

        def _populate_tab2(res: dict) -> None:
            long_r   = res.get("long",  {})
            short_r  = res.get("short", {})
            tot      = res.get("total", {})
            la_cnt   = res.get("long_align",  0)
            sa_cnt   = res.get("short_align", 0)
            next_est = res.get("next_est", "—")
            days     = avail_days_ref[0]
            total_align = la_cnt + sa_cnt
            daily_avg   = round(total_align / max(1, days), 2)

            canvas_scroll = tk.Canvas(tab2_frame, bg=DARK_BG,
                                      highlightthickness=0)
            sb = tk.Scrollbar(tab2_frame, orient="vertical",
                              command=canvas_scroll.yview)
            canvas_scroll.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            canvas_scroll.pack(side="left", fill="both", expand=True)

            inner = tk.Frame(canvas_scroll, bg=DARK_BG)
            inner_id = canvas_scroll.create_window(
                (0, 0), window=inner, anchor="nw")

            def _resize(e):
                canvas_scroll.configure(
                    scrollregion=canvas_scroll.bbox("all"))
                canvas_scroll.itemconfig(inner_id, width=e.width)
            canvas_scroll.bind("<Configure>", _resize)

            # ── 4TF 정렬 발생 통계 ──────────────────────────────────
            align_hdr = tk.Frame(inner, bg=DARK_HEADER, pady=5)
            align_hdr.pack(fill="x", pady=(8, 0))
            tk.Label(align_hdr, text="  🔍  4TF 완전 정렬 발생 통계",
                     bg=DARK_HEADER, fg=ACCENT_BLUE,
                     font=("Segoe UI", 9, "bold")).pack(side="left", padx=6)

            align_row1 = tk.Frame(inner, bg=DARK_PANEL, pady=6)
            align_row1.pack(fill="x")
            for txt, val, col in [
                ("롱 정렬 발생",  f"{la_cnt}회",        POSITIVE),
                ("숏 정렬 발생",  f"{sa_cnt}회",        NEGATIVE),
                ("총 정렬 횟수",  f"{total_align}회",   ACCENT_BLUE),
                ("일 평균 정렬",  f"{daily_avg:.2f}회", DIM_TEXT),
            ]:
                seg = tk.Frame(align_row1, bg=DARK_PANEL)
                seg.pack(side="left", expand=True)
                tk.Label(seg, text=txt,
                         bg=DARK_PANEL, fg=DIM_TEXT,
                         font=("Segoe UI", 7)).pack()
                tk.Label(seg, text=val,
                         bg=DARK_PANEL, fg=col,
                         font=("Consolas", 10, "bold")).pack()

            align_row2 = tk.Frame(inner, bg="#1A1A10", pady=6)
            align_row2.pack(fill="x")
            tk.Label(align_row2,
                     text=f"  ⏱  다음 4TF 정렬 예상  :  "
                          f"{next_est}  발생 예상",
                     bg="#1A1A10", fg=YELLOW,
                     font=("Segoe UI", 8, "bold")).pack(
                         side="left", padx=10)

            # ── 거래 성과 테이블 ─────────────────────────────────────
            tk.Frame(inner, bg="#2A2A2A", height=1).pack(
                fill="x", pady=(10, 0))
            perf_hdr = tk.Frame(inner, bg=DARK_HEADER, pady=5)
            perf_hdr.pack(fill="x")
            tk.Label(perf_hdr, text="  📊  거래 성과  (4TF 정렬 진입 기준)",
                     bg=DARK_HEADER, fg=ACCENT_BLUE,
                     font=("Segoe UI", 9, "bold")).pack(side="left", padx=6)
            tk.Label(perf_hdr,
                     text=f"  총 수익률  {tot.get('return','—')}"
                          f"   적중도  {tot.get('win','—')}"
                          f"   MDD  {tot.get('mdd','—')}",
                     bg=DARK_HEADER, fg=POSITIVE,
                     font=("Segoe UI", 8, "bold")).pack(side="right", padx=12)

            col_hdr = tk.Frame(inner, bg="#252525", pady=4)
            col_hdr.pack(fill="x")
            for txt, w in [("구분", 8), ("거래 횟수", 9), ("적중도", 8),
                           ("평균 수익", 10), ("단일 최대", 12),
                           ("총 수익률", 12)]:
                tk.Label(col_hdr, text=txt, bg="#252525", fg=ACCENT_BLUE,
                         font=("Segoe UI", 7, "bold"),
                         width=w, anchor="center").pack(side="left", padx=3)

            for row_i, (label, col, rkey) in enumerate([
                ("📈  롱", POSITIVE, "long"),
                ("📉  숏", NEGATIVE, "short"),
            ]):
                rbg = DARK_ROW_ODD if row_i % 2 == 0 else DARK_ROW_EVN
                d   = res.get(rkey, {})
                rw  = tk.Frame(inner, bg=rbg, pady=5)
                rw.pack(fill="x")
                tk.Label(rw, text=label, bg=rbg, fg=col,
                         font=("Segoe UI", 8, "bold"),
                         width=8, anchor="center").pack(side="left", padx=3)
                for val, w in [
                    (f"{d.get('count','—')}회", 9),
                    (d.get("hit",   "—"),       8),
                    (d.get("avg",   "—"),       10),
                    (d.get("max",   "—"),       12),
                    (d.get("total", "—"),       12),
                ]:
                    vc = (POSITIVE if "+" in str(val)
                          else NEGATIVE if "-" in str(val) else DIM_TEXT)
                    tk.Label(rw, text=val, bg=rbg, fg=vc,
                             font=("Consolas", 8, "bold"),
                             width=w, anchor="center").pack(side="left", padx=3)

            # ── 심화 분석 지표 ───────────────────────────────────────
            tk.Frame(inner, bg="#2A2A2A", height=1).pack(
                fill="x", pady=(12, 0))
            adv_hdr = tk.Frame(inner, bg=DARK_HEADER, pady=5)
            adv_hdr.pack(fill="x")
            tk.Label(adv_hdr, text="  📐  심화 분석 지표",
                     bg=DARK_HEADER, fg=ACCENT_BLUE,
                     font=("Segoe UI", 9, "bold")).pack(side="left", padx=6)

            adv_specs = [
                ("손익비  (R/R Ratio)",        "rr_ratio"),
                ("수익 팩터  (Profit Factor)",  "profit_factor"),
                ("손실 거래 평균 손실률",        "avg_loss"),
                ("평균 포지션 보유 시간",        "avg_hold"),
                ("최대 연속 손실 횟수",          "max_consec_loss"),
                ("일일 평균 거래 빈도",          "daily_freq"),
            ]

            def _adv_col(v: str) -> str:
                if "+" in v: return POSITIVE
                if "-" in v: return NEGATIVE
                return ACCENT_BLUE

            for i, (label, akey) in enumerate(adv_specs):
                rbg = DARK_ROW_ODD if i % 2 == 0 else DARK_ROW_EVN
                rw  = tk.Frame(inner, bg=rbg, pady=6)
                rw.pack(fill="x")
                tk.Label(rw, text=f"  {label}",
                         bg=rbg, fg=DIM_TEXT,
                         font=("Segoe UI", 8),
                         width=28, anchor="w").pack(side="left", padx=(8, 0))
                lv = long_r.get(akey,  "—")
                sv = short_r.get(akey, "—")
                tk.Label(rw, text=f"롱 :  {lv}",
                         bg=rbg, fg=_adv_col(str(lv)),
                         font=("Consolas", 8, "bold"),
                         width=18, anchor="center").pack(
                             side="left", padx=(12, 4))
                tk.Label(rw, text=f"숏 :  {sv}",
                         bg=rbg, fg=_adv_col(str(sv)),
                         font=("Consolas", 8, "bold"),
                         width=18, anchor="center").pack(
                             side="left", padx=(4, 0))

            # ── Kelly 리스크 분석 ────────────────────────────────────
            derived = res.get("derived", {})
            tk.Frame(inner, bg="#2A2A2A", height=1).pack(
                fill="x", pady=(12, 0))
            kelly_hdr = tk.Frame(inner, bg=DARK_HEADER, pady=5)
            kelly_hdr.pack(fill="x")
            tk.Label(kelly_hdr, text="  📐  Kelly 리스크 분석  (Fractional Kelly × 0.25)",
                     bg=DARK_HEADER, fg=ACCENT_BLUE,
                     font=("Segoe UI", 9, "bold")).pack(side="left", padx=6)

            _note = derived.get("note", "")
            if not derived or "note" in derived and len(derived) == 1:
                # 거래 없음 또는 샘플 부족
                note_row = tk.Frame(inner, bg=DARK_ROW_ODD, pady=8)
                note_row.pack(fill="x")
                tk.Label(note_row, text=f"  {_note or '거래 데이터 없음'}",
                         bg=DARK_ROW_ODD, fg=DIM_TEXT,
                         font=("Segoe UI", 8)).pack(side="left", padx=10)
            else:
                kelly_items = [
                    ("Wilson 승률 하한",       f"{derived.get('win_rate_wilson', 0)*100:.1f}%",  ACCENT_BLUE),
                    ("단순 승률",              f"{derived.get('win_rate_raw', 0)*100:.1f}%",      DIM_TEXT),
                    ("평균 수익 pnl",          f"{derived.get('avg_win_r', 0):+.2f}%",            POSITIVE),
                    ("평균 손실 pnl",          f"-{derived.get('avg_loss_r', 0):.2f}%",           NEGATIVE),
                    ("Kelly 권장 위험 비율",   f"{derived.get('r_per_trade_pct', 0):.2f}%",       YELLOW),
                ]
                if _note:
                    kelly_items.append(("비고", _note, DIM_TEXT))
                for ki, (klabel, kval, kcol) in enumerate(kelly_items):
                    kbg = DARK_ROW_ODD if ki % 2 == 0 else DARK_ROW_EVN
                    krw = tk.Frame(inner, bg=kbg, pady=6)
                    krw.pack(fill="x")
                    tk.Label(krw, text=f"  {klabel}",
                             bg=kbg, fg=DIM_TEXT,
                             font=("Segoe UI", 8),
                             width=24, anchor="w").pack(side="left", padx=(8, 0))
                    tk.Label(krw, text=kval,
                             bg=kbg, fg=kcol,
                             font=("Consolas", 9, "bold"),
                             anchor="w").pack(side="left", padx=(16, 0))

            _req_b = _get_mode_cfg(_selected_sort_ref[0]).quality_grade_req
            if _req_b is not None:
                _note_frm = tk.Frame(inner, bg=DARK_BG, pady=3)
                _note_frm.pack(fill="x", pady=(6, 0))
                tk.Label(_note_frm,
                         text=(f"  ※ 백테스트 등급은 Cascade·Zone·Duration 3축만 반영합니다 (최대 87점).\n"
                               f"     실거래는 Divergence·Swing 포함 125점이므로 백테스트가 더 엄격하며,\n"
                               f"     {_req_b}등급 요구 모드는 실거래보다 거래 수가 적게 나옵니다."),
                         bg=DARK_BG, fg=DIM_TEXT, justify="left",
                         font=("Segoe UI", 8)).pack(side="left", padx=8)

        def _do_load() -> None:
            load_btn.configure(state="disabled", cursor="arrow")
            bt_btn.configure(state="disabled", cursor="arrow",
                             text="  ▶  백테스팅  ")
            status_lbl.configure(text="  데이터 로딩 중...  ", fg=YELLOW)
            _bars_ref[0]         = []
            _data_fetched_ref[0] = False
            _animate(0)

            def _fetch() -> None:
                try:
                    if _HAS_BACKTEST and HistoricalDataLoader is not None:
                        bars = HistoricalDataLoader.load_for_period(sym, "90일")
                    else:
                        bars = []
                except Exception:
                    bars = []
                _bars_ref[0]         = bars
                _data_fetched_ref[0] = True

            _threading.Thread(target=_fetch, daemon=True).start()

        # ── 4모드 비교 실행 ───────────────────────────────────────
        def _do_comparison() -> None:
            bt_btn.configure(state="disabled", cursor="arrow")
            cmp_btn.configure(state="disabled", cursor="arrow")
            status_lbl.configure(text="  4모드 비교 실행 중...  ", fg=YELLOW)

            funds, lev, sl, trail = self._current_params()
            from bottom.models import StrategyParams as _SP, ProhibitionFlags as _PF
            params = _SP(
                sort_mode   = _selected_sort_ref[0],
                funds_pct   = int(funds),
                leverage    = int(lev),
                stop_loss   = float(sl),
                trail_stop  = float(trail),
                prohibition = _PF.from_dict(
                                {k: v.get() for k, v in self._prohibited_vars.items()}),
                use_macro   = self._use_macro_var.get(),
            )

            def _run_cmp() -> None:
                try:
                    if _HAS_BACKTEST and BacktestRunner is not None:
                        period_key = _get_period_key(avail_days_ref[0])
                        cmp_results = BacktestRunner.run_comparison(
                            sym, params, period_key)
                    else:
                        cmp_results = {}
                except Exception:
                    cmp_results = {}
                win.after(0, lambda r=cmp_results: _comparison_done(r))

            _threading.Thread(target=_run_cmp, daemon=True).start()

        def _comparison_done(cmp_results: dict) -> None:
            status_lbl.configure(
                text="  4모드 비교 완료  ✓  ",
                fg=POSITIVE)
            for w in tab2_frame.winfo_children():
                w.destroy()
            _show_comparison_tab2(cmp_results)
            tab2_btn.configure(state="normal", cursor="hand2")
            tab1_btn.configure(**_TAB_UNSEL)
            _show_tab(2)
            bt_btn.configure(state="normal", cursor="hand2",
                             text="  🔄  백테스팅 재실행  ")
            cmp_btn.configure(state="normal", cursor="hand2")

        def _show_comparison_tab2(cmp_results: dict) -> None:
            """4모드 비교 결과를 tab2에 렌더링."""
            canvas_scroll = tk.Canvas(tab2_frame, bg=DARK_BG,
                                      highlightthickness=0)
            sb = tk.Scrollbar(tab2_frame, orient="vertical",
                              command=canvas_scroll.yview)
            canvas_scroll.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            canvas_scroll.pack(side="left", fill="both", expand=True)

            inner = tk.Frame(canvas_scroll, bg=DARK_BG)
            inner_id = canvas_scroll.create_window(
                (0, 0), window=inner, anchor="nw")

            def _resize_cmp(e):
                canvas_scroll.configure(
                    scrollregion=canvas_scroll.bbox("all"))
                canvas_scroll.itemconfig(inner_id, width=e.width)
            canvas_scroll.bind("<Configure>", _resize_cmp)

            # 헤더
            hdr_f = tk.Frame(inner, bg=DARK_HEADER, pady=5)
            hdr_f.pack(fill="x", pady=(8, 0))
            tk.Label(hdr_f, text="  📊  4가지 합의 모드 비교",
                     bg=DARK_HEADER, fg=ACCENT_BLUE,
                     font=("Segoe UI", 9, "bold")).pack(side="left", padx=6)

            # 컬럼 헤더
            col_hdr = tk.Frame(inner, bg="#252525", pady=4)
            col_hdr.pack(fill="x")
            for txt, w in [("합의 모드", 10), ("적중도", 8), ("총 수익률", 10),
                           ("MDD", 8), ("거래 횟수", 8), ("손익비", 8)]:
                tk.Label(col_hdr, text=txt, bg="#252525", fg=ACCENT_BLUE,
                         font=("Segoe UI", 7, "bold"),
                         width=w, anchor="center").pack(side="left", padx=3)

            # 최고 수익률 모드 파악
            _MODES = ["4/4", "3/4", "anchor3", "anchor2"]
            best_mode = max(
                (m for m in _MODES if m in cmp_results),
                key=lambda m: cmp_results[m].total_return,
                default=None,
            )

            for row_i, mode in enumerate(_MODES):
                if mode not in cmp_results:
                    continue
                r   = cmp_results[mode]
                rbg = DARK_ROW_ODD if row_i % 2 == 0 else DARK_ROW_EVN
                is_best = (mode == best_mode)

                # 손익비 계산 (전체 trades 기반)
                all_wins   = [t for t in r.trades if t.pnl_pct > 0]
                all_losses = [t for t in r.trades if t.pnl_pct <= 0]
                avg_w  = (sum(t.pnl_pct for t in all_wins)   / len(all_wins)
                          if all_wins else 0)
                avg_l  = (sum(t.pnl_pct for t in all_losses) / len(all_losses)
                          if all_losses else 0)
                rr_str = (f"{abs(avg_w/avg_l):.1f}:1" if avg_l != 0 else "—")

                mode_label = f"{'★ ' if is_best else '   '}{mode}"
                mode_fg    = YELLOW if is_best else DIM_TEXT

                rw = tk.Frame(inner, bg=rbg, pady=6)
                rw.pack(fill="x")
                tk.Label(rw, text=mode_label, bg=rbg, fg=mode_fg,
                         font=("Consolas", 8, "bold"),
                         width=10, anchor="center").pack(side="left", padx=3)

                cells = [
                    (f"{r.win_rate:.0f}%",            ACCENT_BLUE, 8),
                    (f"{r.total_return:+.1f}%",
                     POSITIVE if r.total_return >= 0 else NEGATIVE, 10),
                    (f"-{r.max_drawdown:.1f}%",        NEGATIVE,    8),
                    (f"{r.total_trades}회",             DIM_TEXT,    8),
                    (rr_str,                            ACCENT_BLUE, 8),
                ]
                for val, col, w in cells:
                    tk.Label(rw, text=val, bg=rbg, fg=col,
                             font=("Consolas", 8, "bold"),
                             width=w, anchor="center").pack(
                                 side="left", padx=3)

            if not cmp_results:
                note_row = tk.Frame(inner, bg=DARK_ROW_ODD, pady=8)
                note_row.pack(fill="x")
                tk.Label(note_row,
                         text="  비교 결과 없음 — 데이터 로딩 후 재시도하세요.",
                         bg=DARK_ROW_ODD, fg=DIM_TEXT,
                         font=("Segoe UI", 8)).pack(side="left", padx=10)

            # ── Kelly 리스크 분석 — 모드별 ──────────────────────────
            if cmp_results:
                tk.Frame(inner, bg="#2A2A2A", height=1).pack(
                    fill="x", pady=(12, 0))
                kelly_hdr = tk.Frame(inner, bg=DARK_HEADER, pady=5)
                kelly_hdr.pack(fill="x")
                tk.Label(kelly_hdr,
                         text="  📐  Kelly 리스크 분석  — 합의 모드별  (Fractional Kelly × 0.25)",
                         bg=DARK_HEADER, fg=ACCENT_BLUE,
                         font=("Segoe UI", 9, "bold")).pack(side="left", padx=6)

                k_col_hdr = tk.Frame(inner, bg="#252525", pady=4)
                k_col_hdr.pack(fill="x")
                for _txt, _w in [("합의 모드", 10), ("Wilson 승률", 11),
                                  ("평균 수익", 10), ("평균 손실", 10), ("Kelly R%", 10)]:
                    tk.Label(k_col_hdr, text=_txt, bg="#252525", fg=ACCENT_BLUE,
                             font=("Segoe UI", 7, "bold"),
                             width=_w, anchor="center").pack(side="left", padx=3)

                from bottom.backtest.param_deriver import derive_params as _derive
                for _ki, _mode in enumerate(_MODES):
                    if _mode not in cmp_results:
                        continue
                    _r   = cmp_results[_mode]
                    _rbg = DARK_ROW_ODD if _ki % 2 == 0 else DARK_ROW_EVN
                    _derived = _derive(_r.trades)

                    _krw = tk.Frame(inner, bg=_rbg, pady=6)
                    _krw.pack(fill="x")
                    tk.Label(_krw, text=f"  {_mode}", bg=_rbg, fg=DIM_TEXT,
                             font=("Consolas", 8, "bold"),
                             width=10, anchor="center").pack(side="left", padx=3)

                    if "win_rate_wilson" not in _derived:
                        tk.Label(_krw,
                                 text=_derived.get("note", "데이터 부족"),
                                 bg=_rbg, fg=DIM_TEXT,
                                 font=("Segoe UI", 7),
                                 anchor="w").pack(side="left", padx=8)
                    else:
                        _kelly_cells = [
                            (f"{_derived['win_rate_wilson']*100:.1f}%", ACCENT_BLUE, 11),
                            (f"+{_derived['avg_win_r']:.2f}%",          POSITIVE,    10),
                            (f"-{_derived['avg_loss_r']:.2f}%",         NEGATIVE,    10),
                            (f"{_derived['r_per_trade_pct']:.2f}%",     YELLOW,      10),
                        ]
                        for _val, _col, _w in _kelly_cells:
                            tk.Label(_krw, text=_val, bg=_rbg, fg=_col,
                                     font=("Consolas", 8, "bold"),
                                     width=_w, anchor="center").pack(
                                         side="left", padx=3)

            try:
                _any_r = next(iter(cmp_results.values()))
                _req_c = _get_mode_cfg(_any_r.sort_mode).quality_grade_req
            except Exception:
                _req_c = None
            if _req_c is not None:
                _cnote_frm = tk.Frame(inner, bg=DARK_BG, pady=3)
                _cnote_frm.pack(fill="x", pady=(6, 0))
                tk.Label(_cnote_frm,
                         text=(f"  ※ 백테스트 등급은 Cascade·Zone·Duration 3축만 반영합니다 (최대 87점).\n"
                               f"     실거래는 Divergence·Swing 포함 125점이므로 백테스트가 더 엄격하며,\n"
                               f"     {_req_c}등급 요구 모드는 실거래보다 거래 수가 적게 나옵니다."),
                         bg=DARK_BG, fg=DIM_TEXT, justify="left",
                         font=("Segoe UI", 8)).pack(side="left", padx=8)

        def _do_restart() -> None:
            status_lbl.configure(text="  —  ", fg=DIM_TEXT)
            period_lbl.configure(text="  분석 기간  —", fg=DIM_TEXT)
            period_sub.configure(
                text="  (데이터 로딩 후 자동 감지)", fg=DIM_TEXT)
            prog_cv.delete("all")
            for w in tab1_frame.winfo_children():
                w.destroy()
            for w in tab_ban_frame.winfo_children():
                w.destroy()
            for w in tab2_frame.winfo_children():
                w.destroy()
            hint_lbl_ref[0]  = None
            ban_hint_ref[0]  = None
            tab2_hint_ref[0] = None
            _make_hint_lbl()
            _make_ban_hint()
            _make_tab2_hint()
            tab1_btn.configure(state="disabled", cursor="arrow", **_TAB_DIS)
            tab_ban_btn.configure(state="disabled", cursor="arrow", **_TAB_DIS)
            tab2_btn.configure(state="disabled", cursor="arrow", **_TAB_DIS)
            _show_tab(1)
            load_btn.configure(state="normal", cursor="hand2",
                               text="  📥  데이터 로딩  ")
            bt_btn.configure(state="disabled", cursor="arrow",
                             text="  ▶  백테스팅  ")
            cmp_btn.configure(state="disabled", cursor="arrow")
            avail_days_ref[0] = 90
            for row_d in _stat_rows:
                row_d["long"].configure( text="롱 :   —", fg=DIM_TEXT)
                row_d["short"].configure(text="숏 :   —", fg=DIM_TEXT)

        load_btn.configure(command=_do_load)
        restart_btn.configure(command=_do_restart)
        bt_btn.configure(command=_do_backtest)
        cmp_btn.configure(command=_do_comparison)
        tab1_btn.configure(command=lambda: _show_tab(1))
        tab_ban_btn.configure(command=lambda: _show_tab(3))
        tab2_btn.configure(command=lambda: _show_tab(2))

    # ─── 전략 확정 ───────────────────────────────────────────────
    def _confirm_strategy(self, win: tk.Toplevel,
                          sort_mode: str = "24h Ticker") -> None:
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
                                "prohibited": prohibited}
        self._applied_sort_mode = sort_mode
        self._strategy_ready = True
        self._strategy_msg.configure(
            text="  ✓ 전략설정완료   4TF 완전 정렬  ", fg=POSITIVE)
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
    def _open_funds_lev_window(self) -> None:
        win = tk.Toplevel(self)
        win.title("Designated Funds  &  Applied Leverage")
        win.configure(bg=DARK_BG)
        win.geometry("440x200")
        win.resizable(False, False)
        win.grab_set()

        tk.Label(win, text="  📊  Designated Funds  &  Applied Leverage",
                 bg=DARK_HEADER, fg=ACCENT_BLUE,
                 font=("Segoe UI", 9, "bold"),
                 anchor="w").pack(fill="x", ipady=6)
        tk.Frame(win, bg="#2A2A2A", height=1).pack(fill="x")

        body = tk.Frame(win, bg=DARK_PANEL, pady=10)
        body.pack(fill="x", padx=16, pady=(8, 0))
        self._inline_slider(body, "Designated Funds",
                            self._funds_var, 1, 100,
                            [1, 25, 50, 75, 100], "%",
                            snap_step=1)
        tk.Frame(body, bg="#2A2A2A", height=1).pack(fill="x", pady=5)
        self._inline_slider(body, "Applied Leverage",
                            self._lev_var, 1, 125,
                            [1, 25, 50, 75, 100, 125], "x",
                            snap_step=1)

        tk.Frame(win, bg="#2A2A2A", height=1).pack(fill="x", pady=(8, 0))

        def _apply() -> None:
            funds = self._funds_var.get()
            lev   = self._lev_var.get()
            self._funds_lev_btn.configure(
                text=f"  ✓  Funds {funds}%   |   {lev}x  ",
                bg="#0D2A1A", fg=POSITIVE,
                activebackground="#0A3A18", activeforeground=POSITIVE)
            if not self._strategy_ready or self._applied_params is None:
                from tkinter import messagebox as _mb
                _mb.showwarning(
                    "전략 미확정",
                    "전략 설정 창에서 전략을 먼저 확정한 후\n"
                    "Funds & Leverage를 적용해 주세요.")
                win.destroy()
                return
            if self._engine is not None and StrategyLoader is not None:
                try:
                    ap = dict(self._applied_params)
                    ap["funds"] = funds
                    ap["leverage"] = lev
                    self._applied_params.update({"funds": funds, "leverage": lev})
                    params = StrategyLoader.save_from_applied(
                        ap, self._applied_sort_mode)
                    self._engine.update_params(params)
                except Exception as e:
                    import tkinter.messagebox as _mb
                    _mb.showwarning("저장 실패", f"전략 설정 저장 실패:\n{e}")
            self._update_param_info_lbl()
            win.destroy()

        tk.Button(win, text="  ✅  적 용  ",
                  bg="#0A2A12", fg=POSITIVE,
                  activebackground="#0A3A18", activeforeground=POSITIVE,
                  font=("Segoe UI", 9, "bold"), relief="flat",
                  padx=14, pady=4, cursor="hand2",
                  command=_apply).pack(anchor="center", pady=6)

    # ══════════════════════════════════════════════════════════════
    # 헤더 버튼 팝업 — Stop Loss & Trailing Stop
    # ══════════════════════════════════════════════════════════════
    def _open_sl_trail_window(self) -> None:
        win = tk.Toplevel(self)
        win.title("Stop Loss  &  Trailing Stop")
        win.configure(bg=DARK_BG)
        win.geometry("360x240")
        win.resizable(False, False)
        win.grab_set()

        tk.Label(win, text="  🛡  Stop Loss  &  Trailing Stop",
                 bg=DARK_HEADER, fg=ACCENT_BLUE,
                 font=("Segoe UI", 9, "bold"),
                 anchor="w").pack(fill="x", ipady=6)
        tk.Frame(win, bg="#2A2A2A", height=1).pack(fill="x")

        body = tk.Frame(win, bg=DARK_PANEL, pady=10)
        body.pack(fill="x", padx=16, pady=(8, 0))
        self._inline_entry(body, "Stop Loss",    "2.5", var=self._sl_var)
        tk.Frame(body, bg="#2A2A2A", height=1).pack(fill="x", pady=5)
        self._inline_entry(body, "Trailing Stop", "1.5", var=self._trail_var)

        # ── Auto 계산 버튼 ──────────────────────────────────────
        auto_info = tk.Label(win, text="",
                             bg=DARK_BG, fg=DIM_TEXT,
                             font=("Segoe UI", 7))
        auto_info.pack(anchor="center", pady=(6, 0))

        def _auto_calc() -> None:
            sym = self._shared_sym.get()
            if not sym:
                auto_info.configure(text="심볼이 배치되지 않았습니다", fg=NEGATIVE)
                return
            try:
                from middle.widget.shared_context import get_ind as _get_ind
                from bottom.engine_core.quality_grader import QualityGrader
                from bottom.engine_core.sl_calculator import SLCalculator
                ind = _get_ind(sym)
                atr_5m = float((ind or {}).get("atr_pct_5m", 0.0))
                lev = self._lev_var.get()
                if atr_5m <= 0.0:
                    auto_info.configure(
                        text="5m ATR 데이터 준비 중 — 잠시 후 다시 시도해 주세요",
                        fg=YELLOW)
                    return
                _st = self._engine.get_state() if self._engine else None
                if _st and _st.short_pos and _st.short_pos.state == PositionState.OPEN:
                    _side = "short"
                elif _st and _st.long_pos and _st.long_pos.state == PositionState.OPEN:
                    _side = "long"
                else:
                    _side = "long"
                grade, _ = QualityGrader.grade(ind or {}, _side)
                _mmr_ui = self._engine.get_mmr_cached(sym) if self._engine else 0.004
                sl_v, trail_v = SLCalculator.compute(atr_5m, grade, lev, mmr=_mmr_ui)
                self._sl_var.set(sl_v)
                self._trail_var.set(trail_v)
                auto_info.configure(
                    text=f"자동 계산 완료  —  ATR5m {atr_5m:.2f}%  |  {_side.upper()} 등급 {grade}  |  레버리지 {lev}x",
                    fg=POSITIVE)
            except Exception:
                auto_info.configure(text="자동 계산 실패 — 수동으로 입력해 주세요", fg=NEGATIVE)

        tk.Button(win, text="  ⚡  Auto  자동 계산  ",
                  bg="#1A1A2A", fg=ACCENT_BLUE,
                  activebackground="#252535", activeforeground=ACCENT_BLUE,
                  font=("Segoe UI", 8, "bold"), relief="flat",
                  padx=10, pady=3, cursor="hand2",
                  command=_auto_calc).pack(anchor="center", pady=(4, 0))

        tk.Frame(win, bg="#2A2A2A", height=1).pack(fill="x", pady=(8, 0))

        def _apply() -> None:
            _, _, sl, trail = self._current_params()
            self._sl_trail_btn.configure(
                text=f"  ✓  SL {sl:.1f}%   |   Trail {trail:.1f}%  ",
                bg="#0D2A1A", fg=POSITIVE,
                activebackground="#0A3A18", activeforeground=POSITIVE)
            if not self._strategy_ready or self._applied_params is None:
                from tkinter import messagebox as _mb
                _mb.showwarning(
                    "전략 미확정",
                    "전략 설정 창에서 전략을 먼저 확정한 후\n"
                    "Stop Loss & Trailing Stop을 적용해 주세요.")
                win.destroy()
                return
            if self._engine is not None and StrategyLoader is not None:
                try:
                    ap = dict(self._applied_params)
                    ap["sl"] = sl
                    ap["trail"] = trail
                    self._applied_params.update({"sl": sl, "trail": trail})
                    params = StrategyLoader.save_from_applied(
                        ap, self._applied_sort_mode)
                    self._engine.update_params(params)
                except Exception as e:
                    import tkinter.messagebox as _mb
                    _mb.showwarning("저장 실패", f"전략 설정 저장 실패:\n{e}")
            self._update_param_info_lbl()
            win.destroy()

        tk.Button(win, text="  ✅  적 용  ",
                  bg="#0A2A12", fg=POSITIVE,
                  activebackground="#0A3A18", activeforeground=POSITIVE,
                  font=("Segoe UI", 9, "bold"), relief="flat",
                  padx=14, pady=4, cursor="hand2",
                  command=_apply).pack(anchor="center", pady=6)

    # ─── 인라인 슬라이더 (라벨 + canvas + 값 — 1행) ─────────────
    def _inline_slider(self, parent, label, var,
                       min_v, max_v, ticks, unit, snap_step=None) -> None:
        row = tk.Frame(parent, bg=DARK_PANEL)
        row.pack(fill="x")
        tk.Label(row, text=label, bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 7, "bold"),
                 anchor="w").pack(side="left", padx=(0, 6))

        cv = tk.Canvas(row, bg=DARK_PANEL, height=20, width=1,
                       highlightthickness=0, cursor="hand2")
        cv.pack(side="left", fill="x", expand=True)

        rng = max(1, max_v - min_v)
        vw  = 38    # 값 텍스트 영역 너비

        def _draw(e=None):
            cv.delete("all")
            w = cv.winfo_width()
            if w < 20: return
            cy = 10
            te = w - vw - 4
            cv.create_line(6, cy, te, cy, fill="#3A3A3A", width=2)
            for t in ticks:
                tx = int(6 + (t - min_v) / rng * (te - 6))
                cv.create_line(tx, cy - 3, tx, cy + 3, fill="#484848", width=1)
            ratio = (var.get() - min_v) / rng
            hx = int(6 + ratio * (te - 6))
            cv.create_line(6, cy, hx, cy, fill=ACCENT_BLUE, width=2)
            cv.create_polygon(hx, cy - 5, hx + 4, cy,
                               hx, cy + 5, hx - 4, cy,
                               fill=ACCENT_BLUE, outline=DARK_BG)
            cv.create_text(w - 2, cy, text=f"{var.get()}{unit}",
                           fill=ACCENT_BLUE,
                           font=("Segoe UI", 7, "bold"), anchor="e")

        def _drag(e):
            w = cv.winfo_width()
            if w < 20: return
            te = w - vw - 4
            ratio = max(0.0, min(1.0, (e.x - 6) / max(1, te - 6)))
            raw   = min_v + ratio * rng
            if snap_step is not None:
                snapped = max(min_v, min(max_v, int(round(raw / snap_step) * snap_step)))
            else:
                snapped = min(ticks, key=lambda t: abs(t - raw))
            var.set(snapped)
            _draw()

        cv.bind("<Configure>", _draw)
        cv.bind("<Button-1>",  _drag)
        cv.bind("<B1-Motion>", _drag)
        cv.after(30, _draw)

    # ─── 인라인 Entry (라벨 + 입력칸 + 단위 — 1행) ──────────────
    def _inline_entry(self, parent, label, default,
                      suffix: str = " %", *, var=None) -> tk.Entry:
        row = tk.Frame(parent, bg=DARK_PANEL)
        row.pack(fill="x")
        tk.Label(row, text=label, bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 7, "bold"),
                 anchor="w").pack(side="left", padx=(0, 6))
        kw = {"textvariable": var} if var is not None else {}
        entry = tk.Entry(row, width=7,
                         bg="#1A1A1A", fg=DARK_TEXT,
                         insertbackground=DARK_TEXT,
                         font=("Consolas", 10, "bold"),
                         relief="flat",
                         highlightthickness=2,
                         highlightbackground="#3A3A3A",
                         highlightcolor=ACCENT_BLUE,
                         **kw)
        if var is None:
            entry.insert(0, default)
        entry.pack(side="left")
        tk.Label(row, text=suffix, bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        entry.bind("<KeyRelease>", lambda e: self._validate_entry(entry))
        entry.bind("<FocusOut>",   lambda e: self._validate_entry(entry))
        return entry

    # ─── Entry 유효성 검사 (0.1 ~ 50.0 %) ───────────────────────
    def _validate_entry(self, entry: tk.Entry) -> bool:
        try:
            val = float(entry.get().strip())
            ok  = 0.1 <= val <= 50.0
        except ValueError:
            ok = False
        entry.configure(
            highlightbackground=("#3A3A3A" if ok else NEGATIVE),
            highlightcolor=(ACCENT_BLUE   if ok else NEGATIVE))
        return ok

    # ─── 현재 파라미터 값 일괄 조회 (범위 오류 시 기본값으로 안전 처리) ──
    def _current_params(self) -> tuple[int, int, float, float]:
        def _fv(var: tk.DoubleVar, default: float) -> float:
            try:
                val = var.get()
                return val if 0.1 <= val <= 50.0 else default
            except tk.TclError:
                return default
        return (self._funds_var.get(), self._lev_var.get(),
                _fv(self._sl_var, _BASE_SL), _fv(self._trail_var, _BASE_TRAIL))

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

    # ──────────────────────────────────────────────────────────────
    # 활성 포지션 인디케이터 — 화살표 + 발광 펄스 (깔끔한 단일 행 구성)
    # 전략 분석 결과(ACTIVE_POSITION)에 따라 1·3열 헤더와 동기화 표시
    # ──────────────────────────────────────────────────────────────
    def _build_position_indicator(self, parent: tk.Frame) -> None:
        INIT_LO, INIT_HI = "#1A1A1A", "#2A2A2A"
        self._pos_glow = {"lo": INIT_LO, "hi": INIT_HI, "phase": 0.0}
        glow_widgets: list = []

        # 1·3열 헤더(높이 35px)와 정확히 맞춰 시각적 정렬을 통일
        ind_f = tk.Frame(parent, bg=INIT_LO, pady=5)
        ind_f.pack(fill="x")
        glow_widgets.append(ind_f)

        row = tk.Frame(ind_f, bg=INIT_LO)
        row.pack(anchor="center")
        glow_widgets.append(row)

        lbl = tk.Label(row, text="⚪   4TF 합의 대기 중",
                       bg=INIT_LO, fg=DIM_TEXT,
                       font=("Segoe UI", 9, "bold"))
        lbl.pack(side="left")
        glow_widgets.append(lbl)

        self._pos_ind = {"frame": ind_f, "row": row,
                         "lbl": lbl, "glow_widgets": glow_widgets}
        _g = self._pos_glow

        # ── 발광 펄스 애니메이션 (배경색 보간 — 폴링으로 색상 동적 갱신) ──
        def _pulse() -> None:
            try:
                t   = (math.sin(_g["phase"]) + 1.0) / 2.0
                col = _lerp_hex(_g["lo"], _g["hi"], t)
                for w in glow_widgets:
                    w.configure(bg=col)
                _g["phase"] += 0.10
                ind_f.after(90, _pulse)
            except tk.TclError:
                pass  # 창 닫힘 시 안전 종료

        ind_f.after(80, _pulse)

    # ══════════════════════════════════════════════════════════════
    # 2열 — 중앙 패널: 거시적 추세 메시지창 + 국지적 4TF Stoch RSI
    # ══════════════════════════════════════════════════════════════
    def _build_center_panel(self, parent: tk.Frame) -> None:

        # ── ⓪ 활성 포지션 인디케이터 바 ──────────────────────────
        self._build_position_indicator(parent)

        # ── ① 상단 헤더 ──────────────────────────────────────────
        hdr = tk.Frame(parent, bg=DARK_HEADER, pady=6)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  📡  거시적 추세 분석",
                 bg=DARK_HEADER, fg=ACCENT_BLUE,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(6, 0))

        # ── ② 거시적 추세 메시지창 (1H · 4H · 1D 실시간) ──────────
        _MAC_BG = "#0E0E10"
        self._macro_f = tk.Frame(parent, bg=_MAC_BG, pady=6)
        self._macro_f.pack(fill="x")
        self._macro_ico_lbl = tk.Label(
            self._macro_f,
            text="⚪   분석 대기 중  —  심볼 배정 후 자동 시작",
            bg=_MAC_BG, fg=DIM_TEXT,
            font=("Segoe UI", 9, "bold"))
        self._macro_ico_lbl.pack(padx=10, pady=(2, 2))
        _tf_row = tk.Frame(self._macro_f, bg=_MAC_BG)
        _tf_row.pack(fill="x", padx=10, pady=(4, 2))
        self._macro_tf_row = _tf_row
        for _idx, (_tf_key, _tf_name) in enumerate(
                (("tf1h", "1H"), ("tf4h", "4H"), ("tf1d", "1D"))):
            if _idx > 0:
                tk.Frame(_tf_row, bg="#333333", width=1).pack(
                    side="left", fill="y", pady=2)
            _l = tk.Label(_tf_row,
                          text=f"{_tf_name} K  —.— D  —.— ↔",
                          bg=_MAC_BG, fg=DIM_TEXT,
                          font=("Consolas", 7), anchor="center")
            _l.pack(side="left", expand=True, fill="x")
            self._macro_tf_lbls[_tf_key] = _l

        # ── ③ 구분선 ─────────────────────────────────────────────
        tk.Frame(parent, bg="#2A2A2A", height=1).pack(fill="x", pady=(4, 0))

        # ── ④ 국지적 4TF Stoch RSI 헤더 ─────────────────────────
        stoch_hdr = tk.Frame(parent, bg=DARK_HEADER, pady=4)
        stoch_hdr.pack(fill="x")
        tk.Label(stoch_hdr, text="  📈  Stoch RSI  모니터링  (국지적 4TF)",
                 bg=DARK_HEADER, fg=ACCENT_BLUE,
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(6, 0))

        # ── ⑤ 4TF 미니차트 그리드 ───────────────────────────────
        TF_H   = 160
        N_PTS  = 22
        SPEEDS = {"1m": 0.20, "3m": 0.13, "5m": 0.09, "15m": 0.04}
        _PL, _PR, _PT, _PB = 4, 24, 5, 4

        tf_anim: dict = {}
        for i, tf in enumerate(TF_KEYS):
            k0  = 50.0   # 초기 중립값 — 폴링으로 실수치 교정
            d0  = 50.0
            amp = 20 + i * 3
            pk  = i * 1.1
            pd  = pk + 0.6
            spd = SPEEDS[tf]
            k_h = [max(2.0, min(98.0,
                       k0 + amp * math.sin(pk - spd * (N_PTS - 1 - j))))
                   for j in range(N_PTS)]
            d_h = [max(2.0, min(98.0,
                       d0 + (amp - 6) * math.sin(pd - spd * (N_PTS - 1 - j))))
                   for j in range(N_PTS)]
            tf_anim[tf] = {
                "k_hist": k_h, "d_hist": d_h,
                "pk": pk, "pd": pd,
                "amp": amp, "ck": k0, "cd": d0, "spd": spd,
                "state0": "상승 ▲",
                "col0":   POSITIVE,
            }

        tf_row = tk.Frame(parent, bg="#0E0E0E")
        tf_row.pack(fill="x")

        ctr_tf_w = 84
        for i, tf in enumerate(TF_KEYS):
            if i > 0:
                tk.Frame(tf_row, bg="#333333", width=2).pack(side="left", fill="y")
            cf = tk.Frame(tf_row, bg="#0E0E0E")
            cf.pack(side="left", fill="both", expand=True)

            tk.Label(cf, text=tf,
                     bg=DARK_HEADER, fg=ACCENT_BLUE,
                     font=("Segoe UI", 10, "bold"),
                     anchor="center", width=6).pack(fill="x", ipady=3)
            tk.Frame(cf, bg="#2A2A2A", height=1).pack(fill="x")

            cv = tk.Canvas(cf, bg="#0E0E0E", width=ctr_tf_w, height=TF_H,
                           highlightthickness=0)
            cv.pack(side="top", fill="x")

            tk.Frame(cf, bg="#2A2A2A", height=1).pack(fill="x")

            slbl = tk.Label(cf, text="대기",
                            bg="#111111", fg=DIM_TEXT,
                            font=("Segoe UI", 8, "bold"), anchor="center",
                            wraplength=ctr_tf_w - 4)
            slbl.pack(fill="x", ipady=3)

            tf_anim[tf]["cv"]   = cv
            tf_anim[tf]["slbl"] = slbl

        def _draw_cv(cv: tk.Canvas, kh: list, dh: list) -> None:
            cv.delete("all")
            W = cv.winfo_width()  or ctr_tf_w
            H = cv.winfo_height() or TF_H
            N = len(kh)

            def fy(v: float) -> float:
                return _PT + (1.0 - v / 100.0) * (H - _PT - _PB)

            def fx(i: int) -> float:
                return _PL + i / max(1, N - 1) * (W - _PL - _PR)

            y80 = fy(80.0);  y20 = fy(20.0)
            x = _PL
            while x < W - _PR:
                cv.create_line(x, y80, min(x + 3, W - _PR), y80,
                               fill="#2A2A2A", width=1)
                cv.create_line(x, y20, min(x + 3, W - _PR), y20,
                               fill="#2A2A2A", width=1)
                x += 6

            for val, y in ((100, _PT), (80, y80), (20, y20), (0, H - _PB)):
                cv.create_text(W - 1, y, text=f"{val:3d}",
                               fill="#3D3D3D", font=("Consolas", 5), anchor="ne")

            slope = kh[-1] - kh[-4] if N >= 4 else 0.0
            k_col = POSITIVE if slope > 1.5 else (NEGATIVE if slope < -1.5 else YELLOW)

            d_pts = []
            for i, v in enumerate(dh):
                d_pts += [fx(i), fy(v)]
            if len(d_pts) >= 4:
                cv.create_line(d_pts, fill=ACCENT_BLUE, width=1.5,
                               smooth=True, joinstyle="round")

            k_pts = []
            for i, v in enumerate(kh):
                k_pts += [fx(i), fy(v)]
            if len(k_pts) >= 4:
                cv.create_line(k_pts, fill=k_col, width=2,
                               smooth=True, joinstyle="round")

            kex, key_ = fx(N - 1), fy(kh[-1])
            dex, dey  = fx(N - 1), fy(dh[-1])
            cv.create_oval(kex - 2.5, key_ - 2.5, kex + 2.5, key_ + 2.5,
                           fill=k_col, outline="")
            cv.create_oval(dex - 2,   dey - 2,   dex + 2,   dey + 2,
                           fill=ACCENT_BLUE, outline="")
            cv.create_text(W - 1, key_, text=f"{kh[-1]:.0f}",
                           fill=k_col, font=("Consolas", 7, "bold"), anchor="e")
            offset = -8 if abs(key_ - dey) < 10 else 0
            cv.create_text(W - 1, dey + offset, text=f"{dh[-1]:.0f}",
                           fill=ACCENT_BLUE, font=("Consolas", 7), anchor="e")

        def _tick(anim: dict = tf_anim, n: int = N_PTS) -> None:
            if not self._tf_ticking:
                return
            try:
                for tf_k, a in anim.items():
                    if a.get("use_real"):
                        # 실데이터 모드 — 2초 주기 교체 후 재그리기만
                        _draw_cv(a["cv"], a["k_hist"], a["d_hist"])
                    else:
                        # 정현파 폴백 — 실데이터 미수신 시
                        a["pk"] += a["spd"]
                        a["pd"] += a["spd"]
                        nk = max(2.0, min(98.0,
                                 a["ck"] + a["amp"] * math.sin(a["pk"])))
                        nd = max(2.0, min(98.0,
                                 a["cd"] + (a["amp"] - 6) * math.sin(a["pd"])))
                        a["k_hist"].append(nk);  a["k_hist"] = a["k_hist"][-n:]
                        a["d_hist"].append(nd);  a["d_hist"] = a["d_hist"][-n:]
                        _draw_cv(a["cv"], a["k_hist"], a["d_hist"])
                        sl = a["k_hist"][-1] - a["k_hist"][-4] if len(a["k_hist"]) >= 4 else 0
                        if nk > 80:
                            st, sc = "과매수",    NEGATIVE
                        elif nk < 20:
                            st, sc = "과매도",    POSITIVE
                        elif sl > 1.5:
                            st, sc = a["state0"], a["col0"]
                        elif sl < -1.5:
                            st, sc = "하락 ▼",    NEGATIVE
                        else:
                            st, sc = "횡보 ↔",    YELLOW
                        a["slbl"].configure(text=st, fg=sc)
                list(anim.values())[0]["cv"].after(320, _tick)
            except tk.TclError:
                pass

        def _start(anim: dict = tf_anim) -> None:
            for a in anim.values():
                _draw_cv(a["cv"], a["k_hist"], a["d_hist"])
            list(anim.values())[0]["cv"].after(320, _tick)

        self._tf_anim    = tf_anim
        self._tf_tick_fn = _tick
        self.after(60, self._freeze_tf_charts)   # 초기: 하단 동결 상태

        # ── ⑥ 4TF 그리드 하단 여백 (5px, Footer 와 동일 톤) ─────────
        tk.Frame(parent, bg=DARK_HEADER, height=5).pack(fill="x")

        # ── ⑦ 여백 ↔ 하단 공백 구분선 (1px, 밝은 톤으로 가시성 확보) ──
        tk.Frame(parent, bg="#3A3A3A", height=1).pack(fill="x")

        # ── ⑧ 전략 파라미터 요약 + 엔진 최근 액션 라벨 ──────────────
        sig_f = tk.Frame(parent, bg="#0A0A0F", pady=4)
        sig_f.pack(fill="x")
        self._param_info_lbl = tk.Label(
            sig_f,
            text="—  전략 미설정  —",
            bg="#0A0A0F", fg=DIM_TEXT,
            font=("Consolas", 7), anchor="center")
        self._param_info_lbl.pack(fill="x", padx=6)
        self._last_sig_lbl = tk.Label(
            sig_f,
            text="—  엔진 대기 중  —",
            bg="#0A0A0F", fg=DIM_TEXT,
            font=("Consolas", 8), anchor="center")
        self._last_sig_lbl.pack(fill="x", padx=6)

        # ── ⑨ 하단 잔여 공백 — 1·3열 Footer 와 동일한 톤으로 채워 정리 ─
        tk.Frame(parent, bg=DARK_HEADER).pack(fill="both", expand=True)

    # ══════════════════════════════════════════════════════════════
    # 중앙 컨트롤 세션 — 실데이터 폴링 / 상태 갱신
    # ══════════════════════════════════════════════════════════════
    @staticmethod
    def _judge_macro_trend(ind: dict) -> tuple[str, str, str, str]:
        """tf1h/tf4h/tf1d 기반 거시적 추세 판정 (1H · 4H · 1D).
        Returns: (fg_color, icon, trend_text, sub_text)
        """
        score = 0
        for key in ("tf1h", "tf4h", "tf1d"):
            td = ind.get(key, {})
            k, d = td.get("k", 50.0), td.get("d", 50.0)
            if k > d and abs(k - d) >= 2.0:
                score += 1
            elif k < d and abs(k - d) >= 2.0:
                score -= 1
        if   score ==  3: return POSITIVE, "🟢", "강한 상승 추세",  "1H · 4H · 1D 전 TF 상승"
        elif score ==  2: return YELLOW,   "🟡", "상승 우세 혼조",  "3TF 중 2개 상승"
        elif score ==  1: return YELLOW,   "🟡", "약 상승 혼조",    "3TF 중 1개 상승"
        elif score == -1: return ORANGE,   "🟠", "약 하락 혼조",    "3TF 중 1개 하락"
        elif score == -2: return ORANGE,   "🔴", "하락 우세 혼조",  "3TF 중 2개 하락"
        elif score == -3: return NEGATIVE, "🔴", "강한 하락 추세",  "1H · 4H · 1D 전 TF 하락"
        else:             return DIM_TEXT, "⚪", "방향 탐색 중",    "TF 간 방향 혼조"

    @staticmethod
    def _calc_macro_score(ind: dict) -> int:
        """tf1h/tf4h/tf1d K·D 기반 거시적 추세 점수 계산. -3 ~ +3."""
        score = 0
        for key in ("tf1h", "tf4h", "tf1d"):
            td = ind.get(key, {})
            k, d = td.get("k", 50.0), td.get("d", 50.0)
            if k > d and abs(k - d) >= 2.0:
                score += 1
            elif k < d and abs(k - d) >= 2.0:
                score -= 1
        return score

    def _update_position_indicator(self, is_long: bool | None) -> None:
        """포지션 인디케이터 텍스트·색·글로우 색상 갱신."""
        if not self._pos_ind:
            return
        if is_long is True:
            txt, fg, lo, hi = "◀   🟢   롱 포지션 활성", POSITIVE, "#071512", "#0D5C2A"
        elif is_long is False:
            txt, fg, lo, hi = "🔴   숏 포지션 활성   ▶", NEGATIVE, "#150709", "#5C0D1E"
        else:
            txt, fg, lo, hi = "방향 미확정  대기중",  DIM_TEXT,  "#1A1A1A", "#2A2A2A"
        self._pos_glow.update({"lo": lo, "hi": hi})
        self._pos_ind["lbl"].configure(text=txt, fg=fg)

    def _update_center(self) -> None:
        """실데이터로 중앙 컨트롤 세션 전체 갱신 (2초 폴링마다 호출)."""
        sym = self._shared_sym.get()
        if not sym:
            return
        ind = get_ind(sym)
        if not ind:
            return

        # ① 거시적 추세 업데이트 (1H · 4H · 1D)
        col, ico, trend_txt, sub_txt = self._judge_macro_trend(ind)
        mac_bg = (
            "#0E1A10" if col == POSITIVE else
            "#1F0A0F" if col in (NEGATIVE, ORANGE) else
            "#0E0E10"
        )
        if self._macro_f:
            self._macro_f.configure(bg=mac_bg)
        if self._macro_tf_row:
            self._macro_tf_row.configure(bg=mac_bg)
            for _w in self._macro_tf_row.winfo_children():
                try: _w.configure(bg=mac_bg)
                except tk.TclError: pass
        if self._macro_ico_lbl:
            self._macro_ico_lbl.configure(
                text=f"{ico}  {trend_txt}  —  {sub_txt}", fg=col, bg=mac_bg)
        for tf_key, tf_name in (("tf1h", "1H"), ("tf4h", "4H"), ("tf1d", "1D")):
            lbl = self._macro_tf_lbls.get(tf_key)
            if lbl is None:
                continue
            td  = ind.get(tf_key, {})
            k   = td.get("k", 50.0)
            d   = td.get("d", 50.0)
            dr  = td.get("dir", "↔")
            c   = POSITIVE if dr == "▲" else (NEGATIVE if dr == "▼" else DIM_TEXT)
            lbl.configure(
                text=f"{tf_name} K{k:5.1f} D{d:5.1f} {dr}",
                fg=c, bg=mac_bg)

        # ② 4TF 미니차트 실수치 교정 (1m · 3m · 5m · 15m)
        for tf, ind_key in (("1m","tf1"), ("3m","tf3"), ("5m","tf5"), ("15m","tf15")):
            a = self._tf_anim.get(tf)
            if a is None:
                continue
            td  = ind.get(ind_key, {})
            k   = td.get("k", 50.0)
            d   = td.get("d", 50.0)
            a["ck"] = k
            a["cd"] = d
            ks = td.get("k_series", [])
            ds = td.get("d_series", [])
            n_pts = len(a.get("k_hist", [])) or 22
            if len(ks) >= 4 and len(ds) >= 4:
                a["k_hist"] = [max(2.0, min(98.0, v)) for v in ks[-n_pts:]]
                a["d_hist"] = [max(2.0, min(98.0, v)) for v in ds[-n_pts:]]
                a["use_real"] = True
            slbl = a.get("slbl")
            if slbl:
                if   k > 80:       st, sc = "과매수", NEGATIVE
                elif k < 20:       st, sc = "과매도", POSITIVE
                elif k > d + 2.0:  st, sc = "상승 ▲", POSITIVE
                elif k < d - 2.0:  st, sc = "하락 ▼", NEGATIVE
                else:              st, sc = "횡보 ↔", YELLOW
                slbl.configure(text=st, fg=sc)

        # ③ 포지션 인디케이터 — 전략 모드에 따라 판단 기준 분기
        use_macro = (self._applied_params or {}).get("use_macro", True)
        if use_macro:
            # 거시적 추세(1H·4H·1D) 방향으로 롱/숏 결정
            score = self._calc_macro_score(ind)
            if   score >= 1:  self._update_position_indicator(True)
            elif score <= -1: self._update_position_indicator(False)
            else:             self._update_position_indicator(None)
        else:
            # 국지적 4TF 과반(3/4 이상) 합의로 롱/숏 결정
            signal = FourTFConsensus.evaluate(ind)
            if   signal.aligned_long  >= 3: self._update_position_indicator(True)
            elif signal.aligned_short >= 3: self._update_position_indicator(False)
            else:                           self._update_position_indicator(None)

    def _poll_center(self) -> None:
        """2초 주기 중앙 컨트롤 세션 폴링 루프."""
        if not self._center_running:
            return
        try:
            self._update_center()
            self._update_price_charts()
            has_open = (self._engine is not None
                        and self._engine.has_open_positions())
            if self._trading_active or has_open:
                self._update_engine_panels()
            self._update_last_signal_lbl()
        except Exception:
            pass
        try:
            self.after(2000, self._poll_center)
        except Exception:
            pass

    def _update_param_info_lbl(self) -> None:
        """전략 파라미터 요약(전략명·Funds·Lev·SL·Trail) + API 키 상태를 표시."""
        if self._param_info_lbl is None:
            return
        ap = self._applied_params
        if ap is None or not self._strategy_ready:
            self._param_info_lbl.configure(
                text="—  전략 미설정  —", fg=DIM_TEXT)
            return
        mode  = self._applied_sort_mode or "—"
        funds = ap.get("funds", "—")
        lev   = ap.get("leverage", "—")
        sl    = ap.get("sl", 2.5)
        trail = ap.get("trail", 1.5)
        has_key = bool(self._engine is not None and
                       getattr(self._engine, "is_live", False))
        if self._engine is not None and not has_key:
            txt = (f"⚠ API 키 미설정  [{mode}]  Funds {funds}%  ×{lev}  "
                   f"SL {sl:.1f}%  Trail {trail:.1f}%")
            clr = ORANGE
        else:
            txt = (f"[{mode}]  Funds {funds}%  ×{lev}  "
                   f"SL {sl:.1f}%  Trail {trail:.1f}%")
            clr = "#5577AA"
        self._param_info_lbl.configure(text=txt, fg=clr)

    def _update_last_signal_lbl(self) -> None:
        """엔진 최근 액션(last_signal / error_msg)·잔고 상태를 중앙 라벨에 갱신."""
        if self._last_sig_lbl is None or self._engine is None:
            return
        try:
            st  = self._engine.get_state()
            err = st.error_msg or ""
            sig = st.last_signal or ""

            long_open  = (st.long_pos  is not None
                          and st.long_pos.state  == PositionState.OPEN)
            short_open = (st.short_pos is not None
                          and st.short_pos.state == PositionState.OPEN)
            pos_open   = long_open or short_open

            if err:
                self._last_sig_lbl.configure(text=f"⚠  {err}", fg=NEGATIVE)
            elif pos_open:
                if sig:
                    if "롱 진입" in sig:
                        fg = POSITIVE
                    elif "숏 진입" in sig:
                        fg = NEGATIVE
                    elif "청산" in sig or "익절" in sig:
                        fg = YELLOW
                    else:
                        fg = DIM_TEXT
                    self._last_sig_lbl.configure(text=f"🔔  {sig}", fg=fg)
                else:
                    side_txt = "롱" if long_open else "숏"
                    self._last_sig_lbl.configure(
                        text=f"⏳  {side_txt} 포지션 보유 중  —  신호 대기",
                        fg=ACCENT_BLUE)
            else:
                bal = self._ui_balance
                if bal is None:
                    bal = st.last_balance
                if bal is not None:
                    if bal > 0:
                        blk_long     = getattr(st, "last_blocked_long",   "")
                        blk_short    = getattr(st, "last_blocked_short",  "")
                        blocked      = getattr(st, "last_blocked_reason", "")
                        side_pfx     = getattr(st, "last_blocked_side",   "")
                        next_scan_at = getattr(st, "next_scan_at",         0.0)
                        remaining    = max(0, int(next_scan_at - time.time())) if next_scan_at > 0 else 0
                        if blk_long and blk_short:
                            self._last_sig_lbl.configure(
                                text=(f"📵 롱 [{remaining:02d}s] {blk_long}"
                                      f"  |  📵 숏 {blk_short}"),
                                fg=ORANGE)
                        elif blocked:
                            pfx = "📵 롱" if side_pfx == "long" else "📵 숏"
                            self._last_sig_lbl.configure(
                                text=f"{pfx} 차단  [{remaining:02d}s]  —  {blocked}",
                                fg=ORANGE)
                        else:
                            if remaining > 0:
                                self._last_sig_lbl.configure(
                                    text=f"✅  {bal:.2f} USDT  —  다음 스캔 {remaining:02d}s",
                                    fg=POSITIVE)
                            else:
                                self._last_sig_lbl.configure(
                                    text=f"✅  {bal:.2f} USDT  —  거래 대기 중",
                                    fg=POSITIVE)
                    else:
                        self._last_sig_lbl.configure(
                            text="⛔  잔고 없음  —  Initial Investment로 자금 이체 필요",
                            fg=ORANGE)
                elif sig:
                    fg = YELLOW if ("청산" in sig or "익절" in sig) else DIM_TEXT
                    self._last_sig_lbl.configure(text=f"🔔  {sig}", fg=fg)
                else:
                    self._last_sig_lbl.configure(
                        text="—  엔진 대기 중  —", fg=DIM_TEXT)
        except Exception:
            pass

    def _refresh_ui_balance_bg(self) -> None:
        """거래 완료 후 잔고 재조회 (배경 스레드) → _last_sig_lbl 즉시 갱신."""
        if self._engine is None:
            return
        def _fetch() -> None:
            val = self._engine._client.get_account_balance()
            self._ui_balance = val
            try:
                self.after(0, self._update_last_signal_lbl)
            except tk.TclError:
                pass
        _threading.Thread(target=_fetch, daemon=True).start()

    def _reset_center(self) -> None:
        """심볼 해제 시 중앙 컨트롤 세션 초기 상태 복귀."""
        self._tf_ticking = False
        self._pnl_running = False
        if self._app_started and self._pos_ind:
            self._pos_ind["lbl"].configure(
                text="코인 심볼 및 전략을 선택하세요!", fg=YELLOW)
        else:
            self._update_position_indicator(None)
        mac_bg = "#0E0E10"
        if self._macro_f:
            self._macro_f.configure(bg=mac_bg)
        if self._macro_tf_row:
            self._macro_tf_row.configure(bg=mac_bg)
            for _w in self._macro_tf_row.winfo_children():
                try: _w.configure(bg=mac_bg)
                except tk.TclError: pass
        if self._macro_ico_lbl:
            self._macro_ico_lbl.configure(
                text="⚪   분석 대기 중  —  심볼 배정 후 자동 시작",
                fg=DIM_TEXT, bg=mac_bg)
        for tf_key, tf_name in (("tf1h","1H"), ("tf4h","4H"), ("tf1d","1D")):
            lbl = self._macro_tf_lbls.get(tf_key)
            if lbl:
                lbl.configure(
                    text=f"{tf_name} K  —.— D  —.— ↔",
                    fg=DIM_TEXT, bg=mac_bg)
        for a in self._tf_anim.values():
            a["ck"] = 50.0
            a["cd"] = 50.0
            a["use_real"] = False
        self.after(50, self._freeze_tf_charts)
        self._update_engine_panels()
        self._update_price_charts()
        self._update_param_info_lbl()

    def _freeze_tf_charts(self) -> None:
        """대기 모드 — 4TF 캔버스를 하단 수평선으로 동결."""
        _PL, _PR, _PT, _PB = 4, 24, 5, 4
        TF_H = 160
        for a in self._tf_anim.values():
            cv   = a.get("cv")
            slbl = a.get("slbl")
            if cv is None:
                continue
            try:
                cv.delete("all")
                W = cv.winfo_width()  or 84
                H = cv.winfo_height() or TF_H
                y80 = _PT + (1.0 - 80.0 / 100.0) * (H - _PT - _PB)
                y20 = _PT + (1.0 - 20.0 / 100.0) * (H - _PT - _PB)
                y_bot = _PT + (1.0 - 5.0 / 100.0) * (H - _PT - _PB)
                x = _PL
                while x < W - _PR:
                    cv.create_line(x, y80, min(x + 3, W - _PR), y80,
                                   fill="#2A2A2A", width=1)
                    cv.create_line(x, y20, min(x + 3, W - _PR), y20,
                                   fill="#2A2A2A", width=1)
                    x += 6
                for val, yv in ((100, _PT), (80, y80), (20, y20), (0, H - _PB)):
                    cv.create_text(W - 1, yv, text=f"{val:3d}",
                                   fill="#3D3D3D", font=("Consolas", 5), anchor="ne")
                cv.create_line(_PL, y_bot, W - _PR, y_bot,
                               fill=ACCENT_BLUE, width=1)
                cv.create_line(_PL, y_bot, W - _PR, y_bot,
                               fill=DIM_TEXT, width=1.5)
            except tk.TclError:
                pass
            if slbl:
                try:
                    slbl.configure(text="대기", fg=DIM_TEXT)
                except tk.TclError:
                    pass

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
        except Exception:
            pass

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

        _state  = self._engine.get_state() if self._engine else None
        err_msg = (_state.error_msg or "") if _state else ""

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
                self._refresh_engine_panel(panel, side, trading_on, direction, ind, pos, err_msg)
            except tk.TclError:
                pass

    def _refresh_engine_panel(self, panel: dict, side: str,
                              trading_on: bool, direction: str | None,
                              ind: dict,
                              pos=None, err: str = "") -> None:
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
            if   k1 < 20:  _pt, _pc = "1m 과매도 진입 신호 대기 중", POSITIVE
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
            _pt, _pc  = "4TF 합의 대기 중", DIM_TEXT

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
