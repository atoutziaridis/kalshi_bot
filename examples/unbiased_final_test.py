"""
UNBIASED FINAL STRATEGY TEST

This test avoids overfitting by:
1. NO parameter optimization on test data
2. Using multiple random train/test splits
3. Testing ONE pre-defined strategy (no cherry-picking)
4. Reporting confidence intervals
5. Using bootstrap resampling for robustness

The strategy is fixed BEFORE looking at results:
- Momentum: Bet WITH crowd on moderate prices
- YES when 65-78%, NO when 22-40%, volume >= 50
"""

from __future__ import annotations

import time

import httpx
import numpy as np
from scipy import stats


STRATEGY_PARAMS = {
    "yes_low": 0.65,
    "yes_high": 0.78,
    "no_low": 0.22,
    "no_high": 0.40,
    "min_volume": 50,
}


def fetch_markets() -> list[dict]:
    print("Fetching all available markets...")
    client = httpx.Client(timeout=60.0)
    base_url = "https://api.elections.kalshi.com/trade-api/v2"

    all_markets = []
    cursor = None
    retries = 0

    while len(all_markets) < 25000 and retries < 25:
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
    print(f"  {len(all_markets)} markets fetched")
    return all_markets


def calculate_fee(price: float) -> float:
    if price <= 0 or price >= 1:
        return 0.0
    return max(0.01, np.ceil(0.07 * price * (1 - price) * 100) / 100)


def generate_signals(markets: list[dict]) -> list[dict]:
    """Generate signals using FIXED strategy parameters."""
    signals = []
    p = STRATEGY_PARAMS

    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)

        if volume < p["min_volume"]:
            continue

        if p["yes_low"] < price < p["yes_high"]:
            cost = price + calculate_fee(price) + 0.01
            pnl = (1.0 - cost) if result else -cost
            signals.append({"price": price, "won": result, "pnl": pnl, "side": "YES"})
        elif p["no_low"] < price < p["no_high"]:
            cost = (1 - price) + calculate_fee(1 - price) + 0.01
            pnl = (1.0 - cost) if not result else -cost
            signals.append({"price": price, "won": not result, "pnl": pnl, "side": "NO"})

    return signals


def backtest_signals(signals: list[dict]) -> dict:
    if not signals:
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

    if len(returns) < 5:
        return None

    pnls = [s["pnl"] for s in signals[:len(returns)]]
    wins = [p for p in pnls if p > 0]

    total_return = (capital - initial) / initial
    win_rate = len(wins) / len(pnls) if pnls else 0

    _, p_value = stats.ttest_1samp(returns, 0) if len(returns) > 5 else (0, 1.0)

    return {
        "trades": len(returns),
        "win_rate": win_rate,
        "return": total_return,
        "p_value": p_value,
        "returns": returns,
    }


def bootstrap_test(returns: list[float], n_bootstrap: int = 5000) -> dict:
    """Bootstrap to get confidence intervals."""
    if len(returns) < 10:
        return None

    bootstrap_means = []
    for _ in range(n_bootstrap):
        sample = np.random.choice(returns, size=len(returns), replace=True)
        bootstrap_means.append(np.mean(sample))

    ci_lower = np.percentile(bootstrap_means, 2.5)
    ci_upper = np.percentile(bootstrap_means, 97.5)
    p_positive = np.mean([m > 0 for m in bootstrap_means])

    return {
        "mean": np.mean(returns),
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "p_positive": p_positive,
    }


def multiple_split_test(markets: list[dict], n_splits: int = 10) -> list[dict]:
    """Test on multiple random train/test splits."""
    results = []
    n = len(markets)

    for i in range(n_splits):
        np.random.seed(i * 42)
        indices = np.random.permutation(n)
        split = int(n * 0.5)

        train_idx = indices[:split]
        test_idx = indices[split:]

        train_markets = [markets[j] for j in train_idx]
        test_markets = [markets[j] for j in test_idx]

        train_signals = generate_signals(train_markets)
        test_signals = generate_signals(test_markets)

        train_result = backtest_signals(train_signals)
        test_result = backtest_signals(test_signals)

        if train_result and test_result:
            results.append({
                "split": i,
                "train_return": train_result["return"],
                "test_return": test_result["return"],
                "train_trades": train_result["trades"],
                "test_trades": test_result["trades"],
                "test_win_rate": test_result["win_rate"],
            })

    return results


