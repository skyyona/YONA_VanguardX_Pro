"""
middle/col3_analysis_panels/comprehensive_analysis/derivative_verdict.py
파생분석 종합 판단 — 종합분석 패널 "파생" 요약 라인 + 주의·위험 라인
_refresh_verdict() 파생 요약 / 주의 / 위험 라인 로직 대응
"""
from __future__ import annotations

from dataclasses import dataclass, field

from middle.widget.constants import (
    POSITIVE as _POSITIVE, NEGATIVE as _NEGATIVE,
    ORANGE as _ORANGE, ACCENT_BLUE as _ACCENT_BLUE,
)


@dataclass
class DerivativeVerdict:
    prefix:  str
    summary: str
    suffix:  str
    color:   str


@dataclass
class DerivativeVerdictResult:
    derivative_line: DerivativeVerdict
    warning_lines:   list[DerivativeVerdict] = field(default_factory=list)
    risk_lines:      list[DerivativeVerdict] = field(default_factory=list)


class DerivativeVerdictPanel:
    """파생분석 종합 판단 생성기."""

    @staticmethod
    def analyze(
        oi_change_pct:  float,
        player_tags:    list,          # PlayerTag 리스트
        fr_pct:         float = 0.0,   # 펀딩비 %
        long_pct:       float = 50.0,  # 롱 계좌 비율 %
        rec_leverage:   int   = 10,    # 권장 레버리지 (주의 계산용)
    ) -> DerivativeVerdictResult:
        """OI·Player·FR·L/S → 파생 종합 판단 라인 생성."""

        # ① 파생 요약 라인
        oi_txt   = f"OI {oi_change_pct:+.1f}%"
        player_txt = (
            "·".join(" ".join(t[0].split()[:2]) for t in player_tags)
            if player_tags else "세력 감지 없음"
        )
        if oi_change_pct > 5:
            oi_suffix, oi_col = "→ 자금 유입·상승 압력", _POSITIVE
        elif oi_change_pct < -5:
            oi_suffix, oi_col = "→ 자금 유출·하락 압력", _NEGATIVE
        else:
            oi_suffix, oi_col = "→ 자금 변동 확인", _ACCENT_BLUE

        deriv_line = DerivativeVerdict(
            prefix="파생 ",
            summary=f"{oi_txt}·{player_txt}",
            suffix=oi_suffix,
            color=oi_col,
        )

        # ② 주의 라인 (FR 과열 시)
        warnings: list[DerivativeVerdict] = []
        if abs(fr_pct) > 0.03:
            daily = abs(fr_pct) * 3 * rec_leverage
            warnings.append(DerivativeVerdict(
                prefix="주의 ",
                summary=f"펀딩비 {fr_pct:+.3f}%",
                suffix=f"→ 하루 {daily:.1f}% 비용 누적",
                color=_ORANGE,
            ))

        # ③ 위험 라인 (L/S 과쏠림 시)
        risks: list[DerivativeVerdict] = []
        if long_pct > 75:
            risks.append(DerivativeVerdict(
                prefix="위험 ",
                summary=f"롱 {long_pct:.0f}% 쏠림",
                suffix="→ 80% 초과 시 스퀴즈 경계",
                color=_ORANGE,
            ))
        elif long_pct < 30:
            risks.append(DerivativeVerdict(
                prefix="위험 ",
                summary=f"숏 {100-long_pct:.0f}% 쏠림",
                suffix="→ 숏 스퀴즈 가능성",
                color=_ORANGE,
            ))

        return DerivativeVerdictResult(
            derivative_line=deriv_line,
            warning_lines=warnings,
            risk_lines=risks,
        )

