"""
YONA VanguardX Pro — Middle Module (실데이터 연동)
1열 1탭 Real-Time Ranking | 실데이터: DataManager 경유
"""
from __future__ import annotations

import os
import json
import webbrowser
import datetime
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

# ── 실데이터 DataManager (선택적 임포트) ───────────────────────
try:
    from middle.data.data_manager import MiddleDataManager as _MiddleDataManager
    _HAS_DATA_MANAGER = True
except ImportError:
    _HAS_DATA_MANAGER = False

# ── Blacklist / Settling / Pending (선택적 임포트) ─────────────
try:
    from middle.col1_ranking_blacklist.blacklist.blacklist import BlacklistManager as _BlacklistManager
    from middle.col1_ranking_blacklist.blacklist.settling import SettlingDetector as _SettlingDetector
    from middle.col1_ranking_blacklist.ranking.pending_listing import (
        PendingEntry as _PendingEntry,
        PendingListingDetector as _PendingListingDetector,
    )
    _HAS_BLACKLIST = True
except ImportError:
    _HAS_BLACKLIST = False

# 모듈 레벨 singleton — MiddlePanel.__init__ 에서 초기화
_data_mgr: "MiddleDataManager | None" = None  # type: ignore[name-defined]
_bl_mgr:   "_BlacklistManager | None"  = None  # type: ignore[name-defined]

try:
    import matplotlib
    matplotlib.use("TkAgg")
    # ── 한글 폰트 설정 (DejaVu Sans 한글 누락 경고 해소) ───────
    import matplotlib.font_manager as _fm
    _KR_FONTS = ["Malgun Gothic", "NanumGothic", "AppleGothic", "Noto Sans CJK KR"]
    _available = {f.name for f in _fm.fontManager.ttflist}
    for _kf in _KR_FONTS:
        if _kf in _available:
            matplotlib.rcParams["font.family"] = _kf
            break
    matplotlib.rcParams["axes.unicode_minus"] = False   # 마이너스 기호 깨짐 방지
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.patches as mptch
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# ── 레이아웃(비율/창 크기) 설정 저장 — sash 드래그/창 크기 조정이 재실행 후에도 유지되도록 영속화
from middle.widget.constants import (
    DARK_BG, DARK_PANEL, DARK_HEADER, DARK_ROW_ODD, DARK_ROW_EVN,
    DARK_SEL, GOLD_ROW_BG, PLAYER_ROW_BG, PLAYER_SHORT_ROW_BG, PLAYER_MIX_ROW_BG,
    SEL_BORDER, DARK_TEXT, DIM_TEXT, ACCENT_BLUE,
    POSITIVE, NEGATIVE, YELLOW, ORANGE, NEW_BG, NEW_FG,
    DIR_BG, _POS, _NEG, _YEL, _ORA, _DIM, _LGR,
    _COLS, fmt_price, ind_bar,
)

from middle.widget.panel_col1 import _Col1Mixin
from middle.widget.panel_col2 import _Col2Mixin
from middle.widget.panel_col3 import _Col3Mixin

LAYOUT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_middle_layout.json")
DEFAULT_MAIN_RATIO = 0.36    # 1열 : 2열  (36%)
DEFAULT_COL1_RATIO = 0.47    # Chart : Middle (2열 30% : 3열 34%)
DEFAULT_GEOMETRY   = "1560x460"


