"""
bottom/models.py
하단 거래 엔진 모듈 데이터 모델 전체
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ── 기본 열거형 ──────────────────────────────────────────────────
class PositionSide(str, Enum):
    LONG  = "long"
    SHORT = "short"


class PositionState(str, Enum):
    IDLE    = "idle"      # 포지션 없음
    PENDING = "pending"   # 진입 주문 대기
    OPEN    = "open"      # 포지션 보유 중
    CLOSING = "closing"   # 청산 주문 진행 중
    CLOSED  = "closed"    # 청산 완료


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT  = "LIMIT"


class OrderSide(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


# ── 전략 파라미터 ─────────────────────────────────────────────────
@dataclass
class ProhibitionFlags:
    """절대 거래 금지 체크리스트 10개 항목 상태."""
    common_macro:     bool = False   # 거시 추세(1H·4H·1D) 반대 방향 거래 금지
    common_liq:       bool = False   # 청산 근접도 위험 구간
    common_atr:       bool = False   # ATR% 과도 변동성 (8% 초과)
    common_fr:        bool = False   # FR 임계치 초과
    common_new:       bool = False   # 신규 상장 심볼 (14일 미만)
    common_hunter:    bool = False   # Player Detection 청산 헌터
    long_fomo:        bool = False   # FOMO 극단 태그 — 롱 금지
    long_short_open:  bool = True    # 숏 보유 중 동시 롱 금지 (One-way Mode 기본 활성)
    short_accum:      bool = False   # 세력 매집 태그 — 숏 금지
    short_long_open:  bool = True    # 롱 보유 중 동시 숏 금지 (One-way Mode 기본 활성)

    @classmethod
    def from_dict(cls, d: dict) -> "ProhibitionFlags":
        return cls(**{k: bool(v) for k, v in d.items() if hasattr(cls, k)})

    def to_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


@dataclass
class StrategyParams:
    """사용자가 전략 팝업에서 설정하는 전체 파라미터."""
    sort_mode:      str   = "24h Ticker"
    funds_pct:      int   = 100         # Designated Funds (% of portfolio)
    leverage:       int   = 10          # Applied Leverage
    stop_loss:      float = 2.5         # Stop Loss (%)
    trail_stop:     float = 1.5         # Trailing Stop (%)
    prohibition:    ProhibitionFlags = field(default_factory=ProhibitionFlags)
    use_macro:      bool             = True   # 거시적 추세(1H·4H·1D) 연동 여부
    consensus_mode: str              = "4/4"  # 4TF 합의 모드 ("4/4" | "3/4")
    portfolio_usdt: float            = 1000.0 # [B-1] 백테스트 기준 자본금 (실잔고 주입)

    @classmethod
    def from_applied_params(cls, d: dict, sort_mode: str = "24h Ticker") -> "StrategyParams":
        p = cls()
        p.sort_mode      = sort_mode
        p.funds_pct      = int(d.get("funds", 100))
        p.leverage       = int(d.get("leverage", 10))
        p.stop_loss      = float(d.get("sl", 2.5))
        p.trail_stop     = float(d.get("trail", 1.5))
        p.prohibition    = ProhibitionFlags.from_dict(d.get("prohibited", {}))
        p.use_macro      = bool(d.get("use_macro", True))
        p.consensus_mode = str(d.get("consensus_mode", "4/4"))
        return p


# ── 4TF 합의 신호 ─────────────────────────────────────────────────
@dataclass
class FourTFSignal:
    """4TF 완전 합의 평가 결과."""
    long_consensus:  bool  = False   # 4TF 전부 K > D (강세)
    short_consensus: bool  = False   # 4TF 전부 K < D (약세)
    aligned_long:    int   = 0       # 강세 일치 TF 수 (0~4)
    aligned_short:   int   = 0       # 약세 일치 TF 수 (0~4)
    details: dict[str, dict] = field(default_factory=dict)  # {tf: {k, d, dir}}


# ── 주문 ─────────────────────────────────────────────────────────
@dataclass
class Order:
    """거래소에 전송할 주문 정보."""
    symbol:     str
    side:       OrderSide
    order_type: OrderType       = OrderType.MARKET
    quantity:   float           = 0.0
    price:      float | None    = None   # LIMIT 주문 시 사용
    leverage:   int             = 10
    stop_loss_pct:  float       = 2.5
    trail_stop_pct: float       = 1.5


@dataclass
class OrderResult:
    """주문 실행 결과."""
    success:   bool
    order_id:  str   = ""
    fill_price: float = 0.0
    quantity:   float = 0.0
    error:     str   = ""


# ── 포지션 ───────────────────────────────────────────────────────
@dataclass
class Position:
    """보유 중인 포지션 상태."""
    symbol:        str
    side:          PositionSide
    state:         PositionState   = PositionState.IDLE
    entry_price:   float           = 0.0
    quantity:      float           = 0.0
    leverage:      int             = 10
    stop_loss_pct: float           = 2.5
    trail_stop_pct: float          = 1.5
    trailing_high: float           = 0.0   # 롱: 최고가 추적 (SL 이동 기준)
    trailing_low:  float           = 0.0   # 숏: 최저가 추적
    current_sl:    float           = 0.0   # 현재 SL 가격
    pnl_pct:       float           = 0.0
    pnl_usdt:      float           = 0.0
    phase:         int             = 1     # 멀티페이즈: 1=초기SL, 2=BEP이동, 3=트레일링
    partial_closed:     bool       = False  # Phase3 50% 부분 청산 완료 여부
    partial_in_progress: bool      = False  # 부분 청산 API 호출 진행 중 (중복 호출 방지)
    exit_price:    float           = 0.0   # 청산 체결가 (CLOSED 시 기록)
    exit_reason:   str             = ""    # 청산 사유 (CLOSED 시 기록)
    entry_time:    float           = 0.0   # 진입 체결 시각 (unix timestamp)
    exit_time:     float           = 0.0   # 청산 체결 시각 (unix timestamp)


# ── 리스크 체크 ──────────────────────────────────────────────────
@dataclass
class RiskCheckResult:
    """리스크 관리자 검증 결과."""
    allowed:  bool
    reason:   str  = ""   # 거부 사유 (allowed=False 시)


# ── 백테스팅 결과 ─────────────────────────────────────────────────
@dataclass
class BacktestTrade:
    """백테스팅 단일 거래 기록."""
    entry_time:  int    # Unix ms
    exit_time:   int
    side:        str
    entry_price: float
    exit_price:  float
    pnl_pct:     float
    pnl_usdt:    float
    exit_reason: str    # "SL" | "TP" | "TRAIL" | "SIGNAL"


@dataclass
class BacktestResult:
    """백테스팅 전체 결과."""
    symbol:       str
    sort_mode:    str
    period_days:  int
    total_trades: int       = 0
    win_trades:   int       = 0
    loss_trades:  int       = 0
    win_rate:     float     = 0.0    # %
    total_return: float     = 0.0    # %
    max_profit:   float     = 0.0    # %
    max_drawdown: float     = 0.0    # % (MDD)
    avg_profit:   float     = 0.0    # %
    avg_loss:     float     = 0.0    # %
    trades:       list[BacktestTrade] = field(default_factory=list)

