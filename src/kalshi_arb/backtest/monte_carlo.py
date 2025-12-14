"""Monte Carlo validation for backtest robustness testing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MonteCarloResult:
    """Results from Monte Carlo simulation."""

    num_simulations: int
    pessimistic_5th: float
    median: float
    optimistic_95th: float
    probability_profitable: float
    mean_return: float
    std_return: float
    confidence_interval_95: tuple[float, float]


class MonteCarloValidator:
    """
    Monte Carlo validation to test if trading edge is real or luck.

    Shuffles trade outcomes while preserving distribution to identify
    if performance is statistically significant.
    """

    def __init__(self, num_simulations: int = 1000, seed: int | None = None):
        self.num_simulations = num_simulations
        self.rng = np.random.default_rng(seed)

    def validate_trades(
        self,
        trade_pnls: list[float],
        initial_capital: float = 10000.0,
    ) -> MonteCarloResult:
        """
        Run Monte Carlo simulation on trade P&Ls.

        Args:
            trade_pnls: List of P&L values from each trade
            initial_capital: Starting capital

        Returns:
            MonteCarloResult with distribution statistics
        """
        if not trade_pnls:
            return MonteCarloResult(
                num_simulations=0,
                pessimistic_5th=1.0,
                median=1.0,
                optimistic_95th=1.0,
                probability_profitable=0.0,
                mean_return=0.0,
                std_return=0.0,
                confidence_interval_95=(1.0, 1.0),
            )

        pnl_array = np.array(trade_pnls)
        final_returns = []

        for _ in range(self.num_simulations):
            shuffled = self.rng.permutation(pnl_array)

            equity = initial_capital
            for pnl in shuffled:
                equity += pnl

            final_return = equity / initial_capital
            final_returns.append(final_return)

        returns_array = np.array(final_returns)

        p5, p50, p95 = np.percentile(returns_array, [5, 50, 95])

        return MonteCarloResult(
            num_simulations=self.num_simulations,
            pessimistic_5th=p5,
            median=p50,
            optimistic_95th=p95,
            probability_profitable=float(np.mean(returns_array > 1.0)),
            mean_return=float(np.mean(returns_array)),
            std_return=float(np.std(returns_array)),
            confidence_interval_95=(p5, p95),
        )

    def bootstrap_sharpe(
        self,
        returns: list[float],
        num_bootstrap: int = 1000,
    ) -> tuple[float, float, float]:
        """
        Bootstrap confidence interval for Sharpe ratio.

        Args:
            returns: List of period returns
            num_bootstrap: Number of bootstrap samples

        Returns:
            Tuple of (lower_bound, point_estimate, upper_bound)
        """
        if len(returns) < 2:
            return (0.0, 0.0, 0.0)

        returns_array = np.array(returns)
        n = len(returns_array)

        sharpes = []
        for _ in range(num_bootstrap):
            sample = self.rng.choice(returns_array, size=n, replace=True)
            if sample.std() > 0:
                sharpe = sample.mean() / sample.std() * np.sqrt(252)
                sharpes.append(sharpe)

        if not sharpes:
            return (0.0, 0.0, 0.0)

        sharpes_array = np.array(sharpes)
        p5, p95 = np.percentile(sharpes_array, [5, 95])
        point_estimate = returns_array.mean() / returns_array.std() * np.sqrt(252)

        return (p5, point_estimate, p95)

    def path_simulation(
        self,
        trade_pnls: list[float],
        initial_capital: float = 10000.0,
        num_paths: int = 100,
    ) -> pd.DataFrame:
        """
        Generate multiple equity curve paths for visualization.

        Args:
            trade_pnls: List of trade P&Ls
            initial_capital: Starting capital
            num_paths: Number of paths to generate

        Returns:
            DataFrame with equity paths (columns = path index)
        """
        if not trade_pnls:
            return pd.DataFrame()

        pnl_array = np.array(trade_pnls)
        n_trades = len(pnl_array)

        paths = np.zeros((n_trades + 1, num_paths))
        paths[0, :] = initial_capital

        for path_idx in range(num_paths):
            shuffled = self.rng.permutation(pnl_array)
            equity = initial_capital
            for i, pnl in enumerate(shuffled):
                equity += pnl
                paths[i + 1, path_idx] = equity

        return pd.DataFrame(paths, columns=[f"path_{i}" for i in range(num_paths)])

    def drawdown_distribution(
        self,
        trade_pnls: list[float],
        initial_capital: float = 10000.0,
    ) -> dict[str, float]:
        """
        Estimate drawdown distribution via simulation.

        Returns:
            Dict with drawdown percentiles
        """
        if not trade_pnls:
            return {"p50": 0.0, "p75": 0.0, "p95": 0.0, "p99": 0.0}

        pnl_array = np.array(trade_pnls)
        max_drawdowns = []

        for _ in range(self.num_simulations):
            shuffled = self.rng.permutation(pnl_array)

            equity = initial_capital
            peak = initial_capital
            max_dd = 0.0

            for pnl in shuffled:
                equity += pnl
                if equity > peak:
                    peak = equity
                dd = (peak - equity) / peak if peak > 0 else 0.0
                max_dd = max(max_dd, dd)

            max_drawdowns.append(max_dd)

        dd_array = np.array(max_drawdowns)
        return {
            "p50": float(np.percentile(dd_array, 50)),
            "p75": float(np.percentile(dd_array, 75)),
            "p95": float(np.percentile(dd_array, 95)),
            "p99": float(np.percentile(dd_array, 99)),
        }

    def print_report(self, result: MonteCarloResult) -> str:
        """Generate formatted Monte Carlo report."""
        lines = [
            "=" * 50,
            "MONTE CARLO VALIDATION REPORT",
            "=" * 50,
            f"Simulations: {result.num_simulations:,}",
            "",
            "RETURN DISTRIBUTION",
            "-" * 30,
            f"5th Percentile (Pessimistic):  {result.pessimistic_5th:.2%}",
            f"Median (50th Percentile):      {result.median:.2%}",
            f"95th Percentile (Optimistic):  {result.optimistic_95th:.2%}",
            "",
            f"Mean Return:                   {result.mean_return:.2%}",
            f"Std Dev:                       {result.std_return:.2%}",
            "",
            "STATISTICAL SIGNIFICANCE",
            "-" * 30,
            f"Probability Profitable:        {result.probability_profitable:.1%}",
            f"95% Confidence Interval:       "
            f"[{result.confidence_interval_95[0]:.2%}, "
            f"{result.confidence_interval_95[1]:.2%}]",
            "",
            "INTERPRETATION",
            "-" * 30,
        ]

        if result.probability_profitable >= 0.95:
            lines.append("✓ Strong edge: >95% profitable across simulations")
        elif result.probability_profitable >= 0.80:
            lines.append("~ Moderate edge: 80-95% profitable")
        elif result.probability_profitable >= 0.60:
            lines.append("? Weak edge: 60-80% profitable, may be luck")
        else:
            lines.append("✗ No edge: <60% profitable, likely random")

        lines.append("=" * 50)
        return "\n".join(lines)
