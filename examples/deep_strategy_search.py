"""
Deep Strategy Search - Finding Real Edge

Key insight from previous run:
- Strategies near 50% (0.50-0.65, 0.35-0.50) showed +20% test returns
- This suggests betting on "uncertain" markets may have edge

New hypotheses to test:
1. Near-50% markets are underpriced (uncertainty premium)
2. High volume = better calibrated prices
3. Time-to-expiration affects accuracy
4. Market category matters (crypto vs politics vs sports)
"""

from __future__ import annotations

import time
from collections import defaultdict

import httpx
import numpy as np
from scipy import stats


def fetch_markets_with_retry() -> list[dict]:
    """Fetch markets with rate limit handling."""
    print("Fetching maximum data...")
    client = httpx.Client(timeout=60.0)
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    all_markets = []
    cursor = None
    retries = 0
    
    while len(all_markets) < 15000 and retries < 10:
        params = {"limit": 200, "status": "settled"}
        if cursor:
            params["cursor"] = cursor
        
        try:
            response = client.get(f"{base_url}/markets", params=params)
            if response.status_code == 429:
                retries += 1
                time.sleep(3)
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
            time.sleep(2)
    
    client.close()
    print(f"  Total: {len(all_markets)} markets")
    return all_markets


def calculate_fee(price: float) -> float:
    if price <= 0 or price >= 1:
        return 0.0
    return max(0.01, np.ceil(0.07 * price * (1 - price) * 100) / 100)


def analyze_calibration(markets: list[dict]) -> dict:
    """Check if market prices are well-calibrated."""
    print("\nAnalyzing price calibration...")
    
    buckets = defaultdict(list)
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = 1 if m.get("result", "").lower() == "yes" else 0
        
        if 0.05 <= price <= 0.95:
            bucket = round(price, 1)
            buckets[bucket].append(result)
    
    print(f"\n{'Price':>6} {'Count':>6} {'Actual':>8} {'Expected':>8} {'Diff':>8}")
    print("-" * 45)
    
    calibration = {}
    for bucket in sorted(buckets.keys()):
        outcomes = buckets[bucket]
        if len(outcomes) < 20:
            continue
        actual = np.mean(outcomes)
        expected = bucket
        diff = actual - expected
        calibration[bucket] = {
            "count": len(outcomes),
            "actual": actual,
            "expected": expected,
            "diff": diff,
        }
        print(f"{bucket:>6.1f} {len(outcomes):>6} {actual:>7.1%} {expected:>7.1%} {diff:>+7.1%}")
    
    return calibration


def strategy_calibration_edge(markets: list[dict], calibration: dict) -> list[dict]:
    """
    Trade based on calibration errors.
    If actual > expected at price X, buy YES at price X.
    If actual < expected at price X, buy NO at price X.
    """
    signals = []
    
    edge_buckets = {}
    for bucket, data in calibration.items():
        if abs(data["diff"]) > 0.05 and data["count"] >= 30:
            edge_buckets[bucket] = data["diff"]
    
    print(f"\nCalibration edge buckets: {edge_buckets}")
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)
        
        if volume < 50:
            continue
        
        bucket = round(price, 1)
        if bucket not in edge_buckets:
            continue
        
        edge = edge_buckets[bucket]
        
        if edge > 0:
            cost = price + calculate_fee(price) + 0.01
            pnl = (1.0 - cost) if result else -cost
            signals.append({
                "price": price,
                "bet": "YES",
                "won": result,
                "pnl": pnl,
                "edge": edge,
            })
        else:
            cost = (1 - price) + calculate_fee(1 - price) + 0.01
            pnl = (1.0 - cost) if not result else -cost
            signals.append({
                "price": price,
                "bet": "NO",
                "won": not result,
                "pnl": pnl,
                "edge": edge,
            })
    
    return signals


def strategy_uncertainty_premium(markets: list[dict]) -> list[dict]:
    """
    Hypothesis: Markets near 50% have uncertainty premium.
    People avoid 50/50 bets, so they may be underpriced.
    Strategy: Always bet YES on 45-55% markets.
    """
    signals = []
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)
        
        if volume < 100:
            continue
        
        if 0.45 <= price <= 0.55:
            cost = price + calculate_fee(price) + 0.01
            pnl = (1.0 - cost) if result else -cost
            signals.append({
                "price": price,
                "bet": "YES",
                "won": result,
                "pnl": pnl,
            })
    
    return signals


