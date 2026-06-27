import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve("..");
const researchDir = path.join(root, "output", "research_straddle");
const outputDir = path.join(root, "output", "excel");

const files = [
  {
    title: "NIFTY 09:20 Individual-Leg Straddle - Realistic Results With Charges",
    sourceCsv: path.join(researchDir, "individual_leg_straddle_realistic_summary.csv"),
    outputName: "Nifty_0920_Individual_Leg_Straddle_Realistic_130_Qty_With_Charges.xlsx",
    topDailyGlobPrefix: "individual_leg_top_",
  },
  {
    title: "NIFTY 09:20 Individual-Leg Straddle - Full Search Results With Charges",
    sourceCsv: path.join(researchDir, "individual_leg_straddle_summary.csv"),
    outputName: "Nifty_0920_Individual_Leg_Straddle_Full_Search_130_Qty_With_Charges.xlsx",
    topDailyGlobPrefix: "individual_leg_top_",
  },
];

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    const next = text[i + 1];
    if (quoted) {
      if (ch === '"' && next === '"') {
        cell += '"';
        i += 1;
      } else if (ch === '"') {
        quoted = false;
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (ch !== "\r") {
      cell += ch;
    }
  }
  if (cell.length || row.length) {
    row.push(cell);
    rows.push(row);
  }
  const headers = rows.shift() ?? [];
  return rows.filter((r) => r.length === headers.length).map((r) => {
    const obj = {};
    headers.forEach((h, idx) => {
      const value = r[idx];
      const n = Number(value);
      obj[h] = value !== "" && Number.isFinite(n) ? n : value;
    });
    return obj;
  });
}

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

function normalizeSummaryRow(row) {
  return [
    row.day_filter,
    row.basket_name,
    row.entry_mode,
    row.target_pct,
    row.leg_sl_pct,
    row.entry_slippage,
    row.market_exit_slippage,
    row.days,
    row.option_legs,
    row.total_points,
    row.net_rupee_pnl,
    row.daily_win_rate_pct,
    row.avg_month_ex_aug,
    row.best_month,
    row.worst_month,
    row.positive_months,
    row.months_350_plus,
    row.max_drawdown_points,
    row.target_legs_pct,
    row.sl_legs_pct,
  ];
}

function applySummaryFormats(sheet, lastRow) {
  sheet.getRange(`A3:T${lastRow}`).format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
  setHeader(sheet.getRange("A3:T3"));
  sheet.getRange(`D4:E${lastRow}`).format.numberFormat = "0.0%";
  sheet.getRange(`F4:G${lastRow}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`H4:I${lastRow}`).format.numberFormat = "#,##0";
  sheet.getRange(`J4:J${lastRow}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`K4:K${lastRow}`).format.numberFormat = "\"Rs\" #,##0";
  sheet.getRange(`L4:L${lastRow}`).format.numberFormat = "0.0";
  sheet.getRange(`M4:O${lastRow}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`P4:Q${lastRow}`).format.numberFormat = "#,##0";
  sheet.getRange(`R4:R${lastRow}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`S4:T${lastRow}`).format.numberFormat = "0.0";
  colorPnL(sheet, `J4:J${lastRow}`);
  colorPnL(sheet, `K4:K${lastRow}`);
  sheet.freezePanes.freezeRows(3);
  sheet.getRange("A:T").format.autofitColumns();
  sheet.getRange("A:C").format.columnWidth = 22;
}

async function findBestDailyFile(bestRow) {
  const files = await fs.readdir(researchDir);
  const target = `individual_leg_top_${bestRow.day_filter}__${bestRow.basket_name}__${bestRow.entry_mode}__target_${Number(bestRow.target_pct).toString()}__legsl_${Number(bestRow.leg_sl_pct).toString()}__entryslip_${Number(bestRow.entry_slippage).toString()}__exitslip_${Number(bestRow.market_exit_slippage).toString()}_daily.csv`;
  if (files.includes(target)) return path.join(researchDir, target);
  return null;
}

