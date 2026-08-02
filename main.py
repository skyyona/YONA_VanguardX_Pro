"""
YONA VanguardX Pro — 메인 진입점
Header + Middle + Bottom 세 모듈을 단일 통합 GUI 창으로 실행

레이아웃:
  행 0 — 헤더 (76px 고정)
  행 1 — PanedWindow (중단/하단 드래그 분할, 초기 50:50)
"""
from __future__ import annotations

import os
import sys
import ctypes
import tkinter as tk

from core.event_bus import EventBus
from core.config import DARK_BG
from header.widget.header_panel import HeaderPanel
from header.widget.investment_dialog import InvestmentDialog
from header.models import HeaderStatus
from middle.widget.middle_panel import MiddlePanel
from bottom.widget.bottom_panel import BottomModuleMockup

# ── 단일 인스턴스 락 (L09-2) ──────────────────────────────────────
_LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".app.lock")


def _acquire_instance_lock() -> None:
    """앱 이중 실행을 방지하는 파일 기반 락 획득.
    이미 동일 PID가 살아 있으면 경고 후 종료, 비정상 종료 잔여 락은 자동 제거.
    """
    if os.path.exists(_LOCK_FILE):
        old_pid: int | None = None
        try:
            with open(_LOCK_FILE, encoding="utf-8") as _f:
                old_pid = int(_f.read().strip())
        except Exception:
            pass

        alive = False
        if old_pid:
            _handle = ctypes.windll.kernel32.OpenProcess(0x0400, False, old_pid)
            if _handle:
                ctypes.windll.kernel32.CloseHandle(_handle)
                alive = True
            else:
                # 비정상 종료 후 잔여 락 파일 — 삭제 후 계속
                try:
                    os.remove(_LOCK_FILE)
                except Exception:
                    pass

        if alive:
            import tkinter.messagebox as _mb
            _r = tk.Tk()
            _r.withdraw()
            _mb.showerror("중복 실행", "YONA VanguardX Pro가 이미 실행 중입니다.")
            _r.destroy()
            sys.exit(0)

    try:
        with open(_LOCK_FILE, "w", encoding="utf-8") as _f:
            _f.write(str(os.getpid()))
    except Exception:
        pass  # 락 파일 생성 실패 시 진행 허용


def _release_instance_lock() -> None:
    """앱 종료 시 락 파일 제거."""
    try:
        if os.path.exists(_LOCK_FILE):
            os.remove(_LOCK_FILE)
    except Exception:
        pass


HEADER_HEIGHT = 52   # 상/하 패딩 1px로 최소화 (기존 76px → 52px)


