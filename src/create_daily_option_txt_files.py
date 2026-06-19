from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "nifty_daily_0915_open_strikes.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "daily_option_txt_files"


def format_option_filename(trade_date: str, strike: int, side: str) -> str:
    parsed_date = datetime.strptime(trade_date, "%Y-%m-%d")
    return f"{parsed_date.day}-{parsed_date.strftime('%b')}-{strike}-{side}.txt"


def month_folder_name(trade_date: str) -> str:
    parsed_date = datetime.strptime(trade_date, "%Y-%m-%d")
    return parsed_date.strftime("%b")


def create_empty_option_files(input_path: Path, output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    created = 0

    with input_path.open(newline="", encoding="utf-8") as input_file:
        reader = csv.DictReader(input_file)
        required = {"trade_date", "nearest_strike"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{input_path} missing required columns: {', '.join(sorted(missing))}")

        for row in reader:
            trade_date = row["trade_date"].strip()
            strike = int(float(row["nearest_strike"]))
            month_dir = output_dir / month_folder_name(trade_date)
            month_dir.mkdir(parents=True, exist_ok=True)
            for side in ("CE", "PE"):
                file_path = month_dir / format_option_filename(trade_date, strike, side)
                if not file_path.exists():
                    created += 1
                file_path.touch()

    return created


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create empty CE/PE text files from daily NIFTY open strikes.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 2

    created = create_empty_option_files(args.input, args.output_dir)
    print(f"Created {created} empty files in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
