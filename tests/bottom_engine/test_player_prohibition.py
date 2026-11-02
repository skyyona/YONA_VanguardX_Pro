"""
tests/bottom_engine/test_player_prohibition.py
Player 태그 금지 항목(청산 헌터·FOMO 극단·세력 매집) — 절단 전 전체 키(_player_keys) 판정,
상세 갱신 전 판정 데이터 미준비 보류, 백테스트 입력(롱숏·펀딩비·ATR)과 실거래 판정 일치.
"""
import itertools

import pytest

from bottom_engine.models import PositionSide, ProhibitionFlags
from bottom_engine.prohibition_settings.prohibition_filter import ProhibitionFilter
from middle.analysis.tag_detector import TagDetector

_LONG, _SHORT = PositionSide.LONG, PositionSide.SHORT


def _ind(det):
    """실거래 data_manager._build_ind_dict와 같은 형태 — 절단 전 전체 키."""
    return {"_player_keys": list(det.keys)}


def _check(flags, side, ind):
    return ProhibitionFilter.check(flags, side, ind)


def test_hunter_blocked_even_when_cut_from_display_top4():
    # 롱 86%·FR 0.105%·VSS 4·BPR 0.1·ATR 5% → 고래 매도·FOMO·FR+·롱 스퀴즈 다음 5번째 청산 헌터
    det = TagDetector.detect(86.0, 0.105, 0.0, 4.0, 0.1, 5.0, 1.0)
    assert "청산 헌터" not in [t.tag_key for t in det.tags]          # 표시용 4개에서 절단
    assert "청산 헌터" in det.keys
    r = _check(ProhibitionFlags(common_hunter=True), _LONG, _ind(det))
    assert r.blocked and "청산 헌터" in r.reason


def test_accum_blocked_for_short_even_when_cut():
    # 롱 86%·FR 0.105%·OI +10.1%·VSS 2.6·BPR 0.66·ATR 5% → 세력 매집 6번째(절단)
    det = TagDetector.detect(86.0, 0.105, 10.1, 2.6, 0.66, 5.0, 1.0)
    assert det.keys[4:] == ["고래 매수", "세력 매집"]
    flags = ProhibitionFlags(short_accum=True)
    assert _check(flags, _SHORT, _ind(det)).blocked
    assert not _check(flags, _LONG, _ind(det)).blocked          # 숏 전용 항목


def test_fomo_long_only():
    det = TagDetector.detect(86.0, 0.09, 0.0, 1.0, 0.5, 2.0, 0.0)
    assert "FOMO 극단" in det.keys
    flags = ProhibitionFlags(long_fomo=True)
    assert _check(flags, _LONG, _ind(det)).blocked
    assert not _check(flags, _SHORT, _ind(det)).blocked


def test_no_player_tag_not_blocked():
    det = TagDetector.detect(50.0, 0.0, 0.0, 1.0, 0.5, 2.0, 0.0)
    flags = ProhibitionFlags(common_hunter=True, long_fomo=True, short_accum=True)
    assert not _check(flags, _LONG, _ind(det)).blocked
    assert not _check(flags, _SHORT, _ind(det)).blocked


@pytest.mark.parametrize("flags,side,blocked", [
    (ProhibitionFlags(common_hunter=True), _LONG, True),
    (ProhibitionFlags(common_hunter=True), _SHORT, True),
    (ProhibitionFlags(long_fomo=True), _LONG, True),
    (ProhibitionFlags(long_fomo=True), _SHORT, False),       # 해당 방향 항목 없음
    (ProhibitionFlags(short_accum=True), _SHORT, True),
    (ProhibitionFlags(short_accum=True), _LONG, False),
    (ProhibitionFlags(), _LONG, False),                       # Player 항목 모두 꺼짐
])
def test_player_data_not_ready_holds_entry(flags, side, blocked):
    """상세 갱신 전(_player_keys 없음) — Player 항목이 켜진 방향만 진입 보류."""
    r = _check(flags, side, {"_data_ready": True})
    assert r.blocked is blocked
    if blocked:
        assert r.reason == "Player 판정 데이터 미준비 — 상세 갱신 대기"


def test_backtest_inputs_match_live_for_three_keys():
    """백테스트는 롱숏·펀딩비·ATR만 입력 — 청산 헌터·FOMO 극단 판정은 실거래(전 입력)와 같고,
    세력 매집은 OI 이력이 없어 판정하지 않는다."""
    for lp, fr, atr, oi, vss, bpr, chg in itertools.product(
            (50.0, 79.9, 80.1, 85.1, 92.0), (-0.06, 0.0, 0.081, 0.12), (2.0, 3.0, 3.01, 6.0),
            (0.0, 12.0), (1.0, 3.0), (0.2, 0.7), (0.0, 6.0)):
        live = TagDetector.detect(lp, fr, oi, vss, bpr, atr, chg).keys
        bt = TagDetector.detect(long_pct=lp, fr_pct=fr, atr_pct=atr).keys
        for key in ("청산 헌터", "FOMO 극단"):
            assert (key in live) == (key in bt), (key, lp, fr, atr, oi, vss, bpr, chg)
        assert "세력 매집" not in bt
