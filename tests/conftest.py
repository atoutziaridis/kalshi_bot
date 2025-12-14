"""Pytest fixtures for kalshi_arb tests."""

import pytest

from kalshi_arb.engine.constraint_engine import ConstraintEngine
from kalshi_arb.models.constraint import ConstraintType
from kalshi_arb.models.market import Market, MarketStatus
from kalshi_arb.risk.position_sizer import PositionSizer, SizingConfig


@pytest.fixture
def constraint_engine():
    """Create a fresh constraint engine."""
    return ConstraintEngine()


@pytest.fixture
def position_sizer():
    """Create a position sizer with default config."""
    return PositionSizer(SizingConfig())


@pytest.fixture
def sample_market():
    """Create a sample market."""
    return Market(
        ticker="TEST-24JAN01-T50",
        series_ticker="TEST",
        title="Test Market",
        category="Test",
        status=MarketStatus.OPEN,
        last_price=50,
        yes_bid=49,
        yes_ask=51,
        volume=1000,
        open_interest=500,
    )


@pytest.fixture
def sample_markets():
    """Create a list of sample markets for testing."""
    return [
        Market(
            ticker="TRUMP-24NOV05-T50",
            series_ticker="TRUMP",
            title="Trump wins presidency",
            category="Politics",
            last_price=42,
            yes_bid=41,
            yes_ask=43,
        ),
        Market(
            ticker="GOP-24NOV05-T50",
            series_ticker="GOP",
            title="GOP wins presidency",
            category="Politics",
            last_price=38,
            yes_bid=37,
            yes_ask=39,
        ),
    ]


@pytest.fixture
def subset_constraint(constraint_engine):
    """Register a subset constraint: Trump ⊂ GOP."""
    return constraint_engine.register_subset(
        subset_ticker="TRUMP-24NOV05-T50",
        superset_ticker="GOP-24NOV05-T50",
        description="Trump wins implies GOP wins",
    )


@pytest.fixture
def partition_markets():
    """Create markets that should sum to 1."""
    return [
        Market(ticker="TEAM-A", title="Team A wins", last_price=33),
        Market(ticker="TEAM-B", title="Team B wins", last_price=33),
        Market(ticker="TEAM-C", title="Team C wins", last_price=33),
    ]
