"""
middle/widget/panel_col3.py
3열 분석 패널 (기술지표/파생/에너지/종합판단) 믹스인
"""
from __future__ import annotations
import tkinter as tk
import tkinter.ttk as ttk
from middle.widget.constants import *

# ── shared_context에서 헬퍼 함수 import (단일 정의, 중복 없음) ──
from middle.widget.shared_context import get_ind, _live_ranking, get_ticker_info
from middle.col3_analysis_panels.derivative_analysis.open_interest import OpenInterestPanel
from middle.col3_analysis_panels.derivative_analysis.funding_rate import FundingRatePanel
from middle.col3_analysis_panels.derivative_analysis.longshort_ratio import LongShortPanel
from middle.col3_analysis_panels.technical_analysis.rsi import RSI
from middle.col3_analysis_panels.technical_analysis.bpr import BPR
from middle.col3_analysis_panels.technical_analysis.vss import VSS
from middle.col3_analysis_panels.technical_analysis.atr_percent import AtrPercent
from middle.col3_analysis_panels.comprehensive_analysis.technical_verdict import TechnicalVerdictPanel
from middle.col3_analysis_panels.comprehensive_analysis.derivative_verdict import DerivativeVerdictPanel
from middle.col3_analysis_panels.comprehensive_analysis.newlisted_lifecycle import NewlistedLifecycle


