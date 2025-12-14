"""Constraint and probability bound models."""
from __future__ import annotations


from enum import Enum

from pydantic import BaseModel, Field


class ConstraintType(str, Enum):
    """Types of logical constraints between markets."""

    SUBSET = "subset"
    PARTITION = "partition"
    TEMPORAL = "temporal"


class Constraint(BaseModel):
    """
    Logical constraint between markets.

    Subset: A ⊂ B means p(A) ≤ p(B)
    Partition: Σ p_i = 1 for mutually exclusive outcomes
    Temporal: Earlier expiration ⊂ later expiration
    """

    id: str = ""
    constraint_type: ConstraintType
    lhs_tickers: list[str] = Field(description="Left-hand side tickers")
    rhs_tickers: list[str] = Field(description="Right-hand side tickers")
    description: str = ""

    @property
    def is_subset(self) -> bool:
        """Check if this is a subset constraint."""
        return self.constraint_type == ConstraintType.SUBSET

    @property
    def is_partition(self) -> bool:
        """Check if this is a partition constraint."""
        return self.constraint_type == ConstraintType.PARTITION

    @property
    def is_temporal(self) -> bool:
        """Check if this is a temporal constraint."""
        return self.constraint_type == ConstraintType.TEMPORAL

    @property
    def all_tickers(self) -> list[str]:
        """Get all tickers involved in this constraint."""
        return list(set(self.lhs_tickers + self.rhs_tickers))


class ProbabilityBound(BaseModel):
    """
    Probability bounds derived from constraints.

    These are hard bounds that the market must respect at resolution.
    """

    ticker: str
    lower: float = Field(default=0.0, ge=0.0, le=1.0)
    upper: float = Field(default=1.0, ge=0.0, le=1.0)
    source_constraint_id: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @property
    def range(self) -> float:
        """Width of the probability range."""
        return self.upper - self.lower

    @property
    def midpoint(self) -> float:
        """Midpoint of the probability range."""
        return (self.lower + self.upper) / 2

    def contains(self, price: float) -> bool:
        """Check if price is within bounds."""
        return self.lower <= price <= self.upper

    def violation(self, price: float) -> float:
        """
        Calculate how much price violates bounds.

        Returns:
            Positive value if price is below lower bound
            Negative value if price is above upper bound
            Zero if price is within bounds
        """
        if price < self.lower:
            return self.lower - price
        if price > self.upper:
            return price - self.upper
        return 0.0

    def merge(self, other: "ProbabilityBound") -> "ProbabilityBound":
        """Merge with another bound (intersection)."""
        if self.ticker != other.ticker:
            raise ValueError("Cannot merge bounds for different tickers")
        return ProbabilityBound(
            ticker=self.ticker,
            lower=max(self.lower, other.lower),
            upper=min(self.upper, other.upper),
            source_constraint_id=f"{self.source_constraint_id}+{other.source_constraint_id}",
            confidence=min(self.confidence, other.confidence),
        )


class ConstraintViolation(BaseModel):
    """Detected violation of a constraint."""

    constraint: Constraint
    violation_magnitude: float = Field(ge=0.0)
    affected_tickers: list[str] = Field(default_factory=list)
    current_prices: dict[str, float] = Field(default_factory=dict)
    expected_bounds: dict[str, ProbabilityBound] = Field(default_factory=dict)
    timestamp: float = 0.0
