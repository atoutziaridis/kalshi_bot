"""
OPTIMAL RANGE FINDER - Final Comprehensive Test

Based on regime analysis findings:
- NO 22-28%: 81.3% win rate (BEST)
- NO 28-34%: 73.1% win rate
- NO 34-40%: 65.3% win rate (LOSES MONEY)

This test will:
1. Test narrow NO ranges to find optimal bounds
2. Test YES ranges separately
3. Use 30K+ markets for large sample size
4. Apply both chronological and random validation
5. Require statistical significance (p < 0.10)
6. Report final deployable strategy
"""

from __future__ import annotations

import time

import httpx
import numpy as np
from scipy import stats


def fetch_markets(max_markets: int = 30000) -> list[dict]:
    """Fetch settled markets."""
    print(f"Fetching {max_markets} settled markets...")
    client = httpx.Client(timeout=60.0)
    base_url = "https://api.elections.kalshi.com/trade-api/v2"

    all_markets = []
    cursor = None
    retries = 0

    while len(all_markets) < max_markets and retries < 30:
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
            if len(all_markets) % 2000 == 0:
                print(f"  ...{len(all_markets)} markets")
        except Exception:
            retries += 1
            time.sleep(1)

    client.close()
    print(f"  Total: {len(all_markets)} markets")
    return all_markets


def calculate_fee(price: float) -> float:
    """Kalshi fee."""
    if price <= 0 or price >= 1:
        return 0.0
    return max(0.01, 0.07 * price * (1 - price))


def generate_signals(
    markets: list[dict],
    yes_low: float,
    yes_high: float,
    no_low: float,
    no_high: float,
    min_volume: int
) -> list[dict]:
    """Generate signals."""
    signals = []

    for m in markets:
        last_price = m.get("last_price", 0)
        if not last_price:
            continue

        price = last_price / 100.0
        volume = m.get("volume", 0) or 0
        result = m.get("result", "").lower() == "yes"

        if volume < min_volume:
            continue

        if yes_low < price < yes_high:
            fee = calculate_fee(price)
            cost = price + fee + 0.01
            if cost < 1.0:
                pnl = (1.0 - cost) if result else -cost
                signals.append({
                    "won": result,
                    "pnl": pnl,
                    "price": price,
                    "side": "YES"
                })

        elif no_low < price < no_high:
            no_price = 1 - price
            fee = calculate_fee(no_price)
            cost = no_price + fee + 0.01
            if cost < 1.0:
                pnl = (1.0 - cost) if not result else -cost
                signals.append({
                    "won": not result,
                    "pnl": pnl,
                    "price": price,
                    "side": "NO"
                })

    return signals


def backtest(signals: list[dict], initial: float = 10000) -> dict | None:
    """Backtest with position sizing."""
    if len(signals) < 20:
        return None

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

    wins = [s["pnl"] for s in signals[:len(returns)] if s["pnl"] > 0]
    win_rate = len(wins) / len(returns) if returns else 0

    _, p_val = stats.ttest_1samp(returns, 0) if len(returns) > 5 else (0, 1.0)

    sharpe = 0
    if len(returns) > 1 and np.std(returns) > 0:
        sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252)

    return {
        "trades": len(returns),
        "return": (capital - initial) / initial,
        "win_rate": win_rate,
        "p_value": p_val,
        "sharpe": sharpe,
        "final": capital,
    }


def test_config(markets: list[dict], config: dict) -> dict:
    """Test configuration with train/test split."""
    n = len(markets)
    train_end = int(n * 0.6)

    train = markets[:train_end]
    test = markets[train_end:]

    train_sig = generate_signals(train, **config)
    test_sig = generate_signals(test, **config)

    return {
        "train": backtest(train_sig),
        "test": backtest(test_sig),
    }


