"""
header/widget/investment_dialog.py
Initial Investment 설정 다이얼로그
"""
from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable

from core.config import (
    DARK_BG as _BG,
    DARK_PANEL as _PANEL,
    DARK_HEADER as _HDR,
    DARK_TEXT as _TEXT,
    POSITIVE as _POSITIVE,
    ORANGE as _ORANGE,
    NEGATIVE as _NEGATIVE,
)
from header.models import TransferDirection, WalletBalanceResult, WalletQueryStatus

_DIM = "#888888"
_SEP = "#2A2A2A"

_SLIDER_HEIGHT      = 28
_SLIDER_PAD         = 10
_SLIDER_KNOB_RADIUS = 7


class InvestmentDialog(tk.Toplevel):
    """Spot/Fiat <-> USDⓈ-M Futures 자금 이체 후, 이체된 자금을 거래 자금 기준점으로 설정하는 팝업."""

    def __init__(
        self,
        master: tk.Misc,
        spot_result: WalletBalanceResult,
        futures_result: WalletBalanceResult,
        futures_available_result: WalletBalanceResult,
        on_confirm_bg: Callable[[float, TransferDirection], WalletBalanceResult],
        on_confirm_done: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.title("Initial Investment 설정")
        self.configure(bg=_BG)
        self.resizable(False, False)

        self._master = master          # 루트 창 참조 (after() 호출용)
        self._on_confirm_bg   = on_confirm_bg    # 백그라운드: API 이체
        self._on_confirm_done = on_confirm_done  # 메인 스레드: UI 갱신

        self._spot_status               = spot_result.status
        self._spot_balance              = spot_result.value_usdt
        self._futures_status            = futures_result.status
        self._futures_balance           = futures_result.value_usdt
        self._futures_available_status  = futures_available_result.status
        self._futures_available_balance = futures_available_result.value_usdt

        self._direction_var = tk.StringVar(value=TransferDirection.TO_FUTURES.value)
        self._percent_var   = tk.DoubleVar(value=0.0)
        self._amount_var    = tk.StringVar(value="0")
        self._syncing = False
        self._amount_var.trace_add("write", self._on_amount_change)

        self._build()
        self.transient(master)
        self.grab_set()
        self.focus_set()
        self.update_idletasks()
        w, h = 480, 500
        self.geometry(f"{w}x{h}+{(self.winfo_screenwidth()-w)//2}+{(self.winfo_screenheight()-h)//2}")

    def _build(self) -> None:
        hdr = tk.Frame(self, bg=_HDR, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Initial Investment 설정", bg=_HDR, fg=_TEXT,
                 font=("Segoe UI", 11, "bold")).pack(padx=20, anchor="w")

        bal_f = tk.Frame(self, bg=_PANEL, pady=12)
        bal_f.pack(fill="x")
        self._add_balance_row(bal_f, "Spot/Fiat 사용 가능 잔액", self._spot_status, self._spot_balance)
        self._add_balance_row(bal_f, "USDⓈ-M Futures 현재 잔액", self._futures_status, self._futures_balance)
        self._add_balance_row(bal_f, "USDⓈ-M Futures 이체 가능 잔액", self._futures_available_status, self._futures_available_balance)
        tk.Frame(self, bg=_SEP, height=1).pack(fill="x")

        body = tk.Frame(self, bg=_BG, pady=16)
        body.pack(fill="both", expand=True, padx=20)
        tk.Label(body, text="이체 방향", bg=_BG, fg=_DIM, font=("Segoe UI", 9)).pack(anchor="w")
        dir_f = tk.Frame(body, bg=_BG)
        dir_f.pack(fill="x", pady=(4, 10))
        for text, val in [("Spot/Fiat → USDⓈ-M Futures  (이체)", TransferDirection.TO_FUTURES.value),
                           ("USDⓈ-M Futures → Spot/Fiat  (환수)", TransferDirection.TO_SPOT.value)]:
            tk.Radiobutton(dir_f, text=text, variable=self._direction_var, value=val,
                           command=self._on_direction_change,
                           bg=_BG, fg=_TEXT, selectcolor=_HDR,
                           activebackground=_BG, activeforeground=_TEXT,
                           font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 4))

        self._amount_label = tk.Label(body, text="", bg=_BG, fg=_DIM, font=("Segoe UI", 9))
        self._amount_label.pack(anchor="w", pady=(10, 0))

        slider_row = tk.Frame(body, bg=_BG)
        slider_row.pack(fill="x", pady=(6, 0))
        self._slider_canvas = tk.Canvas(slider_row, height=_SLIDER_HEIGHT, bg=_BG, highlightthickness=0)
        self._slider_canvas.pack(side="left", fill="x", expand=True)
        self._slider_canvas.bind("<Configure>", self._on_slider_configure)
        self._slider_canvas.bind("<Button-1>", self._on_slider_interact)
        self._slider_canvas.bind("<B1-Motion>", self._on_slider_interact)
        self._percent_label = tk.Label(slider_row, text="0.0 %", bg=_BG, fg=_DIM,
                                        font=("Consolas", 9), width=7, anchor="e")
        self._percent_label.pack(side="left", padx=(8, 0))

        amt_row = tk.Frame(body, bg=_BG)
        amt_row.pack(fill="x", pady=(8, 4))
        self._amount_entry = tk.Entry(amt_row, textvariable=self._amount_var,
                                       bg=_HDR, fg=_TEXT, insertbackground=_TEXT,
                                       font=("Consolas", 13, "bold"), relief="flat")
        self._amount_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))
        tk.Label(amt_row, text="USDT", bg=_BG, fg=_DIM, font=("Segoe UI", 10, "bold")).pack(side="left")

        tk.Label(body, text="0 입력 시 이체 없이, 현재 Futures 잔액을 거래 자금 기준점으로 설정합니다.",
                 bg=_BG, fg=_DIM, font=("Segoe UI", 8), wraplength=420, justify="left").pack(anchor="w", pady=(4, 0))

        self._error_lbl = tk.Label(body, text="", bg=_BG, fg=_NEGATIVE,
                                    font=("Segoe UI", 9, "bold"), wraplength=420, justify="left")
        self._error_lbl.pack(anchor="w", pady=(10, 0))
        tk.Frame(self, bg=_SEP, height=1).pack(fill="x")

        btn_f = tk.Frame(self, bg=_PANEL, pady=10)
        btn_f.pack(fill="x")
        self._confirm_btn = tk.Button(btn_f, text="확인",
                                       bg="#0A2A12", fg=_POSITIVE,
                                       activebackground="#0A3A18", activeforeground=_POSITIVE,
                                       font=("Segoe UI", 9, "bold"),
                                       relief="flat", bd=0, highlightthickness=0,
                                       padx=26, pady=6, cursor="hand2", command=self._confirm)
        self._confirm_btn.pack(side="right", padx=(4, 20))
        self._cancel_btn = tk.Button(btn_f, text="취소", bg=_HDR, fg=_DIM,
                                      activebackground="#333333", activeforeground=_TEXT,
                                      font=("Segoe UI", 9, "bold"), relief="flat", bd=0,
                                      highlightthickness=0, padx=26, pady=6,
                                      cursor="hand2", command=self.destroy)
        self._cancel_btn.pack(side="right", padx=4)
        self._update_amount_label()

    def _add_balance_row(self, parent: tk.Widget, label: str, status: WalletQueryStatus, balance: float) -> None:
        row = tk.Frame(parent, bg=_PANEL)
        row.pack(fill="x", pady=(0, 6))
        tk.Label(row, text=label, bg=_PANEL, fg=_DIM, font=("Segoe UI", 9)).pack(side="left", padx=(20, 0))
        if status == WalletQueryStatus.NO_API_KEY:
            t, c = "API 키 미설정  —  조회 불가", _ORANGE
        elif status == WalletQueryStatus.COMM_ERROR:
            t, c = "통신 오류  —  잠시 후 다시 시도해 주세요", _ORANGE
        elif balance > 0:
            t, c = f"{balance:,.2f} USDT", _TEXT
        else:
            t, c = "0.00 USDT", _DIM
        tk.Label(row, text=t, bg=_PANEL, fg=c, font=("Consolas", 10, "bold")).pack(side="right", padx=(0, 20))

    def _max_amount(self) -> float:
        if self._direction_var.get() == TransferDirection.TO_FUTURES.value:
            return self._spot_balance if self._spot_status == WalletQueryStatus.OK else 0.0
        return self._futures_available_balance if self._futures_available_status == WalletQueryStatus.OK else 0.0

    def _update_amount_label(self) -> None:
        if self._direction_var.get() == TransferDirection.TO_FUTURES.value:
            self._amount_label.configure(text="이체 금액  (기준: Spot/Fiat 사용 가능 잔액)"
                                         if self._spot_status == WalletQueryStatus.OK
                                         else "이체 금액  (Spot/Fiat 잔액 조회 불가)")
        else:
            self._amount_label.configure(text="환수 금액  (기준: USDⓈ-M Futures 이체 가능 잔액)"
                                         if self._futures_available_status == WalletQueryStatus.OK
                                         else "환수 금액  (Futures 이체 가능 잔액 조회 불가)")

    def _redraw_slider(self) -> None:
        canvas = self._slider_canvas
        canvas.delete("all")
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 2 * _SLIDER_PAD:
            return
        y = h // 2
        x0, x1 = _SLIDER_PAD, w - _SLIDER_PAD
        pct = self._percent_var.get()
        xk = x0 + (x1 - x0) * pct / 100.0
        canvas.create_line(x0, y, x1, y, fill=_SEP, width=4, capstyle="round")
        if xk > x0:
            canvas.create_line(x0, y, xk, y, fill=_POSITIVE, width=4, capstyle="round")
        r = _SLIDER_KNOB_RADIUS
        canvas.create_oval(xk-r, y-r, xk+r, y+r, fill="#FFFFFF", outline=_POSITIVE, width=2)

    def _on_slider_configure(self, _e: tk.Event) -> None:
        self._redraw_slider()

    def _on_slider_interact(self, event: tk.Event) -> None:
        w = self._slider_canvas.winfo_width()
        x0, x1 = _SLIDER_PAD, w - _SLIDER_PAD
        if x1 <= x0:
            return
        self._apply_percent(max(0.0, min(100.0, (event.x - x0) / (x1 - x0) * 100.0)))

    def _apply_percent(self, pct: float) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            amt = self._max_amount() * pct / 100.0
            self._percent_var.set(pct)
            self._amount_var.set(f"{amt:.2f}")
            self._percent_label.configure(text=f"{pct:.1f} %")
            self._redraw_slider()
        finally:
            self._syncing = False

    def _on_amount_change(self, *_: object) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            try:
                amt = float(self._amount_var.get())
            except ValueError:
                amt = 0.0
            mx = self._max_amount()
            pct = max(0.0, min(100.0, amt / mx * 100.0 if mx > 0 else 0.0))
            self._percent_var.set(pct)
            self._percent_label.configure(text=f"{pct:.1f} %")
            self._redraw_slider()
        finally:
            self._syncing = False

    def _on_direction_change(self) -> None:
        self._syncing = True
        try:
            self._amount_var.set("0")
            self._percent_var.set(0.0)
            self._percent_label.configure(text="0.0 %")
            self._redraw_slider()
        finally:
            self._syncing = False
        self._update_amount_label()
        self._error_lbl.configure(text="")

    def _confirm(self) -> None:
        try:
            amount = float(self._amount_var.get().strip())
        except ValueError:
            self._error_lbl.configure(text="올바른 숫자를 입력해 주세요.")
            return
        if amount < 0:
            self._error_lbl.configure(text="0 이상의 값을 입력해 주세요.")
            return
        direction = TransferDirection(self._direction_var.get())
        if amount > 0 and self._percent_var.get() >= 99.99:
            mx = self._max_amount()
            if mx > 0:
                amount = mx
        if amount > 0:
            if direction == TransferDirection.TO_FUTURES:
                if self._spot_status != WalletQueryStatus.OK:
                    self._error_lbl.configure(text="Spot/Fiat 잔액을 확인할 수 없어 이체할 수 없습니다.")
                    return
                if amount > self._spot_balance:
                    self._error_lbl.configure(text=f"Spot/Fiat 사용 가능 잔액({self._spot_balance:,.2f} USDT)을 초과할 수 없습니다.")
                    return
            else:
                if self._futures_available_status != WalletQueryStatus.OK:
                    self._error_lbl.configure(text="USDⓈ-M Futures 이체 가능 잔액을 확인할 수 없어 환수할 수 없습니다.")
                    return
                if amount > self._futures_available_balance:
                    self._error_lbl.configure(text=f"이체 가능 잔액({self._futures_available_balance:,.2f} USDT)을 초과할 수 없습니다.")
                    return
        elif self._futures_status != WalletQueryStatus.OK:
            self._error_lbl.configure(text="USDⓈ-M Futures 잔액을 확인할 수 없습니다.")
            return
        # ── 유효성 검사 통과 → 비동기 이체 처리 시작 ──────────
        # UI 즉각 응답: 버튼 비활성 + X버튼 차단
        self._confirm_btn.configure(state="disabled", text="처리 중...")
        self._cancel_btn.configure(state="disabled")
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self._error_lbl.configure(text="")

        def _run() -> None:
            try:
                result = self._on_confirm_bg(amount, direction)
            except Exception:
                result = WalletBalanceResult(WalletQueryStatus.COMM_ERROR, 0.0)
            try:
                # 루트 창 after() 사용 — dialog 소멸 여부와 무관하게 안전
                self._master.after(0, lambda: self._on_transfer_done(result))
            except Exception:
                pass  # 앱 종료 중 — 데몬 스레드가 자동 종료됨

        threading.Thread(target=_run, daemon=True).start()

    def _on_transfer_done(self, result: WalletBalanceResult) -> None:
        """이체 완료 후 메인 스레드에서 실행 — UI 갱신 또는 오류 표시."""
        # dialog가 이미 닫혔으면 조용히 종료 (앱 종료 중 등 방어)
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return

        if result.status == WalletQueryStatus.OK:
            # 성공: 헤더 UI 갱신 후 다이얼로그 닫기
            self._on_confirm_done()
            self.destroy()
        else:
            # 실패: 버튼·X버튼 복원 + 오류 메시지 표시
            self._confirm_btn.configure(state="normal", text="확인")
            self._cancel_btn.configure(state="normal")
            self.protocol("WM_DELETE_WINDOW", self.destroy)
            if result.status == WalletQueryStatus.COMM_ERROR:
                self._error_lbl.configure(
                    text="이체 처리 중 통신 오류가 발생했습니다. 다시 시도해 주세요.")
            elif result.status == WalletQueryStatus.NO_API_KEY:
                self._error_lbl.configure(
                    text="API 키가 설정되지 않아 이체할 수 없습니다.")
