"""
middle/widget/constants.py
중단 세션 공통 색상 상수 및 유틸 함수
모든 panel_col*.py 파일에서 import하여 사용
"""
from __future__ import annotations

from core.config import (
    DARK_BG, DARK_PANEL, DARK_HEADER, DARK_ROW_ODD, DARK_ROW_EVN,
    DARK_SEL, GOLD_ROW_BG, PLAYER_ROW_BG, PLAYER_SHORT_ROW_BG, PLAYER_MIX_ROW_BG,
    SEL_BORDER, DARK_TEXT, DIM_TEXT, ACCENT_BLUE,
    POSITIVE, NEGATIVE, ORANGE, YELLOW, LIGHT_GREEN,
    INITIAL_BUTTON,
)

# ── 중단/하단 전용 색상 ────────────────────────────────────────
NEW_BG = "#0B3D47"
NEW_FG = INITIAL_BUTTON   # #19F6C4 — 신규상장 텍스트 (INITIAL_BUTTON과 동일 값)

DIR_BG = {
    "▲ LONG":  "#0A2A12",
    "▼ SHORT": "#2A0A12",
    "↕ BOTH":  "#2A2200",
    "─ WAIT":  "#1C1C1C",
}

# DataManager _make_row 내부용 축약 색상 상수
_POS = POSITIVE
_NEG = NEGATIVE
_YEL = YELLOW
_ORA = ORANGE
_DIM = DIM_TEXT
_LGR = LIGHT_GREEN

# ── 랭킹 컬럼 정의 ────────────────────────────────────────────
# (헤더텍스트, 고정px, 헤더anchor)
_COLS = [
    ("#",           32,  "center"),
    ("Coin Symbol", 170, "w"),
    ("Change%",      80, "e"),
    ("Cumulative",   78, "e"),
    ("TF합의",         88, "center"),
    ("추세 단계",        0, "center"),
]

# ── 가격 포맷 유틸 ────────────────────────────────────────────
def fmt_price(v: float) -> str:
    if v < 0.0001:  return f"{v:.8f}"
    if v < 1:       return f"{v:.5f}"
    if v < 100:     return f"{v:.3f}"
    return f"{v:,.1f}"

def ind_bar(val: float, max_v: float, total: int = 18) -> str:
    filled = int(total * min(max(val / max_v, 0.0), 1.0))
    return "█" * filled + "░" * (total - filled)
