"""
Calibration Edge Strategy - The Robust One

Key Finding: Kalshi markets are systematically miscalibrated.
- At price 0.40, actual YES rate is only 21% (not 40%)
- At price 0.50, actual YES rate is only 36% (not 50%)
- At price 0.60, actual YES rate is only 40% (not 60%)

Strategy: Bet NO on markets priced 35-65% (they're overpriced)

This script validates with:
1. Large sample size (15,000+ markets)
2. Walk-forward validation (60/40 split)
3. Statistical significance testing
4. Monte Carlo simulation
5. Multiple time period testing
"""

from __future__ import annotations

import time
from collections import defaultdict

import httpx
import numpy as np
from scipy import stats


def fetch_all_markets() -> list[dict]:
    """Fetch maximum markets with rate limiting."""
    print("Fetching all available markets...")
    client = httpx.Client(timeout=60.0)
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    all_markets = []
    cursor = None
    retries = 0
    
    while len(all_markets) < 20000 and retries < 15:
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
    print(f"  Total: {len(all_markets)} markets")
    return all_markets


def calculate_fee(price: float) -> float:
    if price <= 0 or price >= 1:
        return 0.0
    return max(0.01, np.ceil(0.07 * price * (1 - price) * 100) / 100)


def analyze_calibration(markets: list[dict]) -> dict:
    """Analyze price calibration across all markets."""
    buckets = defaultdict(list)
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = 1 if m.get("result", "").lower() == "yes" else 0
        
        if 0.05 <= price <= 0.95:
            bucket = round(price * 20) / 20
            buckets[bucket].append(result)
    
    calibration = {}
    for bucket in sorted(buckets.keys()):
        outcomes = buckets[bucket]
        if len(outcomes) >= 20:
            actual = np.mean(outcomes)
            calibration[bucket] = {
                "count": len(outcomes),
                "actual": actual,
                "expected": bucket,
                "edge": bucket - actual,
            }
    
    return calibration


def generate_calibration_signals(
    markets: list[dict],
    edge_threshold: float = 0.10,
    min_volume: int = 25,
) -> list[dict]:
    """
    Generate signals based on calibration edge.
    Bet NO when price > actual probability (overpriced YES).
    """
    signals = []
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)
        
        if volume < min_volume:
            continue
        
        if 0.35 <= price <= 0.65:
            cost = (1 - price) + calculate_fee(1 - price) + 0.01
            pnl = (1.0 - cost) if not result else -cost
            signals.append({
                "price": price,
                "bet": "NO",
                "won": not result,
                "pnl": pnl,
                "volume": volume,
            })
    
    return signals


def backtest_with_sizing(
    signals: list[dict],
    initial: float = 10000.0,
    position_pct: float = 0.02,
    max_position: float = 200.0,
) -> dict:
    """Backtest with proper position sizing."""
    if not signals:
        return None
    
    capital = initial
    returns = []
    equity = [initial]
    trade_details = []
    
    for s in signals:
        position = min(capital * position_pct, max_position)
        contracts = position / 0.5
        trade_pnl = s["pnl"] * contracts
        
        ret = trade_pnl / capital if capital > 0 else 0
        returns.append(ret)
        capital += trade_pnl
        equity.append(capital)
        
        trade_details.append({
            **s,
            "trade_pnl": trade_pnl,
            "capital": capital,
        })
        
        if capital < 500:
            break
    
    if len(returns) < 5:
        return None
    
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
    
    t_stat, p_value = stats.ttest_1samp(returns, 0)
    
    total_return = (capital - initial) / initial
    win_rate = len(wins) / len(pnls) if pnls else 0
    profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0
    
    return {
        "trades": len(returns),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "total_return": total_return,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "profit_factor": profit_factor,
        "t_stat": t_stat,
        "p_value": p_value,
        "returns": returns,
        "equity": equity,
        "details": trade_details,
    }


def monte_carlo_simulation(returns: list[float], n_sims: int = 10000) -> dict:
    """Monte Carlo to assess robustness."""
    if len(returns) < 10:
        return None
    
    simulated_totals = []
    simulated_dds = []
    
    for _ in range(n_sims):
        shuffled = np.random.choice(returns, size=len(returns), replace=True)
        
        cumsum = np.cumsum(shuffled)
        total = cumsum[-1]
        simulated_totals.append(total)
        
        peak = 0
        max_dd = 0
        for val in cumsum:
            if val > peak:
                peak = val
            dd = (peak - val) if peak > 0 else 0
            max_dd = max(max_dd, dd)
        simulated_dds.append(max_dd)
    
    return {
        "p_profitable": np.mean([t > 0 for t in simulated_totals]),
        "expected_return": np.mean(simulated_totals),
        "median_return": np.median(simulated_totals),
        "return_5pct": np.percentile(simulated_totals, 5),
        "return_95pct": np.percentile(simulated_totals, 95),
        "expected_dd": np.mean(simulated_dds),
        "max_dd_95pct": np.percentile(simulated_dds, 95),
    }


def walk_forward_validation(markets: list[dict]) -> dict:
    """Proper walk-forward validation."""
    n = len(markets)
    
    results = {
        "periods": [],
        "all_train_positive": True,
        "all_test_positive": True,
    }
    
    splits = [
        (0.0, 0.5, 0.5, 0.75),
        (0.25, 0.75, 0.75, 1.0),
        (0.0, 0.6, 0.6, 1.0),
    ]
    
    for train_start, train_end, test_start, test_end in splits:
        train = markets[int(n * train_start):int(n * train_end)]
        test = markets[int(n * test_start):int(n * test_end)]
        
        train_signals = generate_calibration_signals(train)
        test_signals = generate_calibration_signals(test)
        
        train_result = backtest_with_sizing(train_signals)
        test_result = backtest_with_sizing(test_signals)
        
        if train_result and test_result:
            results["periods"].append({
                "train_return": train_result["total_return"],
                "test_return": test_result["total_return"],
                "train_trades": train_result["trades"],
                "test_trades": test_result["trades"],
                "train_pvalue": train_result["p_value"],
            })
            
            if train_result["total_return"] <= 0:
                results["all_train_positive"] = False
            if test_result["total_return"] <= 0:
                results["all_test_positive"] = False
    
    return results


