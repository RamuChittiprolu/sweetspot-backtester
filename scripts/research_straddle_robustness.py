from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.research_straddle_strategies import select_expiry
from src.data_loader import load_market_data
from src.strategy import add_indicators, nearest_atm


ENTRY_SIGNAL_TIME = "09:20"
ENTRY_OFFSETS = [-50, 0]
QTY = 130

ENTRY_MODES = ["close_0920", "next_candle_open"]
TARGET_MODES = ["high_touch", "close_confirm_exit_close", "close_confirm_exit_next_open"]
TARGET_PCTS = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25]
SLIPPAGE_PER_OPTION_LEG = [0.0, 0.5, 1.0, 2.0, 3.0]
DISASTER_SL_PCTS = [0.0, 0.40, 0.50]
DAY_FILTERS = ["all_days", "expiry_days"]

BROKERAGE_PER_ORDER = 20.0
STT_SELL_RATE = 0.0015
STAMP_BUY_RATE = 0.00003
EXCHANGE_TXN_RATE = 0.0003503
SEBI_RATE = 0.000001
GST_RATE = 0.18


@dataclass(frozen=True)
class Variant:
    day_filter: str
    entry_mode: str
    target_mode: str
    target_pct: float
    slippage: float
    disaster_sl_pct: float


def charges_for_straddle(entry_exec: float, exit_exec: float) -> float:
    buy_turnover = entry_exec * QTY
    sell_turnover = exit_exec * QTY
    brokerage = BROKERAGE_PER_ORDER * 4
    stt = sell_turnover * STT_SELL_RATE
    stamp_duty = buy_turnover * STAMP_BUY_RATE
    exchange_txn = (buy_turnover + sell_turnover) * EXCHANGE_TXN_RATE
    sebi_fee = (buy_turnover + sell_turnover) * SEBI_RATE
    gst = (brokerage + exchange_txn + sebi_fee) * GST_RATE
    return brokerage + stt + stamp_duty + exchange_txn + sebi_fee + gst


def week_start_monday(value: date) -> date:
    return value - timedelta(days=value.weekday())


def expiry_dates_from_available(dates: list[date]) -> set[date]:
    weeks: dict[date, list[date]] = {}
    for value in sorted(dates):
        weeks.setdefault(week_start_monday(value), []).append(value)

    expiry_dates: set[date] = set()
    for monday, week_dates in weeks.items():
        revised_rule = week_dates[0] >= date(2025, 9, 1)
        target = monday + timedelta(days=1 if revised_rule else 3)
        candidates = [value for value in week_dates if value <= target]
        if candidates:
            expiry_dates.add(max(candidates))
    return expiry_dates