def run_unbiased_test():
    print("=" * 70)
    print("UNBIASED FINAL STRATEGY TEST")
    print("=" * 70)
    print("\nStrategy (FIXED before testing):")
    print(f"  Buy YES when {STRATEGY_PARAMS['yes_low']:.0%} < price < {STRATEGY_PARAMS['yes_high']:.0%}")
    print(f"  Buy NO when {STRATEGY_PARAMS['no_low']:.0%} < price < {STRATEGY_PARAMS['no_high']:.0%}")
    print(f"  Min volume: {STRATEGY_PARAMS['min_volume']}")

    markets = fetch_markets()
    if len(markets) < 5000:
        print("Insufficient data")
        return

    print("\n" + "=" * 70)
    print("TEST 1: CHRONOLOGICAL SPLIT (50/50)")
    print("=" * 70)
    print("Using first 50% as train, last 50% as test (no lookahead)")

    n = len(markets)
    train_markets = markets[:n // 2]
    test_markets = markets[n // 2:]

    train_signals = generate_signals(train_markets)
    test_signals = generate_signals(test_markets)

    train_result = backtest_signals(train_signals)
    test_result = backtest_signals(test_signals)

    if train_result and test_result:
        print(f"\nTrain: {train_result['trades']} trades, {train_result['return']:+.2%} return")
        print(f"Test:  {test_result['trades']} trades, {test_result['return']:+.2%} return")
        print(f"Test win rate: {test_result['win_rate']:.1%}")
        print(f"Test p-value: {test_result['p_value']:.4f}")

    print("\n" + "=" * 70)
    print("TEST 2: MULTIPLE RANDOM SPLITS (10 iterations)")
    print("=" * 70)
    print("Testing on 10 different random 50/50 splits")

    split_results = multiple_split_test(markets, n_splits=10)

    if split_results:
        test_returns = [r["test_return"] for r in split_results]
        train_returns = [r["train_return"] for r in split_results]

        print(f"\n{'Split':<6} {'Train':>10} {'Test':>10}")
        print("-" * 30)
        for r in split_results:
            print(f"{r['split']:<6} {r['train_return']:>+9.2%} {r['test_return']:>+9.2%}")

        print(f"\nTest Return Statistics:")
        print(f"  Mean:   {np.mean(test_returns):+.2%}")
        print(f"  Median: {np.median(test_returns):+.2%}")
        print(f"  Std:    {np.std(test_returns):.2%}")
        print(f"  Min:    {np.min(test_returns):+.2%}")
        print(f"  Max:    {np.max(test_returns):+.2%}")

        positive_tests = sum(1 for r in test_returns if r > 0)
        print(f"\n  Positive test returns: {positive_tests}/{len(test_returns)}")

    print("\n" + "=" * 70)
    print("TEST 3: BOOTSTRAP CONFIDENCE INTERVAL")
    print("=" * 70)

    all_signals = generate_signals(markets)
    all_result = backtest_signals(all_signals)

    if all_result:
        bootstrap = bootstrap_test(all_result["returns"], n_bootstrap=10000)

        if bootstrap:
            print(f"\nFull dataset: {all_result['trades']} trades")
            print(f"Mean per-trade return: {bootstrap['mean']:.4f}")
            print(f"95% CI: [{bootstrap['ci_lower']:.4f}, {bootstrap['ci_upper']:.4f}]")
            print(f"Probability of positive mean: {bootstrap['p_positive']:.1%}")

            ci_excludes_zero = bootstrap['ci_lower'] > 0 or bootstrap['ci_upper'] < 0

    print("\n" + "=" * 70)
    print("FINAL VERDICT")
    print("=" * 70)

    is_robust = False
    reasons = []

    if test_result and test_result["return"] > 0:
        reasons.append("✓ Positive chronological test return")
    else:
        reasons.append("✗ Negative chronological test return")

    if split_results:
        positive_pct = positive_tests / len(test_returns)
        if positive_pct >= 0.7:
            reasons.append(f"✓ {positive_pct:.0%} of random splits positive")
        else:
            reasons.append(f"✗ Only {positive_pct:.0%} of random splits positive")

    if bootstrap and bootstrap["ci_lower"] > 0:
        reasons.append("✓ 95% CI excludes zero (significant)")
        is_robust = True
    elif bootstrap and bootstrap["p_positive"] > 0.9:
        reasons.append(f"~ {bootstrap['p_positive']:.0%} probability positive (marginal)")
    else:
        reasons.append("✗ 95% CI includes zero (not significant)")

    if test_result and test_result["p_value"] < 0.05:
        reasons.append(f"✓ p-value {test_result['p_value']:.4f} < 0.05")
        is_robust = True
    elif test_result and test_result["p_value"] < 0.10:
        reasons.append(f"~ p-value {test_result['p_value']:.4f} < 0.10 (marginal)")
    else:
        reasons.append(f"✗ p-value {test_result['p_value']:.4f} >= 0.10")

    print("\nEvidence:")
    for r in reasons:
        print(f"  {r}")

    print("\n" + "-" * 70)

    if is_robust:
        print("\n✓ STRATEGY IS STATISTICALLY ROBUST")
        print("\n  Recommendation: Paper trade for 2 weeks, then deploy with $500")
    elif test_result and test_result["return"] > 0 and positive_tests >= 6:
        print("\n~ STRATEGY SHOWS PROMISE BUT NOT STATISTICALLY SIGNIFICANT")
        print("\n  Recommendation: Paper trade for 4+ weeks before any live trading")
        print("  The edge exists but may be too small or unstable")
    else:
        print("\n✗ STRATEGY DOES NOT SHOW ROBUST EDGE")
        print("\n  Recommendation: Do NOT deploy")
        print("  The returns are likely due to chance")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    run_unbiased_test()
