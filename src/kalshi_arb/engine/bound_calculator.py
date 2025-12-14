"""Probability bound calculator from constraints."""
from __future__ import annotations


from kalshi_arb.models.constraint import (
    Constraint,
    ConstraintType,
    ConstraintViolation,
    ProbabilityBound,
)


class BoundCalculator:
    """
    Calculate probability bounds from logical constraints.

    Bounds are absolute - the market must respect them at resolution.
    """

    def calculate_subset_bounds(
        self,
        constraint: Constraint,
        prices: dict[str, float],
    ) -> list[ProbabilityBound]:
        """
        Calculate bounds from subset constraint.

        If A ⊂ B (lhs ⊂ rhs), then:
        - p(B) >= p(A) → bound(B).lower = p(A)
        - p(A) <= p(B) → bound(A).upper = p(B)
        """
        bounds = []

        if len(constraint.lhs_tickers) != 1 or len(constraint.rhs_tickers) != 1:
            return bounds

        subset_ticker = constraint.lhs_tickers[0]
        superset_ticker = constraint.rhs_tickers[0]

        subset_price = prices.get(subset_ticker)
        superset_price = prices.get(superset_ticker)

        if subset_price is not None:
            bounds.append(
                ProbabilityBound(
                    ticker=superset_ticker,
                    lower=subset_price,
                    upper=1.0,
                    source_constraint_id=constraint.id,
                )
            )

        if superset_price is not None:
            bounds.append(
                ProbabilityBound(
                    ticker=subset_ticker,
                    lower=0.0,
                    upper=superset_price,
                    source_constraint_id=constraint.id,
                )
            )

        return bounds

    def calculate_partition_bounds(
        self,
        constraint: Constraint,
        prices: dict[str, float],
    ) -> list[ProbabilityBound]:
        """
        Calculate bounds from partition constraint.

        For mutually exclusive outcomes: Σ p_i = 1
        Each p_i <= 1 - Σ(j≠i) p_j
        """
        bounds = []
        tickers = constraint.lhs_tickers

        available_prices = {t: prices[t] for t in tickers if t in prices}
        if len(available_prices) < 2:
            return bounds

        total = sum(available_prices.values())

        for ticker in tickers:
            if ticker not in available_prices:
                continue

            other_sum = total - available_prices[ticker]
            implied_upper = max(0.0, min(1.0, 1.0 - other_sum))

            bounds.append(
                ProbabilityBound(
                    ticker=ticker,
                    lower=0.0,
                    upper=implied_upper,
                    source_constraint_id=constraint.id,
                )
            )

        return bounds

    def calculate_temporal_bounds(
        self,
        constraint: Constraint,
        prices: dict[str, float],
    ) -> list[ProbabilityBound]:
        """
        Calculate bounds from temporal constraint.

        Earlier expiration is subset of later: p(T1) <= p(T2)
        Same logic as subset constraint.
        """
        return self.calculate_subset_bounds(constraint, prices)

    def calculate_bounds(
        self,
        constraint: Constraint,
        prices: dict[str, float],
    ) -> list[ProbabilityBound]:
        """Calculate bounds based on constraint type."""
        if constraint.constraint_type == ConstraintType.SUBSET:
            return self.calculate_subset_bounds(constraint, prices)
        elif constraint.constraint_type == ConstraintType.PARTITION:
            return self.calculate_partition_bounds(constraint, prices)
        elif constraint.constraint_type == ConstraintType.TEMPORAL:
            return self.calculate_temporal_bounds(constraint, prices)
        return []

    def merge_bounds(
        self,
        bounds: list[ProbabilityBound],
    ) -> dict[str, ProbabilityBound]:
        """
        Merge multiple bounds for same ticker (intersection).

        Returns tightest bounds for each ticker.
        """
        merged: dict[str, ProbabilityBound] = {}

        for bound in bounds:
            if bound.ticker in merged:
                merged[bound.ticker] = merged[bound.ticker].merge(bound)
            else:
                merged[bound.ticker] = bound

        return merged

    def detect_violation(
        self,
        bound: ProbabilityBound,
        current_price: float,
    ) -> float:
        """
        Detect if current price violates bound.

        Returns:
            Violation magnitude (positive if violated, 0 if within bounds)
        """
        return bound.violation(current_price)

    def detect_violations(
        self,
        bounds: dict[str, ProbabilityBound],
        prices: dict[str, float],
    ) -> list[ConstraintViolation]:
        """
        Detect all violations across bounds.

        Returns list of violations with magnitude > 0.
        """
        import time

        violations = []

        for ticker, bound in bounds.items():
            if ticker not in prices:
                continue

            current_price = prices[ticker]
            magnitude = self.detect_violation(bound, current_price)

            if magnitude > 0:
                violations.append(
                    ConstraintViolation(
                        constraint=Constraint(
                            id=bound.source_constraint_id,
                            constraint_type=ConstraintType.SUBSET,
                            lhs_tickers=[ticker],
                            rhs_tickers=[],
                        ),
                        violation_magnitude=magnitude,
                        affected_tickers=[ticker],
                        current_prices={ticker: current_price},
                        expected_bounds={ticker: bound},
                        timestamp=time.time(),
                    )
                )

        return violations
