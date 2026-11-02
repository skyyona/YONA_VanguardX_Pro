"""
tests/middle/test_macro_trend_tie.py
2열 MACRO TREND — 방향 = 일일 추세(1h·4h·1d 중 같은 방향 2개 이상). ▲·▼ 동률·1개뿐이면 중립.
"""
from middle.col2_chart_indicators.macro_4tf_entry import MacroFourTFEntry


def _trend(dirs_kd):
    ind = {key: {"dir": dr, "k": k, "d": d} for key, (dr, k, d) in zip(("tf1h", "tf4h", "tf1d"), dirs_kd)}
    return MacroFourTFEntry.analyze_from_ind(ind).macro_trend


def test_tie_with_neutral_is_neutral():
    r = _trend([("▲", 70.0, 50.0), ("▼", 30.0, 50.0), ("↔", 50.0, 49.0)])
    assert (r.score, r.signal) == (0.0, "NEUTRAL")


def test_all_neutral_is_neutral():
    r = _trend([("↔", 50.0, 49.0), ("↔", 40.0, 41.0), ("↔", 60.0, 59.5)])
    assert (r.score, r.signal) == (0.0, "NEUTRAL")


def test_majority_sets_direction():
    assert _trend([("▲", 70.0, 50.0), ("▲", 60.0, 50.0), ("↔", 50.0, 49.0)]).score > 0
    assert _trend([("▼", 30.0, 50.0), ("▼", 40.0, 50.0), ("↔", 50.0, 49.5)]).score < 0
    assert _trend([("▼", 30.0, 50.0), ("↔", 50.0, 49.0), ("↔", 50.0, 49.5)]).signal == "NEUTRAL"   # 1개뿐
