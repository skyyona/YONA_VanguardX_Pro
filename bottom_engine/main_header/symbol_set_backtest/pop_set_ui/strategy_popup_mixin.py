from __future__ import annotations
import json
import tkinter as tk
from tkinter import ttk
import threading as _threading
from core.config import (
    DARK_BG, DARK_PANEL, DARK_HEADER, DARK_ROW_ODD, DARK_ROW_EVN,
    DARK_TEXT, DIM_TEXT, ACCENT_BLUE, POSITIVE, NEGATIVE, ORANGE, YELLOW,
    LONG_HDR_BG, SHORT_HDR_BG,
)
from bottom_engine.strategy_settings.realtrade_strategy_sort_by import get_mode_config as _get_mode_cfg
from bottom_engine.strategy_settings.strategy_loader import StrategyLoader
from bottom_engine.models import PositionState, ProhibitionFlags
from bottom_engine.backtest.historical_data_loader import HistoricalDataLoader
from bottom_engine.backtest.backtest_runner import BacktestRunner

TF_KEYS = ["1m", "3m", "5m", "15m"]

_BASE_SL    = 2.5
_BASE_TRAIL = 1.5
_HAS_BACKTEST = True


def _backtest_result_to_dict(result: "BacktestResult") -> dict:  # type: ignore[name-defined]
    """BacktestResult → _populate_tab2() 가 기대하는 dict 구조로 변환."""
    long_trades  = [t for t in result.trades if t.side == "long"]
    short_trades = [t for t in result.trades if t.side == "short"]

    def _side_stats(trades: list, period_days: int) -> dict:
        if not trades:
            return {"count": 0, "hit": "0%", "avg": "—", "max": "—",
                    "total": "—", "total_usdt": "—", "rr_ratio": "—",
                    "profit_factor": "—", "avg_loss": "—", "avg_hold": "—",
                    "max_consec_loss": "0회", "daily_freq": "0.00회"}
        wins   = [t for t in trades if t.pnl_pct > 0]
        losses = [t for t in trades if t.pnl_pct <= 0]
        wr      = len(wins) / len(trades) * 100
        avg_w   = sum(t.pnl_pct for t in wins)   / max(len(wins),   1)
        avg_l   = sum(t.pnl_pct for t in losses) / max(len(losses), 1)
        mx       = max(t.pnl_pct  for t in trades)
        tot      = sum(t.pnl_pct  for t in trades)
        tot_usdt = sum(t.pnl_usdt for t in trades)
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
            "total_usdt":      f"{tot_usdt:+.2f} U",
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
        "sort_mode":            result.sort_mode,
        "long_ratio_coverage":  result.long_ratio_coverage,
        "long":        _side_stats(long_trades,  pd_),
        "short":       _side_stats(short_trades, pd_),
        "total": {
            "return": f"{result.total_return:+.1f}%",
            "win":    f"{result.win_rate:.0f}%",
            "max":    f"{result.max_profit:+.1f}%",
            "mdd":    f"-{result.max_drawdown:.1f}%",
        },
    }


