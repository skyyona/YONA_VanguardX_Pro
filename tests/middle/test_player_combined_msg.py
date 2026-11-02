"""
tests/middle/test_player_combined_msg.py
3열 에너지 패널 복수 플레이어 통합 메시지 — 절단 전 전체 태그 키, 정확한 키 일치,
상승·하락 혼재 시 경고(한쪽 메시지 우선 표시 금지).
"""
import tkinter as tk

import pytest

import middle.widget.shared_context as _ctx
from middle.data.data_manager import MiddleDataManager
from middle.widget.constants import NEGATIVE, ORANGE, POSITIVE
from middle.widget.middle_panel import MiddlePanel

_MIXED = ("상승·하락 플레이어 혼재\n→ 방향 확인 전 진입 보류 권장", ORANGE)


@pytest.mark.parametrize("keys,expected", [
    # 세력 매집 + 고래 매도 — 기존 '고래' 글자 판정으로 '가장 강력한 상승 신호'였던 경우
    (["세력 매집", "고래 매도"], _MIXED),
    # 상승 2 + 하락 2 — 기존 상승 우선 판정으로 '가장 강력한 상승 신호'였던 경우
    (["세력 매집", "기관 유입", "롱 스퀴즈", "청산 헌터"], _MIXED),
    (["세력 매집", "고래 매수"],
     ("세력 + 대형 자금 동시 매집\n→ 가장 강력한 상승 신호 — 롱 엔진 즉시 진입 강력 권장", POSITIVE)),
    (["FR-", "세력 매집"],
     ("펀딩비 반전 + 세력 매집 이중 상승 신호\n→ 롱 엔진 강력 추천", POSITIVE)),
    (["세력 분산", "청산 헌터"],
     ("세력 이탈 + 청산 헌터 동시 활동\n→ 강한 하락 압력 — 숏 엔진 즉시 진입 강력 권장", NEGATIVE)),
    (["FOMO 극단", "FR+ 과열"],
     ("개인 FOMO + 펀딩비 과열 이중 경고\n→ 상승 말기 역추세 — 숏 엔진 역발상 검토", ORANGE)),
    (["롱 스퀴즈", "청산 헌터"],
     ("롱 스퀴즈 + 청산 헌터 이중 하락 신호\n→ 숏 엔진 즉시 진입 최적 타이밍", NEGATIVE)),
    (["고래 매수", "FR-"],
     ("복수 상승 플레이어 동시 활동\n→ 롱 에너지 복합 확인 — 롱 엔진 진입 권장", POSITIVE)),
    (["고래 매도", "FR+ 과열"],
     ("복수 하락 플레이어 동시 활동\n→ 숏 에너지 복합 확인 — 숏 엔진 진입 권장", NEGATIVE)),
    (["고래 매수"], (None, None)),
])
def test_combined_msg_rules(keys, expected):
    assert MiddlePanel._player_combined_msg(keys) == expected


def test_energy_panel_uses_full_keys_beyond_display_top4(monkeypatch):
    """태그 6개(표시 상위 4개는 모두 하락 계열, 5·6번째 고래 매수·세력 매집) → 전체 키 기준 혼재 경고."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    root.withdraw()
    try:
        m = MiddleDataManager.__new__(MiddleDataManager)
        m._ind_cache = {"CUTUSDT": {"long_ratio": 86.0, "funding_rate": 0.105, "oi_change": 10.1, "vss": 2.6,
                                    "bpr": 0.66, "atr": 5.0, "price_change_pct": 1.0}}
        m._tkr_map, m._onboard_map, m._ranking_rows = {}, {}, []
        monkeypatch.setattr(_ctx, "_data_mgr", m)
        det = m.get_player("CUTUSDT")
        assert [t.tag_key for t in det.tags] == ["FOMO 극단", "FR+ 과열", "롱 스퀴즈", "청산 헌터"]
        assert det.keys[4:] == ["고래 매수", "세력 매집"]
        p = MiddlePanel.__new__(MiddlePanel)
        p._energy_f, p._sel_var, p._sort_mode = tk.Frame(root), tk.StringVar(root, "CUTUSDT"), "24h Ticker"
        p._refresh_energy()
        texts = [w.cget("text") for w in p._energy_f.winfo_children() if isinstance(w, tk.Label)]
        assert _MIXED[0] in texts
        assert not any("FOMO + 펀딩비 과열" in t for t in texts)
    finally:
        root.destroy()
