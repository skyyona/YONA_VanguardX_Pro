"""
middle/widget/panel_col1_blacklist.py
1열 2탭 Blacklist 믹스인 — Settling Update(exchangeInfo 비정상 상태) 목록 + 블랙리스트 등록·해제.
블랙리스트 저장소는 middle/data/blacklist.py(_ctx._bl_mgr) — 하단 엔진 신규 진입 차단과 같은 원본.
"""
from __future__ import annotations
import tkinter as tk
import tkinter.ttk as ttk
from middle.widget.constants import *

import middle.widget.shared_context as _ctx
from middle.data.settling import SettlingDetector as _SettlingDetector


class _Col1BlacklistMixin:
    """1열 2탭 Blacklist 믹스인."""

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
        if _ctx._data_mgr is not None:
            try:
                info = _ctx._data_mgr.fetch_exchange_info()
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
            tkr = _ctx._data_mgr.get_ticker(symbol)
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