def random_split_test(markets: list[dict], config: dict, n_splits: int = 10):
    """Multiple random splits."""
    test_returns = []
    test_win_rates = []

    for seed in range(n_splits):
        np.random.seed(seed * 42)
        n = len(markets)
        indices = np.random.permutation(n)
        split = int(n * 0.6)

        train_idx = indices[:split]
        test_idx = indices[split:]

        train = [markets[i] for i in train_idx]
        test = [markets[i] for i in test_idx]

        train_sig = generate_signals(train, **config)
        test_sig = generate_signals(test, **config)

        train_result = backtest(train_sig)
        test_result = backtest(test_sig)

        if test_result:
            test_returns.append(test_result["return"])
            test_win_rates.append(test_result["win_rate"])

    if test_returns:
        return {
            "avg_return": np.mean(test_returns),
            "median_return": np.median(test_returns),
            "avg_win_rate": np.mean(test_win_rates),
            "positive_splits": sum(1 for r in test_returns if r > 0),
            "total_splits": len(test_returns),
        }
    return None


def run_optimal_range_finder():
    print("=" * 80)
    print("OPTIMAL RANGE FINDER - Final Comprehensive Test")
    print("=" * 80)

    markets = fetch_markets(30000)

    if len(markets) < 10000:
        print("Insufficient data")
        return

    print(f"\nTesting on {len(markets)} markets")

    print("\n" + "=" * 80)
    print("PHASE 1: NARROW NO RANGE OPTIMIZATION")
    print("=" * 80)
    print("\nTesting narrow NO ranges (based on 81% win rate at 22-28%):")

    no_configs = [
        {"name": "NO 22-26%", "no_low": 0.22, "no_high": 0.26},
        {"name": "NO 22-28%", "no_low": 0.22, "no_high": 0.28},
        {"name": "NO 22-30%", "no_low": 0.22, "no_high": 0.30},
        {"name": "NO 23-29%", "no_low": 0.23, "no_high": 0.29},
        {"name": "NO 24-30%", "no_low": 0.24, "no_high": 0.30},
        {"name": "NO 24-32%", "no_low": 0.24, "no_high": 0.32},
        {"name": "NO 22-32%", "no_low": 0.22, "no_high": 0.32},
        {"name": "NO 22-34%", "no_low": 0.22, "no_high": 0.34},
    ]

    no_results = []

    for cfg in no_configs:
        config = {
            "yes_low": 0.65, "yes_high": 0.78,
            "no_low": cfg["no_low"], "no_high": cfg["no_high"],
            "min_volume": 166
        }

        result = test_config(markets, config)
        random_result = random_split_test(markets, config, n_splits=10)

        train = result["train"]
        test = result["test"]

        if train and test and random_result:
            print(f"\n{cfg['name']}:")
            print(f"  Chrono Train: {train['trades']:3} trades, "
                  f"{train['return']:+7.2%}, p={train['p_value']:.4f}")
            print(f"  Chrono Test:  {test['trades']:3} trades, "
                  f"{test['return']:+7.2%}, WR={test['win_rate']:.1%}")
            print(f"  Random Avg:   {random_result['avg_return']:+7.2%}, "
                  f"WR={random_result['avg_win_rate']:.1%}, "
                  f"{random_result['positive_splits']}/10 positive")

            no_results.append({
                "config": cfg,
                "chrono": result,
                "random": random_result,
            })

    print("\n" + "=" * 80)
    print("PHASE 2: YES RANGE OPTIMIZATION")
    print("=" * 80)
    print("\nTesting YES ranges:")

    yes_configs = [
        {"name": "YES 65-75%", "yes_low": 0.65, "yes_high": 0.75},
        {"name": "YES 65-78%", "yes_low": 0.65, "yes_high": 0.78},
        {"name": "YES 67-78%", "yes_low": 0.67, "yes_high": 0.78},
        {"name": "YES 68-76%", "yes_low": 0.68, "yes_high": 0.76},
        {"name": "YES 70-78%", "yes_low": 0.70, "yes_high": 0.78},
    ]

    yes_results = []

    for cfg in yes_configs:
        config = {
            "yes_low": cfg["yes_low"], "yes_high": cfg["yes_high"],
            "no_low": 0.22, "no_high": 0.28,
            "min_volume": 166
        }

        result = test_config(markets, config)
        random_result = random_split_test(markets, config, n_splits=10)

        train = result["train"]
        test = result["test"]

        if train and test and random_result:
            print(f"\n{cfg['name']}:")
            print(f"  Chrono Train: {train['trades']:3} trades, "
                  f"{train['return']:+7.2%}, p={train['p_value']:.4f}")
            print(f"  Chrono Test:  {test['trades']:3} trades, "
                  f"{test['return']:+7.2%}, WR={test['win_rate']:.1%}")
            print(f"  Random Avg:   {random_result['avg_return']:+7.2%}, "
                  f"WR={random_result['avg_win_rate']:.1%}, "
                  f"{random_result['positive_splits']}/10 positive")

            yes_results.append({
                "config": cfg,
                "chrono": result,
                "random": random_result,
            })

    print("\n" + "=" * 80)
    print("PHASE 3: COMBINED OPTIMAL STRATEGY")
    print("=" * 80)

    best_no = max(no_results, key=lambda x: x["random"]["avg_return"])
    best_yes = max(yes_results, key=lambda x: x["random"]["avg_return"])

    print(f"\nBest NO range: {best_no['config']['name']}")
    print(f"  Random avg return: {best_no['random']['avg_return']:+.2%}")
    print(f"  Random avg win rate: {best_no['random']['avg_win_rate']:.1%}")

    print(f"\nBest YES range: {best_yes['config']['name']}")
    print(f"  Random avg return: {best_yes['random']['avg_return']:+.2%}")
    print(f"  Random avg win rate: {best_yes['random']['avg_win_rate']:.1%}")

    combined_config = {
        "yes_low": best_yes['config']['yes_low'],
        "yes_high": best_yes['config']['yes_high'],
        "no_low": best_no['config']['no_low'],
        "no_high": best_no['config']['no_high'],
        "min_volume": 166
    }

    print(f"\nTesting combined optimal strategy:")
    combined_result = test_config(markets, combined_config)
    combined_random = random_split_test(markets, combined_config, n_splits=20)

    train = combined_result["train"]
    test = combined_result["test"]

    print(f"\n  Chrono Train: {train['trades']:3} trades, "
          f"{train['return']:+7.2%}, p={train['p_value']:.4f}")
    print(f"  Chrono Test:  {test['trades']:3} trades, "
          f"{test['return']:+7.2%}, WR={test['win_rate']:.1%}")
    print(f"  Random Avg (20 splits): {combined_random['avg_return']:+7.2%}, "
          f"WR={combined_random['avg_win_rate']:.1%}")
    print(f"  Positive splits: {combined_random['positive_splits']}/20")

    print("\n" + "=" * 80)
    print("FINAL RECOMMENDATION")
    print("=" * 80)

    is_robust = (
        train["p_value"] < 0.10 and
        combined_random["avg_return"] > 0.10 and
        combined_random["positive_splits"] >= 15
    )

    if is_robust:
        print("\n✓ ROBUST STRATEGY FOUND")
        print(f"\nOPTIMAL MOMENTUM STRATEGY:")
        print(f"  YES range: {best_yes['config']['yes_low']:.0%} - "
              f"{best_yes['config']['yes_high']:.0%}")
        print(f"  NO range:  {best_no['config']['no_low']:.0%} - "
              f"{best_no['config']['no_high']:.0%}")
        print(f"  Min volume: 166")
        print(f"\nExpected Performance:")
        print(f"  Average return: {combined_random['avg_return']:+.2%}")
        print(f"  Win rate: {combined_random['avg_win_rate']:.1%}")
        print(f"  Consistency: {combined_random['positive_splits']}/20 positive")
        print(f"\n✓ RECOMMENDATION: Paper trade for 2 weeks, then deploy $500")
    else:
        print("\n~ MARGINAL STRATEGY")
        print(f"\nBest configuration found:")
        print(f"  YES: {best_yes['config']['yes_low']:.0%}-"
              f"{best_yes['config']['yes_high']:.0%}")
        print(f"  NO: {best_no['config']['no_low']:.0%}-"
              f"{best_no['config']['no_high']:.0%}")
        print(f"  Avg return: {combined_random['avg_return']:+.2%}")
        print(f"  Win rate: {combined_random['avg_win_rate']:.1%}")
        print(f"\n⚠️  RECOMMENDATION: Paper trade for 4+ weeks before live")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    run_optimal_range_finder()