def load_layout_config() -> dict:
    try:
        with open(LAYOUT_CONFIG_PATH, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return {}


def save_layout_config(cfg: dict) -> None:
    try:
        with open(LAYOUT_CONFIG_PATH, "w", encoding="utf-8") as fp:
            json.dump(cfg, fp)
    except Exception:
        pass

# 색상·유틸은 constants.py에서 import됨 (위 import 블록 참조)

# ── 헬퍼 함수: shared_context 단일 정의에서 import (중복 없음) ──
import middle.widget.shared_context as _ctx
from middle.widget.shared_context import (
    get_ind, generate_ohlcv, _live_ranking,
)


# ══════════════════════════════════════════════════════════════
class MiddlePanel(_Col1Mixin, _Col2Mixin, _Col3Mixin, tk.Frame):
    def __init__(self, master: tk.Misc,
                 shared_sym: tk.StringVar | None = None,
                 shared_sort_mode: tk.StringVar | None = None) -> None:
        super().__init__(master, bg=DARK_BG)
        self._layout_cfg = load_layout_config()
        # Toplevel 전용 메서드(title/geometry/minsize/protocol) 제거 — 단일 창 통합 GUI
        self._shared_sym = shared_sym   # bottom module 과 공유하는 심볼 변수
        self._shared_sort_mode = shared_sort_mode   # bottom module 과 공유하는 Sort by 모드

        # ── Blacklist Manager 초기화 ─────────────────────────
        global _bl_mgr
        if _HAS_BLACKLIST and _bl_mgr is None:
            try:
                _bl_mgr = _BlacklistManager()
            except Exception:
                _bl_mgr = None

        # ── 실데이터 DataManager 초기화 ──────────────────────
        global _data_mgr
        if _HAS_DATA_MANAGER and _data_mgr is None:
            try:
                _data_mgr = _MiddleDataManager()
                pass   # start_auto_refresh는 on_app_start()에서 호출
            except Exception:
                _data_mgr = None
        # 콜백 등록 (DataManager → 화면 자동 재갱신) — START 전에도 등록
        if _data_mgr is not None:
            _data_mgr._on_detail_ready_cb  = self._on_data_ready
            _data_mgr._on_ranking_ready_cb = self._soft_update_ranking
            _data_mgr._on_klines_ready_cb  = self._on_klines_ready

        # ── 앱 상태 머신 ─────────────────────────────────────
        # 'IDLE': 초기/STOP 후 | 'RANKING': START 후 | 'ANALYSIS': 심볼 선택 후
        self._app_state     : str = "IDLE"
        self._analysis_mode : bool = False   # True이면 1열 갱신 차단
        self._chart_timer_id    : str | None = None   # 2열 5초 타이머 after ID
        self._analysis_timer_id : str | None = None   # 3열 60초 타이머 after ID
        self._clear_btn     : tk.Button | None = None  # [Clear Coin Analysis] 버튼 참조

        # ── 상태 변수 ────────────────────────────────────────
        self._sel_var       = tk.StringVar(value="BTCUSDT")
        self._tf_var        = tk.StringVar(value="5분봉")
        self._time_fixed      = False
        self._time_fix_prices  : dict[str, float] = {}   # sym → Fix 시점 가격
        self._assigned_sym  : str | None = None

        # ── 위젯 참조 ────────────────────────────────────────
        self._cur_tab       : int = -1
        self._sel_idx       : int = -1              # 현재 선택 행 인덱스 (2행만 스타일 변경용)
        self._row_frames    : list[tuple[tk.Frame, str]] = []
        self._special       : dict[int, set]              = {}
        self._cum_labels    : dict[str, tuple[tk.Label, str, str]] = {}  # sym → (lbl, fixed_text, fixed_color)
        self._change_labels : dict[str, tk.Label]  = {}   # sym → Change% Label (5초 소프트 갱신용)
        self._phase_labels  : dict[str, tuple]     = {}   # sym → (ph_f Frame, ph_lbl Label)
        self._top_bar_f  : tk.Frame | None = None
        self._bl_built   : bool = False          # Blacklist 탭 Lazy Build 플래그
        # Blacklist 탭 체크박스 상태 (☐/☑ 토글)
        self._checked_settling  : set[str] = set()   # Settling에서 ☑ 된 심볼
        self._checked_blacklist : set[str] = set()   # Blacklist에서 ☑ 된 심볼
        # Settling 감지 결과 캐시 (API 재조회 없이 즉시 갱신용)
        self._settling_cache    : list     = []       # SettlingEntry 목록
        # PENDING_TRADING 캐시 (상장 예정 심볼 + markPrice)
        self._pending_cache     : list     = []       # dict 목록
        self._pending_loaded    : bool     = False    # 로드 완료 플래그 (로딩 중/결과 없음 구분)
        self._mpl_canvas = None

        # Gold Ranking — 종합 1위 심볼 (_rebuild_ranking_rows 갱신)
        self._gold_sym        : str  = ""
        # Player Detection — 태그 감지 심볼 맵 (_rebuild_ranking_rows 갱신)
        self._player_tags_map : dict = {}

        # 정렬 드롭다운
        self._sort_mode  : str            = "24h Ticker"
        self._sort_btn   : tk.Button | None = None
        if self._shared_sort_mode is not None:
            self._shared_sort_mode.set(self._sort_mode)

        # 경과 시간 타이머
        self._elapsed_sec : int           = 0
        self._timer_running: bool         = False
        self._timer_lbl  : tk.Label | None = None
        self._timefix_btn: tk.Button | None = None

        # 랭킹 스크롤 애니메이션 (Ease-Out)
        self._scroll_target    : float = 0.0   # 목표 위치 (0.0~1.0)
        self._scroll_current   : float = 0.0   # 현재 애니메이션 위치
        self._scroll_animating : bool  = False  # 애니메이션 진행 중 여부

        # 비율 — 스크린샷 기준 기본값 확정 (창 비례 유지), 저장된 설정이 있으면 그 값을 우선 적용
        self._main_ratio       : float = self._layout_cfg.get("main_ratio", DEFAULT_MAIN_RATIO)
        self._col1_ratio       : float = self._layout_cfg.get("col1_ratio", DEFAULT_COL1_RATIO)

        # 3열 통합 탭 상태 (종합분석 | 기술분석 | Player Detection | 파생분석)
        self._cur_mid_tab    : str              = "verdict"
        self._verdict_tab_btn: tk.Button | None = None
        self._tech_tab_btn   : tk.Button | None = None
        self._pd_tab_btn     : tk.Button | None = None
        self._deriv_tab_btn  : tk.Button | None = None

        # 2열 프레임 참조
        self._deriv_f   : tk.Frame | None = None
        self._verdict_f : tk.Frame | None = None
        self._verdict_title_lbl: tk.Label | None = None

        self._setup_style()

        self._pane = tk.PanedWindow(self, orient="horizontal",
                                    bg=DARK_BG, sashwidth=5,
                                    sashrelief="flat", sashpad=0)
        self._pane.pack(fill="both", expand=True, padx=6, pady=6)
        self._pane.bind("<ButtonRelease-1>", self._on_main_sash_release)

        self._build_left(self._pane)
        self._build_right(self._pane)

        # 초기 선택 — 정렬 결과에서 동적으로 인덱스 탐색
        self.after(80,  self._initial_select)
        self.after(150, self._apply_ratio)

        # bottom module [Clear] 클릭 감지 — shared_sym 이 "" 로 바뀌면 Assign 초기화
        if self._shared_sym is not None:
            self._shared_sym.trace_add("write", self._on_shared_sym_changed)

        # 창 크기 변경 시 자동 비율 유지
        self.bind("<Configure>", self._on_window_resize)

        # shared_context 단일 업데이트 — 모든 panel 파일이 _ctx 경유 접근
        _ctx._data_mgr = _data_mgr
        _ctx._bl_mgr   = _bl_mgr

    # ══════════════════════════════════════════════════════════
    # NOTE: 1열 메서드들은 panel_col1.py (_Col1Mixin) 참조
    # NOTE: 2열 메서드들은 panel_col2.py (_Col2Mixin) 참조
    # NOTE: 3열 메서드들은 panel_col3.py (_Col3Mixin) 참조
    # ══════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════
    # 2열 — 심볼 헤더 → 섹션 레이블 → Coin Momentum | Coin Chart
    # ══════════════════════════════════════════════════════════
    def _build_right(self, pane: tk.PanedWindow) -> None:
        self._right = tk.Frame(pane, bg=DARK_BG)
        pane.add(self._right, minsize=700)  # body_pane 자식 합 260+6+420=686px 이상

        # ── ① 심볼 헤더 (최상단, 전체 너비) ─────────────────
        # ── 헤더 컨테이너 (고정 최상단 바) ──────────────────────
        # _hdr_wrapper: 헤더 전체 고정 컨테이너 (destroy 대상 아님)
        _hdr_wrapper = tk.Frame(self._right, bg=DARK_PANEL)
        _hdr_wrapper.pack(fill="x")

        # _hdr_f: 심볼 정보 표시 영역 (_refresh_header가 내용만 rebuild)
        self._hdr_f = tk.Frame(_hdr_wrapper, bg=DARK_PANEL, pady=8)
        self._hdr_f.pack(side="left", fill="both", expand=True)

        # _action_bar: 우측 고정 버튼 영역 (_refresh_header로 삭제 안 됨)
        self._action_bar = tk.Frame(_hdr_wrapper, bg=DARK_PANEL, pady=4)
        self._action_bar.pack(side="right", padx=8)

        # [Clear Coin Analysis] 버튼 — _action_bar에 고정 (ANALYSIS 상태에서만 표시)
        self._clear_btn = tk.Button(
            self._action_bar, text="✕  Clear Coin Analysis",
            bg="#2A1A1A", fg="#FF6666",
            activebackground="#3A2A2A", activeforeground=NEGATIVE,
            font=("Segoe UI", 8, "bold"), relief="flat", padx=10, pady=3,
            cursor="hand2", command=self.on_clear_analysis,
        )
        # Assign Symbol 버튼 자리 확보용 빈 프레임 (항상 표시)
        self._assign_placeholder = tk.Frame(self._action_bar, bg=DARK_PANEL, width=10)
        self._assign_placeholder.pack(side="right")

        # ── ② 바디: 3열 Outer PanedWindow ───────────────────
        self._body_pane = tk.PanedWindow(
            self._right, orient="horizontal",
            bg=DARK_BG, sashwidth=6,
            sashrelief="flat", sashpad=0,
            bd=0, relief="flat",
        )
        self._body_pane.pack(fill="both", expand=True)
        self._body_pane.bind("<ButtonRelease-1>", self._on_body_sash_release)

        # ── 초기 헤더 메시지 (앱 시작 시 고정 표시) ─────────────
        self._set_header_message("▶  상단 모듈의  [ START ]  버튼을 눌러 시작하세요")

        # ── Outer Col 1: Coin Chart (차트만, 전체 높이) ──────
        col1_f = tk.Frame(self._body_pane, bg="#0D0D0D")
        self._body_pane.add(col1_f, minsize=260)

        # ── Coin Chart 탭 버튼 바 (1열·4열 탭과 동일한 스타일) ──
        cc_bar = tk.Frame(col1_f, bg=DARK_BG)
        cc_bar.pack(fill="x")
        self._chart_tab_btn = tk.Button(
            cc_bar, text="📈 Coin Chart",
            bg=DARK_PANEL, fg=ACCENT_BLUE,
            activebackground=DARK_PANEL, activeforeground=ACCENT_BLUE,
            font=("Segoe UI", 9, "bold"), relief="flat", bd=0, padx=8, pady=8,
            cursor="hand2", command=lambda: self._switch_chart_tab("chart"))
        self._chart_tab_btn.pack(side="left")
        self._mtf_tab_btn = tk.Button(
            cc_bar, text="📊 MTF Stoch RSI",
            bg=DARK_BG, fg=DIM_TEXT,
            activebackground=DARK_PANEL, activeforeground=ACCENT_BLUE,
            font=("Segoe UI", 9, "bold"), relief="flat", bd=0, padx=8, pady=8,
            cursor="hand2", command=lambda: self._switch_chart_tab("mtf"))
        self._mtf_tab_btn.pack(side="left")
        self._macro_tab_btn = tk.Button(
            cc_bar, text="🎯 Macro & 4TF Entry",
            bg=DARK_BG, fg=DIM_TEXT,
            activebackground=DARK_PANEL, activeforeground=ACCENT_BLUE,
            font=("Segoe UI", 9, "bold"), relief="flat", bd=0, padx=8, pady=8,
            cursor="hand2", command=lambda: self._switch_chart_tab("macro"))
        self._macro_tab_btn.pack(side="left")
        tk.Frame(col1_f, bg="#2A2A2A", height=1).pack(fill="x")

        # ── 분봉 버튼 바 (Coin Chart 탭 전용) ─────────────────
        self._tf_bar = tk.Frame(col1_f, bg="#161616", pady=4)
        self._tf_bar.pack(fill="x")
        for tf in ["1분봉", "3분봉", "5분봉", "15분봉", "1시간봉", "4시간봉", "1일봉"]:
            tk.Radiobutton(self._tf_bar, text=f" {tf} ", variable=self._tf_var, value=tf,
                           bg="#161616", fg=DIM_TEXT,
                           activebackground="#161616", activeforeground=ACCENT_BLUE,
                           selectcolor="#252525", indicatoron=False,
                           font=("Segoe UI", 7, "bold"), padx=4, pady=4,
                           relief="flat",
                           command=self._refresh_chart).pack(side="left", expand=True, fill="x", padx=1)

        # ── 차트 영역 + MTF 뷰 (탭 전환으로 show/hide) ────────
        self._chart_f = tk.Frame(col1_f, bg="#0D0D0D")
        self._chart_f.pack(fill="both", expand=True)

        self._mtf_f   = tk.Frame(col1_f, bg=DARK_BG)
        self._macro_f = tk.Frame(col1_f, bg=DARK_BG)
        # 초기 상태: chart 탭 활성, mtf·macro 숨김
        self._cur_chart_tab: str = "chart"

        # ── Outer Col 2: 중간 컨테이너 (3열 통합 탭) ──────────
        col_mid_f = tk.Frame(self._body_pane, bg=DARK_BG)
        self._body_pane.add(col_mid_f, minsize=318)

        # ── 통합 탭 버튼 바 (종합분석 | 기술분석 | Player Detection | 파생분석) ──
        mid_tab_bar = tk.Frame(col_mid_f, bg=DARK_BG)
        mid_tab_bar.pack(fill="x", side="top")

        self._verdict_tab_btn = tk.Button(
            mid_tab_bar, text="📋 종합분석 및 권장 레버리지",
            bg=DARK_PANEL, fg=ACCENT_BLUE,
            activebackground=DARK_PANEL, activeforeground=ACCENT_BLUE,
            font=("Segoe UI", 9, "bold"),
            relief="flat", bd=0, padx=8, pady=8,
            cursor="hand2",
            command=lambda: self._switch_mid_tab("verdict"),
        )
        self._verdict_tab_btn.pack(side="left")

        self._tech_tab_btn = tk.Button(
            mid_tab_bar, text="📈 기술분석",
            bg=DARK_BG, fg=DIM_TEXT,
            activebackground=DARK_PANEL, activeforeground=ACCENT_BLUE,
            font=("Segoe UI", 9, "bold"),
            relief="flat", bd=0, padx=8, pady=8,
            cursor="hand2",
            command=lambda: self._switch_mid_tab("tech"),
        )
        self._tech_tab_btn.pack(side="left")

        self._pd_tab_btn = tk.Button(
            mid_tab_bar, text="🎭 Player Detection",
            bg=DARK_BG, fg=DIM_TEXT,
            activebackground=DARK_PANEL, activeforeground=ACCENT_BLUE,
            font=("Segoe UI", 9, "bold"),
            relief="flat", bd=0, padx=8, pady=8,
            cursor="hand2",
            command=lambda: self._switch_mid_tab("player"),
        )
        self._pd_tab_btn.pack(side="left")

        self._deriv_tab_btn = tk.Button(
            mid_tab_bar, text="🔗 파생분석",
            bg=DARK_BG, fg=DIM_TEXT,
            activebackground=DARK_PANEL, activeforeground=ACCENT_BLUE,
            font=("Segoe UI", 9, "bold"),
            relief="flat", bd=0, padx=8, pady=8,
            cursor="hand2",
            command=lambda: self._switch_mid_tab("deriv"),
        )
        self._deriv_tab_btn.pack(side="left")

        tk.Frame(col_mid_f, bg="#2A2A2A", height=1).pack(fill="x", side="top")

        # ── 탭 콘텐츠 영역 ──
        mid_tab_content = tk.Frame(col_mid_f, bg=DARK_PANEL)
        mid_tab_content.pack(fill="both", expand=True, side="top")

        # 탭1: 종합 분석 및 권장 레버리지
        self._verdict_tab_f = tk.Frame(mid_tab_content, bg=DARK_PANEL)
        self._verdict_title_lbl = tk.Label(
            self._verdict_tab_f, text=f"📋 {self._sort_mode} 분석 및 권장 레버리지",
            bg=DARK_PANEL, fg=ACCENT_BLUE,
            font=("Segoe UI", 9, "bold"), anchor="w")
        self._verdict_title_lbl.pack(fill="x", padx=10, pady=(8, 2))
        tk.Frame(self._verdict_tab_f, bg="#333333", height=1).pack(fill="x")
        self._verdict_f = tk.Frame(self._verdict_tab_f, bg=DARK_PANEL)
        self._verdict_f.pack(fill="both", expand=True)

        # 탭2: 기술 분석
        self._tech_f = tk.Frame(mid_tab_content, bg=DARK_PANEL)
        self._ind_f = tk.Frame(self._tech_f, bg=DARK_PANEL, pady=4)
        self._ind_f.pack(fill="x")
        tk.Frame(self._tech_f, bg="#2A2A2A", height=1).pack(fill="x", pady=(4, 0))
        self._ema_f = tk.Frame(self._tech_f, bg=DARK_PANEL, pady=4)
        self._ema_f.pack(fill="x")

        # 탭3: Player Detection
        self._energy_f = tk.Frame(mid_tab_content, bg=DARK_PANEL)

        # 탭4: 파생 분석
        self._deriv_f = tk.Frame(mid_tab_content, bg=DARK_PANEL, pady=4)

        # 초기 탭: 종합 분석 표시
        self._verdict_tab_f.pack(fill="both", expand=True)

    # ── sash 비율 보존 ────────────────────────────────────────
    def _on_main_sash_release(self, event: tk.Event) -> None:
        """1열/2열 sash 드래그 후 비율 저장 — _apply_ratio와 동일한 분모 사용"""
        total = self.winfo_width()
        if total < 200:
            return
        try:
            usable = total - 17
            sash_x = self._pane.sash_coord(0)[0]
            self._main_ratio = sash_x / usable
            self._save_layout()
        except Exception:
            pass

    # ── 비율 / 창 크기 설정 저장 ─────────────────────────────────
    def _save_layout(self) -> None:
        save_layout_config({
            "main_ratio": self._main_ratio,
            "col1_ratio": self._col1_ratio,
            "geometry": f"{self.winfo_width()}x{self.winfo_height()}",
        })

    def _on_close(self) -> None:
        self._save_layout()
        # Frame 모드: destroy는 호출하지 않음 — 단일 창 통합 GUI에서 main.py가 종료 관리

    # ── 3열 통합 탭 전환 (종합분석 | 기술분석 | Player Detection | 파생분석) ──
    def _switch_mid_tab(self, tab: str) -> None:
        self._cur_mid_tab = tab
        # 모든 콘텐츠 숨김
        self._verdict_tab_f.pack_forget()
        self._tech_f.pack_forget()
        self._energy_f.pack_forget()
        self._deriv_f.pack_forget()
        # 모든 버튼 비활성
        self._verdict_tab_btn.configure(bg=DARK_BG, fg=DIM_TEXT)
        self._tech_tab_btn.configure(bg=DARK_BG, fg=DIM_TEXT)
        self._pd_tab_btn.configure(bg=DARK_BG, fg=DIM_TEXT)
        self._deriv_tab_btn.configure(bg=DARK_BG, fg=DIM_TEXT)

        if tab == "verdict":
            self._verdict_tab_f.pack(fill="both", expand=True)
            self._verdict_tab_btn.configure(bg=DARK_PANEL, fg=ACCENT_BLUE)
        elif tab == "tech":
            self._tech_f.pack(fill="both", expand=True)
            self._tech_tab_btn.configure(bg=DARK_PANEL, fg=ACCENT_BLUE)
        elif tab == "player":
            self._energy_f.pack(fill="both", expand=True)
            self._pd_tab_btn.configure(bg=DARK_PANEL, fg=ACCENT_BLUE)
        else:
            self._deriv_f.pack(fill="both", expand=True)
            self._deriv_tab_btn.configure(bg=DARK_PANEL, fg=ACCENT_BLUE)

    def _on_body_sash_release(self, event: tk.Event) -> None:
        """body_pane sash 드래그 후 비율 저장 — _apply_ratio와 동일한 분모 사용"""
        try:
            total = self.winfo_width()
            if total < 400:
                return
            usable = total - 17
            main_w = int(usable * self._main_ratio)
            body_w = usable - main_w
            if body_w < 100:
                return
            x = self._body_pane.sash_coord(0)[0]
            self._col1_ratio = x / body_w
            self._save_layout()
        except Exception:
            pass

    # ── 창 크기 변경 시 저장된 비율 재적용 ───────────────────
    def _apply_ratio(self) -> None:
        """창 너비에서 직접 계산 → 비율 기준 sash 배치 (resize 타이밍 무관)"""
        total = self.winfo_width()
        if total < 400:
            return

        # ─ Main pane: 1열 | 2열 ──────────────────────────────
        usable   = total - 17              # padx=6×2 + main sash=5
        main_w   = int(usable * self._main_ratio)
        self._pane.sash_place(0, main_w, 0)

        if not hasattr(self, "_body_pane"):
            return

        # ─ Body pane: Chart | Middle ─────────────────────────
        body_w   = usable - main_w        # usable = pane_width - main_sash(5), right = usable - main_w
        if body_w < 100:
            return
        chart_w  = int(body_w * self._col1_ratio)
        self._body_pane.sash_place(0, chart_w, 0)

    def _on_window_resize(self, event: tk.Event) -> None:
        if event.widget is self:
            self.after(30, self._apply_ratio)

    # ── 초기 심볼 선택 (정렬 후 실제 인덱스 동적 탐색) ─────────
    def _initial_select(self) -> None:
        target = "BTCUSDT"
        for idx, (_, sym) in enumerate(self._row_frames):
            if sym == target:
                self._on_select(target, idx)
                return
        if self._row_frames:
            first_sym = self._row_frames[0][1]
            self._on_select(first_sym, 0)

    # ── 행 선택 (2열 분석 패널 갱신) ──────────────────────────
    def _on_select(self, symbol: str, sel_idx: int) -> None:
        # RANKING 상태가 아니면 즉시 차단
        # IDLE: START 전 클릭 무효 / ANALYSIS: [Clear] 클릭 전까지 완전 무효
        if self._app_state != "RANKING":
            return
        self._sel_var.set(symbol)

        # ── Fix④: 이전 선택+신규 선택 2개 행만 스타일 변경 (100행 전체 제거) ──
        prev_idx = self._sel_idx
        self._sel_idx = sel_idx
        for update_idx in {prev_idx, sel_idx}:
            if update_idx < 0 or update_idx >= len(self._row_frames):
                continue
            frame, _sym = self._row_frames[update_idx]
            if update_idx == sel_idx:
                frame.configure(bg=DARK_SEL,
                                highlightthickness=1,
                                highlightbackground=SEL_BORDER)
                self._recolor(frame, DARK_SEL, self._special.get(update_idx, set()))
            else:
                _p_e   = self._player_tags_map.get(_sym)
                row_bg = (GOLD_ROW_BG        if _sym == self._gold_sym                           else
                          PLAYER_SHORT_ROW_BG if _p_e and _p_e.get("direction") == "short"       else
                          PLAYER_MIX_ROW_BG   if _p_e and _p_e.get("direction") == "mixed"       else
                          PLAYER_ROW_BG       if _p_e                                             else
                          DARK_ROW_ODD        if update_idx % 2 == 0                              else
                          DARK_ROW_EVN)
                frame.configure(bg=row_bg, highlightthickness=0)
                self._recolor(frame, row_bg, self._special.get(update_idx, set()))

        # ── Pending Listing: 하이라이트만, 데이터 갱신·ANALYSIS 전환 없음 ──
        if self._sort_mode == "Pending Listing":
            return

        # ── 실데이터 갱신 요청 (비동기 — 완료 시 _on_data_ready → _do_refresh_detail) ──
        if _data_mgr is not None:
            _data_mgr.request_selected(symbol)

        # ── 상태 전환: RANKING → ANALYSIS ───────────────────────
        if self._app_state == "RANKING":
            self._app_state = "ANALYSIS"
            self._analysis_mode = True   # 1열 갱신 차단
            # [Clear Coin Analysis] 버튼 표시
            if self._clear_btn:
                self._clear_btn.pack(side="left", padx=(0, 4))
            # 콜백 기반 갱신 — 타이머 없음
            # 갱신 흐름: STAGE1 완료 → _on_data_ready() → 2열+3열 자동 갱신
            #            STAGE3 완료 → _on_klines_ready() → 2열 차트 재사용 갱신

        # ── 즉각 처리: 헤더 + 분봉 버튼 + 2열 로딩 표시 ──────────
        self.after(5, self._do_refresh_immediate)

    def _recolor(self, widget: tk.Widget, bg: str, skip: set) -> None:
        for child in widget.winfo_children():
            if child in skip:
                continue
            try:
                child.configure(bg=bg)
            except tk.TclError:
                pass
            self._recolor(child, bg, skip)

    # ── 헤더 메시지 헬퍼 ────────────────────────────────────────────
    def _set_header_message(self, msg: str) -> None:
        """_hdr_f를 비우고 안내 메시지 표시 (심볼 선택 전 고정 메시지용)."""
        for w in self._hdr_f.winfo_children():
            w.destroy()
        tk.Label(self._hdr_f, text=msg,
                 bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 10)).pack(padx=16, anchor="w")

    # ── 앱 상태 관리 메서드 ────────────────────────────────────────

    def on_app_start(self) -> None:
        """[START] 클릭 → IDLE → RANKING 전환."""
        if self._app_state != "IDLE":
            return
        self._app_state = "RANKING"
        self._analysis_mode = False
        # 헤더 메시지 업데이트
        self._set_header_message("← 1열에서 코인 심볼을 클릭하세요")
        # DataManager 시작
        global _data_mgr
        if _data_mgr is not None and not _data_mgr._running:
            _data_mgr.start_auto_refresh()
        # 1열 초기 빌드 (빈 목록 → ticker 로드 후 자동 갱신)
        self._rebuild_ranking_rows()

    def on_app_stop(self) -> None:
        """[STOP] 클릭 → any → IDLE 전환 + 모든 갱신 중지."""
        self._app_state = "IDLE"
        self._analysis_mode = False
        # 타이머 중지
        self._stop_chart_timer()
        self._stop_analysis_timer()
        # [Clear] 버튼 숨김
        if self._clear_btn:
            self._clear_btn.pack_forget()
        # DataManager 중지
        global _data_mgr
        if _data_mgr is not None:
            _data_mgr.stop_auto_refresh()
        # 1열 빈 화면
        self._rebuild_ranking_rows()
        # 헤더 초기 메시지 복원
        self._set_header_message("▶  상단 모듈의  [ START ]  버튼을 눌러 시작하세요")
        # 2열/3열 초기화
        self._clear_analysis_panels()

    def on_clear_analysis(self) -> None:
        """[Clear Coin Analysis] 클릭 → ANALYSIS → RANKING 전환."""
        if self._app_state != "ANALYSIS":
            return
        self._app_state = "RANKING"
        self._analysis_mode = False
        # 타이머 중지
        self._stop_chart_timer()
        self._stop_analysis_timer()
        # [Clear] 버튼 숨김
        if self._clear_btn:
            self._clear_btn.pack_forget()
        # Assign 버튼 제거 (RANKING 복귀 시 미선택 상태)
        action_bar = getattr(self, '_action_bar', None)
        if action_bar is not None:
            for w in action_bar.winfo_children():
                if hasattr(w, '_is_assign_btn'):
                    w.destroy()
        # 1열 재개 (이미 DataManager는 실행 중)
        self._rebuild_ranking_rows()
        # 헤더 메시지 복원
        self._set_header_message("← 1열에서 코인 심볼을 클릭하세요")
        # 2열/3열 초기화
        self._clear_analysis_panels()

    def _clear_analysis_panels(self) -> None:
        """2열 + 3열 모든 패널을 빈 화면으로 완전 초기화.
        헤더는 호출자(on_clear_analysis/on_app_stop)에서 별도 설정.
        """
        # ── 2열: Coin Chart / MTF / Macro 3개 모두 초기화 ───────
        # Figure 재사용 참조 초기화 — 다음 심볼 선택 시 새로 생성
        self._mpl_canvas = None
        self._mpl_fig    = None
        self._mpl_ax     = None
        for panel_name in ["_chart_f", "_mtf_f", "_macro_f"]:
            panel = getattr(self, panel_name, None)
            if panel is not None:
                for w in panel.winfo_children():
                    try:
                        w.destroy()
                    except Exception:
                        pass

        # Coin Chart 탭에 안내 메시지 표시
        if getattr(self, "_chart_f", None) is not None:
            tk.Label(self._chart_f,
                     text="← 1열에서 코인 심볼을 클릭하세요",
                     bg="#0D0D0D", fg=DIM_TEXT,
                     font=("Segoe UI", 10)).pack(expand=True)

        # 2열 탭 버튼 상태 초기화 (Coin Chart 기본 활성)
        try:
            self._switch_chart_tab("chart")
        except Exception:
            pass

        # ── 3열: 5개 패널 모두 초기화 (verdict/ind/ema/energy/deriv) ──
        for panel_name in ["_verdict_f", "_ind_f", "_ema_f",
                           "_energy_f", "_deriv_f"]:
            panel = getattr(self, panel_name, None)
            if panel is not None:
                for w in panel.winfo_children():
                    try:
                        w.destroy()
                    except Exception:
                        pass

        # 3열 종합분석 탭에 안내 메시지 표시 (기본 탭)
        if getattr(self, "_verdict_f", None) is not None:
            tk.Label(self._verdict_f,
                     text="← 1열에서 코인 심볼을 클릭하세요",
                     bg=DARK_PANEL, fg=DIM_TEXT,
                     font=("Segoe UI", 10)).pack(expand=True)

        # 3열 탭 상태 초기화 (종합분석 기본 활성)
        try:
            self._switch_mid_tab("verdict")
        except Exception:
            pass

    # ── 콜백 기반 갱신 (타이머 제거) ──────────────────────────────
    # 2열/3열은 DataManager 콜백이 발동할 때만 갱신:
    #   _on_data_ready:  STAGE1 완료 (클릭 후 4~8초) → 2열+3열 즉시 갱신
    #   _on_klines_ready: STAGE3 완료 (60초마다) → 2열 차트 부드럽게 갱신
    # → 데이터 변화가 있을 때만 렌더링 (낭비 없음, 깜빡임 없음)

    def _start_chart_timer(self) -> None:
        """콜백 기반으로 전환 — 타이머 불필요."""
        pass   # 타이머 제거됨

    def _stop_chart_timer(self) -> None:
        """콜백 기반으로 전환 — 취소할 타이머 없음."""
        self._chart_timer_id = None

    def _start_analysis_timer(self) -> None:
        """콜백 기반으로 전환 — 타이머 불필요."""
        pass   # 타이머 제거됨

    def _stop_analysis_timer(self) -> None:
        """콜백 기반으로 전환 — 취소할 타이머 없음."""
        self._analysis_timer_id = None

    # ── _do_refresh_immediate() — 클릭 즉시 처리 (헤더 + 2열 차트) ────────
    def _do_refresh_immediate(self) -> None:
        """클릭 직후 즉각 표시: 심볼 헤더 + TF 버튼 + 2열(차트/MTF/Macro).
        캐시 기반으로 즉시 렌더링 — 정확한 지표는 _do_refresh_detail()에서 처리.
        """
        self._refresh_header()
        self._refresh_tf_buttons()
        if self._cur_chart_tab == "chart":
            self.after(10, self._refresh_chart)
        elif self._cur_chart_tab == "mtf":
            self.after(10, self._refresh_mtf)
        elif self._cur_chart_tab == "macro":
            self.after(10, self._refresh_macro)
        else:
            self.after(10, self._refresh_chart)

    # ── _do_refresh_detail() — 백그라운드 갱신 완료 후 3열 지표 갱신 ────────
    def _do_refresh_detail(self) -> None:
        """실데이터 갱신 완료 후 3열 전체 갱신: 지표·파생·에너지·종합판단.
        ANALYSIS 상태에서만 실행 (RANKING/IDLE 중 호출 시 무시).
        """
        if self._app_state != "ANALYSIS":
            return
        self._refresh_header()       # 헤더도 최신 데이터로 재갱신
        self._refresh_indicators()
        self._refresh_ema()
        self._refresh_deriv()
        self._refresh_energy()
        self._refresh_verdict()
        self._refresh_tf_buttons()
        if self._cur_chart_tab == "chart":
            self.after(10, self._refresh_chart)
        elif self._cur_chart_tab == "mtf":
            self.after(10, self._refresh_mtf)
        elif self._cur_chart_tab == "macro":
            self.after(10, self._refresh_macro)
        else:
            self.after(10, self._refresh_chart)

    # ── _do_refresh() — 하위 호환 (30초 타이머 등 기존 호출부 유지) ──────────
    def _do_refresh(self) -> None:
        """전체 갱신 (타이머 주기 갱신용). 즉각+지연 구분 없이 전체 처리."""
        self._do_refresh_detail()

    # ── 실데이터 갱신 완료 콜백 (DataManager 백그라운드 → 메인 스레드) ──
    def _on_data_ready(self, symbol: str) -> None:
        """STAGE1 완료 콜백 — 2열+3열 즉시 갱신 (콜백 기반).

        ANALYSIS 상태일 때만 갱신:
          - 3열: 지표·파생·에너지·종합 전체 갱신
          - 2열: 현재 선택 탭 갱신 (차트/MTF/Macro)
        """
        def _check_and_refresh():
            try:
                if self._sel_var.get() != symbol:
                    return
                if self._app_state != "ANALYSIS":
                    return
                # ── 3열 갱신 ──────────────────────────────────
                self._do_refresh_detail()
                # ── 2열 갱신 (현재 선택 탭만) ─────────────────
                tab = getattr(self, "_cur_chart_tab", "chart")
                if tab == "chart":
                    self.after(30, self._refresh_chart)
                elif tab == "mtf":
                    self.after(30, self._refresh_mtf)
                elif tab == "macro":
                    self.after(30, self._refresh_macro)
            except Exception:
                pass
        try:
            self.after(0, _check_and_refresh)
        except Exception:
            pass

    def _on_klines_ready(self) -> None:
        """STAGE3 klines 완료 콜백 — 상태에 따라 역할 분리.

        RANKING 상태 → 1열 랭킹 재빌드 (_on_klines_ready_col1)
        ANALYSIS 상태 → 2열 차트 부드럽게 갱신 (matplotlib 재사용)
        MRO: _Col1Mixin보다 MiddlePanel이 우선이므로 이 메서드가 실행됨.
        """
        def _dispatch():
            try:
                state = self._app_state
                if state == "RANKING":
                    # 1열 랭킹 재빌드 (TF합의·ATR%·EMA 즉시 반영)
                    self._on_klines_ready_col1()
                elif state == "ANALYSIS":
                    # 2열 차트 부드럽게 갱신 (Figure 재사용)
                    tab = getattr(self, "_cur_chart_tab", "chart")
                    if tab == "chart":
                        if self._mpl_canvas is not None:
                            self._draw_mpl_chart()
                        else:
                            self._refresh_chart()
                    elif tab == "mtf":
                        self._refresh_mtf()
                    elif tab == "macro":
                        self._refresh_macro()
            except Exception:
                pass
        try:
            self.after(0, _dispatch)
        except Exception:
            pass


if __name__ == "__main__":
    _root = tk.Tk()
    _root.withdraw()           # 빈 루트 창 숨김
    app = MiddlePanel(_root)
    _root.mainloop()
