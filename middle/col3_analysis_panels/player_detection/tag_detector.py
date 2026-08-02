"""
middle/col3_analysis_panels/player_detection/tag_detector.py
Player Detection 태그 감지 — 시장 데이터 기반 세력/고래/FOMO 패턴 추론
_refresh_energy() 패널 / Sharp rise·decline 스코어러 s_player 항목에 연동

태그 감지 규칙 (현재 가용 공개 API 기반):
  FR·OI·L/S비율·VSS·BPR·ATR 조합으로 8종 태그 추론
"""
from __future__ import annotations

from dataclasses import dataclass, field


from middle.widget.constants import (
    POSITIVE as _POSITIVE, NEGATIVE as _NEGATIVE, ORANGE as _ORANGE,
    ACCENT_BLUE as _ACCENT_BLUE, YELLOW as _YELLOW, LIGHT_GREEN as _LGR,
)
_LIGHT_GREEN = _LGR

# ── 태그별 UI 정보 (action 설명·색상) — _PLAYER_INFO 대응 ──────
_TAG_META: dict[str, tuple[str, str]] = {
    "세력 매집":   ("가격 횡보 속 대규모 포지션 지속 누적 중",        _POSITIVE),
    "세력 분산":   ("상승 구간 내 보유 물량 단계적 분산 진행",         _NEGATIVE),
    "고래 매수":   ("대형 단일 체결 — 즉각적 매수 압력 발생",          _POSITIVE),
    "고래 매도":   ("대형 단일 체결 — 즉각적 매도 압력 발생",          _NEGATIVE),
    "기관 유입":   ("기관급 롱 비율 급증 — 중기 자금 유입 진행 중",    _ACCENT_BLUE),
    "롱 스퀴즈":   ("롱 포지션 극단 과밀 — 강제 청산 연쇄 위험 누적",  _NEGATIVE),
    "청산 헌터":   ("롱 청산 구간 세력 집중 활동 포착 중",             _NEGATIVE),
    "FOMO 극단":   ("개인 롱 극단 쏠림 — 90%+ 과밀 누적 상태",        _ORANGE),
    "FR-":         ("숏 과밀 — 음수 펀딩비로 상방 압박 형성 중",       _LIGHT_GREEN),
    "FR+ 과열":    ("롱 과밀 — 펀딩비 과열로 비용 압박 강함",          _ORANGE),
}

# ── 이모지 접두어 ───────────────────────────────────────────────
_TAG_EMOJI: dict[str, str] = {
    "세력 매집":  "⚡",
    "세력 분산":  "⚡",
    "고래 매수":  "🐋",
    "고래 매도":  "🐋",
    "기관 유입":  "🏛",
    "롱 스퀴즈":  "💥",
    "청산 헌터":  "🎯",
    "FOMO 극단":  "👤",
    "FR-":        "💰",
    "FR+ 과열":   "💰",
}


@dataclass
class PlayerTag:
    tag_key:      str    # 키 (e.g., "세력 매집")
    tag_text:     str    # 표시 텍스트 (e.g., "⚡ 세력 매집")
    tag_color:    str    # 표시 색상
    strength_pct: int    # 강도 % (0~100)
    action:       str    # 시장 구조 설명 문장


@dataclass
class TagDetectionResult:
    tags:           list[PlayerTag] = field(default_factory=list)
    has_rise_tag:   bool = False    # Sharp Rise 스코어러 s_player 판정용
    has_decline_tag: bool = False   # Sharp Decline 스코어러 s_player 판정용


def _make_tag(key: str, strength: int) -> PlayerTag:
    action, color = _TAG_META[key]
    emoji = _TAG_EMOJI.get(key, "")
    return PlayerTag(
        tag_key=key,
        tag_text=f"{emoji} {key}".strip(),
        tag_color=color,
        strength_pct=min(100, max(1, strength)),
        action=action,
    )


