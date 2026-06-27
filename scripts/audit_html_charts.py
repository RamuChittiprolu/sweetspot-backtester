from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CHART_DIR = ROOT / "data" / "charts" / "jun_nifty_open"
OUT_DIR = ROOT / "output" / "chart_audit"


FILENAME_RE = re.compile(r"Nifty_(\d{4}-\d{2}-\d{2})_(\d{5})CE_Open_PE\.html$", re.IGNORECASE)
CE_RE = re.compile(r"const\s+ceCandlesData\s*=\s*(\[.*?\]);\s*const\s+peCandlesData", re.S)
PE_RE = re.compile(r"const\s+peCandlesData\s*=\s*(\[.*?\]);", re.S)


def extract_array(pattern: re.Pattern[str], text: str, path: Path) -> list[dict]:
    match = pattern.search(text)
    if not match:
        raise ValueError(f"{path.name}: could not find embedded candle array")
    return json.loads(match.group(1))


def to_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    # The exported lightweight-chart timestamps encode the exchange clock as UTC seconds.
    # For example, the first candle displays as 09:15 in the chart but would become
    # 14:45 if converted to Asia/Kolkata. Keep the UTC clock for audit alignment.
    df["datetime_chart"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_localize(None)
    df["clock"] = df["datetime_chart"].dt.strftime("%H:%M")
    return df


def first_at_or_after(df: pd.DataFrame, clock: str) -> pd.Series | None:
    rows = df[df["clock"] >= clock].sort_values("datetime_chart")
    return None if rows.empty else rows.iloc[0]


def summarize_chart(path: Path) -> dict[str, object]:
    match = FILENAME_RE.match(path.name)
    if not match:
        raise ValueError(f"Unexpected chart filename: {path.name}")
    trade_date = match.group(1)
    strike = int(match.group(2))
    text = path.read_text(encoding="utf-8", errors="replace")
    ce = to_frame(extract_array(CE_RE, text, path))
    pe = to_frame(extract_array(PE_RE, text, path))

    ce_first = ce.iloc[0]
    pe_first = pe.iloc[0]
    ce_0920 = first_at_or_after(ce, "09:20")
    pe_0920 = first_at_or_after(pe, "09:20")
    ce_0925 = first_at_or_after(ce, "09:25")
    pe_0925 = first_at_or_after(pe, "09:25")

    pivot = (float(ce_first["open"]) + float(pe_first["open"])) / 2.0
    ce_above_pivot = int((ce["close"] > pivot).sum())
    pe_above_pivot = int((pe["close"] > pivot).sum())
    both_below_pivot = int(((ce["close"] < pivot) & (pe["close"] < pivot)).sum())

    ce_first_break = ce[ce["close"] > pivot].head(1)
    pe_first_break = pe[pe["close"] > pivot].head(1)
    ce_first_break_time = "" if ce_first_break.empty else ce_first_break.iloc[0]["clock"]
    pe_first_break_time = "" if pe_first_break.empty else pe_first_break.iloc[0]["clock"]

    return {
        "date": trade_date,
        "strike": strike,
        "chart_start": ce_first["clock"],
        "chart_end": ce.iloc[-1]["clock"],
        "candles": len(ce),
        "ce_0915_open": float(ce_first["open"]),
        "pe_0915_open": float(pe_first["open"]),
        "pivot": round(pivot, 2),
        "ce_0920_close": None if ce_0920 is None else float(ce_0920["close"]),
        "pe_0920_close": None if pe_0920 is None else float(pe_0920["close"]),
        "ce_0925_open": None if ce_0925 is None else float(ce_0925["open"]),
        "pe_0925_open": None if pe_0925 is None else float(pe_0925["open"]),
        "ce_above_pivot_candles": ce_above_pivot,
        "pe_above_pivot_candles": pe_above_pivot,
        "both_below_pivot_candles": both_below_pivot,
        "ce_first_close_above_pivot": ce_first_break_time,
        "pe_first_close_above_pivot": pe_first_break_time,
        "ce_day_high": float(ce["high"].max()),
        "pe_day_high": float(pe["high"].max()),
        "ce_day_low": float(ce["low"].min()),
        "pe_day_low": float(pe["low"].min()),
        "filename": path.name,
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(CHART_DIR.glob("*.html"))
    rows = []
    errors = []
    for path in files:
        try:
            rows.append(summarize_chart(path))
        except Exception as exc:
            errors.append({"filename": path.name, "error": str(exc)})

    audit = pd.DataFrame(rows)
    if not audit.empty:
        audit.to_csv(OUT_DIR / "jun_nifty_open_chart_audit.csv", index=False)
    if errors:
        pd.DataFrame(errors).to_csv(OUT_DIR / "jun_nifty_open_chart_audit_errors.csv", index=False)

    print(f"charts: {len(files)}")
    print(f"parsed: {len(rows)}")
    print(f"errors: {len(errors)}")
    if not audit.empty:
        cols = [
            "date",
            "strike",
            "chart_start",
            "chart_end",
            "pivot",
            "ce_0920_close",
            "pe_0920_close",
            "ce_first_close_above_pivot",
            "pe_first_close_above_pivot",
            "ce_above_pivot_candles",
            "pe_above_pivot_candles",
            "both_below_pivot_candles",
        ]
        print(audit[cols].to_string(index=False))
        print(f"saved: {OUT_DIR / 'jun_nifty_open_chart_audit.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