def strategy_favorite_longshot(markets: list[dict]) -> list[dict]:
    """
    Favorite-longshot bias: Longshots are overpriced, favorites underpriced.
    Strategy: Bet on favorites (high probability events).
    """
    signals = []
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)
        
        if volume < 50:
            continue
        
        if 0.75 <= price <= 0.90:
            cost = price + calculate_fee(price) + 0.01
            pnl = (1.0 - cost) if result else -cost
            signals.append({
                "price": price,
                "bet": "YES_FAVORITE",
                "won": result,
                "pnl": pnl,
            })
        elif 0.10 <= price <= 0.25:
            cost = (1 - price) + calculate_fee(1 - price) + 0.01
            pnl = (1.0 - cost) if not result else -cost
            signals.append({
                "price": price,
                "bet": "NO_FAVORITE",
                "won": not result,
                "pnl": pnl,
            })
    
    return signals


def strategy_volume_signal(markets: list[dict]) -> list[dict]:
    """
    High volume = more information = better prices.
    Low volume = less efficient = potential edge.
    Strategy: Fade low-volume extreme prices.
    """
    signals = []
    
    volumes = [m.get("volume", 0) for m in markets if m.get("volume", 0) > 0]
    if not volumes:
        return signals
    
    median_vol = np.median(volumes)
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)
        
        if volume >= median_vol:
            continue
        
        if 0.55 <= price <= 0.70:
            cost = price + calculate_fee(price) + 0.01
            pnl = (1.0 - cost) if result else -cost
            signals.append({
                "price": price,
                "bet": "YES",
                "won": result,
                "pnl": pnl,
                "volume": volume,
            })
        elif 0.30 <= price <= 0.45:
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


def strategy_category_specific(markets: list[dict]) -> dict[str, list[dict]]:
    """
    Different categories may have different biases.
    Crypto traders vs political bettors vs sports fans.
    """
    by_category = defaultdict(list)
    
    for m in markets:
        ticker = m.get("ticker", "")
        
        if "BTC" in ticker or "ETH" in ticker or "CRYPTO" in ticker:
            category = "crypto"
        elif "PRES" in ticker or "ELECT" in ticker or "TRUMP" in ticker:
            category = "politics"
        elif "NFL" in ticker or "NBA" in ticker or "NHL" in ticker:
            category = "sports"
        else:
            category = "other"
        
        by_category[category].append(m)
    
    results = {}
    for category, cat_markets in by_category.items():
        signals = []
        for m in cat_markets:
            price = m.get("last_price", 0) / 100
            result = m.get("result", "").lower() == "yes"
            volume = m.get("volume", 0)
            
            if volume < 25:
                continue
            
            if 0.50 <= price <= 0.70:
                cost = price + calculate_fee(price) + 0.01
                pnl = (1.0 - cost) if result else -cost
                signals.append({
                    "price": price,
                    "won": result,
                    "pnl": pnl,
                })
        
        results[category] = signals
    
    return results


def backtest(signals: list[dict], name: str = "") -> dict:
    """Backtest and return stats."""
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
    losses = [p for p in pnls if p < 0]
    
    total_return = (capital - initial) / initial
    win_rate = len(wins) / len(pnls) if pnls else 0
    
    if len(returns) > 5:
        t_stat, p_value = stats.ttest_1samp(returns, 0)
    else:
        t_stat, p_value = 0, 1
    
    mean_ret = np.mean(returns)
    std_ret = np.std(returns) if len(returns) > 1 else 1
    sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0
    
    return {
        "name": name,
        "trades": len(returns),
        "win_rate": win_rate,
        "return": total_return,
        "sharpe": sharpe,
        "t_stat": t_stat,
        "p_value": p_value,
        "significant": p_value < 0.05 and total_return > 0,
    }


def walk_forward(markets: list[dict], strategy_fn, name: str) -> dict:
    """Walk-forward validation."""
    n = len(markets)
    split = int(n * 0.6)
    
    train = markets[:split]
    test = markets[split:]
    
    train_signals = strategy_fn(train)
    test_signals = strategy_fn(test)
    
    train_result = backtest(train_signals, f"{name}_train")
    test_result = backtest(test_signals, f"{name}_test")
    
    if not train_result or not test_result:
        return None
    
    return {
        "name": name,
        "train_trades": train_result["trades"],
        "test_trades": test_result["trades"],
        "train_return": train_result["return"],
        "test_return": test_result["return"],
        "train_winrate": train_result["win_rate"],
        "test_winrate": test_result["win_rate"],
        "train_pvalue": train_result["p_value"],
        "test_pvalue": test_result["p_value"],
        "robust": (
            train_result["return"] > 0 and
            test_result["return"] > 0 and
            train_result["p_value"] < 0.10
        ),
    }


