from __future__ import annotations

from pathlib import Path
import json
import os

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC_OUTPUT = ROOT / os.environ.get("SWEETSPOT_SOURCE_OUTPUT", "output/recommended_atm_plus_afternoon")
OUT_DIR = ROOT / os.environ.get("SWEETSPOT_JUNE_OUTPUT", "output/june_sweetspot_trades")
QTY = 130
VIX_FILE = ROOT / "data" / "INDIA_VIX_5minute_2025-04-01_to_2026-06-26.csv"
STRATEGY_NAME = os.environ.get("SWEETSPOT_STRATEGY_NAME", "Sweet Spot v3.2.1 Recommended - ATM/Plus Afternoon")
CONFIG_FILE = os.environ.get("SWEETSPOT_CONFIG_FILE", "configs/recommended_atm_plus_afternoon.yaml")

BROKERAGE_PER_ORDER = 20.0
STT_SELL_RATE = 0.0015
STAMP_BUY_RATE = 0.00003
EXCHANGE_TXN_RATE = 0.0003503
SEBI_RATE = 0.000001
GST_RATE = 0.18


def charges_for_trade(entry: float, exit_: float) -> dict[str, float]:
    buy_turnover = entry * QTY
    sell_turnover = exit_ * QTY
    brokerage = BROKERAGE_PER_ORDER * 2
    stt = sell_turnover * STT_SELL_RATE
    stamp_duty = buy_turnover * STAMP_BUY_RATE
    exchange_txn = (buy_turnover + sell_turnover) * EXCHANGE_TXN_RATE
    sebi_fee = (buy_turnover + sell_turnover) * SEBI_RATE
    gst = (brokerage + exchange_txn + sebi_fee) * GST_RATE
    total = brokerage + stt + stamp_duty + exchange_txn + sebi_fee + gst
    gross = (exit_ - entry) * QTY
    return {
        "Buy Turnover": buy_turnover,
        "Sell Turnover": sell_turnover,
        "Gross Rupee P&L": gross,
        "Brokerage": brokerage,
        "STT": stt,
        "Stamp Duty": stamp_duty,
        "Exchange Txn": exchange_txn,
        "SEBI Fee": sebi_fee,
        "GST": gst,
        "Total Charges": total,
        "Net Rupee P&L": gross - total,
        "Capital Used": buy_turnover + brokerage + stamp_duty + exchange_txn + sebi_fee + gst,
    }


def clean_time(value: object) -> str:
    if pd.isna(value):
        return ""
    return pd.to_datetime(value).strftime("%H:%M")


def nearest_atm(value: float) -> int:
    return int(round(value / 50.0) * 50)


def to_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def clean_json_value(value: object) -> object:
    if pd.isna(value):
        return ""
    return value


def records_for_json(df: pd.DataFrame) -> list[dict[str, object]]:
    return [{k: clean_json_value(v) for k, v in row.items()} for row in df.to_dict("records")]


def load_vix() -> pd.DataFrame:
    vix = pd.read_csv(VIX_FILE)
    vix.columns = [c.strip().lower() for c in vix.columns]
    vix["dt"] = pd.to_datetime(vix["date"], errors="coerce").dt.tz_localize(None)
    vix = vix.dropna(subset=["dt"]).sort_values("dt")
    vix["Date"] = vix["dt"].dt.strftime("%Y-%m-%d")
    vix["Time"] = vix["dt"].dt.strftime("%H:%M")
    for col in ["open", "high", "low", "close"]:
        vix[col] = pd.to_numeric(vix[col], errors="coerce")
    return vix


