import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve("..");
const juneOutput = process.env.SWEETSPOT_JUNE_OUTPUT || "output/june_sweetspot_trades";
const workbookName = process.env.SWEETSPOT_WORKBOOK_NAME || "June_2026_SweetSpot_Trades_130_Qty_With_Charges.xlsx";
const workbookTitle = process.env.SWEETSPOT_WORKBOOK_TITLE || "June 2026 Sweet Spot Trades - 130 Quantity With Charges";
const configName = process.env.SWEETSPOT_CONFIG_FILE || "configs/recommended_atm_plus_afternoon.yaml";
const ruleText = process.env.SWEETSPOT_RULE_TEXT || "Source config: recommended_atm_plus_afternoon.yaml. Universe is ATM and ATM +50. Setups allowed are retest/bounce and vacuum breakout. Trade window is 13:00 to 15:00. Entry must be within pivot +10 with max candle range 12. Hard exit is pivot close SL; C2C after +20; trailing after +40; squareoff at 15:25.";
const inputPath = path.join(root, juneOutput, "excel", "june_sweetspot_workbook_data.json");
const outputDir = path.join(root, juneOutput, "excel");
const outputPath = path.join(outputDir, workbookName);
const data = JSON.parse(await fs.readFile(inputPath, "utf8"));

