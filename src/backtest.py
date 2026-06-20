from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

try:
    from .loader import PROJECT_ROOT, build_paired_sessions, extract_zip, load_option_sessions
    from .strategy import (
        Trade,
        VacuumDiagnostic,
        load_strategy_config,
        run_strategy_for_pairs,
        trades_to_dataframe,
        vacuum_diagnostics_to_dataframe,
    )
except ImportError:
    from loader import PROJECT_ROOT, build_paired_sessions, extract_zip, load_option_sessions
    from strategy import (
        Trade,
        VacuumDiagnostic,
        load_strategy_config,
        run_strategy_for_pairs,
        trades_to_dataframe,
        vacuum_diagnostics_to_dataframe,
    )


TRADE_COLUMNS = list(Trade.__dataclass_fields__.keys())
VACUUM_DIAGNOSTIC_COLUMNS = list(VacuumDiagnostic.__dataclass_fields__.keys())
DAILY_COLUMNS = ["trade_date", "trades", "wins", "losses", "gross_pnl", "day_pnl"]
CSV_FLOAT_FORMAT = "%.2f"


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


def calculate_max_drawdown(pnl: pd.Series) -> float:
    if pnl.empty:
        return 0.0
    equity = pnl.cumsum()
    drawdown = equity - equity.cummax()
    return float(drawdown.min())


def build_report(config_path: Path, trades_df: pd.DataFrame, daily_df: pd.DataFrame) -> str:
    total_pnl = float(trades_df["pnl"].sum()) if not trades_df.empty else 0.0
    trades = len(trades_df)
    wins = int((trades_df["pnl"] > 0).sum()) if not trades_df.empty else 0
    losses = int((trades_df["pnl"] < 0).sum()) if not trades_df.empty else 0
    win_rate = (wins / trades * 100) if trades else 0.0
    avg_pnl = (total_pnl / trades) if trades else 0.0
    best_day = float(daily_df["day_pnl"].max()) if not daily_df.empty else 0.0
    worst_day = float(daily_df["day_pnl"].min()) if not daily_df.empty else 0.0
    max_drawdown = calculate_max_drawdown(trades_df["pnl"]) if not trades_df.empty else 0.0

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
        f"Max drawdown: {max_drawdown:.2f}",
    ]
    return "\n".join(lines) + "\n"


def _summary_rows_for_bool(
    trades_df: pd.DataFrame,
    analysis: str,
    column: str,
) -> list[dict[str, object]]:
    rows = []
    for value in (True, False):
        subset = trades_df[trades_df[column] == value]
        rows.append(
            {
                "analysis": analysis,
                "bucket": str(value),
                "trades": len(subset),
                "total_pnl": float(subset["pnl"].sum()) if not subset.empty else 0.0,
            }
        )
    return rows


def build_ema20_diagnostics_summary(trades_df: pd.DataFrame) -> pd.DataFrame:
    columns = ["analysis", "bucket", "trades", "total_pnl"]
    if trades_df.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    rows.extend(_summary_rows_for_bool(trades_df, "entry_above_ema20", "entry_above_ema20"))

    for color, subset in trades_df.groupby("entry_candle_color", sort=True):
        rows.append(
            {
                "analysis": "entry_candle_color",
                "bucket": color,
                "trades": len(subset),
                "total_pnl": float(subset["pnl"].sum()),
            }
        )

    rows.extend(
        _summary_rows_for_bool(
            trades_df,
            "previous_candle_touched_ema20",
            "previous_candle_touched_ema20",
        )
    )
    rows.extend(
        _summary_rows_for_bool(
            trades_df,
            "current_candle_touched_ema20",
            "current_candle_touched_ema20",
        )
    )

    distance = trades_df["distance_from_ema20"].abs()
    near_buckets = [
        ("within 5 pts", distance <= 5),
        ("within 10 pts", (distance > 5) & (distance <= 10)),
        ("within 15 pts", (distance > 10) & (distance <= 15)),
        ("beyond 15 pts", distance > 15),
    ]
    for bucket, mask in near_buckets:
        subset = trades_df[mask]
        rows.append(
            {
                "analysis": "near_ema20_bucket",
                "bucket": bucket,
                "trades": len(subset),
                "total_pnl": float(subset["pnl"].sum()) if not subset.empty else 0.0,
            }
        )

    return pd.DataFrame(rows, columns=columns)


def _load_sessions_for_config(config) -> dict:
    if config.data_dir:
        data_path = Path(PROJECT_ROOT) / config.data_dir
        if not data_path.exists():
            raise FileNotFoundError(
                f"Configured data_dir does not exist: {data_path}"
            )
        if not data_path.is_dir():
            raise FileNotFoundError(
                f"Configured data_dir is not a folder: {data_path}"
            )
        return load_option_sessions(data_path)

    extract_dir = extract_zip()
    return load_option_sessions(extract_dir)


def run_backtest(
    config_path: str | Path,
    output_name: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, str, Path]:
    config_path = Path(config_path)
    config = load_strategy_config(config_path)

    sessions = _load_sessions_for_config(config)
    pairs = build_paired_sessions(sessions)
    vacuum_diagnostics = []
    trades = run_strategy_for_pairs(
        pairs,
        config=config,
        vacuum_diagnostics=vacuum_diagnostics,
    )

    trades_df = trades_to_dataframe(trades)
    if trades_df.empty:
        trades_df = pd.DataFrame(columns=TRADE_COLUMNS)

    daily_df = build_daily_summary(trades_df)
    vacuum_diagnostics_df = vacuum_diagnostics_to_dataframe(vacuum_diagnostics)
    if vacuum_diagnostics_df.empty:
        vacuum_diagnostics_df = pd.DataFrame(columns=VACUUM_DIAGNOSTIC_COLUMNS)
    report = build_report(config_path, trades_df, daily_df)

    output_dir = Path(PROJECT_ROOT) / "output" / (output_name or config.name)
    output_dir.mkdir(parents=True, exist_ok=True)
    trades_df.to_csv(
        output_dir / "trades.csv",
        index=False,
        float_format=CSV_FLOAT_FORMAT,
    )
    daily_df.to_csv(
        output_dir / "daily_summary.csv",
        index=False,
        float_format=CSV_FLOAT_FORMAT,
    )
    build_ema20_diagnostics_summary(trades_df).to_csv(
        output_dir / "ema20_diagnostics_summary.csv",
        index=False,
        float_format=CSV_FLOAT_FORMAT,
    )
    vacuum_diagnostics_df.to_csv(
        output_dir / "vacuum_diagnostics.csv",
        index=False,
        float_format=CSV_FLOAT_FORMAT,
    )
    (output_dir / "report.txt").write_text(report)

    return trades_df, daily_df, report, output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Sweet Spot strategy backtest.")
    parser.add_argument("--config", required=True, help="Path to strategy YAML config.")
    parser.add_argument("--output-name", help="Optional output folder name under output/.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trades_df, daily_df, report, output_dir = run_backtest(args.config, args.output_name)
    print(report)
    print(f"Saved trades: {output_dir / 'trades.csv'}")
    print(f"Saved daily summary: {output_dir / 'daily_summary.csv'}")
    print(f"Saved EMA20 diagnostics: {output_dir / 'ema20_diagnostics_summary.csv'}")
    print(f"Saved report: {output_dir / 'report.txt'}")
    print(f"Trades generated: {len(trades_df)}")
    print(f"Trading days: {len(daily_df)}")


if __name__ == "__main__":
    main()
