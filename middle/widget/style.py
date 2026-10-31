"""
middle/widget/style.py
중단 모듈 ttk 스타일 — clam 테마(Tk 인터프리터 전역) + 다크 스크롤바·Treeview.
MiddlePanel.__init__에서 1열 위젯 생성 전에 1회 호출.
"""
from __future__ import annotations
import tkinter.ttk as ttk

from middle.widget.constants import (
    ACCENT_BLUE, DARK_BG, DARK_HEADER, DARK_PANEL, DARK_ROW_ODD, DARK_SEL,
    DARK_TEXT, DIM_TEXT, POSITIVE,
)


# ── 중단 모듈 ttk 스타일 ─────────────────────────────────────────────────
def setup_style() -> None:
    s = ttk.Style()
    s.theme_use("clam")

    # ── Scrollbar ────────────────────────────────────────────
    s.configure("Vertical.TScrollbar", background=DARK_PANEL,
                troughcolor=DARK_BG, borderwidth=0, arrowcolor=DIM_TEXT)



    # ── Treeview 다크 테마 ─────────────────────────────────
    s.configure("Dark.Treeview",
                background=DARK_ROW_ODD,
                fieldbackground=DARK_BG,
                foreground=DARK_TEXT,
                rowheight=30,
                borderwidth=0,
                relief="flat",
                font=("Segoe UI", 9))
    # Treeview 외각 테두리 레이아웃 제거
    s.layout("Dark.Treeview", [
        ("Treeview.treearea", {"sticky": "nswe"})
    ])
    s.configure("Dark.Treeview.Heading",
                background=DARK_HEADER,
                foreground=ACCENT_BLUE,
                relief="flat",
                borderwidth=0,
                padding=[4, 6],
                font=("Segoe UI", 8, "bold"))
    s.map("Dark.Treeview",
          background=[("selected", DARK_SEL)],
          foreground=[("selected", POSITIVE)])
    s.map("Dark.Treeview.Heading",
          background=[("active",  DARK_HEADER),
                      ("pressed", DARK_HEADER)],
          relief=[("active",  "flat"),
                  ("pressed", "flat")])
