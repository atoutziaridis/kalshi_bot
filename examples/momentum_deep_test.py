"""
Momentum Strategy Deep Test

The momentum strategy showed 88.9% win rate earlier.
Let's test many variations to find a robust version.

Momentum = Bet WITH the crowd on moderate prices
- Buy YES when price is moderately high (crowd expects YES)
- Buy NO when price is moderately low (crowd expects NO)
"""

from __future__ import annotations

import time

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


def momentum_strategy(markets, yes_low, yes_high, no_low, no_high, min_vol):
    """
    Momentum: Bet WITH the crowd.
    - Buy YES when yes_low < price < yes_high
    - Buy NO when no_low < price < no_high
    """
    signals = []
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)
        
        if volume < min_vol:
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
        _, p_value = stats.ttest_1samp(returns, 0)
    else:
        p_value = 1.0
    
    mean_ret = np.mean(returns)
    std_ret = np.std(returns) if len(returns) > 1 else 1
    sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0
    
    return {
        "trades": len(returns),
        "win_rate": win_rate,
        "return": total_return,
        "sharpe": sharpe,
        "p_value": p_value,
        "final": capital,
    }


def walk_forward(markets, yes_low, yes_high, no_low, no_high, min_vol):
    n = len(markets)
    train = markets[:int(n * 0.6)]
    test = markets[int(n * 0.6):]
    
    train_signals = momentum_strategy(train, yes_low, yes_high, no_low, no_high, min_vol)
    test_signals = momentum_strategy(test, yes_low, yes_high, no_low, no_high, min_vol)
    
    train_result = backtest(train_signals)
    test_result = backtest(test_signals)
    
    if not train_result or not test_result:
        return None
    
    robust = (
        train_result["return"] > 0 and
        test_result["return"] > 0 and
        train_result["p_value"] < 0.10 and
        test_result["p_value"] < 0.25
    )
    
    return {
        "train": train_result,
        "test": test_result,
        "robust": robust,
    }


