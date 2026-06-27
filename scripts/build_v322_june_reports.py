from __future__ import annotations

from pathlib import Path
import os

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
V322 = ROOT / "output" / "reclaim_continuation_v322" / "trades" / "all_trades.csv"
V321 = ROOT / "output" / "normal_pivot_breakout_vix_structure_v2" / "trades" / "all_trades.csv"
OUT = ROOT / os.environ.get("V322_JUNE_REPORT_DIR", "output/reclaim_continuation_v322/june_reports")


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df


def daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "trades", "points", "wins", "losses", "best_trade", "worst_trade"])
    out = (
        df.groupby("date", as_index=False)
        .agg(
            trades=("pnl", "count"),
            points=("pnl", "sum"),
            wins=("pnl", lambda s: int((s > 0).sum())),
            losses=("pnl", lambda s: int((s < 0).sum())),
            best_trade=("pnl", "max"),
            worst_trade=("pnl", "min"),
        )
        .sort_values("date")
    )
    return out


def grouped_summary(df: pd.DataFrame, column: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[column, "trades", "points", "wins", "losses", "avg_points", "best_trade", "worst_trade"])
    return (
        df.groupby(column, dropna=False, as_index=False)
        .agg(
            trades=("pnl", "count"),
            points=("pnl", "sum"),
            wins=("pnl", lambda s: int((s > 0).sum())),
            losses=("pnl", lambda s: int((s < 0).sum())),
            avg_points=("pnl", "mean"),
            best_trade=("pnl", "max"),
            worst_trade=("pnl", "min"),
        )
        .sort_values("points", ascending=False)
    )


def missed_move_review(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    review = df[(df["max_favorable_points"] >= 20) & (df["pnl"] <= 0)].copy()
    if review.empty:
        return review
    review["missed_after_plus20"] = review["max_favorable_points"] - review["pnl"]
    review["review_reason"] = review.apply(
        lambda r: (
            "Reached +40 but final exit did not keep profit"
            if r["max_favorable_points"] >= 40
            else "Reached +20 but exited flat/loss"
        ),
        axis=1,
    )
    cols = [
        "date",
        "entry_time",
        "exit_time",
        "strike",
        "option_type",
        "setup",
        "entry_price",
        "exit_price",
        "pnl",
        "max_favorable_points",
        "missed_after_plus20",
        "exit_reason",
        "stop_level",
        "vix_status",
        "vix_reason",
        "review_reason",
    ]
    return review[[c for c in cols if c in review.columns]].sort_values(["date", "entry_time"])


def comparison(v322: pd.DataFrame, v321: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, df in [("v3.2.1 Structure v2", v321), ("v3.2.2 Reclaim + Continuation", v322)]:
        rows.append(
            {
                "strategy": label,
                "trades": len(df),
                "points": round(float(df["pnl"].sum()) if not df.empty else 0.0, 2),
                "wins": int((df["pnl"] > 0).sum()) if not df.empty else 0,
                "losses": int((df["pnl"] < 0).sum()) if not df.empty else 0,
                "win_rate": round(float((df["pnl"] > 0).mean() * 100) if not df.empty else 0.0, 2),
                "best_trade": round(float(df["pnl"].max()) if not df.empty else 0.0, 2),
                "worst_trade": round(float(df["pnl"].min()) if not df.empty else 0.0, 2),
            }
        )
    delta = rows[1]["points"] - rows[0]["points"]
    rows.append(
        {
            "strategy": "Improvement",
            "trades": rows[1]["trades"] - rows[0]["trades"],
            "points": round(delta, 2),
            "wins": rows[1]["wins"] - rows[0]["wins"],
            "losses": rows[1]["losses"] - rows[0]["losses"],
            "win_rate": round(rows[1]["win_rate"] - rows[0]["win_rate"], 2),
            "best_trade": round(rows[1]["best_trade"] - rows[0]["best_trade"], 2),
            "worst_trade": round(rows[1]["worst_trade"] - rows[0]["worst_trade"], 2),
        }
    )
    return pd.DataFrame(rows)


def setup_improvement(v322: pd.DataFrame, v321: pd.DataFrame) -> pd.DataFrame:
    old = grouped_summary(v321, "setup")[["setup", "points", "trades"]].rename(
        columns={"points": "v321_points", "trades": "v321_trades"}
    )
    new = grouped_summary(v322, "setup")[["setup", "points", "trades"]].rename(
        columns={"points": "v322_points", "trades": "v322_trades"}
    )
    merged = pd.merge(new, old, on="setup", how="outer").fillna(0)
    merged["points_improvement"] = merged["v322_points"] - merged["v321_points"]
    return merged.sort_values("points_improvement", ascending=False)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    v322 = load(V322)
    v321 = load(V321)
    june322 = v322[v322["date"].str.startswith("2026-06")].copy().sort_values("entry_time")
    june321 = v321[v321["date"].str.startswith("2026-06")].copy().sort_values("entry_time")

    june322.to_csv(OUT / "trades.csv", index=False)
    daily_summary(june322).to_csv(OUT / "daily_summary.csv", index=False)
    grouped_summary(june322, "setup").to_csv(OUT / "setup_type_summary.csv", index=False)
    grouped_summary(june322, "exit_reason").to_csv(OUT / "exit_reason_summary.csv", index=False)
    missed_move_review(june322).to_csv(OUT / "missed_move_review.csv", index=False)
    comparison(june322, june321).to_csv(OUT / "comparison_vs_v321_structure_v2.csv", index=False)
    setup_improvement(june322, june321).to_csv(OUT / "points_improvement_by_setup_type.csv", index=False)

    print(f"Saved reports to {OUT}")
    print(comparison(june322, june321).to_string(index=False))
    print("\nSetup improvement:")
    print(setup_improvement(june322, june321).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