def vix_context(vix: pd.DataFrame, date: str, entry_time: str) -> dict[str, object]:
    day = vix[vix["Date"] == date].copy()
    if day.empty:
        return {
            "VIX 09:15 Open": "",
            "VIX Entry Close": "",
            "VIX Change From Open %": "",
            "VIX 15m Change": "",
            "VIX 15m Trend": "MISSING",
            "VIX Filter": "REVIEW",
            "VIX Filter Reason": "No VIX data for date",
        }

    open_915 = day.loc[day["Time"] == "09:15", "open"]
    entry_dt = pd.to_datetime(f"{date} {entry_time}", errors="coerce")
    upto_entry = day[day["dt"] <= entry_dt].tail(4)
    entry_row = day[day["Time"] == entry_time]
    if open_915.empty or entry_row.empty or upto_entry.empty:
        return {
            "VIX 09:15 Open": "",
            "VIX Entry Close": "",
            "VIX Change From Open %": "",
            "VIX 15m Change": "",
            "VIX 15m Trend": "MISSING",
            "VIX Filter": "REVIEW",
            "VIX Filter Reason": "Missing 09:15 or entry VIX candle",
        }

    vix_open = float(open_915.iloc[0])
    vix_entry = float(entry_row["close"].iloc[0])
    vix_change_pct = ((vix_entry / vix_open) - 1.0) * 100.0 if vix_open else 0.0
    vix_15m_change = float(upto_entry["close"].iloc[-1] - upto_entry["close"].iloc[0])
    if vix_15m_change > 0.02:
        trend = "RISING"
    elif vix_15m_change < -0.02:
        trend = "FALLING"
    else:
        trend = "FLAT"

    reasons = []
    if vix_change_pct < 0:
        reasons.append("VIX below 09:15 open")
    if vix_15m_change < -0.02:
        reasons.append("VIX falling into entry")
    decision = "TAKE" if not reasons else "SKIP"
    return {
        "VIX 09:15 Open": round(vix_open, 2),
        "VIX Entry Close": round(vix_entry, 2),
        "VIX Change From Open %": round(vix_change_pct, 2),
        "VIX 15m Change": round(vix_15m_change, 2),
        "VIX 15m Trend": trend,
        "VIX Filter": decision,
        "VIX Filter Reason": "OK" if decision == "TAKE" else "; ".join(reasons),
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "trades").mkdir(exist_ok=True)
    (OUT_DIR / "reports").mkdir(exist_ok=True)
    (OUT_DIR / "excel").mkdir(exist_ok=True)

    trades = pd.read_csv(SRC_OUTPUT / "trades" / "all_trades.csv")
    trades["date"] = pd.to_datetime(trades["date"]).dt.strftime("%Y-%m-%d")
    trades["entry_dt"] = pd.to_datetime(trades["entry_time"])
    trades["exit_dt"] = pd.to_datetime(trades["exit_time"])
    june = trades[trades["date"].str.startswith("2026-06")].copy()
    june = june.sort_values(["entry_dt", "strike", "option_type"]).reset_index(drop=True)

    spot = pd.read_csv(ROOT / "data" / "nifty_spot" / "NIFTY_5minute_2025-04-01_to_2026-06-25.csv")
    spot.columns = [c.strip().lower() for c in spot.columns]
    dt_col = "datetime" if "datetime" in spot.columns else "date"
    spot["dt"] = pd.to_datetime(spot[dt_col], errors="coerce")
    spot["date"] = spot["dt"].dt.strftime("%Y-%m-%d")
    spot["time"] = spot["dt"].dt.strftime("%H:%M")
    spot_915 = spot[spot["time"] == "09:15"].copy()
    spot_915["NIFTY 09:15 Open"] = pd.to_numeric(spot_915["open"], errors="coerce")
    spot_map = spot_915.set_index("date")["NIFTY 09:15 Open"].to_dict()
    vix = load_vix()

    chart_files = {p.name[6:16]: p.name for p in (ROOT / "data" / "charts" / "jun_nifty_open").glob("*.html")}

    trade_rows: list[dict[str, object]] = []
    for _, row in june.iterrows():
        entry = float(row["entry_price"])
        exit_ = float(row["exit_price"])
        charge = charges_for_trade(entry, exit_)
        nifty_open = spot_map.get(row["date"])
        atm = nearest_atm(float(nifty_open)) if nifty_open is not None else ""
        item = {
            "Date": row["date"],
            "Entry Time": clean_time(row["entry_time"]),
            "Exit Time": clean_time(row["exit_time"]),
            "NIFTY 09:15 Open": nifty_open,
            "ATM": atm,
            "Strike": int(row["strike"]),
            "Side": row["option_type"],
            "Setup": row["setup"],
            "Entry Premium": entry,
            "Exit Premium": exit_,
            "Points P&L": float(row["pnl"]),
            "Pivot": float(row["pivot"]),
            "Entry Distance From Pivot": round(entry - float(row["pivot"]), 2),
            "Candle Range": float(row["candle_range"]),
            "Max Favorable Points": float(row["max_favorable_points"]),
            "C2C Activated": to_bool(row["c2c_activated"]),
            "Trailing Activated": to_bool(row["trailing_activated"]),
            "Exit Reason": row["exit_reason"],
            "Qty": QTY,
            "Chart File": chart_files.get(row["date"], ""),
        }
        item.update(charge)
        item.update(vix_context(vix, row["date"], item["Entry Time"]))
        trade_rows.append(item)

    trade_df = pd.DataFrame(trade_rows)
    trade_df.to_csv(OUT_DIR / "trades" / "june_sweetspot_trades.csv", index=False)

    if trade_df.empty:
        daily = pd.DataFrame()
    else:
        daily = (
            trade_df.groupby("Date", as_index=False)
            .agg(
                Trades=("Date", "count"),
                Points=("Points P&L", "sum"),
                Gross_Rupee_PnL=("Gross Rupee P&L", "sum"),
                Total_Charges=("Total Charges", "sum"),
                Net_Rupee_PnL=("Net Rupee P&L", "sum"),
                Capital_Used=("Capital Used", "max"),
            )
            .sort_values("Date")
        )
        daily["Result"] = daily["Net_Rupee_PnL"].map(lambda x: "Win" if x > 0 else "Loss")
    daily.to_csv(OUT_DIR / "reports" / "june_daily_summary.csv", index=False)

    chart_dates = sorted(chart_files)
    trade_dates = set(trade_df["Date"]) if not trade_df.empty else set()
    no_trade_rows = []
    for date in chart_dates:
        if date not in trade_dates:
            nifty_open = spot_map.get(date)
            no_trade_rows.append(
                {
                    "Date": date,
                    "NIFTY 09:15 Open": nifty_open,
                    "ATM": nearest_atm(float(nifty_open)) if nifty_open is not None else "",
                    "Chart File": chart_files[date],
                    "Reason": "No Sweet Spot trade triggered by selected config",
                }
            )
    no_trade = pd.DataFrame(no_trade_rows)
    no_trade.to_csv(OUT_DIR / "reports" / "june_no_trade_days.csv", index=False)

    total_points = float(trade_df["Points P&L"].sum()) if not trade_df.empty else 0.0
    gross = float(trade_df["Gross Rupee P&L"].sum()) if not trade_df.empty else 0.0
    charges = float(trade_df["Total Charges"].sum()) if not trade_df.empty else 0.0
    net = float(trade_df["Net Rupee P&L"].sum()) if not trade_df.empty else 0.0
    wins = int((trade_df["Net Rupee P&L"] > 0).sum()) if not trade_df.empty else 0
    filtered = trade_df[trade_df["VIX Filter"] == "TAKE"].copy() if not trade_df.empty else trade_df
    filtered_points = float(filtered["Points P&L"].sum()) if not filtered.empty else 0.0
    filtered_net = float(filtered["Net Rupee P&L"].sum()) if not filtered.empty else 0.0
    summary = [
        ["Strategy", STRATEGY_NAME],
        ["Month", "2026-06"],
        ["Quantity", QTY],
        ["Trades", int(len(trade_df))],
        ["Winning Trades", wins],
        ["Losing Trades", int(len(trade_df) - wins)],
        ["Win Rate", wins / len(trade_df) if len(trade_df) else 0],
        ["Total Points", round(total_points, 2)],
        ["Gross Rupee P&L", round(gross, 0)],
        ["Total Charges", round(charges, 0)],
        ["Net Rupee P&L", round(net, 0)],
        ["Best Trade Points", round(float(trade_df["Points P&L"].max()), 2) if not trade_df.empty else 0],
        ["Worst Trade Points", round(float(trade_df["Points P&L"].min()), 2) if not trade_df.empty else 0],
        ["VIX Filter Rule", "TAKE only if VIX is not below 09:15 open and not falling over last 15 minutes"],
        ["VIX TAKE Trades", int(len(filtered))],
        ["VIX TAKE Points", round(filtered_points, 2)],
        ["VIX TAKE Net Rupee P&L", round(filtered_net, 0)],
        ["VIX SKIP Trades", int(len(trade_df) - len(filtered))],
        ["Chart Days Reviewed", len(chart_dates)],
        ["No-Trade Chart Days", len(no_trade)],
        ["Config File", CONFIG_FILE],
    ]

    payload = {
        "summary": summary,
        "trades": records_for_json(trade_df),
        "daily": records_for_json(daily),
        "noTradeDays": records_for_json(no_trade),
    }
    (OUT_DIR / "excel" / "june_sweetspot_workbook_data.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Trades: {len(trade_df)}")
    print(f"Points: {total_points:.2f}")
    print(f"Net: {net:.0f}")
    print(f"Saved: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
