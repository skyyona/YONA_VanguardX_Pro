"""
middle/widget/panel_col2.py
2열 차트 (Coin Chart / MTF Stoch RSI / Macro & 4TF Entry) 믹스인
"""
from __future__ import annotations
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import font as tkfont
from middle.widget.constants import *

# ── shared_context에서 헬퍼 함수 import (단일 정의, 중복 없음) ──
from middle.widget.shared_context import get_ind, generate_ohlcv
import middle.widget.shared_context as _ctx


try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.font_manager as _fm
    _KR_FONTS = ["Malgun Gothic", "NanumGothic", "AppleGothic", "Noto Sans CJK KR"]
    _available = {f.name for f in _fm.fontManager.ttflist}
    for _kf in _KR_FONTS:
        if _kf in _available:
            matplotlib.rcParams["font.family"] = _kf
            break
    matplotlib.rcParams["axes.unicode_minus"] = False
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.patches as mptch
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    Figure = None
    FigureCanvasTkAgg = None
    mptch = None


# 2열 계산 전담 모듈
from middle.col2_chart_indicators.coin_chart import CoinChart
from middle.col2_chart_indicators.macro_4tf_entry import MacroFourTFEntry


class _Col2Mixin:
    """2열 차트 믹스인."""

    # matplotlib Figure 재사용용 인스턴스 변수 (초기화)
    _mpl_fig = None   # Figure 객체 (재사용)
    _mpl_ax  = None   # Axes 객체 (재사용)

    # ─── 분봉 버튼 갱신 (Trend 방향 + 색상 통합) ─────────────
    _TF_MAP = [
        ("1분봉",   "tf1"),
        ("3분봉",   "tf3"),
        ("5분봉",   "tf5"),
        ("15분봉",  "tf15"),
        ("1시간봉", "tf1h"),
        ("4시간봉", "tf4h"),
        ("1일봉",   "tf1d"),
    ]

    # TF 레이블 → Binance interval 변환 (generate_ohlcv interval 파라미터용)
    _TF_LABEL_TO_INTERVAL = {
        "1분봉":   "1m",
        "3분봉":   "3m",
        "5분봉":   "5m",
        "15분봉":  "15m",
        "1시간봉": "1h",
        "4시간봉": "4h",
        "1일봉":   "1d",
    }

    def _refresh_tf_buttons(self) -> None:
        for w in self._tf_bar.winfo_children():
            w.destroy()

        sym = self._sel_var.get()
        ind = get_ind(sym)

        for tf_label, tf_key in self._TF_MAP:
            tf_d   = ind.get(tf_key, {})          # KeyError 방지
            arrow  = tf_d.get("dir", "↔")
            col    = tf_d.get("col", DIM_TEXT)
            btn_text = f" {tf_label}{arrow} "
            tk.Radiobutton(
                self._tf_bar,
                text=btn_text,
                variable=self._tf_var, value=tf_label,
                bg="#161616", fg=col,
                activebackground="#1A1A1A", activeforeground=col,
                selectcolor="#252525", indicatoron=False,
                font=("Segoe UI", 8, "bold"), padx=4, pady=4,
                relief="flat",
                command=self._refresh_chart,
            ).pack(side="left", expand=True, fill="x", padx=1)

    # ─── Coin Chart / MTF Stoch RSI / Macro & 4TF Entry 탭 전환 ──
    def _switch_chart_tab(self, tab: str) -> None:
        self._cur_chart_tab = tab
        # 모든 콘텐츠 숨김
        self._tf_bar.pack_forget()
        self._chart_f.pack_forget()
        self._mtf_f.pack_forget()
        self._macro_f.pack_forget()
        # 모든 버튼 비활성
        self._chart_tab_btn.configure(bg=DARK_BG, fg=DIM_TEXT)
        self._mtf_tab_btn.configure(bg=DARK_BG, fg=DIM_TEXT)
        self._macro_tab_btn.configure(bg=DARK_BG, fg=DIM_TEXT)

        if tab == "chart":
            self._tf_bar.pack(fill="x")
            self._chart_f.pack(fill="both", expand=True)
            self._chart_tab_btn.configure(bg=DARK_PANEL, fg=ACCENT_BLUE)
        elif tab == "mtf":
            self._mtf_f.pack(fill="both", expand=True)
            self._mtf_tab_btn.configure(bg=DARK_PANEL, fg=ACCENT_BLUE)
            self._refresh_mtf()
        elif tab == "macro":
            self._macro_f.pack(fill="both", expand=True)
            self._macro_tab_btn.configure(bg=DARK_PANEL, fg=ACCENT_BLUE)
            self._refresh_macro()

    # ─── MTF StochRSI 패널 갱신 ─────────────────────────────
    def _refresh_mtf(self) -> None:
        for w in self._mtf_f.winfo_children():
            w.destroy()
        sym = self._sel_var.get()
        if not sym:
            return
        self._build_mtf_panel(sym)

    def _build_mtf_panel(self, sym: str) -> None:
        ind = get_ind(sym)

        TF_ROWS = [
            (" 1M", "tf1"),
            (" 3M", "tf3"), (" 5M", "tf5"), ("15M", "tf15"),
            (" 1H", "tf1h"), (" 4H", "tf4h"), (" 1D", "tf1d"),
        ]

        # ── 헬퍼: 신호 계산 ──────────────────────────────────
        def _signal(k, d):
            diff = k - d
            if diff > 2:
                if k > 80:  return +1, "과매수 진입 ⚠️",       ORANGE
                if k < 20:  return +2, "과매도 골든크로스 !!",  POSITIVE
                return           +1, "골든크로스",             "#8ad7b5"
            if diff < -2:
                if k > 80:  return -2, "과매수 데드크로스 !!", NEGATIVE
                if k < 20:  return -1, "과매도 데드크로스",    NEGATIVE
                return           -1, "데드크로스",             ORANGE
            if diff >  0.5: return 0, "교차 수렴 중 ↓",        YELLOW
            if diff < -0.5: return 0, "교차 수렴 중 ↑",        YELLOW
            return               0, "교차 대기",               YELLOW

        # ── 헬퍼: elapsed → 신선도 가중치 ────────────────────
        def _weight(elapsed):
            if not elapsed:                    return 0.3
            if elapsed == "방금":              return 1.0
            if "분 전" in elapsed:
                try:
                    m = int(elapsed.split("분")[0].strip())
                    return 1.0 if m <= 30 else 0.7
                except: return 0.7
            if "시간 전" in elapsed:
                try:
                    h = int(elapsed.split("시간")[0].strip())
                    if h <= 2: return 0.7
                    if h <= 6: return 0.4
                    return 0.2
                except: return 0.3
            if "일 전" in elapsed:             return 0.15
            return 0.5

        # ── 헬퍼: 시간 표기 색상 ─────────────────────────────
        def _time_col(elapsed, sig_col):
            if elapsed:
                if elapsed == "방금":          return sig_col
                if "분 전" in elapsed:
                    try:
                        if int(elapsed.split("분")[0].strip()) <= 30:
                            return sig_col
                    except: pass
                    return "#8ad7b5" if sig_col in (POSITIVE, "#8ad7b5") else ORANGE
                if "시간 전" in elapsed:
                    try:
                        if int(elapsed.split("시간")[0].strip()) <= 3:
                            return "#8ad7b5" if sig_col in (POSITIVE,"#8ad7b5") else ORANGE
                    except: pass
                    return DIM_TEXT
                return DIM_TEXT
            return DIM_TEXT

        # ── TF 행 구축 ───────────────────────────────────────
        rows_f = tk.Frame(self._mtf_f, bg=DARK_BG)
        rows_f.pack(fill="x", pady=(2, 0))

        w_scores, r_scores, fresh_count, div_tfs = [], [], 0, []

        for i, (tf_label, tf_key) in enumerate(TF_ROWS):
            tf_d    = ind.get(tf_key, {})           # KeyError 방지
            k       = tf_d.get("k", 50.0)
            dv      = tf_d.get("d", 50.0)
            col     = tf_d.get("col", DIM_TEXT)
            elapsed = tf_d.get("elapsed")
            div     = tf_d.get("div")

            score, sig_text, sig_col = _signal(k, dv)
            w_scores.append(score * _weight(elapsed))
            r_scores.append(score)
            if elapsed and ("분 전" in elapsed or elapsed == "방금"):
                fresh_count += 1
            if div:
                div_tfs.append((tf_label.strip(), div))

            time_text = elapsed or "—"
            t_col     = _time_col(elapsed, sig_col)
            row_bg    = DARK_ROW_ODD if i % 2 == 0 else DARK_ROW_EVN

            # ── TF 컨테이너 ──────────────────────────────────
            tf_box = tk.Frame(rows_f, bg=row_bg)
            tf_box.pack(fill="x")

            # ── 1행: TF 라벨 · 점수 · 방향 · K · D · 바 ──────
            r1 = tk.Frame(tf_box, bg=row_bg, pady=4)
            r1.pack(fill="x")

            tk.Label(r1, text=tf_label, bg=row_bg, fg=DARK_TEXT,
                     font=("Consolas", 9, "bold"), width=4, anchor="e").pack(side="left", padx=(8, 3))
            sc_txt = f"[{score:+d}]" if score != 0 else "[ 0]"
            sc_col = POSITIVE if score > 0 else (NEGATIVE if score < 0 else YELLOW)
            tk.Label(r1, text=sc_txt, bg=row_bg, fg=sc_col,
                     font=("Consolas", 9, "bold"), width=4).pack(side="left", padx=(0, 3))
            tk.Label(r1, text=tf_d.get("dir", "↔"), bg=row_bg, fg=col,
                     font=("Segoe UI", 9, "bold"), width=2).pack(side="left")
            tk.Label(r1, text=f"K:{k:5.1f}", bg=row_bg, fg=col,
                     font=("Consolas", 8), width=7).pack(side="left", padx=(3, 0))
            tk.Label(r1, text=f"D:{dv:5.1f}", bg=row_bg, fg=DIM_TEXT,
                     font=("Consolas", 8), width=7).pack(side="left", padx=(1, 3))

            bar_cv = tk.Canvas(r1, bg="#1A1A1A", height=10, highlightthickness=0)
            bar_cv.pack(side="left", fill="x", expand=True, padx=(0, 6))
            def _draw(e=None, cv=bar_cv, kv=k, fc=col):
                cv.delete("all")
                w = cv.winfo_width() or 70
                os_x, ob_x = int(w * 0.20), int(w * 0.80)
                cv.create_rectangle(0, 1, os_x, 9, fill="#1C2A1C", outline="")
                cv.create_rectangle(ob_x, 1, w, 9, fill="#2A1C1C", outline="")
                cv.create_rectangle(os_x, 1, ob_x, 9, fill="#1E1E1E", outline="")
                cv.create_rectangle(0, 1, int(w * kv / 100), 9, fill=fc, outline="")
                cv.create_line(os_x, 0, os_x, 10, fill="#3A5A3A", width=1)
                cv.create_line(ob_x, 0, ob_x, 10, fill="#5A3A3A", width=1)
            bar_cv.bind("<Configure>", _draw)
            bar_cv.after(20, _draw)

            # ── 2행: 신호명 + 시간 [+ 다이버전스 태그] ──────────
            r2 = tk.Frame(tf_box, bg=row_bg, pady=2)
            r2.pack(fill="x")

            tk.Label(r2, text=time_text, bg=row_bg, fg=t_col,
                     font=("Consolas", 8)).pack(side="right", padx=(0, 8))
            if div == "bull":
                tk.Label(r2, text="⚡ 상승 다이버전스", bg=row_bg, fg=POSITIVE,
                         font=("Segoe UI", 7, "bold")).pack(side="right", padx=(0, 6))
            elif div == "bear":
                tk.Label(r2, text="⚠️ 하락 다이버전스", bg=row_bg, fg=ORANGE,
                         font=("Segoe UI", 7, "bold")).pack(side="right", padx=(0, 6))
            tk.Label(r2, text=sig_text, bg=row_bg, fg=sig_col,
                     font=("Segoe UI", 8, "bold"), anchor="w").pack(
                         side="left", padx=(42, 0))

            tk.Frame(tf_box, bg="#222222", height=1).pack(fill="x")

        # ── 다이버전스 요약 (감지된 경우만) ─────────────────────
        if div_tfs:
            tk.Frame(self._mtf_f, bg="#2A2A2A", height=1).pack(fill="x", pady=(3, 0))
            div_f = tk.Frame(self._mtf_f, bg=DARK_PANEL, pady=4)
            div_f.pack(fill="x")
            for tf_lbl, dtype in div_tfs:
                dr = tk.Frame(div_f, bg=DARK_PANEL)
                dr.pack(fill="x", padx=10, pady=1)
                if dtype == "bull":
                    tk.Label(dr, text="⚡ 상승 다이버전스", bg=DARK_PANEL, fg=POSITIVE,
                             font=("Segoe UI", 8, "bold")).pack(side="left")
                    tk.Label(dr, text=f"  [{tf_lbl}]  가격↓ + StochRSI↑ → 반등 가능",
                             bg=DARK_PANEL, fg=DIM_TEXT,
                             font=("Segoe UI", 7)).pack(side="left")
                else:
                    tk.Label(dr, text="⚠️ 하락 다이버전스", bg=DARK_PANEL, fg=ORANGE,
                             font=("Segoe UI", 8, "bold")).pack(side="left")
                    tk.Label(dr, text=f"  [{tf_lbl}]  가격↑ + StochRSI↓ → 고점 경고",
                             bg=DARK_PANEL, fg=DIM_TEXT,
                             font=("Segoe UI", 7)).pack(side="left")

        # 종합 요약 → 🎯 Macro & 4TF Entry 탭으로 이동됨

    # ─── Macro & 4TF Entry 패널 갱신 ─────────────────────────
    def _refresh_macro(self) -> None:
        for w in self._macro_f.winfo_children():
            w.destroy()
        sym = self._sel_var.get()
        if sym:
            self._build_macro_panel(sym)

    def _build_macro_panel(self, sym: str) -> None:  # noqa: C901
        ind = get_ind(sym)
        bpr = ind.get("bpr", 0.5)
        vss = ind.get("vss", 1.0)

        f = self._macro_f

        # ── 계산 전담: MacroFourTFEntry ──────────────────────────
        result = MacroFourTFEntry.analyze_from_ind(ind, bpr, vss)
        mt     = result.macro_trend
        fa     = result.fourtf_align
        sq     = result.signal_quality

        # ── Section 1: MACRO TREND ──────────────────────────────
        hdr1 = tk.Frame(f, bg=DARK_HEADER, pady=6)
        hdr1.pack(fill="x")
        tk.Label(hdr1, text="MACRO TREND", bg=DARK_HEADER, fg=ACCENT_BLUE,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=10)
        tk.Frame(f, bg="#333333", height=1).pack(fill="x")

        gf = tk.Frame(f, bg=DARK_BG, pady=6)
        gf.pack(fill="x", padx=10)
        g_cv = tk.Canvas(gf, bg="#1A1A1A", height=18, highlightthickness=0)
        g_cv.pack(fill="x", expand=True)
        _gauge_font = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        def _gauge(e=None, cv=g_cv, signed=mt.score, c=mt.color, label=mt.signal):
            cv.delete("all"); w = cv.winfo_width() or 100
            label_w = _gauge_font.measure(label) + 12
            bar_w = max(0, w - label_w)
            mid = bar_w // 2
            cv.create_rectangle(0, 2, bar_w, 16, fill="#252525", outline="")
            filled = int(abs(signed) * mid)
            if signed >= 0:
                cv.create_rectangle(mid, 3, mid + filled, 15, fill=c, outline="")
            else:
                cv.create_rectangle(mid - filled, 3, mid, 15, fill=c, outline="")
            cv.create_line(mid, 1, mid, 17, fill=DIM_TEXT, width=1)
            cv.create_text(w - 6, 9, text=label, fill=c, anchor="e", font=_gauge_font)
        g_cv.bind("<Configure>", _gauge); g_cv.after(15, _gauge)

        ic_f = tk.Frame(f, bg=DARK_BG, pady=3)
        ic_f.pack(fill="x", padx=14)
        for tf_name, lbl in (("1h", "1H"), ("4h", "4H"), ("1d", "1D")):
            dr = mt.directions.get(tf_name, "↔")
            c  = POSITIVE if dr == "▲" else (NEGATIVE if dr == "▼" else DIM_TEXT)
            tk.Label(ic_f, text=f"{lbl} {dr}", bg=DARK_BG, fg=c,
                     font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 20))

        # ── Section 2: 4TF COMPLETE ALIGNMENT ───────────────────
        cnt4     = fa.aligned_count
        base4    = fa.base_dir if fa.base_dir != "↔" else None
        avg_sp4  = fa.avg_spread
        prog_col = fa.color
        dir_sym  = base4 if base4 else "↔"

        # 신선도 (디스플레이 전용 — elapsed 직접 읽기)
        local_tfs = [(" 1M", "tf1"), (" 3M", "tf3"), (" 5M", "tf5"), ("15M", "tf15")]
        fresh4 = 0
        for _, key in local_tfs:
            el = ind.get(key, {}).get("elapsed")
            if el:
                if el == "방금": fresh4 += 1
                elif "분 전" in el:
                    try:
                        if int(el.split("분")[0].strip()) <= 30: fresh4 += 1
                    except: pass
        fresh_stars4 = "★" * min(4, fresh4) + "☆" * (4 - min(4, fresh4))
        fresh_col4   = POSITIVE if fresh4 >= 3 else (YELLOW if fresh4 >= 2 else ORANGE)

        # 비합의 TF 교차 임박 감지 (|K-D| ≤ 5 → "교차 대기" 표시)
        _PEND_THR = 5.0
        ap4_lbl = ""
        if cnt4 == 3 and base4:
            for lbl, key in local_tfs:
                tf_d = ind.get(key, {})
                if tf_d.get("dir", "↔") != base4:
                    if abs(tf_d.get("k", 50.0) - tf_d.get("d", 50.0)) <= _PEND_THR:
                        ap4_lbl = lbl.strip()
                    break

        tk.Frame(f, bg=DARK_BG, height=5).pack(fill="x")
        hdr2 = tk.Frame(f, bg=DARK_HEADER, pady=6)
        hdr2.pack(fill="x")
        tk.Label(hdr2, text="4TF COMPLETE ALIGNMENT", bg=DARK_HEADER, fg=ACCENT_BLUE,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=10)
        tk.Frame(f, bg="#333333", height=1).pack(fill="x")

        sum4_f = tk.Frame(f, bg=DARK_BG, pady=5)
        sum4_f.pack(fill="x", padx=10)

        if cnt4 == 4:
            tk.Label(sum4_f, text=f"{dir_sym} 4/4", bg=DARK_BG, fg=prog_col,
                     font=("Segoe UI", 10, "bold")).pack(side="left")
            tk.Label(sum4_f, text=f"   avg +{avg_sp4:.1f}", bg=DARK_BG, fg=prog_col,
                     font=("Consolas", 8)).pack(side="left")
            tk.Label(sum4_f, text=fresh_stars4, bg=DARK_BG, fg=fresh_col4,
                     font=("Segoe UI", 9, "bold")).pack(side="right")
        elif cnt4 == 3:
            s_col3 = "#8ad7b5" if base4 == "▲" else ORANGE
            tk.Label(sum4_f, text=f"{dir_sym} 3/4", bg=DARK_BG, fg=s_col3,
                     font=("Segoe UI", 10, "bold")).pack(side="left")
            if ap4_lbl:
                tk.Label(sum4_f, text=f"  ⏳ {ap4_lbl} 교차 대기", bg=DARK_BG, fg=YELLOW,
                         font=("Segoe UI", 8)).pack(side="left")
        elif cnt4 == 2:
            tk.Label(sum4_f, text=f"{dir_sym} 2/4   합의 형성 중", bg=DARK_BG, fg=YELLOW,
                     font=("Segoe UI", 10, "bold")).pack(side="left")
        else:
            tk.Label(sum4_f, text=f"─ {cnt4}/4   미합의", bg=DARK_BG, fg=DIM_TEXT,
                     font=("Segoe UI", 10, "bold")).pack(side="left")

        # 4TF 개별 에너지 바 (1M / 3M / 5M / 15M) — grid 균등 4분할
        tk.Frame(f, bg="#2A2A2A", height=1).pack(fill="x", pady=(4, 0))
        bars_f = tk.Frame(f, bg=DARK_BG, pady=5)
        bars_f.pack(fill="x", padx=8)
        for _ci in range(4):
            bars_f.columnconfigure(_ci, weight=1, uniform="tf_col")

        for _idx, (_tf_lbl, _tf_key, _tf_id) in enumerate((
            ("1M",  "tf1",  "1m"),
            ("3M",  "tf3",  "3m"),
            ("5M",  "tf5",  "5m"),
            ("15M", "tf15", "15m"),
        )):
            _tf_d    = ind.get(_tf_key, {})
            _kv      = _tf_d.get("k", 50.0)
            _dv      = _tf_d.get("d", 50.0)
            _tf_dir  = fa.directions.get(_tf_id, "↔")
            _aligned = base4 is not None and _tf_dir == base4
            _pending = (not _aligned) and abs(_kv - _dv) <= _PEND_THR

            if _aligned:
                _bar_col  = prog_col
                _stat_sym = "✓"
                _stat_col = POSITIVE if base4 == "▲" else NEGATIVE
            elif _pending:
                _bar_col  = YELLOW
                _stat_sym = "⏳"
                _stat_col = YELLOW
            else:
                _bar_col  = ORANGE
                _stat_sym = "✗"
                _stat_col = ORANGE

            _dir_col = POSITIVE if _tf_dir == "▲" else (NEGATIVE if _tf_dir == "▼" else DIM_TEXT)

            _col_f = tk.Frame(bars_f, bg=DARK_BG)
            _col_f.grid(row=0, column=_idx, sticky="nsew", padx=2)

            _lbl_r = tk.Frame(_col_f, bg=DARK_BG)
            _lbl_r.pack(fill="x")
            tk.Label(_lbl_r, text=_tf_lbl, bg=DARK_BG, fg=DIM_TEXT,
                     font=("Consolas", 8, "bold")).pack(side="left")
            tk.Label(_lbl_r, text=f" {_tf_dir}", bg=DARK_BG, fg=_dir_col,
                     font=("Consolas", 8, "bold")).pack(side="left")
            tk.Label(_lbl_r, text=f" {_stat_sym}", bg=DARK_BG, fg=_stat_col,
                     font=("Segoe UI", 8)).pack(side="left")

            _bar_cv = tk.Canvas(_col_f, bg="#1A1A1A", height=11, width=1,
                                highlightthickness=0)
            _bar_cv.pack(fill="x", pady=(2, 0))

            def _draw_bar(e=None, cv=_bar_cv, k=_kv, bc=_bar_col):
                cv.delete("all"); w = cv.winfo_width() or 60
                cv.create_rectangle(0, 0, w, 11, fill="#252525", outline="")
                filled = max(2, int(w * k / 100))
                cv.create_rectangle(0, 1, filled, 10, fill=bc, outline="")
            _bar_cv.bind("<Configure>", _draw_bar); _bar_cv.after(50, _draw_bar)

        # Entry verdict
        vd_f = tk.Frame(f, bg=DARK_BG, pady=3); vd_f.pack(fill="x", padx=10)
        ap_lbl = ap4_lbl

        if cnt4 == 4:
            vi, vt, vc2 = "✅", f"{'롱' if base4=='▲' else '숏'} 진입 가능", \
                          (POSITIVE if base4 == "▲" else NEGATIVE)
        elif cnt4 == 3:
            dir_lbl = "롱" if base4 == "▲" else "숏"
            vi  = "⏳"
            vt  = f"{dir_lbl} 3/4 대기 — {ap_lbl} 교차 중" if ap_lbl else f"{dir_lbl} 3/4 대기"
            vc2 = YELLOW
        elif cnt4 == 2:
            vi, vt, vc2 = "⏸", "합의 형성 중 (2/4)", DIM_TEXT
        else:
            vi, vt, vc2 = "─ ", "대기 중", DIM_TEXT

        # 1M 타점 품질
        _tf1v  = ind.get("tf1", {})
        _k1v   = _tf1v.get("k", 50.0)
        _d1v   = _tf1v.get("d", 50.0)
        _diff1 = _k1v - _d1v
        if cnt4 == 4 and base4:
            if base4 == "▲":
                if _diff1 > 2 and _k1v < 20:  q_ic, q_tx, q_cl = "★", f"최적 타점  K:{_k1v:.0f}  과매도 골든크로스", POSITIVE
                elif _diff1 > 2 and _k1v > 80: q_ic, q_tx, q_cl = "⚠️", f"추격 주의  K:{_k1v:.0f}  과매수 진입", ORANGE
                elif _diff1 > 2:               q_ic, q_tx, q_cl = "○", f"양호 타점  K:{_k1v:.0f}  골든크로스", "#8ad7b5"
                else:                          q_ic, q_tx, q_cl = "─", f"K:{_k1v:.0f}  교차 대기", DIM_TEXT
            else:
                if _diff1 < -2 and _k1v > 80:  q_ic, q_tx, q_cl = "★", f"최적 타점  K:{_k1v:.0f}  과매수 데드크로스", NEGATIVE
                elif _diff1 < -2 and _k1v < 20: q_ic, q_tx, q_cl = "⚠️", f"추격 주의  K:{_k1v:.0f}  과매도 구간", ORANGE
                elif _diff1 < -2:               q_ic, q_tx, q_cl = "○", f"양호 타점  K:{_k1v:.0f}  데드크로스", ORANGE
                else:                           q_ic, q_tx, q_cl = "─", f"K:{_k1v:.0f}  교차 대기", DIM_TEXT
        elif cnt4 >= 3 and base4:
            if base4 == "▲" and _k1v < 20:  q_ic, q_tx, q_cl = "★", f"K:{_k1v:.0f}  과매도 구간 — 완성 시 최적 가능", POSITIVE
            elif base4 == "▼" and _k1v > 80: q_ic, q_tx, q_cl = "★", f"K:{_k1v:.0f}  과매수 구간 — 완성 시 최적 가능", NEGATIVE
            else:                             q_ic, q_tx, q_cl = "─", f"1M K:{_k1v:.0f}", DIM_TEXT
        else:
            q_ic, q_tx, q_cl = "─", f"1M K:{_k1v:.0f}", DIM_TEXT

        vd_r2 = tk.Frame(vd_f, bg=DARK_BG); vd_r2.pack(fill="x")
        tk.Label(vd_r2, text=vi, bg=DARK_BG, fg=vc2,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(vd_r2, text=f"  {vt}", bg=DARK_BG, fg=vc2,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        q_row = tk.Frame(vd_f, bg=DARK_BG); q_row.pack(fill="x")
        tk.Label(q_row, text=f"     1M  {q_ic}", bg=DARK_BG, fg=q_cl,
                 font=("Segoe UI", 8)).pack(side="left")
        tk.Label(q_row, text=f"  {q_tx}", bg=DARK_BG, fg=q_cl,
                 font=("Segoe UI", 8)).pack(side="left")

        # ── Section 3: SIGNAL QUALITY ───────────────────────────
        stars = "★" * min(5, sq.fresh_count) + "☆" * (5 - min(5, sq.fresh_count))

        tk.Frame(f, bg=DARK_BG, height=5).pack(fill="x")
        hdr3 = tk.Frame(f, bg=DARK_HEADER, pady=6)
        hdr3.pack(fill="x")
        tk.Label(hdr3, text="SIGNAL QUALITY", bg=DARK_HEADER, fg=ACCENT_BLUE,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=10)
        tk.Frame(f, bg="#333333", height=1).pack(fill="x")

        sq_f = tk.Frame(f, bg=DARK_PANEL, pady=5); sq_f.pack(fill="x")
        r1 = tk.Frame(sq_f, bg=DARK_PANEL); r1.pack(fill="x", padx=10, pady=1)
        tk.Label(r1, text="Score", bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 8), width=6, anchor="w").pack(side="left")
        tk.Label(r1, text=f"{sq.score:+.2f}", bg=DARK_PANEL, fg=sq.score_color,
                 font=("Consolas", 9, "bold")).pack(side="left")
        tk.Label(r1, text=f"  {sq.direction}", bg=DARK_PANEL, fg=sq.score_color,
                 font=("Segoe UI", 8)).pack(side="left")
        tk.Label(r1, text=f"   Agreement  {sq.agree_n}/{sq.n_valid}  {int(sq.agree_pct*100)}%",
                 bg=DARK_PANEL, fg=sq.agree_color, font=("Segoe UI", 8)).pack(side="left")
        r2 = tk.Frame(sq_f, bg=DARK_PANEL); r2.pack(fill="x", padx=10, pady=1)
        tk.Label(r2, text="Fresh", bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 8), width=6, anchor="w").pack(side="left")
        tk.Label(r2, text=stars, bg=DARK_PANEL, fg=sq.fresh_color,
                 font=("Consolas", 9, "bold")).pack(side="left")
        tk.Label(r2, text=f"  {sq.fresh_count} signals", bg=DARK_PANEL, fg=sq.fresh_color,
                 font=("Segoe UI", 8)).pack(side="left")
        tk.Label(r2, text=f"   Reliability  {sq.reliability}%",
                 bg=DARK_PANEL, fg=sq.rely_color, font=("Segoe UI", 8)).pack(side="left")
        # ── (end of _build_macro_panel) ─────────────────────────

    # ─── 차트 갱신 ────────────────────────────────────────────
    def _refresh_chart(self) -> None:
        for w in self._chart_f.winfo_children():
            w.destroy()
        self._mpl_canvas = None
        if HAS_MPL:
            self._draw_mpl_chart()
        else:
            self._draw_canvas_fallback()

    def _draw_mpl_chart(self) -> None:
        sym      = self._sel_var.get()
        tf_label = self._tf_var.get()
        interval = self._TF_LABEL_TO_INTERVAL.get(tf_label, "5m")
        candles  = generate_ohlcv(sym, n=60, interval=interval)

        # 빈 캔들 처리 — 로딩 메시지 표시
        if not candles:
            if self._mpl_canvas is None:
                # 최초: Figure 생성
                fig = Figure(figsize=(7, 4.2), dpi=96, facecolor="#0D0D0D")
                ax  = fig.add_subplot(111)
                ax.set_facecolor("#0D0D0D")
                ax.set_axis_off()
                ax.text(0.5, 0.5, f"{sym}\n데이터 로드 중...",
                        ha="center", va="center", fontsize=12,
                        color="#555555", transform=ax.transAxes)
                cv = FigureCanvasTkAgg(fig, master=self._chart_f)
                cv.draw()
                cv.get_tk_widget().pack(fill="both", expand=True)
                self._mpl_canvas = cv
                self._mpl_fig = fig
                self._mpl_ax  = ax
            else:
                # 재사용: 기존 축만 업데이트
                self._mpl_ax.clear()
                self._mpl_ax.set_axis_off()
                self._mpl_ax.text(0.5, 0.5, f"{sym}\n데이터 로드 중...",
                                  ha="center", va="center", fontsize=12,
                                  color="#555555", transform=self._mpl_ax.transAxes)
                self._mpl_fig.canvas.draw_idle()
            return

        chart_data = CoinChart.prepare(candles, sym)   # EMA20·EMA50·VWAP 계산 위임

        # ── Figure/Axes 재사용 여부 결정 ─────────────────────────
        reuse = (self._mpl_canvas is not None
                 and self._mpl_fig is not None
                 and self._mpl_ax is not None)

        if reuse:
            fig = self._mpl_fig
            ax  = self._mpl_ax
            ax.clear()   # 이전 데이터만 지움 (Figure/Canvas 유지)
        else:
            # 최초 렌더링: 새 Figure + Canvas 생성
            for w_old in self._chart_f.winfo_children():
                w_old.destroy()
            fig = Figure(figsize=(7, 4.2), dpi=96, facecolor="#0D0D0D")
            ax  = fig.add_subplot(111)
            self._mpl_fig = fig
            self._mpl_ax  = ax

        # ── 축 스타일 설정 ────────────────────────────────────────
        ax.set_facecolor("#0D0D0D")
        fig.subplots_adjust(left=0.03, right=0.88, top=0.91, bottom=0.06)
        for spine in ax.spines.values():
            spine.set_color("#2A2A2A")
        ax.tick_params(colors="#555555", labelsize=7)
        ax.yaxis.tick_right()
        ax.grid(True, color="#1C1C1C", linewidth=0.5, linestyle="--", alpha=0.7)

        # ── 캔들 그리기 ─────────────────────────────────────────────
        bw = 0.55
        for i, c in enumerate(chart_data.candles):
            col = POSITIVE if c.is_bullish else NEGATIVE
            ax.plot([i, i], [c.l, c.h], color=col, linewidth=0.8, alpha=0.6)
            body_h = abs(c.c - c.o) or abs(c.h - c.l) * 0.05
            rect = mptch.FancyBboxPatch(
                (i - bw / 2, min(c.o, c.c)),
                bw, body_h,
                boxstyle="square,pad=0",
                linewidth=0, facecolor=col, alpha=0.88,
            )
            ax.add_patch(rect)

        xs = list(range(len(chart_data.candles)))
        ax.plot(xs, chart_data.ema20_line, color=ACCENT_BLUE, linewidth=1.3, label="EMA 20", alpha=0.9)
        ax.plot(xs, chart_data.ema50_line, color=YELLOW,     linewidth=1.3, label="EMA 50", alpha=0.9)
        ax.plot(xs, chart_data.vwap_line,  color="#BBBBBB", linewidth=1.2, label="VWAP",   alpha=0.85,
                linestyle="--")
        if chart_data.support_level is not None:
            ax.axhline(chart_data.support_level, color=POSITIVE, linewidth=0.8,
                       linestyle=":", alpha=0.55, label="Support")
        if chart_data.resist_level is not None:
            ax.axhline(chart_data.resist_level,  color=NEGATIVE, linewidth=0.8,
                       linestyle=":", alpha=0.55, label="Resist")
        ax.legend(loc="upper left", fontsize=7, framealpha=0.25,
                  facecolor="#1E1E1E", edgecolor="#333333", labelcolor=DARK_TEXT)
        ax.set_title(f"{sym}  —  {tf_label}",
                     color=DARK_TEXT, fontsize=9, pad=7, loc="center")
        ax.set_xlim(-1, len(chart_data.candles))

        if reuse:
            # Figure 재사용: 비동기 렌더링 (깜빡임 없음)
            fig.canvas.draw_idle()
        else:
            # 최초 렌더링: Canvas 생성 후 pack
            cv = FigureCanvasTkAgg(fig, master=self._chart_f)
            cv.draw()
            cv.get_tk_widget().pack(fill="both", expand=True)
            self._mpl_canvas = cv

    def _draw_canvas_fallback(self) -> None:
        cv = tk.Canvas(self._chart_f, bg="#0D0D0D", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        self.update_idletasks()
        W = cv.winfo_width() or 700
        H = cv.winfo_height() or 340

        sym      = self._sel_var.get()
        tf_label = self._tf_var.get()
        interval = self._TF_LABEL_TO_INTERVAL.get(tf_label, "5m")
        candles  = generate_ohlcv(sym, n=60, interval=interval)

        # 빈 캔들 처리 — ValueError 방지
        if not candles:
            cv.create_text(W // 2, H // 2, text=f"{sym}\n데이터 로드 중...",
                           fill="#555555", font=("Segoe UI", 11), justify="center")
            return

        chart_data = CoinChart.prepare(candles, sym)   # EMA20·EMA50·VWAP·지지저항 계산 위임

        lo  = min(c.l for c in chart_data.candles)
        hi  = max(c.h for c in chart_data.candles)
        rng = hi - lo or 1
        pl, pr, pt, pb = 10, 58, 24, 18
        cw = W - pl - pr
        ch = H - pt - pb
        bw = cw / len(chart_data.candles)

        def py(p: float) -> float:
            return pt + ch * (1 - (p - lo) / rng)

        for i, c in enumerate(chart_data.candles):
            x   = pl + (i + 0.5) * bw
            col = POSITIVE if c.is_bullish else NEGATIVE
            cv.create_line(x, py(c.l), x, py(c.h), fill=col, width=1)
            bdy = max(bw * 0.55, 2)
            y1, y2 = py(max(c.o, c.c)), py(min(c.o, c.c))
            if abs(y2 - y1) < 1:
                y1 -= 1
            cv.create_rectangle(x - bdy/2, y1, x + bdy/2, y2, fill=col, outline="")

        pts = [(pl + (i + 0.5) * bw, py(v)) for i, v in enumerate(chart_data.ema20_line)]
        if len(pts) > 1:
            flat = [coord for p in pts for coord in p]
            cv.create_line(*flat, fill=ACCENT_BLUE, width=1, smooth=True)

        e50pts = [(pl + (i + 0.5) * bw, py(v)) for i, v in enumerate(chart_data.ema50_line)]
        if len(e50pts) > 1:
            e50flat = [coord for p in e50pts for coord in p]
            cv.create_line(*e50flat, fill=YELLOW, width=1, smooth=True)

        vpts = [(pl + (i + 0.5) * bw, py(v)) for i, v in enumerate(chart_data.vwap_line)]
        if len(vpts) > 1:
            vflat = [coord for p in vpts for coord in p]
            cv.create_line(*vflat, fill="#BBBBBB", width=1, smooth=True, dash=(4, 3))

        if chart_data.support_level is not None:
            sy = py(chart_data.support_level)
            cv.create_line(pl, sy, W - pr, sy, fill=POSITIVE, width=1, dash=(3, 4))
            cv.create_text(W - pr + 3, sy, text="S", fill=POSITIVE,
                           font=("Consolas", 6), anchor="w")

        if chart_data.resist_level is not None:
            ry = py(chart_data.resist_level)
            cv.create_line(pl, ry, W - pr, ry, fill=NEGATIVE, width=1, dash=(3, 4))
            cv.create_text(W - pr + 3, ry, text="R", fill=NEGATIVE,
                           font=("Consolas", 6), anchor="w")

        cv.create_text(W // 2, 12,
                       text=f"{sym}  {self._tf_var.get()}  — Fallback Mode",
                       fill=DIM_TEXT, font=("Segoe UI", 8))
