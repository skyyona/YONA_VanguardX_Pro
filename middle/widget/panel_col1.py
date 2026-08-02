"""
middle/widget/panel_col1.py
1열 Real-Time Ranking + Blacklist 믹스인
"""
from __future__ import annotations
import tkinter as tk
import tkinter.ttk as ttk
import webbrowser
from middle.widget.constants import *
from middle.widget.constants import _COLS, _POS, _NEG, _YEL, _ORA, _DIM, _LGR

# ── shared_context에서 헬퍼 함수 import (단일 정의, 중복 없음) ──
from middle.widget.shared_context import get_ind, _live_ranking
import middle.widget.shared_context as _ctx

# ── Sort by 7개 모드 스코어러 (ranking/ 폴더 — 모드별 단일 파일 분리) ──
from middle.col1_ranking_blacklist.ranking.ticker_scorer import TickerScorer
from middle.col1_ranking_blacklist.ranking.sharp_rise_scorer import SharpRiseScorer
from middle.col1_ranking_blacklist.ranking.sharp_decline_scorer import SharpDeclineScorer
from middle.col1_ranking_blacklist.ranking.volatility_scorer import VolatilityScorer
from middle.col1_ranking_blacklist.ranking.fourtf_scorer import FourTFScorer
from middle.col1_ranking_blacklist.ranking.newlisted_scorer import NewlistedScorer
from middle.col1_ranking_blacklist.ranking.gold_ranking import GoldRanking
from middle.col1_ranking_blacklist.ranking.player_ranking import PlayerRanking
from middle.col3_analysis_panels.technical_analysis.atr_percent import AtrPercent

# Blacklist/Settling/Pending 관련 (middle_panel.py 와 동일한 선택적 import)
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


