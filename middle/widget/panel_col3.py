"""
middle/widget/panel_col3.py
3열 분석 패널 (기술지표/파생/에너지/종합판단) 믹스인
"""
from __future__ import annotations
from datetime import datetime
import tkinter as tk
import tkinter.ttk as ttk
from middle.widget.constants import *

# ── shared_context에서 헬퍼 함수 import (단일 정의, 중복 없음) ──
from middle.widget.shared_context import (bars_ready, get_ind, _live_ranking, get_ticker_info, get_player, get_listing_days,
                                         get_forecast, forecast_enabled, get_row)
import middle.widget.shared_context as _ctx
from middle.col3_analysis_panels.derivative_analysis.open_interest import OpenInterestPanel
from middle.col3_analysis_panels.derivative_analysis.funding_rate import FundingRatePanel
from middle.col3_analysis_panels.derivative_analysis.longshort_ratio import LongShortPanel
from middle.col3_analysis_panels.technical_analysis.rsi import RSI
from middle.col3_analysis_panels.technical_analysis.bpr import BPR
from middle.col3_analysis_panels.technical_analysis.vss import VSS
from middle.analysis.atr_percent import AtrPercent
from middle.col3_analysis_panels.comprehensive_analysis.technical_verdict import TechnicalVerdictPanel
from middle.col3_analysis_panels.comprehensive_analysis.derivative_verdict import DerivativeVerdictPanel
from middle.analysis.newlisted_lifecycle import lifecycle_summary
from middle.analysis.tag_detector import TagDetector
from middle.col1_ranking.ranking.sharp_rise_scorer import SharpRiseScorer
from middle.col1_ranking.ranking.sharp_decline_scorer import SharpDeclineScorer
from middle.analysis.trend import trend_text


