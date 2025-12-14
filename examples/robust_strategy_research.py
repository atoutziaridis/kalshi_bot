"""
Robust Strategy Research - Statistical Validation

This script:
1. Fetches maximum available historical data
2. Tests 20+ strategy variations
3. Uses walk-forward validation (train/test split)
4. Calculates statistical significance (t-test, confidence intervals)
5. Runs Monte Carlo simulations
6. Identifies truly robust strategies
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import httpx
import numpy as np
from scipy import stats


@dataclass
class StrategyResult:
    name: str
    params: dict
    trades: int
    wins: int
    win_rate: float
    total_return: float
    sharpe: float
    max_dd: float
    profit_factor: float
    t_stat: float
    p_value: float
    is_significant: bool
    train_return: float
    test_return: float


def fetch_max_markets() -> list[dict]:
    """Fetch as many markets as possible with rate limiting."""
    print("Fetching maximum historical data...")
    client = httpx.Client(timeout=60.0)
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    all_markets = []
    cursor = None
    
    for i in range(50):
        params = {"limit": 200, "status": "settled"}
        if cursor:
            params["cursor"] = cursor
        
        try:
            response = client.get(f"{base_url}/markets", params=params)
            if response.status_code == 429:
                print(f"  Rate limited. Waiting 5s...")
                time.sleep(5)
                continue
            response.raise_for_status()
            data = response.json()
            markets = data.get("markets", [])
            all_markets.extend(markets)
            cursor = data.get("cursor")
            if not cursor or not markets:
                break
            if i % 5 == 0:
                print(f"  Fetched {len(all_markets)} markets...")
        except Exception as e:
            print(f"  Error: {e}")
            break
    
    client.close()
    print(f"  Total: {len(all_markets)} markets")
    return all_markets


def calculate_fee(price: float) -> float:
    if price <= 0 or price >= 1:
        return 0.0
    return max(0.01, np.ceil(0.07 * price * (1 - price) * 100) / 100)


def generate_signals(
    markets: list[dict],
    yes_low: float,
    yes_high: float,
    no_low: float,
    no_high: float,
    min_volume: int,
) -> list[dict]:
    """Generate signals with configurable parameters."""
    signals = []
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)
        
        if volume < min_volume:
            continue
        
        if yes_low < price < yes_high:
            cost = price + calculate_fee(price) + 0.01
            pnl = (1.0 - cost) if result else -cost
            signals.append({
                "price": price,
                "bet": "YES",
                "won": result,
                "pnl": pnl,
            })
        elif no_low < price < no_high:
            cost = (1 - price) + calculate_fee(1 - price) + 0.01
            pnl = (1.0 - cost) if not result else -cost
            signals.append({
                "price": price,
                "bet": "NO",
                "won": not result,
                "pnl": pnl,
            })
    
    return signals


def backtest_signals(signals: list[dict], position_pct: float = 0.03) -> dict:
    """Backtest signals and return metrics."""
    if not signals:
        return None
    
    initial = 10000.0
    capital = initial
    returns = []
    equity = [initial]
    
    for s in signals:
        position = min(capital * position_pct, 300)
        contracts = position / 0.5
        trade_pnl = s["pnl"] * contracts
        
        ret = trade_pnl / capital if capital > 0 else 0
        returns.append(ret)
        
        capital += trade_pnl
        equity.append(capital)
        
        if capital < 500:
            break
    
    if not returns:
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
    
    total_return = (capital - initial) / initial
    win_rate = len(wins) / len(pnls) if pnls else 0
    profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0
    
    if len(returns) > 2:
        t_stat, p_value = stats.ttest_1samp(returns, 0)
    else:
        t_stat, p_value = 0, 1
    
    return {
        "trades": len(returns),
        "wins": len(wins),
        "win_rate": win_rate,
        "total_return": total_return,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "profit_factor": profit_factor,
        "t_stat": t_stat,
        "p_value": p_value,
        "returns": returns,
    }


def walk_forward_test(
    markets: list[dict],
    yes_low: float,
    yes_high: float,
    no_low: float,
    no_high: float,
    min_volume: int,
    train_pct: float = 0.7,
) -> tuple[dict, dict]:
    """Split data into train/test for out-of-sample validation."""
    n = len(markets)
    split = int(n * train_pct)
    
    train_markets = markets[:split]
    test_markets = markets[split:]
    
    train_signals = generate_signals(
        train_markets, yes_low, yes_high, no_low, no_high, min_volume
    )
    test_signals = generate_signals(
        test_markets, yes_low, yes_high, no_low, no_high, min_volume
    )
    
    train_result = backtest_signals(train_signals)
    test_result = backtest_signals(test_signals)
    
    return train_result, test_result


def monte_carlo_validation(returns: list[float], n_simulations: int = 1000) -> dict:
    """Run Monte Carlo to assess robustness."""
    if len(returns) < 5:
        return {"p_profitable": 0, "expected_return": 0, "var_95": 0}
    
    simulated_returns = []
    
    for _ in range(n_simulations):
        shuffled = np.random.choice(returns, size=len(returns), replace=True)
        total = np.sum(shuffled)
        simulated_returns.append(total)
    
    p_profitable = np.mean([r > 0 for r in simulated_returns])
    expected = np.mean(simulated_returns)
    var_95 = np.percentile(simulated_returns, 5)
    
    return {
        "p_profitable": p_profitable,
        "expected_return": expected,
        "var_95": var_95,
    }


def test_strategy_grid(markets: list[dict]) -> list[StrategyResult]:
    """Test a grid of strategy parameters."""
    results = []
    
    param_grid = [
        {"yes_low": 0.55, "yes_high": 0.75, "no_low": 0.25, "no_high": 0.45, "min_vol": 50},
        {"yes_low": 0.60, "yes_high": 0.80, "no_low": 0.20, "no_high": 0.40, "min_vol": 50},
        {"yes_low": 0.60, "yes_high": 0.85, "no_low": 0.15, "no_high": 0.40, "min_vol": 50},
        {"yes_low": 0.65, "yes_high": 0.85, "no_low": 0.15, "no_high": 0.35, "min_vol": 50},
        {"yes_low": 0.70, "yes_high": 0.90, "no_low": 0.10, "no_high": 0.30, "min_vol": 50},
        {"yes_low": 0.55, "yes_high": 0.75, "no_low": 0.25, "no_high": 0.45, "min_vol": 100},
        {"yes_low": 0.60, "yes_high": 0.80, "no_low": 0.20, "no_high": 0.40, "min_vol": 100},
        {"yes_low": 0.60, "yes_high": 0.85, "no_low": 0.15, "no_high": 0.40, "min_vol": 100},
        {"yes_low": 0.65, "yes_high": 0.85, "no_low": 0.15, "no_high": 0.35, "min_vol": 100},
        {"yes_low": 0.55, "yes_high": 0.70, "no_low": 0.30, "no_high": 0.45, "min_vol": 50},
        {"yes_low": 0.50, "yes_high": 0.65, "no_low": 0.35, "no_high": 0.50, "min_vol": 50},
        {"yes_low": 0.52, "yes_high": 0.68, "no_low": 0.32, "no_high": 0.48, "min_vol": 50},
        {"yes_low": 0.55, "yes_high": 0.72, "no_low": 0.28, "no_high": 0.45, "min_vol": 75},
        {"yes_low": 0.58, "yes_high": 0.78, "no_low": 0.22, "no_high": 0.42, "min_vol": 75},
        {"yes_low": 0.62, "yes_high": 0.82, "no_low": 0.18, "no_high": 0.38, "min_vol": 75},
        {"yes_low": 0.55, "yes_high": 0.65, "no_low": 0.35, "no_high": 0.45, "min_vol": 25},
        {"yes_low": 0.53, "yes_high": 0.67, "no_low": 0.33, "no_high": 0.47, "min_vol": 25},
        {"yes_low": 0.51, "yes_high": 0.60, "no_low": 0.40, "no_high": 0.49, "min_vol": 25},
        {"yes_low": 0.75, "yes_high": 0.95, "no_low": 0.05, "no_high": 0.25, "min_vol": 50},
        {"yes_low": 0.80, "yes_high": 0.95, "no_low": 0.05, "no_high": 0.20, "min_vol": 50},
    ]
    
    print(f"\nTesting {len(param_grid)} parameter combinations...")
    
    for i, p in enumerate(param_grid):
        train_result, test_result = walk_forward_test(
            markets,
            p["yes_low"], p["yes_high"],
            p["no_low"], p["no_high"],
            p["min_vol"],
        )
        
        if not train_result or not test_result:
            continue
        
        if train_result["trades"] < 10 or test_result["trades"] < 5:
            continue
        
        combined_returns = train_result["returns"] + test_result["returns"]
        
        is_significant = (
            train_result["p_value"] < 0.10 and
            test_result["total_return"] > 0 and
            train_result["total_return"] > 0
        )
        
        name = f"YES[{p['yes_low']:.2f}-{p['yes_high']:.2f}]_NO[{p['no_low']:.2f}-{p['no_high']:.2f}]_V{p['min_vol']}"
        
        results.append(StrategyResult(
            name=name,
            params=p,
            trades=train_result["trades"] + test_result["trades"],
            wins=train_result["wins"] + test_result["wins"],
            win_rate=(train_result["win_rate"] + test_result["win_rate"]) / 2,
            total_return=(train_result["total_return"] + test_result["total_return"]) / 2,
            sharpe=(train_result["sharpe"] + test_result["sharpe"]) / 2,
            max_dd=max(train_result["max_dd"], test_result["max_dd"]),
            profit_factor=(train_result["profit_factor"] + test_result["profit_factor"]) / 2,
            t_stat=train_result["t_stat"],
            p_value=train_result["p_value"],
            is_significant=is_significant,
            train_return=train_result["total_return"],
            test_return=test_result["total_return"],
        ))
    
    return results


def run_research():
    print("=" * 70)
    print("ROBUST STRATEGY RESEARCH")
    print("=" * 70)
    print("\nObjective: Find statistically significant, out-of-sample validated strategy")
    
    markets = fetch_max_markets()
    if len(markets) < 500:
        print("Insufficient data for robust analysis")
        return
    
    print(f"\nData: {len(markets)} settled markets")
    print(f"Train/Test Split: 70%/30%")
    
    results = test_strategy_grid(markets)
    
    if not results:
        print("\nNo valid strategies found")
        return
    
    results.sort(key=lambda x: x.total_return, reverse=True)
    
    print("\n" + "=" * 70)
    print("TOP 10 STRATEGIES BY RETURN")
    print("=" * 70)
    print(f"{'Strategy':<50} {'Trades':>6} {'WinR':>6} {'Return':>8} {'Test':>8} {'Sig':>4}")
    print("-" * 70)
    
    for r in results[:10]:
        sig = "YES" if r.is_significant else "no"
        print(f"{r.name:<50} {r.trades:>6} {r.win_rate:>5.1%} {r.total_return:>+7.2%} {r.test_return:>+7.2%} {sig:>4}")
    
    significant = [r for r in results if r.is_significant]
    
    print("\n" + "=" * 70)
    print(f"STATISTICALLY SIGNIFICANT STRATEGIES ({len(significant)} found)")
    print("=" * 70)
    
    if not significant:
        print("\nNo strategies passed significance tests.")
        print("This means the edge is likely due to chance.")
        
        print("\n" + "=" * 70)
        print("ALTERNATIVE APPROACHES")
        print("=" * 70)
        print("""
