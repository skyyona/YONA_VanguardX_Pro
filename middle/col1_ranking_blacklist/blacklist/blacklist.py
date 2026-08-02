"""
middle/col1_ranking_blacklist/blacklist.py
블랙리스트 관리 · 영속화 (JSON 파일 기반)
거래 금지·상장폐지·이슈 심볼을 관리하고 랭킹에서 제외
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

_BLACKLIST_PATH = Path(__file__).parent / "_blacklist.json"


@dataclass
class BlacklistEntry:
    symbol:     str
    added_utc:  str    # "2025-03-12 14:23 UTC"
    status:     str    # "DELISTED" | "SETTLING" | "HALT" | "MANUAL"
    reason:     str = ""


class BlacklistManager:
    """블랙리스트 관리자 — JSON 파일 기반 영속화."""

    def __init__(self, path: Path = _BLACKLIST_PATH) -> None:
        self._path    = path
        self._entries: dict[str, BlacklistEntry] = {}
        self.load()

    # ── CRUD ──────────────────────────────────────────────────
    def add(self, symbol: str, status: str = "MANUAL", reason: str = "") -> None:
        now_utc = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        self._entries[symbol] = BlacklistEntry(
            symbol=symbol, added_utc=now_utc, status=status, reason=reason
        )
        self.save()

    def remove(self, symbol: str) -> bool:
        if symbol in self._entries:
            del self._entries[symbol]
            self.save()
            return True
        return False

    def is_blacklisted(self, symbol: str) -> bool:
        return symbol in self._entries

    def get_all(self) -> list[BlacklistEntry]:
        return sorted(self._entries.values(), key=lambda e: e.added_utc, reverse=True)

    # ── 영속화 ────────────────────────────────────────────────
    def load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._entries = {
                d["symbol"]: BlacklistEntry(**d) for d in data
            }
        except Exception:
            self._entries = {}

    def save(self) -> None:
        try:
            self._path.write_text(
                json.dumps([asdict(e) for e in self._entries.values()],
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

