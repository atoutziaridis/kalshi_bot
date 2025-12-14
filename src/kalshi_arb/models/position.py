"""Position and order models."""
from __future__ import annotations


from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    """Order side."""

    YES = "yes"
    NO = "no"


class OrderType(str, Enum):
    """Order type."""

    LIMIT = "limit"
    MARKET = "market"


class OrderAction(str, Enum):
    """Order action."""

    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    """Order status."""

    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Order(BaseModel):
    """Trading order."""

    id: str = ""
    ticker: str
    side: OrderSide
    action: OrderAction
    order_type: OrderType = OrderType.LIMIT

    price: int = Field(ge=1, le=99, description="Price in cents")
    quantity: int = Field(ge=1, description="Number of contracts")
    filled_quantity: int = Field(default=0, ge=0)

    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime | None = None

    signal_id: str = ""

    @property
    def is_complete(self) -> bool:
        """Check if order is fully filled or terminal."""
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        )

    @property
    def remaining_quantity(self) -> int:
        """Quantity remaining to fill."""
        return self.quantity - self.filled_quantity

    @property
    def fill_rate(self) -> float:
        """Percentage filled."""
        if self.quantity == 0:
            return 0.0
        return self.filled_quantity / self.quantity

    @property
    def price_decimal(self) -> float:
        """Price as decimal."""
        return self.price / 100


class Position(BaseModel):
    """Open position in a market."""

    ticker: str
    side: OrderSide
    quantity: int = Field(ge=0)
    average_price: float = Field(ge=0.0, le=1.0)

    realized_pnl: float = Field(default=0.0)
    unrealized_pnl: float = Field(default=0.0)

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def cost_basis(self) -> float:
        """Total cost basis."""
        return self.quantity * self.average_price

    @property
    def total_pnl(self) -> float:
        """Total P&L (realized + unrealized)."""
        return self.realized_pnl + self.unrealized_pnl

    def update_unrealized_pnl(self, current_price: float) -> None:
        """Update unrealized P&L based on current price."""
        if self.side == OrderSide.YES:
            self.unrealized_pnl = self.quantity * (current_price - self.average_price)
        else:
            self.unrealized_pnl = self.quantity * (self.average_price - current_price)

    @classmethod
    def from_api_response(cls, data: dict) -> "Position":
        """Create Position from API response."""
        return cls(
            ticker=data.get("ticker", ""),
            side=OrderSide(data.get("side", "yes")),
            quantity=data.get("position", 0),
            average_price=data.get("average_price", 0) / 100,
            realized_pnl=data.get("realized_pnl", 0) / 100,
        )


class PortfolioSummary(BaseModel):
    """Summary of portfolio state."""

    positions: list[Position] = Field(default_factory=list)
    total_value: float = Field(default=0.0)
    cash_balance: float = Field(default=0.0)
    total_realized_pnl: float = Field(default=0.0)
    total_unrealized_pnl: float = Field(default=0.0)

    @property
    def total_pnl(self) -> float:
        """Total P&L across all positions."""
        return self.total_realized_pnl + self.total_unrealized_pnl

    @property
    def position_count(self) -> int:
        """Number of open positions."""
        return len(self.positions)