class _Col3Mixin:
    """3열 분석 패널 믹스인."""

    # ─── 심볼 헤더 갱신 ───────────────────────────────────────
    def _refresh_header(self) -> None:
        for w in self._hdr_f.winfo_children():
            w.destroy()

        sym  = self._sel_var.get()
        # 1열 행과 같은 값 — 거래량 상위 200 밖 종목(24h Ticker·Newly Listed 목록)도 포함 (data_manager.get_row 단일 정의)
        data = get_row(sym)

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
            # 시세 없는 심볼(거래 목록에 없음): 심볼명 + —— (M4 준비/추세 단계) + 등락률 + 순위 뱃지
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
         phase, phase_color, phase_priority) = data

        left = tk.Frame(self._hdr_f, bg=DARK_PANEL)
        left.pack(side="left", padx=16)

        tk.Label(left, text=symbol, bg=DARK_PANEL, fg=DARK_TEXT,
                 font=("Segoe UI", 10, "bold")).pack(side="left")

        if 0 < days <= 30:   # 1열 신규 배지와 같은 조건 (상장 30일 이하)
            tk.Label(left, text=f" 신규{days}일",
                     bg=NEW_BG, fg=NEW_FG,
                     font=("Segoe UI", 7, "bold"), padx=3).pack(side="left", padx=(6, 0))

        tk.Label(left, text=f"  {tf_text} ", bg=DARK_PANEL, fg=tf_color,
                 font=("Segoe UI", 9, "bold"), padx=4, pady=1).pack(side="left", padx=(10, 0))

        tk.Label(left, text=phase, bg=DARK_PANEL, fg=phase_color,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(6, 0))

        tk.Label(left, text=change, bg=DARK_PANEL, fg=change_color,
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=(10, 0))

        info = get_ticker_info(sym)
        vol_rank = info[1] if info else 999
        if vol_rank <= 200:
            tk.Label(left, text="  TOP 200 ",
                     bg="#0A1F0A", fg=POSITIVE,
                     font=("Segoe UI", 7, "bold"), padx=3).pack(side="left", padx=(6, 0))
        else:   # 거래량 상위 200 밖 (24h Ticker·Newly Listed 목록 종목) — 거래량 순위 뱃지
            tk.Label(left, text=f"  {vol_rank}위 ",
                     bg="#2A1A00", fg="#CC6600",
                     font=("Segoe UI", 7, "bold"), padx=3).pack(side="left", padx=(6, 0))

    # ─── Assign 버튼 처리 ─────────────────────────────────────
    def _on_assign(self, symbol: str) -> None:
        if self._assigned_sym == symbol:
            self._assigned_sym = None
            if self._shared_sym is not None:
                self._shared_sym.set("")        # 배치 해제
        else:
            if _ctx._bl_mgr is not None and _ctx._bl_mgr.is_blacklisted(symbol):
                self._set_header_message(
                    f"⛔ {symbol} — 블랙리스트 등록 심볼이므로 배정할 수 없습니다")
                return
            _wide = _ctx.get_wide_spread(symbol)
            if _wide is not None:
                self._set_header_message(
                    f"⛔ {symbol} — 호가 스프레드 {_wide:.3f}% (최근 10분 이내 표본 중앙값)가 "
                    f"기준 {_ctx.MAX_SPREAD_PCT}%를 초과해 배정할 수 없습니다")
                return
            self._assigned_sym = symbol
            if self._shared_sym is not None:
                self._shared_sym.set(symbol)    # bottom module 에 즉시 전달
        self._refresh_header()

    def _on_shared_sym_changed(self, *_) -> None:
        """bottom [Clear] 등 외부에서 shared_sym 변경 시 Assign 버튼 동기화"""
        if self._shared_sym is None:
            return
        new_val = self._shared_sym.get()
        if new_val == "":
            if self._assigned_sym is not None:
                self._assigned_sym = None
                self._refresh_header()
        else:
            if self._assigned_sym != new_val:
                self._assigned_sym = new_val
                self._refresh_header()

    # ─── 지표 패널 갱신 (좌측 230px 세로 배치) ──────────────────
    def _refresh_indicators(self) -> None:
        for w in self._ind_f.winfo_children():
            w.destroy()

        sym  = self._sel_var.get()
        ind  = get_ind(sym)
        _days = get_listing_days(sym)   # 1열 행·Newly Listed와 같은 정의 (거래량 상위 200 밖 포함)

        # ── 신규 상장 코인 분석 신뢰도 경고 배너 ────────────────
        if _days > 0:
            if _days <= 7:
                _warn_bg  = "#1A0A00"
                _warn_col = ORANGE
                _warn_ico = "⚠"
                _warn_ttl = f"D+{_days} Ultra New — 데이터 부족"
                _valid    = "✅ 유효: 에너지·VSS·Player·OI·FR"
                _invalid  = "❌ 제한: M4 준비·추세·4TF·Macro"
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
            # ── 라이프사이클 감지 결과 — 봉 지표 실제 값일 때만 (N7: 기본값으로 '펌프 미발생' 표시 방지) ──
            _lc_res = lifecycle_summary(_days, ind) if bars_ready(sym) else None
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

            # Sort by="4TF Optimization" 모드: ATR은 점수 항목 아님(2026-11-16 제거) — 엔진 4TF 모드 G4 범위 안 여부만 표시
            if name == "ATR%" and self._sort_mode == "4TF Optimization":
                _band4 = _ctx.engine_atr_band("4TF Optimization")
                if _band4 is not None:
                    _ok = _band4[0] <= val <= _band4[1]
                    tk.Label(row, text=f"  엔진 4TF ATR 범위 {_band4[0]:.2f}~{_band4[1]:.1f}% {'✅' if _ok else '❌'}",
                             bg=DARK_PANEL, fg=POSITIVE if _ok else ORANGE,
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
            # T6: 점수 함수 결과 그대로 — 점수 기준은 1시간 OI(위 수치는 10분 OI)
            _res4b = self._calc_4tf_score(sym)
            _oi_ok = _res4b["scores"]["oi"] == 1
            tk.Label(oi_row, text=f"🎯 OI 1h {_res4b['oi']:+.1f}% {'✅+1' if _oi_ok else '—0'}",
                     bg=DARK_PANEL, fg=ACCENT_BLUE if _oi_ok else DIM_TEXT,
                     font=("Segoe UI", 7, "bold")).pack(side="right")
        if self._sort_mode == "Newly Listed":
            _s_oi_nl = self._calc_newlist_score(sym)["scores"]["oi"]
            tk.Label(oi_row, text=f"🎯 OI 1h Momentum (+{_s_oi_nl}점)",
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
            # T6: 점수 함수 결과 그대로 (추세쏠림: 상승 롱>60 / 하락 롱<40)
            _bal_ok = self._calc_4tf_score(sym)["scores"]["balance"] == 1
            tk.Label(ls_row, text=f"🎯 추세쏠림 {'✅+1' if _bal_ok else '—0'}",
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

        self._render_forecast(sym)

        lines = []
        # 기술 요약 — TechnicalVerdictPanel 위임
        tv = TechnicalVerdictPanel.analyze(
            rsi_1h    = ind.get("rsi", 50.0),
            bpr       = ind.get("bpr", 0.0),
            ema_align = ind.get("align", ""),
        )
        lines.append((tv.prefix, tv.summary, tv.suffix, tv.color))
        # 파생 요약/주의/위험 — DerivativeVerdictPanel 위임
        # Player 태그 — 에너지 패널·1열과 같은 결과 (data_manager.get_player 단일 정의, 표시용 상위 4개)
        _det = get_player(sym)
        player_tags = [(t.tag_text, t.tag_color, t.strength_pct) for t in _det.tags] if _det else []
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
            _row = get_row(sym)   # 24h 목록은 거래량 상위 200 밖 종목 포함
            if _row is not None:
                # 1열에 표시된 순위 우선 (분석 중 1열은 멈춰 있음 — 1열 # 칸과 같은 숫자), 1열에 없으면 실시간 순위
                _rank = next((i + 1 for i, (_, s) in enumerate(getattr(self, "_row_frames", [])) if s == sym), None)
                if _rank is None:
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

        # ── Sort by="Sharp rise" 선정 근거 (5요소 점수 breakdown + 전체 순위) ──
        elif self._sort_mode == "Sharp rise":
            res = self._calc_rise_score(sym)
            ctx_f = tk.Frame(self._verdict_f, bg=DARK_PANEL)
            ctx_f.pack(fill="x", padx=10, pady=(2, 1))
            if not res["ready"]:
                # 갱신 대상 밖·데이터 준비 전 — 옛 값·기본값이라 채점하지 않음 (2026-11-16)
                tk.Label(ctx_f, text="⚠ Sharp rise 채점 보류 (갱신 대상 밖·데이터 준비 중) — 참고용 분석",
                         bg=DARK_PANEL, fg=ORANGE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            elif not res["qualified"]:
                tk.Label(ctx_f, text=f"⚠ Sharp rise 자격 미달 (SR {res['sr']:.0f}%<50% & FR 미달) — 참고용 분석",
                         bg=DARK_PANEL, fg=ORANGE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            else:
                _sorted = self._get_sorted_ranking()
                _rank = next((i + 1 for i, r in enumerate(_sorted) if r[0] == sym), None)
                tk.Label(ctx_f, text="🎯 Sharp rise 선정 근거 ", bg=DARK_PANEL, fg=ACCENT_BLUE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
                # 자격은 있으나 목록에 없음(4점 미만·20위 밖·블랙리스트) → 'None위' 대신 목록 밖 표시 (2026-11-16)
                _rank_txt = f"전체 {_rank}위" if _rank is not None else "목록 밖 (4점 미만·20위 밖)"
                tk.Label(ctx_f, text=f"{_rank_txt} · 총 {res['total']}/{res['max']}점",
                         bg=DARK_PANEL, fg=DARK_TEXT,
                         font=("Consolas", 8, "bold"), anchor="w").pack(side="left")
                sc = res["scores"]
                detail_lines = [
                    (f"숏쏠림 {res['sr']:.0f}%(+{sc['sr']})  "
                     f"FR {res['fr']:+.3f}%(+{sc['fr']})"),
                    (f"OI(1h) {res['oi']:+.1f}%(+{sc['oi']})  "
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

        # ── Sort by="Sharp decline" 선정 근거 (5요소 점수 breakdown + 전체 순위) ──
        elif self._sort_mode == "Sharp decline":
            res = self._calc_decline_score(sym)
            ctx_f = tk.Frame(self._verdict_f, bg=DARK_PANEL)
            ctx_f.pack(fill="x", padx=10, pady=(2, 1))
            if not res["ready"]:
                # 갱신 대상 밖·데이터 준비 전 — 옛 값·기본값이라 채점하지 않음 (2026-11-16)
                tk.Label(ctx_f, text="⚠ Sharp decline 채점 보류 (갱신 대상 밖·데이터 준비 중) — 참고용 분석",
                         bg=DARK_PANEL, fg=ORANGE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            elif not res["qualified"]:
                # 미달 조건만 표시 (롱 50% 미만 / FR 음수)
                _why = (f"롱쏠림 {res['lr']:.0f}% < 50%" if res["lr"] < 50.0 else f"FR {res['fr']:+.3f}% 음수")
                tk.Label(ctx_f, text=f"⚠ Sharp decline 자격 미달 ({_why}) — 참고용 분석",
                         bg=DARK_PANEL, fg=ORANGE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            else:
                _sorted = self._get_sorted_ranking()
                _rank = next((i + 1 for i, r in enumerate(_sorted) if r[0] == sym), None)
                tk.Label(ctx_f, text="🎯 Sharp decline 선정 근거 ", bg=DARK_PANEL, fg=ACCENT_BLUE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
                # 자격은 있으나 목록에 없음(4점 미만·30위 밖·블랙리스트) → 'None위' 대신 목록 밖 표시 (2026-11-16)
                _rank_txt = f"전체 {_rank}위" if _rank is not None else "목록 밖 (4점 미만·30위 밖)"
                tk.Label(ctx_f, text=f"{_rank_txt} · 총 {res['total']}/{res['max']}점",
                         bg=DARK_PANEL, fg=DARK_TEXT,
                         font=("Consolas", 8, "bold"), anchor="w").pack(side="left")
                sc = res["scores"]
                detail_lines = [
                    (f"롱쏠림 {res['lr']:.0f}%(+{sc['lr']})  "
                     f"FR {res['fr']:+.3f}%(+{sc['fr']})"),
                    (f"OI(1h) {res['oi']:+.1f}%(+{sc['oi']})  "
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

        # ── Sort by="Volatility" 선정 근거 (ATR% + 변동성 등급 + 엔진 ATR 범위 + 전체 순위) ──
        elif self._sort_mode == "Volatility":
            _row = next((d for d in _live_ranking() if d[0] == sym), None)
            if _row is not None:
                ctx_f = tk.Frame(self._verdict_f, bg=DARK_PANEL)
                ctx_f.pack(fill="x", padx=10, pady=(2, 1))
                if not bars_ready(sym):
                    # 갱신 대상 밖·데이터 준비 전 — 옛 값·기본값 ATR이라 표시하지 않음 (V6)
                    tk.Label(ctx_f, text="⚠ Volatility 채점 보류 (갱신 대상 밖·데이터 준비 중) — 참고용 분석",
                             bg=DARK_PANEL, fg=ORANGE,
                             font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
                elif not ind.get("_atr_ready"):
                    tk.Label(ctx_f, text="⚠ Volatility ATR 데이터 부족 (1h 봉 15개 미만·조회 실패)",
                             bg=DARK_PANEL, fg=ORANGE,
                             font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
                else:
                    _sorted = self._get_sorted_ranking()
                    _rank = next((i + 1 for i, r in enumerate(_sorted) if r[0] == sym), None)
                    _atr = ind.get("atr", 2.0)
                    tk.Label(ctx_f, text="🎯 Volatility 선정 근거 ", bg=DARK_PANEL, fg=ACCENT_BLUE,
                             font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
                    tk.Label(ctx_f, text=f"ATR {_atr:.2f}% ({AtrPercent.label(_atr)})",   # 소수 2자리 (V5)
                             bg=DARK_PANEL, fg=AtrPercent.color(_atr),
                             font=("Consolas", 8, "bold"), anchor="w").pack(side="left")
                    # 목록 밖(100위 밖·블랙리스트) → 순위 대신 목록 밖 표시 (V6)
                    _rank_txt = f"  (전체 {_rank}위)" if _rank is not None else "  (목록 밖 — 100위 밖)"
                    tk.Label(ctx_f, text=_rank_txt, bg=DARK_PANEL, fg=DIM_TEXT,
                             font=("Segoe UI", 8), anchor="w").pack(side="left")
                    # 엔진 Volatility 모드 G4 ATR% 허용 범위 — 1열 '엔진 ATR 범위' 열과 같은 판정 (진입 보장 아님)
                    _band = _ctx.engine_atr_band("Volatility")
                    if _band is not None:
                        _lo, _hi = _band
                        if _atr > _hi:
                            _btxt, _bcol = f"▲ 엔진 ATR 범위 초과 (>{_hi:.1f}%) — 진입 차단", ORANGE
                        elif _atr < _lo:
                            _btxt, _bcol = f"▼ 엔진 ATR 범위 미만 (<{_lo:.2f}%) — 진입 차단", DIM_TEXT
                        else:
                            _btxt, _bcol = f"✓ 엔진 ATR 범위 안 ({_lo:.2f}~{_hi:.1f}%) — 다른 진입 조건은 별도", POSITIVE
                        brow = tk.Frame(self._verdict_f, bg=DARK_PANEL)
                        brow.pack(fill="x", padx=10, pady=(0, 1))
                        tk.Label(brow, text=_btxt, bg=DARK_PANEL, fg=_bcol,
                                 font=("Consolas", 8), anchor="w").pack(side="left")
                tk.Frame(self._verdict_f, bg="#2A2A2A", height=1).pack(
                    fill="x", padx=10, pady=(2, 2))

        # ── Sort by="4TF Optimization" 선정 근거 (6항목 체크리스트 + 전체 순위 + 엔진 4TF 기본 조건) ──
        elif self._sort_mode == "4TF Optimization":
            res = self._calc_4tf_score(sym)
            ctx_f = tk.Frame(self._verdict_f, bg=DARK_PANEL)
            ctx_f.pack(fill="x", padx=10, pady=(2, 1))
            if not res["ready"]:
                # T8: 갱신 대상 밖·데이터 준비 전 — 옛 값·기본값이라 채점하지 않음
                tk.Label(ctx_f, text="⚠ 4TF Optimization 채점 보류 (갱신 대상 밖·데이터 준비 중) — 참고용 분석",
                         bg=DARK_PANEL, fg=ORANGE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            else:
                _sorted = self._get_sorted_ranking()
                _rank = next((i + 1 for i, r in enumerate(_sorted) if r[0] == sym), None)
                sc = res["scores"]
                tk.Label(ctx_f, text="🎯 4TF Optimization 선정 근거 ", bg=DARK_PANEL, fg=ACCENT_BLUE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
                # T8: 목록 밖(4점 미만·일일 중립·50위 밖·블랙리스트) → 'None위' 대신 목록 밖 표시
                _rank_txt = f"전체 {_rank}위" if _rank is not None else "목록 밖 (4점 미만·일일 중립·50위 밖)"
                tk.Label(ctx_f, text=f"{_rank_txt} · 총 {res['total']}/{res['max']}점",
                         bg=DARK_PANEL, fg=DARK_TEXT,
                         font=("Consolas", 8, "bold"), anchor="w").pack(side="left")

                # 일일 추세(1h·4h·1d 같은 방향 2개 이상) = 기준 방향, 단기 추세(1m~15m 3개 이상) 참고
                tk.Label(self._verdict_f,
                         text=f"일일 추세 {trend_text(res['daily'])}  ·  단기 추세 {trend_text(res['short'])}",
                         bg=DARK_PANEL, fg=DARK_TEXT,
                         font=("Consolas", 8, "bold"), anchor="w").pack(fill="x", padx=10, pady=(0, 1))
                if res["base_dir"] is None:
                    tk.Label(self._verdict_f,
                             text="⚠ 일일 추세 중립 (1h·4h·1d 같은 방향 2개 미만) — 목록 제외, 단기일치·1m진입·일일강도·추세쏠림 0점",
                             bg=DARK_PANEL, fg=ORANGE,
                             font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=10, pady=(0, 1))

                detail_lines = [
                    (f"단기일치 {sc['align']}/4(+{sc['align']})  "
                     f"1m진입{'✅' if sc['entry'] else '—'}(+{sc['entry']})  "
                     f"일일강도 {sc['macro']}/2(+{sc['macro']})"),
                    (f"거래량Top10{'✅' if sc['volume'] else '—'}(+{sc['volume']}, rank {res['vol_rank']})  "
                     f"OI 1h {res['oi']:+.1f}%{'✅' if sc['oi'] else '—'}(+{sc['oi']})  "
                     f"추세쏠림{'✅' if sc['balance'] else '—'}(+{sc['balance']})"),
                ]
                for dtxt in detail_lines:
                    drow = tk.Frame(self._verdict_f, bg=DARK_PANEL)
                    drow.pack(fill="x", padx=10, pady=(0, 1))
                    tk.Label(drow, text=dtxt, bg=DARK_PANEL, fg=DIM_TEXT,
                             font=("Consolas", 8), anchor="w").pack(side="left")

                # 엔진 4TF 모드 기본 조건 (G4 ATR 범위 · G_K 5분 K) — 점수 아님, 배정 전 확인용 (다른 진입 조건은 별도)
                _band4 = _ctx.engine_atr_band("4TF Optimization")
                _kg = _ctx.engine_k_gate("4TF Optimization")
                if _band4 is not None and _kg is not None:
                    _atr4 = res["atr"]
                    _atr_ok = _band4[0] <= _atr4 <= _band4[1]
                    _k5 = ind.get("tf5", {}).get("k", 50.0)
                    if res["base_dir"] == "▲":
                        _k_ok, _k_rule = _k5 <= _kg[0], f"롱 ≤{_kg[0]:.0f}"
                    elif res["base_dir"] == "▼":
                        _k_ok, _k_rule = _k5 >= _kg[1], f"숏 ≥{_kg[1]:.0f}"
                    else:
                        _k_ok, _k_rule = False, "방향 중립"
                    _eng_ok = _atr_ok and _k_ok
                    tk.Label(self._verdict_f,
                             text=(f"엔진 4TF 기본 조건: ATR {_atr4:.2f}% ({_band4[0]:.2f}~{_band4[1]:.1f}) "
                                   f"{'✅' if _atr_ok else '❌'} · 5분 K {_k5:.0f} ({_k_rule}) {'✅' if _k_ok else '❌'}"
                                   f" — 다른 진입 조건 별도"),
                             bg=DARK_PANEL, fg=POSITIVE if _eng_ok else ORANGE,
                             font=("Consolas", 8), anchor="w").pack(fill="x", padx=10, pady=(0, 1))
            tk.Frame(self._verdict_f, bg="#2A2A2A", height=1).pack(
                fill="x", padx=10, pady=(2, 2))

        # ── Sort by="Newly Listed" 선정 근거 (4요소 점수 + 연령가중 + 전체 순위) ──
        elif self._sort_mode == "Newly Listed":
            # 1열에 표시한 같은 행(상장 경과일·24h 등락률)으로 계산 → 점수·순위 1열과 일치
            _nl_shown = self._nl_rows.get(sym)
            res = self._calc_newlist_score(sym, _nl_shown) if _nl_shown is not None else None
            ctx_f = tk.Frame(self._verdict_f, bg=DARK_PANEL)
            ctx_f.pack(fill="x", padx=10, pady=(2, 1))
            if res is None:
                tk.Label(ctx_f,
                         text="⚠ Newly Listed 대상 아님 (1열 목록 밖 — 상장 30일 초과·미상·주식/ETF·자격 미달 또는 상위 30위 밖)",
                         bg=DARK_PANEL, fg=ORANGE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            elif not res["ready"]:
                # N6: 봉 지표 미준비(갱신 대상 밖·데이터 준비 중) — 기본값을 측정값처럼 표시하지 않음
                tk.Label(ctx_f, text="⚠ Newly Listed 채점 보류 (갱신 대상 밖·데이터 준비 중) — 참고용 분석",
                         bg=DARK_PANEL, fg=ORANGE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            elif not res["qualified"]:
                tk.Label(ctx_f,
                         text=(f"⚠ Newly Listed 자격 미달 "
                               f"(VSS {res['vss']:.2f}<1.2 & OI 1h {res['oi']:+.1f}%<3%) — 참고용 분석"),
                         bg=DARK_PANEL, fg=ORANGE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            else:
                _rank = list(self._nl_rows).index(sym) + 1   # 1열 표시 순위
                tk.Label(ctx_f, text="🎯 Newly Listed 선정 근거 ", bg=DARK_PANEL, fg=ACCENT_BLUE,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
                tk.Label(ctx_f, text=f"전체 {_rank}위 · 총 {res['total']}/{res['max']}점 × 연령가중 {res['age_weight']:.1f} = {res['weighted']:.1f}점",
                         bg=DARK_PANEL, fg=DARK_TEXT,
                         font=("Consolas", 8, "bold"), anchor="w").pack(side="left")
                sc = res["scores"]
                detail_lines = [
                    (f"Volume Surge VSS {res['vss']:.2f}(+{sc['surge']})  "
                     f"OI 1h Momentum {res['oi']:+.1f}%(+{sc['oi']})"),
                    (f"Price Velocity 24h {res['chg']:+.2f}%(+{sc['velocity']})  "
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
        _nl_days = get_listing_days(sym)   # 1열 행·Newly Listed와 같은 정의 (거래량 상위 200 밖 포함)
        if _nl_days > 0 and bars_ready(sym):   # N7: 갱신 대상 밖 기본값으로 생애주기 판정하지 않음
            _lc_res = lifecycle_summary(_nl_days, ind)
            if _lc_res:
                _lc_stage, _lc_lbl, _lc_col, _lc_strat = _lc_res
                _pchg = ind.get("price_change_pct", 0.0)
                _h24p = ind.get("high_24h_pct",     0.0)
                _vss  = ind.get("vss",              1.0)
                _dv   = _nl_days
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

    # ─── 가격 예고 (12시간) — 종합 분석 맨 위, 화면 표시 전용 ──────
    def _render_forecast(self, sym: str) -> None:
        """data_manager.get_forecast 결과 표시: 문구(방향·내용) + 판정 시각·근거 수치·검증 상태."""
        hdr = tk.Frame(self._verdict_f, bg=DARK_PANEL)
        hdr.pack(fill="x", padx=10, pady=(4, 0))
        tk.Label(hdr, text="🔮 가격 예고 (12시간)", bg=DARK_PANEL, fg=ACCENT_BLUE,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
        fc = get_forecast(sym)
        if not forecast_enabled():
            head, tail, col, sub = "─ 판정식 없음", "forecast_params.json 학습 필요", DIM_TEXT, ""
        elif fc is None:
            head, tail, col, sub = "─ 계산 중", "5분 봉·OI 24시간치 수신 대기", DIM_TEXT, ""
        else:
            head, _, tail = fc["text"].partition(" — ")
            col = (NEGATIVE if head.startswith("▼") else POSITIVE if head.startswith("▲")
                   else ORANGE if head.startswith("⚡") else DIM_TEXT)
            ft = fc["feats"]
            sub = "" if ft is None else (
                f"{datetime.fromtimestamp(fc['t'] / 1000):%H:%M} 판정 · 24h {ft['r24']:+.1f}% · "
                f"고점 대비 {ft['dd_high']:+.1f}% · OI 4h {ft['oi4h']:+.1f}%")
            if sub and fc["status"]:
                sub += f" · {fc['status']}"
        body = tk.Frame(self._verdict_f, bg=DARK_PANEL)
        body.pack(fill="x", padx=10, pady=(1, 0))
        tk.Label(body, text=head, bg=DARK_PANEL, fg=col,
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left")
        tk.Label(body, text=f"  {tail}", bg=DARK_PANEL, fg=col,
                 font=("Segoe UI", 8), anchor="w").pack(side="left")
        if sub:
            tk.Label(self._verdict_f, text=sub, bg=DARK_PANEL, fg=DIM_TEXT,
                     font=("Consolas", 7), anchor="w").pack(fill="x", padx=10)
        tk.Frame(self._verdict_f, bg="#2A2A2A", height=1).pack(fill="x", padx=10, pady=(3, 2))

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

    def _get_phase_for_sym(self, sym: str) -> tuple:
        """1열 행의 추세 단계 (거래량 상위 200 밖 종목 포함 — 엔진 판단이 1열 표시와 같은 추세 단계 사용)."""
        data = get_row(sym)
        return (data[8], data[9]) if data else ("", DIM_TEXT)

    # ─── Col 4: Player Detection 상세 + 에너지 ────────────────
    def _refresh_energy(self) -> None:
        for w in self._energy_f.winfo_children():
            w.destroy()

        sym    = self._sel_var.get()
        ind    = get_ind(sym)
        long_r = self._calc_energy(ind)
        long_p = int(long_r * 100)
        short_p = 100 - long_p

        # Player Detection — 1열 행 배경·Sharp 점수와 같은 결과 (data_manager.get_player 단일 정의)
        _det  = get_player(sym)
        _tags = list(_det.tags) if _det else []

        # ── Sort by="Sharp rise"/"Sharp decline" 모드: Player 가산점(+2점, 절단 전 전체 태그 기준) 요약 + 태그 우선 배치 ──
        _is_rise_mode    = self._sort_mode == "Sharp rise"
        _is_decline_mode = self._sort_mode == "Sharp decline"
        #   가산 태그 = 각 스코어러 PLAYER_KEYS (rise: 'FR-' 제외 · decline: 롱비율·FR 조건 태그 3개 제외 — 점수와 같은 집합)
        _bonus_keys = SharpRiseScorer.PLAYER_KEYS if _is_rise_mode else SharpDeclineScorer.PLAYER_KEYS
        if _is_rise_mode or _is_decline_mode:
            _has_bonus_tag = bool(_det and _bonus_keys.intersection(_det.keys))
            _bonus_col = POSITIVE if _has_bonus_tag else DIM_TEXT
            _bonus_txt = "✅ +2/2점" if _has_bonus_tag else "— 0/2점"
            sum_f = tk.Frame(self._energy_f, bg=DARK_PANEL)
            sum_f.pack(fill="x", padx=8, pady=(4, 2))
            tk.Label(sum_f, text=f"🎯 {self._sort_mode} Player 가산점", bg=DARK_PANEL, fg=ACCENT_BLUE,
                     font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
            tk.Label(sum_f, text=f"  {_bonus_txt}", bg=DARK_PANEL, fg=_bonus_col,
                     font=("Consolas", 8, "bold"), anchor="w").pack(side="left")
            tk.Frame(self._energy_f, bg="#2A2A2A", height=1).pack(fill="x", padx=8, pady=(2, 2))
            _tags.sort(key=lambda t: 0 if t.tag_key in _bonus_keys else 1)
        _bonus_texts = {t.tag_text for t in _tags if t.tag_key in _bonus_keys}   # 가산 대상 태그 (🎯 가산 표시)

        # ── Player Detection 상세 ─────────────────────────────
        if not _tags:
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
            for i, tag in enumerate(_tags):
                tag_text, tag_color, strength_pct = tag.tag_text, tag.tag_color, tag.strength_pct
                if i > 0:
                    tk.Frame(self._energy_f, bg="#2A2A2A", height=1).pack(
                        fill="x", padx=12, pady=(2, 2))
                item_f = tk.Frame(self._energy_f, bg="#1A1A1A", pady=4)
                item_f.pack(fill="x", padx=8, pady=(4 if i == 0 else 0, 0))

                # 플레이어명 + 방향 + mini Canvas 강도 바 + %
                dir_txt, dir_col = self._player_direction(tag)

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
                if (_is_rise_mode or _is_decline_mode) and tag_text in _bonus_texts:
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
                tk.Label(item_f, text=tag.action, bg="#1A1A1A", fg=DIM_TEXT,
                         font=("Segoe UI", 8), anchor="w",
                         wraplength=240).pack(fill="x", padx=6, pady=(0, 4))

            # 복수 플레이어 통합 메시지 — 절단 전 전체 태그 키 기준 (표시는 상위 4개)
            if len(_det.keys) >= 2:
                cmb_msg, cmb_col = self._player_combined_msg(_det.keys)
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

    # ─── Player Detection 방향 표시 ──────────────────────────
    @staticmethod
    def _player_direction(tag) -> tuple:
        """태그 방향 표시 (텍스트, 색) — TagDetector 상승 키=롱 우세, 하락 키 중 주의색(FOMO 극단·FR+ 과열)=주의,
        나머지 하락 키=숏 우세. 롱 우세 색은 FR-만 라이트 그린, 나머지(기관 유입 포함) 초록."""
        if tag.tag_key in TagDetector.RISE_KEYS:
            return "롱 우세", (LIGHT_GREEN if tag.tag_color == LIGHT_GREEN else POSITIVE)
        if tag.tag_key in TagDetector.DECLINE_KEYS:
            return ("주의", ORANGE) if tag.tag_color == ORANGE else ("숏 우세", NEGATIVE)
        return "중립", DIM_TEXT

    @staticmethod
    def _player_combined_msg(keys: list) -> tuple:
        """복수 플레이어 통합 메시지 — keys: 절단 전 전체 태그 키(TagDetectionResult.keys).
        상승·하락 태그가 함께 있으면 혼재 경고, 한쪽만 있을 때만 조합·복수 메시지 (태그 키 정확 일치)."""
        if len(keys) < 2:
            return None, None
        ks = set(keys)
        up = len(ks & TagDetector.RISE_KEYS)
        dn = len(ks & TagDetector.DECLINE_KEYS)
        if up and dn:
            return "상승·하락 플레이어 혼재\n→ 방향 확인 전 진입 보류 권장", ORANGE
        if "세력 매집" in ks and ks & {"고래 매수", "기관 유입"}:
            return "세력 + 대형 자금 동시 매집\n→ 가장 강력한 상승 신호 — 롱 엔진 즉시 진입 강력 권장", POSITIVE
        if {"세력 분산", "청산 헌터"} <= ks:
            return "세력 이탈 + 청산 헌터 동시 활동\n→ 강한 하락 압력 — 숏 엔진 즉시 진입 강력 권장", NEGATIVE
        if {"FOMO 극단", "FR+ 과열"} <= ks:
            return "개인 FOMO + 펀딩비 과열 이중 경고\n→ 상승 말기 역추세 — 숏 엔진 역발상 검토", ORANGE
        if {"FR-", "세력 매집"} <= ks:
            return "펀딩비 반전 + 세력 매집 이중 상승 신호\n→ 롱 엔진 강력 추천", POSITIVE
        if {"롱 스퀴즈", "청산 헌터"} <= ks:
            return "롱 스퀴즈 + 청산 헌터 이중 하락 신호\n→ 숏 엔진 즉시 진입 최적 타이밍", NEGATIVE
        if up >= 2:
            return "복수 상승 플레이어 동시 활동\n→ 롱 에너지 복합 확인 — 롱 엔진 진입 권장", POSITIVE
        if dn >= 2:
            return "복수 하락 플레이어 동시 활동\n→ 숏 에너지 복합 확인 — 숏 엔진 진입 권장", NEGATIVE
        return None, None
