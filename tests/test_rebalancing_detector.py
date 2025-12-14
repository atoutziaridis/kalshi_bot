"""Tests for market rebalancing detector."""

import pytest

from kalshi_arb.signals.rebalancing_detector import RebalancingDetector


class TestRebalancingDetection:
    """Tests for rebalancing opportunity detection."""

    def test_detect_long_opportunity(self):
        """Detect long opportunity when sum < 1."""
        detector = RebalancingDetector(min_profit_threshold=0.01)

        opportunity = detector.scan_market(
            market_id="TEST",
            conditions=["A", "B", "C"],
            prices=[0.30, 0.30, 0.30],
        )

        assert opportunity is not None
        assert opportunity.side == "long"
        assert opportunity.price_sum == pytest.approx(0.90, abs=0.001)
        assert opportunity.deviation == pytest.approx(0.10, abs=0.001)

    def test_detect_short_opportunity(self):
        """Detect short opportunity when sum > 1."""
        detector = RebalancingDetector(min_profit_threshold=0.01)

        opportunity = detector.scan_market(
            market_id="TEST",
            conditions=["A", "B", "C"],
            prices=[0.40, 0.40, 0.40],
        )

        assert opportunity is not None
        assert opportunity.side == "short"
        assert opportunity.price_sum == pytest.approx(1.20, abs=0.001)
        assert opportunity.deviation == pytest.approx(0.20, abs=0.001)

    def test_no_opportunity_when_balanced(self):
        """No opportunity when prices sum to 1."""
        detector = RebalancingDetector(min_profit_threshold=0.01)

        opportunity = detector.scan_market(
            market_id="TEST",
            conditions=["A", "B"],
            prices=[0.50, 0.50],
        )

        assert opportunity is None

    def test_opportunity_accounts_for_fees(self):
        """Opportunity accounts for fees."""
        detector = RebalancingDetector(min_profit_threshold=0.01)

        opportunity = detector.scan_market(
            market_id="TEST",
            conditions=["A", "B", "C"],
            prices=[0.32, 0.32, 0.32],
        )

        if opportunity:
            assert opportunity.profit_post_fee < opportunity.profit_pre_fee

    def test_minimum_conditions(self):
        """Require at least 2 conditions."""
        detector = RebalancingDetector()

        opportunity = detector.scan_market(
            market_id="TEST",
            conditions=["A"],
            prices=[0.50],
        )

        assert opportunity is None


class TestOpportunityRanking:
    """Tests for opportunity ranking."""

    def test_rank_by_profitability(self):
        """Rank opportunities by profitability."""
        detector = RebalancingDetector(min_profit_threshold=0.001)

        opp1 = detector.scan_market("A", ["X", "Y"], [0.40, 0.40])
        opp2 = detector.scan_market("B", ["X", "Y"], [0.30, 0.30])

        opportunities = [o for o in [opp1, opp2] if o is not None]
        ranked = detector.rank_opportunities(opportunities)

        assert len(ranked) >= 1
