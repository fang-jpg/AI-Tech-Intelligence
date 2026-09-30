import fs from "node:fs/promises";
import path from "node:path";
import ExcelJS from "exceljs";
import { ROOT, readJson } from "./lib.mjs";

const INPUT_PATH = path.join(ROOT, "outputs", "ai_executive_intelligence_web_20260921.xlsx");
const OUTPUT_PATH = process.argv[2] || path.join(ROOT, "outputs", "ai_executive_intelligence_web_20260921_高校研究机构补充_20260923.xlsx");
const before = new ExcelJS.Workbook();
const after = new ExcelJS.Workbook();
await Promise.all([before.xlsx.readFile(INPUT_PATH), after.xlsx.readFile(OUTPUT_PATH)]);

for (const name of ["高管发言", "情报明细", "厂商趋势"]) {
  const original = before.getWorksheet(name);
  const merged = after.getWorksheet(name);
  if (!merged) throw new Error(`Original sheet missing after merge: ${name}`);
  if (original.rowCount !== merged.rowCount || original.columnCount !== merged.columnCount) throw new Error(`Original sheet dimensions changed: ${name}`);
}

const detail = after.getWorksheet("高校研究机构情报");
const trends = after.getWorksheet("高校趋势汇总");
if (!detail || !trends) throw new Error("Academic sheets missing");
if (detail.rowCount !== 308 || detail.columnCount !== 20) throw new Error(`Academic detail dimensions: ${detail.rowCount}x${detail.columnCount}`);
if (trends.rowCount !== 103 || trends.columnCount !== 8) throw new Error(`Academic trend dimensions: ${trends.rowCount}x${trends.columnCount}`);

const headers = detail.getRow(4).values.slice(1);
const expectedHeaders = ["模型厂商", "高管/来源", "职位", "日期", "来源类型", "原文标题", "官方链接", "检索方式", "内容基础", "核心观点", "技术标签", "AI未来模型动向分析", "证据等级", "置信度", "时间窗口", "来源等级", "是否官方", "归因状态", "证据校验", "分析模型"];
if (JSON.stringify(headers) !== JSON.stringify(expectedHeaders)) throw new Error("Academic detail headers do not match template");

let linkCount = 0;
let nonblankTrends = 0;
const trendTexts = [];
const formulaErrors = [];
for (let rowNumber = 5; rowNumber <= detail.rowCount; rowNumber += 1) {
  const row = detail.getRow(rowNumber);
  if (row.getCell(7).value?.hyperlink) linkCount += 1;
  const trend = String(row.getCell(12).value ?? "").trim();
  if (trend) {
    nonblankTrends += 1;
    trendTexts.push(trend);
  }
}
for (const sheet of after.worksheets) {
  sheet.eachRow((row) => row.eachCell((cell) => {
    const text = String(cell.value?.result ?? cell.value ?? "");
    if (/^#(?:REF!|VALUE!|DIV\/0!|NAME\?|N\/A|NUM!|NULL!)/.test(text)) formulaErrors.push(`${sheet.name}!${cell.address}:${text}`);
  }));
}

const summaryData = await readJson(path.join(ROOT, "data", "academic_source_summaries_20260923.json"));
const exactTrendDuplicates = trendTexts.length - new Set(trendTexts).size;
if (linkCount !== 304) throw new Error(`Expected 304 links, got ${linkCount}`);
if (nonblankTrends !== 99) throw new Error(`Expected 99 nonblank trends, got ${nonblankTrends}`);
if (exactTrendDuplicates !== 0) throw new Error(`Duplicate trend texts: ${exactTrendDuplicates}`);
if (summaryData.metrics.exact_duplicate_summaries !== 0) throw new Error(`Duplicate source summaries: ${summaryData.metrics.exact_duplicate_summaries}`);
if (summaryData.metrics.fallback_summaries !== 0) throw new Error(`Fallback source summaries remain: ${summaryData.metrics.fallback_summaries}`);
if (formulaErrors.length) throw new Error(`Formula errors: ${formulaErrors.join(", ")}`);

const stat = await fs.stat(OUTPUT_PATH);
console.log(JSON.stringify({ output: OUTPUT_PATH, bytes: stat.size, sheets: after.worksheets.map((sheet) => ({ name: sheet.name, rows: sheet.rowCount, columns: sheet.columnCount })), academicLinks: linkCount, nonblankTrends, exactTrendDuplicates, exactDuplicateSummaries: summaryData.metrics.exact_duplicate_summaries, fallbackSummaries: summaryData.metrics.fallback_summaries, formulaErrors: formulaErrors.length }, null, 2));
