from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def max_drawdown(pnl: pd.Series) -> float:
    if pnl.empty:
        return 0.0
    equity = pnl.cumsum()
    drawdown = equity - equity.cummax()
    return round(float(drawdown.min()), 2)


def losing_streak(pnl: pd.Series) -> int:
    streak = best = 0
    for value in pnl:
        if value < 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


def summarize_strategy(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame([{
            "total_points": 0.0, "total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "average_trade": 0.0, "max_drawdown": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
            "losing_streak": 0, "avg_monthly_points": 0.0, "target_350_400_month": False,
        }])
    pnl = trades["pnl"].astype(float)
    gross_win = pnl[pnl > 0].sum()
    gross_loss = abs(pnl[pnl < 0].sum())
    monthly = monthly_summary(trades)
    avg_monthly = float(monthly["points"].mean()) if not monthly.empty else 0.0
    return pd.DataFrame([{
        "total_points": round(float(pnl.sum()), 2),
        "total_trades": int(len(trades)),
        "win_rate": round(float((pnl > 0).mean() * 100), 2),
        "profit_factor": round(float(gross_win / gross_loss), 2) if gross_loss else np.inf,
        "average_trade": round(float(pnl.mean()), 2),
        "max_drawdown": max_drawdown(pnl),
        "best_trade": round(float(pnl.max()), 2),
        "worst_trade": round(float(pnl.min()), 2),
        "losing_streak": losing_streak(pnl),
        "avg_monthly_points": round(avg_monthly, 2),
        "target_350_400_month": bool(350 <= avg_monthly <= 400),
    }])


def daily_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["date", "points", "trades", "wins", "losses"])
    df = trades.copy()
    return (
        df.groupby("date")
        .agg(points=("pnl", "sum"), trades=("pnl", "size"), wins=("pnl", lambda s: int((s > 0).sum())), losses=("pnl", lambda s: int((s < 0).sum())))
        .reset_index()
        .round({"points": 2})
    )


def monthly_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["month", "points", "trades", "win_rate", "target_350_400"])
    df = trades.copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["month"] = df["entry_time"].dt.to_period("M").astype(str)
    out = (
        df.groupby("month")
        .agg(points=("pnl", "sum"), trades=("pnl", "size"), win_rate=("pnl", lambda s: float((s > 0).mean() * 100)))
        .reset_index()
    )
    out["target_350_400"] = out["points"].between(350, 400)
    return out.round({"points": 2, "win_rate": 2})


def bad_day_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    daily = daily_summary(trades)
    if daily.empty:
        return daily
    return daily.sort_values("points").head(20)


def write_reports(trades: pd.DataFrame, output_dir: str | Path) -> dict[str, Path]:
    report_dir = Path(output_dir) / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    reports = {
        "daily_summary": daily_summary(trades),
        "monthly_summary": monthly_summary(trades),
        "strategy_summary": summarize_strategy(trades),
        "bad_day_analysis": bad_day_analysis(trades),
    }
    paths: dict[str, Path] = {}
    for name, df in reports.items():
        path = report_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        paths[name] = path
    return paths