function toExcelDate(value) {
  return new Date(`${value}T00:00:00`);
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

function writeTable(sheet, startCell, headers, rows) {
  sheet.getRange(startCell).write([headers, ...rows]);
}

const workbook = Workbook.create();
const summary = workbook.worksheets.add("Summary");
const trades = workbook.worksheets.add("Trades");
const daily = workbook.worksheets.add("Daily");
const noTrade = workbook.worksheets.add("No Trade Days");
const notes = workbook.worksheets.add("Notes");

for (const sheet of [summary, trades, daily, noTrade, notes]) {
  sheet.showGridLines = false;
}

summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [[workbookTitle]];
setTitle(summary.getRange("A1:H1"));
summary.getRange("A3:B23").values = data.summary;
summary.getRange("A3:A23").format = { fill: "#E8EEF5", font: { bold: true, color: "#0B2545" } };
summary.getRange("A3:B23").format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
summary.getRange("B5:B8").format.numberFormat = "#,##0";
summary.getRange("B9:B9").format.numberFormat = "0.0%";
summary.getRange("B10:B10").format.numberFormat = "#,##0.00";
summary.getRange("B11:B13").format.numberFormat = "\"Rs\" #,##0";
summary.getRange("B14:B15").format.numberFormat = "#,##0.00";
summary.getRange("B18:B19").format.numberFormat = "#,##0.00";
summary.getRange("B20:B20").format.numberFormat = "\"Rs\" #,##0";
summary.getRange("B21:B22").format.numberFormat = "#,##0";
colorPnL(summary, "B10:B13");
colorPnL(summary, "B14:B15");
colorPnL(summary, "B18:B20");
summary.getRange("D3:H3").merge();
summary.getRange("D3").values = [["Rules Used"]];
setSection(summary.getRange("D3:H3"));
summary.getRange("D4:H13").merge();
summary.getRange("D4").values = [[ruleText]];
summary.getRange("D4:H13").format = { wrapText: true, verticalAlignment: "top", fill: "#F8FAFC" };
summary.getRange("D4:H13").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
summary.getRange("D15:H15").merge();
summary.getRange("D15").values = [["Important"]];
setSection(summary.getRange("D15:H15"));
summary.getRange("D16:H20").merge();
summary.getRange("D16").values = [[
  "This workbook is June-only and uses the current backtester trades, not manual chart-picked trades. No-trade days are included so chart review can focus on why no valid Sweet Spot entry was triggered."
]];
summary.getRange("D16:H20").format = { wrapText: true, verticalAlignment: "top", fill: "#FFF7ED", font: { color: "#7C2D12" } };
summary.getRange("D16:H20").format.borders = { preset: "outside", style: "thin", color: "#FDBA74" };
summary.getRange("A:A").format.columnWidth = 28;
summary.getRange("B:B").format.columnWidth = 26;
summary.getRange("D:H").format.columnWidth = 18;

const tradeHeaders = [
  "Date", "Entry Time", "Exit Time", "NIFTY 09:15 Open", "ATM", "Strike", "Side", "Setup",
  "Entry Premium", "Exit Premium", "Points P&L", "Pivot", "Entry Distance From Pivot",
  "Candle Range", "Max Favorable Points", "C2C Activated", "Trailing Activated", "Exit Reason",
  "Qty", "Gross Rupee P&L", "Total Charges", "Net Rupee P&L", "Capital Used", "Chart File",
  "VIX 09:15 Open", "VIX Entry Close", "VIX Change From Open %", "VIX 15m Change",
  "VIX 15m Trend", "VIX Filter", "VIX Filter Reason",
];
const tradeRows = data.trades.map((r) => [
  toExcelDate(r["Date"]), r["Entry Time"], r["Exit Time"], r["NIFTY 09:15 Open"], r["ATM"], r["Strike"],
  r["Side"], r["Setup"], r["Entry Premium"], r["Exit Premium"], r["Points P&L"], r["Pivot"],
  r["Entry Distance From Pivot"], r["Candle Range"], r["Max Favorable Points"], r["C2C Activated"],
  r["Trailing Activated"], r["Exit Reason"], r["Qty"], r["Gross Rupee P&L"], r["Total Charges"],
  r["Net Rupee P&L"], r["Capital Used"], r["Chart File"],
  r["VIX 09:15 Open"], r["VIX Entry Close"], r["VIX Change From Open %"], r["VIX 15m Change"],
  r["VIX 15m Trend"], r["VIX Filter"], r["VIX Filter Reason"],
]);
trades.getRange("A1:AE1").merge();
trades.getRange("A1").values = [["June Sweet Spot Trade Entries"]];
setTitle(trades.getRange("A1:AE1"));
writeTable(trades, "A3", tradeHeaders, tradeRows);
const tradeLast = tradeRows.length + 3;
trades.getRange(`A3:AE${tradeLast}`).format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
setHeader(trades.getRange("A3:AE3"));
trades.getRange(`A4:A${tradeLast}`).format.numberFormat = "yyyy-mm-dd";
trades.getRange(`D4:F${tradeLast}`).format.numberFormat = "#,##0.00";
trades.getRange(`I4:O${tradeLast}`).format.numberFormat = "#,##0.00";
trades.getRange(`S4:S${tradeLast}`).format.numberFormat = "#,##0";
trades.getRange(`T4:W${tradeLast}`).format.numberFormat = "\"Rs\" #,##0";
trades.getRange(`Y4:AB${tradeLast}`).format.numberFormat = "#,##0.00";
colorPnL(trades, `K4:K${tradeLast}`);
colorPnL(trades, `V4:V${tradeLast}`);
colorPnL(trades, `AA4:AB${tradeLast}`);
trades.freezePanes.freezeRows(3);
trades.getRange("A:AE").format.autofitColumns();
trades.getRange("H:H").format.columnWidth = 18;
trades.getRange("R:R").format.columnWidth = 20;
trades.getRange("X:X").format.columnWidth = 44;
trades.getRange("AE:AE").format.columnWidth = 42;

const dailyHeaders = ["Date", "Trades", "Points", "Gross Rupee P&L", "Total Charges", "Net Rupee P&L", "Capital Used", "Result"];
const dailyRows = data.daily.map((r) => [
  toExcelDate(r["Date"]), r["Trades"], r["Points"], r["Gross_Rupee_PnL"], r["Total_Charges"],
  r["Net_Rupee_PnL"], r["Capital_Used"], r["Result"],
]);
daily.getRange("A1:H1").merge();
daily.getRange("A1").values = [["June Daily Summary"]];
setTitle(daily.getRange("A1:H1"));
writeTable(daily, "A3", dailyHeaders, dailyRows);
const dailyLast = dailyRows.length + 3;
daily.getRange(`A3:H${dailyLast}`).format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
setHeader(daily.getRange("A3:H3"));
daily.getRange(`A4:A${dailyLast}`).format.numberFormat = "yyyy-mm-dd";
daily.getRange(`B4:B${dailyLast}`).format.numberFormat = "#,##0";
daily.getRange(`C4:C${dailyLast}`).format.numberFormat = "#,##0.00";
daily.getRange(`D4:G${dailyLast}`).format.numberFormat = "\"Rs\" #,##0";
colorPnL(daily, `C4:C${dailyLast}`);
colorPnL(daily, `F4:F${dailyLast}`);
daily.freezePanes.freezeRows(3);
daily.getRange("A:H").format.autofitColumns();

const noTradeHeaders = ["Date", "NIFTY 09:15 Open", "ATM", "Chart File", "Reason"];
const noTradeRows = data.noTradeDays.map((r) => [
  toExcelDate(r["Date"]), r["NIFTY 09:15 Open"], r["ATM"], r["Chart File"], r["Reason"],
]);
noTrade.getRange("A1:E1").merge();
noTrade.getRange("A1").values = [["June Chart Days With No Sweet Spot Trade"]];
setTitle(noTrade.getRange("A1:E1"));
writeTable(noTrade, "A3", noTradeHeaders, noTradeRows);
const noTradeLast = noTradeRows.length + 3;
noTrade.getRange(`A3:E${noTradeLast}`).format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
setHeader(noTrade.getRange("A3:E3"));
noTrade.getRange(`A4:A${noTradeLast}`).format.numberFormat = "yyyy-mm-dd";
noTrade.getRange(`B4:C${noTradeLast}`).format.numberFormat = "#,##0.00";
noTrade.freezePanes.freezeRows(3);
noTrade.getRange("A:E").format.autofitColumns();
noTrade.getRange("D:D").format.columnWidth = 46;
noTrade.getRange("E:E").format.columnWidth = 44;

notes.getRange("A1:D1").merge();
notes.getRange("A1").values = [["Sources and Notes"]];
setTitle(notes.getRange("A1:D1"));
notes.getRange("A3:B12").values = [
  ["Trade CSV", `${juneOutput}/trades/june_sweetspot_trades.csv`],
  ["Daily Summary CSV", `${juneOutput}/reports/june_daily_summary.csv`],
  ["No-Trade Days CSV", `${juneOutput}/reports/june_no_trade_days.csv`],
  ["Config", configName],
  ["Chart folder", "data/charts/jun_nifty_open"],
  ["Quantity", "130"],
  ["Charges", "Included: brokerage, STT, stamp duty, exchange txn, SEBI fee, GST"],
  ["VIX filter", "First-pass avoidance rule: take only when VIX is not below 09:15 open and not falling over the last 15 minutes."],
  ["Note", "This is generated from the Sweet Spot backtester; it is not manually selected from charts."],
  ["Next Step", "Use this file to compare each trade date against the June HTML charts."],
];
notes.getRange("A3:A12").format = { fill: "#E8EEF5", font: { bold: true, color: "#0B2545" } };
notes.getRange("A3:B12").format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
notes.getRange("A:A").format.columnWidth = 24;
notes.getRange("B:B").format.columnWidth = 95;
notes.getRange("B:B").format.wrapText = true;

await fs.mkdir(outputDir, { recursive: true });
for (const [sheetName, range] of Object.entries({
  Summary: "A1:H24",
  Trades: "A1:AE12",
  Daily: "A1:H12",
  "No Trade Days": "A1:E24",
  Notes: "A1:D15",
})) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(
    path.join(outputDir, `preview_june_sweetspot_${sheetName.replaceAll(" ", "_")}.png`),
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