class _Col3Mixin:
    """3열 분석 패널 믹스인."""

    # ─── 심볼 헤더 갱신 ───────────────────────────────────────
    def _refresh_header(self) -> None:
        for w in self._hdr_f.winfo_children():
            w.destroy()

        sym  = self._sel_var.get()
        data = next((d for d in _live_ranking() if d[0] == sym), None)

        # ── Assign Symbol 버튼: sym 있으면 top-200 여부 무관하게 항상 갱신 ──
        action_bar = getattr(self, '_action_bar', None)
        if action_bar is not None and sym:
            for w in action_bar.winfo_children():
                if hasattr(w, '_is_assign_btn'):
                    w.destroy()
            is_assigned = (self._assigned_sym == sym)
            assign_btn = tk.Button(
                action_bar,
                text="✓  Assigned" if is_assigned else "  Assign Symbol  ",
                bg=POSITIVE       if is_assigned else "#252525",
                fg="#000000"      if is_assigned else "#888888",
                activebackground="#0ab875" if is_assigned else "#303030",
                activeforeground="#000000" if is_assigned else DARK_TEXT,
                font=("Segoe UI", 8, "bold"),
                relief="flat", padx=10, pady=4,
                cursor="hand2",
                command=lambda s=sym: self._on_assign(s),
            )
            assign_btn._is_assign_btn = True
            assign_btn.pack(side="right", padx=4)

        if not data:
            # 200위 밖 심볼: 심볼명 + —— (별점/장단계) + 등락률 + 순위 뱃지
            info = get_ticker_info(sym)
            chg      = info[0] if info else 0.0
            vol_rank = info[1] if info else 999
            chg_txt  = f"  {chg:+.2f}%"
            chg_col  = POSITIVE if chg > 0 else (NEGATIVE if chg < 0 else DIM_TEXT)

            left = tk.Frame(self._hdr_f, bg=DARK_PANEL)
            left.pack(side="left", padx=16)
            tk.Label(left, text=sym, bg=DARK_PANEL, fg=DARK_TEXT,
                     font=("Segoe UI", 10, "bold")).pack(side="left")
            tk.Label(left, text="  ——  ", bg=DARK_PANEL, fg=DIM_TEXT,
                     font=("Segoe UI", 9, "bold"), padx=4, pady=1).pack(side="left", padx=(10, 0))
            tk.Label(left, text="——", bg=DARK_PANEL, fg=DIM_TEXT,
                     font=("Segoe UI", 9, "bold")).pack(side="left", padx=(6, 0))
            tk.Label(left, text=chg_txt, bg=DARK_PANEL, fg=chg_col,
                     font=("Segoe UI", 10, "bold")).pack(side="left", padx=(10, 0))
            tk.Label(left, text=f"  {vol_rank}위 ",
                     bg="#2A1A00", fg="#CC6600",
                     font=("Segoe UI", 7, "bold"), padx=3).pack(side="left", padx=(6, 0))
            return

        (symbol, days,
         tf_text, tf_color,
         change, change_color,
         cum_pct, cum_color,
         phase, phase_color, phase_priority,
         player_tags) = data

        left = tk.Frame(self._hdr_f, bg=DARK_PANEL)
        left.pack(side="left", padx=16)

        tk.Label(left, text=symbol, bg=DARK_PANEL, fg=DARK_TEXT,
                 font=("Segoe UI", 10, "bold")).pack(side="left")

        if days > 0:
            tk.Label(left, text=f" 신규{days}일",
                     bg=NEW_BG, fg=NEW_FG,
                     font=("Segoe UI", 7, "bold"), padx=3).pack(side="left", padx=(6, 0))

        tk.Label(left, text=f"  {tf_text} ", bg=DARK_PANEL, fg=tf_color,
                 font=("Segoe UI", 9, "bold"), padx=4, pady=1).pack(side="left", padx=(10, 0))

        tk.Label(left, text=phase, bg=DARK_PANEL, fg=phase_color,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(6, 0))

        tk.Label(left, text=change, bg=DARK_PANEL, fg=change_color,
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=(10, 0))

        tk.Label(left, text="  TOP 200 ",
                 bg="#0A1F0A", fg=POSITIVE,
                 font=("Segoe UI", 7, "bold"), padx=3).pack(side="left", padx=(6, 0))

    # ─── 지표 패널 갱신 (좌측 230px 세로 배치) ──────────────────
    def _refresh_indicators(self) -> None:
        for w in self._ind_f.winfo_children():
            w.destroy()

        sym  = self._sel_var.get()
        ind  = get_ind(sym)
        _row = next((d for d in _live_ranking() if d[0] == sym), None)
        _days = _row[1] if _row else 0

        # ── 신규 상장 코인 분석 신뢰도 경고 배너 ────────────────
        if _days > 0:
            if _days <= 7:
                _warn_bg  = "#1A0A00"
                _warn_col = ORANGE
                _warn_ico = "⚠"
                _warn_ttl = f"D+{_days} Ultra New — 데이터 부족"
                _valid    = "✅ 유효: 에너지·VSS·Player·OI·FR"
                _invalid  = "❌ 제한: TF합의·추세·4TF·Macro"
            elif _days <= 30:
                _warn_bg  = "#1A1400"
                _warn_col = YELLOW
                _warn_ico = "⚠"
                _warn_ttl = f"D+{_days} New — 일부 분석 제한"
                _valid    = "✅ 유효: 에너지·VSS·Player·OI·FR"
                _invalid  = "⚠ 주의: 4TF·Macro 부분 제한"
            else:
                _warn_bg  = DARK_PANEL
                _warn_col = DIM_TEXT
                _warn_ico = "ℹ"
                _warn_ttl = f"D+{_days} Recent — 1D 데이터 제한적"
                _valid    = "✅ 대부분 분석 유효"
                _invalid  = "ℹ 1D 기반 거시 분석 참고 수준"

            wb = tk.Frame(self._ind_f, bg=_warn_bg, pady=4)
            wb.pack(fill="x", padx=6, pady=(2, 4))
            tk.Label(wb, text=f"{_warn_ico} {_warn_ttl}",
                     bg=_warn_bg, fg=_warn_col,
                     font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", padx=6)
            tk.Label(wb, text=_valid,
                     bg=_warn_bg, fg="#7FBF7F",
                     font=("Segoe UI", 7), anchor="w").pack(fill="x", padx=8)
            tk.Label(wb, text=_invalid,
                     bg=_warn_bg, fg=_warn_col,
                     font=("Segoe UI", 7), anchor="w").pack(fill="x", padx=8)
            # ── 라이프사이클 감지 결과 ──────────────────────────
            _lc_res = self._nl_lifecycle(sym, days=_days)
            if _lc_res:
                _, _lc_lbl, _lc_col, _ = _lc_res
                _pchg = ind.get("price_change_pct", 0.0)
                _h24p = ind.get("high_24h_pct",     0.0)
                _vss  = ind.get("vss",              1.0)
                tk.Frame(wb, bg="#333333", height=1).pack(
                    fill="x", padx=4, pady=(3, 2))
                tk.Label(wb, text=_lc_lbl,
                         bg=_warn_bg, fg=_lc_col,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", padx=6)
                tk.Label(wb,
                         text=f"   24h {_pchg:+.1f}%  고점차 {_h24p:+.1f}%  VSS {_vss:.1f}",
                         bg=_warn_bg, fg=DIM_TEXT,
                         font=("Consolas", 7), anchor="w").pack(fill="x", padx=6)

        # 5개 지표 — 한 행씩 세로 배치 (ind.get으로 KeyError 방지)
        _rsi = ind.get("rsi", 50.0)
        _bpr = ind.get("bpr", 0.5)
        _vss = ind.get("vss", 1.0)
        _atr = ind.get("atr", 0.0)
        specs = [
            ("RSI",  _rsi,  100.0, RSI.color(_rsi),        RSI.label(_rsi)),
            ("BPR",  _bpr,    1.0, BPR.color(_bpr),        BPR.label(_bpr)),
            ("VSS",  _vss,    2.5, VSS.color(_vss),        VSS.label(_vss)),
            ("ATR%", _atr,   10.0, ACCENT_BLUE,            "(변동성)"),
        ]
        for name, val, mx, col, lbl in specs:
            row = tk.Frame(self._ind_f, bg=DARK_PANEL)
            row.pack(fill="x", padx=8, pady=2)

            # 지표명 (고정 너비)
            tk.Label(row, text=name, bg=DARK_PANEL, fg=DIM_TEXT,
                     font=("Segoe UI", 9, "bold"), width=7,
                     anchor="w").pack(side="left")

            # Canvas 비례 바 (패널 너비에 맞게 자동 확장)
            ratio = min(max(val / mx, 0.0), 1.0)
            bar_cv = tk.Canvas(row, bg="#1A1A1A", height=10, width=120,
                               highlightthickness=0)
            bar_cv.pack(side="left", fill="x", expand=True, padx=(2, 4))

            def _redraw(event=None, cv=bar_cv, r=ratio, c=col):
                cv.delete("all")
                w = cv.winfo_width()
                if w < 2:
                    return
                filled = int(w * r)
                cv.create_rectangle(0, 0, w, 10, fill="#1A1A1A", outline="")
                if filled > 0:
                    cv.create_rectangle(0, 1, filled, 9, fill=c, outline="")

            bar_cv.bind("<Configure>", _redraw)
            bar_cv.after(15, _redraw)

            # 값 + 레이블 (고정 너비)
            val_str = (f"{val:.1f}" if mx >= 10
                       else f"{val:.2f}" if mx <= 2.5
                       else f"{val:.1f}")
            tk.Label(row, text=f"{val_str} {lbl}",
                     bg=DARK_PANEL, fg=col,
                     font=("Segoe UI", 9), width=14,
                     anchor="w").pack(side="left")

            # Sort by="Sharp rise"/"Sharp decline" 모드: VSS는 선정 점수의 'VSS 거래량 에너지' 항목 → 배지 표시
            if name == "VSS" and self._sort_mode in ("Sharp rise", "Sharp decline"):
                _s_vss = 2 if val > 1.5 else 1 if val > 1.2 else 0
                tk.Label(row, text=f"  🎯 {self._sort_mode} 핵심 (+{_s_vss}점)",
                         bg=DARK_PANEL, fg=ACCENT_BLUE,
                         font=("Segoe UI", 7, "bold"), anchor="w").pack(side="left")

            # Sort by="Volatility" 모드: ATR%이 정렬 기준 → 변동성 등급 배지 표시
            if name == "ATR%" and self._sort_mode == "Volatility":
                tk.Label(row, text=f"  🎯 Volatility 정렬 기준 ({AtrPercent.label(val)})",
                         bg=DARK_PANEL, fg=AtrPercent.color(val),
                         font=("Segoe UI", 7, "bold"), anchor="w").pack(side="left")

            # Sort by="4TF Optimization" 모드: ATR 3~8% 적정 변동성 → ④항목 배지 표시
            if name == "ATR%" and self._sort_mode == "4TF Optimization":
                _ok = 3.0 <= val <= 8.0
                tk.Label(row, text=f"  🎯 4TF 적정 변동성 (3~8%) {'✅ +1점' if _ok else '— 0점'}",
                         bg=DARK_PANEL, fg=ACCENT_BLUE if _ok else DIM_TEXT,
                         font=("Segoe UI", 7, "bold"), anchor="w").pack(side="left")

            # Sort by="Newly Listed" 모드: VSS는 ①Volume Surge 점수 항목 → 배지 표시
            if name == "VSS" and self._sort_mode == "Newly Listed":
                _res_nl = self._calc_newlist_score(sym)
                _s_surge = _res_nl["scores"]["surge"]
                tk.Label(row, text=f"  🎯 Volume Surge (+{_s_surge}점)",
                         bg=DARK_PANEL, fg=ACCENT_BLUE if _s_surge > 0 else DIM_TEXT,
                         font=("Segoe UI", 7, "bold"), anchor="w").pack(side="left")

        # 구분선
        tk.Frame(self._ind_f, bg="#333333", height=1).pack(fill="x", padx=8, pady=(4, 2))

        # ② 패턴 + VWAP — 1행 병렬 (📊 패턴  |  💧 VWAP)
        _vwap_val = ind.get("vwap", "")
        vwap_col  = POSITIVE if "위" in _vwap_val else (NEGATIVE if "아래" in _vwap_val else DIM_TEXT)
        pv_row = tk.Frame(self._ind_f, bg=DARK_PANEL)
        pv_row.pack(fill="x", padx=6, pady=(2, 4))
        tk.Label(pv_row, text=f"📊 {ind.get('pattern', '—')}",
                 bg=DARK_PANEL, fg=YELLOW,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
        tk.Label(pv_row, text="  |  ",
                 bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 8)).pack(side="left")
        tk.Label(pv_row, text=f"💧 {ind.get('vwap', '—')}",
                 bg=DARK_PANEL, fg=vwap_col,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")

    # ─── EMA + 추세 패널 갱신 (좌측 230px 세로 배치) ────────────
    def _refresh_ema(self) -> None:
        for w in self._ema_f.winfo_children():
            w.destroy()

        sym = self._sel_var.get()
        ind = get_ind(sym)
        align     = ind.get("align", "—")           # KeyError 방지
        align_col = POSITIVE if align == "정배열" else (NEGATIVE if align == "역배열" else YELLOW)
        align_icon= "✅" if align == "정배열" else ("❌" if align == "역배열" else "⚠️")

        # EMA Trend 타이틀 행
        r0 = tk.Frame(self._ema_f, bg=DARK_PANEL)
        r0.pack(fill="x", padx=8, pady=(0, 2))
        tk.Label(r0, text="EMA Trend", bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(r0, text=f"  {align_icon} {align}",
                 bg=DARK_PANEL, fg=align_col,
                 font=("Segoe UI", 9, "bold")).pack(side="left")

        # EMA 수치 (3개 한 줄 가운데 정렬)
        ema_txt = (f"EMA5: {fmt_price(ind.get('e5', 0.0))}"
                   f"   EMA10: {fmt_price(ind.get('e10', 0.0))}"
                   f"   EMA20: {fmt_price(ind.get('e20', 0.0))}")
        tk.Label(self._ema_f, text=ema_txt,
                 bg=DARK_PANEL, fg=DARK_TEXT,
                 font=("Consolas", 9),
                 justify="center").pack(fill="x", padx=4, pady=(0, 2))

        # Trend 정보는 분봉 버튼에 통합됨 (_refresh_tf_buttons 참조)

    # ─── Col 3: 파생 분석 패널 갱신 ──────────────────────────
    def _refresh_deriv(self) -> None:
        if self._deriv_f is None:
            return
        for w in self._deriv_f.winfo_children():
            w.destroy()

        sym = self._sel_var.get()
        ind = get_ind(sym)
        fr      = ind.get("funding_rate",  0.0)
        oi      = ind.get("oi_change",     0.0)
        lr      = ind.get("long_ratio",   50.0)
        liq_l   = ind.get("liq_long_pct", -1.5)
        liq_s   = ind.get("liq_short_pct", 1.5)
        rec_lev = ind.get("rec_leverage",   10)
        sr      = 100.0 - lr
        fra     = FundingRatePanel.from_rate(fr, rec_lev)
        lsa     = LongShortPanel.from_pct(lr)

        def div():
            tk.Frame(self._deriv_f, bg="#2A2A2A", height=1).pack(
                fill="x", padx=8, pady=(3, 0))

        # ── ① 펀딩비 (FR) — 인라인 ───────────────────────────────
        fr_col  = ORANGE if fr > 0.05 else (NEGATIVE if fr < -0.05 else ACCENT_BLUE)
        fr_icon = fra.direction
        daily   = fra.daily_cost_pct

        fr_row = tk.Frame(self._deriv_f, bg=DARK_PANEL)
        fr_row.pack(fill="x", padx=8, pady=(5, 1))
        tk.Label(fr_row, text="FR", bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 8, "bold"), width=3, anchor="w").pack(side="left")
        tk.Label(fr_row, text=f"{fr:+.3f}%", bg=DARK_PANEL, fg=fr_col,
                 font=("Consolas", 9, "bold")).pack(side="left", padx=(3, 0))
        tk.Label(fr_row, text=f"  {fr_icon}", bg=DARK_PANEL, fg=fr_col,
                 font=("Segoe UI", 8)).pack(side="left")
        tk.Label(fr_row, text=f"{rec_lev}배/일 {daily:.2f}%", bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 7)).pack(side="right")
        if self._sort_mode == "4TF Optimization":
            _fr_ok = fra.score_4tf == 1
            tk.Label(fr_row, text=f"🎯 FR중립 {'✅+1' if _fr_ok else '—0'}",
                     bg=DARK_PANEL, fg=ACCENT_BLUE if _fr_ok else DIM_TEXT,
                     font=("Segoe UI", 7, "bold")).pack(side="right", padx=(0, 8))
        if self._sort_mode == "Newly Listed":
            _s_fr_nl = self._calc_newlist_score(sym)["scores"]["funding"]
            tk.Label(fr_row, text=f"🎯 Funding Extreme (+{_s_fr_nl}점)",
                     bg=DARK_PANEL, fg=ACCENT_BLUE if _s_fr_nl > 0 else DIM_TEXT,
                     font=("Segoe UI", 7, "bold")).pack(side="right", padx=(0, 8))
        _fr_grade = fra.grade
        tk.Label(self._deriv_f, text=f"  {_fr_grade}", bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 7), anchor="w").pack(fill="x", padx=8)

        cv_fr = tk.Canvas(self._deriv_f, bg="#1A1A1A", height=8, highlightthickness=0)
        cv_fr.pack(fill="x", padx=8, pady=(1, 3))
        def _draw_fr(e=None, cv=cv_fr, val=fr):
            cv.delete("all"); w = cv.winfo_width()
            if w < 4: return
            mid = w // 2
            px = max(1, min(w-1, int(mid + (val / 0.15) * mid)))
            cv.create_rectangle(0, 1, w, 7, fill="#252525", outline="")
            cv.create_line(mid, 0, mid, 8, fill=DIM_TEXT, width=1)
            col = ORANGE if val > 0.05 else (POSITIVE if val < -0.05 else ACCENT_BLUE)
            if val >= 0: cv.create_rectangle(mid, 2, px, 6, fill=col, outline="")
            else:        cv.create_rectangle(px, 2, mid, 6, fill=col, outline="")
        cv_fr.bind("<Configure>", _draw_fr); cv_fr.after(15, _draw_fr)

        # ── ② OI 변화 — 중앙 기준 게이지 (FR과 동일 시각 언어) ───
        oi_col  = POSITIVE if oi > 5 else (NEGATIVE if oi < -5 else ACCENT_BLUE)
        oi_icon = "유입↑" if oi > 5 else ("이탈↓" if oi < -5 else "보합")

        oi_row = tk.Frame(self._deriv_f, bg=DARK_PANEL)
        oi_row.pack(fill="x", padx=8, pady=(2, 1))
        tk.Label(oi_row, text="OI", bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 8, "bold"), width=3, anchor="w").pack(side="left")
        tk.Label(oi_row, text=f"{oi:+.1f}%", bg=DARK_PANEL, fg=oi_col,
                 font=("Consolas", 9, "bold")).pack(side="left", padx=(3, 0))
        tk.Label(oi_row, text=f"  {oi_icon}", bg=DARK_PANEL, fg=oi_col,
                 font=("Segoe UI", 8)).pack(side="left")
        if self._sort_mode == "4TF Optimization":
            _oi_ok = oi > 0
            tk.Label(oi_row, text=f"🎯 OI증가 {'✅+1' if _oi_ok else '—0'}",
                     bg=DARK_PANEL, fg=ACCENT_BLUE if _oi_ok else DIM_TEXT,
                     font=("Segoe UI", 7, "bold")).pack(side="right")
        if self._sort_mode == "Newly Listed":
            _s_oi_nl = self._calc_newlist_score(sym)["scores"]["oi"]
            tk.Label(oi_row, text=f"🎯 OI Momentum (+{_s_oi_nl}점)",
                     bg=DARK_PANEL, fg=ACCENT_BLUE if _s_oi_nl > 0 else DIM_TEXT,
                     font=("Segoe UI", 7, "bold")).pack(side="right")
        _oi_grade = OpenInterestPanel.analyze(oi).grade
        tk.Label(self._deriv_f, text=f"  {_oi_grade}", bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 7), anchor="w").pack(fill="x", padx=8)

        cv_oi = tk.Canvas(self._deriv_f, bg="#1A1A1A", height=8, highlightthickness=0)
        cv_oi.pack(fill="x", padx=8, pady=(1, 3))
        def _draw_oi(e=None, cv=cv_oi, val=oi):
            cv.delete("all"); w = cv.winfo_width()
            if w < 4: return
            mid = w // 2
            px = max(1, min(w-1, int(mid + (val / 30.0) * mid)))
            cv.create_rectangle(0, 1, w, 7, fill="#252525", outline="")
            cv.create_line(mid, 0, mid, 8, fill=DIM_TEXT, width=1)
            col = POSITIVE if val > 5 else (NEGATIVE if val < -5 else ACCENT_BLUE)
            if val >= 0: cv.create_rectangle(mid, 2, px, 6, fill=col, outline="")
            else:        cv.create_rectangle(px, 2, mid, 6, fill=col, outline="")
        cv_oi.bind("<Configure>", _draw_oi); cv_oi.after(15, _draw_oi)

        div()

        # ── ③ 롱/숏 비율 — 압축 ────────────────────────────────
        lr_col = ORANGE if lr > 80 else (POSITIVE if lr > 55 else (NEGATIVE if lr < 30 else ACCENT_BLUE))
        warn   = "  ⚠️" if lsa.warning else ""

        ls_row = tk.Frame(self._deriv_f, bg=DARK_PANEL)
        ls_row.pack(fill="x", padx=8, pady=(4, 1))
        tk.Label(ls_row, text=f"롱 {lr:.0f}%",
                 bg=DARK_PANEL, fg=(POSITIVE if lr > 50 else DIM_TEXT),
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Label(ls_row, text=f"  숏 {sr:.0f}%{warn}",
                 bg=DARK_PANEL, fg=lr_col,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        if self._sort_mode == "4TF Optimization":
            _bal_ok = lsa.score_4tf == 1
            tk.Label(ls_row, text=f"🎯 롱숏균형 {'✅+1' if _bal_ok else '—0'}",
                     bg=DARK_PANEL, fg=ACCENT_BLUE if _bal_ok else DIM_TEXT,
                     font=("Segoe UI", 7, "bold")).pack(side="right")
        _ls_grade = lsa.grade
        _squeeze  = lsa.squeeze_risk
        _ls_grade_row = tk.Frame(self._deriv_f, bg=DARK_PANEL)
        _ls_grade_row.pack(fill="x", padx=8, pady=(1, 0))
        tk.Label(_ls_grade_row, text=f"  {_ls_grade}", bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 7), anchor="w").pack(side="left")
        tk.Label(_ls_grade_row, text=_squeeze, bg=DARK_PANEL, fg=ACCENT_BLUE,
                 font=("Segoe UI", 7), anchor="e").pack(side="right")

        cv_ls = tk.Canvas(self._deriv_f, bg="#1A1A1A", height=10, highlightthickness=0)
        cv_ls.pack(fill="x", padx=8, pady=(1, 3))
        def _draw_ls(e=None, cv=cv_ls, ratio=lr/100):
            cv.delete("all"); w = cv.winfo_width()
            if w < 4: return
            lp = int(w * ratio)
            cv.create_rectangle(0, 1, w, 9, fill="#252525", outline="")
            if lp > 0:
                cv.create_rectangle(0, 2, lp, 8, fill=(ORANGE if ratio > 0.80 else POSITIVE), outline="")
            if lp < w:
                cv.create_rectangle(lp, 2, w, 8, fill=NEGATIVE, outline="")
        cv_ls.bind("<Configure>", _draw_ls); cv_ls.after(15, _draw_ls)

        div()

        # ── ④ 청산 근접도 (신규 시각화) ──────────────────────────
        abs_l = abs(liq_l)
        abs_s = abs(liq_s)
        MAX_D = 5.0
        ratio_l = min(abs_l / MAX_D, 1.0)
        ratio_s = min(abs_s / MAX_D, 1.0)

        closer = "롱 청산 근접!" if abs_l < abs_s - 0.3 else ("숏 청산 근접!" if abs_s < abs_l - 0.3 else "")
        closer_col = NEGATIVE if "롱" in closer else (POSITIVE if "숏" in closer else DIM_TEXT)

        liq_hdr = tk.Frame(self._deriv_f, bg=DARK_PANEL)
        liq_hdr.pack(fill="x", padx=8, pady=(4, 2))
        tk.Label(liq_hdr, text="청산 근접도", bg=DARK_PANEL, fg=DIM_TEXT,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        if closer:
            tk.Label(liq_hdr, text=closer, bg=DARK_PANEL, fg=closer_col,
                     font=("Segoe UI", 7, "bold")).pack(side="right")

        for direction, ratio, pct_txt, base_col in [
            ("↓ 롱", ratio_l, f"{liq_l:+.1f}%", NEGATIVE),
            ("↑ 숏", ratio_s, f"+{abs_s:.1f}%",  POSITIVE),
        ]:
            warn_col = (NEGATIVE if ratio < 0.20 else
                        (ORANGE   if ratio < 0.40 else DIM_TEXT))
            full_txt = pct_txt + (" ⚠️" if ratio < 0.20 else "")
            fill_col = (NEGATIVE if ratio < 0.20 else
                        (ORANGE   if ratio < 0.40 else "#1A2A1A"))

            lq_row = tk.Frame(self._deriv_f, bg=DARK_PANEL)
            lq_row.pack(fill="x", padx=8, pady=(1, 1))
            tk.Label(lq_row, text=direction, bg=DARK_PANEL, fg=base_col,
                     font=("Consolas", 8, "bold"), width=5).pack(side="left")
            # RIGHT 먼저 pack → 캔버스가 중간 공간 채움
            tk.Label(lq_row, text=full_txt, bg=DARK_PANEL, fg=warn_col,
                     font=("Consolas", 8, "bold")).pack(side="right")
            cv_lq = tk.Canvas(lq_row, bg="#1A1A1A", height=8, highlightthickness=0)
            cv_lq.pack(side="left", fill="x", expand=True, padx=(2, 4))
            def _draw_lq(e=None, cv=cv_lq, r=ratio, fc=fill_col):
                cv.delete("all"); w = cv.winfo_width()
                if w < 4: return
                filled = int(w * r)
                cv.create_rectangle(0, 1, w, 7, fill="#252525", outline="")
                if filled > 0:
                    cv.create_rectangle(0, 2, filled, 6, fill=fc, outline="")
            cv_lq.bind("<Configure>", _draw_lq); cv_lq.after(15, _draw_lq)

    # ─── Col 1 하단: 종합 분석 갱신 ──────────────────────────
    def _refresh_verdict(self) -> None:
        if self._verdict_f is None:
            return
        for w in self._verdict_f.winfo_children():
            w.destroy()

        sym     = self._sel_var.get()
        ind     = get_ind(sym)
        phase, _= self._get_phase_for_sym(sym)
        long_r  = self._calc_energy(ind)
        rec_lev = ind.get("rec_leverage", 10)
        fr      = ind.get("funding_rate", 0.0)
        oi      = ind.get("oi_change", 0.0)
        lr      = ind.get("long_ratio", 50.0)

        lines = []
        # 기술 요약 — TechnicalVerdictPanel 위임
        tv = TechnicalVerdictPanel.analyze(
            rsi_1h    = ind.get("rsi", 50.0),
            bpr       = ind.get("bpr", 0.0),
            ema_align = ind.get("align", ""),
        )
        lines.append((tv.prefix, tv.summary, tv.suffix, tv.color))
        # 파생 요약/주의/위험 — DerivativeVerdictPanel 위임
        player_tags = ind.get("_player_tags", [])
        dvr = DerivativeVerdictPanel.analyze(
            oi_change_pct = oi,
            player_tags   = player_tags,
            fr_pct        = fr,
            long_pct      = lr,
            rec_leverage  = rec_lev,
        )
        lines.append((dvr.derivative_line.prefix, dvr.derivative_line.summary,
                      dvr.derivative_line.suffix, dvr.derivative_line.color))
        for w in dvr.warning_lines + dvr.risk_lines:
            lines.append((w.prefix, w.summary, w.suffix, w.color))

        # ── Sort by="24h Ticker" 선정 근거 (24h 변동률 + 전체 순위) ──
        if self._sort_mode == "24h Ticker":
            _row = next((d for d in _live_ranking() if d[0] == sym), None)
            if _row is not None:
                _sorted = self._get_sorted_ranking()
                _rank = next((i + 1 for i, r in enumerate(_sorted) if r[0] == sym), None)
                ctx_f = tk.Frame(self._verdict_f, bg=DARK_PANEL)
                ctx_f.pack(fill="x", padx=10, pady=(2, 1))
                tk.Label(ctx_f, text="🎯 24h 변동률 ", bg=DARK_PANEL, fg=ACCENT_BLUE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
                tk.Label(ctx_f, text=_row[4], bg=DARK_PANEL, fg=_row[5],
                         font=("Consolas", 8, "bold"), anchor="w").pack(side="left")
                if _rank is not None:
                    tk.Label(ctx_f, text=f"  (전체 {_rank}위)", bg=DARK_PANEL, fg=DIM_TEXT,
                             font=("Segoe UI", 8), anchor="w").pack(side="left")
                tk.Frame(self._verdict_f, bg="#2A2A2A", height=1).pack(
                    fill="x", padx=10, pady=(2, 2))

        # ── Sort by="Sharp rise" 선정 근거 (6요소 점수 breakdown + 전체 순위) ──
        elif self._sort_mode == "Sharp rise":
            res = self._calc_rise_score(sym)
            ctx_f = tk.Frame(self._verdict_f, bg=DARK_PANEL)
            ctx_f.pack(fill="x", padx=10, pady=(2, 1))
            if not res["qualified"]:
                tk.Label(ctx_f, text=f"⚠ Sharp rise 자격 미달 (SR {res['sr']:.0f}%<40% & FR 미달) — 참고용 분석",
                         bg=DARK_PANEL, fg=ORANGE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            else:
                _sorted = self._get_sorted_ranking()
                _rank = next((i + 1 for i, r in enumerate(_sorted) if r[0] == sym), None)
                tk.Label(ctx_f, text="🎯 Sharp rise 선정 근거 ", bg=DARK_PANEL, fg=ACCENT_BLUE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
                tk.Label(ctx_f, text=f"전체 {_rank}위 · 총 {res['total']}/{res['max']}점",
                         bg=DARK_PANEL, fg=DARK_TEXT,
                         font=("Consolas", 8, "bold"), anchor="w").pack(side="left")
                sc = res["scores"]
                detail_lines = [
                    (f"숏쏠림 {res['sr']:.0f}%(+{sc['sr']})  "
                     f"FR {res['fr']:+.3f}%(+{sc['fr']})  "
                     f"숏청산 {res['liq_s']:.1f}%(+{sc['liq']})"),
                    (f"OI {res['oi']:+.1f}%(+{sc['oi']})  "
                     f"VSS {res['vss']:.2f}(+{sc['vss']})  "
                     f"Player{'✅' if res['has_rise_tag'] else '—'}(+{sc['player']})"),
                ]
                for dtxt in detail_lines:
                    drow = tk.Frame(self._verdict_f, bg=DARK_PANEL)
                    drow.pack(fill="x", padx=10, pady=(0, 1))
                    tk.Label(drow, text=dtxt, bg=DARK_PANEL, fg=DIM_TEXT,
                             font=("Consolas", 8), anchor="w").pack(side="left")
            tk.Frame(self._verdict_f, bg="#2A2A2A", height=1).pack(
                fill="x", padx=10, pady=(2, 2))

        # ── Sort by="Sharp decline" 선정 근거 (6요소 점수 breakdown + 전체 순위) ──
        elif self._sort_mode == "Sharp decline":
            res = self._calc_decline_score(sym)
            ctx_f = tk.Frame(self._verdict_f, bg=DARK_PANEL)
            ctx_f.pack(fill="x", padx=10, pady=(2, 1))
            if not res["qualified"]:
                tk.Label(ctx_f, text=f"⚠ Sharp decline 자격 미달 (롱쏠림 {res['lr']:.0f}% < 50%) — 참고용 분석",
                         bg=DARK_PANEL, fg=ORANGE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            else:
                _sorted = self._get_sorted_ranking()
                _rank = next((i + 1 for i, r in enumerate(_sorted) if r[0] == sym), None)
                tk.Label(ctx_f, text="🎯 Sharp decline 선정 근거 ", bg=DARK_PANEL, fg=ACCENT_BLUE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
                tk.Label(ctx_f, text=f"전체 {_rank}위 · 총 {res['total']}/{res['max']}점",
                         bg=DARK_PANEL, fg=DARK_TEXT,
                         font=("Consolas", 8, "bold"), anchor="w").pack(side="left")
                sc = res["scores"]
                detail_lines = [
                    (f"롱쏠림 {res['lr']:.0f}%(+{sc['lr']})  "
                     f"FR {res['fr']:+.3f}%(+{sc['fr']})  "
                     f"롱청산 {res['liq_l']:.1f}%(+{sc['liq']})"),
                    (f"OI {res['oi']:+.1f}%(+{sc['oi']})  "
                     f"VSS {res['vss']:.2f}(+{sc['vss']})  "
                     f"Player{'✅' if res['has_decline_tag'] else '—'}(+{sc['player']})"),
                ]
                for dtxt in detail_lines:
                    drow = tk.Frame(self._verdict_f, bg=DARK_PANEL)
                    drow.pack(fill="x", padx=10, pady=(0, 1))
                    tk.Label(drow, text=dtxt, bg=DARK_PANEL, fg=DIM_TEXT,
                             font=("Consolas", 8), anchor="w").pack(side="left")
            tk.Frame(self._verdict_f, bg="#2A2A2A", height=1).pack(
                fill="x", padx=10, pady=(2, 2))

        # ── Sort by="Volatility" 선정 근거 (ATR% + 변동성 등급 + 전체 순위) ──
        elif self._sort_mode == "Volatility":
            _row = next((d for d in _live_ranking() if d[0] == sym), None)
            if _row is not None:
                _sorted = self._get_sorted_ranking()
                _rank = next((i + 1 for i, r in enumerate(_sorted) if r[0] == sym), None)
                _atr = ind.get("atr", 2.0)
                ctx_f = tk.Frame(self._verdict_f, bg=DARK_PANEL)
                ctx_f.pack(fill="x", padx=10, pady=(2, 1))
                tk.Label(ctx_f, text="🎯 Volatility 선정 근거 ", bg=DARK_PANEL, fg=ACCENT_BLUE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
                tk.Label(ctx_f, text=f"ATR {_atr:.1f}% ({AtrPercent.label(_atr)})",
                         bg=DARK_PANEL, fg=AtrPercent.color(_atr),
                         font=("Consolas", 8, "bold"), anchor="w").pack(side="left")
                if _rank is not None:
                    tk.Label(ctx_f, text=f"  (전체 {_rank}위)", bg=DARK_PANEL, fg=DIM_TEXT,
                             font=("Segoe UI", 8), anchor="w").pack(side="left")
                tk.Frame(self._verdict_f, bg="#2A2A2A", height=1).pack(
                    fill="x", padx=10, pady=(2, 2))

        # ── Sort by="4TF Optimization" 선정 근거 (9항목 체크리스트 + 전체 순위) ──
        elif self._sort_mode == "4TF Optimization":
            res = self._calc_4tf_score(sym)
            _sorted = self._get_sorted_ranking()
            _rank = next((i + 1 for i, r in enumerate(_sorted) if r[0] == sym), None)
            sc = res["scores"]
            ctx_f = tk.Frame(self._verdict_f, bg=DARK_PANEL)
            ctx_f.pack(fill="x", padx=10, pady=(2, 1))
            tk.Label(ctx_f, text="🎯 4TF Optimization 선정 근거 ", bg=DARK_PANEL, fg=ACCENT_BLUE,
                     font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            tk.Label(ctx_f, text=f"전체 {_rank}위 · 총 {res['total']}/{res['max']}점",
                     bg=DARK_PANEL, fg=DARK_TEXT,
                     font=("Consolas", 8, "bold"), anchor="w").pack(side="left")

            if res["base_dir"] is None:
                tk.Label(self._verdict_f, text="⚠ 방향성 불분명 (tf1 ↔) — TF정렬·거시지지 0점 처리",
                         bg=DARK_PANEL, fg=ORANGE,
                         font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=10, pady=(0, 1))

            detail_lines = [
                (f"TF정렬 {sc['align']}/4(+{sc['align']})  "
                 f"1m진입{'✅' if sc['entry'] else '—'}(+{sc['entry']})  "
                 f"거시지지 {sc['macro']}/3(+{sc['macro']})"),
                (f"ATR적정{'✅' if sc['atr'] else '—'}(+{sc['atr']})  "
                 f"거래량Top10{'✅' if sc['volume'] else '—'}(+{sc['volume']}, rank {res['vol_rank']})"),
                (f"FR중립{'✅' if sc['fr'] else '—'}(+{sc['fr']})  "
                 f"OI증가{'✅' if sc['oi'] else '—'}(+{sc['oi']})  "
                 f"세션일치{'✅' if sc['session'] else '—'}(+{sc['session']})  "
                 f"롱숏균형{'✅' if sc['balance'] else '—'}(+{sc['balance']})"),
            ]
            for dtxt in detail_lines:
                drow = tk.Frame(self._verdict_f, bg=DARK_PANEL)
                drow.pack(fill="x", padx=10, pady=(0, 1))
                tk.Label(drow, text=dtxt, bg=DARK_PANEL, fg=DIM_TEXT,
                         font=("Consolas", 8), anchor="w").pack(side="left")
            tk.Frame(self._verdict_f, bg="#2A2A2A", height=1).pack(
                fill="x", padx=10, pady=(2, 2))

        # ── Sort by="Newly Listed" 선정 근거 (4요소 점수 + 연령가중 + 전체 순위) ──
        elif self._sort_mode == "Newly Listed":
            res = self._calc_newlist_score(sym)
            ctx_f = tk.Frame(self._verdict_f, bg=DARK_PANEL)
            ctx_f.pack(fill="x", padx=10, pady=(2, 1))
            if not res["qualified"]:
                tk.Label(ctx_f,
                         text=(f"⚠ Newly Listed 자격 미달 "
                               f"(VSS {res['vss']:.2f}<1.2 & OI {res['oi']:.1f}%<3%) — 참고용 분석"),
                         bg=DARK_PANEL, fg=ORANGE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            else:
                _sorted = self._get_sorted_ranking()
                _rank = next((i + 1 for i, r in enumerate(_sorted) if r[0] == sym), None)
                tk.Label(ctx_f, text="🎯 Newly Listed 선정 근거 ", bg=DARK_PANEL, fg=ACCENT_BLUE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
                tk.Label(ctx_f, text=f"전체 {_rank}위 · 총 {res['total']}/{res['max']}점 × 연령가중 {res['age_weight']:.1f} = {res['weighted']:.1f}점",
                         bg=DARK_PANEL, fg=DARK_TEXT,
                         font=("Consolas", 8, "bold"), anchor="w").pack(side="left")
                sc = res["scores"]
                detail_lines = [
                    (f"Volume Surge VSS {res['vss']:.2f}(+{sc['surge']})  "
                     f"OI Momentum {res['oi']:.1f}%(+{sc['oi']})"),
                    (f"Price Velocity {res['chg']:.2f}%(+{sc['velocity']})  "
                     f"Funding Extreme {res['fr']:.3f}%(+{sc['funding']})"),
                ]
                for dtxt in detail_lines:
                    drow = tk.Frame(self._verdict_f, bg=DARK_PANEL)
                    drow.pack(fill="x", padx=10, pady=(0, 1))
                    tk.Label(drow, text=dtxt, bg=DARK_PANEL, fg=DIM_TEXT,
                             font=("Consolas", 8), anchor="w").pack(side="left")
            tk.Frame(self._verdict_f, bg="#2A2A2A", height=1).pack(
                fill="x", padx=10, pady=(2, 2))

        for prefix, mid, suffix, col in lines:
            row_f = tk.Frame(self._verdict_f, bg=DARK_PANEL)
            row_f.pack(fill="x", padx=10, pady=1)
            tk.Label(row_f, text=prefix, bg=DARK_PANEL, fg=DIM_TEXT,
                     font=("Segoe UI", 8, "bold"), width=4, anchor="w").pack(side="left")
            tk.Label(row_f, text=mid, bg=DARK_PANEL, fg=DARK_TEXT,
                     font=("Segoe UI", 8), anchor="w").pack(side="left")
            tk.Label(row_f, text=f"  {suffix}", bg=DARK_PANEL, fg=col,
                     font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")

        # ── Newly Listed 전용 분석 블록 ───────────────────────────
        _nl_row = next((d for d in _live_ranking() if d[0] == sym), None)
        if _nl_row and _nl_row[1] > 0:
            _lc_res = self._nl_lifecycle(sym)
            if _lc_res:
                _lc_stage, _lc_lbl, _lc_col, _lc_strat = _lc_res
                _pchg = ind.get("price_change_pct", 0.0)
                _h24p = ind.get("high_24h_pct",     0.0)
                _vss  = ind.get("vss",              1.0)
                _dv   = _nl_row[1]
                # 헤더
                tk.Frame(self._verdict_f, bg="#333333", height=1).pack(
                    fill="x", padx=10, pady=(4, 2))
                hdr_f = tk.Frame(self._verdict_f, bg=DARK_PANEL)
                hdr_f.pack(fill="x", padx=10, pady=(0, 2))
                tk.Label(hdr_f, text="★ Newly Listed 분석",
                         bg=DARK_PANEL, fg=ACCENT_BLUE,
                         font=("Segoe UI", 8, "bold")).pack(side="left")
                tk.Label(hdr_f, text=f" D+{_dv} ",
                         bg=NEW_BG, fg=NEW_FG,
                         font=("Segoe UI", 7, "bold"), padx=3).pack(side="right")
                # 분석 4줄
                nl_lines = [
                    ("단계", _lc_lbl,                                       _lc_col),
                    ("24h",  f"변화 {_pchg:+.1f}%  고점차 {_h24p:+.1f}%", DIM_TEXT),
                    ("거래", f"VSS {_vss:.1f}  OI {oi:+.1f}%",             DIM_TEXT),
                    ("전략", _lc_strat,                                      ACCENT_BLUE),
                ]
                for pfx, txt, col2 in nl_lines:
                    r = tk.Frame(self._verdict_f, bg=DARK_PANEL)
                    r.pack(fill="x", padx=10, pady=1)
                    tk.Label(r, text=pfx, bg=DARK_PANEL, fg=DIM_TEXT,
                             font=("Segoe UI", 8, "bold"), width=4,
                             anchor="w").pack(side="left")
                    tk.Label(r, text=txt, bg=DARK_PANEL, fg=col2,
                             font=("Segoe UI", 8), anchor="w").pack(side="left")

        # ── 하단: 롱·숏 양방향 엔진 판단 ─────────────────────────
        tk.Frame(self._verdict_f, bg="#333333", height=1).pack(
            fill="x", padx=10, pady=(4, 2))

        l_s, l_c, s_s, s_c = self._engine_status(phase, long_r)
        long_ret, short_ret = self._calc_both_returns(ind)

        # 수익 색상: 엔진 상태에 연동 (부적합→DIM, 경고→YELLOW, 진입→원색)
        long_ret_col  = POSITIVE  if "✅" in l_s else (YELLOW if "⚠️" in l_s else DIM_TEXT)
        short_ret_col = NEGATIVE  if "✅" in s_s else (ORANGE if "⚠️" in s_s else DIM_TEXT)

        # 롱 엔진 행
        long_row = tk.Frame(self._verdict_f, bg=DARK_PANEL)
        long_row.pack(fill="x", padx=10, pady=(2, 1))
        tk.Label(long_row, text="▲ 롱", bg=DARK_PANEL, fg=POSITIVE,
                 font=("Segoe UI", 9, "bold"), width=5, anchor="w").pack(side="left")
        tk.Label(long_row, text=l_s, bg=DARK_PANEL, fg=l_c,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(2, 6))
        tk.Label(long_row, text=long_ret, bg=DARK_PANEL, fg=long_ret_col,
                 font=("Consolas", 8)).pack(side="right")

        # 숏 엔진 행
        short_row = tk.Frame(self._verdict_f, bg=DARK_PANEL)
        short_row.pack(fill="x", padx=10, pady=(1, 3))
        tk.Label(short_row, text="▼ 숏", bg=DARK_PANEL, fg=NEGATIVE,
                 font=("Segoe UI", 9, "bold"), width=5, anchor="w").pack(side="left")
        tk.Label(short_row, text=s_s, bg=DARK_PANEL, fg=s_c,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(2, 6))
        tk.Label(short_row, text=short_ret, bg=DARK_PANEL, fg=short_ret_col,
                 font=("Consolas", 8)).pack(side="right")

        # 권장 레버리지 (1행: 텍스트 좌 + 바 우)
        tk.Frame(self._verdict_f, bg="#2A2A2A", height=1).pack(
            fill="x", padx=10, pady=(1, 2))
        lev_row = tk.Frame(self._verdict_f, bg=DARK_PANEL)
        lev_row.pack(fill="x", padx=10, pady=(2, 5))
        tk.Label(lev_row,
                 text=f"권장 레버리지  {rec_lev}배 이하  (ATR {ind.get('atr',2.0):.1f}%)",
                 bg=DARK_PANEL, fg=DARK_TEXT,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
        cv_lev = tk.Canvas(lev_row, bg="#1A1A1A", height=12,
                           highlightthickness=0)
        cv_lev.pack(side="left", fill="x", expand=True, padx=(18, 18))
        def _draw_lev(event=None, cv=cv_lev, safe=rec_lev):
            cv.delete("all")
            w = cv.winfo_width()
            if w < 4: return
            safe_px = int(w * min(safe / 50, 1.0))
            warn_px = int(w * min(safe * 2 / 50, 1.0))
            cv.create_rectangle(0,       1, safe_px, 11, fill=POSITIVE, outline="")
            cv.create_rectangle(safe_px, 1, warn_px, 11, fill=YELLOW,   outline="")
            cv.create_rectangle(warn_px, 1, w,       11, fill=NEGATIVE,  outline="")
            cv.create_text(w // 2, 6, text=f"{safe}배",
                           fill=DARK_TEXT, font=("Segoe UI", 7, "bold"))
        cv_lev.bind("<Configure>", _draw_lev)
        cv_lev.after(15, _draw_lev)

    # ─── 롱/숏 엔진 양방향 상태 판단 ────────────────────────────
    @staticmethod
    def _engine_status(phase: str, long_r: float):
        """→ (long_stat, long_col, short_stat, short_col)"""
        pct = int(long_r * 100)
        sct = 100 - pct

        # ── 롱 엔진 ──
        if "상승 과열" in phase:
            l_s, l_c = "⚠️ 과열·고점 경계", ORANGE
        elif pct >= 65 and any(k in phase for k in ("상승 전환","상승 초기","상승 진행")):
            l_s, l_c = "✅ 주력 진입",     POSITIVE
        elif pct >= 55:
            l_s, l_c = "✅ 진입 검토",     "#8ad7b5"
        elif pct >= 45:
            l_s, l_c = "⚠️ 신중 접근",    YELLOW
        elif pct >= 30:
            l_s, l_c = "⏸ 대기",           DIM_TEXT
        else:
            l_s, l_c = "❌ 부적합",        ORANGE

        # ── 숏 엔진 ──
        if "하락 과매도" in phase:
            s_s, s_c = "⚠️ 과매도·저점 경계", ORANGE
        elif sct >= 65 and any(k in phase for k in ("하락 전환","하락 초기","하락 진행")):
            s_s, s_c = "✅ 주력 진입",     NEGATIVE
        elif sct >= 55:
            s_s, s_c = "✅ 진입 검토",     ORANGE
        elif sct >= 45:
            s_s, s_c = "⚠️ 신중 접근",    YELLOW
        elif sct >= 30:
            s_s, s_c = "⏸ 대기",           DIM_TEXT
        else:
            s_s, s_c = "❌ 부적합",        DIM_TEXT

        # 상승 계열 phase에서 숏 ✅ 억제 (phase-energy 모순 방지)
        if any(k in phase for k in ("상승 전환", "상승 초기", "상승 진행", "상승 과열")):
            if "✅" in s_s:
                s_s, s_c = "⏸ 대기", DIM_TEXT

        # 전환 대기 특수 처리 (최종 override)
        if "전환 대기" in phase:
            l_s, l_c = "⏸ 방향 대기", YELLOW
            s_s, s_c = "⏸ 방향 대기", YELLOW

        return l_s, l_c, s_s, s_c

    # ─── 롱/숏 양방향 예상 수익 ──────────────────────────────────
    @staticmethod
    def _calc_both_returns(ind: dict) -> tuple:
        """항상 롱·숏 양방향 수익 범위 반환"""
        atr   = ind.get("atr", 2.0)
        liq_l = abs(ind.get("liq_long_pct",  -1.5))
        liq_s = abs(ind.get("liq_short_pct",  1.5))
        base      = round(atr * 0.7, 1)
        long_ret  = f"+{min(base, liq_s):.1f}%~+{max(base, liq_s):.1f}%"
        short_ret = f"+{min(base, liq_l):.1f}%~+{max(base, liq_l):.1f}%"
        return long_ret, short_ret

    # ─── 에너지 계산 ──────────────────────────────────────────
    @staticmethod
    def _calc_energy(ind: dict) -> float:
        """BPR 50% + RSI 25% + VWAP 15% + Stoch 10% 가중 합산 → 롱 에너지 비율"""
        bpr     = ind.get("bpr",  0.5)
        rsi     = ind.get("rsi", 50.0)
        stoch_k = ind.get("tf1h", {}).get("k", 50.0)   # KeyError 방지
        vwap    = ind.get("vwap", "")
        raw = (bpr * 0.50
               + (rsi     / 100.0) * 0.25
               + (0.15 if "위" in vwap else 0.0)
               + (stoch_k / 100.0) * 0.10)
        return max(0.05, min(0.95, raw))

    def _get_player_tags_for_sym(self, sym: str) -> list:
        for data in _live_ranking():
            if data[0] == sym:
                return data[11]
        return []

    def _get_phase_for_sym(self, sym: str) -> tuple:
        for data in _live_ranking():
            if data[0] == sym:
                return data[8], data[9]
        return "", DIM_TEXT

    def _nl_lifecycle(self, sym: str, days: int | None = None):
        """신규 상장 코인 라이프사이클 단계 감지 → (stage, label, color, strategy) 또는 None
        days: 호출자가 이미 알고 있을 때 전달 → _live_ranking() O(n) 탐색 생략
        """
        if days is None:
            _row = next((d for d in _live_ranking() if d[0] == sym), None)
            if not _row or _row[1] == 0:
                return None
            days = _row[1]
        elif days == 0:
            return None
        ind = get_ind(sym)
        res = NewlistedLifecycle.analyze(
            days             = days,
            vss              = ind.get("vss",              1.0),
            oi_change_pct    = ind.get("oi_change",        0.0),
            price_change_pct = ind.get("price_change_pct", 0.0),
            high_24h_pct     = ind.get("high_24h_pct",     0.0),
        )
        if res is None:
            return None
        return (res.stage, res.label, res.color, res.strategy)

    # ─── Col 4: Player Detection 상세 + 에너지 ────────────────
    def _refresh_energy(self) -> None:
        for w in self._energy_f.winfo_children():
            w.destroy()

        sym    = self._sel_var.get()
        ind    = get_ind(sym)
        long_r = self._calc_energy(ind)
        long_p = int(long_r * 100)
        short_p = 100 - long_p

        player_tags = ind.get("_player_tags", [])

        # ── Sort by="Sharp rise"/"Sharp decline" 모드: Player 가산점(rise_kw/decline_kw 매칭, +2점) 요약 + 태그 우선 배치 ──
        _rise_kw    = ("고래 매수", "세력 매집", "기관 유입", "FR-")
        _decline_kw = ("FR+", "FOMO", "롱 스퀴즈", "청산 헌터", "헌터", "세력 분산")
        _is_rise_mode    = self._sort_mode == "Sharp rise"
        _is_decline_mode = self._sort_mode == "Sharp decline"
        _squeeze_kw = _rise_kw if _is_rise_mode else _decline_kw
        if _is_rise_mode or _is_decline_mode:
            _has_bonus_tag = any(any(kw in t[0] for kw in _squeeze_kw) for t in player_tags)
            _bonus_col = POSITIVE if _has_bonus_tag else DIM_TEXT
            _bonus_txt = "✅ +2/2점" if _has_bonus_tag else "— 0/2점"
            sum_f = tk.Frame(self._energy_f, bg=DARK_PANEL)
            sum_f.pack(fill="x", padx=8, pady=(4, 2))
            tk.Label(sum_f, text=f"🎯 {self._sort_mode} Player 가산점", bg=DARK_PANEL, fg=ACCENT_BLUE,
                     font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            tk.Label(sum_f, text=f"  {_bonus_txt}", bg=DARK_PANEL, fg=_bonus_col,
                     font=("Consolas", 8, "bold"), anchor="w").pack(side="left")
            tk.Frame(self._energy_f, bg="#2A2A2A", height=1).pack(fill="x", padx=8, pady=(2, 2))
            if player_tags:
                player_tags = sorted(
                    player_tags,
                    key=lambda t: 0 if any(kw in t[0] for kw in _squeeze_kw) else 1)

        # ── Player Detection 상세 ─────────────────────────────
        if not player_tags:
            no_f = tk.Frame(self._energy_f, bg=DARK_PANEL, pady=8)
            no_f.pack(fill="x", padx=8)
            tk.Label(no_f, text="─  감지된 주요 플레이어 없음",
                     bg=DARK_PANEL, fg=DIM_TEXT,
                     font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=4)
            tk.Label(no_f, text="소매 투자자 중심 거래 진행 중",
                     bg=DARK_PANEL, fg=DIM_TEXT,
                     font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=4, pady=(2, 0))
            tk.Label(no_f, text="→ 추세 단계 기준으로 엔진 방향 판단 권장",
                     bg=DARK_PANEL, fg=DIM_TEXT,
                     font=("Segoe UI", 8, "bold"), anchor="w").pack(
                         fill="x", padx=4, pady=(1, 4))
        else:
            for i, tag in enumerate(player_tags):
                tag_text, tag_color, strength_pct = tag[0], tag[1], tag[2] if len(tag) > 2 else 60
                if i > 0:
                    tk.Frame(self._energy_f, bg="#2A2A2A", height=1).pack(
                        fill="x", padx=12, pady=(2, 2))
                item_f = tk.Frame(self._energy_f, bg="#1A1A1A", pady=4)
                item_f.pack(fill="x", padx=8, pady=(4 if i == 0 else 0, 0))

                # 플레이어명 + 방향 + mini Canvas 강도 바 + %
                action, _, rec_col = self._lookup_player_info(tag_text)

                # 방향 텍스트 (rec_col 기반)
                if rec_col in (POSITIVE, "#8ad7b5"):
                    dir_txt, dir_col = "롱 우세", rec_col
                elif rec_col == NEGATIVE:
                    dir_txt, dir_col = "숏 우세", NEGATIVE
                elif rec_col == ORANGE:
                    dir_txt, dir_col = "주의",    ORANGE
                else:
                    dir_txt, dir_col = "중립",    DIM_TEXT

                hdr_f = tk.Frame(item_f, bg="#1A1A1A")
                hdr_f.pack(fill="x", padx=6, pady=(0, 2))
                # RIGHT 먼저 pack → bar 70px 공간 보장
                tk.Label(hdr_f, text=f"{strength_pct}%", bg="#1A1A1A", fg=tag_color,
                         font=("Consolas", 8, "bold"), anchor="e").pack(side="right")
                bar_cv = tk.Canvas(hdr_f, bg="#252525", height=8, width=70,
                                   highlightthickness=0)
                bar_cv.pack(side="right", padx=(4, 4))
                # LEFT 나중에 pack → 남은 공간 채움
                tk.Label(hdr_f, text=tag_text, bg="#1A1A1A", fg=tag_color,
                         font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left")
                tk.Label(hdr_f, text=f"  {dir_txt}", bg="#1A1A1A", fg=dir_col,
                         font=("Segoe UI", 8, "bold")).pack(side="left")
                if (_is_rise_mode or _is_decline_mode) and any(kw in tag_text for kw in _squeeze_kw):
                    tk.Label(hdr_f, text="  🎯 가산", bg="#1A1A1A", fg=ACCENT_BLUE,
                             font=("Segoe UI", 7, "bold")).pack(side="left")
                ratio = strength_pct / 100.0
                def _bar_draw(event=None, cv=bar_cv, r=ratio, c=tag_color):
                    cv.delete("all")
                    w = cv.winfo_width()
                    if w < 2: return
                    filled = int(w * r)
                    cv.create_rectangle(0, 0, w, 8, fill="#252525", outline="")
                    if filled > 0:
                        cv.create_rectangle(0, 1, filled, 7, fill=c, outline="")
                bar_cv.bind("<Configure>", _bar_draw)
                bar_cv.after(15, _bar_draw)

                # 시장 구조 메시지 (활동 유형·강도·지속성)
                tk.Label(item_f, text=action, bg="#1A1A1A", fg=DIM_TEXT,
                         font=("Segoe UI", 8), anchor="w",
                         wraplength=240).pack(fill="x", padx=6, pady=(0, 4))

            # 복수 플레이어 통합 메시지
            if len(player_tags) >= 2:
                cmb_msg, cmb_col = self._player_combined_msg(player_tags)
                if cmb_msg:
                    tk.Frame(self._energy_f, bg="#333333", height=1).pack(
                        fill="x", padx=8, pady=(6, 2))
                    tk.Label(self._energy_f, text=cmb_msg,
                             bg="#161B2E", fg=cmb_col,
                             font=("Segoe UI", 8, "bold"),
                             wraplength=200, justify="center",
                             pady=5).pack(fill="x", padx=8, pady=(0, 2))

        # ── 에너지 균형 (단일 분할 바) ─────────────────────────
        tk.Frame(self._energy_f, bg="#2A2A2A", height=1).pack(
            fill="x", padx=8, pady=(6, 0))
        tk.Label(self._energy_f, text="⚡ 에너지 균형",
                 bg=DARK_PANEL, fg=ACCENT_BLUE,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(4, 2))

        diff    = long_p - short_p
        dom_col = POSITIVE if diff > 0 else NEGATIVE
        dom_txt = f"▲ +{abs(diff)}%p" if diff > 0 else f"▼ +{abs(diff)}%p"

        eb_row = tk.Frame(self._energy_f, bg=DARK_PANEL, pady=3)
        eb_row.pack(fill="x", padx=8, pady=(0, 5))

        # RIGHT 먼저 pack → canvas가 중간 공간 채움
        tk.Label(eb_row, text=dom_txt, bg=DARK_PANEL, fg=dom_col,
                 font=("Consolas", 8, "bold")).pack(side="right", padx=(4, 2))
        tk.Label(eb_row, text=f"숏 {short_p}%", bg=DARK_PANEL, fg=NEGATIVE,
                 font=("Consolas", 8, "bold"), width=6, anchor="e").pack(side="right")
        # LEFT
        tk.Label(eb_row, text=f"롱 {long_p}%", bg=DARK_PANEL, fg=POSITIVE,
                 font=("Consolas", 8, "bold"), width=6, anchor="w").pack(side="left")
        # 분할 바 캔버스 (중간 공간 채움)
        eb_cv = tk.Canvas(eb_row, bg="#1A1A1A", height=10, highlightthickness=0)
        eb_cv.pack(side="left", fill="x", expand=True, padx=(3, 3))

        def _draw_split(e=None, cv=eb_cv, lr=long_r):
            cv.delete("all"); w = cv.winfo_width()
            if w < 4: return
            lp = int(w * lr)
            cv.create_rectangle(0, 0, w, 10, fill="#1E1E1E", outline="")
            if lp > 0:
                cv.create_rectangle(0, 1, lp, 9, fill=POSITIVE, outline="")
                cv.create_rectangle(1, 1, max(2, lp-1), 3,
                                    fill="#FFFFFF", outline="", stipple="gray50")
            if lp < w:
                cv.create_rectangle(lp, 1, w, 9, fill=NEGATIVE, outline="")
            if 0 < lp < w:
                cv.create_line(lp, 0, lp, 10, fill="#FFFFFF", width=1)

        eb_cv.bind("<Configure>", _draw_split)
        eb_cv.after(15, _draw_split)

    # ─── Player Detection 해석 사전 ──────────────────────────
    # key: tag_text 안에 포함된 키워드 (긴 것 우선 매칭)
    # value: (행동 설명, 해석+추천, 추천 색상)
    _PLAYER_INFO: dict = {
        "세력 매집":   ("가격 횡보 속 대규모 포지션 지속 누적 중",       "", POSITIVE),
        "세력 분산":   ("상승 구간 내 보유 물량 단계적 분산 진행",        "", NEGATIVE),
        "고래 매수":   ("대형 단일 체결 — 즉각적 매수 압력 발생",         "", POSITIVE),
        "고래 매도":   ("대형 단일 체결 — 즉각적 매도 압력 발생",         "", NEGATIVE),
        "기관 유입":   ("기관급 롱 비율 급증 — 중기 자금 유입 진행 중",   "", POSITIVE),
        "롱 스퀴즈":   ("롱 포지션 극단 과밀 — 강제 청산 연쇄 위험 누적", "", NEGATIVE),
        "청산 헌터":   ("롱 청산 구간 세력 집중 활동 포착 중",            "", NEGATIVE),
        "FOMO 극단":   ("개인 롱 극단 쏠림 — 90%+ 과밀 누적 상태",       "", ORANGE),
        "FR+ 과열":    ("롱 과밀 — 펀딩비 과열로 비용 압박 강함",         "", ORANGE),
        "FR-":         ("숏 과밀 — 음수 펀딩비로 상방 압박 형성 중",      "", "#8ad7b5"),
    }

    def _lookup_player_info(self, tag_text: str) -> tuple:
        for key in sorted(self._PLAYER_INFO.keys(), key=len, reverse=True):
            if key in tag_text:
                return self._PLAYER_INFO[key]
        return ("활동 감지", "추세 방향 확인 후 대응 권장", DIM_TEXT)

    @staticmethod
    def _player_combined_msg(player_tags: list) -> tuple:
        if len(player_tags) < 2:
            return None, None
        texts = " ".join(t[0] for t in player_tags if t)
        if "세력 매집" in texts and ("고래" in texts or "기관" in texts):
            return "세력 + 대형 자금 동시 매집\n→ 가장 강력한 상승 신호 — 롱 엔진 즉시 진입 강력 권장", POSITIVE
        if "세력 분산" in texts and ("청산 헌터" in texts or "헌터" in texts):
            return "세력 이탈 + 청산 헌터 동시 활동\n→ 강한 하락 압력 — 숏 엔진 즉시 진입 강력 권장", NEGATIVE
        if "FOMO" in texts and "FR+" in texts:
            return "개인 FOMO + 펀딩비 과열 이중 경고\n→ 상승 말기 역추세 — 숏 엔진 역발상 검토", ORANGE
        if "FR-" in texts and "세력 매집" in texts:
            return "펀딩비 반전 + 세력 매집 이중 상승 신호\n→ 롱 엔진 강력 추천", POSITIVE
        if "롱 스퀴즈" in texts and ("청산 헌터" in texts or "헌터" in texts):
            return "롱 스퀴즈 + 청산 헌터 이중 하락 신호\n→ 숏 엔진 즉시 진입 최적 타이밍", NEGATIVE
        up = sum(1 for k in ["매집", "매수", "유입", "FR-"] if k in texts)
        dn = sum(1 for k in ["분산", "청산", "스퀴즈", "FOMO", "FR+"] if k in texts)
        if up >= 2:
            return "복수 상승 플레이어 동시 활동\n→ 롱 에너지 복합 확인 — 롱 엔진 진입 권장", POSITIVE
        if dn >= 2:
            return "복수 하락 플레이어 동시 활동\n→ 숏 에너지 복합 확인 — 숏 엔진 진입 권장", NEGATIVE
        return None, None
