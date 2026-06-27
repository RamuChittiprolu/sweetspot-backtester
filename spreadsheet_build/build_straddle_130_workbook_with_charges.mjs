import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve("..");
const inputPath = path.join(root, "output", "excel", "straddle_130_workbook_data_with_charges.json");
const outputDir = path.join(root, "output", "excel");
const outputPath = path.join(outputDir, "Nifty_0920_Straddle_Basket_130_Qty_With_Charges.xlsx");
const data = JSON.parse(await fs.readFile(inputPath, "utf8"));

function toExcelDate(value) {
  return new Date(`${value}T00:00:00`);
}

function writeTable(sheet, startCell, headers, rows) {
  sheet.getRange(startCell).write([headers, ...rows]);
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

const workbook = Workbook.create();
const summary = workbook.worksheets.add("Summary");
const monthly = workbook.worksheets.add("Monthly");
const daily = workbook.worksheets.add("Daily Trades");
const legs = workbook.worksheets.add("Leg Trades");
const sources = workbook.worksheets.add("Sources");

for (const sheet of [summary, monthly, daily, legs, sources]) {
  sheet.showGridLines = false;
}

summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["NIFTY 09:20 Straddle Basket - 130 Quantity With Charges"]];
setTitle(summary.getRange("A1:H1"));
summary.getRange("A3:B20").values = data.summary;
summary.getRange("A3:A20").format = { fill: "#E8EEF5", font: { bold: true, color: "#0B2545" } };
summary.getRange("A3:B20").format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
summary.getRange("B3:B4").format.numberFormat = "#,##0";
summary.getRange("B5:B6").format.numberFormat = "#,##0";
summary.getRange("B7:B11").format.numberFormat = "0.0000%";
summary.getRange("B15:B20").format.numberFormat = "\"Rs\" #,##0";
summary.getRange("D3:H3").merge();
summary.getRange("D3").values = [["Charge assumptions"]];
setSection(summary.getRange("D3:H3"));
summary.getRange("D4:H10").merge();
summary.getRange("D4").values = [[
  "Charges are estimates and are configurable in the Summary sheet. Brokerage is assumed at Rs 20 per option order. Each straddle row contains CE+PE buy and CE+PE sell, so 4 option orders per row. STT is applied on sell premium only; stamp duty on buy premium only; exchange and SEBI fees on buy+sell premium; GST on brokerage, exchange, and SEBI fees."
]];
summary.getRange("D4:H10").format = { wrapText: true, verticalAlignment: "top", fill: "#F8FAFC" };
summary.getRange("D4:H10").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
summary.getRange("D12:H12").merge();
summary.getRange("D12").values = [["Net result"]];
setSection(summary.getRange("D12:H12"));
summary.getRange("D13:H17").merge();
summary.getRange("D13").values = [[
  "The workbook reports both gross and net P&L. Net P&L subtracts estimated brokerage, STT, stamp duty, exchange transaction charge, SEBI fee, and GST. Slippage is still not included."
]];
summary.getRange("D13:H17").format = { wrapText: true, verticalAlignment: "top", fill: "#FFF7ED", font: { color: "#7C2D12" } };
summary.getRange("D13:H17").format.borders = { preset: "outside", style: "thin", color: "#FDBA74" };
summary.getRange("A:A").format.columnWidth = 35;
summary.getRange("B:B").format.columnWidth = 24;
summary.getRange("D:H").format.columnWidth = 18;

