from __future__ import annotations
import tkinter as tk
import math
import time
import threading as _threading

try:
    from middle.widget.shared_context import get_ind
    from bottom_engine.engine_core.fourtf_consensus import FourTFConsensus
except ImportError:
    def get_ind(_s: str) -> dict: return {}                                # type: ignore[misc]
    class FourTFConsensus:                           # type: ignore[misc]
        @classmethod
        def evaluate(cls, _d: dict):
            from types import SimpleNamespace
            return SimpleNamespace(long_consensus=False, short_consensus=False,
                                   aligned_long=0, aligned_short=0, details={})

try:
    from bottom_engine.models import PositionState
except ImportError:
    class PositionState:    # type: ignore[misc]
        OPEN = "open"

from core.config import (
    DARK_BG, DARK_PANEL, DARK_HEADER, DARK_TEXT, DIM_TEXT,
    ACCENT_BLUE, POSITIVE, NEGATIVE, ORANGE, YELLOW,
    LONG_HDR_BG, SHORT_HDR_BG,
)


def _lerp_hex(c0: str, c1: str, t: float) -> str:
    r0, g0, b0 = int(c0[1:3], 16), int(c0[3:5], 16), int(c0[5:7], 16)
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r = int(r0 + (r1 - r0) * t)
    g = int(g0 + (g1 - g0) * t)
    b = int(b0 + (b1 - b0) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


TF_KEYS = ["1m", "3m", "5m", "15m"]


class CenterCtrlMixin:

    # ──────────────────────────────────────────────────────────────
    def _build_position_indicator(self, parent: tk.Frame) -> None:
        INIT_LO, INIT_HI = "#1A1A1A", "#2A2A2A"
        self._pos_glow = {"lo": INIT_LO, "hi": INIT_HI, "phase": 0.0}
        glow_widgets: list = []

        # 1·3열 헤더(높이 35px)와 정확히 맞춰 시각적 정렬을 통일
        ind_f = tk.Frame(parent, bg=INIT_LO, pady=5)
        ind_f.pack(fill="x")
        glow_widgets.append(ind_f)

        row = tk.Frame(ind_f, bg=INIT_LO)
        row.pack(anchor="center")
        glow_widgets.append(row)

        lbl = tk.Label(row, text="⚪   4TF 합의 대기 중",
                       bg=INIT_LO, fg=DIM_TEXT,
                       font=("Segoe UI", 9, "bold"))
        lbl.pack(side="left")
        glow_widgets.append(lbl)

        self._pos_ind = {"frame": ind_f, "row": row,
                         "lbl": lbl, "glow_widgets": glow_widgets}
        _g = self._pos_glow

        # ── 발광 펄스 애니메이션 (배경색 보간 — 폴링으로 색상 동적 갱신) ──
        def _pulse() -> None:
            try:
                t   = (math.sin(_g["phase"]) + 1.0) / 2.0
                col = _lerp_hex(_g["lo"], _g["hi"], t)
                for w in glow_widgets:
                    w.configure(bg=col)
                _g["phase"] += 0.10
                ind_f.after(90, _pulse)
            except tk.TclError:
                pass  # 창 닫힘 시 안전 종료

        ind_f.after(80, _pulse)

    # ══════════════════════════════════════════════════════════════
    # 2열 — 중앙 패널: 거시적 추세 메시지창 + 국지적 4TF Stoch RSI
    # ══════════════════════════════════════════════════════════════
    def _build_center_panel(self, parent: tk.Frame) -> None:

        # ── ⓪ 활성 포지션 인디케이터 바 ──────────────────────────
        self._build_position_indicator(parent)

        # ── ① 상단 헤더 ──────────────────────────────────────────
        hdr = tk.Frame(parent, bg=DARK_HEADER, pady=6)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  📡  거시적 추세 분석",
                 bg=DARK_HEADER, fg=ACCENT_BLUE,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(6, 0))

        # ── ② 거시적 추세 메시지창 (1H · 4H · 1D 실시간) ──────────
        _MAC_BG = "#0E0E10"
        self._macro_f = tk.Frame(parent, bg=_MAC_BG, pady=6)
        self._macro_f.pack(fill="x")
        self._macro_ico_lbl = tk.Label(
            self._macro_f,
            text="⚪   분석 대기 중  —  심볼 배정 후 자동 시작",
            bg=_MAC_BG, fg=DIM_TEXT,
            font=("Segoe UI", 9, "bold"))
        self._macro_ico_lbl.pack(padx=10, pady=(2, 2))
        _tf_row = tk.Frame(self._macro_f, bg=_MAC_BG)
        _tf_row.pack(fill="x", padx=10, pady=(4, 2))
        self._macro_tf_row = _tf_row
        for _idx, (_tf_key, _tf_name) in enumerate(
                (("tf1h", "1H"), ("tf4h", "4H"), ("tf1d", "1D"))):
            if _idx > 0:
                tk.Frame(_tf_row, bg="#333333", width=1).pack(
                    side="left", fill="y", pady=2)
            _l = tk.Label(_tf_row,
                          text=f"{_tf_name} K  —.— D  —.— ↔",
                          bg=_MAC_BG, fg=DIM_TEXT,
                          font=("Consolas", 7), anchor="center")
            _l.pack(side="left", expand=True, fill="x")
            self._macro_tf_lbls[_tf_key] = _l

        # ── ③ 구분선 ─────────────────────────────────────────────
        tk.Frame(parent, bg="#2A2A2A", height=1).pack(fill="x", pady=(4, 0))

        # ── ④ 국지적 4TF Stoch RSI 헤더 ─────────────────────────
        stoch_hdr = tk.Frame(parent, bg=DARK_HEADER, pady=4)
        stoch_hdr.pack(fill="x")
        tk.Label(stoch_hdr, text="  📈  Stoch RSI  모니터링  (국지적 4TF)",
                 bg=DARK_HEADER, fg=ACCENT_BLUE,
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(6, 0))

        # ── ⑤ 4TF 미니차트 그리드 ───────────────────────────────
        TF_H   = 160
        N_PTS  = 22
        SPEEDS = {"1m": 0.20, "3m": 0.13, "5m": 0.09, "15m": 0.04}
        _PL, _PR, _PT, _PB = 4, 24, 5, 4

        tf_anim: dict = {}
        for i, tf in enumerate(TF_KEYS):
            k0  = 50.0   # 초기 중립값 — 폴링으로 실수치 교정
            d0  = 50.0
            amp = 20 + i * 3
            pk  = i * 1.1
            pd  = pk + 0.6
            spd = SPEEDS[tf]
            k_h = [max(2.0, min(98.0,
                       k0 + amp * math.sin(pk - spd * (N_PTS - 1 - j))))
                   for j in range(N_PTS)]
            d_h = [max(2.0, min(98.0,
                       d0 + (amp - 6) * math.sin(pd - spd * (N_PTS - 1 - j))))
                   for j in range(N_PTS)]
            tf_anim[tf] = {
                "k_hist": k_h, "d_hist": d_h,
                "pk": pk, "pd": pd,
                "amp": amp, "ck": k0, "cd": d0, "spd": spd,
                "state0": "상승 ▲",
                "col0":   POSITIVE,
            }

        tf_row = tk.Frame(parent, bg="#0E0E0E")
        tf_row.pack(fill="x")

        ctr_tf_w = 84
        for i, tf in enumerate(TF_KEYS):
            if i > 0:
                tk.Frame(tf_row, bg="#333333", width=2).pack(side="left", fill="y")
            cf = tk.Frame(tf_row, bg="#0E0E0E")
            cf.pack(side="left", fill="both", expand=True)

            tk.Label(cf, text=tf,
                     bg=DARK_HEADER, fg=ACCENT_BLUE,
                     font=("Segoe UI", 10, "bold"),
                     anchor="center", width=6).pack(fill="x", ipady=3)
            tk.Frame(cf, bg="#2A2A2A", height=1).pack(fill="x")

            cv = tk.Canvas(cf, bg="#0E0E0E", width=ctr_tf_w, height=TF_H,
                           highlightthickness=0)
            cv.pack(side="top", fill="x")

            tk.Frame(cf, bg="#2A2A2A", height=1).pack(fill="x")

            slbl = tk.Label(cf, text="대기",
                            bg="#111111", fg=DIM_TEXT,
                            font=("Segoe UI", 8, "bold"), anchor="center",
                            wraplength=ctr_tf_w - 4)
            slbl.pack(fill="x", ipady=3)

            tf_anim[tf]["cv"]   = cv
            tf_anim[tf]["slbl"] = slbl

        def _draw_cv(cv: tk.Canvas, kh: list, dh: list) -> None:
            cv.delete("all")
            W = cv.winfo_width()  or ctr_tf_w
            H = cv.winfo_height() or TF_H
            N = len(kh)

            def fy(v: float) -> float:
                return _PT + (1.0 - v / 100.0) * (H - _PT - _PB)

            def fx(i: int) -> float:
                return _PL + i / max(1, N - 1) * (W - _PL - _PR)

            y80 = fy(80.0);  y20 = fy(20.0)
            x = _PL
            while x < W - _PR:
                cv.create_line(x, y80, min(x + 3, W - _PR), y80,
                               fill="#2A2A2A", width=1)
                cv.create_line(x, y20, min(x + 3, W - _PR), y20,
                               fill="#2A2A2A", width=1)
                x += 6

            for val, y in ((100, _PT), (80, y80), (20, y20), (0, H - _PB)):
                cv.create_text(W - 1, y, text=f"{val:3d}",
                               fill="#3D3D3D", font=("Consolas", 5), anchor="ne")

            slope = kh[-1] - kh[-4] if N >= 4 else 0.0
            k_col = POSITIVE if slope > 1.5 else (NEGATIVE if slope < -1.5 else YELLOW)

            d_pts = []
            for i, v in enumerate(dh):
                d_pts += [fx(i), fy(v)]
            if len(d_pts) >= 4:
                cv.create_line(d_pts, fill=ACCENT_BLUE, width=1.5,
                               smooth=True, joinstyle="round")

            k_pts = []
            for i, v in enumerate(kh):
                k_pts += [fx(i), fy(v)]
            if len(k_pts) >= 4:
                cv.create_line(k_pts, fill=k_col, width=2,
                               smooth=True, joinstyle="round")

            kex, key_ = fx(N - 1), fy(kh[-1])
            dex, dey  = fx(N - 1), fy(dh[-1])
            cv.create_oval(kex - 2.5, key_ - 2.5, kex + 2.5, key_ + 2.5,
                           fill=k_col, outline="")
            cv.create_oval(dex - 2,   dey - 2,   dex + 2,   dey + 2,
                           fill=ACCENT_BLUE, outline="")
            cv.create_text(W - 1, key_, text=f"{kh[-1]:.0f}",
                           fill=k_col, font=("Consolas", 7, "bold"), anchor="e")
            offset = -8 if abs(key_ - dey) < 10 else 0
            cv.create_text(W - 1, dey + offset, text=f"{dh[-1]:.0f}",
                           fill=ACCENT_BLUE, font=("Consolas", 7), anchor="e")

        def _tick(anim: dict = tf_anim, n: int = N_PTS) -> None:
            if not self._tf_ticking:
                return
            try:
                for tf_k, a in anim.items():
                    if a.get("use_real"):
                        # 실데이터 모드 — 2초 주기 교체 후 재그리기만
                        _draw_cv(a["cv"], a["k_hist"], a["d_hist"])
                    else:
                        # 정현파 폴백 — 실데이터 미수신 시
                        a["pk"] += a["spd"]
                        a["pd"] += a["spd"]
                        nk = max(2.0, min(98.0,
                                 a["ck"] + a["amp"] * math.sin(a["pk"])))
                        nd = max(2.0, min(98.0,
                                 a["cd"] + (a["amp"] - 6) * math.sin(a["pd"])))
                        a["k_hist"].append(nk);  a["k_hist"] = a["k_hist"][-n:]
                        a["d_hist"].append(nd);  a["d_hist"] = a["d_hist"][-n:]
                        _draw_cv(a["cv"], a["k_hist"], a["d_hist"])
                        sl = a["k_hist"][-1] - a["k_hist"][-4] if len(a["k_hist"]) >= 4 else 0
                        if nk > 80:
                            st, sc = "과매수",    NEGATIVE
                        elif nk < 20:
                            st, sc = "과매도",    POSITIVE
                        elif sl > 1.5:
                            st, sc = a["state0"], a["col0"]
                        elif sl < -1.5:
                            st, sc = "하락 ▼",    NEGATIVE
                        else:
                            st, sc = "횡보 ↔",    YELLOW
                        a["slbl"].configure(text=st, fg=sc)
                list(anim.values())[0]["cv"].after(320, _tick)
            except tk.TclError:
                pass

        def _start(anim: dict = tf_anim) -> None:
            for a in anim.values():
                _draw_cv(a["cv"], a["k_hist"], a["d_hist"])
            list(anim.values())[0]["cv"].after(320, _tick)

        self._tf_anim    = tf_anim
        self._tf_tick_fn = _tick
        self.after(60, self._freeze_tf_charts)   # 초기: 하단 동결 상태

        # ── ⑥ 4TF 그리드 하단 여백 (5px, Footer 와 동일 톤) ─────────
        tk.Frame(parent, bg=DARK_HEADER, height=5).pack(fill="x")

        # ── ⑦ 여백 ↔ 하단 공백 구분선 (1px, 밝은 톤으로 가시성 확보) ──
        tk.Frame(parent, bg="#3A3A3A", height=1).pack(fill="x")

        # ── ⑧ 전략 파라미터 요약 + 엔진 최근 액션 라벨 ──────────────
        sig_f = tk.Frame(parent, bg="#0A0A0F", pady=4)
        sig_f.pack(fill="x")
        self._param_info_lbl = tk.Label(
            sig_f,
            text="—  전략 미설정  —",
            bg="#0A0A0F", fg=DIM_TEXT,
            font=("Consolas", 7), anchor="center")
        self._param_info_lbl.pack(fill="x", padx=6)
        self._last_sig_lbl = tk.Label(
            sig_f,
            text="—  엔진 대기 중  —",
            bg="#0A0A0F", fg=DIM_TEXT,
            font=("Consolas", 8), anchor="center")
        self._last_sig_lbl.pack(fill="x", padx=6)

        # ── ⑨ 하단 잔여 공백 — 1·3열 Footer 와 동일한 톤으로 채워 정리 ─
        tk.Frame(parent, bg=DARK_HEADER).pack(fill="both", expand=True)

    # ══════════════════════════════════════════════════════════════
    # 중앙 컨트롤 세션 — 실데이터 폴링 / 상태 갱신
    # ══════════════════════════════════════════════════════════════
    @staticmethod
    def _judge_macro_trend(ind: dict) -> tuple[str, str, str, str]:
        """tf1h/tf4h/tf1d 기반 거시적 추세 판정 (1H · 4H · 1D).
        Returns: (fg_color, icon, trend_text, sub_text)
        """
        score = 0
        for key in ("tf1h", "tf4h", "tf1d"):
            td = ind.get(key, {})
            k, d = td.get("k", 50.0), td.get("d", 50.0)
            if k > d and abs(k - d) >= 2.0:
                score += 1
            elif k < d and abs(k - d) >= 2.0:
                score -= 1
        if   score ==  3: return POSITIVE, "🟢", "강한 상승 추세",  "1H · 4H · 1D 전 TF 상승"
        elif score ==  2: return YELLOW,   "🟡", "상승 우세 혼조",  "3TF 중 2개 상승"
        elif score ==  1: return YELLOW,   "🟡", "약 상승 혼조",    "3TF 중 1개 상승"
        elif score == -1: return ORANGE,   "🟠", "약 하락 혼조",    "3TF 중 1개 하락"
        elif score == -2: return ORANGE,   "🔴", "하락 우세 혼조",  "3TF 중 2개 하락"
        elif score == -3: return NEGATIVE, "🔴", "강한 하락 추세",  "1H · 4H · 1D 전 TF 하락"
        else:             return DIM_TEXT, "⚪", "방향 탐색 중",    "TF 간 방향 혼조"

    @staticmethod
    def _calc_macro_score(ind: dict) -> int:
        """tf1h/tf4h/tf1d K·D 기반 거시적 추세 점수 계산. -3 ~ +3."""
        score = 0
        for key in ("tf1h", "tf4h", "tf1d"):
            td = ind.get(key, {})
            k, d = td.get("k", 50.0), td.get("d", 50.0)
            if k > d and abs(k - d) >= 2.0:
                score += 1
            elif k < d and abs(k - d) >= 2.0:
                score -= 1
        return score

    def _update_position_indicator(self, is_long: bool | None) -> None:
        """포지션 인디케이터 텍스트·색·글로우 색상 갱신."""
        if not self._pos_ind:
            return
        if is_long is True:
            txt, fg, lo, hi = "◀   🟢   롱 포지션 활성", POSITIVE, "#071512", "#0D5C2A"
        elif is_long is False:
            txt, fg, lo, hi = "🔴   숏 포지션 활성   ▶", NEGATIVE, "#150709", "#5C0D1E"
        else:
            txt, fg, lo, hi = "방향 미확정  대기중",  DIM_TEXT,  "#1A1A1A", "#2A2A2A"
        self._pos_glow.update({"lo": lo, "hi": hi})
        self._pos_ind["lbl"].configure(text=txt, fg=fg)

    def _update_center(self) -> None:
        """실데이터로 중앙 컨트롤 세션 전체 갱신 (2초 폴링마다 호출)."""
        sym = self._shared_sym.get()
        if not sym:
            return
        ind = get_ind(sym)
        if not ind:
            return

        # ① 거시적 추세 업데이트 (1H · 4H · 1D)
        col, ico, trend_txt, sub_txt = self._judge_macro_trend(ind)
        mac_bg = (
            "#0E1A10" if col == POSITIVE else
            "#1F0A0F" if col in (NEGATIVE, ORANGE) else
            "#0E0E10"
        )
        if self._macro_f:
            self._macro_f.configure(bg=mac_bg)
        if self._macro_tf_row:
            self._macro_tf_row.configure(bg=mac_bg)
            for _w in self._macro_tf_row.winfo_children():
                try: _w.configure(bg=mac_bg)
                except tk.TclError: pass
        if self._macro_ico_lbl:
            self._macro_ico_lbl.configure(
                text=f"{ico}  {trend_txt}  —  {sub_txt}", fg=col, bg=mac_bg)
        for tf_key, tf_name in (("tf1h", "1H"), ("tf4h", "4H"), ("tf1d", "1D")):
            lbl = self._macro_tf_lbls.get(tf_key)
            if lbl is None:
                continue
            td  = ind.get(tf_key, {})
            k   = td.get("k", 50.0)
            d   = td.get("d", 50.0)
            dr  = td.get("dir", "↔")
            c   = POSITIVE if dr == "▲" else (NEGATIVE if dr == "▼" else DIM_TEXT)
            lbl.configure(
                text=f"{tf_name} K{k:5.1f} D{d:5.1f} {dr}",
                fg=c, bg=mac_bg)

        # ② 4TF 미니차트 실수치 교정 (1m · 3m · 5m · 15m)
        for tf, ind_key in (("1m","tf1"), ("3m","tf3"), ("5m","tf5"), ("15m","tf15")):
            a = self._tf_anim.get(tf)
            if a is None:
                continue
            td  = ind.get(ind_key, {})
            k   = td.get("k", 50.0)
            d   = td.get("d", 50.0)
            a["ck"] = k
            a["cd"] = d
            ks = td.get("k_series", [])
            ds = td.get("d_series", [])
            n_pts = len(a.get("k_hist", [])) or 22
            if len(ks) >= 4 and len(ds) >= 4:
                a["k_hist"] = [max(2.0, min(98.0, v)) for v in ks[-n_pts:]]
                a["d_hist"] = [max(2.0, min(98.0, v)) for v in ds[-n_pts:]]
                a["use_real"] = True
            slbl = a.get("slbl")
            if slbl:
                if   k > 80:       st, sc = "과매수", NEGATIVE
                elif k < 20:       st, sc = "과매도", POSITIVE
                elif k > d + 2.0:  st, sc = "상승 ▲", POSITIVE
                elif k < d - 2.0:  st, sc = "하락 ▼", NEGATIVE
                else:              st, sc = "횡보 ↔", YELLOW
                slbl.configure(text=st, fg=sc)

        # ③ 포지션 인디케이터 — 전략 모드에 따라 판단 기준 분기
        use_macro = (self._applied_params or {}).get("use_macro", True)
        if use_macro:
            # 거시적 추세(1H·4H·1D) 방향으로 롱/숏 결정
            score = self._calc_macro_score(ind)
            if   score >= 1:  self._update_position_indicator(True)
            elif score <= -1: self._update_position_indicator(False)
            else:             self._update_position_indicator(None)
        else:
            # 국지적 4TF 과반(3/4 이상) 합의로 롱/숏 결정
            signal = FourTFConsensus.evaluate(ind)
            if   signal.aligned_long  >= 3: self._update_position_indicator(True)
            elif signal.aligned_short >= 3: self._update_position_indicator(False)
            else:                           self._update_position_indicator(None)

    def _poll_center(self) -> None:
        """0.5초 주기 중앙 컨트롤 세션 폴링 루프."""
        if not self._center_running:
            return
        try:
            self._update_center()
            self._update_price_charts()
            has_open = (self._engine is not None
                        and self._engine.has_open_positions())
            if self._trading_active or has_open:
                self._update_engine_panels()
            self._update_last_signal_lbl()
        except Exception:
            pass
        try:
            self.after(500, self._poll_center)
        except Exception:
            pass

    def _update_param_info_lbl(self) -> None:
        """전략 파라미터 요약(전략명·Funds·Lev·SL·Trail) + API 키 상태를 표시."""
        if self._param_info_lbl is None:
            return
        ap = self._applied_params
        if ap is None or not self._strategy_ready:
            self._param_info_lbl.configure(
                text="—  전략 미설정  —", fg=DIM_TEXT)
            return
        mode  = self._applied_sort_mode or "—"
        funds = ap.get("funds", "—")
        lev   = ap.get("leverage", "—")
        sl    = ap.get("sl", 2.5)
        trail = ap.get("trail", 1.5)
        has_key = bool(self._engine is not None and
                       getattr(self._engine, "is_live", False))
        if self._engine is not None and not has_key:
            txt = (f"⚠ API 키 미설정  [{mode}]  Funds {funds}%  ×{lev}  "
                   f"SL {sl:.1f}%  Trail {trail:.1f}%")
            clr = ORANGE
        else:
            txt = (f"[{mode}]  Funds {funds}%  ×{lev}  "
                   f"SL {sl:.1f}%  Trail {trail:.1f}%")
            clr = "#5577AA"
        self._param_info_lbl.configure(text=txt, fg=clr)

    def _update_last_signal_lbl(self) -> None:
        """엔진 최근 액션(last_signal / error_msg)·잔고 상태를 중앙 라벨에 갱신."""
        if self._last_sig_lbl is None or self._engine is None:
            return
        try:
            st  = self._engine.get_state()
            err = st.error_msg or ""
            sig = st.last_signal or ""

            long_open  = (st.long_pos  is not None
                          and st.long_pos.state  == PositionState.OPEN)
            short_open = (st.short_pos is not None
                          and st.short_pos.state == PositionState.OPEN)
            pos_open   = long_open or short_open

            if err:
                self._last_sig_lbl.configure(text=f"⚠  {err}", fg=NEGATIVE)
            elif pos_open:
                if sig:
                    if "롱 진입" in sig:
                        fg = POSITIVE
                    elif "숏 진입" in sig:
                        fg = NEGATIVE
                    elif "청산" in sig or "익절" in sig:
                        fg = YELLOW
                    else:
                        fg = DIM_TEXT
                    self._last_sig_lbl.configure(text=f"🔔  {sig}", fg=fg)
                else:
                    side_txt = "롱" if long_open else "숏"
                    self._last_sig_lbl.configure(
                        text=f"⏳  {side_txt} 포지션 보유 중  —  신호 대기",
                        fg=ACCENT_BLUE)
            else:
                bal = self._ui_balance
                if bal is None:
                    bal = st.last_balance
                if bal is not None:
                    if bal > 0:
                        blk_long     = getattr(st, "last_blocked_long",   "")
                        blk_short    = getattr(st, "last_blocked_short",  "")
                        blocked      = getattr(st, "last_blocked_reason", "")
                        side_pfx     = getattr(st, "last_blocked_side",   "")
                        next_scan_at = getattr(st, "next_scan_at",         0.0)
                        remaining    = max(0, int(next_scan_at - time.time())) if next_scan_at > 0 else 0
                        if blk_long and blk_short:
                            self._last_sig_lbl.configure(
                                text=(f"📵 롱 [{remaining:02d}s] {blk_long}"
                                      f"  |  📵 숏 {blk_short}"),
                                fg=ORANGE)
                        elif blocked:
                            pfx = "📵 롱" if side_pfx == "long" else "📵 숏"
                            self._last_sig_lbl.configure(
                                text=f"{pfx} 차단  [{remaining:02d}s]  —  {blocked}",
                                fg=ORANGE)
                        else:
                            if remaining > 0:
                                self._last_sig_lbl.configure(
                                    text=f"✅  {bal:.2f} USDT  —  다음 스캔 {remaining:02d}s",
                                    fg=POSITIVE)
                            else:
                                self._last_sig_lbl.configure(
                                    text=f"✅  {bal:.2f} USDT  —  거래 대기 중",
                                    fg=POSITIVE)
                    else:
                        self._last_sig_lbl.configure(
                            text="⛔  잔고 없음  —  Initial Investment로 자금 이체 필요",
                            fg=ORANGE)
                elif sig:
                    fg = YELLOW if ("청산" in sig or "익절" in sig) else DIM_TEXT
                    self._last_sig_lbl.configure(text=f"🔔  {sig}", fg=fg)
                else:
                    self._last_sig_lbl.configure(
                        text="—  엔진 대기 중  —", fg=DIM_TEXT)
        except Exception:
            pass

    def _refresh_ui_balance_bg(self) -> None:
        """거래 완료 후 잔고 재조회 (배경 스레드) → _last_sig_lbl 즉시 갱신."""
        if self._engine is None:
            return
        def _fetch() -> None:
            val = self._engine._client.get_account_balance()
            self._ui_balance = val
            try:
                self.after(0, self._update_last_signal_lbl)
            except tk.TclError:
                pass
        _threading.Thread(target=_fetch, daemon=True).start()

    def _reset_center(self) -> None:
        """심볼 해제 시 중앙 컨트롤 세션 초기 상태 복귀."""
        self._tf_ticking = False
        self._pnl_running = False
        if self._app_started and self._pos_ind:
            self._pos_ind["lbl"].configure(
                text="코인 심볼 및 전략을 선택하세요!", fg=YELLOW)
        else:
            self._update_position_indicator(None)
        mac_bg = "#0E0E10"
        if self._macro_f:
            self._macro_f.configure(bg=mac_bg)
        if self._macro_tf_row:
            self._macro_tf_row.configure(bg=mac_bg)
            for _w in self._macro_tf_row.winfo_children():
                try: _w.configure(bg=mac_bg)
                except tk.TclError: pass
        if self._macro_ico_lbl:
            self._macro_ico_lbl.configure(
                text="⚪   분석 대기 중  —  심볼 배정 후 자동 시작",
                fg=DIM_TEXT, bg=mac_bg)
        for tf_key, tf_name in (("tf1h","1H"), ("tf4h","4H"), ("tf1d","1D")):
            lbl = self._macro_tf_lbls.get(tf_key)
            if lbl:
                lbl.configure(
                    text=f"{tf_name} K  —.— D  —.— ↔",
                    fg=DIM_TEXT, bg=mac_bg)
        for a in self._tf_anim.values():
            a["ck"] = 50.0
            a["cd"] = 50.0
            a["use_real"] = False
        self.after(50, self._freeze_tf_charts)
        self._update_engine_panels()
        self._update_price_charts()
        self._update_param_info_lbl()

    def _freeze_tf_charts(self) -> None:
        """대기 모드 — 4TF 캔버스를 하단 수평선으로 동결."""
        _PL, _PR, _PT, _PB = 4, 24, 5, 4
        TF_H = 160
        for a in self._tf_anim.values():
            cv   = a.get("cv")
            slbl = a.get("slbl")
            if cv is None:
                continue
            try:
                cv.delete("all")
                W = cv.winfo_width()  or 84
                H = cv.winfo_height() or TF_H
                y80 = _PT + (1.0 - 80.0 / 100.0) * (H - _PT - _PB)
                y20 = _PT + (1.0 - 20.0 / 100.0) * (H - _PT - _PB)
                y_bot = _PT + (1.0 - 5.0 / 100.0) * (H - _PT - _PB)
                x = _PL
                while x < W - _PR:
                    cv.create_line(x, y80, min(x + 3, W - _PR), y80,
                                   fill="#2A2A2A", width=1)
                    cv.create_line(x, y20, min(x + 3, W - _PR), y20,
                                   fill="#2A2A2A", width=1)
                    x += 6
                for val, yv in ((100, _PT), (80, y80), (20, y20), (0, H - _PB)):
                    cv.create_text(W - 1, yv, text=f"{val:3d}",
                                   fill="#3D3D3D", font=("Consolas", 5), anchor="ne")
                cv.create_line(_PL, y_bot, W - _PR, y_bot,
                               fill=ACCENT_BLUE, width=1)
                cv.create_line(_PL, y_bot, W - _PR, y_bot,
                               fill=DIM_TEXT, width=1.5)
            except tk.TclError:
                pass
            if slbl:
                try:
                    slbl.configure(text="대기", fg=DIM_TEXT)
                except tk.TclError:
                    pass
