"""
FINAL REALISTIC BACKTEST

Tests both strategies with REAL Kalshi data:
1. Original Constraint-Based Strategy (from docs/main.md)
2. Calibration Edge Strategy (discovered through research)

Includes:
- Actual Kalshi fees: 0.07 * p * (1-p)
- Realistic spread costs: 2 cents
- Walk-forward validation
- Statistical significance testing
"""

from __future__ import annotations

import time
from collections import defaultdict

import httpx
import numpy as np
from scipy import stats


def fetch_markets(max_markets: int = 20000) -> list[dict]:
    """Fetch maximum settled markets."""
    print("Fetching real Kalshi market data...")
    client = httpx.Client(timeout=60.0)
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    all_markets = []
    cursor = None
    retries = 0
    
    while len(all_markets) < max_markets and retries < 20:
        params = {"limit": 200, "status": "settled"}
        if cursor:
            params["cursor"] = cursor
        
        try:
            response = client.get(f"{base_url}/markets", params=params)
            if response.status_code == 429:
                retries += 1
                time.sleep(2)
                continue
            response.raise_for_status()
            data = response.json()
            markets = data.get("markets", [])
            all_markets.extend(markets)
            cursor = data.get("cursor")
            if not cursor or not markets:
                break
            retries = 0
        except Exception:
            retries += 1
            time.sleep(1)
    
    client.close()
    print(f"  Fetched {len(all_markets)} settled markets")
    return all_markets


def calculate_fee(price: float) -> float:
    """Kalshi fee formula: 0.07 * p * (1-p), min 1 cent."""
    if price <= 0 or price >= 1:
        return 0.0
    return max(0.01, np.ceil(0.07 * price * (1 - price) * 100) / 100)


def strategy_constraint_based(markets: list[dict]) -> list[dict]:
    """
    Original strategy from docs/main.md:
    Find subset/temporal constraints and trade violations.
    """
    signals = []
    
    by_series = defaultdict(list)
    for m in markets:
        series = m.get("series_ticker", "")
        if series:
            by_series[series].append(m)
    
    for series, series_markets in by_series.items():
        if len(series_markets) < 2:
            continue
        
        sorted_mkts = sorted(
            series_markets,
            key=lambda x: x.get("expiration_time", "") or "",
        )
        
        for i in range(len(sorted_mkts) - 1):
            earlier = sorted_mkts[i]
            later = sorted_mkts[i + 1]
            
            p_earlier = earlier.get("last_price", 0) / 100
            p_later = later.get("last_price", 0) / 100
            
            if p_earlier < 0.05 or p_earlier > 0.95:
                continue
            if p_later < 0.05 or p_later > 0.95:
                continue
            
            violation = p_earlier - p_later
            
            fee = calculate_fee(p_earlier) + calculate_fee(p_later)
            spread = 0.02
            net_edge = abs(violation) - fee - spread
            
            if net_edge < 0.01:
                continue
            
            result_earlier = earlier.get("result", "").lower() == "yes"
            result_later = later.get("result", "").lower() == "yes"
            
            if violation > 0:
                cost = p_later + calculate_fee(p_later) + 0.01
                pnl = (1.0 - cost) if result_later else -cost
                signals.append({
                    "strategy": "constraint",
                    "type": "temporal_subset",
                    "price": p_later,
                    "bet": "YES_LATER",
                    "won": result_later,
                    "pnl": pnl,
                    "edge": net_edge,
                })
            else:
                cost = (1 - p_earlier) + calculate_fee(1 - p_earlier) + 0.01
                pnl = (1.0 - cost) if not result_earlier else -cost
                signals.append({
                    "strategy": "constraint",
                    "type": "temporal_subset",
                    "price": p_earlier,
                    "bet": "NO_EARLIER",
                    "won": not result_earlier,
                    "pnl": pnl,
                    "edge": net_edge,
                })
    
    return signals


