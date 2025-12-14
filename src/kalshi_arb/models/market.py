"""Market and order book data models."""
from __future__ import annotations


from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, computed_field


class MarketStatus(str, Enum):
    """Market status enumeration."""

    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"


class SettlementSource(BaseModel):
    """Settlement data source."""

    name: str
    url: str = ""


class OrderBookLevel(BaseModel):
    """Single level in the order book."""

    price: int = Field(ge=1, le=99, description="Price in cents")
    quantity: int = Field(ge=0, description="Number of contracts")


class OrderBook(BaseModel):
    """Order book for a market."""

    yes_bids: list[OrderBookLevel] = Field(default_factory=list)
    ticker: str = ""

    @computed_field
    @property
    def best_yes_bid(self) -> float | None:
        """Best YES bid price as decimal (0-1)."""
        if not self.yes_bids:
            return None
        return max(level.price for level in self.yes_bids) / 100

    @computed_field
    @property
    def best_yes_ask(self) -> float | None:
        """Best YES ask price (derived from NO bids)."""
        if not self.yes_bids:
            return None
        return (100 - min(level.price for level in self.yes_bids)) / 100

    @computed_field
    @property
    def best_no_bid(self) -> float | None:
        """Best NO bid price (100 - best YES ask)."""
        if not self.yes_bids:
            return None
        return (100 - max(level.price for level in self.yes_bids)) / 100

    @computed_field
    @property
    def mid_price(self) -> float | None:
        """Mid-market price for YES."""
        if self.best_yes_bid is None or self.best_yes_ask is None:
            return None
        return (self.best_yes_bid + self.best_yes_ask) / 2

    @computed_field
    @property
    def spread(self) -> float | None:
        """Bid-ask spread."""
        if self.best_yes_bid is None or self.best_yes_ask is None:
            return None
        return self.best_yes_ask - self.best_yes_bid

    def depth_at_price(self, price_cents: int, side: str = "yes") -> int:
        """Get total quantity at or better than price."""
        if side == "yes":
            return sum(
                level.quantity for level in self.yes_bids if level.price >= price_cents
            )
        return sum(
            level.quantity for level in self.yes_bids if level.price <= price_cents
        )

    def total_depth(self, within_cents: int = 5) -> int:
        """Get total quantity within X cents of best bid."""
        if not self.yes_bids or self.best_yes_bid is None:
            return 0
        best_price = int(self.best_yes_bid * 100)
        return sum(
            level.quantity
            for level in self.yes_bids
            if level.price >= best_price - within_cents
        )


class Market(BaseModel):
    """Kalshi market representation."""

    ticker: str
    series_ticker: str = ""
    title: str = ""
    subtitle: str = ""
    category: str = ""

    yes_subtitle: str = ""
    no_subtitle: str = ""

    open_time: datetime | None = None
    close_time: datetime | None = None
    expiration_time: datetime | None = None
    settlement_time: datetime | None = None

    status: MarketStatus = MarketStatus.OPEN

    last_price: int = Field(default=50, ge=0, le=100, description="Last YES price in cents")
    yes_bid: int = Field(default=0, ge=0, le=100)
    yes_ask: int = Field(default=100, ge=0, le=100)
    volume: int = Field(default=0, ge=0)
    volume_24h: int = Field(default=0, ge=0)
    open_interest: int = Field(default=0, ge=0)

    settlement_sources: list[SettlementSource] = Field(default_factory=list)

    result: str | None = None

    @computed_field
    @property
    def last_price_decimal(self) -> float:
        """Last price as decimal (0-1)."""
        return self.last_price / 100

    @computed_field
    @property
    def yes_bid_decimal(self) -> float:
        """YES bid as decimal."""
        return self.yes_bid / 100

    @computed_field
    @property
    def yes_ask_decimal(self) -> float:
        """YES ask as decimal."""
        return self.yes_ask / 100

    @computed_field
    @property
    def spread_decimal(self) -> float:
        """Spread as decimal."""
        return (self.yes_ask - self.yes_bid) / 100

    @computed_field
    @property
    def mid_price_decimal(self) -> float:
        """Mid price as decimal."""
        return (self.yes_bid + self.yes_ask) / 200

    @computed_field
    @property
    def days_to_expiration(self) -> float | None:
        """Days until expiration."""
        if self.expiration_time is None:
            return None
        delta = self.expiration_time - datetime.now()
        return max(0, delta.total_seconds() / 86400)

    @classmethod
    def from_api_response(cls, data: dict) -> "Market":
        """Create Market from Kalshi API response."""
        market_data = data.get("market", data)
        return cls(
            ticker=market_data.get("ticker", ""),
            series_ticker=market_data.get("series_ticker", ""),
            title=market_data.get("title", ""),
            subtitle=market_data.get("subtitle", ""),
            category=market_data.get("category", ""),
            yes_subtitle=market_data.get("yes_sub_title", ""),
            no_subtitle=market_data.get("no_sub_title", ""),
            open_time=_parse_datetime(market_data.get("open_time")),
            close_time=_parse_datetime(market_data.get("close_time")),
            expiration_time=_parse_datetime(market_data.get("expiration_time")),
            settlement_time=_parse_datetime(market_data.get("settlement_time")),
            status=MarketStatus(market_data.get("status", "open")),
            last_price=market_data.get("last_price", 50),
            yes_bid=market_data.get("yes_bid", 0),
            yes_ask=market_data.get("yes_ask", 100),
            volume=market_data.get("volume", 0),
            volume_24h=market_data.get("volume_24h", 0),
            open_interest=market_data.get("open_interest", 0),
            result=market_data.get("result"),
        )


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
