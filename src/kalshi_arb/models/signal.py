"""Trading signal models."""
from __future__ import annotations


from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SignalDirection(str, Enum):
    """Direction of trading signal."""

    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"


class SignalType(str, Enum):
    """Type of signal source."""

    REBALANCING = "rebalancing"
    CONSTRAINT_VIOLATION = "constraint_violation"
    COMBINATORIAL = "combinatorial"


class DirectionalSignal(BaseModel):
    """
    Trading signal generated from constraint violations.

    Represents a directional bet when market price violates logical bounds.
    """

    ticker: str
    direction: SignalDirection
    signal_type: SignalType = SignalType.CONSTRAINT_VIOLATION

    current_price: float = Field(ge=0.0, le=1.0)
    bound_price: float = Field(ge=0.0, le=1.0)

    raw_edge: float = Field(description="Edge before costs")
    estimated_fee: float = Field(default=0.0, ge=0.0)
    estimated_spread: float = Field(default=0.0, ge=0.0)
    net_edge: float = Field(description="Edge after costs")

    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_constraint_id: str = ""

    created_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime | None = None

    @property
    def is_valid(self) -> bool:
        """Check if signal is still valid (not expired)."""
        if self.expires_at is None:
            return True
        return datetime.now() < self.expires_at

    @property
    def total_costs(self) -> float:
        """Total estimated costs."""
        return self.estimated_fee + self.estimated_spread

    @classmethod
    def create(
        cls,
        ticker: str,
        direction: SignalDirection,
        current_price: float,
        bound_price: float,
        fee: float = 0.0,
        spread: float = 0.0,
        signal_type: SignalType = SignalType.CONSTRAINT_VIOLATION,
        constraint_id: str = "",
        confidence: float = 1.0,
    ) -> "DirectionalSignal":
        """Create a signal with calculated edges."""
        if direction == SignalDirection.BUY_YES:
            raw_edge = bound_price - current_price
        else:
            raw_edge = current_price - bound_price

        net_edge = raw_edge - fee - spread

        return cls(
            ticker=ticker,
            direction=direction,
            signal_type=signal_type,
            current_price=current_price,
            bound_price=bound_price,
            raw_edge=raw_edge,
            estimated_fee=fee,
            estimated_spread=spread,
            net_edge=net_edge,
            confidence=confidence,
            source_constraint_id=constraint_id,
        )


class RebalancingOpportunity(BaseModel):
    """
    Market rebalancing arbitrage opportunity.

    Detected when sum of YES prices deviates from 1.0.
    """

    market_id: str
    side: str = Field(description="'long' if sum < 1, 'short' if sum > 1")
    conditions: list[str] = Field(default_factory=list)
    prices: list[float] = Field(default_factory=list)

    price_sum: float
    deviation: float = Field(description="Absolute deviation from 1.0")

    profit_pre_fee: float
    total_fees: float
    profit_post_fee: float

    min_liquidity: int = Field(default=0, description="Minimum depth across conditions")
    created_at: datetime = Field(default_factory=datetime.now)

    @property
    def is_profitable(self) -> bool:
        """Check if opportunity is profitable after fees."""
        return self.profit_post_fee > 0.01

    @property
    def is_long(self) -> bool:
        """Check if this is a long rebalancing opportunity."""
        return self.side == "long"