def run_deep_search():
    print("=" * 70)
    print("DEEP STRATEGY SEARCH")
    print("=" * 70)
    
    markets = fetch_markets_with_retry()
    if len(markets) < 1000:
        print("Insufficient data")
        return
    
    calibration = analyze_calibration(markets)
    
    print("\n" + "=" * 70)
    print("TESTING STRATEGIES")
    print("=" * 70)
    
    strategies = [
        ("Uncertainty Premium", strategy_uncertainty_premium),
        ("Favorite-Longshot", strategy_favorite_longshot),
        ("Volume Signal", strategy_volume_signal),
    ]
    
    results = []
    for name, fn in strategies:
        result = walk_forward(markets, fn, name)
        if result:
            results.append(result)
            status = "ROBUST" if result["robust"] else "weak"
            print(f"\n{name}:")
            print(f"  Train: {result['train_trades']} trades, "
                  f"{result['train_return']:+.2%} return, "
                  f"p={result['train_pvalue']:.3f}")
            print(f"  Test:  {result['test_trades']} trades, "
                  f"{result['test_return']:+.2%} return, "
                  f"p={result['test_pvalue']:.3f}")
            print(f"  Status: {status}")
    
    print("\n" + "=" * 70)
    print("CATEGORY ANALYSIS")
    print("=" * 70)
    
    cat_results = strategy_category_specific(markets)
    for category, signals in cat_results.items():
        result = backtest(signals, category)
        if result:
            sig = "*" if result["significant"] else ""
            print(f"  {category:12} | {result['trades']:>4} trades | "
                  f"{result['win_rate']:>5.1%} win | "
                  f"{result['return']:>+6.2%} {sig}")
    
    print("\n" + "=" * 70)
    print("CALIBRATION-BASED STRATEGY")
    print("=" * 70)
    
    n = len(markets)
    train_markets = markets[:int(n * 0.6)]
    test_markets = markets[int(n * 0.6):]
    
    train_cal = {}
    buckets = defaultdict(list)
    for m in train_markets:
        price = m.get("last_price", 0) / 100
        result = 1 if m.get("result", "").lower() == "yes" else 0
        if 0.05 <= price <= 0.95:
            bucket = round(price, 1)
            buckets[bucket].append(result)
    
    for bucket in buckets:
        if len(buckets[bucket]) >= 30:
            actual = np.mean(buckets[bucket])
            train_cal[bucket] = {
                "count": len(buckets[bucket]),
                "actual": actual,
                "expected": bucket,
                "diff": actual - bucket,
            }
    
    def cal_strategy(mkts):
        return strategy_calibration_edge(mkts, train_cal)
    
    cal_result = walk_forward(markets, cal_strategy, "Calibration Edge")
    if cal_result:
        print(f"\nCalibration Edge Strategy:")
        print(f"  Train: {cal_result['train_return']:+.2%}")
        print(f"  Test:  {cal_result['test_return']:+.2%}")
        print(f"  Robust: {cal_result['robust']}")
    
    robust = [r for r in results if r["robust"]]
    
    print("\n" + "=" * 70)
    print("FINAL RESULTS")
    print("=" * 70)
    
    if robust:
        print(f"\nFound {len(robust)} robust strategies!")
        for r in robust:
            print(f"\n  {r['name']}:")
            print(f"    Train: {r['train_return']:+.2%} ({r['train_trades']} trades)")
            print(f"    Test:  {r['test_return']:+.2%} ({r['test_trades']} trades)")
    else:
        print("\nNo robust strategies found with current data.")
        print("\nKey findings:")
        
        if calibration:
            miscal = [(k, v["diff"]) for k, v in calibration.items() 
                      if abs(v["diff"]) > 0.03]
            if miscal:
                print("\n  Calibration errors detected:")
                for bucket, diff in sorted(miscal, key=lambda x: abs(x[1]), reverse=True)[:5]:
                    direction = "underpriced" if diff > 0 else "overpriced"
                    print(f"    Price {bucket:.1f}: {direction} by {abs(diff):.1%}")
        
        print("\n  Recommendations:")
        print("    1. Focus on specific market categories you understand")
        print("    2. Look for cross-market arbitrage (Kalshi vs Polymarket)")
        print("    3. Consider market making if you have fast execution")
        print("    4. Build domain expertise for information edge")


if __name__ == "__main__":
    run_deep_search()
