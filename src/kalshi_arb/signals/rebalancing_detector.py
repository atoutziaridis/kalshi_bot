"""Market rebalancing arbitrage detector."""
from __future__ import annotations


from datetime import datetime

from kalshi_arb.models.market import Market, OrderBook
from kalshi_arb.models.signal import RebalancingOpportunity
from kalshi_arb.utils.fees import calculate_fee, calculate_total_fees


class RebalancingDetector:
    """
    Detect intra-market arbitrage opportunities.

    Arbitrage exists when sum of YES prices deviates from 1.0:
    - sum < 1: Long arbitrage (buy all YES contracts)
    - sum > 1: Short arbitrage (buy all NO contracts)
    """

    def __init__(self, min_profit_threshold: float = 0.01):
        self.min_profit_threshold = min_profit_threshold

    def scan_market(
        self,
        market_id: str,
        conditions: list[str],
        prices: list[float],
        quantities: list[int] | None = None,
    ) -> RebalancingOpportunity | None:
        """
        Scan a multi-condition market for rebalancing opportunities.

        Args:
            market_id: Market identifier
            conditions: List of condition tickers
            prices: YES prices for each condition (as decimals 0-1)
            quantities: Available quantities at each price level

        Returns:
            RebalancingOpportunity if profitable, None otherwise
        """
        if len(conditions) < 2 or len(conditions) != len(prices):
            return None

        price_sum = sum(prices)
        deviation = abs(price_sum - 1.0)

        if deviation < 0.001:
            return None

        total_fees = calculate_total_fees(prices)

        if price_sum < 1.0:
            profit_pre_fee = 1.0 - price_sum
            profit_post_fee = profit_pre_fee - total_fees
            side = "long"
        else:
            profit_pre_fee = price_sum - 1.0
            profit_post_fee = profit_pre_fee - total_fees
            side = "short"

        min_liquidity = min(quantities) if quantities else 0

        opportunity = RebalancingOpportunity(
            market_id=market_id,
            side=side,
            conditions=conditions,
            prices=prices,
            price_sum=price_sum,
            deviation=deviation,
            profit_pre_fee=profit_pre_fee,
            total_fees=total_fees,
            profit_post_fee=profit_post_fee,
            min_liquidity=min_liquidity,
            created_at=datetime.now(),
        )

        if opportunity.is_profitable and profit_post_fee >= self.min_profit_threshold:
            return opportunity

        return None

    def scan_series(
        self,
        series_ticker: str,
        markets: list[Market],
    ) -> RebalancingOpportunity | None:
        """
        Scan a series of markets for partition constraint violations.

        Args:
            series_ticker: Series identifier
            markets: List of markets in the series

        Returns:
            RebalancingOpportunity if found
        """
        if len(markets) < 2:
            return None

        conditions = [m.ticker for m in markets]
        prices = [m.mid_price_decimal for m in markets]

        return self.scan_market(
            market_id=series_ticker,
            conditions=conditions,
            prices=prices,
        )

    def scan_orderbook_market(
        self,
        market_id: str,
        orderbooks: dict[str, OrderBook],
    ) -> tuple[RebalancingOpportunity | None, RebalancingOpportunity | None]:
        """
        Scan using order book data for more accurate detection.

        Returns both long (using asks) and short (using bids) opportunities.

        Args:
            market_id: Market identifier
            orderbooks: Order books keyed by condition ticker

        Returns:
            Tuple of (long_opportunity, short_opportunity)
        """
        if len(orderbooks) < 2:
            return None, None

        conditions = list(orderbooks.keys())

        ask_prices = []
        bid_prices = []
        ask_quantities = []
        bid_quantities = []

        for ticker in conditions:
            ob = orderbooks[ticker]
            if ob.best_yes_ask is not None:
                ask_prices.append(ob.best_yes_ask)
                ask_quantities.append(ob.total_depth(within_cents=1))
            else:
                ask_prices.append(1.0)
                ask_quantities.append(0)

            if ob.best_yes_bid is not None:
                bid_prices.append(ob.best_yes_bid)
                bid_quantities.append(ob.total_depth(within_cents=1))
            else:
                bid_prices.append(0.0)
                bid_quantities.append(0)

        long_opp = None
        if sum(ask_prices) < 1.0:
            long_opp = self.scan_market(
                market_id=f"{market_id}_long",
                conditions=conditions,
                prices=ask_prices,
                quantities=ask_quantities,
            )

        short_opp = None
        if sum(bid_prices) > 1.0:
            short_opp = self.scan_market(
                market_id=f"{market_id}_short",
                conditions=conditions,
                prices=bid_prices,
                quantities=bid_quantities,
            )

        return long_opp, short_opp

    def estimate_execution_profit(
        self,
        opportunity: RebalancingOpportunity,
        slippage_per_leg: float = 0.005,
    ) -> float:
        """
        Estimate realistic profit accounting for execution slippage.

        Args:
            opportunity: Detected opportunity
            slippage_per_leg: Expected slippage per condition

        Returns:
            Estimated profit after slippage
        """
        total_slippage = slippage_per_leg * len(opportunity.conditions)
        return opportunity.profit_post_fee - total_slippage

    def rank_opportunities(
        self,
        opportunities: list[RebalancingOpportunity],
    ) -> list[RebalancingOpportunity]:
        """
        Rank opportunities by profitability and liquidity.

        Score = profit_post_fee * min(1, min_liquidity / 1000)
        """
        def score(opp: RebalancingOpportunity) -> float:
            liquidity_factor = min(1.0, opp.min_liquidity / 1000)
            return opp.profit_post_fee * liquidity_factor

        return sorted(opportunities, key=score, reverse=True)