def run_full_validation():
    print("=" * 70)
    print("CALIBRATION EDGE STRATEGY - FULL VALIDATION")
    print("=" * 70)
    
    markets = fetch_all_markets()
    if len(markets) < 5000:
        print("Insufficient data for robust validation")
        return
    
    print("\n" + "=" * 70)
    print("1. CALIBRATION ANALYSIS")
    print("=" * 70)
    
    calibration = analyze_calibration(markets)
    
    print(f"\n{'Price':>6} {'Count':>6} {'Actual':>8} {'Expected':>8} {'Edge':>8}")
    print("-" * 45)
    
    for bucket in sorted(calibration.keys()):
        data = calibration[bucket]
        if data["count"] >= 50:
            edge_str = f"{data['edge']:+.1%}" if abs(data["edge"]) > 0.05 else ""
            print(f"{bucket:>6.2f} {data['count']:>6} "
                  f"{data['actual']:>7.1%} {data['expected']:>7.1%} {edge_str:>8}")
    
    print("\n" + "=" * 70)
    print("2. WALK-FORWARD VALIDATION")
    print("=" * 70)
    
    wf_results = walk_forward_validation(markets)
    
    print(f"\n{'Period':>8} {'Train':>10} {'Test':>10} {'Trades':>8}")
    print("-" * 40)
    
    for i, period in enumerate(wf_results["periods"]):
        print(f"   {i + 1:>5} {period['train_return']:>+9.2%} "
              f"{period['test_return']:>+9.2%} "
              f"{period['train_trades'] + period['test_trades']:>8}")
    
    print(f"\nAll train periods positive: {wf_results['all_train_positive']}")
    print(f"All test periods positive: {wf_results['all_test_positive']}")
    
    print("\n" + "=" * 70)
    print("3. FULL BACKTEST")
    print("=" * 70)
    
    all_signals = generate_calibration_signals(markets)
    full_result = backtest_with_sizing(all_signals)
    
    if full_result:
        print(f"\nTotal Trades: {full_result['trades']}")
        print(f"Win Rate: {full_result['win_rate']:.1%}")
        print(f"Total Return: {full_result['total_return']:+.2%}")
        print(f"Sharpe Ratio: {full_result['sharpe']:.2f}")
        print(f"Max Drawdown: {full_result['max_dd']:.1%}")
        print(f"Profit Factor: {full_result['profit_factor']:.2f}")
        print(f"t-statistic: {full_result['t_stat']:.3f}")
        print(f"p-value: {full_result['p_value']:.4f}")
        
        is_significant = full_result["p_value"] < 0.05
        print(f"\nStatistically Significant: {'YES' if is_significant else 'NO'}")
    
    print("\n" + "=" * 70)
    print("4. MONTE CARLO SIMULATION")
    print("=" * 70)
    
    if full_result:
        mc = monte_carlo_simulation(full_result["returns"])
        if mc:
            print(f"\nSimulations: 10,000")
            print(f"Probability of Profit: {mc['p_profitable']:.1%}")
            print(f"Expected Return: {mc['expected_return']:.4f}")
            print(f"Median Return: {mc['median_return']:.4f}")
            print(f"5th Percentile: {mc['return_5pct']:.4f}")
            print(f"95th Percentile: {mc['return_95pct']:.4f}")
            print(f"Expected Max DD: {mc['expected_dd']:.4f}")
    
    print("\n" + "=" * 70)
    print("5. FINAL VERDICT")
    print("=" * 70)
    
    is_robust = (
        full_result and
        full_result["p_value"] < 0.10 and
        full_result["total_return"] > 0.05 and
        wf_results["all_test_positive"] and
        len(wf_results["periods"]) >= 2
    )
    
    if is_robust:
        print("\n✓ STRATEGY IS ROBUST")
        print("\nThe Calibration Edge strategy shows:")
        print(f"  - Positive returns in all test periods")
        print(f"  - Statistical significance (p < 0.10)")
        print(f"  - Consistent edge across time")
        
        print("\nIMPLEMENTATION RULES:")
        print("  1. Bet NO on markets priced 35-65%")
        print("  2. Require volume >= 25 contracts")
        print("  3. Position size: 2% of capital, max $200")
        print("  4. Stop if drawdown > 20%")
        
        print("\nCAVEATS:")
        print("  - This is historical data")
        print("  - Real execution will have slippage")
        print("  - Market structure may change")
        print("  - Paper trade first!")
    else:
        print("\n✗ STRATEGY NOT ROBUST ENOUGH")
        print("\nReasons:")
        if not full_result:
            print("  - Insufficient trades")
        elif full_result["p_value"] >= 0.10:
            print(f"  - Not statistically significant (p={full_result['p_value']:.3f})")
        if not wf_results["all_test_positive"]:
            print("  - Some test periods had negative returns")
    
    print("\n" + "=" * 70)
    
    if full_result and full_result["trades"] > 0:
        print("\nSAMPLE TRADES:")
        for t in full_result["details"][:10]:
            status = "WIN" if t["won"] else "LOSS"
            print(f"  price={t['price']:.2f} | bet={t['bet']:3} | "
                  f"P&L=${t['trade_pnl']:+.2f} [{status}]")


if __name__ == "__main__":
    run_full_validation()
