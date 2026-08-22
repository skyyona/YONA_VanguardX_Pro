from __future__ import annotations
import tkinter as tk
from core.config import (
    DARK_BG, DARK_PANEL, DARK_HEADER, DARK_TEXT, DIM_TEXT,
    ACCENT_BLUE, POSITIVE, NEGATIVE, ORANGE, YELLOW,
    LONG_HDR_BG, SHORT_HDR_BG,
)


class HeaderUiMixin:
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

    def _clear_symbol(self) -> None:
        if self._trading_active:
            return
        self._shared_sym.set("")

    def _on_sort_mode_watch(self, *_) -> None:
        """Sort by 모드 변경 감지 → 전략 재확정 필요 경고 표시 + UI vars 동기화."""
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
            self._restore_strategy_vars(new_mode)  # lev/sl/trail/funds vars를 JSON 저장값으로 동기화
