"""
middle/col2_chart_indicators/macro_4tf_entry.py
Macro & 4TF Entry 분석 전담 — Col2 Macro & 4TF Entry 탭 계산
panel_col2._build_macro_panel() 에서 호출.

섹션:
  Section 1 — MACRO TREND      (1H·4H·1D StochRSI 방향 기반)
  Section 2 — 4TF ALIGNMENT    (1M·3M·5M·15M 합의 기반)
  Section 3 — SIGNAL QUALITY   (전 7TF 가중치 합산 신뢰도)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from middle.col2_chart_indicators.mtf_stochrsi import StochRSIResult

# 거시 TF (MACRO TREND 섹션)
_MACRO_TFS  = ("1h", "4h", "1d")
# 단기 TF (4TF COMPLETE ALIGNMENT 섹션)
_LOCAL_TFS  = ("1m", "3m", "5m", "15m")
# 전체 7TF (SIGNAL QUALITY 섹션)
_ALL_TFS    = ("1m", "3m", "5m", "15m", "1h", "4h", "1d")

# ind dict tf_key → 실 TF 이름 매핑
_IND_TO_TF = {
    "tf1": "1m", "tf3": "3m", "tf5": "5m", "tf15": "15m",
    "tf1h": "1h", "tf4h": "4h", "tf1d": "1d",
}

from middle.widget.constants import (
    POSITIVE as _POSITIVE, NEGATIVE as _NEGATIVE, ORANGE as _ORANGE,
    YELLOW as _YELLOW, LIGHT_GREEN as _LGR,
    DIM_TEXT as _DIM,
)
_LIGHT_GREEN = _LGR


# ── 결과 데이터클래스 ─────────────────────────────────────────────

@dataclass
class MacroTrendResult:
    """MACRO TREND 섹션 분석 결과."""
    signal:     str    # "STRONG BULLISH" | "BULLISH" | ... | "STRONG BEARISH"
    color:      str    # 신호 색상
    score:      float  # -1.0 ~ +1.0
    up_count:   int    # 상승 TF 수 (0~3)
    dn_count:   int    # 하락 TF 수 (0~3)
    directions: dict[str, str] = field(default_factory=dict)  # {tf: "▲"/"▼"/"↔"}


@dataclass
class FourTFAlignmentResult:
    """4TF COMPLETE ALIGNMENT 섹션 분석 결과."""
    aligned_count: int     # 일치 TF 수 (0~4)
    base_dir:      str     # "▲" | "▼" | "↔"
    avg_spread:    float   # K-D 평균 스프레드
    directions:    dict[str, str] = field(default_factory=dict)
    color:         str = _DIM


@dataclass
class SignalQualityResult:
    """SIGNAL QUALITY 섹션 분석 결과."""
    score:       float   # 가중치 정규화 점수 -1.0 ~ +1.0
    direction:   str     # "▲▲ BULLISH" | "▲ BULLISH" | "NEUTRAL" | "▼ BEARISH" | "▼▼ BEARISH"
    fresh_count: int     # 30분 이내 신선 신호 수 (0~7)
    reliability: int     # 신뢰도 % (0~85)
    agree_n:     int     # 합의 TF 수 (같은 방향)
    agree_pct:   float   # 합의 비율 (0.0~1.0)
    n_valid:     int     # 실데이터 보유 TF 수 (0~7)
    score_color: str = _YELLOW
    agree_color: str = _YELLOW
    fresh_color: str = _YELLOW
    rely_color:  str = _YELLOW


@dataclass
class MacroAnalysisResult:
    macro_trend:    MacroTrendResult
    fourtf_align:   FourTFAlignmentResult
    signal_quality: SignalQualityResult


# ── 분석기 ────────────────────────────────────────────────────────

class MacroFourTFEntry:
    """Macro & 4TF Entry 분석기.

    panel_col2._build_macro_panel() 의 Section 1/2/3 계산을 전담.
    """

    # ── 공개 진입점 ───────────────────────────────────────────────

    @classmethod
    def analyze_from_ind(
        cls,
        ind: dict,
        bpr: float = 0.5,
        vss: float = 1.0,
    ) -> MacroAnalysisResult:
        """get_ind(sym) 반환 dict에서 직접 분석 결과 생성.

        ind: data_manager.get_ind(sym) 반환 dict
             ind["tf1h"] = {"dir":"▲","k":72.3,"d":68.1,"col":"...","elapsed":"방금",...}
        """
        stoch_map = cls._ind_to_stoch_map(ind)
        return MacroAnalysisResult(
            macro_trend=cls._macro_trend(stoch_map),
            fourtf_align=cls._fourtf_alignment(stoch_map, ind),
            signal_quality=cls._signal_quality(stoch_map, ind, bpr, vss),
        )

    # ── ind dict → StochRSIResult 변환 어댑터 ────────────────────

    @staticmethod
    def _ind_to_stoch_map(ind: dict) -> dict[str, StochRSIResult]:
        """ind dict 내 tf dict들을 StochRSIResult 맵으로 변환."""
        result: dict[str, StochRSIResult] = {}
        for ind_key, tf_name in _IND_TO_TF.items():
            tf_d = ind.get(ind_key, {})
            result[tf_name] = StochRSIResult(
                k         = tf_d.get("k", 50.0),
                d         = tf_d.get("d", 50.0),
                direction = tf_d.get("dir", "↔"),
            )
        return result

    # ── Section 1: MACRO TREND ────────────────────────────────────

    @classmethod
    def _macro_trend(cls, stoch_map: dict[str, StochRSIResult]) -> MacroTrendResult:
        dirs    = {tf: stoch_map[tf].direction for tf in _MACRO_TFS if tf in stoch_map}
        spreads = [abs(stoch_map[tf].k - stoch_map[tf].d) for tf in _MACRO_TFS if tf in stoch_map]
        up      = sum(1 for d in dirs.values() if d == "▲")
        dn      = sum(1 for d in dirs.values() if d == "▼")
        avg_sp  = sum(spreads) / len(spreads) if spreads else 0.0

        dom     = up if up >= dn else dn
        str_raw = min(1.0, (dom / 3.0) * (1.0 + avg_sp / 20.0))
        score   = str_raw if up >= dn else -str_raw

        if   score >  0.8: signal, color = "STRONG BULLISH",  _POSITIVE
        elif score >  0.5: signal, color = "BULLISH",          _POSITIVE
        elif score >  0.2: signal, color = "MODERATE BULLISH", _LIGHT_GREEN
        elif score > -0.2: signal, color = "NEUTRAL",          _YELLOW
        elif score > -0.5: signal, color = "MODERATE BEARISH", _ORANGE
        elif score > -0.8: signal, color = "BEARISH",          _NEGATIVE
        else:              signal, color = "STRONG BEARISH",   _NEGATIVE

        return MacroTrendResult(
            score=round(score, 4), signal=signal, color=color,
            up_count=up, dn_count=dn, directions=dirs,
        )

    # ── Section 2: 4TF COMPLETE ALIGNMENT ────────────────────────

    @classmethod
    def _fourtf_alignment(
        cls,
        stoch_map: dict[str, StochRSIResult],
        ind: dict,
    ) -> FourTFAlignmentResult:
        dirs    = [stoch_map[tf].direction for tf in _LOCAL_TFS if tf in stoch_map]
        dir_map = {tf: stoch_map[tf].direction for tf in _LOCAL_TFS if tf in stoch_map}

        upper_dirs = [dir_map.get(tf, "↔") for tf in ("3m", "5m", "15m")]
        trend_up   = sum(1 for d in upper_dirs if d == "▲")
        trend_dn   = sum(1 for d in upper_dirs if d == "▼")
        base       = "▲" if trend_up > trend_dn else ("▼" if trend_dn > trend_up else None)
        count      = sum(1 for d in dirs if d == base) if base else 0

        # 정렬된 TF의 K-D 평균 스프레드
        ind_key_map = {"1m": "tf1", "3m": "tf3", "5m": "tf5", "15m": "tf15"}
        aligned_spreads = [
            abs(stoch_map[tf].k - stoch_map[tf].d)
            for tf in _LOCAL_TFS
            if tf in stoch_map
            and (base is None or stoch_map[tf].direction == base)
            and ind.get(ind_key_map.get(tf, ""), {}).get("elapsed") is not None
        ]
        avg_sp = sum(aligned_spreads) / len(aligned_spreads) if aligned_spreads else 0.0

        if count == 4 and base == "▲":   color = _POSITIVE
        elif count == 4 and base == "▼": color = _NEGATIVE
        elif count == 3:                  color = _LIGHT_GREEN
        elif count == 2:                  color = _YELLOW
        else:                             color = _DIM

        return FourTFAlignmentResult(
            aligned_count=count,
            base_dir=base or "↔",
            avg_spread=round(avg_sp, 2),
            directions=dir_map,
            color=color,
        )

    # ── Section 3: SIGNAL QUALITY ─────────────────────────────────

    @classmethod
    def _signal_quality(
        cls,
        stoch_map: dict[str, StochRSIResult],
        ind: dict,
        bpr: float,
        vss: float,
    ) -> SignalQualityResult:
        ind_key_map = {
            "1m": "tf1", "3m": "tf3", "5m": "tf5", "15m": "tf15",
            "1h": "tf1h", "4h": "tf4h", "1d": "tf1d",
        }

        def _sig(k: float, d: float) -> int:
            return +1 if k - d > 2 else (-1 if k - d < -2 else 0)

        def _wt(elapsed: str | None) -> float:
            if not elapsed or elapsed == "—": return 0.3
            if elapsed == "방금":             return 1.0
            if "분 전" in elapsed:
                try:
                    m = int(elapsed.split("분")[0].strip())
                    return 1.0 if m <= 30 else 0.7
                except: return 0.7
            if "시간 전" in elapsed:
                try:
                    h = int(elapsed.split("시간")[0].strip())
                    return 0.7 if h <= 2 else (0.4 if h <= 6 else 0.2)
                except: return 0.3
            return 0.15

        w_sc, r_sc, fresh = [], [], 0
        for tf in _ALL_TFS:
            r  = stoch_map[tf]
            sc = _sig(r.k, r.d)
            el = ind.get(ind_key_map.get(tf, ""), {}).get("elapsed")
            w_sc.append(sc * _wt(el))
            r_sc.append(sc)
            if el and ("분 전" in el or el == "방금"):
                try:
                    if el == "방금" or int(el.split("분")[0].strip()) <= 30:
                        fresh += 1
                except: pass

        n_bull = sum(1 for s in r_sc if s > 0)
        n_bear = sum(1 for s in r_sc if s < 0)
        n_dir  = n_bull + n_bear
        agree  = max(n_bull, n_bear) / max(n_dir, 1)
        norm   = max(-1.0, min(1.0, sum(w_sc) / 7.0))

        if   norm >  0.50: direction = "▲▲ BULLISH"
        elif norm >  0.15: direction = "▲ BULLISH"
        elif norm > -0.15: direction = "NEUTRAL"
        elif norm > -0.50: direction = "▼ BEARISH"
        else:              direction = "▼▼ BEARISH"

        bpr_w   = 1.0 + (bpr - 0.5) * 0.3
        vss_w   = 1.0 + min(max(vss - 1.0, 0.0), 0.5) * 0.2
        reliab  = min(85, int(agree * bpr_w * vss_w * 100))
        agree_n = max(n_bull, n_bear)

        sc_col  = _POSITIVE if norm > 0 else (_NEGATIVE if norm < 0 else _YELLOW)
        ag_col  = _POSITIVE if n_bull > n_bear else (_NEGATIVE if n_bear > n_bull else _YELLOW)
        fr_col  = _POSITIVE if fresh >= 4 else (_YELLOW if fresh >= 2 else _ORANGE)
        re_col  = _POSITIVE if reliab >= 65 else (_YELLOW if reliab >= 50 else _ORANGE)

        return SignalQualityResult(
            score=round(norm, 4),
            direction=direction,
            fresh_count=fresh,
            reliability=reliab,
            agree_n=agree_n,
            agree_pct=round(agree, 4),
            n_valid=n_dir,
            score_color=sc_col,
            agree_color=ag_col,
            fresh_color=fr_col,
            rely_color=re_col,
        )
