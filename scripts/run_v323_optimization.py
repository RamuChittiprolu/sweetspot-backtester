from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest import run_backtest_with_market
from src.data_loader import load_market_data


OUT = ROOT / "output" / "v323_optimization"


CONFIGS = [
    ("config_1_v322_baseline", ROOT / "configs" / "reclaim_continuation_v322.yaml"),
    ("config_2_v323_continuation_disabled", ROOT / "configs" / "v323_continuation_disabled.yaml"),
    ("config_3_v323_profit_lock_8_continuation_disabled", ROOT / "configs" / "v323_profit_lock_8_continuation_disabled.yaml"),
    ("config_4_v323_profit_lock_10_continuation_disabled", ROOT / "configs" / "v323_profit_lock_10_continuation_disabled.yaml"),
    ("config_5_v323_profit_lock_15_continuation_disabled", ROOT / "configs" / "v323_profit_lock_15_continuation_disabled.yaml"),
    ("config_6_v323_profit_lock_10_strict_continuation", ROOT / "configs" / "v323_profit_lock_10_strict_continuation.yaml"),
    ("config_7_v323_profit_lock_10_strict_continuation_strict_vix", ROOT / "configs" / "v323_profit_lock_10_strict_continuation_strict_vix.yaml"),
]


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ["options_dir", "spot_dir", "output_dir"]:
        value = Path(config["data"][key])
        if not value.is_absolute():
            config["data"][key] = str(ROOT / value)
    return config


