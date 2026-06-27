import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve("..");
const inputPath = path.join(root, "output", "excel", "straddle_ce_pe_leg_workbook_data.json");
const outputDir = path.join(root, "output", "excel");
const analysisMode = process.env.STRADDLE_ANALYSIS_MODE ?? "all";
const isExpiryOnly = analysisMode === "expiry_only";
const outputPath = path.join(
  outputDir,
  isExpiryOnly
    ? "Nifty_0920_Straddle_Basket_Expiry_Days_CE_PE_Legs_130_Qty.xlsx"
    : "Nifty_0920_Straddle_Basket_CE_PE_Legs_130_Qty.xlsx",
);
const data = JSON.parse(await fs.readFile(inputPath, "utf8"));

function dateValue(row) {
  return new Date(`${row["Date"]}T00:00:00`).getTime();
}

function sortDailyDesc(rows) {
  return [...rows].sort((a, b) => dateValue(b) - dateValue(a));
}

function sortTradeDesc(rows) {
  const sideOrder = { CE: 0, PE: 1 };
  return [...rows].sort((a, b) => {
    const dateDiff = dateValue(b) - dateValue(a);
    if (dateDiff !== 0) return dateDiff;
    const offsetDiff = Number(a["Offset"]) - Number(b["Offset"]);
    if (offsetDiff !== 0) return offsetDiff;
    const strikeDiff = Number(a["Strike"]) - Number(b["Strike"]);
    if (strikeDiff !== 0) return strikeDiff;
    return (sideOrder[a["Side"]] ?? 9) - (sideOrder[b["Side"]] ?? 9);
  });
}

