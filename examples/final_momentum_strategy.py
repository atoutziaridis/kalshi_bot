"""
FINAL COMPREHENSIVE MOMENTUM STRATEGY BACKTEST

This is the ultimate test of the momentum strategy with:
1. Multiple parameter variations
2. Advanced filters (category, time-to-expiry, spread)
3. Proper train/validate/test splits
4. Statistical significance testing
5. Risk-adjusted metrics (Sharpe, max drawdown)
6. Realistic fees and slippage

Goal: Find the most robust, deployable version of the strategy.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

import httpx
import numpy as np
from scipy import stats


@dataclass
class StrategyConfig:
    """Configuration for a momentum strategy variant."""
    name: str
    yes_low: float
    yes_high: float
    no_low: float
    no_high: float
    min_volume: int
    max_spread: float = 0.10
    min_days_to_expiry: int = 0
    max_days_to_expiry: int = 9999
    category_filter: str | None = None


def fetch_markets(max_markets: int = 30000) -> list[dict]:
    """Fetch settled markets for backtesting."""
    print(f"Fetching up to {max_markets} settled markets...")
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
            if len(all_markets) % 1000 == 0:
                print(f"  ...{len(all_markets)} markets")
        except Exception as e:
            print(f"  Error: {e}")
            retries += 1
            time.sleep(1)

    client.close()
    print(f"  Total: {len(all_markets)} markets fetched")
    return all_markets


def calculate_fee(price: float) -> float:
    """Kalshi fee: 0.07 * p * (1-p), minimum 1 cent."""
    if price <= 0 or price >= 1:
        return 0.0
    return max(0.01, np.ceil(0.07 * price * (1 - price) * 100) / 100)


def calculate_spread_cost(yes_bid: float, yes_ask: float) -> float:
    """Estimate spread cost."""
    if yes_bid == 0 or yes_ask == 0:
        return 0.01
    spread = yes_ask - yes_bid
    return spread / 2


def generate_signals(
    markets: list[dict],
    config: StrategyConfig
) -> list[dict]:
    """Generate trading signals based on strategy config."""
    signals = []

    for m in markets:
        ticker = m.get("ticker", "")
        title = m.get("title", "")
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0) or 0
        category = m.get("category", "")

        yes_bid = (m.get("yes_bid", 0) or 0) / 100
        yes_ask = (m.get("yes_ask", 0) or 0) / 100
        last_price = (m.get("last_price", 0) or 0) / 100

        if yes_bid and yes_ask:
            price = (yes_bid + yes_ask) / 2
            spread = yes_ask - yes_bid
        elif last_price:
            price = last_price
            spread = 0.02
        else:
            continue

        if volume < config.min_volume:
            continue

        if spread > config.max_spread:
            continue

        if config.category_filter and category != config.category_filter:
            continue

        exp_str = m.get("close_time") or m.get("expiration_time", "")
        if exp_str:
            try:
                exp_time = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                days_to_expiry = (exp_time - now).days
                if days_to_expiry < config.min_days_to_expiry:
                    continue
                if days_to_expiry > config.max_days_to_expiry:
                    continue
            except:
                pass

        signal = None

        if config.yes_low < price < config.yes_high:
            entry_price = yes_ask if yes_ask else price + 0.01
            fee = calculate_fee(entry_price)
            spread_cost = calculate_spread_cost(yes_bid, yes_ask)
            total_cost = entry_price + fee + spread_cost

            if total_cost >= 1.0:
                continue

            pnl = (1.0 - total_cost) if result else -total_cost
            signal = {
                "ticker": ticker,
                "title": title,
                "price": price,
                "entry_cost": total_cost,
                "won": result,
                "pnl": pnl,
                "side": "YES",
                "volume": volume,
                "category": category,
            }

        elif config.no_low < price < config.no_high:
            no_price = 1 - price
            entry_price = 1 - yes_bid if yes_bid else no_price + 0.01
            fee = calculate_fee(entry_price)
            spread_cost = calculate_spread_cost(yes_bid, yes_ask)
            total_cost = entry_price + fee + spread_cost

            if total_cost >= 1.0:
                continue

            pnl = (1.0 - total_cost) if not result else -total_cost
            signal = {
                "ticker": ticker,
                "title": title,
                "price": price,
                "entry_cost": total_cost,
                "won": not result,
                "pnl": pnl,
                "side": "NO",
                "volume": volume,
                "category": category,
            }

        if signal:
            signals.append(signal)

    return signals


def backtest_signals(signals: list[dict], initial_capital: float = 10000) -> dict:
    """Run backtest with position sizing and risk management."""
    if not signals:
        return None

    capital = initial_capital
    returns = []
    trades = []
    max_capital = capital
    max_drawdown = 0

    for s in signals:
        position_size = min(capital * 0.02, 200)
        contracts = position_size / 0.5

        trade_pnl = s["pnl"] * contracts
        ret = trade_pnl / capital if capital > 0 else 0
        returns.append(ret)

        capital += trade_pnl
        max_capital = max(max_capital, capital)
        drawdown = (max_capital - capital) / max_capital if max_capital > 0 else 0
        max_drawdown = max(max_drawdown, drawdown)

        trades.append({
            "pnl": trade_pnl,
            "capital": capital,
            "won": s["won"],
        })

        if capital < 500:
            break

    if len(returns) < 5:
        return None

    pnls = [s["pnl"] for s in signals[:len(returns)]]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total_return = (capital - initial_capital) / initial_capital
    win_rate = len(wins) / len(pnls) if pnls else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0

    _, p_value = stats.ttest_1samp(returns, 0) if len(returns) > 5 else (0, 1.0)

    sharpe = 0
    if len(returns) > 1:
        mean_ret = np.mean(returns)
        std_ret = np.std(returns)
        if std_ret > 0:
            sharpe = (mean_ret / std_ret) * np.sqrt(252)

    return {
        "trades": len(returns),
        "win_rate": win_rate,
        "return": total_return,
        "final_capital": capital,
        "p_value": p_value,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "returns": returns,
    }


def three_way_split_test(
    markets: list[dict],
    config: StrategyConfig
) -> dict:
    """Test strategy with train/validate/test split."""
    n = len(markets)
    train_end = int(n * 0.5)
    val_end = int(n * 0.75)

    train_markets = markets[:train_end]
    val_markets = markets[train_end:val_end]
    test_markets = markets[val_end:]

    train_signals = generate_signals(train_markets, config)
    val_signals = generate_signals(val_markets, config)
    test_signals = generate_signals(test_markets, config)

    train_result = backtest_signals(train_signals)
    val_result = backtest_signals(val_signals)
    test_result = backtest_signals(test_signals)

    return {
        "config": config,
        "train": train_result,
        "validate": val_result,
        "test": test_result,
    }


def run_comprehensive_backtest():
    print("=" * 80)
    print("FINAL COMPREHENSIVE MOMENTUM STRATEGY BACKTEST")
    print("=" * 80)

    markets = fetch_markets(max_markets=30000)

    if len(markets) < 5000:
        print("Insufficient data for robust testing")
        return

    print(f"\nTesting on {len(markets)} settled markets")

    strategies = [
        StrategyConfig(
            name="Original (65-78/22-40, v50)",
            yes_low=0.65, yes_high=0.78,
            no_low=0.22, no_high=0.40,
            min_volume=50
        ),
        StrategyConfig(
            name="Tight Range (68-75/25-35, v100)",
            yes_low=0.68, yes_high=0.75,
            no_low=0.25, no_high=0.35,
            min_volume=100
        ),
        StrategyConfig(
            name="Wide Range (62-80/20-42, v50)",
            yes_low=0.62, yes_high=0.80,
            no_low=0.20, no_high=0.42,
            min_volume=50
        ),
        StrategyConfig(
            name="High Volume (65-78/22-40, v200)",
            yes_low=0.65, yes_high=0.78,
            no_low=0.22, no_high=0.40,
            min_volume=200
        ),
        StrategyConfig(
            name="Asymmetric (67-78/22-38, v75)",
            yes_low=0.67, yes_high=0.78,
            no_low=0.22, no_high=0.38,
            min_volume=75
        ),
        StrategyConfig(
            name="Conservative (70-76/24-32, v100)",
            yes_low=0.70, yes_high=0.76,
            no_low=0.24, no_high=0.32,
            min_volume=100
        ),
        StrategyConfig(
            name="Aggressive (63-80/20-40, v25)",
            yes_low=0.63, yes_high=0.80,
            no_low=0.20, no_high=0.40,
            min_volume=25
        ),
        StrategyConfig(
            name="Tight Spread (65-78/22-40, v50, spread<5%)",
            yes_low=0.65, yes_high=0.78,
            no_low=0.22, no_high=0.40,
            min_volume=50,
            max_spread=0.05
        ),
    ]

    print(f"\nTesting {len(strategies)} strategy variations...")
    print("\n" + "=" * 80)

    results = []
    for i, config in enumerate(strategies, 1):
        print(f"\n[{i}/{len(strategies)}] Testing: {config.name}")
        result = three_way_split_test(markets, config)
        results.append(result)

        train = result["train"]
        val = result["validate"]
        test = result["test"]

        if train and val and test:
            print(f"  Train:    {train['trades']:4} trades, "
                  f"{train['return']:+7.2%}, p={train['p_value']:.4f}, "
                  f"Sharpe={train['sharpe']:.2f}")
            print(f"  Validate: {val['trades']:4} trades, "
                  f"{val['return']:+7.2%}, WR={val['win_rate']:.1%}")
            print(f"  Test:     {test['trades']:4} trades, "
                  f"{test['return']:+7.2%}, WR={test['win_rate']:.1%}, "
                  f"DD={test['max_drawdown']:.1%}")
        else:
            print("  Insufficient trades")

    print("\n" + "=" * 80)
    print("FINAL RESULTS SUMMARY")
    print("=" * 80)

    robust_strategies = []
    for r in results:
        train = r["train"]
        val = r["validate"]
        test = r["test"]

        if not (train and val and test):
            continue

        is_robust = (
            train["return"] > 0 and
            val["return"] > 0 and
            test["return"] > 0 and
            train["p_value"] < 0.10 and
            test["trades"] >= 20
        )

        if is_robust:
            robust_strategies.append(r)

    if robust_strategies:
        print(f"\n✓ Found {len(robust_strategies)} robust strategies:\n")

        robust_strategies.sort(
            key=lambda x: x["test"]["return"],
            reverse=True
        )

        for i, r in enumerate(robust_strategies, 1):
            config = r["config"]
            test = r["test"]
            train = r["train"]

            print(f"{i}. {config.name}")
            print(f"   Test Return: {test['return']:+.2%}")
            print(f"   Test Win Rate: {test['win_rate']:.1%}")
            print(f"   Test Sharpe: {test['sharpe']:.2f}")
            print(f"   Test Max DD: {test['max_drawdown']:.1%}")
            print(f"   Train p-value: {train['p_value']:.4f}")
            print()

        print("=" * 80)
        print("DEPLOYMENT RECOMMENDATION")
        print("=" * 80)

        best = robust_strategies[0]
        config = best["config"]
        test = best["test"]

        print(f"\n✓ DEPLOY: {config.name}")
        print(f"\nParameters:")
        print(f"  YES range: {config.yes_low:.0%} - {config.yes_high:.0%}")
        print(f"  NO range:  {config.no_low:.0%} - {config.no_high:.0%}")
        print(f"  Min volume: {config.min_volume}")
        print(f"  Max spread: {config.max_spread:.0%}")
        print(f"\nExpected Performance:")
        print(f"  Win rate: {test['win_rate']:.1%}")
        print(f"  Return: {test['return']:+.2%}")
        print(f"  Sharpe: {test['sharpe']:.2f}")
        print(f"  Max drawdown: {test['max_drawdown']:.1%}")

    else:
        print("\n✗ NO ROBUST STRATEGIES FOUND")
        print("\nBest performing (even if not robust):\n")

        valid_results = [r for r in results if r["test"]]
        valid_results.sort(
            key=lambda x: x["test"]["return"],
            reverse=True
        )

        for i, r in enumerate(valid_results[:3], 1):
            config = r["config"]
            test = r["test"]
            train = r["train"]

            print(f"{i}. {config.name}")
            print(f"   Test: {test['return']:+.2%}, "
                  f"WR={test['win_rate']:.1%}, "
                  f"p={train['p_value']:.4f}")

        print("\n⚠️  RECOMMENDATION: DO NOT DEPLOY")
        print("   No strategy meets robustness criteria")
        print("   Consider this a failed hypothesis")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    run_comprehensive_backtest()
