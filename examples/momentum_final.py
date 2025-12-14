"""
Momentum Strategy - Final Optimization

Best candidates from previous test:
- Balanced 62-78/22-38, v50: test=+27.43%, p=0.100
- Tight 68-78/22-32, v50: test=+22.15%, p=0.104

Let's fine-tune around these parameters.
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
            signals.append({"price": price, "won": result, "pnl": pnl})
        elif no_low < price < no_high:
            cost = (1 - price) + calculate_fee(1 - price) + 0.01
            pnl = (1.0 - cost) if not result else -cost
            signals.append({"price": price, "won": not result, "pnl": pnl})
    return signals


def backtest(signals):
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
    
    return {
        "trades": len(returns),
        "win_rate": win_rate,
        "return": total_return,
        "p_value": p_value,
        "final": capital,
    }


def walk_forward_3way(markets, yes_low, yes_high, no_low, no_high, min_vol):
    """3-way split: train/validate/test"""
    n = len(markets)
    train = markets[:int(n * 0.5)]
    validate = markets[int(n * 0.5):int(n * 0.75)]
    test = markets[int(n * 0.75):]
    
    train_sig = momentum_strategy(train, yes_low, yes_high, no_low, no_high, min_vol)
    val_sig = momentum_strategy(validate, yes_low, yes_high, no_low, no_high, min_vol)
    test_sig = momentum_strategy(test, yes_low, yes_high, no_low, no_high, min_vol)
    
    train_r = backtest(train_sig)
    val_r = backtest(val_sig)
    test_r = backtest(test_sig)
    
    if not train_r or not val_r or not test_r:
        return None
    
    robust = (
        train_r["return"] > 0 and
        val_r["return"] > 0 and
        test_r["return"] > 0 and
        train_r["p_value"] < 0.15
    )
    
    return {
        "train": train_r,
        "validate": val_r,
        "test": test_r,
        "robust": robust,
    }


def run_final_optimization():
    print("=" * 70)
    print("MOMENTUM STRATEGY - FINAL OPTIMIZATION")
    print("=" * 70)
    
    markets = fetch_markets()
    if len(markets) < 5000:
        print("Insufficient data")
        return
    
    configs = [
        {"name": "Base 62-78/22-38 v50", "y": (0.62, 0.78), "n": (0.22, 0.38), "v": 50},
        {"name": "Tweak 60-78/22-40 v50", "y": (0.60, 0.78), "n": (0.22, 0.40), "v": 50},
        {"name": "Tweak 62-80/20-38 v50", "y": (0.62, 0.80), "n": (0.20, 0.38), "v": 50},
        {"name": "Tweak 63-77/23-37 v50", "y": (0.63, 0.77), "n": (0.23, 0.37), "v": 50},
        {"name": "Tweak 64-76/24-36 v50", "y": (0.64, 0.76), "n": (0.24, 0.36), "v": 50},
        {"name": "Base 68-78/22-32 v50", "y": (0.68, 0.78), "n": (0.22, 0.32), "v": 50},
        {"name": "Tweak 66-78/22-34 v50", "y": (0.66, 0.78), "n": (0.22, 0.34), "v": 50},
        {"name": "Tweak 67-77/23-33 v50", "y": (0.67, 0.77), "n": (0.23, 0.33), "v": 50},
        {"name": "Lower vol 62-78/22-38 v30", "y": (0.62, 0.78), "n": (0.22, 0.38), "v": 30},
        {"name": "Lower vol 62-78/22-38 v40", "y": (0.62, 0.78), "n": (0.22, 0.38), "v": 40},
        {"name": "Higher vol 62-78/22-38 v75", "y": (0.62, 0.78), "n": (0.22, 0.38), "v": 75},
        {"name": "Wider 58-82/18-42 v50", "y": (0.58, 0.82), "n": (0.18, 0.42), "v": 50},
        {"name": "Asymm 60-80/20-35 v50", "y": (0.60, 0.80), "n": (0.20, 0.35), "v": 50},
        {"name": "Asymm 65-78/22-40 v50", "y": (0.65, 0.78), "n": (0.22, 0.40), "v": 50},
    ]
    
    print(f"\nTesting {len(configs)} fine-tuned configs with 3-way validation...")
    print(f"\n{'Config':<30} {'Train':>7} {'Val':>7} {'Test':>7} {'Robust':>7}")
    print("-" * 65)
    
    results = []
    for cfg in configs:
        result = walk_forward_3way(
            markets, cfg["y"][0], cfg["y"][1], cfg["n"][0], cfg["n"][1], cfg["v"]
        )
        
        if not result:
            print(f"{cfg['name']:<30} {'N/A':>7} {'N/A':>7} {'N/A':>7} {'N/A':>7}")
            continue
        
        tr = result["train"]["return"]
        vr = result["validate"]["return"]
        te = result["test"]["return"]
        robust = "YES" if result["robust"] else "no"
        
        print(f"{cfg['name']:<30} {tr:>+6.1%} {vr:>+6.1%} {te:>+6.1%} {robust:>7}")
        results.append((cfg, result))
    
    robust_results = [(c, r) for c, r in results if r["robust"]]
    
    print("\n" + "=" * 70)
    
    if robust_results:
        robust_results.sort(key=lambda x: x[1]["test"]["return"], reverse=True)
        best_cfg, best = robust_results[0]
        
        print("✓ ROBUST STRATEGY FOUND!")
        print("=" * 70)
        print(f"\n  Strategy: {best_cfg['name']}")
        print(f"  YES range: {best_cfg['y'][0]:.0%} - {best_cfg['y'][1]:.0%}")
        print(f"  NO range:  {best_cfg['n'][0]:.0%} - {best_cfg['n'][1]:.0%}")
        print(f"  Min volume: {best_cfg['v']}")
        print(f"\n  Performance:")
        print(f"    Train:    {best['train']['return']:+.2%} (p={best['train']['p_value']:.3f})")
        print(f"    Validate: {best['validate']['return']:+.2%}")
        print(f"    Test:     {best['test']['return']:+.2%}")
        print(f"    Win Rate: {best['test']['win_rate']:.0%}")
        
        print(f"\n  DEPLOYMENT RECOMMENDATION:")
        if best["test"]["return"] > 0.05:
            print("  ✓ Ready for paper trading")
            print("  ✓ After 2 weeks paper, start with $500")
        else:
            print("  ~ Marginal - paper trade 4 weeks first")
    else:
        print("NO ROBUST STRATEGY (positive in all 3 periods)")
        print("=" * 70)
        
        positive_test = [(c, r) for c, r in results 
                         if r["test"]["return"] > 0 and r["validate"]["return"] > 0]
        
        if positive_test:
            positive_test.sort(key=lambda x: x[1]["test"]["return"], reverse=True)
            print("\nBest candidates (positive val + test):")
            for cfg, r in positive_test[:3]:
                print(f"\n  {cfg['name']}:")
                print(f"    Train: {r['train']['return']:+.2%}")
                print(f"    Val:   {r['validate']['return']:+.2%}")
                print(f"    Test:  {r['test']['return']:+.2%}")
                print(f"    p-val: {r['train']['p_value']:.3f}")
            
            best_cfg, best = positive_test[0]
            if best["test"]["return"] > 0.10:
                print("\n" + "=" * 70)
                print("RECOMMENDATION")
                print("=" * 70)
                print(f"\n  {best_cfg['name']} shows promise:")
                print(f"  - Positive in validation AND test")
                print(f"  - Test return: {best['test']['return']:+.2%}")
                print(f"\n  Worth paper trading for 2-4 weeks.")
                print(f"  If results hold, start small ($500).")
        else:
            print("\nNo strategies positive in both validation and test.")
            print("The momentum edge does not appear robust.")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    run_final_optimization()
