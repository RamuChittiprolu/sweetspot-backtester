import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve("..");
const inputPath = path.join(root, "output", "excel", "straddle_130_workbook_data.json");
const outputDir = path.join(root, "output", "excel");
const outputPath = path.join(outputDir, "Nifty_0920_Straddle_Basket_130_Qty.xlsx");
const data = JSON.parse(await fs.readFile(inputPath, "utf8"));

function toExcelDate(value) {
  return new Date(`${value}T00:00:00`);
}

function writeTable(sheet, startCell, headers, rows) {
  const matrix = [headers, ...rows];
  sheet.getRange(startCell).write(matrix);
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

function setTitle(range) {
  range.format = {
    fill: "#0B2545",
    font: { bold: true, color: "#FFFFFF", size: 15 },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
}

function setSection(range) {
  range.format = {
    fill: "#E8EEF5",
    font: { bold: true, color: "#0B2545" },
  };
}

function setNumericFormats(sheet, ranges) {
  for (const [addr, fmt] of ranges) {
    sheet.getRange(addr).format.numberFormat = fmt;
  }
}

const workbook = Workbook.create();

const summary = workbook.worksheets.add("Summary");
const monthly = workbook.worksheets.add("Monthly");
const daily = workbook.worksheets.add("Daily Trades");
const legs = workbook.worksheets.add("Leg Trades");
const sources = workbook.worksheets.add("Sources");

for (const sheet of [summary, monthly, daily, legs, sources]) {
  sheet.showGridLines = false;
}

// Summary
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["NIFTY 09:20 Straddle Basket - 130 Quantity Workbook"]];
setTitle(summary.getRange("A1:H1"));
summary.getRange("A3:B14").values = data.summary;
summary.getRange("A3:A14").format = { fill: "#E8EEF5", font: { bold: true, color: "#0B2545" } };
summary.getRange("A3:B14").format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
summary.getRange("B10:B14").format.numberFormat = "#,##0";
summary.getRange("D3:H3").merge();
summary.getRange("D3").values = [["How to read this workbook"]];
setSection(summary.getRange("D3:H3"));
summary.getRange("D4:H8").merge();
summary.getRange("D4").values = [[
  "Leg Trades has every straddle leg from the backtest. Daily Trades groups both legs into one daily basket. Monthly summarizes rupee P&L and capital used for 130 quantity. Charges, slippage, brokerage, and taxes are not deducted."
]];
summary.getRange("D4:H8").format = { wrapText: true, verticalAlignment: "top", fill: "#F8FAFC" };
summary.getRange("D4:H8").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
summary.getRange("A16:H16").merge();
summary.getRange("A16").values = [["Risk Reminder"]];
setSection(summary.getRange("A16:H16"));
summary.getRange("A17:H20").merge();
summary.getRange("A17").values = [[
  "The tested version uses no intraday stop-loss. The historical worst daily loss at 130 quantity was around Rs 23,276, and the worst tested month was around Rs -41,438. This is research output, not a live-trading guarantee."
]];
summary.getRange("A17:H20").format = { wrapText: true, verticalAlignment: "top", fill: "#FFF7ED", font: { color: "#7C2D12" } };
summary.getRange("A17:H20").format.borders = { preset: "outside", style: "thin", color: "#FDBA74" };
summary.getRange("A:A").format.columnWidth = 28;
summary.getRange("B:B").format.columnWidth = 24;
summary.getRange("D:H").format.columnWidth = 18;

// Monthly
monthly.getRange("A1:L1").merge();
monthly.getRange("A1").values = [["Monthly Summary - 130 Quantity"]];
setTitle(monthly.getRange("A1:L1"));
const monthlyHeaders = [
  "Month", "Trading Days", "Winning Days", "Losing Days", "Win Rate", "Points",
  "Rupee P&L", "Avg Daily Points", "Max Daily Gain", "Max Daily Loss", "Max Capital Used", "Avg Capital Used"
];
const monthlyRows = data.monthly.map((r) => [
  r["Month"], r["Trading Days"], r["Winning Days"], r["Losing Days"], r["Win Rate"], r["Points"],
  r["Rupee P&L"], r["Avg Daily Points"], r["Max Daily Gain"], r["Max Daily Loss"], r["Max Capital Used"], r["Avg Capital Used"]
]);
writeTable(monthly, "A3", monthlyHeaders, monthlyRows);
setHeader(monthly.getRange("A3:L3"));
monthly.getRange(`A3:L${monthlyRows.length + 3}`).format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
setNumericFormats(monthly, [
  [`E4:E${monthlyRows.length + 3}`, "0.0%"],
  [`F4:F${monthlyRows.length + 3}`, "#,##0.00"],
  [`G4:G${monthlyRows.length + 3}`, "\"Rs\" #,##0"],
  [`H4:J${monthlyRows.length + 3}`, "#,##0.00"],
  [`K4:L${monthlyRows.length + 3}`, "\"Rs\" #,##0"],
]);
monthly.freezePanes.freezeRows(3);
monthly.getRange("A:L").format.autofitColumns();

// Daily
daily.getRange("A1:J1").merge();
daily.getRange("A1").values = [["Daily Basket Trades - 130 Quantity"]];
setTitle(daily.getRange("A1:J1"));
const dailyHeaders = [
  "Date", "Month", "NIFTY 09:15 Open", "ATM", "Entry Premium", "Exit Premium",
  "Points P&L", "Rupee P&L", "Capital Used", "Result"
];
const dailyRows = data.daily.map((r) => [
  toExcelDate(r["Date"]), r["Month"], r["NIFTY 09:15 Open"], r["ATM"], r["Entry Premium"], r["Exit Premium"],
  r["Points P&L"], r["Rupee P&L"], r["Capital Used"], r["Result"]
]);
writeTable(daily, "A3", dailyHeaders, dailyRows);
setHeader(daily.getRange("A3:J3"));
daily.getRange(`A3:J${dailyRows.length + 3}`).format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
setNumericFormats(daily, [
  [`A4:A${dailyRows.length + 3}`, "yyyy-mm-dd"],
  [`C4:F${dailyRows.length + 3}`, "#,##0.00"],
  [`G4:G${dailyRows.length + 3}`, "#,##0.00"],
  [`H4:I${dailyRows.length + 3}`, "\"Rs\" #,##0"],
]);
daily.freezePanes.freezeRows(3);
daily.getRange("A:J").format.autofitColumns();

// Leg Trades
legs.getRange("A1:P1").merge();
legs.getRange("A1").values = [["Detailed Leg Trades - 130 Quantity"]];
setTitle(legs.getRange("A1:P1"));
const legHeaders = [
  "Date", "Month", "Entry Time", "NIFTY 09:15 Open", "ATM", "Leg", "Offset", "Strike",
  "Entry Premium", "Target Premium", "Exit Premium", "Points P&L", "Qty", "Rupee P&L",
  "Capital Used", "Exit Reason"
];
const legRows = data.legTrades.map((r) => [
  toExcelDate(r["Date"]), r["Month"], r["Entry Time"], r["NIFTY 09:15 Open"], r["ATM"], r["Leg"], r["Offset"], r["Strike"],
  r["Entry Premium"], r["Target Premium"], r["Exit Premium"], r["Points P&L"], null, null, null, r["Exit Reason"]
]);
writeTable(legs, "A3", legHeaders, legRows);
setHeader(legs.getRange("A3:P3"));
const legLast = legRows.length + 3;
legs.getRange("M4").formulas = [["='Summary'!$B$3"]];
legs.getRange(`M4:M${legLast}`).fillDown();
legs.getRange("N4").formulas = [["=L4*M4"]];
legs.getRange(`N4:N${legLast}`).fillDown();
legs.getRange("O4").formulas = [["=I4*M4"]];
legs.getRange(`O4:O${legLast}`).fillDown();
legs.getRange(`A3:P${legLast}`).format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
setNumericFormats(legs, [
  [`A4:A${legLast}`, "yyyy-mm-dd"],
  [`D4:E${legLast}`, "#,##0.00"],
  [`G4:H${legLast}`, "#,##0"],
  [`I4:L${legLast}`, "#,##0.00"],
  [`M4:M${legLast}`, "#,##0"],
  [`N4:O${legLast}`, "\"Rs\" #,##0"],
]);
legs.freezePanes.freezeRows(3);
legs.getRange("A:P").format.autofitColumns();
legs.getRange("F:F").format.columnWidth = 20;

// Sources
sources.getRange("A1:D1").merge();
sources.getRange("A1").values = [["Sources and Notes"]];
setTitle(sources.getRange("A1:D1"));
sources.getRange("A3:B9").values = [
  ["Source trade file", "output/research_straddle/straddle_0920_atm_minus50_basket_trades.csv"],
  ["Backtest rule", "09:20 long straddle basket: ATM -50 straddle + ATM straddle"],
  ["Quantity", "130"],
  ["Costs included?", "No brokerage, STT, exchange fees, GST, slippage, or liquidity impact deducted"],
  ["Expiry selection", "Nearest available expiry on or after the trade date"],
  ["Target", "15% per straddle"],
  ["Square-off", "15:15 if target not hit"],
];
sources.getRange("A3:A9").format = { fill: "#E8EEF5", font: { bold: true, color: "#0B2545" } };
sources.getRange("A3:B9").format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
sources.getRange("A:A").format.columnWidth = 24;
sources.getRange("B:B").format.columnWidth = 90;
sources.getRange("B:B").format.wrapText = true;

// Conditional formatting for P&L columns.
monthly.getRange(`G4:G${monthlyRows.length + 3}`).conditionalFormats.add("cellIs", {
  operator: "greaterThanOrEqual",
  formula: 0,
  format: { fill: "#DCFCE7", font: { color: "#166534" } },
});
monthly.getRange(`G4:G${monthlyRows.length + 3}`).conditionalFormats.add("cellIs", {
  operator: "lessThan",
  formula: 0,
  format: { fill: "#FEE2E2", font: { color: "#991B1B" } },
});
daily.getRange(`H4:H${dailyRows.length + 3}`).conditionalFormats.add("cellIs", {
  operator: "greaterThanOrEqual",
  formula: 0,
  format: { fill: "#DCFCE7", font: { color: "#166534" } },
});
daily.getRange(`H4:H${dailyRows.length + 3}`).conditionalFormats.add("cellIs", {
  operator: "lessThan",
  formula: 0,
  format: { fill: "#FEE2E2", font: { color: "#991B1B" } },
});

// Chart on Summary from Monthly.
const chart = summary.charts.add("line", monthly.getRange(`A3:G${monthlyRows.length + 3}`));
chart.title = "Monthly Rupee P&L";
chart.hasLegend = false;
chart.xAxis = { axisType: "textAxis" };
chart.yAxis = { numberFormatCode: "\"Rs\" #,##0" };
chart.setPosition("D10", "H25");

// Verification renders.
await fs.mkdir(outputDir, { recursive: true });
for (const sheetName of ["Summary", "Monthly", "Daily Trades", "Leg Trades"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(
    path.join(outputDir, `preview_${sheetName.replaceAll(" ", "_")}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const inspect = await workbook.inspect({
  kind: "table",
  sheetId: "Summary",
  range: "A1:H20",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 8,
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