class _Col1Mixin:
    """1열 Real-Time Ranking + Blacklist 믹스인."""

    # _COLS: constants.py에서 import된 값을 클래스 속성으로 참조 (중복 정의 없음)
    _COLS = _COLS  # noqa

    # ── 스타일 ─────────────────────────────────────────────────
    def _setup_style(self) -> None:
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

    # ══════════════════════════════════════════════════════════
    # 1열 — 커스텀 탭 (ttk.Notebook 미사용 → 테두리 없음)
    # ══════════════════════════════════════════════════════════
    def _build_left(self, pane: tk.PanedWindow) -> None:
        outer = tk.Frame(pane, bg=DARK_BG)
        pane.add(outer, minsize=403)

        # ── 탭 버튼 바 ──────────────────────────────────────
        tab_bar = tk.Frame(outer, bg=DARK_BG)
        tab_bar.pack(fill="x", side="top")

        self._tab_btn_rank = tk.Button(
            tab_bar, text="  📊  Real-Time Ranking  ",
            bg=DARK_PANEL, fg=ACCENT_BLUE,
            activebackground=DARK_PANEL, activeforeground=ACCENT_BLUE,
            font=("Segoe UI", 9, "bold"),
            relief="flat", bd=0, padx=4, pady=8,
            cursor="hand2",
            command=lambda: self._switch_tab(0),
        )
        self._tab_btn_rank.pack(side="left")

        self._tab_btn_bl = tk.Button(
            tab_bar, text="  🚫  Blacklist  ",
            bg=DARK_BG, fg=DIM_TEXT,
            activebackground=DARK_PANEL, activeforeground=ACCENT_BLUE,
            font=("Segoe UI", 9, "bold"),
            relief="flat", bd=0, padx=4, pady=8,
            cursor="hand2",
            command=lambda: self._switch_tab(1),
        )
        self._tab_btn_bl.pack(side="left")

        # 탭 바 하단 구분선
        tk.Frame(outer, bg="#2A2A2A", height=1).pack(fill="x", side="top")

        # ── 탭 콘텐츠 영역 (테두리 없음) ──────────────────
        content = tk.Frame(outer, bg=DARK_BG)
        content.pack(fill="both", expand=True, side="top")

        self._tab_ranking_f  = tk.Frame(content, bg=DARK_BG)
        self._tab_blacklist_f = tk.Frame(content, bg=DARK_BG)

        self._build_ranking_tab(self._tab_ranking_f)
        # Blacklist 탭은 Lazy Build — 처음 탭 전환 시 생성

        # 기본 탭 표시
        self._switch_tab(0)

    # ── 커스텀 탭 전환 ─────────────────────────────────────────
    def _switch_tab(self, idx: int) -> None:
        if self._cur_tab == idx:
            return
        self._cur_tab = idx

        self._tab_ranking_f.pack_forget()
        self._tab_blacklist_f.pack_forget()

        if idx == 0:
            self._tab_ranking_f.pack(fill="both", expand=True)
            self._tab_btn_rank.configure(bg=DARK_PANEL, fg=ACCENT_BLUE)
            self._tab_btn_bl.configure(bg=DARK_BG,    fg=DIM_TEXT)
        else:
            self._tab_blacklist_f.pack(fill="both", expand=True)
            self._tab_btn_rank.configure(bg=DARK_BG,    fg=DIM_TEXT)
            self._tab_btn_bl.configure(bg=DARK_PANEL, fg=ACCENT_BLUE)
            # Lazy Build — 처음 표시 시점에 부모 폭이 확정된 후 생성
            if not self._bl_built:
                self.update_idletasks()   # 부모 레이아웃 완전 적용 보장
                self._build_blacklist_tab(self._tab_blacklist_f)
                self._bl_built = True

    # _COLS는 constants.py에서 import됨 (중복 정의 제거)

    # ══════════════════════════════════════════════════════════
    # 1탭 — Real-Time Ranking
    # ══════════════════════════════════════════════════════════
    def _build_ranking_tab(self, parent: tk.Frame) -> None:

        # ① 상단 컨트롤 바 (Sort by 드롭다운 + 경과 타이머 + Time Fix)
        self._top_bar_f = tk.Frame(parent, bg=DARK_PANEL, pady=6)
        self._top_bar_f.pack(fill="x")
        self._render_top_bar()

        # ② 컬럼 헤더 (데이터 행과 동일한 픽셀 너비 사용)
        hdr = tk.Frame(parent, bg=DARK_HEADER, pady=7)
        hdr.pack(fill="x")

        self._hdr_labels: list[tk.Label] = []
        for i, (text, px, h_anc) in enumerate(self._COLS):
            pad_l = 8 if i == 0 else 1
            if px > 0:
                f = tk.Frame(hdr, bg=DARK_HEADER, width=px)
                f.pack(side="left", padx=(pad_l, 1), fill="y")
                f.pack_propagate(False)
                inner_padx = (4, 4) if h_anc == "center" else (4, 2) if h_anc == "e" else (2, 4)
                lbl = tk.Label(f, text=text, bg=DARK_HEADER, fg=ACCENT_BLUE,
                         font=("Segoe UI", 9, "bold"), anchor=h_anc)
                lbl.pack(fill="both", expand=True, padx=inner_padx)
            else:
                lbl = tk.Label(hdr, text=text, bg=DARK_HEADER, fg=ACCENT_BLUE,
                         font=("Segoe UI", 9, "bold"), anchor=h_anc)
                lbl.pack(side="left", padx=(2, 8), fill="x", expand=True)
            self._hdr_labels.append(lbl)
        # 스크롤바(14px) 너비만큼 헤더 우측 여백 — 데이터 행과 정렬 맞춤
        tk.Frame(hdr, bg=DARK_HEADER, width=14).pack(side="right", fill="y")

        # 헤더 구분선
        tk.Frame(parent, bg="#333333", height=1).pack(fill="x")

        # ③ 스크롤 테이블
        ctr = tk.Frame(parent, bg=DARK_BG)
        ctr.pack(fill="both", expand=True)
        cv = tk.Canvas(ctr, bg=DARK_BG, highlightthickness=0)
        self._rank_cv = cv   # 행 자식 위젯의 MouseWheel 바인딩에서 참조
        # 스크롤바 — 표준 ttk, 다크 테마 적용 (드래그 + 위치 파악)
        sb = ttk.Scrollbar(ctr, orient="vertical", command=cv.yview)
        self._inner = tk.Frame(cv, bg=DARK_BG)
        self._inner.bind("<Configure>",
            lambda e: cv.configure(scrollregion=cv.bbox("all")))
        # 내부 프레임이 캔버스 너비에 맞게 자동 확장
        self._rank_win_id = cv.create_window((0, 0), window=self._inner, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        cv.bind("<Configure>",
            lambda e: cv.itemconfigure(self._rank_win_id, width=e.width))
        # yscrollincrement = 행 높이 → 1 unit = 정확히 1행, 창 크기 무관
        cv.configure(yscrollincrement=38)
        # 마우스휠 → 부드러운 Ease-Out 애니메이션 핸들러
        cv.bind("<MouseWheel>", self._on_wheel_scroll)

        self._build_ranking_rows()

    # ─── 상단 바 렌더링 (한 번만 호출, 위젯 참조 저장) ──────────
    def _render_top_bar(self) -> None:
        f = self._top_bar_f

        # ── 좌측: Sort by 레이블 + 드롭다운 버튼 ──────────────
        left = tk.Frame(f, bg=DARK_PANEL)
        left.pack(side="left", padx=(10, 0))

        tk.Label(left, text="Sort by", bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 6))

        self._sort_btn = tk.Button(
            left,
            text=f"  {self._sort_mode}  ▼",
            bg="#1E2A1E", fg=POSITIVE,
            activebackground="#263426", activeforeground=POSITIVE,
            font=("Segoe UI", 8, "bold"),
            relief="flat", padx=8, pady=3,
            cursor="hand2",
            command=self._show_sort_dropdown,
        )
        self._sort_btn.pack(side="left")

        # ── 중앙: 경과 시간 표시 ───────────────────────────────
        self._timer_lbl = tk.Label(
            f, text="00:00:00",
            bg=DARK_PANEL, fg=DIM_TEXT,
            font=("Consolas", 11, "bold"),
        )
        self._timer_lbl.pack(side="left", expand=True)

        # ── 우측: Time Fix 버튼 ────────────────────────────────
        self._timefix_btn = tk.Button(
            f,
            text="⏱  Time Fix",
            bg="#1A2A1A", fg=POSITIVE,
            activebackground="#1A3A1A", activeforeground=POSITIVE,
            font=("Segoe UI", 9, "bold"),
            relief="flat", padx=14, pady=4,
            cursor="hand2",
            command=self._toggle_time_fix,
        )
        self._timefix_btn.pack(side="right", padx=10)

    # ─── Sort by 드롭다운 팝업 ────────────────────────────────
    def _show_sort_dropdown(self) -> None:
        if self._sort_btn is None:
            return
        options = ["24h Ticker", "Sharp rise", "Sharp decline", "Volatility",
                   "4TF Optimization", "Newly Listed", "Pending Listing"]

        popup = tk.Toplevel(self)
        popup.wm_overrideredirect(True)
        popup.configure(bg="#2A2A2A")

        x = self._sort_btn.winfo_rootx()
        y = self._sort_btn.winfo_rooty() + self._sort_btn.winfo_height() + 2
        popup.geometry(f"+{x}+{y}")

        for opt in options:
            is_cur = (opt == self._sort_mode)
            btn = tk.Button(
                popup,
                text=("  ✓ " if is_cur else "     ") + opt + "  ",
                bg="#2A2A2A" if not is_cur else "#1E2A1E",
                fg=POSITIVE if is_cur else DARK_TEXT,
                activebackground="#333333", activeforeground=POSITIVE,
                font=("Segoe UI", 9, "bold" if is_cur else "normal"),
                relief="flat", anchor="w",
                padx=4, pady=5,
                cursor="hand2",
                command=lambda o=opt, p=popup: self._select_sort(o, p),
            )
            btn.pack(fill="x")

        popup.bind("<FocusOut>", lambda e: popup.destroy())
        popup.focus_set()

    def _select_sort(self, mode: str, popup: tk.Toplevel) -> None:
        popup.destroy()
        self._sort_mode = mode
        if self._shared_sort_mode is not None:
            self._shared_sort_mode.set(mode)
        if self._sort_btn:
            self._sort_btn.configure(text=f"  {mode}  ▼")
        # 컬럼 헤더 동적 교체 (col4, col5)
        if hasattr(self, "_hdr_labels") and len(self._hdr_labels) >= 6:
            if mode in ("Sharp rise", "Sharp decline"):
                self._hdr_labels[4].configure(text="Squeeze Str")
                self._hdr_labels[5].configure(text="Precise Check", anchor="center")
            elif mode == "Newly Listed":
                self._hdr_labels[4].configure(text="Listing Age")
                self._hdr_labels[5].configure(text="Opportunity", anchor="center")
            elif mode == "Volatility":
                self._hdr_labels[4].configure(text="ATR%")
                self._hdr_labels[5].configure(text="변동성 등급", anchor="center")
            elif mode == "4TF Optimization":
                self._hdr_labels[4].configure(text="4TF Score")
                self._hdr_labels[5].configure(text="충족 항목", anchor="center")
            elif mode == "Pending Listing":
                self._hdr_labels[1].configure(text="심볼  [유형]")
                self._hdr_labels[2].configure(text="상장예정일시",  anchor="center")
                self._hdr_labels[3].configure(text="남은시간",      anchor="center")
                self._hdr_labels[4].configure(text="markPrice",   anchor="center")
                self._hdr_labels[5].configure(text="",             anchor="center")
            else:
                self._hdr_labels[1].configure(text="Coin Symbol")
                self._hdr_labels[2].configure(text="Change%",   anchor="e")
                self._hdr_labels[3].configure(text="Cumulative",anchor="e")
                self._hdr_labels[4].configure(text="TF합의")
                self._hdr_labels[5].configure(text="추세 단계", anchor="center")
        # Pending Listing: 데이터 로드 후 재빌드
        if mode == "Pending Listing":
            self.after(0, self._load_pending_then_rebuild)

        # Sort by 모드와 가장 관련 높은 Coin Chart/MTF Stoch RSI/Macro & 4TF Entry
        # 탭을 기본으로 먼저 보여줌 (탭 콘텐츠 자체는 변경 없음)
        if mode == "4TF Optimization":
            self._switch_chart_tab("macro")
        elif mode in ("Sharp rise", "Sharp decline"):
            self._switch_chart_tab("mtf")
        else:
            self._switch_chart_tab("chart")
        # 종합 분석 패널 제목을 현재 Sort by 모드에 맞게 갱신
        if self._verdict_title_lbl is not None:
            self._verdict_title_lbl.configure(text=f"📋 {mode} 분석 및 권장 레버리지")
        self._refresh_verdict()
        self._rebuild_ranking_rows()

    # ─── Sort by 점수 계산 — ranking/ 폴더 각 Scorer 클래스로 위임 ──
    # (panel_col3.py 등 기존 호출부 호환을 위해 동일 메서드명 유지)
    def _calc_rise_score(self, sym: str, tag_map: dict | None = None) -> dict:
        return SharpRiseScorer.calc_score(sym, tag_map)

    def _calc_decline_score(self, sym: str, tag_map: dict | None = None) -> dict:
        return SharpDeclineScorer.calc_score(sym, tag_map)

    def _calc_4tf_score(self, sym: str) -> dict:
        return FourTFScorer.calc_score(sym)

    def _calc_newlist_score(self, sym: str, row: list | None = None) -> dict:
        return NewlistedScorer.calc_score(sym, row)

    # ─── 정렬된 랭킹 데이터 반환 (Sort by 모드별 수량 제한·점수 필터 적용) ──
    def _get_sorted_ranking(self) -> list:
        # _ctx 경유 접근 (global 불필요)
        if _ctx._data_mgr is not None:
            data = list(_ctx._data_mgr.get_ranking_rows())
        else:
            data = list(_live_ranking())

        # ── 블랙리스트 심볼 제외 ──────────────────────────────
        if _ctx._bl_mgr is not None and _ctx._bl_mgr.get_all():
            data = [r for r in data if not _ctx._bl_mgr.is_blacklisted(r[0])]

        mode = self._sort_mode

        # ── 각 Sort by 모드 — ranking/ 폴더 전용 Scorer 클래스로 위임 ──
        if mode == "24h Ticker":
            return TickerScorer.get_sorted(data, _ctx._data_mgr, _ctx._bl_mgr, limit=100)
        elif mode == "Sharp rise":
            return SharpRiseScorer.get_sorted(data, limit=20)
        elif mode == "Sharp decline":
            return SharpDeclineScorer.get_sorted(data, limit=30)
        elif mode == "Volatility":
            return VolatilityScorer.get_sorted(data, limit=100)
        elif mode == "4TF Optimization":
            return FourTFScorer.get_sorted(data, limit=50)
        elif mode == "Newly Listed":
            nl_data = _ctx._data_mgr.get_newlisted_rows() if _ctx._data_mgr is not None else data
            if _ctx._bl_mgr is not None and _ctx._bl_mgr.get_all():
                nl_data = [r for r in nl_data if not _ctx._bl_mgr.is_blacklisted(r[0])]
            return NewlistedScorer.get_sorted(nl_data, limit=30)
        elif mode == "Pending Listing":
            return []   # 표시 전용 모드 — _build_pending_rows() 경로에서 처리, 여기 도달하면 안 됨

        return data

    # ─── 랭킹 행 전체 재생성 ──────────────────────────────────
    def _rebuild_ranking_rows(self) -> None:
        """랭킹 행 재생성 — 안정적 단일 동기 빌드.

        pack_forget(0.17ms): 기존 행 즉시 숨김
        동기 빌드(~104ms):   청크 없이 한번에 전체 표시 → 안정적, 깜빡임 없음
        백그라운드 destroy:  숨겨진 old 행을 after(0)으로 조용히 정리
        """
        # ① 기존 행 스냅샷
        old_children = list(self._inner.winfo_children())

        # ② 데이터 구조 초기화
        self._row_frames.clear()
        self._special.clear()
        self._cum_labels.clear()
        self._change_labels.clear()
        self._phase_labels.clear()

        # ③ pack_forget (0.17ms) — 즉시 화면에서 제거
        for w in old_children:
            try:
                w.pack_forget()
            except Exception:
                pass

        # Gold Ranking — 종합 1위 심볼 갱신 (행 빌드 전 확정)
        self._gold_sym        = GoldRanking.get_top1()
        # Player Detection — 전 심볼 태그 스캔 (행 빌드 전 확정)
        self._player_tags_map = PlayerRanking.scan_all()

        # ④ 동기 빌드 (~104ms) — 청크 없이 한번에, 리스트 안정적 표시
        self._build_ranking_rows()

        # ⑤ 선택 심볼 하이라이트 복원 (패널 갱신 없음 — flicker 방지)
        cur = self._sel_var.get()
        for idx, (_, sym) in enumerate(self._row_frames):
            if sym == cur:
                self._restore_row_highlight(idx)
                break
        else:
            # 현재 선택 심볼이 새 목록에 없을 때 — 하이라이트만 복원
            # _on_select 대신 _restore_row_highlight 사용:
            # → rebuild 완료 시 자동으로 분석/바이낸스 실행되는 부작용 방지
            if self._row_frames:
                self._restore_row_highlight(0)

        # ⑥ old 행 백그라운드 destroy (숨겨진 상태, 시각 영향 없음)
        if old_children:
            self.after(0, lambda oc=old_children: self._destroy_old_rows(oc))

    def _destroy_old_rows(self, old_children: list) -> None:
        """pack_forget된 old 행들을 백그라운드에서 일괄 정리."""
        for w in old_children:
            try:
                w.destroy()
            except Exception:
                pass

    # ─── 랭킹 행 생성 ─────────────────────────────────────────
    def _build_ranking_rows(self) -> None:
        """랭킹 행 전체 생성."""
        # _ctx 경유 접근 (global 불필요)   # 함수 최상단 선언 (if 블록 안 global 제거용)
        if getattr(self, '_app_state', 'IDLE') == "IDLE":
            return
        if self._sort_mode == "Pending Listing":
            self._build_pending_rows()
            return
        data = self._get_sorted_ranking()
        _squeeze_tag_map = (
            {d[0]: d[11] for d in _live_ranking()}
            if self._sort_mode in ("Sharp rise", "Sharp decline") else None
        )
        for idx, row in enumerate(data):
            (symbol, days,
             tf_text, tf_color,
             change, change_color,
             cum_pct, cum_color,
             phase, phase_color, phase_priority,
             player_tags) = row

            _p_entry = self._player_tags_map.get(symbol)
            row_bg = (GOLD_ROW_BG        if symbol == self._gold_sym                              else
                      PLAYER_SHORT_ROW_BG if _p_entry and _p_entry.get("direction") == "short"   else
                      PLAYER_MIX_ROW_BG   if _p_entry and _p_entry.get("direction") == "mixed"   else
                      PLAYER_ROW_BG       if _p_entry                                             else
                      DARK_ROW_ODD        if idx % 2 == 0                                         else
                      DARK_ROW_EVN)
            rank   = idx + 1

            _row_data = row   # tk.Frame 덮어쓰기 전 원본 tuple 보존
            row = tk.Frame(self._inner, bg=row_bg, pady=9,
                           highlightthickness=0)
            row.pack(fill="x")
            self._row_frames.append((row, symbol))
            self._special[idx] = set()

            # 행 전체 클릭 → 2열 분석 갱신
            row.bind("<Button-1>",
                     lambda e, s=symbol, i=idx: self._on_select(s, i))

            # ── Col 0 : 순위 번호 (28px, center) ──────────
            _, px0, _ = self._COLS[0]
            rk_f = tk.Frame(row, bg=row_bg, width=px0)
            rk_f.pack(side="left", padx=(8, 1), fill="y")
            rk_f.pack_propagate(False)
            rk_col = YELLOW if rank <= 3 else (ACCENT_BLUE if rank <= 10 else DIM_TEXT)
            tk.Label(rk_f, text=str(rank), bg=row_bg, fg=rk_col,
                     font=("Segoe UI", 9, "bold"), anchor="center").pack(fill="both", expand=True)

            # ── Col 1 : Coin Symbol (152px, left) ──────────
            _, px2, _ = self._COLS[1]
            sf = tk.Frame(row, bg=row_bg, width=px2)
            sf.pack(side="left", padx=1, fill="y")
            sf.pack_propagate(False)

            sym_lbl = tk.Label(sf, text=symbol, bg=row_bg, fg=ACCENT_BLUE,
                               font=("Segoe UI", 9, "bold"), anchor="w",
                               cursor="hand2")
            sym_lbl.pack(side="left", padx=(2, 0), fill="y")
            sym_lbl.bind("<Button-1>",
                         lambda e, s=symbol, i=idx: [
                             self._on_select(s, i),
                             self._open_binance(s),
                         ] and "break")   # 이벤트 전파 차단 → row.bind 중복 방지

            # 신규 30일 이내만 표시
            if 0 < days <= 30:
                new_lbl = tk.Label(sf, text=f" 신규{days}일 ",
                                   bg=NEW_BG, fg=NEW_FG,
                                   font=("Segoe UI", 7, "bold"))
                new_lbl.pack(side="left", padx=(4, 0))
                self._special[idx].add(new_lbl)

            # ── Col 2 : Change% (72px, right) ──────────────
            _, px3, _ = self._COLS[2]
            ch_f = tk.Frame(row, bg=row_bg, width=px3)
            ch_f.pack(side="left", padx=1, fill="y")
            ch_f.pack_propagate(False)
            chg_lbl = tk.Label(ch_f, text=change, bg=row_bg, fg=change_color,
                                font=("Segoe UI", 9, "bold"), anchor="e")
            chg_lbl.pack(fill="both", expand=True, padx=(2, 4))
            self._change_labels[symbol] = chg_lbl   # 소프트 갱신용 참조 저장

            # ── Col 3 : Cumulative (78px, right) ───────────
            _, px4, _ = self._COLS[3]
            cum_f = tk.Frame(row, bg=row_bg, width=px4)
            cum_f.pack(side="left", padx=1, fill="y")
            cum_f.pack_propagate(False)
            # Time Fix 활성 중 재생성 시: Fix 시점 기준 현재가 변화율로 초기화
            # Cumulative = (현재가 - Fix가) / Fix가 × 100  (Fix 직후 = +0.00%)
            if self._time_fixed and self._time_fix_prices:
                fix_price = self._time_fix_prices.get(symbol, 0.0)
                if fix_price > 0 and _ctx._data_mgr is not None:
                    tkr = _ctx._data_mgr._tkr_map.get(symbol)
                    if tkr and tkr.last_price > 0:
                        _pct = (tkr.last_price - fix_price) / fix_price * 100.0
                        cum_text_now = f"{_pct:+.2f}%"
                        cum_col_now  = POSITIVE if _pct > 0 else (NEGATIVE if _pct < 0 else DIM_TEXT)
                    else:
                        cum_text_now, cum_col_now = "+0.00%", DIM_TEXT
                else:
                    cum_text_now, cum_col_now = "+0.00%", DIM_TEXT
            else:
                cum_text_now = "+000.00"
                cum_col_now  = DIM_TEXT
            cum_lbl = tk.Label(cum_f, text=cum_text_now,
                               bg=row_bg, fg=cum_col_now,
                               font=("Consolas", 9, "bold"), anchor="e")
            cum_lbl.pack(fill="both", expand=True, padx=(2, 4))
            self._cum_labels[symbol] = (cum_lbl, cum_pct, cum_color)

            # ── Sharp rise/decline / Newly Listed / Volatility / 4TF Optimization 사전 계산 ──
            _is_squeeze    = self._sort_mode in ("Sharp rise", "Sharp decline")
            _is_newlisted  = self._sort_mode == "Newly Listed"
            _is_volatility = self._sort_mode == "Volatility"
            _is_4tf        = self._sort_mode == "4TF Optimization"
            if _is_squeeze:
                # 정렬 기준(_get_sorted_ranking)과 동일한 16점 만점 점수를 사용
                # (Player 가산점 포함) — 별점이 정렬 순위·종합분석과 같은 척도를 갖도록 통일
                if self._sort_mode == "Sharp rise":
                    _res = self._calc_rise_score(symbol, _squeeze_tag_map)
                else:
                    _res = self._calc_decline_score(symbol, _squeeze_tag_map)

                if not _res["qualified"]:
                    # 자격 미달 — 별점 산정 대상이 아님을 명시
                    _stars, _star_col = "—", DIM_TEXT
                    if self._sort_mode == "Sharp rise":
                        _sq_txt = f"⚠ 자격 미달 (숏쏠림 {_res['sr']:.0f}%<50%)"
                    else:
                        _sq_txt = f"⚠ 자격 미달 (롱쏠림 {_res['lr']:.0f}%<50%)"
                    _sq_col = DIM_TEXT
                else:
                    # 별점 (16점 만점)
                    _total = _res["total"]
                    if   _total >= 14: _stars, _star_col = "★★★★★", POSITIVE
                    elif _total >= 11: _stars, _star_col = "★★★★☆", "#8ad7b5"
                    elif _total >=  8: _stars, _star_col = "★★★☆☆", YELLOW
                    elif _total >=  5: _stars, _star_col = "★★☆☆☆", ORANGE
                    else:              _stars, _star_col = "★☆☆☆☆", DIM_TEXT
                    # 내용 텍스트
                    if self._sort_mode == "Sharp rise":
                        if _res["liq_s"] < 1.5:
                            _sq_txt = f"숏 {_res['sr']:.0f}%  청산+{_res['liq_s']:.1f}% 근접!"
                            _sq_col = NEGATIVE
                        else:
                            _sq_txt = f"숏 {_res['sr']:.0f}%  FR{_res['fr']:+.3f}%"
                            _sq_col = "#8ad7b5" if _res['fr'] < -0.03 else DIM_TEXT
                    else:
                        if _res["liq_l"] < 1.0:
                            _sq_txt = f"롱 {_res['lr']:.0f}%  청산-{_res['liq_l']:.1f}% 근접!"
                            _sq_col = NEGATIVE
                        else:
                            _sq_txt = f"롱 {_res['lr']:.0f}%  FR{_res['fr']:+.3f}%"
                            _sq_col = ORANGE if _res['fr'] > 0.05 else DIM_TEXT

            # ── Newly Listed col4/col5 사전 계산 ─────────────
            if _is_newlisted:
                # Col4: Listing Age 텍스트 + 색상
                if   days <=  7: _age_txt, _age_col = f"D+{days}  Ultra", NEW_FG
                elif days <= 30: _age_txt, _age_col = f"D+{days}  New",   YELLOW
                elif days <= 90: _age_txt, _age_col = f"D+{days}  Recent", DIM_TEXT
                else:            _age_txt, _age_col = f"D+{days}  Mature", "#555555"
                # Col5: 자격 미달 시 경고, 충족 시 라이프사이클 단축 레이블
                _res_nl = self._calc_newlist_score(symbol, _row_data)
                if not _res_nl["qualified"]:
                    _opp_txt, _opp_col = "⚠ 자격 미달 (VSS/OI 부족)", DIM_TEXT
                else:
                    _lc_result = self._nl_lifecycle(symbol, days)
                    if _lc_result:
                        _, _opp_txt, _opp_col, _ = _lc_result
                    else:
                        _opp_txt, _opp_col = "관망 중", DIM_TEXT

            # ── Volatility col4/col5 사전 계산 ────────────────
            if _is_volatility:
                # 정렬 기준(ATR%)을 테이블에서 직접 확인 가능하게 노출
                _atr     = get_ind(symbol).get("atr", 2.0)
                _atr_txt = f"{_atr:.1f}%"
                _atr_col = AtrPercent.color(_atr)
                if _atr > 5.0:
                    _grade_txt = "🔥 고변동 — 큰 스윙 주의"
                elif _atr >= 2.0:
                    _grade_txt = "─ 중간 변동성"
                else:
                    _grade_txt = "❄ 저변동 — 스캘핑 부적합"
                _grade_col = _atr_col

            # ── 4TF Optimization col4/col5 사전 계산 ──────────
            if _is_4tf:
                _res4   = self._calc_4tf_score(symbol)
                _total4 = _res4["total"]
                if   _total4 >= 12: _stars4, _star4_col = "★★★★★", POSITIVE
                elif _total4 >=  9: _stars4, _star4_col = "★★★★☆", "#8ad7b5"
                elif _total4 >=  6: _stars4, _star4_col = "★★★☆☆", YELLOW
                elif _total4 >=  3: _stars4, _star4_col = "★★☆☆☆", ORANGE
                else:               _stars4, _star4_col = "★☆☆☆☆", DIM_TEXT

                _sc4  = _res4["scores"]
                _hit4 = sum(1 for v in _sc4.values() if v > 0)
                _NAMES4 = {"align": "TF정렬", "entry": "1m진입", "macro": "거시지지",
                           "atr": "ATR적정", "volume": "거래량Top10", "fr": "FR중립",
                           "oi": "OI증가", "balance": "롱숏균형"}
                _missing4 = [_NAMES4[k] for k, v in _sc4.items() if v == 0]
                if _missing4:
                    _more = "…" if len(_missing4) > 2 else ""
                    _4tf_txt = f"✅ {_hit4}/8 충족 · 부족: {', '.join(_missing4[:2])}{_more}"
                    _4tf_col = YELLOW if _hit4 >= 6 else ORANGE
                else:
                    _4tf_txt = f"✅ {_hit4}/8 전부 충족!  (총 {_total4}/13점)"
                    _4tf_col = POSITIVE

            # ── Col 4 : Squeeze Str or 잠재력 크기 ────────────
            _, px5, _ = self._COLS[4]
            tf_f = tk.Frame(row, bg=row_bg, width=px5)
            tf_f.pack(side="left", padx=1, fill="y")
            tf_f.pack_propagate(False)
            if _is_squeeze:
                tf_lbl = tk.Label(tf_f, text=_stars, bg=row_bg, fg=_star_col,
                                  font=("Segoe UI", 8, "bold"), anchor="center")
            elif _is_newlisted:
                tf_lbl = tk.Label(tf_f, text=_age_txt, bg=row_bg, fg=_age_col,
                                  font=("Consolas", 8, "bold"), anchor="center")
            elif _is_volatility:
                tf_lbl = tk.Label(tf_f, text=_atr_txt, bg=row_bg, fg=_atr_col,
                                  font=("Consolas", 9, "bold"), anchor="center")
            elif _is_4tf:
                tf_lbl = tk.Label(tf_f, text=_stars4, bg=row_bg, fg=_star4_col,
                                  font=("Segoe UI", 8, "bold"), anchor="center")
            else:
                tf_lbl = tk.Label(tf_f, text=tf_text, bg=row_bg, fg=tf_color,
                                  font=("Segoe UI", 9, "bold"), anchor="center")
            tf_lbl.pack(fill="both", expand=True, padx=2)
            self._special[idx].add(tf_lbl)

            # ── Col 5 : Precise Check or 잠재력 내용 ──────────
            if _is_squeeze:
                ph_f = tk.Frame(row, bg=row_bg)
                ph_f.pack(side="left", padx=(4, 8), fill="x", expand=True)
                ph_lbl = tk.Label(ph_f, text=_sq_txt, bg=row_bg, fg=_sq_col,
                                  font=("Consolas", 8, "bold"), anchor="w")
            elif _is_newlisted:
                ph_f = tk.Frame(row, bg=row_bg)
                ph_f.pack(side="left", padx=(4, 8), fill="x", expand=True)
                ph_lbl = tk.Label(ph_f, text=_opp_txt, bg=row_bg, fg=_opp_col,
                                  font=("Consolas", 8, "bold"), anchor="w")
            elif _is_volatility:
                ph_f = tk.Frame(row, bg=row_bg)
                ph_f.pack(side="left", padx=(4, 8), fill="x", expand=True)
                ph_lbl = tk.Label(ph_f, text=_grade_txt, bg=row_bg, fg=_grade_col,
                                  font=("Consolas", 8, "bold"), anchor="w")
            elif _is_4tf:
                ph_f = tk.Frame(row, bg=row_bg)
                ph_f.pack(side="left", padx=(4, 8), fill="x", expand=True)
                ph_lbl = tk.Label(ph_f, text=_4tf_txt, bg=row_bg, fg=_4tf_col,
                                  font=("Consolas", 8, "bold"), anchor="w")
            else:
                _p_e = self._player_tags_map.get(symbol)
                if _p_e and _p_e.get("tags"):
                    # Player Detection 감지: 추세 단계 대신 최강 태그 1개 표시
                    _top_tag  = _p_e["tags"][0]
                    _tag_txt, _tag_col, _tag_str = _top_tag
                    ph_bg = row_bg
                    ph_f = tk.Frame(row, bg=ph_bg)
                    ph_f.pack(side="left", padx=(4, 8), fill="x", expand=True)
                    ph_lbl = tk.Label(ph_f, text=f"{_tag_txt}  {_tag_str}%",
                                      bg=ph_bg, fg=_tag_col,
                                      font=("Segoe UI", 9, "bold"), anchor="w")
                else:
                    ph_bg = "#0F1F0F" if phase.startswith("◀") else (
                            "#1F0F0F" if phase.startswith("▶") else row_bg)
                    ph_f = tk.Frame(row, bg=ph_bg)
                    ph_f.pack(side="left", padx=(4, 8), fill="x", expand=True)
                    ph_lbl = tk.Label(ph_f, text=phase, bg=ph_bg, fg=phase_color,
                                      font=("Segoe UI", 9, "bold"), anchor="w")
            ph_lbl.pack(fill="both", expand=True, padx=(4, 2))
            self._special[idx].add(ph_f)
            self._special[idx].add(ph_lbl)
            self._phase_labels[symbol] = (ph_f, ph_lbl)   # 소프트 갱신용 참조 저장

            # ── 모든 자식 위젯에 클릭 바인딩 재귀 적용 ────────────
            # Tkinter에서 자식 Label 클릭은 부모 Frame bind로 전파되지 않음
            # → row의 모든 자식에 직접 바인딩해야 어느 위치를 클릭해도 _on_select 발동
            # sym_lbl은 특수 바인딩(_open_binance + break) 유지 위해 skip
            self._bind_row_children(row, symbol, idx, skip={sym_lbl})

    # ─── Time Fix 토글 ────────────────────────────────────────
    def _toggle_time_fix(self) -> None:
        self._time_fixed = not self._time_fixed
        # _ctx 경유 접근 (global 불필요)
        if self._time_fixed:
            # ── 화면에 표시된 심볼만 현재가 스냅샷 ──────────────
            # _row_frames = 현재 Sort by 필터 후 랭킹에 표시된 N개 심볼
            self._time_fix_prices.clear()
            if _ctx._data_mgr is not None:
                for _, sym in self._row_frames:
                    tkr = _ctx._data_mgr._tkr_map.get(sym)
                    if tkr and tkr.last_price > 0:
                        self._time_fix_prices[sym] = tkr.last_price  # Fix 시점 가격 스냅샷
            # 타이머 시작
            self._elapsed_sec   = 0
            self._timer_running = True
            self._tick_timer()
            if self._timefix_btn:
                self._timefix_btn.configure(
                    text="✕  Release",
                    bg="#2A1A1A", fg=NEGATIVE,
                    activebackground="#3A2A2A", activeforeground=NEGATIVE)
            if self._timer_lbl:
                self._timer_lbl.configure(fg=POSITIVE)
        else:
            # ── 스냅샷 삭제 + 타이머 정지 + 리셋 ─────────────
            self._time_fix_prices.clear()
            self._timer_running = False
            self._elapsed_sec   = 0
            if self._timer_lbl:
                self._timer_lbl.configure(text="00:00:00", fg=DIM_TEXT)
            if self._timefix_btn:
                self._timefix_btn.configure(
                    text="⏱  Time Fix",
                    bg="#1A2A1A", fg=POSITIVE,
                    activebackground="#1A3A1A", activeforeground=POSITIVE)
            # Time Fix 해제 시 최신 순위로 즉시 재정렬
            # (Time Fix 중 스킵됐던 30초 재정렬을 즉시 실행)
            self.after(50, self._rebuild_ranking_rows)
        self._update_cum_labels()

    def _tick_timer(self) -> None:
        if not self._timer_running:
            return
        # ── self.after()는 try 밖에 — 어떤 예외도 타이머를 멈추지 않음 ────
        try:
            self._elapsed_sec += 1
            h = self._elapsed_sec // 3600
            m = (self._elapsed_sec % 3600) // 60
            s = self._elapsed_sec % 60
            try:
                if self._timer_lbl:
                    self._timer_lbl.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
            except Exception:
                pass

            # Time Fix 활성: 1초마다 Cumulative 실시간 갱신 (즉각 반응)
            if self._time_fixed:
                self._update_cum_labels()

            # 30초마다 순위 재정렬 — Time Fix 중 스킵
            if self._elapsed_sec % 30 == 0 and not self._time_fixed:
                self._rebuild_ranking_rows()

            # 30초마다 선택 심볼 패널 갱신 — ANALYSIS 상태에서만 실행
            # (콜백 기반 갱신으로 전환되었으므로 ANALYSIS 중에도 보조 갱신 역할)
            if self._elapsed_sec % 30 == 0:
                if getattr(self, '_app_state', 'IDLE') == "ANALYSIS":
                    if _ctx._data_mgr is not None:
                        sym = self._sel_var.get()
                        if sym:
                            _ctx._data_mgr.request_selected(sym)
        except Exception:
            pass   # 내부 예외는 무시, 타이머는 반드시 계속됨
        # ── 항상 다음 틱 예약 (try 블록 바깥) ──────────────────────
        self.after(1000, self._tick_timer)

    def _update_cum_labels(self) -> None:
        """Cumulative 컬럼 실시간 갱신.
        Time Fix 활성: (현재가 - Fix시점가) / Fix시점가 × 100
          - Fix 클릭 직후: +0.00% 시작
          - 이후 +3% 오르면 → +3.00%
          - 다시 -2% 내리면 → +1.00%  (Fix 기준점 대비 누적)
        Time Fix 비활성: '+000.00' (미측정)
        """
        # _ctx 경유 접근 (global 불필요)
        for sym, (lbl, _ft, _fc) in self._cum_labels.items():
            try:
                if self._time_fixed and self._time_fix_prices:
                    fix_price = self._time_fix_prices.get(sym, 0.0)
                    if fix_price > 0 and _ctx._data_mgr is not None:
                        tkr = _ctx._data_mgr._tkr_map.get(sym)
                        if tkr and tkr.last_price > 0:
                            pct = (tkr.last_price - fix_price) / fix_price * 100.0
                            txt = f"{pct:+.2f}%"
                            col = POSITIVE if pct > 0 else (NEGATIVE if pct < 0 else DIM_TEXT)
                        else:
                            txt, col = "+0.00%", DIM_TEXT
                    else:
                        txt, col = "+0.00%", DIM_TEXT
                    lbl.configure(text=txt, fg=col)
                else:
                    lbl.configure(text="+000.00", fg=DIM_TEXT)
            except Exception:
                pass

    # ─── Assign 버튼 처리 ─────────────────────────────────────
    def _on_assign(self, symbol: str) -> None:
        if self._assigned_sym == symbol:
            self._assigned_sym = None
            if self._shared_sym is not None:
                self._shared_sym.set("")        # 배치 해제
        else:
            self._assigned_sym = symbol
            if self._shared_sym is not None:
                self._shared_sym.set(symbol)    # bottom module 에 즉시 전달
        self._refresh_header()

    def _on_shared_sym_changed(self, *_) -> None:
        """bottom [Clear] 등 외부에서 shared_sym="" 설정 시 Assign 버튼 초기화"""
        if self._shared_sym is None:
            return
        if self._shared_sym.get() == "" and self._assigned_sym is not None:
            self._assigned_sym = None
            self._refresh_header()

    # ─── Binance 링크 열기 ───────────────────────────────────
    @staticmethod
    def _open_binance(symbol: str) -> None:
        url = f"https://www.binance.com/en/futures/{symbol}"
        webbrowser.open(url)

    # ══════════════════════════════════════════════════════════
    # 2탭 — Blacklist
    # ══════════════════════════════════════════════════════════

    def _build_blacklist_tab(self, parent: tk.Frame) -> None:
        # ── PanedWindow: 높이 드래그 조절 ─────────────────────────
        vpane = tk.PanedWindow(parent, orient="vertical",
                               bg=DARK_BG, sashwidth=4,
                               sashrelief="flat", sashpad=0,
                               bd=0, relief="flat")
        vpane.pack(fill="both", expand=True)

        # ══ 1행: Settling Update ═══════════════════════════════
        top_f = tk.Frame(vpane, bg=DARK_BG)
        vpane.add(top_f, minsize=80)

        t_bar = tk.Frame(top_f, bg=DARK_PANEL, pady=8)
        t_bar.pack(fill="x")
        tk.Label(t_bar, text="Settling Update",
                 bg=DARK_PANEL, fg=DARK_TEXT,
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=14)
        tk.Label(t_bar, text="● 자동 감지",
                 bg=DARK_PANEL, fg=POSITIVE,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 0))
        add_btn = tk.Button(t_bar, text="+ Add to Blacklist",
                            bg="#1A1000", fg=ORANGE,
                            activebackground="#2A2000", activeforeground=ORANGE,
                            font=("Segoe UI", 8, "bold"), relief="flat",
                            padx=10, pady=3, cursor="hand2")
        add_btn.pack(side="right", padx=12)

        t_ctr = tk.Frame(top_f, bg=DARK_BG)
        t_ctr.pack(fill="both", expand=True)

        t_tree = ttk.Treeview(t_ctr, style="Dark.Treeview",
                              columns=("rank", "check", "symbol", "change", "status"),
                              show="headings", selectmode="extended")
        t_tree.heading("rank",   text="#",           anchor="center")
        t_tree.heading("check",  text="☐",           anchor="center")
        t_tree.heading("symbol", text="Coin Symbol", anchor="center")
        t_tree.heading("change", text="Change%",     anchor="center")
        t_tree.heading("status", text="Status",      anchor="center")
        t_tree.column("rank",   width=40,  minwidth=30, stretch=False, anchor="center")
        t_tree.column("check",  width=44,  minwidth=36, stretch=False, anchor="center")
        t_tree.column("symbol", width=170, minwidth=80, stretch=True,  anchor="center")
        t_tree.column("change", width=100, minwidth=70, stretch=False, anchor="center")
        t_tree.column("status", width=140, minwidth=80, stretch=False, anchor="center")

        t_tree.tag_configure("settling_odd",  background=DARK_ROW_ODD, foreground=ORANGE)
        t_tree.tag_configure("settling_even", background=DARK_ROW_EVN, foreground=ORANGE)
        t_tree.tag_configure("halt_odd",      background=DARK_ROW_ODD, foreground=DIM_TEXT)
        t_tree.tag_configure("halt_even",     background=DARK_ROW_EVN, foreground=DIM_TEXT)
        t_tree.tag_configure("warn_odd",      background=DARK_ROW_ODD, foreground=NEGATIVE)
        t_tree.tag_configure("warn_even",     background=DARK_ROW_EVN, foreground=NEGATIVE)

        t_sb = ttk.Scrollbar(t_ctr, orient="vertical", command=t_tree.yview)
        t_tree.configure(yscrollcommand=t_sb.set)
        t_sb.pack(side="right", fill="y")
        t_tree.pack(side="left", fill="both", expand=True)

        # 체크박스 토글 (두 번째 컬럼 #2 클릭 시, sym_col=2)
        t_tree.bind("<Button-1>",
                    lambda e: self._toggle_tree_check(e, t_tree, self._checked_settling, 2))
        t_tree.bind("<Double-1>",
                    lambda e, t=t_tree: self._open_binance(
                        t.item(t.focus(), "values")[1] if t.focus() else ""))

        # ══ 2행: Blacklist ══════════════════════════════════════
        bot_f = tk.Frame(vpane, bg=DARK_BG)
        vpane.add(bot_f, minsize=80)

        b_bar = tk.Frame(bot_f, bg=DARK_PANEL, pady=8)
        b_bar.pack(fill="x")
        self._bl_count_lbl = tk.Label(b_bar, text="Blacklist",
                 bg=DARK_PANEL, fg=DARK_TEXT,
                 font=("Segoe UI", 10, "bold"))
        self._bl_count_lbl.pack(side="left", padx=14)
        rel_btn = tk.Button(b_bar, text="Release",
                            bg="#1A1000", fg=ORANGE,
                            activebackground="#2A2000", activeforeground=ORANGE,
                            font=("Segoe UI", 8, "bold"), relief="flat",
                            padx=10, pady=3, cursor="hand2")
        rel_btn.pack(side="right", padx=12)

        b_ctr = tk.Frame(bot_f, bg=DARK_BG)
        b_ctr.pack(fill="both", expand=True)

        b_tree = ttk.Treeview(b_ctr, style="Dark.Treeview",
                              columns=("rank", "check", "symbol", "change", "added", "status"),
                              show="headings", selectmode="extended")
        b_tree.heading("rank",   text="#",           anchor="center")
        b_tree.heading("check",  text="☐",           anchor="center")
        b_tree.heading("symbol", text="Symbol",      anchor="center")
        b_tree.heading("change", text="Change%",     anchor="center")
        b_tree.heading("added",  text="Added (UTC)", anchor="center")
        b_tree.heading("status", text="Status",      anchor="center")
        b_tree.column("rank",   width=40,  minwidth=30,  stretch=False, anchor="center")
        b_tree.column("check",  width=44,  minwidth=36,  stretch=False, anchor="center")
        b_tree.column("symbol", width=140, minwidth=80,  stretch=False, anchor="center")
        b_tree.column("change", width=90,  minwidth=70,  stretch=False, anchor="center")
        b_tree.column("added",  width=170, minwidth=120, stretch=True,  anchor="center")
        b_tree.column("status", width=100, minwidth=70,  stretch=False, anchor="center")

        b_tree.tag_configure("neg_odd",  background=DARK_ROW_ODD, foreground=NEGATIVE)
        b_tree.tag_configure("neg_even", background=DARK_ROW_EVN, foreground=NEGATIVE)
        b_tree.tag_configure("ora_odd",  background=DARK_ROW_ODD, foreground=ORANGE)
        b_tree.tag_configure("ora_even", background=DARK_ROW_EVN, foreground=ORANGE)
        b_tree.tag_configure("dim_odd",  background=DARK_ROW_ODD, foreground=DIM_TEXT)
        b_tree.tag_configure("dim_even", background=DARK_ROW_EVN, foreground=DIM_TEXT)

        # 체크박스 토글 (두 번째 컬럼 #2 클릭 시, sym_col=2)
        b_tree.bind("<Button-1>",
                    lambda e: self._toggle_tree_check(e, b_tree, self._checked_blacklist, 2))
        b_sb = ttk.Scrollbar(b_ctr, orient="vertical", command=b_tree.yview)
        b_tree.configure(yscrollcommand=b_sb.set)
        b_sb.pack(side="right", fill="y")
        b_tree.pack(side="left", fill="both", expand=True)

        # ── 위젯 참조 저장 (버튼 핸들러에서 사용) ────────────────
        self._t_tree = t_tree
        self._b_tree = b_tree

        # ── 버튼 command 연결 ─────────────────────────────────
        add_btn.configure(command=self._add_to_blacklist)
        rel_btn.configure(command=self._release_from_blacklist)

        # ── 초기 데이터 로드 ─────────────────────────────────
        self._load_settling_data()
        self._refresh_blacklist_ui()

        # 초기 sash 위치 (렌더 후 적용)
        parent.after(50, lambda p=vpane, r=parent: self._init_bl_sash(p, r))

    def _init_bl_sash(self, vpane: tk.PanedWindow, ref: tk.Frame) -> None:
        h = ref.winfo_height()
        if h > 40:
            vpane.sash_place(0, 0, max(100, h // 2))

    # ─── Blacklist 체크박스 토글 ─────────────────────────────

    def _toggle_tree_check(self, event: tk.Event,
                           tree: "ttk.Treeview",
                           checked: set, sym_col: int) -> None:
        """체크박스 컬럼(#2) 클릭 시 ☐↔☑ 토글.
        컬럼 구조: 1=#(순번) | 2=☐/☑(체크) | 3~5=데이터
        checked: 현재 ☑ 된 심볼 집합
        sym_col: values 내 심볼 인덱스 (2 = 세 번째 값)
        """
        region = tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = tree.identify_column(event.x)
        if col != "#2":   # 두 번째 컬럼(체크박스)만 토글
            return
        row_id = tree.identify_row(event.y)
        if not row_id:
            return
        vals = list(tree.item(row_id, "values"))
        if len(vals) <= sym_col:
            return
        sym = vals[sym_col]
        if not sym or sym == "데이터 로드 중...":
            return
        if sym in checked:
            checked.discard(sym)
            vals[1] = "☐"   # 두 번째 값(체크박스)
        else:
            checked.add(sym)
            vals[1] = "☑"   # 두 번째 값(체크박스)
        tree.item(row_id, values=vals)

    # ─── Blacklist 데이터 로드/갱신 헬퍼 ──────────────────────

    def _load_settling_data(self) -> None:
        """Settling Update: Binance exchangeInfo 기반 비정상 심볼 표시."""
        t_tree = getattr(self, "_t_tree", None)
        if t_tree is None:
            return
        for row in t_tree.get_children():
            t_tree.delete(row)

        settling_entries: list = []

        # 실데이터: Binance exchangeInfo에서 SETTLING/HALT 감지
        if _ctx._data_mgr is not None and _HAS_BLACKLIST:
            try:
                info = _ctx._data_mgr._client.fetch_exchange_info()
                if info:
                    settling_entries = _SettlingDetector.detect(info)
            except Exception:
                pass

        # 캐시 저장 (Blacklist 추가/해제 시 재조회 없이 즉시 갱신)
        self._settling_cache = list(settling_entries)

        # Blacklist에 이미 등록된 심볼 제외 후 표시
        self._render_settling_tree(t_tree)

    def _get_change_str(self, symbol: str) -> tuple:
        """심볼의 현재 Change% 문자열과 색상 반환.
        DataManager tkr_map에서 실시간 조회. 없으면 '—' 반환.
        """
        if _ctx._data_mgr is not None:
            tkr = _ctx._data_mgr._tkr_map.get(symbol)
            if tkr and tkr.price_change_pct != 0.0:
                pct = tkr.price_change_pct
                txt = f"{pct:+.2f}%"
                col = POSITIVE if pct > 0 else (NEGATIVE if pct < 0 else DIM_TEXT)
                return txt, col
        return "—", DIM_TEXT

    def _render_settling_tree(self, t_tree: "ttk.Treeview") -> None:
        """캐시된 Settling 목록에서 Blacklist 심볼을 제외하고 트리에 표시."""
        for row in t_tree.get_children():
            t_tree.delete(row)
        self._checked_settling.clear()

        # Blacklist에 없는 심볼만 표시
        visible = [
            e for e in self._settling_cache
            if _ctx._bl_mgr is None or not _ctx._bl_mgr.is_blacklisted(e.symbol)
        ]

        if visible:
            for idx, entry in enumerate(visible):
                parity = "odd" if idx % 2 == 0 else "even"
                tag = f"{entry.color_hint}_{parity}"
                chg_txt, _ = self._get_change_str(entry.symbol)
                t_tree.insert("", "end",
                               values=(str(idx + 1), "☐",
                                       entry.symbol, chg_txt, entry.label),
                               tags=(tag,))
        else:
            t_tree.insert("", "end",
                          values=("", "", "감지된 심볼 없음", "", ""),
                          tags=("dim_odd",))

    def _refresh_settling_ui(self) -> None:
        """캐시 기반으로 Settling 목록 즉시 갱신 (API 재조회 없음).
        Blacklist 추가/해제 후 호출 — 이미 등록된 심볼 제외 표시.
        """
        t_tree = getattr(self, "_t_tree", None)
        if t_tree is None:
            return
        self._render_settling_tree(t_tree)

    def _refresh_blacklist_ui(self) -> None:
        """Blacklist 하단 목록을 _ctx._bl_mgr 실데이터로 갱신."""
        b_tree = getattr(self, "_b_tree", None)
        if b_tree is None:
            return
        for row in b_tree.get_children():
            b_tree.delete(row)

        if _ctx._bl_mgr is None:
            return

        self._checked_blacklist.clear()   # 갱신 시 체크 초기화
        entries = _ctx._bl_mgr.get_all()
        for idx, entry in enumerate(entries):
            parity = "odd" if idx % 2 == 0 else "even"
            # settling.py _label() 매핑(SETTLING/HALT/EOD/DELISTING/DELISTED)
            # + 수동 추가(MANUAL) 전체 상태를 누락 없이 커버
            if entry.status in ("DELISTED", "DELISTING"):              color = "neg"
            elif entry.status in ("SETTLING", "HALT", "MANUAL", "EOD"): color = "ora"
            else:                                                       color = "dim"
            chg_txt, _ = self._get_change_str(entry.symbol)
            b_tree.insert("", "end",
                          values=(str(idx + 1), "☐", entry.symbol,
                                  chg_txt, entry.added_utc, entry.status),
                          tags=(f"{color}_{parity}",))

        # 헤더 카운트 업데이트
        count_lbl = getattr(self, "_bl_count_lbl", None)
        if count_lbl:
            n = len(entries)
            count_lbl.configure(text=f"Blacklist  ({n}개)" if n else "Blacklist")

    def _add_to_blacklist(self) -> None:
        """Settling Update에서 ☑ 체크된 심볼 일괄 Blacklist 추가.
        체크 없으면 현재 포커스 행 단일 추가.
        """
        t_tree = getattr(self, "_t_tree", None)
        if t_tree is None or _ctx._bl_mgr is None:
            return

        # ☑ 체크된 심볼 수집 (없으면 포커스 행 단일 추가)
        targets: list = []   # [(symbol, status), ...]

        if self._checked_settling:
            # 트리에서 체크된 심볼의 status 값 조회 (rank|check|symbol|change|status)
            for row_id in t_tree.get_children():
                vals = t_tree.item(row_id, "values")
                if vals and len(vals) >= 3 and vals[2] in self._checked_settling:
                    sym    = vals[2]
                    status = vals[4] if len(vals) > 4 else "SETTLING"
                    targets.append((sym, status))
        else:
            sel = t_tree.focus()
            if not sel:
                return
            vals = t_tree.item(sel, "values")
            if not vals or len(vals) < 3:
                return
            sym = vals[2]
            if not sym or sym == "데이터 로드 중...":
                return
            targets.append((sym, vals[4] if len(vals) > 4 else "SETTLING"))

        if not targets:
            return

        for sym, status in targets:
            _ctx._bl_mgr.add(sym, status=status, reason="Settling Update 자동 감지")

        self._refresh_settling_ui()    # Settling에서 추가된 심볼 즉시 제거
        self._refresh_blacklist_ui()   # Blacklist에 추가된 심볼 표시
        self._rebuild_ranking_rows()   # Ranking에서 즉시 제외

    def _release_from_blacklist(self) -> None:
        """Blacklist에서 ☑ 체크된 심볼 일괄 제거, Ranking에 복귀.
        체크 없으면 현재 포커스 행 단일 제거.
        """
        b_tree = getattr(self, "_b_tree", None)
        if b_tree is None or _ctx._bl_mgr is None:
            return

        targets: list = []   # 제거할 심볼 목록

        if self._checked_blacklist:
            targets = list(self._checked_blacklist)
        else:
            sel = b_tree.focus()
            if not sel:
                return
            vals = b_tree.item(sel, "values")
            if not vals or len(vals) < 3:
                return
            sym = vals[2]   # rank|check|symbol|added|status
            if sym:
                targets.append(sym)

        if not targets:
            return

        for sym in targets:
            _ctx._bl_mgr.remove(sym)

        self._refresh_settling_ui()    # Settling에 해제된 심볼 복귀 표시
        self._refresh_blacklist_ui()   # Blacklist에서 제거된 심볼 삭제
        self._rebuild_ranking_rows()   # Ranking에 즉시 복귀

    # ── 부드러운 스크롤 (Ease-Out 애니메이션) ────────────────────
    def _on_wheel_scroll(self, event: tk.Event) -> None:
        """마우스휠/트랙패드 → Ease-Out 애니메이션 스크롤.

        - yscrollincrement=38 덕분에 1 unit = 정확히 1행, 창 크기 무관
        - 트랙패드(delta < 120)도 비율대로 반응
        - 빠른 연속 스크롤 시 목표 누적 → 부드럽게 한번에 이동
        """
        cv = self._rank_cv
        if cv is None:
            return
        content_h = self._inner.winfo_height()
        view_h    = cv.winfo_height()
        if content_h < 10 or view_h < 10:   # 렌더링 전(0 또는 1) 방어
            return
        if content_h <= view_h:
            return

        # 3행 기준 이동량 (트랙패드는 delta가 작으므로 나눗셈으로 비율 유지)
        rows           = -(event.delta / 120.0) * 3
        delta_fraction = rows * 38 / content_h  # 38px = 행 높이

        # 애니메이션이 멈춰있으면 실제 위치로 목표 초기화 (드래그 후 휠 시 동기화)
        if not self._scroll_animating:
            try:
                pos = cv.yview()[0]
            except Exception:
                return
            self._scroll_target  = pos
            self._scroll_current = pos

        self._scroll_target = max(0.0, min(1.0,
                                           self._scroll_target + delta_fraction))

        if not self._scroll_animating:
            self._animate_scroll()

    def _animate_scroll(self) -> None:
        """Ease-Out 감속 애니메이션 — 16ms(~60fps)마다 호출."""
        cv = self._rank_cv
        if cv is None:
            self._scroll_animating = False
            return

        diff = self._scroll_target - self._scroll_current
        if abs(diff) < 0.00025:          # 충분히 가까우면 완료
            try:
                cv.yview_moveto(self._scroll_target)
            except Exception:
                pass
            self._scroll_animating = False
            return

        self._scroll_animating = True
        self._scroll_current  += diff * 0.28  # 28%씩 접근 = 자연스러운 감속
        try:
            cv.yview_moveto(self._scroll_current)
        except Exception:
            self._scroll_animating = False
            return

        self.after(16, self._animate_scroll)   # ~60 fps

    # ── PENDING_TRADING 전용 메서드 ──────────────────────────────

    def _load_pending_then_rebuild(self) -> None:
        """Pending Listing 모드 진입 시: 데이터 로드 → 재빌드 → 1분 타이머."""
        import threading
        def _load():
            self._load_pending_data()
            self.after(0, self._rebuild_ranking_rows)
        threading.Thread(target=_load, daemon=True).start()
        self._schedule_pending_refresh()

    def _load_pending_data(self) -> None:
        """PENDING_TRADING 심볼 캐시 구성 — PendingListingDetector 위임."""
        self._pending_cache.clear()
        self._pending_loaded = False
        if _ctx._data_mgr is None or not _HAS_BLACKLIST:
            return
        entries = _PendingListingDetector.detect(_ctx._data_mgr._client)
        self._pending_cache.extend(entries)
        self._pending_loaded = True

    def _get_type_badge(self, entry: "_PendingEntry") -> tuple:
        """유형 배지 텍스트·색상 — PendingListingDetector 위임."""
        return _PendingListingDetector.get_type_badge(entry)

    def _format_remaining(self, onboard_ms: int) -> tuple:
        """남은 시간 텍스트·색상 — PendingListingDetector 위임."""
        return _PendingListingDetector.format_remaining(onboard_ms)

    def _schedule_pending_refresh(self) -> None:
        """Pending 모드 진입 시 60초 타이머 예약 (즉시 rebuild 없음)."""
        self.after(60_000, self._do_pending_time_refresh)

    def _do_pending_time_refresh(self) -> None:
        """60초마다 남은시간 갱신 — Pending 모드일 때만 실행."""
        if self._sort_mode != "Pending Listing":
            return
        self._rebuild_ranking_rows()
        self.after(60_000, self._do_pending_time_refresh)

    def _build_pending_rows(self) -> None:
        """PENDING_TRADING 전용 행 생성 — 방안 C 레이아웃."""
        import datetime as _dt
        if not self._pending_cache:
            row = tk.Frame(self._inner, bg=DARK_ROW_ODD, pady=9)
            row.pack(fill="x")
            _loaded = getattr(self, "_pending_loaded", False)
            _msg = ("  현재 상장 예정 심볼(PENDING_TRADING)이 없습니다."
                    if _loaded else "  PENDING 데이터 로드 중...")
            tk.Label(row, text=_msg,
                     bg=DARK_ROW_ODD, fg=DIM_TEXT,
                     font=("Segoe UI", 9)).pack(side="left", padx=14)
            self._row_frames.append((row, ""))
            self._special[0] = set()
            return

        _, px0, _ = self._COLS[0]
        _, px1, _ = self._COLS[1]
        _, px2, _ = self._COLS[2]
        _, px3, _ = self._COLS[3]
        _, px4, _ = self._COLS[4]

        for idx, entry in enumerate(self._pending_cache):
            row_bg = DARK_ROW_ODD if idx % 2 == 0 else DARK_ROW_EVN
            sym        = entry.symbol
            onboard_ms = entry.onboard_date
            mark_price = entry.mark_price

            row = tk.Frame(self._inner, bg=row_bg, pady=9, highlightthickness=0)
            row.pack(fill="x")
            self._row_frames.append((row, sym))
            self._special[idx] = set()

            # ── Col 0: 순위 ────────────────────────────────
            rk_f = tk.Frame(row, bg=row_bg, width=px0)
            rk_f.pack(side="left", padx=(8, 1), fill="y")
            rk_f.pack_propagate(False)
            tk.Label(rk_f, text=str(idx + 1), bg=row_bg, fg=DIM_TEXT,
                     font=("Segoe UI", 9, "bold"), anchor="center").pack(fill="both", expand=True)

            # ── Col 1: 심볼 + 유형배지 ────────────────────
            sf = tk.Frame(row, bg=row_bg, width=px1)
            sf.pack(side="left", padx=1, fill="y")
            sf.pack_propagate(False)

            sym_lbl = tk.Label(sf, text=sym, bg=row_bg, fg=ACCENT_BLUE,
                               font=("Segoe UI", 9, "bold"), anchor="w",
                               cursor="hand2")
            sym_lbl.pack(side="left", padx=(2, 0), fill="y")
            sym_lbl.bind("<Button-1>",
                         lambda e, s=sym, i=idx, ba=entry.base_asset: [
                             self._on_select(s, i),
                             webbrowser.open(f"https://www.binance.com/en/price/{ba}") if ba else None,
                         ] and "break")   # Pending: Spot 코인 정보 페이지 (base_asset 기반)

            badge_txt, badge_col = self._get_type_badge(entry)
            badge_lbl = tk.Label(sf, text=badge_txt, bg=row_bg, fg=badge_col,
                                 font=("Segoe UI", 7, "bold"), anchor="w")
            badge_lbl.pack(side="left", padx=(4, 0))
            self._special[idx].add(badge_lbl)

            # ── Col 2: 상장예정일시 ────────────────────────
            dt_f = tk.Frame(row, bg=row_bg, width=px2)
            dt_f.pack(side="left", padx=1, fill="y")
            dt_f.pack_propagate(False)
            if onboard_ms:
                dt_obj = _dt.datetime.fromtimestamp(onboard_ms / 1000)
                dt_txt = dt_obj.strftime("%m/%d %H:%M")
            else:
                dt_txt = "—"
            tk.Label(dt_f, text=dt_txt, bg=row_bg, fg=DARK_TEXT,
                     font=("Consolas", 8), anchor="center").pack(fill="both", expand=True, padx=2)

            # ── Col 3: 남은시간 ────────────────────────────
            rem_f = tk.Frame(row, bg=row_bg, width=px3)
            rem_f.pack(side="left", padx=1, fill="y")
            rem_f.pack_propagate(False)
            rem_txt, rem_col = self._format_remaining(onboard_ms)
            rem_lbl = tk.Label(rem_f, text=rem_txt, bg=row_bg, fg=rem_col,
                               font=("Consolas", 8, "bold"), anchor="center")
            rem_lbl.pack(fill="both", expand=True, padx=2)
            self._special[idx].add(rem_lbl)

            # ── Col 4: markPrice ───────────────────────────
            mp_f = tk.Frame(row, bg=row_bg, width=px4)
            mp_f.pack(side="left", padx=1, fill="y")
            mp_f.pack_propagate(False)
            if mark_price >= 100:   mp_txt = f"{mark_price:.2f}"
            elif mark_price >= 1:   mp_txt = f"{mark_price:.4f}"
            elif mark_price > 0:    mp_txt = f"{mark_price:.6f}"
            else:                   mp_txt = "—"
            tk.Label(mp_f, text=mp_txt, bg=row_bg, fg=DARK_TEXT,
                     font=("Consolas", 9, "bold"), anchor="center").pack(fill="both", expand=True, padx=2)

            # ── Col 5: 빈칸 (expand) ───────────────────────
            ph_f = tk.Frame(row, bg=row_bg)
            ph_f.pack(side="left", padx=(4, 8), fill="x", expand=True)
            tk.Label(ph_f, text="", bg=row_bg).pack()

            # 클릭: 바이낸스 페이지 열기 (_on_select 경유로 처리됨)
            row.bind("<Button-1>",
                     lambda e, s=sym, i=idx: self._on_select(s, i))
            self._bind_row_children(row, sym, idx, skip={sym_lbl, badge_lbl})

    def _restore_row_highlight(self, sel_idx: int) -> None:
        """rebuild 완료 후 선택 행 하이라이트만 복원.

        _on_select와 달리 _do_refresh_immediate를 호출하지 않아
        30초마다 자동 rebuild 시 패널이 깜빡이지 않음.
        """
        self._sel_idx = sel_idx
        for update_idx, (frame, _sym) in enumerate(self._row_frames):
            if update_idx == sel_idx:
                try:
                    frame.configure(bg=DARK_SEL,
                                    highlightthickness=1,
                                    highlightbackground=SEL_BORDER)
                    self._recolor(frame, DARK_SEL,
                                  self._special.get(update_idx, set()))
                except Exception:
                    pass
            else:
                _p_entry = self._player_tags_map.get(_sym)
                row_bg = (GOLD_ROW_BG        if _sym == self._gold_sym                              else
                          PLAYER_SHORT_ROW_BG if _p_entry and _p_entry.get("direction") == "short"  else
                          PLAYER_MIX_ROW_BG   if _p_entry and _p_entry.get("direction") == "mixed"  else
                          PLAYER_ROW_BG       if _p_entry                                            else
                          DARK_ROW_ODD        if update_idx % 2 == 0                                 else
                          DARK_ROW_EVN)
                try:
                    frame.configure(bg=row_bg, highlightthickness=0)
                    self._recolor(frame, row_bg,
                                  self._special.get(update_idx, set()))
                except Exception:
                    pass

    def _bind_row_children(self, widget: tk.Widget, symbol: str, idx: int,
                           skip: set | None = None) -> None:
        """행의 모든 자식 위젯에 재귀적으로 Button-1 + MouseWheel 바인딩.

        Tkinter에서 자식 Widget 이벤트는 부모로 전파되지 않음.
        → Button-1:  모든 자식에 직접 바인딩 → _on_select 도달
        → MouseWheel: 모든 자식에 직접 바인딩 → _rank_cv 스크롤 도달
        skip 집합에 포함된 위젯은 건너뜀 (sym_lbl 등 특수 바인딩 유지).
        """
        if skip is None:
            skip = set()
        cv = getattr(self, "_rank_cv", None)
        for child in widget.winfo_children():
            if child in skip:
                continue
            try:
                child.bind("<Button-1>",
                           lambda e, s=symbol, i=idx: self._on_select(s, i))
                if cv is not None:
                    child.bind("<MouseWheel>", self._on_wheel_scroll)
            except Exception:
                pass
            self._bind_row_children(child, symbol, idx, skip)

    # ── 5초 ticker 갱신 → 랭킹 목록 경량 업데이트 ────────────────
    def _soft_update_ranking(self) -> None:
        """DataManager ticker 5초 갱신 완료 콜백 — 메인 스레드에 위임.

        행이 없으면(앱 시작 직후 ticker 미로드 상태) soft_update 대신
        즉시 rebuild → 코인 목록을 ~2초 만에 표시.
        Pending Listing 모드에서는 ticker 갱신 불필요이므로 스킵.
        """
        def _update():
            # IDLE 또는 ANALYSIS 상태에서는 1열 갱신 차단
            if getattr(self, '_app_state', 'IDLE') == "IDLE":
                return
            if getattr(self, '_analysis_mode', False):
                return
            if self._sort_mode == "Pending Listing":
                return   # 가격 데이터 없는 모드 — 소프트 갱신 불필요
            if not self._row_frames:
                # 앱 시작 직후 or 목록 비어있을 때 → 전체 rebuild로 즉시 표시
                self._rebuild_ranking_rows()
            else:
                self._do_soft_ranking_update()
        try:
            self.after(0, _update)
        except Exception:
            pass

    # ── STAGE3 완료 → TF합의·ATR%·EMA 즉시 랭킹 재빌드 ──────────
    def _on_klines_ready_col1(self) -> None:
        """STAGE3 완료 → 1열 랭킹 재빌드 (TF합의·ATR%·EMA 즉시 반영).
        MRO 충돌 방지를 위해 _on_klines_ready와 분리된 이름 사용.
        RANKING 상태에서만 실행 (ANALYSIS 중에는 1열 정지).
        """
        def _do_rebuild():
            try:
                if getattr(self, '_app_state', 'IDLE') != "RANKING":
                    return
                if not self._time_fixed:
                    self._rebuild_ranking_rows()
            except Exception:
                pass
        try:
            self.after(0, _do_rebuild)
        except Exception:
            pass

    def _do_soft_ranking_update(self) -> None:
        """메인 스레드에서 실행: 5초마다 Change%·장단계 숫자만 업데이트.

        Time Fix 활성 중: Change% 고정 유지 (덮어쓰지 않음), 장단계만 갱신
        Time Fix 비활성: Change% + 장단계 모두 갱신
        순위(코인 위치)는 절대 변경하지 않음 → 사용자가 안정적으로 클릭 가능.
        순위 재정렬은 30초마다 _tick_timer()에서 별도 실행.
        """
        try:
            new_data = self._get_sorted_ranking()
            cur_sym_set = {sym for _, sym in self._row_frames}

            for row_data in new_data:
                sym         = row_data[0]
                new_chg     = row_data[4]   # Change% 텍스트
                new_chg_col = row_data[5]   # Change% 색상
                new_phase   = row_data[8]   # 장단계 텍스트
                new_ph_col  = row_data[9]   # 장단계 색상

                if sym not in cur_sym_set:
                    continue

                # ── Bug1 Fix: Time Fix 비활성 시에만 Change% 업데이트 ───────
                # Time Fix 활성 중: Change%는 클릭 시점 값으로 고정 유지
                if not self._time_fixed:
                    chg_lbl = self._change_labels.get(sym)
                    if chg_lbl:
                        try:
                            chg_lbl.configure(text=new_chg, fg=new_chg_col)
                        except Exception:
                            pass

                # ── 장단계 라벨 업데이트 (전 모드, Time Fix와 무관) ──────────
                # 장단계는 EMA/24h 기반 추세 표시로 Time Fix와 독립적
                # Player Detection 행은 Col5에 태그 텍스트 표시 중 → 장단계 덮어쓰기 금지
                # (Sharp rise/decline·Newly Listed·Volatility·4TF 모드는 Player 행도 장단계 갱신 대상)
                if (sym in self._player_tags_map and
                        self._sort_mode not in ("Sharp rise", "Sharp decline",
                                                "Newly Listed", "Volatility",
                                                "4TF Optimization")):
                    continue
                ph_pair = self._phase_labels.get(sym)
                if ph_pair:
                    ph_f, ph_lbl = ph_pair
                    ph_bg = "#0F1F0F" if new_phase.startswith("◀") else (
                            "#1F0F0F" if new_phase.startswith("▶") else
                            ph_f.cget("bg"))
                    try:
                        ph_f.configure(bg=ph_bg)
                        ph_lbl.configure(text=new_phase, fg=new_ph_col, bg=ph_bg)
                    except Exception:
                        pass
        except Exception:
            pass
