"""
bottom/engine_core/fourtf_consensus.py
4TF 완전 합의 판단 — 롱·숏 공통 진입 조건 핵심
1m/3m/5m/15m 전체 StochRSI K>D(롱) 또는 K<D(숏) 완전 일치 시 합의
"""
from __future__ import annotations

from bottom.models import FourTFSignal

TF_KEYS = ("1m", "3m", "5m", "15m")

# StochRSI K-D 최소 스프레드 (크로스 강도 필터 — 너무 약한 신호 제외)
MIN_SPREAD = 2.0


class FourTFConsensus:
    """4TF 완전 합의 평가기.

    middle module DataManager의 get_ind(symbol) 반환 dict에서
    tf1/tf3/tf5/tf15 StochRSI K·D 값을 읽어 합의 여부 판정.
    """

    @classmethod
    def evaluate(cls, ind_data: dict) -> FourTFSignal:
        """ind_data (get_ind 반환 dict) → FourTFSignal 반환."""
        tf_key_map = {
            "1m": "tf1", "3m": "tf3", "5m": "tf5", "15m": "tf15",
        }

        long_count  = 0
        short_count = 0
        details: dict[str, dict] = {}

        for tf, ind_key in tf_key_map.items():
            tf_dict = ind_data.get(ind_key, {})
            k = float(tf_dict.get("k", 50.0))
            d = float(tf_dict.get("d", 50.0))
            spread = abs(k - d)

            if k > d and spread >= MIN_SPREAD:
                direction = "▲"
                long_count += 1
            elif k < d and spread >= MIN_SPREAD:
                direction = "▼"
                short_count += 1
            else:
                direction = "↔"

            details[tf] = {"k": k, "d": d, "dir": direction, "spread": round(spread, 2)}

        return FourTFSignal(
            long_consensus  = (long_count  == 4),
            short_consensus = (short_count == 4),
            aligned_long    = long_count,
            aligned_short   = short_count,
            details         = details,
        )

    @classmethod
    def from_stochrsi_map(cls, stoch_map: dict) -> FourTFSignal:
        """StochRSIResult dict (tf → StochRSIResult) 기반으로 직접 평가.
        DataManager를 거치지 않고 직접 StochRSI 결과를 받을 때 사용.
        """
        fake_ind: dict = {}
        key_map = {"1m": "tf1", "3m": "tf3", "5m": "tf5", "15m": "tf15"}
        for tf, ind_key in key_map.items():
            r = stoch_map.get(tf)
            if r:
                fake_ind[ind_key] = {"k": r.k, "d": r.d}
        return cls.evaluate(fake_ind)

