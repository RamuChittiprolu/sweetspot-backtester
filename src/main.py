from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .backtest import run_and_write
from .data_loader import DataValidationError
from .metrics import daily_summary, monthly_summary, summarize_strategy, write_reports
from .probability_engine import write_probability_reports


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    base = config_path.parent.parent
    for key in ["options_dir", "spot_dir", "output_dir"]:
        value = Path(config["data"][key])
        if not value.is_absolute():
            config["data"][key] = str(base / value)
    return config


def print_summary(trades: pd.DataFrame) -> None:
    strategy = summarize_strategy(trades)
    monthly = monthly_summary(trades)
    daily = daily_summary(trades)
    row = strategy.iloc[0].to_dict()
    print("\nSweet Spot v3.2.1 Backtest Summary")
    print(f"Total points: {row['total_points']}")
    print(f"Total trades: {row['total_trades']}")
    print(f"Win rate: {row['win_rate']}%")
    print(f"Max drawdown: {row['max_drawdown']}")
    print(f"Best trade: {row['best_trade']}")
    print(f"Worst trade: {row['worst_trade']}")
    print(f"350-400 points/month target: {row['target_350_400_month']}")
    print("\nMonth-wise points:")
    print(monthly.to_string(index=False) if not monthly.empty else "No monthly trades.")
    print("\nDaily points:")
    print(daily.to_string(index=False) if not daily.empty else "No daily trades.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweet Spot v3.2.1 Multi-Strike Probability Backtester")
    parser.add_argument("--config", required=True, help="Path to YAML config.")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        trades, warnings = run_and_write(config)
        output_dir = config["data"].get("output_dir", "output")
        write_reports(trades, output_dir)
        write_probability_reports(trades, output_dir)
        print_summary(trades)
        if warnings:
            print("\nValidation warnings:")
            for warning in warnings[:30]:
                print(f"- {warning}")
            if len(warnings) > 30:
                print(f"- {len(warnings) - 30} more warnings suppressed.")
        return 0
    except DataValidationError as exc:
        print(f"Data validation error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