class StrategyPopupMixin:
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
                  command=lambda: self._confirm_strategy(win, _selected_sort_ref[0], _consensus_var.get())
                  ).pack(anchor="center", pady=(4, 0))

        # [중간] 백테스팅 결과 요약 (항상 표시 — 백테스팅 전: "—", 후: 실제값)
        footer_mid = tk.Frame(win, bg=DARK_PANEL, pady=4)
        footer_mid.pack(fill="x", side="bottom")
        tk.Frame(footer_mid, bg="#2A2A2A", height=1).pack(fill="x")

        _stat_label_items = [
            ("4TF 정렬 적중도",       "hit"),
            ("단일 거래 최대 수익률", "max"),
            ("기간 총 수익률",        "total"),
            ("예상 USDT 총손익",      "total_usdt"),
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

        # 전략 비교 버튼
        cmp_btn = tk.Button(footer_row1, text="  📊  전략 비교  ",
                            bg=DARK_PANEL, fg=DIM_TEXT,
                            activebackground="#252525",
                            activeforeground=DARK_TEXT,
                            font=("Segoe UI", 8), relief="flat",
                            padx=8, pady=4, cursor="hand2",
                            state="disabled")
        cmp_btn.pack(side="left", padx=(12, 0), pady=(4, 0))

        # 합의 모드 선택 Combobox — 실거래·백테스트 양쪽 동시 제어
        _init_mode = (self._applied_params.get("consensus_mode", "4/4")
                      if self._applied_params else "4/4")
        _consensus_var = tk.StringVar(value=_init_mode)
        _consensus_cb = ttk.Combobox(
            footer_row1,
            textvariable=_consensus_var,
            values=["4/4", "3/4"],
            state="readonly", width=8,
            font=("Segoe UI", 7),
        )
        _consensus_cb.pack(side="left", padx=(8, 0), pady=(4, 0))

        bt_btn = tk.Button(footer_row1, text="  ▶  백테스팅  ",
                           bg=DARK_PANEL, fg=ACCENT_BLUE,
                           activebackground="#252525", activeforeground=ACCENT_BLUE,
                           font=("Segoe UI", 8, "bold"), relief="flat",
                           padx=10, pady=4, cursor="hand2",
                           state="disabled")
        bt_btn.pack(side="left", padx=(8, 0), pady=(4, 0))

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
                _cm = self._restore_strategy_vars(mode)
                if _cm:                        # [B-4] 저장된 consensus_mode 복원
                    _consensus_var.set(_cm)
                for opt, b in sort_btns.items():
                    sel = (opt == mode)
                    b.configure(
                        bg="#1E2A1E" if sel else DARK_PANEL,
                        fg=POSITIVE if sel else DARK_TEXT,
                        font=("Segoe UI", 8, "bold" if sel else "normal"))
                cfg = _get_mode_cfg(mode)
                from bottom_engine.engine_core.sl_calculator import SLCalculator as _SLC
                # Sort by 팝업은 심볼 독립 UI — sym 없으므로 mmr은 Binance USDT-M 표준값 사용
                _sl_used_s, _ = _SLC.clamp(
                    self._sl_var.get(), self._trail_var.get(),
                    self._lev_var.get(), mmr=0.004)
                _atr_min_eff_s = max(cfg.atr_min, _sl_used_s / 2.0)
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
                          f"  |  ATR {_atr_min_eff_s:.1f}~{cfg.atr_max:.1f}%{_extra}"))
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
                from bottom_engine.engine_core.sl_calculator import SLCalculator as _SLC
                # Sort by 팝업은 심볼 독립 UI — sym 없으므로 mmr은 Binance USDT-M 표준값 사용
                _sl_used_c, _ = _SLC.clamp(
                    self._sl_var.get(), self._trail_var.get(),
                    self._lev_var.get(), mmr=0.004)
                _atr_min_eff_c = max(cfg.atr_min, _sl_used_c / 2.0)

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
                                      f"{_atr_min_eff_c:.1f}% ~ {cfg.atr_max:.1f}%", ACCENT_BLUE)
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
                                      f"{_atr_min_eff_c:.1f}% ~ {cfg.atr_max:.1f}%", ACCENT_BLUE)
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
                from bottom_engine.engine_core.sl_calculator import SLCalculator as _SLC
                # Sort by 팝업은 심볼 독립 UI — sym 없으므로 mmr은 Binance USDT-M 표준값 사용
                _sl_used_b, _ = _SLC.clamp(
                    self._sl_var.get(), self._trail_var.get(),
                    self._lev_var.get(), mmr=0.004)
                _atr_min_eff_b = max(cfg_ban.atr_min, _sl_used_b / 2.0)

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
                          f"{_atr_min_eff_b:.1f}% ~ {cfg_ban.atr_max:.1f}%", ACCENT_BLUE)

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
            _ban_row("common_liq",    "청산 근접도 위험 구간 진입 (강제 청산가 근접)")
            _ban_row("common_fr",     "FR(펀딩비)  임계치 초과  —  과열 신호")
            _ban_row("common_new",    "신규 상장 심볼  —  가용 데이터 14일 미만")
            _ban_row("common_hunter", "Player Detection  '청산 헌터'  태그 감지")

            _ban_sec_hdr("롱 포지션 전용 금지 조건")
            _ban_row("long_fomo",      "Player Detection  'FOMO 극단'  태그 감지 시 롱 진입 금지")

            _ban_sec_hdr("숏 포지션 전용 금지 조건")
            _ban_row("short_accum",    "Player Detection  '세력 매집'  태그 감지 시 숏 진입 금지")

        # ── 백테스팅 실행 ─────────────────────────────────────────
        def _do_backtest() -> None:
            bt_btn.configure(state="disabled", cursor="arrow")
            cmp_btn.configure(state="disabled", cursor="arrow")
            status_lbl.configure(text="  백테스팅 실행 중...  ", fg=YELLOW)

            # UI 변수에서 현재 설정 파라미터 직접 읽기
            funds, lev, sl, trail = self._current_params()
            # [B-1] 실잔고 조회 — last_balance 캐시 우선, 없으면 1000.0 기본값
            _portfolio_usdt = 1000.0
            if self._engine is not None:
                _st = self._engine.get_state()
                if _st.last_balance and _st.last_balance > 0:
                    _portfolio_usdt = _st.last_balance
            from bottom_engine.models import StrategyParams as _SP, ProhibitionFlags as _PF
            params = _SP(
                sort_mode      = _selected_sort_ref[0],
                funds_pct      = funds,
                leverage       = lev,
                stop_loss      = sl,
                trail_stop     = trail,
                prohibition    = _PF.from_dict({k: v.get() for k, v in self._prohibited_vars.items()}),
                use_macro      = self._use_macro_var.get(),
                portfolio_usdt = _portfolio_usdt,   # [B-1]
            )

            def _run() -> None:
                # [C-2] MMR 조회 — 캐시 미스 시 REST 호출. 워커 스레드 전용
                if self._engine is not None:
                    params.mmr = self._engine.get_mmr(sym)
                from bottom_engine.engine_core.sl_calculator import SLCalculator as _SLC
                _sl_used, _trail_used = _SLC.clamp(
                    params.stop_loss, params.trail_stop, params.leverage, mmr=params.mmr)
                try:
                    if _HAS_BACKTEST and BacktestRunner is not None:
                        from bottom_engine.backtest.param_deriver import derive_params
                        period_key = _get_period_key(avail_days_ref[0])
                        mode       = _consensus_var.get()
                        result_obj = BacktestRunner.run(sym, params, period_key, mode)
                        res = _backtest_result_to_dict(result_obj)
                        res["derived"] = derive_params(result_obj.trades)
                    else:
                        res = {}
                except Exception:
                    res = {}
                res["sl_used"]    = _sl_used    # [C-2] 실제 적용 SL 표시용
                res["trail_used"] = _trail_used # [C-2] 실제 적용 Trail 표시용
                res["mmr_used"]   = params.mmr  # [C-2] 실제 적용 MMR 표시용
                win.after(0, lambda r=res: _backtest_done(r))

            _threading.Thread(target=_run, daemon=True).start()

        def _backtest_done(res: dict) -> None:
            long_r  = res.get("long",  {})
            short_r = res.get("short", {})
            win_str = res.get("total", {}).get("win", "—")
            _sl  = res.get("sl_used",    "—")
            _tr  = res.get("trail_used", "—")
            _mmr = res.get("mmr_used",   0.004)
            _sm  = res.get("sort_mode",  "—")
            _cov = res.get("long_ratio_coverage", 0.0)
            _cov_str = f"  L/S {_cov:.0f}%" if _cov > 0 else ""
            status_lbl.configure(
                text=f"  [{_sm}] 백테스팅 완료  ✓   적중도 {win_str}  |  SL {_sl}% / Trail {_tr}% / MMR {_mmr:.4f}{_cov_str}  ",
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

        # ── 전략 비교 실행 ────────────────────────────────────────
        def _do_comparison() -> None:
            bt_btn.configure(state="disabled", cursor="arrow")
            cmp_btn.configure(state="disabled", cursor="arrow")
            status_lbl.configure(text="  전략 비교 실행 중...  ", fg=YELLOW)

            # UI 변수에서 현재 설정 파라미터 직접 읽기
            funds, lev, sl, trail = self._current_params()
            # [B-1] 실잔고 조회 — last_balance 캐시 우선, 없으면 1000.0 기본값
            _portfolio_usdt = 1000.0
            if self._engine is not None:
                _st = self._engine.get_state()
                if _st.last_balance and _st.last_balance > 0:
                    _portfolio_usdt = _st.last_balance
            from bottom_engine.models import StrategyParams as _SP, ProhibitionFlags as _PF
            params = _SP(
                sort_mode      = _selected_sort_ref[0],
                funds_pct      = funds,
                leverage       = lev,
                stop_loss      = sl,
                trail_stop     = trail,
                prohibition    = _PF.from_dict({k: v.get() for k, v in self._prohibited_vars.items()}),
                use_macro      = self._use_macro_var.get(),
                portfolio_usdt = _portfolio_usdt,   # [B-1]
            )

            def _run_cmp() -> None:
                # [C-2] MMR 조회 — 캐시 미스 시 REST 호출. 워커 스레드 전용
                if self._engine is not None:
                    params.mmr = self._engine.get_mmr(sym)
                from bottom_engine.engine_core.sl_calculator import SLCalculator as _SLC
                _sl_used, _trail_used = _SLC.clamp(
                    params.stop_loss, params.trail_stop, params.leverage, mmr=params.mmr)
                try:
                    if _HAS_BACKTEST and BacktestRunner is not None:
                        period_key = _get_period_key(avail_days_ref[0])
                        cmp_results = BacktestRunner.run_comparison(
                            sym, params, period_key)
                    else:
                        cmp_results = {}
                except Exception:
                    cmp_results = {}
                cmp_results["sl_used"]    = _sl_used    # [C-2] 실제 적용 SL 표시용
                cmp_results["trail_used"] = _trail_used # [C-2] 실제 적용 Trail 표시용
                cmp_results["mmr_used"]   = params.mmr  # [C-2] 실제 적용 MMR 표시용
                cmp_results["sort_mode"]  = params.sort_mode
                win.after(0, lambda r=cmp_results: _comparison_done(r))

            _threading.Thread(target=_run_cmp, daemon=True).start()

        def _comparison_done(cmp_results: dict) -> None:
            _sl  = cmp_results.get("sl_used",    "—")
            _tr  = cmp_results.get("trail_used", "—")
            _mmr = cmp_results.get("mmr_used",   0.004)
            _sm  = cmp_results.get("sort_mode",  "—")
            status_lbl.configure(
                text=f"  [{_sm}] 전략 비교 완료  ✓  |  SL {_sl}% / Trail {_tr}% / MMR {_mmr:.4f}  ",
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
            """전략 비교 결과를 tab2에 렌더링."""
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
            tk.Label(hdr_f, text="  📊  전략 비교  (4/4 vs 3/4)",
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
            _MODES = ["4/4", "3/4"]
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

                from bottom_engine.backtest.param_deriver import derive_params as _derive
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
            # 전략 확정 후에만 엔진 라이브 업데이트
            if self._strategy_ready and self._applied_params is not None:
                self._applied_params.update({"funds": funds, "leverage": lev})
                if self._engine is not None and StrategyLoader is not None:
                    try:
                        ap = dict(self._applied_params)
                        params = StrategyLoader.save_from_applied(
                            ap, self._applied_sort_mode)
                        self._engine.update_params(params)
                    except Exception as e:
                        import tkinter.messagebox as _mb
                        _mb.showwarning("저장 실패", f"전략 설정 저장 실패:\n{e}")
                        return
                self._update_param_info_lbl()
            # 버튼 텍스트 갱신 — 확정 여부 무관 (_funds_var에 값 저장됨)
            self._funds_lev_btn.configure(
                text=f"  ✓  Funds {funds}%   |   {lev}x  ",
                bg="#0D2A1A", fg=POSITIVE,
                activebackground="#0A3A18", activeforeground=POSITIVE)
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
                from bottom_engine.engine_core.quality_grader import QualityGrader
                from bottom_engine.engine_core.sl_calculator import SLCalculator
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
            # 전략 확정 후에만 엔진 라이브 업데이트
            if self._strategy_ready and self._applied_params is not None:
                self._applied_params.update({"sl": sl, "trail": trail})
                if self._engine is not None and StrategyLoader is not None:
                    try:
                        ap = dict(self._applied_params)
                        params = StrategyLoader.save_from_applied(
                            ap, self._applied_sort_mode)
                        self._engine.update_params(params)
                    except Exception as e:
                        import tkinter.messagebox as _mb
                        _mb.showwarning("저장 실패", f"전략 설정 저장 실패:\n{e}")
                        return
                self._update_param_info_lbl()
            # 버튼 텍스트 갱신 — 확정 여부 무관 (_sl_var, _trail_var에 값 저장됨)
            self._sl_trail_btn.configure(
                text=f"  ✓  SL {sl:.1f}%   |   Trail {trail:.1f}%  ",
                bg="#0D2A1A", fg=POSITIVE,
                activebackground="#0A3A18", activeforeground=POSITIVE)
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
