"""
tests/middle/test_trend_definition.py
일일 추세(1h·4h·1d 중 같은 방향 2개 이상)·단기 추세(1m·3m·5m·15m 중 3개 이상) 단일 정의 —
1열 4TF Optimization 점수(기준 방향·단기일치·일일강도)·2열 MACRO TREND·4TF COMPLETE ALIGNMENT가 같은 정의를 쓰는지 검증.
"""
import pytest

import middle.widget.shared_context as _ctx
from middle.analysis.trend import Trend, daily_trend, short_trend, trend_text
from middle.col1_ranking.ranking.fourtf_scorer import FourTFScorer
from middle.col2_chart_indicators.macro_4tf_entry import MacroFourTFEntry

_DAILY = ("tf1h", "tf4h", "tf1d")
_SHORT = ("tf1", "tf3", "tf5", "tf15")


def _ind(daily, short, **extra):
    ind = {k: {"dir": d, "k": 50.0, "d": 50.0} for k, d in zip(_DAILY, daily)}
    ind.update({k: {"dir": d, "k": 50.0, "d": 50.0} for k, d in zip(_SHORT, short)})
    ind.update(extra)
    return ind


@pytest.mark.parametrize("dirs,expected", [
    (("▲", "▲", "▲"), Trend("▲", 3, 3, 3, 0)),
    (("▲", "▲", "▼"), Trend("▲", 2, 3, 2, 1)),
    (("▼", "↔", "▼"), Trend("▼", 2, 3, 0, 2)),
    (("▲", "▼", "↔"), Trend(None, 1, 3, 1, 1)),
    (("▲", "↔", "↔"), Trend(None, 1, 3, 1, 0)),
    (("↔", "↔", "↔"), Trend(None, 0, 3, 0, 0)),
])
def test_daily_trend(dirs, expected):
    assert daily_trend(_ind(dirs, ("↔",) * 4)) == expected


@pytest.mark.parametrize("dirs,expected", [
    (("▲", "▲", "▲", "▲"), Trend("▲", 4, 4, 4, 0)),
    (("▲", "▲", "▲", "▼"), Trend("▲", 3, 4, 3, 1)),
    (("▼", "▼", "↔", "▼"), Trend("▼", 3, 4, 0, 3)),
    (("▲", "▲", "▼", "▼"), Trend(None, 2, 4, 2, 2)),
    (("↔", "▲", "▲", "↔"), Trend(None, 2, 4, 2, 0)),
])
def test_short_trend(dirs, expected):
    assert short_trend(_ind(("↔",) * 3, dirs)) == expected


def test_missing_tf_data_is_neutral():
    assert daily_trend({}).direction is None and short_trend({}).direction is None
    assert trend_text(daily_trend({})) == "↔ 중립"
    assert trend_text(Trend("▼", 2, 3, 0, 2)) == "▼ 2/3"


def _score(monkeypatch, ind):
    monkeypatch.setattr(_ctx, "_data_mgr", type("DM", (), {"get_ind": lambda self, s: ind})())
    return FourTFScorer.calc_score("XUSDT")


def test_4tf_base_is_daily_not_1h(monkeypatch):
    """1h ▼ 이어도 4h·1d ▲ 이면 기준 방향 ▲ (기존: 1h 단독 기준 ▼)."""
    res = _score(monkeypatch, _ind(("▼", "▲", "▲"), ("▲", "▲", "▲", "▼")))
    assert res["base_dir"] == "▲" and res["daily"].direction == "▲"
    assert res["scores"]["align"] == 3 and res["scores"]["macro"] == 1


def test_4tf_daily_strength_and_neutral(monkeypatch):
    res = _score(monkeypatch, _ind(("▼", "▼", "▼"), ("▼", "▼", "▼", "▼"), long_ratio=30.0,
                                   tf1={"dir": "▼", "k": 85.0, "d": 50.0}))
    sc = res["scores"]
    assert (sc["align"], sc["macro"], sc["entry"], sc["balance"]) == (4, 2, 1, 1)
    neutral = _score(monkeypatch, _ind(("▲", "▼", "↔"), ("▲", "▲", "▲", "▲"), long_ratio=70.0))
    assert neutral["base_dir"] is None
    assert (neutral["scores"]["align"], neutral["scores"]["macro"],
            neutral["scores"]["entry"], neutral["scores"]["balance"]) == (0, 0, 0, 0)


def test_col2_macro_trend_follows_daily():
    """MACRO TREND 방향 = 일일 추세 — 같은 방향 1개뿐이면 중립 (기존: ▲ 1개도 상승 표시)."""
    assert MacroFourTFEntry.analyze_from_ind(_ind(("▲", "↔", "↔"), ("↔",) * 4)).macro_trend.signal == "NEUTRAL"
    assert MacroFourTFEntry.analyze_from_ind(_ind(("▲", "▲", "↔"), ("↔",) * 4)).macro_trend.score > 0


def test_col2_4tf_alignment_follows_short():
    """4TF COMPLETE ALIGNMENT 기준 = 단기 추세(1m 포함 3개 이상) — 기존 3m·5m·15m 다수결 2개는 중립."""
    fa = MacroFourTFEntry.analyze_from_ind(_ind(("↔",) * 3, ("↔", "▲", "▲", "↔"))).fourtf_align
    assert (fa.base_dir, fa.aligned_count) == ("↔", 0)
    fa = MacroFourTFEntry.analyze_from_ind(_ind(("↔",) * 3, ("▲", "▲", "↔", "▲"))).fourtf_align
    assert (fa.base_dir, fa.aligned_count) == ("▲", 3)
