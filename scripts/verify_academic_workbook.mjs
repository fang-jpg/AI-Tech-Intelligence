import fs from "node:fs/promises";
import path from "node:path";
import ExcelJS from "exceljs";
import { ROOT, readJson } from "./lib.mjs";

const workbookPath = process.argv[2] || path.join(ROOT, "outputs", "高校研究机构智能情报_20260922", "高校研究机构_AI技术情报量化研判_20260922.xlsx");
const workbook = new ExcelJS.Workbook();
await workbook.xlsx.readFile(workbookPath);
const expected = ["高校研究机构", "来源明细", "量化趋势判断", "覆盖与质量", "说明与口径"];
for (const name of expected) if (!workbook.getWorksheet(name)) throw new Error(`Missing sheet: ${name}`);

const registry = workbook.getWorksheet("高校研究机构");
const sources = workbook.getWorksheet("来源明细");
const outlooks = workbook.getWorksheet("量化趋势判断");
if (registry.rowCount !== 103) throw new Error(`Registry row count mismatch: ${registry.rowCount}`);
if (outlooks.rowCount !== 103) throw new Error(`Outlook row count mismatch: ${outlooks.rowCount}`);
if (sources.rowCount < 200) throw new Error(`Source coverage unexpectedly low: ${sources.rowCount}`);

const data = await readJson(path.join(ROOT, "data", "academic_quantitative_outlooks_20260922.json"));
const values = Object.values(data.outlooks);
const exactDuplicates = values.length - new Set(values.map((item) => item.trend_hypothesis)).size;
const pastThresholds = values.filter((item) => /202[0-6].*(Q[1-3]|上半年|前)/i.test(item.indicator_threshold.replace("2026-09-22", ""))).length;
const weakProbabilityViolations = values.filter((item) => item.evidence_status === "registry_baseline_only" && item.probability_high_pct > 45).length;
const emptyEvidenceUrls = values.filter((item) => !item.evidence_urls.length).length;
const formulaErrors = [];
for (const sheet of workbook.worksheets) {
  sheet.eachRow((row) => row.eachCell((cell) => {
    const text = String(cell.value?.result ?? cell.value ?? "");
    if (/^#(?:REF!|VALUE!|DIV\/0!|NAME\?|N\/A|NUM!|NULL!)/.test(text)) formulaErrors.push(`${sheet.name}!${cell.address}:${text}`);
  }));
}
if (exactDuplicates) throw new Error(`Exact duplicate outlooks: ${exactDuplicates}`);
if (pastThresholds) throw new Error(`Past-dated thresholds: ${pastThresholds}`);
if (weakProbabilityViolations) throw new Error(`Insufficient-evidence probability violations: ${weakProbabilityViolations}`);
if (emptyEvidenceUrls) throw new Error(`Empty evidence URLs: ${emptyEvidenceUrls}`);
if (formulaErrors.length) throw new Error(`Formula errors: ${formulaErrors.join(", ")}`);

const stat = await fs.stat(workbookPath);
console.log(JSON.stringify({ workbook: workbookPath, bytes: stat.size, sheets: workbook.worksheets.map((sheet) => ({ name: sheet.name, rows: sheet.rowCount, columns: sheet.columnCount })), exactDuplicates, pastThresholds, weakProbabilityViolations, emptyEvidenceUrls, formulaErrors: formulaErrors.length, maxPairwiseSimilarity: data.metrics.max_pairwise_similarity }, null, 2));
