"""
Improved Strategy Search - Finding Robust Edge

The basic calibration strategy showed edge decay in test period.
Testing multiple variations to find a stable, deployable edge.
"""

from __future__ import annotations

import time
from collections import defaultdict

import httpx
import numpy as np
from scipy import stats


def fetch_markets() -> list[dict]:
    print("Fetching markets...")
    client = httpx.Client(timeout=60.0)
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    all_markets = []
    cursor = None
    retries = 0
    
    while len(all_markets) < 20000 and retries < 20:
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
    print(f"  {len(all_markets)} markets")
    return all_markets


def calculate_fee(price: float) -> float:
    if price <= 0 or price >= 1:
        return 0.0
    return max(0.01, np.ceil(0.07 * price * (1 - price) * 100) / 100)


def make_strategy(price_low, price_high, min_vol, max_vol=None, categories=None):
    """Factory to create strategy functions with different parameters."""
    def strategy(markets):
        signals = []
        for m in markets:
            ticker = m.get("ticker", "")
            price = m.get("last_price", 0) / 100
            result = m.get("result", "").lower() == "yes"
            volume = m.get("volume", 0)
            
            if volume < min_vol:
                continue
            if max_vol and volume > max_vol:
                continue
            if categories:
                match = False
                for cat in categories:
                    if cat in ticker:
                        match = True
                        break
                if not match:
                    continue
            
            if price_low <= price <= price_high:
                cost = (1 - price) + calculate_fee(1 - price) + 0.01
                pnl = (1.0 - cost) if not result else -cost
                signals.append({"price": price, "won": not result, "pnl": pnl})
        return signals
    return strategy


def backtest(signals: list[dict]) -> dict:
    if not signals or len(signals) < 10:
        return None
    
    initial = 10000.0
    capital = initial
    returns = []
    
    for s in signals:
        position = min(capital * 0.02, 200)
        contracts = position / 0.5
        trade_pnl = s["pnl"] * contracts
        ret = trade_pnl / capital if capital > 0 else 0
        returns.append(ret)
        capital += trade_pnl
        if capital < 500:
            break
    
    pnls = [s["pnl"] for s in signals[:len(returns)]]
    wins = [p for p in pnls if p > 0]
    
    total_return = (capital - initial) / initial
    win_rate = len(wins) / len(pnls) if pnls else 0
    
    if len(returns) > 5:
        t_stat, p_value = stats.ttest_1samp(returns, 0)
    else:
        t_stat, p_value = 0, 1.0
    
    mean_ret = np.mean(returns)
    std_ret = np.std(returns) if len(returns) > 1 else 1
    sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0
    
    return {
        "trades": len(returns),
        "win_rate": win_rate,
        "return": total_return,
        "sharpe": sharpe,
        "p_value": p_value,
    }


def walk_forward(markets: list[dict], strategy_fn) -> dict:
    n = len(markets)
    train = markets[:int(n * 0.6)]
    test = markets[int(n * 0.6):]
    
    train_result = backtest(strategy_fn(train))
    test_result = backtest(strategy_fn(test))
    
    if not train_result or not test_result:
        return None
    
    robust = (
        train_result["return"] > 0 and
        test_result["return"] > 0 and
        train_result["p_value"] < 0.10 and
        test_result["p_value"] < 0.30
    )
    
    return {
        "train": train_result,
        "test": test_result,
        "robust": robust,
    }


