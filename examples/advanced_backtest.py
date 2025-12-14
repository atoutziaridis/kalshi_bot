"""
Advanced backtesting example with event-driven simulation and Monte Carlo validation.

Demonstrates:
1. Event-driven backtesting with order book microstructure
2. Constraint-based signal generation
3. Monte Carlo validation for robustness
4. Comprehensive performance metrics
"""

from __future__ import annotations

from datetime import datetime, timedelta
import numpy as np

from kalshi_arb.backtest.event_simulator import (
    EventDrivenBacktester,
    MarketState,
    Signal,
    Side,
)
from kalshi_arb.backtest.monte_carlo import MonteCarloValidator
from kalshi_arb.engine.constraint_engine import ConstraintEngine
from kalshi_arb.models.constraint import ConstraintType


def generate_market_states(
    num_periods: int = 200,
) -> tuple[list[MarketState], dict[str, bool]]:
    """
    Generate synthetic market data with constraint violations.

    Creates two related markets (Trump/GOP subset constraint) with
    periodic mispricings that create trading opportunities.
    """
    states = []
    base_time = datetime.now() - timedelta(days=30)

    np.random.seed(42)

    for i in range(num_periods):
        timestamp = base_time + timedelta(hours=i)

        trump_base = 0.40 + 0.05 * np.sin(i / 20)
        gop_base = 0.45 + 0.05 * np.sin(i / 20)

        if i % 10 < 3:
            trump_price = trump_base + 0.08
            gop_price = gop_base - 0.05
        else:
            trump_price = trump_base
            gop_price = gop_base + 0.03

        trump_price = np.clip(trump_price, 0.10, 0.90)
        gop_price = np.clip(gop_price, 0.10, 0.90)

        spread = 0.02

        states.append(MarketState(
            timestamp=timestamp,
            ticker="TRUMP",
            bid=trump_price - spread / 2,
            ask=trump_price + spread / 2,
            last_price=trump_price,
            volume=np.random.randint(100, 1000),
        ))

        states.append(MarketState(
            timestamp=timestamp,
            ticker="GOP",
            bid=gop_price - spread / 2,
            ask=gop_price + spread / 2,
            last_price=gop_price,
            volume=np.random.randint(100, 1000),
        ))

    states.sort(key=lambda s: (s.timestamp, s.ticker))

    resolutions = {"TRUMP": False, "GOP": True}

    return states, resolutions


def create_constraint_strategy(engine: ConstraintEngine):
    """
    Create a signal function based on constraint violations.

    Strategy:
    - Detect when p(Trump) > p(GOP) (violates subset constraint)
    - Buy YES on GOP (underpriced)
    - Size based on violation magnitude
    """

    def signal_func(state: MarketState, context: dict) -> Signal:
        positions = context.get("positions", {})
        capital = context.get("capital", 10000)

        if state.ticker in positions:
            return Signal(action="hold")

        prices = context.get("prices", {})
        prices[state.ticker] = state.mid_price
        context["prices"] = prices

        if "TRUMP" not in prices or "GOP" not in prices:
            return Signal(action="hold")

        trump_price = prices["TRUMP"]
        gop_price = prices["GOP"]

        violation = trump_price - gop_price

        if violation > 0.03:
            if state.ticker == "GOP":
                qty = int(min(capital * 0.05, 500) / state.ask)
                if qty > 0:
                    return Signal(
                        action="buy",
                        side=Side.YES,
                        quantity=qty,
                        reason=f"Constraint violation: {violation:.2%}",
                    )

            elif state.ticker == "TRUMP":
                qty = int(min(capital * 0.05, 500) / (1 - state.bid))
                if qty > 0:
                    return Signal(
                        action="buy",
                        side=Side.NO,
                        quantity=qty,
                        reason=f"Constraint violation: {violation:.2%}",
                    )

        return Signal(action="hold")

    return signal_func


def run_advanced_backtest():
    """Run the advanced backtest with all components."""
    print("=" * 60)
    print("ADVANCED KALSHI BACKTEST")
    print("Event-Driven Simulation + Monte Carlo Validation")
    print("=" * 60)

    engine = ConstraintEngine()
    engine.register_constraint(
        constraint_type=ConstraintType.SUBSET,
        lhs_tickers=["TRUMP"],
        rhs_tickers=["GOP"],
        description="Trump wins implies GOP wins",
        constraint_id="trump_gop",
    )

    print("\n1. GENERATING MARKET DATA")
    print("-" * 40)
    states, resolutions = generate_market_states(num_periods=200)
    print(f"   Generated {len(states)} market state snapshots")
    print(f"   Time range: {states[0].timestamp} to {states[-1].timestamp}")

    print("\n2. RUNNING EVENT-DRIVEN BACKTEST")
    print("-" * 40)

    backtester = EventDrivenBacktester(
        initial_capital=10000.0,
        fee_rate=0.07,
        slippage_bps=5.0,
    )

    signal_func = create_constraint_strategy(engine)
    metrics = backtester.run(states, signal_func, resolutions)

    print(backtester.print_report(metrics))

    print("\n3. MONTE CARLO VALIDATION")
    print("-" * 40)

    trade_pnls = [t.pnl for t in backtester.trades if t.pnl != 0]

    if trade_pnls:
        validator = MonteCarloValidator(num_simulations=1000, seed=42)
        mc_result = validator.validate_trades(trade_pnls, initial_capital=10000.0)

        print(validator.print_report(mc_result))

        print("\n4. SHARPE RATIO CONFIDENCE INTERVAL")
        print("-" * 40)

        if backtester.equity_curve:
            equity_values = [e[1] for e in backtester.equity_curve]
            returns = np.diff(equity_values) / equity_values[:-1]
            returns = returns[~np.isnan(returns)]

            if len(returns) > 10:
                lower, point, upper = validator.bootstrap_sharpe(list(returns))
                print(f"   Sharpe Ratio: {point:.2f}")
                print(f"   95% CI: [{lower:.2f}, {upper:.2f}]")

        print("\n5. DRAWDOWN DISTRIBUTION")
        print("-" * 40)

        dd_dist = validator.drawdown_distribution(trade_pnls)
        print(f"   50th percentile: {dd_dist['p50']:.1%}")
        print(f"   75th percentile: {dd_dist['p75']:.1%}")
        print(f"   95th percentile: {dd_dist['p95']:.1%}")
        print(f"   99th percentile: {dd_dist['p99']:.1%}")
    else:
        print("   No trades executed - cannot run Monte Carlo")

    print("\n6. TRADE LOG (First 10)")
    print("-" * 40)
    for trade in backtester.trades[:10]:
        print(f"   {trade.timestamp.strftime('%Y-%m-%d %H:%M')}: "
              f"{trade.action} {trade.quantity} {trade.ticker} "
              f"@ {trade.price:.2f} | P&L: ${trade.pnl:.2f}")

    print("\n" + "=" * 60)
    print("BACKTEST COMPLETE")
    print("=" * 60)

    return metrics, backtester.trades


if __name__ == "__main__":
    metrics, trades = run_advanced_backtest()