monthly.getRange("A1:N1").merge();
monthly.getRange("A1").values = [["Monthly Summary - 130 Quantity With Charges"]];
setTitle(monthly.getRange("A1:N1"));
const monthlyHeaders = [
  "Month", "Trading Days", "Winning Days", "Losing Days", "Win Rate", "Points",
  "Gross Rupee P&L", "Total Charges", "Net Rupee P&L", "Avg Daily Net",
  "Max Daily Net Gain", "Max Daily Net Loss", "Max Capital Used", "Avg Capital Used"
];
const monthlyRows = data.monthly.map((r) => [
  r["Month"], r["Trading Days"], r["Winning Days"], r["Losing Days"], r["Win Rate"], r["Points"],
  r["Gross Rupee P&L"], r["Total Charges"], r["Net Rupee P&L"], r["Avg Daily Net"],
  r["Max Daily Net Gain"], r["Max Daily Net Loss"], r["Max Capital Used"], r["Avg Capital Used"]
]);
writeTable(monthly, "A3", monthlyHeaders, monthlyRows);
setHeader(monthly.getRange("A3:N3"));
const monthlyLast = monthlyRows.length + 3;
monthly.getRange(`A3:N${monthlyLast}`).format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
setNumericFormats(monthly, [
  [`E4:E${monthlyLast}`, "0.0%"],
  [`F4:F${monthlyLast}`, "#,##0.00"],
  [`G4:N${monthlyLast}`, "\"Rs\" #,##0"],
]);
colorPnL(monthly, `I4:I${monthlyLast}`);
monthly.freezePanes.freezeRows(3);
monthly.getRange("A:N").format.autofitColumns();

daily.getRange("A1:R1").merge();
daily.getRange("A1").values = [["Daily Basket Trades - 130 Quantity With Charges"]];
setTitle(daily.getRange("A1:R1"));
const dailyHeaders = [
  "Date", "Month", "NIFTY 09:15 Open", "ATM", "Entry Premium", "Exit Premium", "Points P&L",
  "Buy Turnover", "Sell Turnover", "Gross Rupee P&L", "Brokerage", "STT", "Stamp Duty",
  "Exchange Txn", "SEBI Fee", "GST", "Total Charges", "Net Rupee P&L", "Capital Used", "Result"
];
const dailyRows = data.daily.map((r) => [
  toExcelDate(r["Date"]), r["Month"], r["NIFTY 09:15 Open"], r["ATM"], r["Entry Premium"], r["Exit Premium"], r["Points P&L"],
  r["Buy Turnover"], r["Sell Turnover"], r["Gross Rupee P&L"], r["Brokerage"], r["STT"], r["Stamp Duty"],
  r["Exchange Txn"], r["SEBI Fee"], r["GST"], r["Total Charges"], r["Net Rupee P&L"], r["Capital Used"], r["Result"]
]);
writeTable(daily, "A3", dailyHeaders, dailyRows);
setHeader(daily.getRange("A3:T3"));
const dailyLast = dailyRows.length + 3;
daily.getRange(`A3:T${dailyLast}`).format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
setNumericFormats(daily, [
  [`A4:A${dailyLast}`, "yyyy-mm-dd"],
  [`C4:G${dailyLast}`, "#,##0.00"],
  [`H4:S${dailyLast}`, "\"Rs\" #,##0"],
]);
colorPnL(daily, `R4:R${dailyLast}`);
daily.freezePanes.freezeRows(3);
daily.getRange("A:T").format.autofitColumns();