def june_only(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["entry_time"] = pd.to_datetime(out["entry_time"])
    out["exit_time"] = pd.to_datetime(out["exit_time"])
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out[out["date"].str.startswith("2026-06")].sort_values("entry_time").reset_index(drop=True)


def daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "trades", "points", "wins", "losses", "best_trade", "worst_trade"])
    return (
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
    review["review_reason"] = review["max_favorable_points"].map(
        lambda x: "Reached +40 but final exit did not keep profit" if x >= 40 else "Reached +20 but exited flat/loss"
    )
    return review.sort_values(["date", "entry_time"])


def comparison(df: pd.DataFrame, baseline: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, item in [("v3.2.2 baseline", baseline), ("current_config", df)]:
        rows.append(
            {
                "strategy": label,
                "trades": len(item),
                "points": round(float(item["pnl"].sum()) if not item.empty else 0.0, 2),
                "wins": int((item["pnl"] > 0).sum()) if not item.empty else 0,
                "losses": int((item["pnl"] < 0).sum()) if not item.empty else 0,
                "best_trade": round(float(item["pnl"].max()) if not item.empty else 0.0, 2),
                "worst_trade": round(float(item["pnl"].min()) if not item.empty else 0.0, 2),
            }
        )
    rows.append(
        {
            "strategy": "improvement",
            "trades": rows[1]["trades"] - rows[0]["trades"],
            "points": round(rows[1]["points"] - rows[0]["points"], 2),
            "wins": rows[1]["wins"] - rows[0]["wins"],
            "losses": rows[1]["losses"] - rows[0]["losses"],
            "best_trade": round(rows[1]["best_trade"] - rows[0]["best_trade"], 2),
            "worst_trade": round(rows[1]["worst_trade"] - rows[0]["worst_trade"], 2),
        }
    )
    return pd.DataFrame(rows)


def points_for(df: pd.DataFrame, setup: str) -> float:
    if df.empty or "setup" not in df:
        return 0.0
    return round(float(df.loc[df["setup"] == setup, "pnl"].sum()), 2)


def max_drawdown(points: pd.Series) -> float:
    if points.empty:
        return 0.0
    curve = points.cumsum()
    dd = curve - curve.cummax()
    return round(float(dd.min()), 2)


def summary_row(name: str, df: pd.DataFrame) -> dict[str, Any]:
    daily = daily_summary(df)
    pivot_mask = df["exit_reason"].isin(["PIVOT_CLOSE_SL", "BASE_LOW_SL"]) if not df.empty else pd.Series(dtype=bool)
    return {
        "config_name": name,
        "total_points": round(float(df["pnl"].sum()) if not df.empty else 0.0, 2),
        "total_trades": int(len(df)),
        "winning_trades": int((df["pnl"] > 0).sum()) if not df.empty else 0,
        "losing_trades": int((df["pnl"] < 0).sum()) if not df.empty else 0,
        "c2c_trades": int((df["exit_reason"] == "C2C").sum()) if not df.empty else 0,
        "profit_lock_exits": int((df["exit_reason"] == "PROFIT_LOCK").sum()) if not df.empty else 0,
        "trailing_sl_points": round(float(df.loc[df["exit_reason"] == "TRAILING_SL", "pnl"].sum()) if not df.empty else 0.0, 2),
        "pivot_sl_points": round(float(df.loc[pivot_mask, "pnl"].sum()) if not df.empty else 0.0, 2),
        "continuation_points": points_for(df, "continuation_base_breakout"),
        "ignition_points": points_for(df, "ignition_reclaim"),
        "first_breakout_points": points_for(df, "first_breakout"),
        "max_daily_loss": round(float(daily["points"].min()) if not daily.empty else 0.0, 2),
        "max_drawdown": max_drawdown(df["pnl"] if not df.empty else pd.Series(dtype=float)),
        "best_day": round(float(daily["points"].max()) if not daily.empty else 0.0, 2),
        "worst_day": round(float(daily["points"].min()) if not daily.empty else 0.0, 2),
    }


def audit(name: str, df: pd.DataFrame, config: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if df.empty:
        return issues
    strat = config["strategy"]
    ceilings = {
        "first_breakout": float(strat.get("max_entry_distance_from_pivot", 20)),
        "ignition_reclaim": float(strat.get("ignition_max_entry_distance", 30)),
        "fresh_reclaim": float(strat.get("reclaim_max_entry_distance", 30)),
        "continuation_base_breakout": float(strat.get("continuation_max_entry_distance", 40)),
        "side_switch": float(strat.get("side_switch_max_entry_distance", 30)),
    }
    for setup, ceiling in ceilings.items():
        bad = df[(df["setup"] == setup) & ((df["entry_price"] - df["pivot"]) > ceiling + 1e-9)]
        if not bad.empty:
            issues.append(f"{name}: {len(bad)} {setup} trades entered above ceiling.")
    if strat.get("vix_filter_mode") == "strict":
        bad_cont = df[(df["setup"] == "continuation_base_breakout") & (df["vix_status"].isin(["SHARP_FALL", "REVIEW"]))]
        if not bad_cont.empty:
            issues.append(f"{name}: strict VIX continuation violation count {len(bad_cont)}.")
    if strat.get("profit_lock_points") is not None:
        bad_loss = df[(df["max_favorable_points"] >= float(strat.get("profit_lock_trigger", 20))) & (df["pnl"] < -1e-9)]
        if not bad_loss.empty:
            issues.append(f"{name}: {len(bad_loss)} trades reached +20/profit trigger and exited below entry.")
        bad_lock = df[(df["exit_reason"] == "PROFIT_LOCK") & (df["max_favorable_points"] < float(strat.get("profit_lock_trigger", 20)))]
        if not bad_lock.empty:
            issues.append(f"{name}: {len(bad_lock)} profit-lock exits before trigger.")
    return issues


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    base_config = load_config(CONFIGS[0][1])
    market = load_market_data(base_config["data"]["options_dir"], base_config["data"]["spot_dir"], int(base_config["data"].get("candle_minutes", 5)))
    options = market.options[market.options["date"].astype(str).str.startswith("2026-06")].copy()
    spot = market.spot[market.spot["date"].astype(str).str.startswith("2026-06")].copy()

    all_results: dict[str, pd.DataFrame] = {}
    all_configs: dict[str, dict[str, Any]] = {}
    summary_rows = []
    audit_rows = []

    for name, path in CONFIGS:
        config = load_config(path)
        all_configs[name] = config
        trades, _ = run_backtest_with_market(config, options, spot, list(market.warnings))
        june = june_only(trades)
        all_results[name] = june

    baseline = all_results["config_1_v322_baseline"]
    for name, df in all_results.items():
        folder = OUT / name
        folder.mkdir(parents=True, exist_ok=True)
        df.to_csv(folder / "trades.csv", index=False)
        daily_summary(df).to_csv(folder / "daily_summary.csv", index=False)
        grouped_summary(df, "setup").to_csv(folder / "setup_type_summary.csv", index=False)
        grouped_summary(df, "exit_reason").to_csv(folder / "exit_reason_summary.csv", index=False)
        missed_move_review(df).to_csv(folder / "missed_move_review.csv", index=False)
        comparison(df, baseline).to_csv(folder / "comparison_vs_v322.csv", index=False)
        summary_rows.append(summary_row(name, df))
        issues = audit(name, df, all_configs[name])
        if issues:
            audit_rows.extend({"config_name": name, "audit_result": issue} for issue in issues)
        else:
            audit_rows.append({"config_name": name, "audit_result": "PASS"})

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUT / "v323_optimization_summary.csv", index=False)
    pd.DataFrame(audit_rows).to_csv(OUT / "v323_audit_results.csv", index=False)
    print(summary.to_string(index=False))
    print("\nAudit:")
    print(pd.DataFrame(audit_rows).to_string(index=False))
    print(f"\nSaved to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