class TagDetector:
    """시장 데이터 기반 Player Detection 태그 감지기.

    감지 규칙 (공개 API 기반 추론):
      - 세력 매집:  OI 증가 > 10% + 가격 변동 작음(±3%) + VSS > 1.5
      - 세력 분산:  OI 감소 < -5% + 가격 상승 > 5%
      - 고래 매수:  VSS > 2.5 + BPR > 0.65
      - 고래 매도:  VSS > 2.5 + BPR < 0.35
      - 기관 유입:  롱 비율 > 65% + OI 증가 > 8% + FR 중립(-0.05%~+0.08%)
      - 롱 스퀴즈:  롱 비율 > 80% + FR > 0.10%
      - 청산 헌터:  롱 비율 > 80% + ATR > 3.0%
      - FOMO 극단:  롱 비율 > 85% + FR > 0.08%
      - FR-:        FR < -0.05%  (숏 과밀 실질 기준)
      - FR+ 과열:   FR > 0.10%  (롱 과밀 실질 기준)
    """

    # Sharp Rise 스코어러 판정 키워드 (= _PLAYER_INFO의 rise_kw)
    RISE_KEYS    = {"고래 매수", "세력 매집", "기관 유입", "FR-"}
    # Sharp Decline 스코어러 판정 키워드
    DECLINE_KEYS = {"FR+ 과열", "FOMO 극단", "롱 스퀴즈", "청산 헌터", "세력 분산", "고래 매도"}

    @classmethod
    def detect(
        cls,
        long_pct:      float = 50.0,   # 롱 계좌 비율 %
        fr_pct:        float = 0.0,    # 펀딩비 % (FundingRateAnalysis.rate_pct)
        oi_change_pct: float = 0.0,    # OI 변화율 %
        vss:           float = 1.0,    # Volume Surge Score
        bpr:           float = 0.5,    # Buying Pressure Ratio (0~1)
        atr_pct:       float = 2.0,    # ATR%
        price_chg_pct: float = 0.0,    # 24h 가격 변화 %
    ) -> TagDetectionResult:
        """시장 지표 조합으로 Player 태그 감지."""
        tags: list[PlayerTag] = []
        short_pct = 100.0 - long_pct

        # ① 세력 매집: OI 급증 + 가격 횡보 + 거래량 증가 (기준 강화)
        if oi_change_pct > 10.0 and abs(price_chg_pct) < 3.0 and vss > 1.5:
            strength = min(100, int(oi_change_pct * 3 + vss * 15))
            tags.append(_make_tag("세력 매집", strength))

        # ② 세력 분산: OI 감소 + 가격 상승 (보유 물량 분산)
        if oi_change_pct < -5.0 and price_chg_pct > 5.0:
            strength = min(100, int(abs(oi_change_pct) * 3 + price_chg_pct * 2))
            tags.append(_make_tag("세력 분산", strength))

        # ③ 고래 매수: VSS 급등 + 매수 압박 강함 (VSS 기준 강화)
        if vss > 2.5 and bpr > 0.65:
            strength = min(100, int(vss * 20 + bpr * 30))
            tags.append(_make_tag("고래 매수", strength))

        # ④ 고래 매도: VSS 급등 + 매도 압박 강함 (VSS 기준 강화)
        if vss > 2.5 and bpr < 0.35:
            strength = min(100, int(vss * 20 + (1 - bpr) * 30))
            tags.append(_make_tag("고래 매도", strength))

        # ⑤ 기관 유입: 롱 과밀 + OI 급증 + FR 중립 (FR- 영역 기준 강화 반영)
        if long_pct > 65.0 and oi_change_pct > 8.0 and -0.05 <= fr_pct < 0.08:
            strength = min(100, int(long_pct * 0.7 + oi_change_pct * 0.8))
            tags.append(_make_tag("기관 유입", strength))

        # ⑥ 롱 스퀴즈: 롱 극단 + FR 양수 과열 (기준 강화)
        if long_pct > 80.0 and fr_pct > 0.10:
            strength = min(100, int(long_pct * 0.8 + fr_pct * 200))
            tags.append(_make_tag("롱 스퀴즈", strength))

        # ⑦ 청산 헌터: 롱 극단 + 고변동성
        if long_pct > 80.0 and atr_pct > 3.0:
            strength = min(100, int(long_pct * 0.7 + atr_pct * 3))
            tags.append(_make_tag("청산 헌터", strength))

        # ⑧ FOMO 극단: 극단 롱 쏠림 + FR 과열
        if long_pct > 85.0 and fr_pct > 0.08:
            strength = min(100, int(long_pct * 0.8 + fr_pct * 300))
            tags.append(_make_tag("FOMO 극단", strength))

        # ⑨ FR- 신호: 숏 과밀 실질 기준 (기준 강화)
        if fr_pct < -0.05:
            strength = min(100, int(abs(fr_pct) * 800 + 20))
            tags.append(_make_tag("FR-", strength))

        # ⑩ FR+ 과열 신호: 롱 과밀 실질 기준 (기준 강화)
        if fr_pct > 0.10:
            strength = min(100, int(fr_pct * 800 + 20))
            tags.append(_make_tag("FR+ 과열", strength))

        # 강도 내림차순 정렬, 최대 4개
        tags.sort(key=lambda t: t.strength_pct, reverse=True)
        tags = tags[:4]

        # Sharp rise/decline 판정
        detected_keys = {t.tag_key for t in tags}
        has_rise    = bool(detected_keys & cls.RISE_KEYS)
        has_decline = bool(detected_keys & cls.DECLINE_KEYS)

        return TagDetectionResult(
            tags=tags,
            has_rise_tag=has_rise,
            has_decline_tag=has_decline,
        )

