"""Combinatorial arbitrage detector for inter-market dependencies."""
from __future__ import annotations


import logging
from collections import defaultdict
from datetime import datetime

from pydantic import BaseModel, Field

from kalshi_arb.models.market import Market
from kalshi_arb.models.signal import DirectionalSignal, SignalDirection, SignalType
from kalshi_arb.utils.fees import calculate_total_fees

logger = logging.getLogger(__name__)


class MarketPair(BaseModel):
    """Candidate pair of markets for dependency analysis."""

    market_a: str
    market_b: str
    similarity_score: float = 0.0
    same_category: bool = False
    date_proximity_days: float = 0.0


class CombinatorialOpportunity(BaseModel):
    """Inter-market arbitrage opportunity."""

    market_a: str
    market_b: str
    dependency_type: str
    price_a: float
    price_b: float
    price_gap: float
    profit_pre_fee: float
    profit_post_fee: float
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=datetime.now)

    @property
    def is_profitable(self) -> bool:
        return self.profit_post_fee > 0.02


class CombinatorialDetector:
    """
    Detect inter-market arbitrage from logical dependencies.

    Dependencies exist when resolution of one market constrains another:
    - Calendar: Earlier expiration ⊂ later expiration
    - Overlapping: "Trump wins" ⊂ "GOP wins"
    - Range partition: Overlapping price/value ranges
    """

    def __init__(
        self,
        min_profit_threshold: float = 0.02,
        max_date_proximity_days: float = 1.0,
    ):
        self.min_profit_threshold = min_profit_threshold
        self.max_date_proximity_days = max_date_proximity_days
        self._known_dependencies: dict[str, list[str]] = {}

    def register_dependency(
        self,
        subset_ticker: str,
        superset_ticker: str,
    ) -> None:
        """Manually register a known dependency."""
        if subset_ticker not in self._known_dependencies:
            self._known_dependencies[subset_ticker] = []
        self._known_dependencies[subset_ticker].append(superset_ticker)

    def find_candidate_pairs(
        self,
        markets: list[Market],
    ) -> list[MarketPair]:
        """
        Find candidate market pairs for dependency analysis.

        Filters by:
        1. Same category
        2. Similar expiration dates
        3. Title similarity (basic keyword matching)
        """
        pairs = []

        by_category: dict[str, list[Market]] = defaultdict(list)
        for market in markets:
            by_category[market.category].append(market)

        for category, category_markets in by_category.items():
            if len(category_markets) < 2:
                continue

            for i, m1 in enumerate(category_markets):
                for m2 in category_markets[i + 1:]:
                    if m1.expiration_time and m2.expiration_time:
                        delta = abs(
                            (m1.expiration_time - m2.expiration_time).total_seconds()
                        )
                        days = delta / 86400

                        if days > self.max_date_proximity_days:
                            continue
                    else:
                        days = 0.0

                    similarity = self._calculate_title_similarity(
                        m1.title, m2.title
                    )

                    if similarity > 0.3:
                        pairs.append(MarketPair(
                            market_a=m1.ticker,
                            market_b=m2.ticker,
                            similarity_score=similarity,
                            same_category=True,
                            date_proximity_days=days,
                        ))

        return pairs

    def _calculate_title_similarity(self, title1: str, title2: str) -> float:
        """Calculate simple keyword overlap similarity."""
        words1 = set(title1.lower().split())
        words2 = set(title2.lower().split())

        stop_words = {"will", "the", "a", "an", "be", "by", "on", "in", "to", "?"}
        words1 -= stop_words
        words2 -= stop_words

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    def check_calendar_dependency(
        self,
        earlier: Market,
        later: Market,
    ) -> CombinatorialOpportunity | None:
        """
        Check for calendar arbitrage.

        If earlier event resolves YES, later must also resolve YES.
        Therefore: p(earlier) <= p(later)

        Arbitrage exists if p(earlier) > p(later).
        """
        if not earlier.expiration_time or not later.expiration_time:
            return None

        if earlier.expiration_time >= later.expiration_time:
            return None

        price_earlier = earlier.mid_price_decimal
        price_later = later.mid_price_decimal

        if price_earlier <= price_later:
            return None

        price_gap = price_earlier - price_later
        fees = calculate_total_fees([price_earlier, price_later])
        profit = price_gap - fees

        if profit < self.min_profit_threshold:
            return None

        return CombinatorialOpportunity(
            market_a=earlier.ticker,
            market_b=later.ticker,
            dependency_type="calendar",
            price_a=price_earlier,
            price_b=price_later,
            price_gap=price_gap,
            profit_pre_fee=price_gap,
            profit_post_fee=profit,
        )

    def check_subset_dependency(
        self,
        subset_ticker: str,
        superset_ticker: str,
        prices: dict[str, float],
    ) -> CombinatorialOpportunity | None:
        """
        Check for subset arbitrage.

        If subset resolves YES, superset must also resolve YES.
        Therefore: p(subset) <= p(superset)

        Arbitrage exists if p(subset) > p(superset).
        """
        if subset_ticker not in prices or superset_ticker not in prices:
            return None

        price_subset = prices[subset_ticker]
        price_superset = prices[superset_ticker]

        if price_subset <= price_superset:
            return None

        price_gap = price_subset - price_superset
        fees = calculate_total_fees([price_subset, price_superset])
        profit = price_gap - fees

        if profit < self.min_profit_threshold:
            return None

        return CombinatorialOpportunity(
            market_a=subset_ticker,
            market_b=superset_ticker,
            dependency_type="subset",
            price_a=price_subset,
            price_b=price_superset,
            price_gap=price_gap,
            profit_pre_fee=price_gap,
            profit_post_fee=profit,
        )

    def scan_known_dependencies(
        self,
        prices: dict[str, float],
    ) -> list[CombinatorialOpportunity]:
        """Scan all registered dependencies for opportunities."""
        opportunities = []

        for subset, supersets in self._known_dependencies.items():
            for superset in supersets:
                opp = self.check_subset_dependency(subset, superset, prices)
                if opp:
                    opportunities.append(opp)

        return opportunities

    def scan_calendar_opportunities(
        self,
        markets: list[Market],
    ) -> list[CombinatorialOpportunity]:
        """Scan for calendar arbitrage opportunities."""
        opportunities = []

        by_series: dict[str, list[Market]] = defaultdict(list)
        for market in markets:
            if market.series_ticker:
                by_series[market.series_ticker].append(market)

        for series, series_markets in by_series.items():
            if len(series_markets) < 2:
                continue

            sorted_markets = sorted(
                series_markets,
                key=lambda m: m.expiration_time or datetime.max,
            )

            for i, earlier in enumerate(sorted_markets):
                for later in sorted_markets[i + 1:]:
                    opp = self.check_calendar_dependency(earlier, later)
                    if opp:
                        opportunities.append(opp)

        return opportunities

    def generate_signals(
        self,
        opportunity: CombinatorialOpportunity,
    ) -> list[DirectionalSignal]:
        """
        Generate trading signals from combinatorial opportunity.

        Strategy:
        - Buy YES on underpriced market (superset/later)
        - Buy NO on overpriced market (subset/earlier)
        """
        signals = []

        signals.append(DirectionalSignal(
            ticker=opportunity.market_b,
            direction=SignalDirection.BUY_YES,
            signal_type=SignalType.COMBINATORIAL,
            current_price=opportunity.price_b,
            bound_price=opportunity.price_a,
            raw_edge=opportunity.price_gap,
            estimated_fee=0.02,
            estimated_spread=0.01,
            net_edge=opportunity.profit_post_fee / 2,
            confidence=opportunity.confidence,
            source_constraint_id=f"comb_{opportunity.market_a}_{opportunity.market_b}",
        ))

        signals.append(DirectionalSignal(
            ticker=opportunity.market_a,
            direction=SignalDirection.BUY_NO,
            signal_type=SignalType.COMBINATORIAL,
            current_price=opportunity.price_a,
            bound_price=opportunity.price_b,
            raw_edge=opportunity.price_gap,
            estimated_fee=0.02,
            estimated_spread=0.01,
            net_edge=opportunity.profit_post_fee / 2,
            confidence=opportunity.confidence,
            source_constraint_id=f"comb_{opportunity.market_a}_{opportunity.market_b}",
        ))

        return signals

    def scan_all(
        self,
        markets: list[Market],
        prices: dict[str, float],
    ) -> list[CombinatorialOpportunity]:
        """Run all scans and return opportunities."""
        opportunities = []

        opportunities.extend(self.scan_known_dependencies(prices))

        opportunities.extend(self.scan_calendar_opportunities(markets))

        return sorted(
            opportunities,
            key=lambda o: o.profit_post_fee,
            reverse=True,
        )