function parseDateOnly(value) {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function toDateString(date) {
  return date.toISOString().slice(0, 10);
}

function weekStartMonday(date) {
  const d = new Date(date.getTime());
  const day = d.getUTCDay();
  const diff = day === 0 ? -6 : 1 - day;
  d.setUTCDate(d.getUTCDate() + diff);
  return d;
}

function addDays(date, days) {
  const d = new Date(date.getTime());
  d.setUTCDate(d.getUTCDate() + days);
  return d;
}

function buildExpiryDateSet(rows) {
  const allDates = [...new Set(rows.map((row) => row["Date"]))].sort();
  const weeks = new Map();
  for (const value of allDates) {
    const monday = toDateString(weekStartMonday(parseDateOnly(value)));
    if (!weeks.has(monday)) weeks.set(monday, []);
    weeks.get(monday).push(value);
  }

  const expiryDates = new Set();
  for (const [mondayValue, dates] of weeks.entries()) {
    const monday = parseDateOnly(mondayValue);
    const revisedRule = dates[0] >= "2025-09-01";
    const targetValue = toDateString(addDays(monday, revisedRule ? 1 : 3));
    const candidates = dates.filter((value) => value <= targetValue);
    if (candidates.length) {
      expiryDates.add(candidates[candidates.length - 1]);
    }
  }
  return expiryDates;
}

const expiryDates = buildExpiryDateSet(data.daily);
const filteredDailySource = isExpiryOnly
  ? data.daily.filter((row) => expiryDates.has(row["Date"]))
  : data.daily;
const filteredStraddleSource = isExpiryOnly
  ? data.straddles.filter((row) => expiryDates.has(row["Date"]))
  : data.straddles;
const filteredOptionLegSource = isExpiryOnly
  ? data.optionLegs.filter((row) => expiryDates.has(row["Date"]))
  : data.optionLegs;

const dailyData = sortDailyDesc(filteredDailySource);
const straddleData = sortTradeDesc(filteredStraddleSource);
const optionLegData = sortTradeDesc(filteredOptionLegSource);

function sumRows(rows, key) {
  return rows.reduce((total, row) => total + Number(row[key] ?? 0), 0);
}

function buildSummaryRows() {
  const dailyCount = filteredDailySource.length;
  const winningDays = filteredDailySource.filter((row) => Number(row["Net Rupee P&L"]) >= 0).length;
  return [
    ["Strategy", "09:20 long straddle basket"],
    ["Basket", "ATM -50 straddle + ATM straddle"],
    ["Quantity", 130],
    ["Target", "15% per straddle"],
    ["Stop Loss", "None"],
    ["Analysis Filter", isExpiryOnly ? "Actual NIFTY expiry sessions only" : "All available sessions"],
    ["Option leg rows", optionLegData.length],
    ["Straddle component rows", straddleData.length],
    ["Daily rows", dailyCount],
    ["Win rate", dailyCount ? winningDays / dailyCount : 0],
    ["Total points", sumRows(filteredDailySource, "Points P&L")],
    ["Total gross rupee P&L", sumRows(filteredDailySource, "Gross Rupee P&L")],
    ["Total charges", sumRows(filteredDailySource, "Total Charges")],
    ["Total net rupee P&L", sumRows(filteredDailySource, "Net Rupee P&L")],
    ["Important note", "TARGET rows use estimated CE/PE allocation from the target candle high because 5-minute OHLC does not show the exact tick split."],
  ];
}

function toExcelDate(value) {
  return new Date(`${value}T00:00:00`);
}

function writeTable(sheet, startCell, headers, rows) {
  sheet.getRange(startCell).write([headers, ...rows]);
}

function setTitle(range) {
  range.format = {
    fill: "#0B2545",
    font: { bold: true, color: "#FFFFFF", size: 15 },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
}

function setHeader(range) {
  range.format = {
    fill: "#1F4D78",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
}

function setSection(range) {
  range.format = {
    fill: "#E8EEF5",
    font: { bold: true, color: "#0B2545" },
  };
}

function colorPnL(sheet, range) {
  sheet.getRange(range).conditionalFormats.add("cellIs", {
    operator: "greaterThanOrEqual",
    formula: 0,
    format: { fill: "#DCFCE7", font: { color: "#166534" } },
  });
  sheet.getRange(range).conditionalFormats.add("cellIs", {
    operator: "lessThan",
    formula: 0,
    format: { fill: "#FEE2E2", font: { color: "#991B1B" } },
  });
}

function applyBasicTableStyle(sheet, range, headerRange) {
  setHeader(headerRange);
  sheet.getRange(range).format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
}

const workbook = Workbook.create();
const summary = workbook.worksheets.add("Summary");
const daily = workbook.worksheets.add("Daily");
const straddles = workbook.worksheets.add("Straddles");
const optionLegs = workbook.worksheets.add("CE_PE Legs");
const notes = workbook.worksheets.add("Notes");

for (const sheet of [summary, daily, straddles, optionLegs, notes]) {
  sheet.showGridLines = false;
}

summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [[
  isExpiryOnly
    ? "NIFTY 09:20 Straddle Basket - Expiry Day CE/PE Breakdown"
    : "NIFTY 09:20 Straddle Basket - CE/PE Leg Breakdown",
]];
setTitle(summary.getRange("A1:H1"));
const summaryRows = buildSummaryRows().map(([label, value]) =>
  label === "Important note" ? [label, "See the orange fill note on the right."] : [label, value],
);
summary.getRange("A3:B17").values = summaryRows;
summary.getRange("A3:A17").format = { fill: "#E8EEF5", font: { bold: true, color: "#0B2545" } };
summary.getRange("A3:B17").format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
summary.getRange("B5:B5").format.numberFormat = "#,##0";
summary.getRange("B9:B11").format.numberFormat = "#,##0";
summary.getRange("B12:B12").format.numberFormat = "0.0%";
summary.getRange("B13:B13").format.numberFormat = "#,##0.00";
summary.getRange("B14:B16").format.numberFormat = "\"Rs\" #,##0";
summary.getRange("D3:H3").merge();
summary.getRange("D3").values = [["How to read this workbook"]];
setSection(summary.getRange("D3:H3"));
summary.getRange("D4:H10").merge();
summary.getRange("D4").values = [[
  isExpiryOnly
    ? "This workbook keeps only actual NIFTY expiry sessions. From September 2025 onward, NIFTY expiry is treated as Tuesday; if that Tuesday is absent in the trading data, the previous available trading day in that week is treated as expiry. The CE_PE Legs sheet has one row for each option side."
    : "The CE_PE Legs sheet has one row for each option side. For a normal basket day you will see four rows: ATM -50 CE, ATM -50 PE, ATM CE, and ATM PE. The Straddles sheet sums CE+PE for each straddle. The Daily sheet sums both straddles for the day."
]];
summary.getRange("D4:H10").format = { wrapText: true, verticalAlignment: "top", fill: "#F8FAFC" };
summary.getRange("D4:H10").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
summary.getRange("D12:H12").merge();
summary.getRange("D12").values = [["Important fill note"]];
setSection(summary.getRange("D12:H12"));
summary.getRange("D13:H18").merge();
summary.getRange("D13").values = [[
  "For SQUAREOFF exits, CE and PE exit premiums are exact 5-minute close values. For TARGET exits, the straddle target is exact, but the CE/PE split is estimated from the exit candle high because 5-minute OHLC data does not reveal the exact tick-level split at the moment the combined target was touched."
]];
summary.getRange("D13:H18").format = { wrapText: true, verticalAlignment: "top", fill: "#FFF7ED", font: { color: "#7C2D12" } };
summary.getRange("D13:H18").format.borders = { preset: "outside", style: "thin", color: "#FDBA74" };
summary.getRange("A:A").format.columnWidth = 30;
summary.getRange("B:B").format.columnWidth = 34;
summary.getRange("D:H").format.columnWidth = 18;

const dailyHeaders = [
  "Date", "Month", "NIFTY 09:15 Open", "ATM", "Straddles Taken", "Option Legs",
  "Entry Premium", "Exit Premium", "Points P&L", "Gross Rupee P&L", "Total Charges",
  "Net Rupee P&L", "Capital Used", "Result",
];
const dailyRows = dailyData.map((r) => [
  toExcelDate(r["Date"]), r["Month"], r["NIFTY 09:15 Open"], r["ATM"], r["Straddles Taken"], r["Option Legs"],
  r["Entry Premium"], r["Exit Premium"], r["Points P&L"], r["Gross Rupee P&L"], r["Total Charges"],
  r["Net Rupee P&L"], r["Capital Used"], r["Result"],
]);
daily.getRange("A1:N1").merge();
daily.getRange("A1").values = [["Daily Basket Summary"]];
setTitle(daily.getRange("A1:N1"));
writeTable(daily, "A3", dailyHeaders, dailyRows);
const dailyLast = dailyRows.length + 3;
applyBasicTableStyle(daily, `A3:N${dailyLast}`, daily.getRange("A3:N3"));
daily.getRange(`A4:A${dailyLast}`).format.numberFormat = "yyyy-mm-dd";
daily.getRange(`C4:I${dailyLast}`).format.numberFormat = "#,##0.00";
daily.getRange(`J4:M${dailyLast}`).format.numberFormat = "\"Rs\" #,##0";
colorPnL(daily, `L4:L${dailyLast}`);
daily.freezePanes.freezeRows(3);
daily.getRange("A:N").format.autofitColumns();

const straddleHeaders = [
  "Date", "Month", "Entry Time", "Exit Time", "NIFTY 09:15 Open", "ATM", "Straddle", "Offset", "Strike",
  "Entry Premium", "Target Premium", "Exit Premium", "Points P&L", "Gross Rupee P&L", "Total Charges",
  "Net Rupee P&L", "Capital Used", "Exit Reason", "Fill Type",
];
const straddleRows = straddleData.map((r) => [
  toExcelDate(r["Date"]), r["Month"], r["Entry Time"], r["Exit Time"], r["NIFTY 09:15 Open"], r["ATM"],
  r["Straddle"], r["Offset"], r["Strike"], r["Entry Premium"], r["Target Premium"], r["Exit Premium"],
  r["Points P&L"], r["Gross Rupee P&L"], r["Total Charges"], r["Net Rupee P&L"], r["Capital Used"],
  r["Exit Reason"], r["Fill Type"],
]);
straddles.getRange("A1:S1").merge();
straddles.getRange("A1").values = [["Straddle Components - CE + PE Combined"]];
setTitle(straddles.getRange("A1:S1"));
writeTable(straddles, "A3", straddleHeaders, straddleRows);
const straddleLast = straddleRows.length + 3;
applyBasicTableStyle(straddles, `A3:S${straddleLast}`, straddles.getRange("A3:S3"));
straddles.getRange(`A4:A${straddleLast}`).format.numberFormat = "yyyy-mm-dd";
straddles.getRange(`E4:F${straddleLast}`).format.numberFormat = "#,##0.00";
straddles.getRange(`H4:I${straddleLast}`).format.numberFormat = "#,##0";
straddles.getRange(`J4:M${straddleLast}`).format.numberFormat = "#,##0.00";
straddles.getRange(`N4:Q${straddleLast}`).format.numberFormat = "\"Rs\" #,##0";
colorPnL(straddles, `P4:P${straddleLast}`);
straddles.freezePanes.freezeRows(3);
straddles.getRange("A:S").format.autofitColumns();
straddles.getRange("G:G").format.columnWidth = 20;
straddles.getRange("S:S").format.columnWidth = 30;

const optionHeaders = [
  "Date", "Month", "Entry Time", "Exit Time", "NIFTY 09:15 Open", "ATM", "Straddle", "Offset", "Strike",
  "Expiry", "Side", "Entry Premium", "Exit Premium", "Points P&L", "Qty", "Gross Rupee P&L",
  "Total Charges", "Net Rupee P&L", "Capital Used", "Buy Turnover", "Sell Turnover", "Stamp Duty",
  "Exit Reason", "Fill Type",
  "Exit Candle Close", "Exit Candle High", "Exit Candle Low", "Source File",
];
const optionRows = optionLegData.map((r) => [
  toExcelDate(r["Date"]), r["Month"], r["Entry Time"], r["Exit Time"], r["NIFTY 09:15 Open"], r["ATM"],
  r["Straddle"], r["Offset"], r["Strike"], toExcelDate(r["Expiry"]), r["Side"], r["Entry Premium"],
  r["Exit Premium"], r["Points P&L"], r["Qty"], r["Gross Rupee P&L"], r["Total Charges"],
  r["Net Rupee P&L"], r["Capital Used"], r["Buy Turnover"], r["Sell Turnover"], r["Stamp Duty"],
  r["Exit Reason"], r["Fill Type"], r["Exit Candle Close"], r["Exit Candle High"], r["Exit Candle Low"], r["Source File"],
]);
optionLegs.getRange("A1:AB1").merge();
optionLegs.getRange("A1").values = [["CE/PE Option Leg Trades - Four Rows Per Basket Day"]];
setTitle(optionLegs.getRange("A1:AB1"));
writeTable(optionLegs, "A3", optionHeaders, optionRows);
const optionLast = optionRows.length + 3;
applyBasicTableStyle(optionLegs, `A3:AB${optionLast}`, optionLegs.getRange("A3:AB3"));
optionLegs.getRange(`A4:A${optionLast}`).format.numberFormat = "yyyy-mm-dd";
optionLegs.getRange(`J4:J${optionLast}`).format.numberFormat = "yyyy-mm-dd";
optionLegs.getRange(`E4:F${optionLast}`).format.numberFormat = "#,##0.00";
optionLegs.getRange(`H4:I${optionLast}`).format.numberFormat = "#,##0";
optionLegs.getRange(`L4:N${optionLast}`).format.numberFormat = "#,##0.00";
optionLegs.getRange(`O4:O${optionLast}`).format.numberFormat = "#,##0";
optionLegs.getRange(`P4:V${optionLast}`).format.numberFormat = "\"Rs\" #,##0";
optionLegs.getRange(`Y4:AA${optionLast}`).format.numberFormat = "#,##0.00";
colorPnL(optionLegs, `R4:R${optionLast}`);
optionLegs.freezePanes.freezeRows(3);
optionLegs.getRange("A:AB").format.autofitColumns();
optionLegs.getRange("G:G").format.columnWidth = 20;
optionLegs.getRange("X:X").format.columnWidth = 32;
optionLegs.getRange("AB:AB").format.columnWidth = 42;

notes.getRange("A1:D1").merge();
notes.getRange("A1").values = [["Notes"]];
setTitle(notes.getRange("A1:D1"));
notes.getRange("A3:B10").values = [
  ["Source CSV", "output/research_straddle/straddle_0920_ce_pe_leg_trades.csv"],
  ["Strategy", "09:20 long straddle basket: ATM -50 straddle + ATM straddle"],
  ["Quantity", "130"],
  ["Target", "15% per straddle"],
  ["Stop loss", "None in this workbook"],
  ["Analysis filter", isExpiryOnly ? "Actual NIFTY expiry sessions only" : "All available sessions"],
  ["Exact values", "Entry premium and SQUAREOFF exit premium are exact 5-minute close values."],
  ["Expiry rule used", "Before September 1, 2025: Thursday. On/after September 1, 2025: Tuesday. If holiday/missing, previous available trading day in that week."],
];
notes.getRange("A3:A10").format = { fill: "#E8EEF5", font: { bold: true, color: "#0B2545" } };
notes.getRange("A3:B10").format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
notes.getRange("A:A").format.columnWidth = 24;
notes.getRange("B:B").format.columnWidth = 120;
notes.getRange("B:B").format.wrapText = true;

await fs.mkdir(outputDir, { recursive: true });
for (const sheetName of ["Summary", "Daily", "Straddles", "CE_PE Legs", "Notes"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(
    path.join(outputDir, `preview_ce_pe_${sheetName.replaceAll(" ", "_")}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const inspect = await workbook.inspect({
  kind: "table",
  sheetId: "CE_PE Legs",
  range: "A1:AB12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 28,
});
console.log(inspect.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(outputPath);
