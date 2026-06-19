from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time as datetime_time, timedelta
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INSTRUMENT_TOKEN = "256265"  # NSE:NIFTY 50 index
DEFAULT_INTERVAL = "15minute"
DEFAULT_FROM_DATE = "2026-01-01"
KITE_HISTORICAL_URL = "https://api.kite.trade/instruments/historical"


class KiteDownloadError(RuntimeError):
    pass


def _parse_date(raw: str) -> date:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {raw!r}") from exc


def _parse_time(raw: str) -> datetime_time:
    try:
        return datetime.strptime(raw, "%H:%M:%S").time()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected HH:MM:SS, got {raw!r}") from exc


def _format_kite_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _request_json(
    url: str,
    api_key: str,
    access_token: str,
    retries: int,
    retry_sleep_seconds: float,
) -> dict[str, Any]:
    headers = {
        "X-Kite-Version": "3",
        "Authorization": f"token {api_key}:{access_token}",
    }

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = KiteDownloadError(f"HTTP {exc.code}: {body}")
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries:
                raise last_error from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == retries:
                raise KiteDownloadError(str(exc)) from exc

        time.sleep(retry_sleep_seconds * (attempt + 1))

    raise KiteDownloadError(str(last_error))


def fetch_historical_chunk(
    instrument_token: str,
    interval: str,
    start: datetime,
    end: datetime,
    api_key: str,
    access_token: str,
    retries: int,
    retry_sleep_seconds: float,
) -> list[list[Any]]:
    query = urllib.parse.urlencode(
        {
            "from": _format_kite_datetime(start),
            "to": _format_kite_datetime(end),
        }
    )
    url = f"{KITE_HISTORICAL_URL}/{instrument_token}/{interval}?{query}"
    response = _request_json(
        url=url,
        api_key=api_key,
        access_token=access_token,
        retries=retries,
        retry_sleep_seconds=retry_sleep_seconds,
    )

    if response.get("status") != "success":
        raise KiteDownloadError(f"unexpected response: {response}")

    candles = response.get("data", {}).get("candles")
    if not isinstance(candles, list):
        raise KiteDownloadError(f"missing candles in response: {response}")
    return candles


def iter_date_chunks(start_date: date, end_date: date, chunk_days: int) -> list[tuple[date, date]]:
    chunks = []
    current = start_date
    while current <= end_date:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def write_candles(path: Path, candles: list[list[Any]]) -> None:
    seen: set[str] = set()
    rows = []
    for candle in candles:
        if len(candle) < 6:
            continue
        timestamp = str(candle[0])
        if timestamp in seen:
            continue
        seen.add(timestamp)
        rows.append(
            {
                "datetime": timestamp,
                "open": candle[1],
                "high": candle[2],
                "low": candle[3],
                "close": candle[4],
                "volume": candle[5],
            }
        )

    rows.sort(key=lambda row: row["datetime"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=["datetime", "open", "high", "low", "close", "volume"],
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    today = date.today()
    parser = argparse.ArgumentParser(
        description="Download NIFTY 50 historical candles from Zerodha Kite Connect.",
    )
    parser.add_argument("--from-date", type=_parse_date, default=_parse_date(DEFAULT_FROM_DATE))
    parser.add_argument("--to-date", type=_parse_date, default=today)
    parser.add_argument("--market-open", type=_parse_time, default=_parse_time("09:15:00"))
    parser.add_argument("--market-close", type=_parse_time, default=_parse_time("15:30:00"))
    parser.add_argument("--instrument-token", default=DEFAULT_INSTRUMENT_TOKEN)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--chunk-days", type=int, default=60)
    parser.add_argument("--sleep-seconds", type=float, default=0.35)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-sleep-seconds", type=float, default=2.0)
    parser.add_argument("--api-key", default=os.getenv("KITE_API_KEY"))
    parser.add_argument("--access-token", default=os.getenv("KITE_ACCESS_TOKEN"))
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / f"nifty_15minute_{DEFAULT_FROM_DATE}_to_{today.isoformat()}.csv",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.api_key:
        print("Missing API key. Set KITE_API_KEY or pass --api-key.", file=sys.stderr)
        return 2
    if not args.access_token:
        print("Missing access token. Set KITE_ACCESS_TOKEN or pass --access-token.", file=sys.stderr)
        return 2
    if args.from_date > args.to_date:
        print("--from-date cannot be after --to-date.", file=sys.stderr)
        return 2
    if args.chunk_days < 1:
        print("--chunk-days must be at least 1.", file=sys.stderr)
        return 2

    all_candles: list[list[Any]] = []
    chunks = iter_date_chunks(args.from_date, args.to_date, args.chunk_days)
    for index, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        start = datetime.combine(chunk_start, args.market_open)
        end = datetime.combine(chunk_end, args.market_close)
        print(
            f"[{index}/{len(chunks)}] Downloading {args.interval} candles "
            f"from {_format_kite_datetime(start)} to {_format_kite_datetime(end)}"
        )
        all_candles.extend(
            fetch_historical_chunk(
                instrument_token=args.instrument_token,
                interval=args.interval,
                start=start,
                end=end,
                api_key=args.api_key,
                access_token=args.access_token,
                retries=args.retries,
                retry_sleep_seconds=args.retry_sleep_seconds,
            )
        )
        if index < len(chunks):
            time.sleep(args.sleep_seconds)

    write_candles(args.output, all_candles)
    print(f"Saved {len({str(candle[0]) for candle in all_candles if candle})} candles to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