legs.getRange("A1:Z1").merge();
legs.getRange("A1").values = [["Detailed Straddle Rows - 130 Quantity With Charges"]];
setTitle(legs.getRange("A1:Z1"));
const legHeaders = [
  "Date", "Month", "Entry Time", "NIFTY 09:15 Open", "ATM", "Leg", "Offset", "Strike",
  "Entry Premium", "Target Premium", "Exit Premium", "Points P&L", "Qty", "Buy Turnover",
  "Sell Turnover", "Gross Rupee P&L", "Brokerage", "STT", "Stamp Duty", "Exchange Txn",
  "SEBI Fee", "GST", "Total Charges", "Net Rupee P&L", "Capital Used", "Exit Reason"
];
const legRows = data.legTrades.map((r) => [
  toExcelDate(r["Date"]), r["Month"], r["Entry Time"], r["NIFTY 09:15 Open"], r["ATM"], r["Leg"], r["Offset"], r["Strike"],
  r["Entry Premium"], r["Target Premium"], r["Exit Premium"], r["Points P&L"], r["Qty"], r["Buy Turnover"],
  r["Sell Turnover"], r["Gross Rupee P&L"], r["Brokerage"], r["STT"], r["Stamp Duty"], r["Exchange Txn"],
  r["SEBI Fee"], r["GST"], r["Total Charges"], r["Net Rupee P&L"], r["Capital Used"], r["Exit Reason"]
]);
writeTable(legs, "A3", legHeaders, legRows);
setHeader(legs.getRange("A3:Z3"));
const legLast = legRows.length + 3;
legs.getRange(`A3:Z${legLast}`).format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
setNumericFormats(legs, [
  [`A4:A${legLast}`, "yyyy-mm-dd"],
  [`D4:E${legLast}`, "#,##0.00"],
  [`G4:H${legLast}`, "#,##0"],
  [`I4:L${legLast}`, "#,##0.00"],
  [`M4:M${legLast}`, "#,##0"],
  [`N4:Y${legLast}`, "\"Rs\" #,##0"],
]);
colorPnL(legs, `X4:X${legLast}`);
legs.freezePanes.freezeRows(3);
legs.getRange("A:Z").format.autofitColumns();
legs.getRange("F:F").format.columnWidth = 20;

sources.getRange("A1:D1").merge();
sources.getRange("A1").values = [["Sources and Notes"]];
setTitle(sources.getRange("A1:D1"));
sources.getRange("A3:B13").values = [
  ["Source trade file", "output/research_straddle/straddle_0920_atm_minus50_basket_trades.csv"],
  ["Backtest rule", "09:20 long straddle basket: ATM -50 straddle + ATM straddle"],
  ["Quantity", "130"],
  ["Charges included", "Brokerage, STT, stamp duty, exchange transaction charge, SEBI fee, GST"],
  ["Costs still excluded", "Slippage, bid-ask spread, impact cost, pledge interest, platform fees, taxes on income"],
  ["STT source", "https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies"],
  ["STT mechanism source", "https://www.nseclearing.in/clearing-settlement/equity-derivatives/securities-transaction-tax"],
  ["Stamp duty source", "https://www.nseindia.com/static/invest/first-time-investor-stamp-duty-charges-taxes"],
  ["Exchange charge context", "https://legal.economictimes.indiatimes.com/news/regulators/nse-bse-revise-transaction-charges-effective-from-oct-1/113748265"],
  ["Brokerage assumption", "Rs 20 per option order; edit Summary assumptions if your broker differs"],
  ["Important", "Rates can change; verify with your broker contract note before live use"],
];
sources.getRange("A3:A13").format = { fill: "#E8EEF5", font: { bold: true, color: "#0B2545" } };
sources.getRange("A3:B13").format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
sources.getRange("A:A").format.columnWidth = 24;
sources.getRange("B:B").format.columnWidth = 105;
sources.getRange("B:B").format.wrapText = true;

const chart = summary.charts.add("line", monthly.getRange(`A3:I${monthlyLast}`));
chart.title = "Monthly Net Rupee P&L";
chart.hasLegend = false;
chart.xAxis = { axisType: "textAxis" };
chart.yAxis = { numberFormatCode: "\"Rs\" #,##0" };
chart.setPosition("D19", "H34");

await fs.mkdir(outputDir, { recursive: true });
for (const sheetName of ["Summary", "Monthly", "Daily Trades", "Leg Trades"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(
    path.join(outputDir, `preview_charges_${sheetName.replaceAll(" ", "_")}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const inspect = await workbook.inspect({
  kind: "table",
  sheetId: "Summary",
  range: "A1:H24",
  include: "values,formulas",
  tableMaxRows: 24,
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
