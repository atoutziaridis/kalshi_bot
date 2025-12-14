"""Example backtest demonstrating the constraint-based trading strategy."""

from __future__ import annotations

import pandas as pd
from datetime import datetime, timedelta

from kalshi_arb.backtest.backtester import Backtester, BacktestConfig
from kalshi_arb.engine.constraint_engine import ConstraintEngine
from kalshi_arb.models.constraint import ConstraintType


def generate_sample_data() -> tuple[pd.DataFrame, dict[str, bool]]:
    """
    Generate synthetic market data with constraint violations.
    
    Simulates the Trump/GOP subset constraint violation scenario:
    - Trump wins (subset) priced at 0.42
    - GOP wins (superset) priced at 0.38
    - This violates p(Trump) <= p(GOP)
    """
    timestamps = pd.date_range(
        start=datetime.now() - timedelta(days=30),
        periods=100,
        freq="6h",
    )
    
    data = []
    
    for i, ts in enumerate(timestamps):
        trump_base = 0.40 + 0.02 * (i % 10 - 5) / 5
        gop_base = 0.38 + 0.02 * (i % 10 - 5) / 5
        
        if i % 5 == 0:
            trump_price = trump_base + 0.05
            gop_price = gop_base - 0.02
        else:
            trump_price = trump_base
            gop_price = gop_base + 0.05
        
        trump_price = max(0.10, min(0.90, trump_price))
        gop_price = max(0.10, min(0.90, gop_price))
        
        data.append({"timestamp": ts, "ticker": "TRUMP", "price": trump_price})
        data.append({"timestamp": ts, "ticker": "GOP", "price": gop_price})
        
        btc_jan = 0.30 + 0.01 * (i % 20 - 10) / 10
        btc_feb = 0.35 + 0.01 * (i % 20 - 10) / 10
        
        if i % 7 == 0:
            btc_jan = btc_feb + 0.03
        
        data.append({"timestamp": ts, "ticker": "BTC-JAN", "price": btc_jan})
        data.append({"timestamp": ts, "ticker": "BTC-FEB", "price": btc_feb})
    
    df = pd.DataFrame(data)
    
    resolutions = {
        "TRUMP": False,
        "GOP": True,
        "BTC-JAN": False,
        "BTC-FEB": True,
    }
    
    return df, resolutions


def run_backtest():
    """Run the backtest with constraint-based signals."""
    print("=" * 60)
    print("KALSHI ARBITRAGE BACKTEST")
    print("=" * 60)
    
    config = BacktestConfig(
        initial_capital=10000.0,
        min_edge_threshold=0.01,
        kelly_fraction=0.25,
        max_position_pct=0.05,
    )
    
    backtester = Backtester(config)
    
    backtester.constraint_engine.register_constraint(
        constraint_type=ConstraintType.SUBSET,
        lhs_tickers=["TRUMP"],
        rhs_tickers=["GOP"],
        description="Trump wins implies GOP wins",
        constraint_id="trump_gop",
    )
    
    backtester.constraint_engine.register_constraint(
        constraint_type=ConstraintType.TEMPORAL,
        lhs_tickers=["BTC-JAN"],
        rhs_tickers=["BTC-FEB"],
        description="BTC Jan expiry is subset of Feb expiry",
        constraint_id="btc_calendar",
    )
    
    print("\nRegistered Constraints:")
    for c in backtester.constraint_engine.get_all_constraints():
        print(f"  - {c.description}")
    
    print("\nGenerating synthetic market data...")
    price_data, resolutions = generate_sample_data()
    
    print(f"  - {len(price_data)} price observations")
    print(f"  - {len(price_data['timestamp'].unique())} time periods")
    print(f"  - {len(price_data['ticker'].unique())} markets")
    
    print("\nRunning backtest...")
    result = backtester.run(price_data, resolutions)
    
    print("\n" + backtester.print_report(result))
    
    print("\nSample Trades:")
    for trade in result.trades[:5]:
        print(f"  - {trade.ticker}: {trade.direction} @ {trade.entry_price:.2f}")
        print(f"    P&L: ${trade.pnl:.2f}, Fees: ${trade.fees:.2f}")
    
    return result


def demonstrate_constraint_violation():
    """Demonstrate how constraint violations are detected."""
    print("\n" + "=" * 60)
    print("CONSTRAINT VIOLATION DETECTION DEMO")
    print("=" * 60)
    
    engine = ConstraintEngine()
    
    engine.register_constraint(
        constraint_type=ConstraintType.SUBSET,
        lhs_tickers=["TRUMP"],
        rhs_tickers=["GOP"],
        description="Trump ⊂ GOP",
        constraint_id="demo_subset",
    )
    
    print("\nScenario: Trump wins priced at 0.42, GOP wins priced at 0.38")
    print("Constraint: p(Trump) <= p(GOP)")
    print("Violation: 0.42 > 0.38 ✗")
    
    prices = {"TRUMP": 0.42, "GOP": 0.38}
    
    violations = engine.detect_violations(prices)
    
    print(f"\nDetected {len(violations)} violation(s):")
    for v in violations:
        print(f"  - Magnitude: {v.violation_magnitude:.2%}")
        print(f"  - Affected: {v.affected_tickers}")
    
    gop_bound = engine.calculate_bounds("GOP", prices)
    trump_bound = engine.calculate_bounds("TRUMP", prices)
    
    print(f"\nDerived Bounds:")
    print(f"  - GOP: [{gop_bound.lower:.2f}, {gop_bound.upper:.2f}]")
    print(f"    Current price 0.38 violates lower bound {gop_bound.lower:.2f}")
    print(f"  - TRUMP: [{trump_bound.lower:.2f}, {trump_bound.upper:.2f}]")
    print(f"    Current price 0.42 violates upper bound {trump_bound.upper:.2f}")
    
    print("\nTrading Signal:")
    print("  → BUY YES on GOP (underpriced relative to constraint)")
    print("  → Edge = 0.42 - 0.38 = 0.04 (4%)")
    print("  → After fees (~1.5%): Net edge ~2.5%")


if __name__ == "__main__":
    demonstrate_constraint_violation()
    result = run_backtest()
    
    print("\n" + "=" * 60)
    print("BACKTEST COMPLETE")
    print("=" * 60)
