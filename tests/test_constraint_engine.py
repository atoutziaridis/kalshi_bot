"""Tests for the constraint engine."""

import pytest

from kalshi_arb.engine.constraint_engine import ConstraintEngine
from kalshi_arb.models.constraint import ConstraintType


class TestConstraintRegistration:
    """Tests for constraint registration."""

    def test_register_subset_constraint(self, constraint_engine):
        """Register a subset constraint."""
        constraint = constraint_engine.register_subset(
            subset_ticker="A",
            superset_ticker="B",
        )
        assert constraint.constraint_type == ConstraintType.SUBSET
        assert constraint.lhs_tickers == ["A"]
        assert constraint.rhs_tickers == ["B"]

    def test_register_partition_constraint(self, constraint_engine):
        """Register a partition constraint."""
        constraint = constraint_engine.register_partition(
            tickers=["A", "B", "C"],
        )
        assert constraint.constraint_type == ConstraintType.PARTITION
        assert constraint.lhs_tickers == ["A", "B", "C"]

    def test_register_temporal_constraint(self, constraint_engine):
        """Register a temporal constraint."""
        constraint = constraint_engine.register_temporal(
            earlier_ticker="JAN",
            later_ticker="FEB",
        )
        assert constraint.constraint_type == ConstraintType.TEMPORAL

    def test_get_constraints_for_ticker(self, constraint_engine):
        """Get constraints involving a ticker."""
        constraint_engine.register_constraint(
            constraint_type=ConstraintType.SUBSET,
            lhs_tickers=["A"],
            rhs_tickers=["B"],
            constraint_id="c1",
        )
        constraint_engine.register_constraint(
            constraint_type=ConstraintType.SUBSET,
            lhs_tickers=["A"],
            rhs_tickers=["C"],
            constraint_id="c2",
        )

        constraints = constraint_engine.get_constraints_for_ticker("A")
        assert len(constraints) == 2

    def test_remove_constraint(self, constraint_engine):
        """Remove a constraint."""
        constraint = constraint_engine.register_subset("A", "B")
        assert constraint_engine.remove_constraint(constraint.id)
        assert constraint_engine.get_constraint(constraint.id) is None


class TestBoundCalculation:
    """Tests for probability bound calculation."""

    def test_subset_bound_calculation(self, constraint_engine):
        """Calculate bounds from subset constraint."""
        constraint_engine.register_subset("TRUMP", "GOP")

        prices = {"TRUMP": 0.42, "GOP": 0.38}

        bound_gop = constraint_engine.calculate_bounds("GOP", prices)
        assert bound_gop.lower == 0.42  # GOP >= TRUMP

        bound_trump = constraint_engine.calculate_bounds("TRUMP", prices)
        assert bound_trump.upper == 0.38  # TRUMP <= GOP

    def test_violation_detection(self, constraint_engine):
        """Detect constraint violations."""
        constraint_engine.register_subset("TRUMP", "GOP")

        prices = {"TRUMP": 0.42, "GOP": 0.38}

        violations = constraint_engine.detect_violations(prices)
        assert len(violations) > 0

        total_violation = sum(v.violation_magnitude for v in violations)
        assert total_violation > 0

    def test_no_violation_when_valid(self, constraint_engine):
        """No violations when prices are valid."""
        constraint_engine.register_subset("TRUMP", "GOP")

        prices = {"TRUMP": 0.35, "GOP": 0.45}

        violations = constraint_engine.detect_violations(prices, min_magnitude=0.01)
        assert len(violations) == 0


class TestPartitionConstraint:
    """Tests for partition constraints."""

    def test_partition_bound_calculation(self, constraint_engine):
        """Calculate bounds from partition constraint."""
        constraint_engine.register_partition(["A", "B", "C"])

        prices = {"A": 0.40, "B": 0.40, "C": 0.40}

        bound_a = constraint_engine.calculate_bounds("A", prices)
        assert bound_a.upper <= 0.20
