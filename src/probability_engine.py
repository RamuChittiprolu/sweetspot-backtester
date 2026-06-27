from __future__ import annotations

from pathlib import Path

import pandas as pd


def _prob_group(trades: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=by + ["trades", "prob_hit_20_before_sl", "prob_hit_40_before_sl", "avg_pnl", "avg_win", "avg_loss", "expected_value"])
    df = trades.copy()
    df["hit_20"] = df["max_favorable_points"] >= 20
    df["hit_40"] = df["max_favorable_points"] >= 40
    out = (
        df.groupby(by, dropna=False)
        .agg(
            trades=("pnl", "size"),
            prob_hit_20_before_sl=("hit_20", "mean"),
            prob_hit_40_before_sl=("hit_40", "mean"),
            avg_pnl=("pnl", "mean"),
            avg_win=("pnl", lambda s: s[s > 0].mean()),
            avg_loss=("pnl", lambda s: s[s < 0].mean()),
        )
        .reset_index()
    )
    out["expected_value"] = out["avg_pnl"]
    return out.round(4)


def build_probability_reports(trades: pd.DataFrame) -> dict[str, pd.DataFrame]:
    df = trades.copy()
    if not df.empty:
        df["entry_time"] = pd.to_datetime(df["entry_time"])
        df["time_bucket"] = df["entry_time"].dt.strftime("%H:%M")
    return {
        "probability_report": _prob_group(df, ["setup"]) if not df.empty else _prob_group(df, ["setup"]),
        "setup_probability": _prob_group(df, ["setup"]),
        "time_bucket_probability": _prob_group(df, ["time_bucket"]) if "time_bucket" in df else pd.DataFrame(),
        "strike_probability": _prob_group(df, ["strike_distance", "option_type"]),
        "take_skip_candidates": _take_skip_candidates(df),
    }


def _take_skip_candidates(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["setup", "time_bucket", "strike_distance", "option_type", "trades", "prob_hit_20_before_sl", "expected_value", "decision"])
    grouped = _prob_group(trades, ["setup", "time_bucket", "strike_distance", "option_type"])
    grouped["decision"] = grouped.apply(
        lambda r: "TAKE" if r["trades"] >= 5 and r["prob_hit_20_before_sl"] >= 0.55 and r["expected_value"] > 0 else "SKIP",
        axis=1,
    )
    return grouped.sort_values(["decision", "expected_value"], ascending=[True, False])


def write_probability_reports(trades: pd.DataFrame, output_dir: str | Path) -> dict[str, Path]:
    probability_dir = Path(output_dir) / "probability"
    probability_dir.mkdir(parents=True, exist_ok=True)
    reports = build_probability_reports(trades)
    paths: dict[str, Path] = {}
    for name, df in reports.items():
        path = probability_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        paths[name] = path
    return paths
