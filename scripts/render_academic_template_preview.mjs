import fs from "node:fs/promises";
import path from "node:path";
import ExcelJS from "exceljs";
import { ROOT } from "./lib.mjs";

const workbookPath = path.join(ROOT, "outputs", "ai_executive_intelligence_web_20260921_高校研究机构补充_20260923.xlsx");
const outputPath = path.join(ROOT, "outputs", "高校研究机构情报_模板预览.html");
const workbook = new ExcelJS.Workbook();
await workbook.xlsx.readFile(workbookPath);
const sheet = workbook.getWorksheet("高校研究机构情报");
const columns = [1, 2, 3, 6, 7, 10, 11, 12, 13, 14, 15, 19];
const headers = columns.map((column) => sheet.getRow(4).getCell(column).text);
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
const rows = [];
for (let rowNumber = 5; rowNumber <= Math.min(sheet.rowCount, 26); rowNumber += 1) {
  const row = sheet.getRow(rowNumber);
  rows.push(`<tr>${columns.map((column) => `<td>${escape(row.getCell(column).text)}</td>`).join("")}</tr>`);
}
const html = `<!doctype html><meta charset="utf-8"><title>高校研究机构情报预览</title><style>body{font-family:"Microsoft YaHei",Arial,sans-serif;margin:22px;color:#1f2937}h1{font-size:24px;color:#1f4e78}p{color:#5b6573}table{border-collapse:collapse;width:100%;font-size:11px}th{background:#1f4e78;color:#fff}th,td{border:1px solid #d9e2f3;padding:7px;vertical-align:top;white-space:pre-wrap}tr:nth-child(odd){background:#f8fafc}td:nth-child(1),td:nth-child(2),td:nth-child(3){min-width:120px}td:nth-child(4){min-width:210px}td:nth-child(5){max-width:240px;word-break:break-all}td:nth-child(6),td:nth-child(8){min-width:360px}td:nth-child(7){min-width:170px}</style><h1>高校研究机构与研究者技术情报</h1><p>模板列预览：前 22 条来源。未来趋势仅出现在每个实体的首条来源行。</p><table><thead><tr>${headers.map((header) => `<th>${escape(header)}</th>`).join("")}</tr></thead><tbody>${rows.join("\n")}</tbody></table>`;
await fs.writeFile(outputPath, html, "utf8");
console.log(outputPath);
