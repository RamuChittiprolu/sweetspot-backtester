from __future__ import annotations

from pathlib import Path
import json
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_loader import load_market_data
from src.strategy import add_indicators, nearest_atm
from scripts.research_straddle_strategies import select_expiry


ENTRY_TIME = "09:20"
ENTRY_OFFSETS = [-50, 0]
TARGET_PCT = 0.15
SL_PCT = 0.0
QTY = 130

BROKERAGE_PER_ORDER = 20.0
STT_SELL_RATE = 0.0015
STAMP_BUY_RATE = 0.00003
EXCHANGE_TXN_RATE = 0.0003503
SEBI_RATE = 0.000001
GST_RATE = 0.18


def charges_for_option_leg(entry_premium: float, exit_premium: float) -> dict[str, float]:
    buy_turnover = entry_premium * QTY
    sell_turnover = exit_premium * QTY
    brokerage = BROKERAGE_PER_ORDER * 2
    stt = sell_turnover * STT_SELL_RATE
    stamp_duty = buy_turnover * STAMP_BUY_RATE
    exchange_txn = (buy_turnover + sell_turnover) * EXCHANGE_TXN_RATE
    sebi_fee = (buy_turnover + sell_turnover) * SEBI_RATE
    gst = (brokerage + exchange_txn + sebi_fee) * GST_RATE
    total_charges = brokerage + stt + stamp_duty + exchange_txn + sebi_fee + gst
    gross = (exit_premium - entry_premium) * QTY
    return {
        "buy_turnover": buy_turnover,
        "sell_turnover": sell_turnover,
        "gross_rupee_pnl": gross,
        "brokerage": brokerage,
        "stt": stt,
        "stamp_duty": stamp_duty,
        "exchange_txn": exchange_txn,
        "sebi_fee": sebi_fee,
        "gst": gst,
        "total_charges": total_charges,
        "net_rupee_pnl": gross - total_charges,
        "capital_used": buy_turnover + brokerage + stamp_duty + exchange_txn + sebi_fee + gst,
    }


def simulate_straddle(
    entry_ce: float,
    entry_pe: float,
    future: pd.DataFrame,
    target_pct: float,
    sl_pct: float,
) -> dict[str, object]:
    entry_total = entry_ce + entry_pe
    target_total = entry_total * (1 + target_pct) if target_pct else None
    stop_total = entry_total * (1 - sl_pct) if sl_pct else None
    last = future.iloc[-1]

    for _, row in future.iterrows():
        high_total = float(row["high_ce"] + row["high_pe"])
        low_total = float(row["low_ce"] + row["low_pe"])
        close_total = float(row["close_ce"] + row["close_pe"])

        if stop_total and low_total <= stop_total:
            low_sum = float(row["low_ce"] + row["low_pe"])
            if low_sum > 0:
                ce_exit = stop_total * float(row["low_ce"]) / low_sum
            else:
                ce_exit = stop_total * entry_ce / entry_total
            pe_exit = stop_total - ce_exit
            return {
                "exit_time": row["time"],
                "exit_reason": "SL",
                "exit_total": stop_total,
                "ce_exit": ce_exit,
                "pe_exit": pe_exit,
                "fill_type": "estimated_from_exit_candle_low",
                "exit_candle_close_ce": float(row["close_ce"]),
                "exit_candle_close_pe": float(row["close_pe"]),
                "exit_candle_high_ce": float(row["high_ce"]),
                "exit_candle_high_pe": float(row["high_pe"]),
                "exit_candle_low_ce": float(row["low_ce"]),
                "exit_candle_low_pe": float(row["low_pe"]),
            }

        if target_total and high_total >= target_total:
            high_sum = float(row["high_ce"] + row["high_pe"])
            if high_sum > 0:
                ce_exit = target_total * float(row["high_ce"]) / high_sum
            else:
                ce_exit = target_total * entry_ce / entry_total
            pe_exit = target_total - ce_exit
            return {
                "exit_time": row["time"],
                "exit_reason": "TARGET",
                "exit_total": target_total,
                "ce_exit": ce_exit,
                "pe_exit": pe_exit,
                "fill_type": "estimated_from_exit_candle_high",
                "exit_candle_close_ce": float(row["close_ce"]),
                "exit_candle_close_pe": float(row["close_pe"]),
                "exit_candle_high_ce": float(row["high_ce"]),
                "exit_candle_high_pe": float(row["high_pe"]),
                "exit_candle_low_ce": float(row["low_ce"]),
                "exit_candle_low_pe": float(row["low_pe"]),
            }

        if row["time"] >= "15:15":
            return {
                "exit_time": row["time"],
                "exit_reason": "SQUAREOFF",
                "exit_total": close_total,
                "ce_exit": float(row["close_ce"]),
                "pe_exit": float(row["close_pe"]),
                "fill_type": "exact_close",
                "exit_candle_close_ce": float(row["close_ce"]),
                "exit_candle_close_pe": float(row["close_pe"]),
                "exit_candle_high_ce": float(row["high_ce"]),
                "exit_candle_high_pe": float(row["high_pe"]),
                "exit_candle_low_ce": float(row["low_ce"]),
                "exit_candle_low_pe": float(row["low_pe"]),
            }

    return {
        "exit_time": last["time"],
        "exit_reason": "END",
        "exit_total": float(last["close_ce"] + last["close_pe"]),
        "ce_exit": float(last["close_ce"]),
        "pe_exit": float(last["close_pe"]),
        "fill_type": "exact_close",
        "exit_candle_close_ce": float(last["close_ce"]),
        "exit_candle_close_pe": float(last["close_pe"]),
        "exit_candle_high_ce": float(last["high_ce"]),
        "exit_candle_high_pe": float(last["high_pe"]),
        "exit_candle_low_ce": float(last["low_ce"]),
        "exit_candle_low_pe": float(last["low_pe"]),
    }