async function buildWorkbook(config) {
  const rows = parseCsv(await fs.readFile(config.sourceCsv, "utf8"));
  rows.sort((a, b) => Number(b.avg_month_ex_aug) - Number(a.avg_month_ex_aug) || Number(b.total_points) - Number(a.total_points));
  const best = rows[0];
  const topRows = rows.slice(0, 50);
  const headers = [
    "Day Filter", "Basket", "Entry Mode", "Target %", "Leg SL %", "Entry Slippage",
    "Exit Slippage", "Days", "Option Legs", "Total Points", "Net Rupee P&L",
    "Daily Win Rate", "Avg Month", "Best Month", "Worst Month", "Positive Months",
    "Months >=350", "Max Drawdown", "Target Legs %", "SL Legs %",
  ];

  const workbook = Workbook.create();
  const summary = workbook.worksheets.add("Summary");
  const top = workbook.worksheets.add("Top Results");
  const all = workbook.worksheets.add("All Results");
  const daily = workbook.worksheets.add("Best Daily");
  const sources = workbook.worksheets.add("Sources");

  for (const sheet of [summary, top, all, daily, sources]) {
    sheet.showGridLines = false;
  }

  summary.getRange("A1:H1").merge();
  summary.getRange("A1").values = [[config.title]];
  setTitle(summary.getRange("A1:H1"));

  summary.getRange("A3:B22").values = [
    ["Best day filter", best.day_filter],
    ["Best basket", best.basket_name],
    ["Entry mode", best.entry_mode],
    ["Target", best.target_pct],
    ["Leg SL", best.leg_sl_pct],
    ["Entry slippage", best.entry_slippage],
    ["Market exit slippage", best.market_exit_slippage],
    ["Trading days", best.days],
    ["Option legs", best.option_legs],
    ["Total points", best.total_points],
    ["Net rupee P&L", best.net_rupee_pnl],
    ["Daily win rate", best.daily_win_rate_pct],
    ["Avg month", best.avg_month_ex_aug],
    ["Best month", best.best_month],
    ["Worst month", best.worst_month],
    ["Positive months", best.positive_months],
    ["Months >=350", best.months_350_plus],
    ["Max drawdown", best.max_drawdown_points],
    ["Target legs %", best.target_legs_pct],
    ["SL legs %", best.sl_legs_pct],
  ];
  summary.getRange("A3:A22").format = { fill: "#E8EEF5", font: { bold: true, color: "#0B2545" } };
  summary.getRange("A3:B22").format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
  summary.getRange("B6:B7").format.numberFormat = "0.0%";
  summary.getRange("B8:B9").format.numberFormat = "#,##0.00";
  summary.getRange("B10:B11").format.numberFormat = "#,##0";
  summary.getRange("B12:B12").format.numberFormat = "#,##0.00";
  summary.getRange("B13:B13").format.numberFormat = "\"Rs\" #,##0";
  summary.getRange("B14:B14").format.numberFormat = "0.0";
  summary.getRange("B15:B17").format.numberFormat = "#,##0.00";
  summary.getRange("B18:B19").format.numberFormat = "#,##0";
  summary.getRange("B20:B20").format.numberFormat = "#,##0.00";
  summary.getRange("B21:B22").format.numberFormat = "0.0";
  colorPnL(summary, "B12:B13");
  colorPnL(summary, "B17:B17");
  summary.getRange("D3:H3").merge();
  summary.getRange("D3").values = [["Interpretation"]];
  setSection(summary.getRange("D3:H3"));
  summary.getRange("D4:H12").merge();
  summary.getRange("D4").values = [[
    "This workbook follows the same presentation style as the earlier With_Charges output. Results are from the individual-leg straddle research: each CE/PE leg can hit its own target independently, charges are included in net P&L, and slippage assumptions are shown in the summary."
  ]];
  summary.getRange("D4:H12").format = { wrapText: true, verticalAlignment: "top", fill: "#F8FAFC" };
  summary.getRange("D4:H12").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
  summary.getRange("A:A").format.columnWidth = 28;
  summary.getRange("B:B").format.columnWidth = 24;
  summary.getRange("D:H").format.columnWidth = 18;

  top.getRange("A1:T1").merge();
  top.getRange("A1").values = [["Top 50 Strategy Variants"]];
  setTitle(top.getRange("A1:T1"));
  writeTable(top, "A3", headers, topRows.map(normalizeSummaryRow));
  applySummaryFormats(top, topRows.length + 3);

  all.getRange("A1:T1").merge();
  all.getRange("A1").values = [["All Strategy Variants"]];
  setTitle(all.getRange("A1:T1"));
  writeTable(all, "A3", headers, rows.map(normalizeSummaryRow));
  applySummaryFormats(all, rows.length + 3);

  const dailyPath = await findBestDailyFile(best);
  if (dailyPath) {
    const dailyRowsRaw = parseCsv(await fs.readFile(dailyPath, "utf8")).sort((a, b) => new Date(`${b.date}T00:00:00`) - new Date(`${a.date}T00:00:00`));
    const dailyHeaders = [
      "Date", "Month", "Option Legs", "Points", "Gross Rupee P&L", "Charges",
      "Net Rupee P&L", "Target Legs", "SL Legs",
    ];
    const dailyRows = dailyRowsRaw.map((r) => [
      toExcelDate(r.date), r.month, r.option_legs, r.points, r.gross_rupee_pnl,
      r.charges, r.net_rupee_pnl, r.target_legs, r.sl_legs,
    ]);
    daily.getRange("A1:I1").merge();
    daily.getRange("A1").values = [["Best Variant Daily Trades"]];
    setTitle(daily.getRange("A1:I1"));
    writeTable(daily, "A3", dailyHeaders, dailyRows);
    const dailyLast = dailyRows.length + 3;
    daily.getRange(`A3:I${dailyLast}`).format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
    setHeader(daily.getRange("A3:I3"));
    daily.getRange(`A4:A${dailyLast}`).format.numberFormat = "yyyy-mm-dd";
    daily.getRange(`C4:C${dailyLast}`).format.numberFormat = "#,##0";
    daily.getRange(`D4:D${dailyLast}`).format.numberFormat = "#,##0.00";
    daily.getRange(`E4:G${dailyLast}`).format.numberFormat = "\"Rs\" #,##0";
    daily.getRange(`H4:I${dailyLast}`).format.numberFormat = "#,##0";
    colorPnL(daily, `D4:D${dailyLast}`);
    colorPnL(daily, `G4:G${dailyLast}`);
    daily.freezePanes.freezeRows(3);
    daily.getRange("A:I").format.autofitColumns();
  } else {
    daily.getRange("A1:D1").merge();
    daily.getRange("A1").values = [["Best Variant Daily Trades"]];
    setTitle(daily.getRange("A1:D1"));
    daily.getRange("A3:D6").merge();
    daily.getRange("A3").values = [["Daily CSV for the best variant was not found. The Summary, Top Results, and All Results sheets are complete."]];
    daily.getRange("A3:D6").format = { wrapText: true, verticalAlignment: "top" };
  }

  sources.getRange("A1:D1").merge();
  sources.getRange("A1").values = [["Sources and Notes"]];
  setTitle(sources.getRange("A1:D1"));
  sources.getRange("A3:B11").values = [
    ["Source summary CSV", path.relative(root, config.sourceCsv)],
    ["Quantity", "130"],
    ["Charges", "Included in Net Rupee P&L"],
    ["Entry assumption", "Next candle open for realistic variants"],
    ["Exit assumption", "Individual CE/PE leg target exits; square-off and SL use market-exit slippage"],
    ["Slippage", "Shown in Entry Slippage and Exit Slippage columns"],
    ["Important", "This is research output, not a live trading recommendation."],
    ["Generated workbook", config.outputName],
    ["Prior style reference", "Nifty_0920_Straddle_Basket_130_Qty_With_Charges.xlsx"],
  ];
  sources.getRange("A3:A11").format = { fill: "#E8EEF5", font: { bold: true, color: "#0B2545" } };
  sources.getRange("A3:B11").format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
  sources.getRange("A:A").format.columnWidth = 28;
  sources.getRange("B:B").format.columnWidth = 95;
  sources.getRange("B:B").format.wrapText = true;

  await fs.mkdir(outputDir, { recursive: true });
  const previewRanges = {
    Summary: "A1:H24",
    "Top Results": "A1:T35",
    "All Results": "A1:T35",
    "Best Daily": "A1:I35",
    Sources: "A1:D14",
  };
  for (const [sheetName, range] of Object.entries(previewRanges)) {
    const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
    await fs.writeFile(
      path.join(outputDir, `preview_${config.outputName.replace(".xlsx", "")}_${sheetName.replaceAll(" ", "_")}.png`),
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
  const outPath = path.join(outputDir, config.outputName);
  await output.save(outPath);
  console.log(outPath);
}

for (const config of files) {
  await buildWorkbook(config);
}