def run_momentum_search():
    print("=" * 70)
    print("MOMENTUM STRATEGY DEEP TEST")
    print("=" * 70)
    print("\nMomentum = Bet WITH the crowd on moderate prices")
    
    markets = fetch_markets()
    if len(markets) < 5000:
        print("Insufficient data")
        return
    
    configs = [
        {"name": "Original 60-85/15-40, v100", "yes": (0.60, 0.85), "no": (0.15, 0.40), "vol": 100},
        {"name": "Narrow 65-80/20-35, v100", "yes": (0.65, 0.80), "no": (0.20, 0.35), "vol": 100},
        {"name": "Narrow 65-80/20-35, v50", "yes": (0.65, 0.80), "no": (0.20, 0.35), "vol": 50},
        {"name": "Tight 68-78/22-32, v50", "yes": (0.68, 0.78), "no": (0.22, 0.32), "vol": 50},
        {"name": "Tight 70-80/20-30, v50", "yes": (0.70, 0.80), "no": (0.20, 0.30), "vol": 50},
        {"name": "Tight 70-80/20-30, v25", "yes": (0.70, 0.80), "no": (0.20, 0.30), "vol": 25},
        {"name": "High conf 75-90/10-25, v50", "yes": (0.75, 0.90), "no": (0.10, 0.25), "vol": 50},
        {"name": "High conf 75-90/10-25, v25", "yes": (0.75, 0.90), "no": (0.10, 0.25), "vol": 25},
        {"name": "Very high 80-92/08-20, v25", "yes": (0.80, 0.92), "no": (0.08, 0.20), "vol": 25},
        {"name": "Very high 80-92/08-20, v50", "yes": (0.80, 0.92), "no": (0.08, 0.20), "vol": 50},
        {"name": "Moderate 55-75/25-45, v50", "yes": (0.55, 0.75), "no": (0.25, 0.45), "vol": 50},
        {"name": "Moderate 55-75/25-45, v100", "yes": (0.55, 0.75), "no": (0.25, 0.45), "vol": 100},
        {"name": "Wide 55-85/15-45, v50", "yes": (0.55, 0.85), "no": (0.15, 0.45), "vol": 50},
        {"name": "Extreme 85-95/05-15, v25", "yes": (0.85, 0.95), "no": (0.05, 0.15), "vol": 25},
        {"name": "Balanced 60-75/25-40, v75", "yes": (0.60, 0.75), "no": (0.25, 0.40), "vol": 75},
        {"name": "Balanced 62-78/22-38, v50", "yes": (0.62, 0.78), "no": (0.22, 0.38), "vol": 50},
        {"name": "Conservative 70-85/15-30, v100", "yes": (0.70, 0.85), "no": (0.15, 0.30), "vol": 100},
        {"name": "Conservative 72-88/12-28, v75", "yes": (0.72, 0.88), "no": (0.12, 0.28), "vol": 75},
    ]
    
    print(f"\nTesting {len(configs)} momentum configurations...")
    print(f"\n{'Config':<35} {'Train':>8} {'Test':>8} {'WinR':>6} {'Robust':>7}")
    print("-" * 70)
    
    results = []
    for cfg in configs:
        result = walk_forward(
            markets,
            cfg["yes"][0], cfg["yes"][1],
            cfg["no"][0], cfg["no"][1],
            cfg["vol"],
        )
        
        if not result:
            print(f"{cfg['name']:<35} {'N/A':>8} {'N/A':>8} {'N/A':>6} {'N/A':>7}")
            continue
        
        train_ret = result["train"]["return"]
        test_ret = result["test"]["return"]
        test_wr = result["test"]["win_rate"]
        robust = "YES" if result["robust"] else "no"
        
        print(f"{cfg['name']:<35} {train_ret:>+7.1%} {test_ret:>+7.1%} "
              f"{test_wr:>5.0%} {robust:>7}")
        
        results.append((cfg, result))
    
    robust_results = [(c, r) for c, r in results if r["robust"]]
    
    print("\n" + "=" * 70)
    print("ROBUST MOMENTUM STRATEGIES")
    print("=" * 70)
    
    if not robust_results:
        print("\nNo robust momentum strategies found.")
        
        positive_test = [(c, r) for c, r in results 
                         if r and r["test"]["return"] > 0]
        
        if positive_test:
            positive_test.sort(key=lambda x: x[1]["test"]["return"], reverse=True)
            print("\nBest non-robust (positive test return):")
            for cfg, r in positive_test[:5]:
                print(f"  {cfg['name']}: test={r['test']['return']:+.2%}, "
                      f"p={r['test']['p_value']:.3f}")
    else:
        robust_results.sort(key=lambda x: x[1]["test"]["return"], reverse=True)
        
        print(f"\nFound {len(robust_results)} robust strategies:")
        for cfg, r in robust_results:
            print(f"\n  {cfg['name']}:")
            print(f"    YES range: {cfg['yes'][0]:.0%} - {cfg['yes'][1]:.0%}")
            print(f"    NO range:  {cfg['no'][0]:.0%} - {cfg['no'][1]:.0%}")
            print(f"    Min volume: {cfg['vol']}")
            print(f"    Train: {r['train']['return']:+.2%} "
                  f"(p={r['train']['p_value']:.4f})")
            print(f"    Test:  {r['test']['return']:+.2%} "
                  f"(p={r['test']['p_value']:.4f})")
            print(f"    Test win rate: {r['test']['win_rate']:.1%}")
        
        best_cfg, best = robust_results[0]
        
        print("\n" + "=" * 70)
        print("DEPLOYMENT RECOMMENDATION")
        print("=" * 70)
        
        if best["test"]["return"] > 0.05 and best["test"]["p_value"] < 0.15:
            print(f"\n✓ DEPLOYABLE: {best_cfg['name']}")
            print(f"\n  Rules:")
            print(f"    - Buy YES when {best_cfg['yes'][0]:.0%} < price < {best_cfg['yes'][1]:.0%}")
            print(f"    - Buy NO when {best_cfg['no'][0]:.0%} < price < {best_cfg['no'][1]:.0%}")
            print(f"    - Require volume >= {best_cfg['vol']}")
            print(f"\n  Expected performance:")
            print(f"    - Win rate: ~{best['test']['win_rate']:.0%}")
            print(f"    - Return: ~{best['test']['return']:+.1%} per period")
            print(f"\n  Next steps:")
            print(f"    1. Paper trade for 2 weeks")
            print(f"    2. Start with $500-1000 if paper results hold")
            print(f"    3. Scale up gradually")
        else:
            print(f"\n~ MARGINAL: {best_cfg['name']}")
            print(f"  Test return: {best['test']['return']:+.2%}")
            print(f"  Paper trade for 4+ weeks before live")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    run_momentum_search()