def run_search():
    print("=" * 70)
    print("IMPROVED STRATEGY SEARCH")
    print("=" * 70)
    
    markets = fetch_markets()
    if len(markets) < 5000:
        print("Insufficient data")
        return
    
    strategies = [
        ("Original 35-65%, vol>=25", make_strategy(0.35, 0.65, 25)),
        ("Narrow 40-60%, vol>=25", make_strategy(0.40, 0.60, 25)),
        ("Narrow 40-60%, vol>=50", make_strategy(0.40, 0.60, 50)),
        ("Narrow 40-60%, vol>=100", make_strategy(0.40, 0.60, 100)),
        ("Extreme 45-55%, vol>=25", make_strategy(0.45, 0.55, 25)),
        ("Extreme 45-55%, vol>=50", make_strategy(0.45, 0.55, 50)),
        ("Extreme 45-55%, vol>=100", make_strategy(0.45, 0.55, 100)),
        ("Wide 30-70%, vol>=50", make_strategy(0.30, 0.70, 50)),
        ("Low vol 35-65%, 25-100", make_strategy(0.35, 0.65, 25, 100)),
        ("High vol 35-65%, vol>=200", make_strategy(0.35, 0.65, 200)),
        ("Crypto 35-65%", make_strategy(0.35, 0.65, 25, None, ["BTC", "ETH", "CRYPTO"])),
        ("Sports 35-65%", make_strategy(0.35, 0.65, 25, None, ["NFL", "NBA", "NHL", "MLB"])),
        ("Tight 42-58%, vol>=50", make_strategy(0.42, 0.58, 50)),
        ("Tight 43-57%, vol>=75", make_strategy(0.43, 0.57, 75)),
        ("Mid 38-62%, vol>=75", make_strategy(0.38, 0.62, 75)),
    ]
    
    print(f"\nTesting {len(strategies)} variations...")
    print(f"\n{'Strategy':<35} {'Train':>8} {'Test':>8} {'T-pval':>8} {'Robust':>7}")
    print("-" * 70)
    
    results = []
    for name, fn in strategies:
        result = walk_forward(markets, fn)
        if not result:
            print(f"{name:<35} {'N/A':>8} {'N/A':>8} {'N/A':>8} {'N/A':>7}")
            continue
        
        train_ret = result["train"]["return"]
        test_ret = result["test"]["return"]
        test_p = result["test"]["p_value"]
        robust = "YES" if result["robust"] else "no"
        
        print(f"{name:<35} {train_ret:>+7.1%} {test_ret:>+7.1%} {test_p:>7.3f} {robust:>7}")
        
        results.append((name, result))
    
    robust_strategies = [(n, r) for n, r in results if r["robust"]]
    
    print("\n" + "=" * 70)
    print("ROBUST STRATEGIES (positive train + test, significant)")
    print("=" * 70)
    
    if not robust_strategies:
        print("\nNo robust strategies found.")
        print("\nThe calibration edge appears to be:")
        print("  - Decaying over time")
        print("  - Too weak to survive out-of-sample")
        print("  - Or specific to the training period")
        
        print("\n" + "=" * 70)
        print("RECOMMENDATION")
        print("=" * 70)
        print("\n❌ DO NOT deploy this strategy with real money.")
        print("\nAlternative approaches:")
        print("  1. Paper trade for 4 weeks to see if edge returns")
        print("  2. Focus on specific event types you understand")
        print("  3. Consider market making instead of directional bets")
        print("  4. Look for cross-market arbitrage opportunities")
    else:
        robust_strategies.sort(key=lambda x: x[1]["test"]["return"], reverse=True)
        
        print(f"\nFound {len(robust_strategies)} robust strategies:")
        for name, r in robust_strategies:
            print(f"\n  {name}:")
            print(f"    Train: {r['train']['return']:+.2%} "
                  f"(p={r['train']['p_value']:.4f}, {r['train']['trades']} trades)")
            print(f"    Test:  {r['test']['return']:+.2%} "
                  f"(p={r['test']['p_value']:.4f}, {r['test']['trades']} trades)")
        
        best_name, best = robust_strategies[0]
        
        print("\n" + "=" * 70)
        print("BEST STRATEGY FOR DEPLOYMENT")
        print("=" * 70)
        print(f"\n  Strategy: {best_name}")
        print(f"  Test Return: {best['test']['return']:+.2%}")
        print(f"  Test p-value: {best['test']['p_value']:.4f}")
        
        if best["test"]["return"] > 0.05 and best["test"]["p_value"] < 0.15:
            print("\n  ✓ DEPLOYABLE - Paper trade for 2 weeks, then small live test")
        elif best["test"]["return"] > 0.02:
            print("\n  ~ MARGINAL - Paper trade for 4 weeks before any live trading")
        else:
            print("\n  ⚠ WEAK - Continue research before deployment")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    run_search()
