"""
YONA VanguardX Pro — 모듈 간 상태 공유 이벤트 버스
헤더·중단·하단 모듈이 공유하는 tk.StringVar 인스턴스를 관리
"""
from __future__ import annotations

import tkinter as tk


class EventBus:
    """세 모듈이 공유하는 상태 변수 컨테이너.

    main.py 에서 tk.Tk() 루트 생성 직후 인스턴스화하여
    각 모듈 위젯 생성자에 전달한다.
    """

    def __init__(self, master: tk.Misc) -> None:
        # 중단 → 하단: 배정된 심볼
        self.assigned_sym: tk.StringVar = tk.StringVar(master, value="")
        # 중단 → 하단: 현재 Sort by 모드
        self.shared_sort_mode: tk.StringVar = tk.StringVar(master, value="24h Ticker")
        # 앱 상태: 'IDLE' / 'RANKING' / 'ANALYSIS'
        self.app_state: tk.StringVar = tk.StringVar(master, value="IDLE")