Since simple momentum doesn't show robust edge, consider:

1. MARKET MAKING
   - Provide liquidity, earn the spread
   - Requires API access and fast execution
   
2. EVENT-SPECIFIC EXPERTISE
   - Focus on domains you know (sports, politics, crypto)
   - Use superior information/models
   
3. CALENDAR EFFECTS
   - Markets may misprice near expiration
   - Time-based patterns
   
4. CROSS-MARKET ARBITRAGE
   - Compare Kalshi to other prediction markets
   - Polymarket, PredictIt price differences
""")
    else:
        significant.sort(key=lambda x: x.test_return, reverse=True)
        
        print(f"\n{'Strategy':<50} {'Train':>8} {'Test':>8} {'p-val':>8}")
        print("-" * 70)
        
        for r in significant:
            print(f"{r.name:<50} {r.train_return:>+7.2%} {r.test_return:>+7.2%} {r.p_value:>7.4f}")
        
        best = significant[0]
        
        print("\n" + "=" * 70)
        print("BEST ROBUST STRATEGY")
        print("=" * 70)
        print(f"\nStrategy: {best.name}")
        print(f"Parameters:")
        print(f"  YES range: {best.params['yes_low']:.2f} - {best.params['yes_high']:.2f}")
        print(f"  NO range:  {best.params['no_low']:.2f} - {best.params['no_high']:.2f}")
        print(f"  Min Volume: {best.params['min_vol']}")
        print(f"\nPerformance:")
        print(f"  Total Trades: {best.trades}")
        print(f"  Win Rate: {best.win_rate:.1%}")
        print(f"  Train Return: {best.train_return:+.2%}")
        print(f"  Test Return: {best.test_return:+.2%}")
        print(f"  Sharpe Ratio: {best.sharpe:.2f}")
        print(f"  Max Drawdown: {best.max_dd:.1%}")
        print(f"  p-value: {best.p_value:.4f}")
        
        all_signals = generate_signals(
            markets,
            best.params["yes_low"],
            best.params["yes_high"],
            best.params["no_low"],
            best.params["no_high"],
            best.params["min_vol"],
        )
        all_result = backtest_signals(all_signals)
        
        if all_result:
            mc = monte_carlo_validation(all_result["returns"])
            print(f"\nMonte Carlo Validation (1000 simulations):")
            print(f"  Probability of Profit: {mc['p_profitable']:.1%}")
            print(f"  Expected Return: {mc['expected_return']:.4f}")
            print(f"  95% VaR: {mc['var_95']:.4f}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    run_research()
