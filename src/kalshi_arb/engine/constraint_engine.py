"""Constraint engine for managing and evaluating logical constraints."""
from __future__ import annotations


import json
import time
from pathlib import Path

from kalshi_arb.engine.bound_calculator import BoundCalculator
from kalshi_arb.models.constraint import (
    Constraint,
    ConstraintType,
    ConstraintViolation,
    ProbabilityBound,
)
from kalshi_arb.models.market import Market


class ConstraintEngine:
    """
    Engine for managing logical constraints between markets.

    Supports three constraint types:
    1. Subset: A ⊂ B means p(A) <= p(B)
    2. Partition: Mutually exclusive outcomes sum to 1
    3. Temporal: Earlier expiration is subset of later
    """

    def __init__(self, storage_path: Path | None = None):
        self._constraints: dict[str, Constraint] = {}
        self._ticker_index: dict[str, set[str]] = {}
        self._calculator = BoundCalculator()
        self._storage_path = storage_path

        if storage_path and storage_path.exists():
            self._load_constraints()

    def register_constraint(
        self,
        constraint_type: ConstraintType,
        lhs_tickers: list[str],
        rhs_tickers: list[str],
        description: str = "",
        constraint_id: str | None = None,
    ) -> Constraint:
        """
        Register a new constraint.

        Args:
            constraint_type: Type of constraint
            lhs_tickers: Left-hand side tickers
            rhs_tickers: Right-hand side tickers
            description: Human-readable description
            constraint_id: Optional ID (auto-generated if not provided)

        Returns:
            Registered constraint
        """
        if constraint_id is None:
            constraint_id = f"{constraint_type.value}_{int(time.time() * 1000)}"

        constraint = Constraint(
            id=constraint_id,
            constraint_type=constraint_type,
            lhs_tickers=lhs_tickers,
            rhs_tickers=rhs_tickers,
            description=description,
        )

        self._constraints[constraint_id] = constraint

        for ticker in constraint.all_tickers:
            if ticker not in self._ticker_index:
                self._ticker_index[ticker] = set()
            self._ticker_index[ticker].add(constraint_id)

        self._save_constraints()
        return constraint

    def register_subset(
        self,
        subset_ticker: str,
        superset_ticker: str,
        description: str = "",
    ) -> Constraint:
        """
        Register a subset constraint: subset ⊂ superset.

        Example: "Trump wins" ⊂ "GOP wins"
        """
        return self.register_constraint(
            constraint_type=ConstraintType.SUBSET,
            lhs_tickers=[subset_ticker],
            rhs_tickers=[superset_ticker],
            description=description or f"{subset_ticker} ⊂ {superset_ticker}",
        )

    def register_partition(
        self,
        tickers: list[str],
        description: str = "",
    ) -> Constraint:
        """
        Register a partition constraint: outcomes are mutually exclusive.

        Example: ["Team A wins", "Team B wins", "Draw"]
        """
        return self.register_constraint(
            constraint_type=ConstraintType.PARTITION,
            lhs_tickers=tickers,
            rhs_tickers=[],
            description=description or f"Partition: {', '.join(tickers)}",
        )

    def register_temporal(
        self,
        earlier_ticker: str,
        later_ticker: str,
        description: str = "",
    ) -> Constraint:
        """
        Register a temporal constraint: earlier expiration ⊂ later.

        Example: "BTC > 250k by Jan 15" ⊂ "BTC > 250k by Feb 1"
        """
        return self.register_constraint(
            constraint_type=ConstraintType.TEMPORAL,
            lhs_tickers=[earlier_ticker],
            rhs_tickers=[later_ticker],
            description=description or f"{earlier_ticker} (earlier) ⊂ {later_ticker} (later)",
        )

    def get_constraint(self, constraint_id: str) -> Constraint | None:
        """Get constraint by ID."""
        return self._constraints.get(constraint_id)

    def get_constraints_for_ticker(self, ticker: str) -> list[Constraint]:
        """Get all constraints involving a ticker."""
        constraint_ids = self._ticker_index.get(ticker, set())
        return [self._constraints[cid] for cid in constraint_ids if cid in self._constraints]

    def get_all_constraints(self) -> list[Constraint]:
        """Get all registered constraints."""
        return list(self._constraints.values())

    def remove_constraint(self, constraint_id: str) -> bool:
        """Remove a constraint."""
        if constraint_id not in self._constraints:
            return False

        constraint = self._constraints.pop(constraint_id)

        for ticker in constraint.all_tickers:
            if ticker in self._ticker_index:
                self._ticker_index[ticker].discard(constraint_id)

        self._save_constraints()
        return True

    def calculate_bounds(
        self,
        ticker: str,
        prices: dict[str, float],
    ) -> ProbabilityBound:
        """
        Calculate probability bounds for a ticker from all constraints.

        Args:
            ticker: Market ticker
            prices: Current prices for all relevant markets

        Returns:
            Merged probability bound (tightest constraints)
        """
        constraints = self.get_constraints_for_ticker(ticker)
        all_bounds: list[ProbabilityBound] = []

        for constraint in constraints:
            bounds = self._calculator.calculate_bounds(constraint, prices)
            ticker_bounds = [b for b in bounds if b.ticker == ticker]
            all_bounds.extend(ticker_bounds)

        if not all_bounds:
            return ProbabilityBound(ticker=ticker, lower=0.0, upper=1.0)

        merged = all_bounds[0]
        for bound in all_bounds[1:]:
            merged = merged.merge(bound)

        return merged

    def calculate_all_bounds(
        self,
        prices: dict[str, float],
    ) -> dict[str, ProbabilityBound]:
        """Calculate bounds for all tickers with constraints."""
        all_bounds: list[ProbabilityBound] = []

        for constraint in self._constraints.values():
            bounds = self._calculator.calculate_bounds(constraint, prices)
            all_bounds.extend(bounds)

        return self._calculator.merge_bounds(all_bounds)

    def detect_violations(
        self,
        prices: dict[str, float],
        min_magnitude: float = 0.0,
    ) -> list[ConstraintViolation]:
        """
        Detect all constraint violations.

        Args:
            prices: Current market prices
            min_magnitude: Minimum violation magnitude to report

        Returns:
            List of violations sorted by magnitude
        """
        bounds = self.calculate_all_bounds(prices)
        violations = self._calculator.detect_violations(bounds, prices)

        if min_magnitude > 0:
            violations = [v for v in violations if v.violation_magnitude >= min_magnitude]

        return sorted(violations, key=lambda v: v.violation_magnitude, reverse=True)

    def auto_detect_temporal_constraints(
        self,
        markets: list[Market],
    ) -> list[Constraint]:
        """
        Auto-detect temporal constraints from market expiration dates.

        Groups markets by series and creates temporal constraints
        for markets with different expiration dates.
        """
        from collections import defaultdict

        series_markets: dict[str, list[Market]] = defaultdict(list)

        for market in markets:
            if market.series_ticker and market.expiration_time:
                series_markets[market.series_ticker].append(market)

        new_constraints = []

        for series, series_mkts in series_markets.items():
            sorted_markets = sorted(
                series_mkts,
                key=lambda m: m.expiration_time or 0,
            )

            for i in range(len(sorted_markets) - 1):
                earlier = sorted_markets[i]
                later = sorted_markets[i + 1]

                if earlier.expiration_time == later.expiration_time:
                    continue

                constraint = self.register_temporal(
                    earlier_ticker=earlier.ticker,
                    later_ticker=later.ticker,
                    description=f"Temporal: {earlier.ticker} expires before {later.ticker}",
                )
                new_constraints.append(constraint)

        return new_constraints

    def _save_constraints(self) -> None:
        """Save constraints to storage."""
        if not self._storage_path:
            return

        data = {
            cid: {
                "id": c.id,
                "constraint_type": c.constraint_type.value,
                "lhs_tickers": c.lhs_tickers,
                "rhs_tickers": c.rhs_tickers,
                "description": c.description,
            }
            for cid, c in self._constraints.items()
        }

        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._storage_path.write_text(json.dumps(data, indent=2))

    def _load_constraints(self) -> None:
        """Load constraints from storage."""
        if not self._storage_path or not self._storage_path.exists():
            return

        try:
            data = json.loads(self._storage_path.read_text())
            for cid, cdata in data.items():
                constraint = Constraint(
                    id=cdata["id"],
                    constraint_type=ConstraintType(cdata["constraint_type"]),
                    lhs_tickers=cdata["lhs_tickers"],
                    rhs_tickers=cdata["rhs_tickers"],
                    description=cdata.get("description", ""),
                )
                self._constraints[cid] = constraint

                for ticker in constraint.all_tickers:
                    if ticker not in self._ticker_index:
                        self._ticker_index[ticker] = set()
                    self._ticker_index[ticker].add(cid)
        except (json.JSONDecodeError, KeyError):
            pass
