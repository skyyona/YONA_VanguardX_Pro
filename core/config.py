"""
YONA VanguardX Pro — 전역 설정
색상 팔레트, 폰트, 상수, 갱신 주기
"""
# ── 앱 정보 ────────────────────────────────────────────────────
APP_TITLE = "YONA VanguardX Pro"

# ── 갱신 주기 ──────────────────────────────────────────────────
HEADER_UPDATE_INTERVAL_SEC = 1
MIDDLE_REFRESH_INTERVAL_MS = 3000

# ── 타임존 ─────────────────────────────────────────────────────
KST_TIMEZONE = "Asia/Seoul"

# ── 다크 테마 색상 팔레트 ──────────────────────────────────────
DARK_BG       = "#121212"
DARK_PANEL    = "#1E1E1E"
DARK_HEADER   = "#252525"
DARK_ROW_ODD  = "#191919"
DARK_ROW_EVN  = "#141414"
DARK_SEL      = "#0A2218"
GOLD_ROW_BG          = "#4A3600"
PLAYER_ROW_BG        = "#1A4A28"   # Player Detection 롱 편향 행 배경 (에메랄드)
PLAYER_SHORT_ROW_BG  = "#3A1A1A"   # Player Detection 숏 편향 행 배경 (다크 레드)
PLAYER_MIX_ROW_BG    = "#2A2A12"   # Player Detection 혼재 행 배경 (다크 옐로우)
SEL_BORDER    = "#11de93"
DARK_TEXT     = "#E0E0E0"
DIM_TEXT      = "#555555"
ACCENT_BLUE   = "#4EA1FF"
POSITIVE      = "#11de93"
NEGATIVE      = "#ff007a"
ORANGE        = "#FF8C25"
YELLOW        = "#FFD700"
LIGHT_GREEN   = "#8ad7b5"   # 골든크로스·에너지 바 라이트 그린
NEUTRAL       = DARK_TEXT

# ── 포지션 패널 색상 ────────────────────────────────────────────
LONG_HDR_BG   = "#0A1F12"   # 롱 엔진 헤더 틴트
SHORT_HDR_BG  = "#1F0A0F"   # 숏 엔진 헤더 틴트

# ── 헤더 전용 색상 ─────────────────────────────────────────────
APP_RUNNING      = POSITIVE
APP_IDLE         = DARK_TEXT
APP_ERROR        = NEGATIVE
INITIAL_BUTTON   = "#19F6C4"
FORCED_BUTTON    = "#b500f9"
START_BUTTON     = "#11de93"
STOP_BUTTON      = "#ff007a"

# ── 공통 TF 키 ─────────────────────────────────────────────────
TF_KEYS = ["1m", "3m", "5m", "15m"]

# ── Sort by 옵션 ────────────────────────────────────────────────
SORT_OPTIONS = [
    "24h Ticker",
    "Sharp rise",
    "Sharp decline",
    "Volatility",
    "4TF Optimization",
    "Newly Listed",
]
