"""
middle/widget/panel_col1_blacklist.py
1열 2탭 Blacklist 믹스인 — Settling Update(exchangeInfo 비정상 상태) 목록 + 블랙리스트 등록·해제.
블랙리스트 저장소는 middle/data/blacklist.py(_ctx._bl_mgr) — 하단 엔진 신규 진입 차단과 같은 원본.
"""
from __future__ import annotations
import logging
import threading
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox
from middle.widget.constants import *

import middle.widget.shared_context as _ctx
from middle.data.settling import SettlingDetector as _SettlingDetector


class _Col1BlacklistMixin:
    """1열 2탭 Blacklist 믹스인."""

    # Settling 자동 감지·거래 재개 자동 해제 주기 — TRADING 심볼 캐시(binance_client, 5분)와 같은 주기 (2026-11-22 사용자 결정)
    _SETTLING_REFRESH_MS = 300_000

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
        t_tree.bind("<Double-1>", lambda e, t=t_tree: self._open_settling_symbol(t))

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
        컬럼 구조: 1=#(순번) | 2=☐/☑(체크) | 3~=데이터 (Settling 3~5 · Blacklist 3~6)
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
        # 안내 행 제외 — 데이터 행은 순번 칸(vals[0])이 항상 str(idx+1), 안내 행("Settling 조회 중..."·
        # "Settling 조회 실패 …"·"감지된 심볼 없음")은 빈 문자열 (B-1, 2026-11-18 — 기존 가드는 옛 문구
        # "데이터 로드 중..."만 비교해 안내 문구가 체크·등록되던 문제). Settling·Blacklist 두 트리 공용 판정.
        if not sym or not vals[0]:
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
        """Settling Update: Binance exchangeInfo 기반 비정상 심볼 — Blacklist 탭 첫 표시 때 호출.
        5분 캐시(cached_exchange_info)가 있으면 그것으로 즉시 표시(추가 요청 없음), 아직 없으면(앱 시작 직후)
        백그라운드 조회 후 메인 스레드에서 표시 (exchangeInfo 약 1.2MB 동기 조회로 화면이 멈추던 문제 방지).
        이후 갱신은 _auto_settling_refresh (5분 주기)."""
        t_tree = getattr(self, "_t_tree", None)
        if t_tree is None:
            return
        info = _ctx._data_mgr.cached_exchange_info() if _ctx._data_mgr is not None else None
        if info:
            self._apply_exchange_info(info)   # 5분 캐시 재사용 — 추가 요청 없음 (2026-11-22 3번)
            return
        self._settling_cache  = []
        self._settling_status = "loading"
        self._render_settling_tree(t_tree)

        def _load():
            entries = None   # None = 조회 실패 ('감지된 심볼 없음'과 구분)
            if _ctx._data_mgr is not None:
                try:
                    info = _ctx._data_mgr.fetch_exchange_info()
                    if info:
                        entries = _SettlingDetector.detect(info)
                except Exception as e:
                    logging.warning("Blacklist Settling 조회 실패: %s", e)   # 원인 기록 (2026-11-22)
                    entries = None
            self._post(self._apply_settling_data, entries)   # 작업 스레드는 Tk 미호출 (MiddlePanel._post)
        threading.Thread(target=_load, daemon=True).start()

    def _apply_settling_data(self, entries: "list | None") -> None:
        """메인 스레드: 조회 결과 캐시 저장(Blacklist 추가/해제 시 재조회 없이 갱신) 후 표시."""
        self._settling_cache  = entries or []
        self._settling_status = "failed" if entries is None else "ok"
        t_tree = getattr(self, "_t_tree", None)
        if t_tree is not None:
            self._render_settling_tree(t_tree)

    def _auto_settling_refresh(self) -> None:
        """5분마다(앱 시작부터 — Blacklist 탭을 열지 않아도) TRADING 심볼 캐시의 exchangeInfo로
        Settling 목록 갱신(3번 '● 자동 감지') + 거래 재개 종목 자동 해제(2번). 새 조회 요청은 하지 않는다 (2026-11-22)."""
        try:
            info = _ctx._data_mgr.cached_exchange_info() if _ctx._data_mgr is not None else None
            if info:
                self._apply_exchange_info(info)
        except Exception as e:
            logging.warning("Blacklist Settling 자동 감지 실패: %s", e)
        try:
            self.after(self._SETTLING_REFRESH_MS, self._auto_settling_refresh)
        except tk.TclError:
            pass   # 앱 종료 중

    def _apply_exchange_info(self, info: dict) -> None:
        """메인 스레드: exchangeInfo로 Settling 목록 갱신 + 거래 재개 종목 자동 해제.
        목록이 바뀌었거나 트리를 아직 그리지 않은 경우에만 그리고, 다시 그려도 사용자가 ☑ 체크해 둔 심볼(목록에 남은 것)은 유지."""
        entries = _SettlingDetector.detect(info)
        changed = (getattr(self, "_settling_status", "") != "ok"
                   or [(e.symbol, e.status) for e in entries]
                   != [(e.symbol, e.status) for e in self._settling_cache])
        self._settling_cache, self._settling_status = entries, "ok"
        released = self._release_resumed_symbols(info)
        t_tree = getattr(self, "_t_tree", None)
        # not get_children() = 아직 한 번도 그리지 않은 트리 (_render_settling_tree는 항목이 없어도 안내 행 1줄을 넣으므로
        # 0행은 '미렌더'와 같음). 탭을 열기 전에 5분 자동 감지가 먼저 돌면 상태 "ok"·캐시 동일로 changed=False가 되어
        # 탭 첫 표시가 빈 화면이던 문제 (N-1, 2026-11-22)
        if t_tree is not None and (changed or released or not t_tree.get_children()):
            keep = set(self._checked_settling)
            self._render_settling_tree(t_tree)          # 체크 집합 초기화 후 다시 그림
            for row_id in t_tree.get_children():
                vals = list(t_tree.item(row_id, "values"))
                if vals and vals[0] and vals[2] in keep:
                    self._checked_settling.add(vals[2])
                    vals[1] = "☑"
                    t_tree.item(row_id, values=vals)
        if released:
            self._refresh_blacklist_ui()
            self._refresh_ranking_if_affected(released, added=False)   # 해제된 심볼 Ranking 복귀 (수동 Release와 같음)

    def _refresh_ranking_if_affected(self, symbols: list, added: bool) -> None:
        """블랙리스트 변경이 1열 목록을 바꿀 때만 Time Fix 해제·1열 재생성 (2026-11-22 — Settling 종목은 거래 중이
        아니라 1열에 없어 등록·해제해도 목록이 그대로인데 Time Fix가 풀리고 재생성되던 문제).
        등록(added): 지금 1열에 표시된 심볼이 있을 때 · 해제: 시세가 있는(거래 중) 심볼이 있을 때 — 1열은 거래 중 심볼만 표시."""
        if added:
            shown = {s for _, s in self._row_frames}
            hit = any(s in shown for s in symbols)
        else:
            hit = _ctx._data_mgr is not None and any(_ctx._data_mgr.get_ticker(s) is not None for s in symbols)
        if hit:
            self._release_time_fix_for_rebuild()   # 재생성이 고정 순위를 깨므로 Time Fix 자동 해제
            self._rebuild_ranking_rows()

    def _release_resumed_symbols(self, info: dict) -> list:
        """거래 재개(exchangeInfo status TRADING) 심볼을 블랙리스트에서 자동 해제 — 반환: 해제한 심볼 목록.
        사용자가 직접 등록한 MANUAL 항목은 자동 해제하지 않는다 (2026-11-22 사용자 결정 2번).
        exchangeInfo에 없는 심볼(상장폐지 완료)은 TRADING이 아니므로 그대로 유지."""
        if _ctx._bl_mgr is None:
            return []
        status = {s.get("symbol"): s.get("status") for s in info.get("symbols", [])}
        released = [e.symbol for e in _ctx._bl_mgr.get_all()
                    if e.status != "MANUAL" and status.get(e.symbol) == "TRADING"]
        for sym in released:
            _ctx._bl_mgr.remove(sym)
        if released:
            logging.warning("Blacklist 자동 해제 (거래 재개): %s", ", ".join(released))
        return released

    def _open_settling_symbol(self, t_tree: "ttk.Treeview") -> None:
        """Settling 행 더블클릭 → 바이낸스 선물 페이지. 값 (번호, 체크, 심볼, 등락, 상태) 중 심볼 칸,
        목록 심볼일 때만 (안내 행 "감지된 심볼 없음" 제외)."""
        focus = t_tree.focus()
        if not focus:
            return
        sym = t_tree.item(focus, "values")[2]
        if any(e.symbol == sym for e in self._settling_cache):
            self._open_binance(sym)

    def _get_change_str(self, symbol: str) -> tuple:
        """심볼의 현재 Change% 문자열과 색상 반환.
        DataManager tkr_map에서 실시간 조회. 시세 없으면 '—' 반환
        (실제 0.00%는 '+0.00%' — 2026-11-22: 0.00%를 시세 없음 '—'로 표시하던 문제).
        """
        if _ctx._data_mgr is not None:
            tkr = _ctx._data_mgr.get_ticker(symbol)
            if tkr:
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
            _msg = {"loading": "Settling 조회 중...",
                    "failed":  "Settling 조회 실패 — 앱 재시작 시 다시 조회"}.get(
                        getattr(self, "_settling_status", "ok"), "감지된 심볼 없음")
            t_tree.insert("", "end",
                          values=("", "", _msg, "", ""),
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
        """Settling Update에서 ☑ 체크된 심볼만 일괄 Blacklist 추가 — 체크가 없으면 등록 없이 안내만 표시(N-2).
        (UI-2, 2026-11-18 — 체크 없을 때 포커스 행을 대신 추가하던 동작 삭제: 체크 칸 클릭도 포커스를 남겨
        ☑ 후 ☐로 해제한 행이 그대로 추가되던 문제. 화면의 ☑ = 실제 처리 대상)
        엔진 배정 종목은 제외하고 안내 표시 (②, 2026-11-22).
        """
        t_tree = getattr(self, "_t_tree", None)
        if t_tree is None or _ctx._bl_mgr is None:
            return

        # ☑ 체크된 데이터 행의 심볼·status 수집 (rank|check|symbol|change|status) — 안내 행(순번 칸 빈 문자열) 제외 (B-1)
        targets: list = []   # [(symbol, status), ...]
        for row_id in t_tree.get_children():
            vals = t_tree.item(row_id, "values")
            if vals and len(vals) >= 3 and vals[0] and vals[2] in self._checked_settling:
                sym    = vals[2]
                status = vals[4] if len(vals) > 4 else "SETTLING"
                targets.append((sym, status))

        if not targets:   # 체크 없음 — 무반응 대신 안내 (N-2, 2026-11-22)
            self._set_header_message("⛔ 체크한 심볼이 없습니다 — Settling Update 목록의 ☐ 칸을 클릭해 선택한 뒤 Add")
            return

        # 엔진 배정 종목은 등록하지 않는다 (2026-11-22 ② — 블랙리스트 종목은 랭킹 제외·Assign 차단이라
        # 엔진이 블랙리스트 종목을 갖는 유일한 경로가 '배정 후 등록'이었음. 이 경로를 막아 엔진 블랙리스트
        # 분기는 안전망으로만 남김). 거래 정지 → 배정 해제 후 등록.
        assigned = getattr(self, "_assigned_sym", None)
        if assigned and any(sym == assigned for sym, _ in targets):
            targets = [(sym, status) for sym, status in targets if sym != assigned]
            self._set_header_message(
                f"⛔ {assigned} — 엔진 배정 종목은 블랙리스트에 등록할 수 없습니다 (배정 해제 후 등록)")

        if not targets:
            return

        for sym, status in targets:
            _ctx._bl_mgr.add(sym, status=status, reason="Settling Update 자동 감지")

        self._refresh_settling_ui()    # Settling에서 추가된 심볼 즉시 제거
        self._refresh_blacklist_ui()   # Blacklist에 추가된 심볼 표시
        self._refresh_ranking_if_affected([sym for sym, _ in targets], added=True)   # 1열에 있던 심볼이면 즉시 제외

    def _release_from_blacklist(self) -> None:
        """Blacklist에서 ☑ 체크된 심볼만 일괄 제거, Ranking에 복귀 — 체크가 없으면 해제 없이 안내만 표시(N-2).
        (UI-2, 2026-11-18 — 체크 없을 때 포커스 행을 대신 해제하던 동작 삭제: ☑ 후 ☐로 해제한 행이
        블랙리스트에서 풀려 엔진 진입이 다시 가능해지던 문제)
        """
        b_tree = getattr(self, "_b_tree", None)
        if b_tree is None or _ctx._bl_mgr is None:
            return

        targets: list = list(self._checked_blacklist)   # 제거할 심볼 목록 (체크된 것만)

        if not targets:   # 체크 없음 — 무반응 대신 안내 (N-2, 2026-11-22)
            self._set_header_message("⛔ 체크한 심볼이 없습니다 — Blacklist 목록의 ☐ 칸을 클릭해 선택한 뒤 Release")
            return

        for sym in targets:
            _ctx._bl_mgr.remove(sym)

        self._refresh_settling_ui()    # Settling에 해제된 심볼 복귀 표시
        self._refresh_blacklist_ui()   # Blacklist에서 제거된 심볼 삭제
        self._refresh_ranking_if_affected(targets, added=False)   # 거래 중 심볼이면 Ranking에 즉시 복귀

    def _blacklist_selected_symbol(self, symbol: str) -> None:
        """3열 분석 중인 종목을 블랙리스트에 직접 등록 (2026-11-22 사용자 결정 1번 — 기존 등록 경로는 Settling 감지 종목뿐).
        확인 창 → MANUAL 등록(거래 재개 자동 해제 대상 아님) → Blacklist 탭 갱신 → 분석 자동 종료('가')·1열에서 즉시 제외.
        엔진 배정 종목은 등록하지 않는다 (②)."""
        if _ctx._bl_mgr is None:
            self._set_header_message(f"⛔ {symbol} — 블랙리스트 미로드 상태라 등록할 수 없습니다")
            return
        if self._assigned_sym == symbol:
            self._set_header_message(
                f"⛔ {symbol} — 엔진 배정 종목은 블랙리스트에 등록할 수 없습니다 (배정 해제 후 등록)")
            return
        if _ctx._bl_mgr.is_blacklisted(symbol):   # 기존 항목의 상태·등록 시각을 MANUAL로 덮어쓰지 않음
            self._set_header_message(f"⛔ {symbol} — 이미 블랙리스트에 등록된 심볼입니다")
            return
        if not messagebox.askyesno(
                "블랙리스트 등록",
                f"{symbol} 을(를) 블랙리스트에 등록할까요?\n\n"
                f"1열 랭킹에서 제외되고 엔진 신규 진입이 차단됩니다.\n"
                f"(해제: 1열 Blacklist 탭에서 ☑ 체크 후 Release)",
                parent=self):
            return
        _ctx._bl_mgr.add(symbol, status="MANUAL", reason="사용자 직접 등록")
        self._refresh_settling_ui()    # Settling 목록에 있던 심볼이면 제거
        self._refresh_blacklist_ui()   # Blacklist 목록·개수 갱신
        if self._app_state == "ANALYSIS":
            self.on_clear_analysis()   # '가': 분석 자동 종료 — Time Fix 해제·1열 재생성 포함 (3열에 블랙리스트 종목이 남지 않음)
        else:
            self._refresh_ranking_if_affected([symbol], added=True)