def build_paths(options: pd.DataFrame, spot: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    options_by_date = {trade_date: df for trade_date, df in options.groupby("date", sort=True)}

    for trade_date, day_spot in spot.groupby("date", sort=True):
        day_options = options_by_date.get(trade_date)
        if day_options is None:
            continue
        spot_915 = day_spot[day_spot["time"] == "09:15"]
        if spot_915.empty:
            continue

        nifty_open = float(spot_915.sort_values("datetime").iloc[0]["open"])
        atm = nearest_atm(nifty_open, 50)
        for offset in ENTRY_OFFSETS:
            strike = atm + offset
            expiry = select_expiry(day_options, trade_date, strike)
            if expiry is None:
                continue

            ce = day_options[
                (day_options["strike"] == strike)
                & (day_options["option_type"] == "CE")
                & (day_options["expiry_date"] == expiry)
            ].sort_values("datetime")
            pe = day_options[
                (day_options["strike"] == strike)
                & (day_options["option_type"] == "PE")
                & (day_options["expiry_date"] == expiry)
            ].sort_values("datetime")
            if ce.empty or pe.empty:
                continue

            merged = ce[["datetime", "time", "open", "high", "low", "close"]].merge(
                pe[["datetime", "time", "open", "high", "low", "close"]],
                on=["datetime", "time"],
                suffixes=("_ce", "_pe"),
            )
            signal_rows = merged[merged["time"] == ENTRY_SIGNAL_TIME]
            if signal_rows.empty:
                continue

            signal = signal_rows.iloc[0]
            after_signal = merged[merged["datetime"] > signal["datetime"]]
            if after_signal.empty:
                continue

            rows.append(
                {
                    "date": trade_date,
                    "month": pd.Timestamp(trade_date).strftime("%Y-%m"),
                    "offset": offset,
                    "strike": strike,
                    "close_0920_entry_raw": float(signal["close_ce"] + signal["close_pe"]),
                    "next_open_entry_raw": float(after_signal.iloc[0]["open_ce"] + after_signal.iloc[0]["open_pe"]),
                    "future_after_signal": after_signal[
                        [
                            "time",
                            "open_ce",
                            "open_pe",
                            "high_ce",
                            "high_pe",
                            "low_ce",
                            "low_pe",
                            "close_ce",
                            "close_pe",
                        ]
                    ].to_dict("records"),
                }
            )
    return pd.DataFrame(rows)


def raw_sum(row: dict[str, object], field: str) -> float:
    return float(row[f"{field}_ce"] + row[f"{field}_pe"])


def simulate_path(path: pd.Series, variant: Variant) -> dict[str, object]:
    entry_slip = variant.slippage * 2
    exit_slip = variant.slippage * 2

    if variant.entry_mode == "close_0920":
        entry_raw = float(path["close_0920_entry_raw"])
        future = path["future_after_signal"]
    else:
        entry_raw = float(path["next_open_entry_raw"])
        future = path["future_after_signal"]

    entry_exec = entry_raw + entry_slip
    target_exec = entry_exec * (1 + variant.target_pct)
    stop_exec = entry_exec * (1 - variant.disaster_sl_pct) if variant.disaster_sl_pct else None

    for idx, row in enumerate(future):
        close_exec = raw_sum(row, "close") - exit_slip
        high_exec = raw_sum(row, "high") - exit_slip

        if stop_exec and close_exec <= stop_exec:
            if variant.target_mode.endswith("next_open") and idx + 1 < len(future):
                exit_exec = raw_sum(future[idx + 1], "open") - exit_slip
                exit_time = future[idx + 1]["time"]
            else:
                exit_exec = close_exec
                exit_time = row["time"]
            return {
                "exit_exec": exit_exec,
                "reason": "DISASTER_SL",
                "exit_time": exit_time,
                "entry_exec": entry_exec,
            }

        if variant.target_mode == "high_touch":
            if high_exec >= target_exec:
                return {
                    "exit_exec": target_exec,
                    "reason": "TARGET_HIGH_TOUCH",
                    "exit_time": row["time"],
                    "entry_exec": entry_exec,
                }
        elif variant.target_mode == "close_confirm_exit_close":
            if close_exec >= target_exec:
                return {
                    "exit_exec": close_exec,
                    "reason": "TARGET_CLOSE",
                    "exit_time": row["time"],
                    "entry_exec": entry_exec,
                }
        elif variant.target_mode == "close_confirm_exit_next_open":
            if close_exec >= target_exec:
                if idx + 1 < len(future):
                    exit_exec = raw_sum(future[idx + 1], "open") - exit_slip
                    exit_time = future[idx + 1]["time"]
                else:
                    exit_exec = close_exec
                    exit_time = row["time"]
                return {
                    "exit_exec": exit_exec,
                    "reason": "TARGET_CLOSE_NEXT_OPEN",
                    "exit_time": exit_time,
                    "entry_exec": entry_exec,
                }

        if row["time"] >= "15:15":
            return {
                "exit_exec": close_exec,
                "reason": "SQUAREOFF",
                "exit_time": row["time"],
                "entry_exec": entry_exec,
            }

    last = future[-1]
    return {
        "exit_exec": raw_sum(last, "close") - exit_slip,
        "reason": "END",
        "exit_time": last["time"],
        "entry_exec": entry_exec,
    }


def evaluate(paths: pd.DataFrame, variant: Variant, expiry_dates: set[date]) -> tuple[dict[str, object], pd.DataFrame]:
    subset = paths.copy()
    if variant.day_filter == "expiry_days":
        subset = subset[subset["date"].isin(expiry_dates)]
    if subset.empty:
        return {}, pd.DataFrame()

    component_rows: list[dict[str, object]] = []
    for _, path in subset.iterrows():
        result = simulate_path(path, variant)
        entry_exec = float(result["entry_exec"])
        exit_exec = float(result["exit_exec"])
        points = exit_exec - entry_exec
        charges = charges_for_straddle(entry_exec, exit_exec)
        component_rows.append(
            {
                "date": path["date"],
                "month": path["month"],
                "offset": path["offset"],
                "strike": path["strike"],
                "entry_exec": entry_exec,
                "exit_exec": exit_exec,
                "points": points,
                "gross_rupee_pnl": points * QTY,
                "charges": charges,
                "net_rupee_pnl": points * QTY - charges,
                "exit_reason": result["reason"],
                "exit_time": result["exit_time"],
            }
        )

    components = pd.DataFrame(component_rows)
    daily = (
        components.groupby(["date", "month"], as_index=False)
        .agg(
            straddles=("offset", "count"),
            points=("points", "sum"),
            gross_rupee_pnl=("gross_rupee_pnl", "sum"),
            charges=("charges", "sum"),
            net_rupee_pnl=("net_rupee_pnl", "sum"),
        )
        .sort_values("date")
    )
    monthly = daily.groupby("month")["points"].sum()
    complete_months = monthly[monthly.index != "2025-08"]
    daily["equity"] = daily["points"].cumsum()
    daily["peak"] = daily["equity"].cummax()
    daily["drawdown"] = daily["equity"] - daily["peak"]

    summary = {
        "day_filter": variant.day_filter,
        "entry_mode": variant.entry_mode,
        "target_mode": variant.target_mode,
        "target_pct": variant.target_pct,
        "slippage_per_option_leg": variant.slippage,
        "disaster_sl_pct": variant.disaster_sl_pct,
        "days": int(len(daily)),
        "straddle_components": int(len(components)),
        "total_points": round(float(daily["points"].sum()), 2),
        "net_rupee_pnl": round(float(daily["net_rupee_pnl"].sum()), 0),
        "daily_win_rate_pct": round(float((daily["net_rupee_pnl"] > 0).mean() * 100), 2),
        "avg_month_ex_aug": round(float(complete_months.mean()), 2) if not complete_months.empty else 0.0,
        "best_month": round(float(complete_months.max()), 2) if not complete_months.empty else 0.0,
        "worst_month": round(float(complete_months.min()), 2) if not complete_months.empty else 0.0,
        "positive_months": int((complete_months > 0).sum()),
        "months_350_plus": int((complete_months >= 350).sum()),
        "max_drawdown_points": round(float(daily["drawdown"].min()), 2),
        "target_exits": int(components["exit_reason"].str.contains("TARGET").sum()),
        "sl_exits": int((components["exit_reason"] == "DISASTER_SL").sum()),
    }
    return summary, daily


def main() -> int:
    market = load_market_data(ROOT / "data/raw", ROOT / "data/nifty_spot", 5)
    options = add_indicators(market.options, 20)
    paths = build_paths(options, market.spot)
    expiry_dates = expiry_dates_from_available(list(paths["date"].unique()))

    summaries: list[dict[str, object]] = []
    selected_daily: dict[str, pd.DataFrame] = {}
    for day_filter in DAY_FILTERS:
            for entry_mode in ENTRY_MODES:
                for target_mode in TARGET_MODES:
                    for target_pct in TARGET_PCTS:
                        for slippage in SLIPPAGE_PER_OPTION_LEG:
                            for disaster_sl_pct in DISASTER_SL_PCTS:
                                variant = Variant(
                                    day_filter,
                                    entry_mode,
                                    target_mode,
                                    target_pct,
                                    slippage,
                                    disaster_sl_pct,
                                )
                                summary, daily = evaluate(paths, variant, expiry_dates)
                                if not summary:
                                    continue
                                summaries.append(summary)
                                key = (
                                    f"{day_filter}__{entry_mode}__{target_mode}"
                                    f"__target_{target_pct:g}__slip_{slippage:g}__dsl_{disaster_sl_pct:g}"
                                )
                                selected_daily[key] = daily

    out_dir = ROOT / "output" / "research_straddle"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_df = pd.DataFrame(summaries).sort_values(
        ["avg_month_ex_aug", "total_points"], ascending=False
    )
    summary_df.to_csv(out_dir / "straddle_robustness_summary.csv", index=False)

    robust = summary_df[
        (summary_df["target_mode"] != "high_touch")
        & (summary_df["entry_mode"] == "next_candle_open")
        & (summary_df["slippage_per_option_leg"] >= 1.0)
    ].copy()
    robust.to_csv(out_dir / "straddle_robustness_conservative_only.csv", index=False)

    watchlist = [
        "all_days__next_candle_open__close_confirm_exit_next_open__target_0.1__slip_1__dsl_0",
        "all_days__next_candle_open__close_confirm_exit_close__target_0.1__slip_1__dsl_0",
        "expiry_days__next_candle_open__close_confirm_exit_next_open__target_0.1__slip_1__dsl_0",
        "expiry_days__next_candle_open__close_confirm_exit_close__target_0.1__slip_1__dsl_0",
    ]
    for key in watchlist:
        daily = selected_daily.get(key)
        if daily is not None:
            daily.to_csv(out_dir / f"{key}_daily.csv", index=False)

    print("All variants:", len(summary_df))
    print("\nTop 20 all variants")
    print(summary_df.head(20).to_string(index=False))
    print("\nTop 20 conservative variants: next-candle entry, no high-touch target, >=1pt slippage/leg")
    print(robust.head(20).to_string(index=False))
    print(f"\nSaved {out_dir / 'straddle_robustness_summary.csv'}")
    print(f"Saved {out_dir / 'straddle_robustness_conservative_only.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