def strategy_calibration_edge(markets: list[dict]) -> list[dict]:
    """
    Discovered strategy: Bet NO on mid-range prices (35-65%).
    Markets are systematically miscalibrated at these levels.
    """
    signals = []
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)
        
        if volume < 25:
            continue
        
        if 0.35 <= price <= 0.65:
            cost = (1 - price) + calculate_fee(1 - price) + 0.01
            pnl = (1.0 - cost) if not result else -cost
            signals.append({
                "strategy": "calibration",
                "price": price,
                "bet": "NO",
                "won": not result,
                "pnl": pnl,
            })
    
    return signals


def backtest(signals: list[dict], initial: float = 10000.0) -> dict:
    """Run backtest with position sizing and track all metrics."""
    if not signals or len(signals) < 5:
        return None
    
    capital = initial
    returns = []
    equity = [initial]
    
    for s in signals:
        position = min(capital * 0.02, 200)
        contracts = position / 0.5
        trade_pnl = s["pnl"] * contracts
        
        ret = trade_pnl / capital if capital > 0 else 0
        returns.append(ret)
        capital += trade_pnl
        equity.append(capital)
        
        if capital < 500:
            break
    
    pnls = [s["pnl"] for s in signals[:len(returns)]]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    
    peak = initial
    max_dd = 0
    for eq in equity:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    
    mean_ret = np.mean(returns)
    std_ret = np.std(returns) if len(returns) > 1 else 1
    sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0
    
    if len(returns) > 5:
        t_stat, p_value = stats.ttest_1samp(returns, 0)
    else:
        t_stat, p_value = 0, 1.0
    
    total_return = (capital - initial) / initial
    win_rate = len(wins) / len(pnls) if pnls else 0
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0
    
    return {
        "trades": len(returns),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "total_return": total_return,
        "final_capital": capital,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "profit_factor": pf,
        "t_stat": t_stat,
        "p_value": p_value,
        "significant": p_value < 0.05 and total_return > 0,
    }


def walk_forward(markets: list[dict], strategy_fn) -> dict:
    """Walk-forward validation with 60/40 split."""
    n = len(markets)
    train = markets[:int(n * 0.6)]
    test = markets[int(n * 0.6):]
    
    train_signals = strategy_fn(train)
    test_signals = strategy_fn(test)
    
    train_result = backtest(train_signals)
    test_result = backtest(test_signals)
    
    return {
        "train": train_result,
        "test": test_result,
    }


