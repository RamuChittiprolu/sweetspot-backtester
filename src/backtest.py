from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

try:
    from .loader import PROJECT_ROOT, build_paired_sessions, extract_zip, load_option_sessions
    from .strategy import (
        Trade,
        load_strategy_config,
        run_strategy_for_pairs,
        trades_to_dataframe,
    )
except ImportError:
    from loader import PROJECT_ROOT, build_paired_sessions, extract_zip, load_option_sessions
    from strategy import (
        Trade,
        load_strategy_config,
        run_strategy_for_pairs,
        trades_to_dataframe,
    )


TRADE_COLUMNS = list(Trade.__dataclass_fields__.keys())
DAILY_COLUMNS = ["trade_date", "trades", "wins", "losses", "gross_pnl", "day_pnl"]


def build_daily_summary(trades_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)

    grouped = trades_df.groupby("trade_date")
    daily = grouped.agg(
        trades=("pnl", "size"),
        wins=("pnl", lambda values: int((values > 0).sum())),
        losses=("pnl", lambda values: int((values < 0).sum())),
        gross_pnl=("pnl", "sum"),
    ).reset_index()
    daily["day_pnl"] = daily["gross_pnl"]
    return daily[DAILY_COLUMNS]


def build_report(config_path: Path, trades_df: pd.DataFrame, daily_df: pd.DataFrame) -> str:
    total_pnl = float(trades_df["pnl"].sum()) if not trades_df.empty else 0.0
    trades = len(trades_df)
    wins = int((trades_df["pnl"] > 0).sum()) if not trades_df.empty else 0
    losses = int((trades_df["pnl"] < 0).sum()) if not trades_df.empty else 0
    win_rate = (wins / trades * 100) if trades else 0.0
    avg_pnl = (total_pnl / trades) if trades else 0.0
    best_day = float(daily_df["day_pnl"].max()) if not daily_df.empty else 0.0
    worst_day = float(daily_df["day_pnl"].min()) if not daily_df.empty else 0.0

    lines = [
        "Sweet Spot Backtest Report",
        "==========================",
        f"Config: {config_path}",
        "",
        f"Trading days: {len(daily_df)}",
        f"Trades: {trades}",
        f"Wins: {wins}",
        f"Losses: {losses}",
        f"Win rate: {win_rate:.2f}%",
        f"Total P&L: {total_pnl:.2f}",
        f"Average P&L per trade: {avg_pnl:.2f}",
        f"Best day: {best_day:.2f}",
        f"Worst day: {worst_day:.2f}",
    ]
    return "\n".join(lines) + "\n"


def run_backtest(config_path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame, str, Path]:
    config_path = Path(config_path)
    config = load_strategy_config(config_path)

    extract_dir = extract_zip()
    sessions = load_option_sessions(extract_dir)
    pairs = build_paired_sessions(sessions)
    trades = run_strategy_for_pairs(pairs, config=config)

    trades_df = trades_to_dataframe(trades)
    if trades_df.empty:
        trades_df = pd.DataFrame(columns=TRADE_COLUMNS)

    daily_df = build_daily_summary(trades_df)
    report = build_report(config_path, trades_df, daily_df)

    output_dir = Path(PROJECT_ROOT) / "output" / config.name
    output_dir.mkdir(parents=True, exist_ok=True)
    trades_df.to_csv(output_dir / "trades.csv", index=False)
    daily_df.to_csv(output_dir / "daily_summary.csv", index=False)
    (output_dir / "report.txt").write_text(report)

    return trades_df, daily_df, report, output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Sweet Spot strategy backtest.")
    parser.add_argument("--config", required=True, help="Path to strategy YAML config.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trades_df, daily_df, report, output_dir = run_backtest(args.config)
    print(report)
    print(f"Saved trades: {output_dir / 'trades.csv'}")
    print(f"Saved daily summary: {output_dir / 'daily_summary.csv'}")
    print(f"Saved report: {output_dir / 'report.txt'}")
    print(f"Trades generated: {len(trades_df)}")
    print(f"Trading days: {len(daily_df)}")


if __name__ == "__main__":
    main()