def build_rows(options: pd.DataFrame, spot: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    option_rows: list[dict[str, object]] = []
    straddle_rows: list[dict[str, object]] = []
    daily_rows: list[dict[str, object]] = []
    options_by_date = {date: df for date, df in options.groupby("date", sort=True)}

    for trade_date, day_spot in spot.groupby("date", sort=True):
        day_options = options_by_date.get(trade_date)
        if day_options is None:
            continue
        spot_915 = day_spot[day_spot["time"] == "09:15"]
        if spot_915.empty:
            continue

        nifty_open = float(spot_915.sort_values("datetime").iloc[0]["open"])
        atm = nearest_atm(nifty_open, 50)
        day_totals = {
            "entry_premium": 0.0,
            "exit_premium": 0.0,
            "points_pnl": 0.0,
            "gross_rupee_pnl": 0.0,
            "total_charges": 0.0,
            "net_rupee_pnl": 0.0,
            "capital_used": 0.0,
        }
        day_leg_count = 0

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

            merged = ce[
                ["datetime", "time", "open", "high", "low", "close", "source_file"]
            ].merge(
                pe[["datetime", "time", "open", "high", "low", "close", "source_file"]],
                on=["datetime", "time"],
                suffixes=("_ce", "_pe"),
            )
            entry_rows = merged[merged["time"] == ENTRY_TIME]
            if entry_rows.empty:
                continue
            future = merged[merged["datetime"] > entry_rows.iloc[0]["datetime"]]
            if future.empty:
                continue

            entry = entry_rows.iloc[0]
            entry_ce = float(entry["close_ce"])
            entry_pe = float(entry["close_pe"])
            entry_total = entry_ce + entry_pe
            exit_info = simulate_straddle(entry_ce, entry_pe, future, TARGET_PCT, SL_PCT)
            ce_exit = float(exit_info["ce_exit"])
            pe_exit = float(exit_info["pe_exit"])
            exit_total = ce_exit + pe_exit
            target_premium = entry_total * (1 + TARGET_PCT)
            straddle_name = "ATM -50 Straddle" if offset == -50 else "ATM Straddle"

            straddle_gross = 0.0
            straddle_charges = 0.0
            straddle_net = 0.0
            straddle_capital = 0.0

            for side, entry_premium, exit_premium, source_file in [
                ("CE", entry_ce, ce_exit, entry["source_file_ce"]),
                ("PE", entry_pe, pe_exit, entry["source_file_pe"]),
            ]:
                option_charges = charges_for_option_leg(entry_premium, exit_premium)
                points_pnl = exit_premium - entry_premium
                option_rows.append(
                    {
                        "Date": pd.Timestamp(trade_date).strftime("%Y-%m-%d"),
                        "Month": pd.Timestamp(trade_date).strftime("%Y-%m"),
                        "Entry Time": ENTRY_TIME,
                        "Exit Time": exit_info["exit_time"],
                        "NIFTY 09:15 Open": nifty_open,
                        "ATM": atm,
                        "Straddle": straddle_name,
                        "Offset": offset,
                        "Strike": strike,
                        "Expiry": pd.Timestamp(expiry).strftime("%Y-%m-%d") if pd.notna(expiry) else "",
                        "Side": side,
                        "Entry Premium": entry_premium,
                        "Exit Premium": exit_premium,
                        "Points P&L": points_pnl,
                        "Qty": QTY,
                        "Gross Rupee P&L": option_charges["gross_rupee_pnl"],
                        "Total Charges": option_charges["total_charges"],
                        "Net Rupee P&L": option_charges["net_rupee_pnl"],
                        "Capital Used": option_charges["capital_used"],
                        "Buy Turnover": option_charges["buy_turnover"],
                        "Sell Turnover": option_charges["sell_turnover"],
                        "Brokerage": option_charges["brokerage"],
                        "STT": option_charges["stt"],
                        "Stamp Duty": option_charges["stamp_duty"],
                        "Exchange Txn": option_charges["exchange_txn"],
                        "SEBI Fee": option_charges["sebi_fee"],
                        "GST": option_charges["gst"],
                        "Exit Reason": exit_info["exit_reason"],
                        "Fill Type": exit_info["fill_type"],
                        "Exit Candle Close": exit_info[f"exit_candle_close_{side.lower()}"],
                        "Exit Candle High": exit_info[f"exit_candle_high_{side.lower()}"],
                        "Exit Candle Low": exit_info[f"exit_candle_low_{side.lower()}"],
                        "Source File": source_file,
                    }
                )
                straddle_gross += option_charges["gross_rupee_pnl"]
                straddle_charges += option_charges["total_charges"]
                straddle_net += option_charges["net_rupee_pnl"]
                straddle_capital += option_charges["capital_used"]

            straddle_pnl = exit_total - entry_total
            straddle_rows.append(
                {
                    "Date": pd.Timestamp(trade_date).strftime("%Y-%m-%d"),
                    "Month": pd.Timestamp(trade_date).strftime("%Y-%m"),
                    "Entry Time": ENTRY_TIME,
                    "Exit Time": exit_info["exit_time"],
                    "NIFTY 09:15 Open": nifty_open,
                    "ATM": atm,
                    "Straddle": straddle_name,
                    "Offset": offset,
                    "Strike": strike,
                    "Entry Premium": entry_total,
                    "Target Premium": target_premium,
                    "Exit Premium": exit_total,
                    "Points P&L": straddle_pnl,
                    "Gross Rupee P&L": straddle_gross,
                    "Total Charges": straddle_charges,
                    "Net Rupee P&L": straddle_net,
                    "Capital Used": straddle_capital,
                    "Exit Reason": exit_info["exit_reason"],
                    "Fill Type": exit_info["fill_type"],
                }
            )

            day_totals["entry_premium"] += entry_total
            day_totals["exit_premium"] += exit_total
            day_totals["points_pnl"] += straddle_pnl
            day_totals["gross_rupee_pnl"] += straddle_gross
            day_totals["total_charges"] += straddle_charges
            day_totals["net_rupee_pnl"] += straddle_net
            day_totals["capital_used"] += straddle_capital
            day_leg_count += 1

        if day_leg_count:
            daily_rows.append(
                {
                    "Date": pd.Timestamp(trade_date).strftime("%Y-%m-%d"),
                    "Month": pd.Timestamp(trade_date).strftime("%Y-%m"),
                    "NIFTY 09:15 Open": nifty_open,
                    "ATM": atm,
                    "Straddles Taken": day_leg_count,
                    "Option Legs": day_leg_count * 2,
                    "Entry Premium": day_totals["entry_premium"],
                    "Exit Premium": day_totals["exit_premium"],
                    "Points P&L": day_totals["points_pnl"],
                    "Gross Rupee P&L": day_totals["gross_rupee_pnl"],
                    "Total Charges": day_totals["total_charges"],
                    "Net Rupee P&L": day_totals["net_rupee_pnl"],
                    "Capital Used": day_totals["capital_used"],
                    "Result": "Win" if day_totals["net_rupee_pnl"] >= 0 else "Loss",
                }
            )

    return pd.DataFrame(option_rows), pd.DataFrame(straddle_rows), pd.DataFrame(daily_rows)


def main() -> int:
    market = load_market_data(ROOT / "data/raw", ROOT / "data/nifty_spot", 5)
    options = add_indicators(market.options, 20)
    option_rows, straddle_rows, daily_rows = build_rows(options, market.spot)

    out_dir = ROOT / "output" / "research_straddle"
    out_dir.mkdir(parents=True, exist_ok=True)
    option_csv = out_dir / "straddle_0920_ce_pe_leg_trades.csv"
    straddle_csv = out_dir / "straddle_0920_straddle_component_trades_with_leg_alloc.csv"
    daily_csv = out_dir / "straddle_0920_daily_with_ce_pe_charges.csv"
    option_rows.to_csv(option_csv, index=False)
    straddle_rows.to_csv(straddle_csv, index=False)
    daily_rows.to_csv(daily_csv, index=False)

    monthly = (
        daily_rows.groupby("Month", as_index=False)
        .agg(
            **{
                "Trading Days": ("Date", "count"),
                "Points": ("Points P&L", "sum"),
                "Gross Rupee P&L": ("Gross Rupee P&L", "sum"),
                "Total Charges": ("Total Charges", "sum"),
                "Net Rupee P&L": ("Net Rupee P&L", "sum"),
                "Max Capital Used": ("Capital Used", "max"),
            }
        )
        if not daily_rows.empty
        else pd.DataFrame()
    )

    excel_data = {
        "summary": [
            ["Strategy", "09:20 long straddle basket"],
            ["Basket", "ATM -50 straddle + ATM straddle"],
            ["Quantity", QTY],
            ["Target", f"{TARGET_PCT:.0%} per straddle"],
            ["Stop Loss", "None" if SL_PCT == 0 else f"{SL_PCT:.0%} per straddle"],
            ["Option leg rows", int(len(option_rows))],
            ["Straddle component rows", int(len(straddle_rows))],
            ["Daily rows", int(len(daily_rows))],
            ["Total points", round(float(daily_rows["Points P&L"].sum()), 2) if not daily_rows.empty else 0],
            ["Total gross rupee P&L", round(float(daily_rows["Gross Rupee P&L"].sum()), 2) if not daily_rows.empty else 0],
            ["Total charges", round(float(daily_rows["Total Charges"].sum()), 2) if not daily_rows.empty else 0],
            ["Total net rupee P&L", round(float(daily_rows["Net Rupee P&L"].sum()), 2) if not daily_rows.empty else 0],
            ["Important note", "TARGET rows use estimated CE/PE allocation from the target candle high because 5-minute OHLC does not show the exact tick split."],
        ],
        "monthly": monthly.to_dict("records"),
        "daily": daily_rows.to_dict("records"),
        "straddles": straddle_rows.to_dict("records"),
        "optionLegs": option_rows.to_dict("records"),
    }
    json_path = ROOT / "output" / "excel" / "straddle_ce_pe_leg_workbook_data.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(excel_data, indent=2), encoding="utf-8")

    print(f"Option CE/PE rows: {len(option_rows)}")
    print(f"Saved {option_csv}")
    print(f"Saved {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