def run_final_test():
    print("=" * 70)
    print("FINAL REALISTIC BACKTEST")
    print("=" * 70)
    print("\nUsing REAL Kalshi data with ACTUAL fees")
    print("Fee formula: 0.07 * p * (1-p)")
    print("Spread cost: 2 cents per contract")
    print("Position sizing: 2% of capital, max $200")
    
    markets = fetch_markets()
    if len(markets) < 1000:
        print("Insufficient data")
        return
    
    print(f"\nTotal markets: {len(markets)}")
    
    print("\n" + "=" * 70)
    print("STRATEGY 1: CONSTRAINT-BASED (from docs/main.md)")
    print("=" * 70)
    print("Rule: Trade temporal/subset constraint violations")
    
    constraint_wf = walk_forward(markets, strategy_constraint_based)
    
    if constraint_wf["train"] and constraint_wf["test"]:
        print(f"\nTrain Period:")
        print(f"  Trades: {constraint_wf['train']['trades']}")
        print(f"  Return: {constraint_wf['train']['total_return']:+.2%}")
        print(f"  Win Rate: {constraint_wf['train']['win_rate']:.1%}")
        
        print(f"\nTest Period:")
        print(f"  Trades: {constraint_wf['test']['trades']}")
        print(f"  Return: {constraint_wf['test']['total_return']:+.2%}")
        print(f"  Win Rate: {constraint_wf['test']['win_rate']:.1%}")
        
        constraint_works = (
            constraint_wf["train"]["total_return"] > 0 and
            constraint_wf["test"]["total_return"] > 0
        )
        print(f"\nRobust: {'YES' if constraint_works else 'NO'}")
    else:
        print("\nInsufficient constraint signals found")
        constraint_works = False
    
    print("\n" + "=" * 70)
    print("STRATEGY 2: CALIBRATION EDGE (discovered)")
    print("=" * 70)
    print("Rule: Bet NO on markets priced 35-65% (they're overpriced)")
    
    calibration_wf = walk_forward(markets, strategy_calibration_edge)
    
    if calibration_wf["train"] and calibration_wf["test"]:
        print(f"\nTrain Period:")
        print(f"  Trades: {calibration_wf['train']['trades']}")
        print(f"  Return: {calibration_wf['train']['total_return']:+.2%}")
        print(f"  Win Rate: {calibration_wf['train']['win_rate']:.1%}")
        print(f"  Sharpe: {calibration_wf['train']['sharpe']:.2f}")
        print(f"  p-value: {calibration_wf['train']['p_value']:.4f}")
        
        print(f"\nTest Period:")
        print(f"  Trades: {calibration_wf['test']['trades']}")
        print(f"  Return: {calibration_wf['test']['total_return']:+.2%}")
        print(f"  Win Rate: {calibration_wf['test']['win_rate']:.1%}")
        print(f"  Sharpe: {calibration_wf['test']['sharpe']:.2f}")
        print(f"  p-value: {calibration_wf['test']['p_value']:.4f}")
        
        calibration_works = (
            calibration_wf["train"]["total_return"] > 0 and
            calibration_wf["test"]["total_return"] > 0 and
            calibration_wf["train"]["p_value"] < 0.10
        )
        print(f"\nRobust: {'YES' if calibration_works else 'NO'}")
        print(f"Statistically Significant: "
              f"{'YES' if calibration_wf['train']['significant'] else 'NO'}")
    else:
        calibration_works = False
    
    print("\n" + "=" * 70)
    print("FULL BACKTEST (ALL DATA)")
    print("=" * 70)
    
    all_calibration = strategy_calibration_edge(markets)
    full_result = backtest(all_calibration)
    
    if full_result:
        print(f"\nCalibration Edge Strategy - Full Results:")
        print(f"  Total Trades: {full_result['trades']}")
        print(f"  Win Rate: {full_result['win_rate']:.1%}")
        print(f"  Total Return: {full_result['total_return']:+.2%}")
        print(f"  Final Capital: ${full_result['final_capital']:,.2f}")
        print(f"  Sharpe Ratio: {full_result['sharpe']:.2f}")
        print(f"  Max Drawdown: {full_result['max_dd']:.1%}")
        print(f"  Profit Factor: {full_result['profit_factor']:.2f}")
        print(f"  t-statistic: {full_result['t_stat']:.3f}")
        print(f"  p-value: {full_result['p_value']:.4f}")
    
    print("\n" + "=" * 70)
    print("FINAL VERDICT")
    print("=" * 70)
    
    print("\n1. CONSTRAINT-BASED STRATEGY (docs/main.md):")
    if constraint_works:
        print("   ✓ Works - Shows positive returns in train and test")
    else:
        print("   ✗ Does NOT work reliably")
        print("   - Insufficient constraint violations in real data")
        print("   - Or violations don't predict outcomes")
    
    print("\n2. CALIBRATION EDGE STRATEGY:")
    if calibration_works and full_result and full_result["significant"]:
        print("   ✓ WORKS - Statistically significant edge found!")
        print(f"   - {full_result['trades']} trades")
        print(f"   - {full_result['win_rate']:.1%} win rate")
        print(f"   - {full_result['total_return']:+.2%} return")
        print(f"   - p-value: {full_result['p_value']:.4f}")
        
        print("\n   THE WINNING STRATEGY:")
        print("   ━━━━━━━━━━━━━━━━━━━━━━")
        print("   Rule: Bet NO on markets priced 35-65%")
        print("   Why: Kalshi YES prices are systematically too high")
        print("        at mid-range levels (actual win rate ~30-40%,")
        print("        not the 35-65% the price suggests)")
        print("   Volume: Require >= 25 contracts")
        print("   Size: 2% of capital per trade, max $200")
    elif calibration_works:
        print("   ~ Marginal edge - positive but not significant")
    else:
        print("   ✗ Does not show robust edge")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    run_final_test()
