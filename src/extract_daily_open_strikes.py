from __future__ import annotations

import argparse
import csv
import math
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "nifty_15minute_2026-01-01_to_2026-06-19.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "nifty_daily_0915_open_strikes.csv"
DEFAULT_OPEN_TIME = "09:15"
DEFAULT_STRIKE_STEP = 50


def parse_timestamp(raw: str) -> datetime:
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    if len(value) >= 5 and value[-5] in {"+", "-"} and value[-3] != ":":
        value = f"{value[:-2]}:{value[-2:]}"
    return datetime.fromisoformat(value)


def nearest_strike(price: float, strike_step: int) -> int:
    return int(math.floor((price / strike_step) + 0.5) * strike_step)


def extract_open_strikes(input_path: Path, open_time: str, strike_step: int) -> list[dict[str, object]]:
    rows_by_date: dict[str, dict[str, object]] = {}

    with input_path.open(newline="", encoding="utf-8") as input_file:
        reader = csv.DictReader(input_file)
        required = {"datetime", "open"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{input_path} missing required columns: {', '.join(sorted(missing))}")

        for row in reader:
            timestamp = parse_timestamp(row["datetime"])
            if timestamp.strftime("%H:%M") != open_time:
                continue

            trade_date = timestamp.date().isoformat()
            open_price = float(row["open"])
            rows_by_date.setdefault(
                trade_date,
                {
                    "trade_date": trade_date,
                    "open_time": timestamp.strftime("%H:%M:%S"),
                    "nifty_open": open_price,
                    "nearest_strike": nearest_strike(open_price, strike_step),
                },
            )

    return [rows_by_date[trade_date] for trade_date in sorted(rows_by_date)]


def write_output(output_path: Path, rows: list[dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=["trade_date", "open_time", "nifty_open", "nearest_strike"],
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract daily 09:15 NIFTY open and nearest strike from 15-minute candles.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--open-time", default=DEFAULT_OPEN_TIME)
    parser.add_argument("--strike-step", type=int, default=DEFAULT_STRIKE_STEP)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 2
    if args.strike_step <= 0:
        print("--strike-step must be positive.", file=sys.stderr)
        return 2

    rows = extract_open_strikes(args.input, args.open_time, args.strike_step)
    write_output(args.output, rows)
    print(f"Saved {len(rows)} daily open strikes to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