class YONAVanguardXPro(tk.Tk):
    """상단·중단·하단 모듈을 하나의 통합 창으로 구성하는 메인 앱."""

    def __init__(self) -> None:
        super().__init__()
        self.title("YONA VanguardX Pro")
        self.configure(bg=DARK_BG)

        # ── 창 최대화 (제목바 포함, 작업표시줄 제외) ──────────────
        self.state("zoomed")

        # ── 단일 창 레이아웃 (grid) ───────────────────────────────
        self.rowconfigure(0, weight=0)   # 헤더 — 고정 76px
        self.rowconfigure(1, weight=1)   # PanedWindow — 나머지 전체 확장
        self.columnconfigure(0, weight=1)

        # ── 모듈 간 공유 상태 (EventBus) ─────────────────────────
        self._bus = EventBus(self)

        # ── 상단 헤더 모듈 ────────────────────────────────────────
        self.header_frame = tk.Frame(self, height=HEADER_HEIGHT, bg=DARK_BG)
        self.header_frame.grid(row=0, column=0, sticky="nsew")
        self.header_frame.grid_propagate(False)
        self.header_panel = HeaderPanel(self.header_frame)
        self._bind_header_actions()
        self.header_panel.initialize()

        # ── PanedWindow (중단/하단 사이 드래그 분할 핸들) ─────────
        self._v_pane = tk.PanedWindow(
            self,
            orient="vertical",
            bg="#2A2A2A",        # 구분선 색상 (다크 테마)
            sashwidth=5,         # 드래그 핸들 두께
            sashrelief="flat",
            sashpad=0,
            opaqueresize=True,
        )
        self._v_pane.grid(row=1, column=0, sticky="nsew")

        # ── 중단 세션 모듈 (PanedWindow 상단 패널) ───────────────
        self.middle = MiddlePanel(
            self._v_pane,
            self._bus.assigned_sym,
            self._bus.shared_sort_mode,
        )
        self._v_pane.add(self.middle, stretch="always", minsize=400)

        # ── 하단 거래 엔진 모듈 (PanedWindow 하단 패널) ──────────
        self.bottom = BottomModuleMockup(
            self._v_pane,
            self._bus.assigned_sym,
            self._bus.shared_sort_mode,
        )
        self._v_pane.add(self.bottom, stretch="always", minsize=380)

        # ── 단일 창 종료 바인딩 ───────────────────────────────────
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── 초기 분할 위치 50:50 설정 (창 렌더링 후 실행) ────────
        self.after(250, self._set_initial_sash)

    # ── 헤더 액션 바인딩 ─────────────────────────────────────────
    def _bind_header_actions(self) -> None:
        def on_set_initial_investment() -> None:
            InvestmentDialog(
                self,
                spot_result=self.header_panel.get_spot_balance(),
                futures_result=self.header_panel.get_futures_balance(),
                futures_available_result=self.header_panel.get_available_balance(),
                on_confirm_bg=self.header_panel.do_transfer_bg,
                on_confirm_done=self.header_panel.on_transfer_done,
            )

        def on_start() -> None:
            self.header_panel.start()
            if hasattr(self.middle, "on_app_start"):
                self.middle.on_app_start()
            if hasattr(self.bottom, "on_app_start"):
                self.bottom.on_app_start()

        def _do_full_stop() -> None:
            """상단·중단·하단 전체 모듈 정지."""
            self.header_panel.stop()
            if hasattr(self.middle, "on_app_stop"):
                self.middle.on_app_stop()
            if hasattr(self.bottom, "on_app_stop"):
                self.bottom.on_app_stop()

        def on_stop() -> None:
            engine = getattr(getattr(self, "bottom", None), "_engine", None)
            has_pos = (engine is not None and engine.has_open_positions())
            if has_pos and hasattr(self.bottom, "force_stop_with_liquidation"):
                # 포지션 있음 → 먼저 강제 청산 시도
                def _on_fail(results: dict) -> None:
                    # 청산 실패 → STOP 취소, 실패 메시지만 표시
                    if hasattr(self.bottom, "_on_force_close_done"):
                        self.bottom._on_force_close_done(results)
                self.bottom.force_stop_with_liquidation(
                    on_success=_do_full_stop,
                    on_fail=_on_fail,
                )
            else:
                # 포지션 없음 → 즉시 전체 정지
                _do_full_stop()

        def on_forced_liquidation() -> None:
            # 포지션만 강제 청산 — 앱·엔진 계속 작동
            if hasattr(self.bottom, "force_close_all_positions"):
                self.bottom.force_close_all_positions()

        self.header_panel.bind_actions(
            on_set_initial_investment=on_set_initial_investment,
            on_start=on_start,
            on_stop=on_stop,
            on_forced_liquidation=on_forced_liquidation,
        )

    # ── PanedWindow 초기 분할 위치 ───────────────────────────────
    def _set_initial_sash(self) -> None:
        """PanedWindow 초기 분할 위치를 50:50으로 설정.
        창이 완전히 렌더링되기 전일 경우 재시도.
        """
        h = self._v_pane.winfo_height()
        if h > 100:
            self._v_pane.sash_place(0, 0, h // 2)
        else:
            self.after(100, self._set_initial_sash)

    # ── 종료 ─────────────────────────────────────────────────────
    def _on_close(self) -> None:
        """앱 종료 — 포지션 보유 여부 확인 후 레이아웃 저장 및 닫기."""
        # [A] 포지션 보유 중이면 경고 다이얼로그 (보완 3)
        engine = getattr(getattr(self, "bottom", None), "_engine", None)
        if engine is not None and engine.has_open_positions():
            from tkinter import messagebox
            ok = messagebox.askokcancel(
                "포지션 보유 중",
                "현재 열린 포지션이 있습니다.\n"
                "앱을 종료해도 Binance에 등록된 SL 주문은 유지됩니다.\n"
                "계속 종료하시겠습니까?"
            )
            if not ok:
                return  # 취소 시 종료 안 함
        if hasattr(self, "middle") and hasattr(self.middle, "_on_close"):
            self.middle._on_close()
        if hasattr(self, "header_panel"):
            state = self.header_panel.get_state()
            if state.status == HeaderStatus.RUNNING:
                self.header_panel.stop()
        # [B] 단일 인스턴스 락 해제 (L09-2)
        _release_instance_lock()
        self.destroy()


if __name__ == "__main__":
    _acquire_instance_lock()  # [B] 단일 인스턴스 락 획득
    app = YONAVanguardXPro()
    app.mainloop()
