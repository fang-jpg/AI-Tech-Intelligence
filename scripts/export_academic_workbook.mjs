import fs from "node:fs/promises";
import path from "node:path";
import ExcelJS from "exceljs";
import { DATASET_PATH, ROOT, readJson, toEntities } from "./lib.mjs";

const OUTPUT_DIR = path.join(ROOT, "outputs", "高校研究机构智能情报_20260922");
const OUTPUT_PATH = path.join(OUTPUT_DIR, "高校研究机构_AI技术情报量化研判_20260922.xlsx");
const PREVIEW_PATH = path.join(OUTPUT_DIR, "量化趋势判断_预览.html");
const search = await readJson(path.join(ROOT, "data", "academic_web_search_20260922.json"));
const analysis = await readJson(path.join(ROOT, "data", "academic_quantitative_outlooks_20260922.json"));
const entities = toEntities(await readJson(DATASET_PATH));
const outlooks = entities.map((entity) => analysis.outlooks[entity.id]);
await fs.mkdir(OUTPUT_DIR, { recursive: true });

const workbook = new ExcelJS.Workbook();
workbook.creator = "AI-Tech-Intelligence";
workbook.subject = "高校研究机构与研究者 AI 技术情报量化研判";
workbook.title = "高校研究机构 AI 技术情报量化研判 2026-09-22";
workbook.created = new Date("2026-09-22T00:00:00Z");
workbook.modified = new Date();
workbook.calcProperties.fullCalcOnLoad = true;

const colors = {
  navy: "1F4E78",
  blue: "D9EAF7",
  pale: "EAF2F8",
  green: "E2F0D9",
  yellow: "FFF2CC",
  red: "FCE4D6",
  white: "FFFFFF",
  text: "1F2937",
  gray: "667085",
  border: "D0D5DD",
};

function setupSheet(name, title, subtitle, columns) {
  const sheet = workbook.addWorksheet(name, { views: [{ state: "frozen", ySplit: 4, xSplit: name === "来源明细" ? 2 : 1 }] });
  sheet.columns = columns.map((column) => ({ key: column.key, width: column.width }));
  sheet.mergeCells(1, 1, 1, columns.length);
  sheet.getCell(1, 1).value = title;
  sheet.getCell(1, 1).font = { name: "Microsoft YaHei", size: 16, bold: true, color: { argb: colors.navy } };
  sheet.getCell(1, 1).alignment = { vertical: "middle" };
  sheet.getRow(1).height = 28;
  sheet.mergeCells(2, 1, 2, columns.length);
  sheet.getCell(2, 1).value = subtitle;
  sheet.getCell(2, 1).font = { name: "Microsoft YaHei", size: 10, italic: true, color: { argb: colors.gray } };
  sheet.getCell(2, 1).alignment = { wrapText: true, vertical: "middle" };
  sheet.getRow(2).height = 30;
  const header = sheet.getRow(4);
  header.values = columns.map((column) => column.header);
  header.height = 34;
  header.eachCell((cell) => {
    cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: colors.navy } };
    cell.font = { name: "Microsoft YaHei", size: 10, bold: true, color: { argb: colors.white } };
    cell.alignment = { horizontal: "center", vertical: "middle", wrapText: true };
    cell.border = { bottom: { style: "thin", color: { argb: colors.white } } };
  });
  sheet.autoFilter = { from: { row: 4, column: 1 }, to: { row: 4, column: columns.length } };
  sheet.properties.defaultRowHeight = 18;
  sheet.views = [{ state: "frozen", ySplit: 4, xSplit: name === "来源明细" ? 2 : 1, showGridLines: false }];
  return sheet;
}

function addDataRow(sheet, columns, values, height = 72) {
  const row = sheet.addRow(values);
  row.height = height;
  row.eachCell({ includeEmpty: true }, (cell, columnIndex) => {
    cell.font = { name: "Microsoft YaHei", size: 9, color: { argb: colors.text } };
    cell.alignment = { vertical: "top", wrapText: true };
    cell.border = { bottom: { style: "hair", color: { argb: colors.border } } };
    if (row.number % 2 === 1) cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "F8FAFC" } };
    const column = columns[columnIndex - 1];
    if (column?.format) cell.numFmt = column.format;
  });
  return row;
}

function setLink(cell, url) {
  if (!url) return;
  cell.value = { text: url, hyperlink: url, tooltip: url };
  cell.font = { name: "Microsoft YaHei", size: 9, color: { argb: "0563C1" }, underline: true };
}

const registryColumns = [
  { key: "id", header: "实体ID", width: 14 },
  { key: "name", header: "机构 / 姓名", width: 34 },
  { key: "region", header: "地区", width: 10 },
  { key: "type", header: "类型", width: 12 },
  { key: "homepage", header: "官网 / 主页", width: 42 },
  { key: "github", header: "GitHub", width: 38 },
  { key: "description", header: "研究重点说明", width: 62 },
];
const registry = setupSheet("高校研究机构", "高校研究机构与研究者注册表", "源自“高校科研机构”工作表，共 99 个实体；此页是搜索边界和官方来源白名单。", registryColumns);
for (const entity of entities) {
  const row = addDataRow(registry, registryColumns, [entity.id, entity.name, entity.region, entity.entity_type === "institution" ? "机构" : "个人", entity.homepage, entity.github, entity.description], 46);
  setLink(row.getCell(5), entity.homepage);
  setLink(row.getCell(6), entity.github);
}

const sourceColumns = [
  { key: "entity", header: "机构 / 姓名", width: 28 },
  { key: "type", header: "类型", width: 11 },
  { key: "title", header: "官方材料标题", width: 44 },
  { key: "url", header: "官方链接", width: 54 },
  { key: "date", header: "发布日期 / 线索日期", width: 18 },
  { key: "method", header: "发现方式", width: 28 },
  { key: "basis", header: "内容基础", width: 18 },
  { key: "excerpt", header: "搜索摘录 / 注册说明", width: 80 },
];
const sourceSheet = setupSheet("来源明细", "官方来源明细", "304 条去重来源；搜索摘录用于发现与初步研判，不等同于完整网页正文。", sourceColumns);
let sourceCount = 0;
for (const entity of entities) {
  for (const source of search.entities[entity.id]?.results ?? []) {
    const basis = source.discovery_method.startsWith("Registry baseline") ? "注册表基线" : "官方搜索摘录";
    const row = addDataRow(sourceSheet, sourceColumns, [entity.name, entity.entity_type === "institution" ? "机构" : "个人", source.title, source.url, source.published_date ?? "", source.discovery_method, basis, source.content], 74);
    setLink(row.getCell(4), source.url);
    if (basis === "注册表基线") row.eachCell((cell) => { cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: colors.yellow } }; });
    sourceCount += 1;
  }
}

const outlookColumns = [
  { key: "entity", header: "机构 / 姓名", width: 28 },
  { key: "type", header: "类型", width: 10 },
  { key: "trend", header: "独特未来技术判断", width: 62 },
  { key: "evidence", header: "证据链", width: 64 },
  { key: "why", header: "Why now / 推断逻辑", width: 54 },
  { key: "horizon", header: "预测窗口（月）", width: 14 },
  { key: "probLow", header: "主观概率下界", width: 14, format: "0%" },
  { key: "probHigh", header: "主观概率上界", width: 14, format: "0%" },
  { key: "stage", header: "成熟度 1-5", width: 12 },
  { key: "score", header: "证据分 0-100", width: 13 },
  { key: "level", header: "证据等级", width: 18 },
  { key: "indicator", header: "领先指标", width: 48 },
  { key: "threshold", header: "可核验阈值", width: 54 },
  { key: "counter", header: "反向信号", width: 44 },
  { key: "falsify", header: "证伪条件", width: 52 },
  { key: "rationale", header: "置信度说明", width: 48 },
  { key: "urls", header: "主要证据链接", width: 58 },
  { key: "status", header: "研判状态", width: 22 },
  { key: "similarity", header: "最高相似度", width: 13, format: "0.0%" },
  { key: "model", header: "分析模型", width: 18 },
];
const outlookSheet = setupSheet("量化趋势判断", "高校 / 研究者未来 AI 技术动向量化研判", "截至 2026-09-22；概率是证据约束的主观区间，不是客观频率或机构承诺。无数值基线时不输出虚构的性能涨幅。", outlookColumns);
for (const outlook of outlooks) {
  const row = addDataRow(outlookSheet, outlookColumns, [
    outlook.entity_name,
    outlook.entity_type === "institution" ? "机构" : "个人",
    outlook.trend_hypothesis,
    outlook.evidence_chain.join("\n• ").replace(/^/, "• "),
    outlook.why_now,
    `${outlook.horizon_months_low}-${outlook.horizon_months_high}`,
    outlook.probability_low_pct / 100,
    outlook.probability_high_pct / 100,
    outlook.maturity_stage_1_5,
    outlook.evidence_score_0_100,
    outlook.evidence_level,
    outlook.leading_indicator,
    outlook.indicator_threshold,
    outlook.counter_signals.join("\n• ").replace(/^/, "• "),
    outlook.falsification_criteria,
    outlook.confidence_rationale,
    outlook.evidence_urls.join("\n"),
    outlook.forecast_status === "insufficient_evidence" ? "证据不足 / 待补充" : "有证据研判",
    outlook.max_similarity,
    outlook.analysis_model,
  ], 122);
  if (outlook.forecast_status === "insufficient_evidence") {
    row.eachCell((cell) => { cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: colors.red } }; });
  } else if (outlook.evidence_score_0_100 >= 80) {
    row.getCell(10).fill = { type: "pattern", pattern: "solid", fgColor: { argb: colors.green } };
  } else {
    row.getCell(10).fill = { type: "pattern", pattern: "solid", fgColor: { argb: colors.yellow } };
  }
  const firstUrl = outlook.evidence_urls[0];
  if (firstUrl) {
    row.getCell(17).value = { text: outlook.evidence_urls.join("\n"), hyperlink: firstUrl, tooltip: firstUrl };
    row.getCell(17).font = { name: "Microsoft YaHei", size: 9, color: { argb: "0563C1" }, underline: true };
  }
}

const qualityColumns = [
  { key: "metric", header: "指标", width: 34 },
  { key: "value", header: "结果", width: 22 },
  { key: "explain", header: "正确解释", width: 92 },
];
const quality = setupSheet("覆盖与质量", "覆盖与质量检查", "指标用于说明可追溯性与覆盖边界，不应误解为人工语义评审达到 100%。", qualityColumns);
const levelCounts = Object.groupBy(outlooks, (item) => item.evidence_level);
const methodCounts = Object.groupBy(Object.values(search.entities).flatMap((item) => item.results), (item) => item.discovery_method);
const qualityRows = [
  ["注册实体", entities.length, "51 个机构 + 48 位个人研究者。"],
  ["来源记录", sourceCount, "URL 规范化后保留的官方域名、官方 GitHub 或注册表基线记录。"],
  ["有当前官方搜索线索的实体", analysis.metrics.current_evidence_entities, "至少有一条非注册表基线的官方搜索摘录。"],
  ["证据不足实体", analysis.metrics.insufficient_evidence_entities, "仅有注册表基线；概率上界被程序强制限制为 45%。"],
  ["Explicit", (levelCounts.Explicit ?? []).length, "输入摘录中存在明确计划、路线或时间性承诺；仍需阅读全文复核。"],
  ["Strong inference", (levelCounts["Strong inference"] ?? []).length, "多个具体信号一致，但原文未直接承诺预测结论。"],
  ["Speculative", (levelCounts.Speculative ?? []).length, "信号较弱或单一，采用宽概率区间。"],
  ["Insufficient", (levelCounts.Insufficient ?? []).length, "不足以形成证据支持的趋势判断。"],
  ["完全重复趋势", new Set(outlooks.map((item) => item.trend_hypothesis)).size === outlooks.length ? 0 : outlooks.length - new Set(outlooks.map((item) => item.trend_hypothesis)).size, "按完整文本精确去重。"],
  ["最高两两相似度", analysis.metrics.max_pairwise_similarity, "中文二元组 + 英文词元 Jaccard；低于 0.62 无需定向改写。"],
  ["待重复复核", analysis.metrics.duplicate_review_count, "相似度达到 0.62 的判断数量。"],
  ["分析模型", analysis.analysis_model, "实际持久化分析模型；未虚标为 GPT-5.6。"],
  ...Object.entries(methodCounts).map(([method, values]) => [`发现方式：${method}`, values.length, "来源发现记录数；同一实体可包含多种方式。"]),
];
for (const values of qualityRows) addDataRow(quality, qualityColumns, values, 34);
quality.getColumn(2).alignment = { horizontal: "center", vertical: "middle", wrapText: true };

const notesColumns = [
  { key: "field", header: "字段 / 口径", width: 28 },
  { key: "description", header: "说明", width: 112 },
];
const notes = setupSheet("说明与口径", "方法、量化口径与限制", "本页用于汇报时准确区分“搜索发现、证据评分、模型推断和事实”。", notesColumns);
const noteRows = [
  ["搜索范围", "99 个实体；优先注册官网与官方 GitHub。Tavily 用于规模化搜索，Serper 用于无有效结果时补搜，ChatGPT/Codex 内置 Web Search 用于代表性官方源增强。"],
  ["内容基础", "本轮持久化的是官方搜索摘录，不是所有网页的完整正文。表中的证据链与推断必须按‘摘要级证据’理解；重要判断应打开官方链接阅读全文复核。"],
  ["证据分 0-100", "程序化分数：来源数量、官方域名命中、2025-2026 时间信号与技术相关性组成；不是模型自评，也不是事实正确率。"],
  ["主观概率区间", "qwen3.7-plus 在给定摘要基础上的分析性区间。区间用于比较优先级，不能解释为统计频率、机构承诺或投资建议。"],
  ["成熟度 1-5", "1=早期研究线索；2=多项研究/原型；3=可复现实验或持续项目；4=稳定平台/广泛使用；5=成熟基础设施或标准化生态。"],
  ["量化克制", "若原文没有数值基线，expected_change 不填；本工作簿以概率区间、时间窗、成熟度和可观察阈值实现量化，避免臆造性能涨幅。"],
  ["证伪机制", "每条判断都有领先指标阈值和证伪条件。到期未达到阈值，或出现公开转向信号，应降低概率或撤销判断。"],
  ["重复控制", "趋势先由模型按实体专属项目生成，再以中文二元组 + 英文词元 Jaccard 做跨实体检测；阈值 0.62。本轮最高 0.386，待重复复核为 0。"],
  ["时间一致性", "所有可核验阈值统一从 2026-09-22 起按预测窗口计算；原始模型阈值保留在 JSON 的 indicator_threshold_original 字段供审计。"],
  ["不足处理", "16 个实体仅有注册表基线，标红为‘证据不足’，证据等级强制为 Insufficient，主观概率上界强制不超过 45%。"],
  ["模型边界", `发现层含 ChatGPT/Codex 内置 Web Search；批量分析层实际模型为 ${analysis.analysis_model}。当前 .env.txt 未配置 OPENAI_API_KEY，因此没有把结果标记为 GPT-5.6 分析。`],
  ["截至日期", "2026-09-22（America/New_York）。网页更新、索引延迟、反爬和动态渲染可能造成遗漏。"],
];
for (const values of noteRows) addDataRow(notes, notesColumns, values, 52);
notes.getColumn(1).eachCell((cell, rowNumber) => {
  if (rowNumber >= 5) cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: colors.blue } };
});

await workbook.xlsx.writeFile(OUTPUT_PATH);

const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
const previewRows = outlooks.slice(0, 25).map((item) => `<tr class="${item.forecast_status === "insufficient_evidence" ? "insufficient" : ""}"><td>${escape(item.entity_name)}</td><td>${escape(item.trend_hypothesis)}</td><td>${item.probability_low_pct}–${item.probability_high_pct}%</td><td>${item.evidence_score_0_100}</td><td>${escape(item.indicator_threshold)}</td><td>${escape(item.evidence_level)}</td></tr>`).join("\n");
await fs.writeFile(PREVIEW_PATH, `<!doctype html><meta charset="utf-8"><title>量化趋势判断预览</title><style>body{font-family:"Microsoft YaHei",Arial,sans-serif;margin:24px;color:#1f2937}h1{color:#1f4e78;font-size:24px}p{color:#667085}table{border-collapse:collapse;width:100%;font-size:12px}th{background:#1f4e78;color:white;position:sticky;top:0}th,td{border:1px solid #d0d5dd;padding:8px;vertical-align:top}tr:nth-child(odd){background:#f8fafc}.insufficient{background:#fce4d6!important}td:nth-child(1){width:13%}td:nth-child(2){width:34%}td:nth-child(3),td:nth-child(4),td:nth-child(6){text-align:center;white-space:nowrap}td:nth-child(5){width:30%}</style><h1>高校 / 研究者未来 AI 技术动向量化研判</h1><p>截至 2026-09-22；显示前 25 行用于视觉检查。概率为主观分析区间。</p><table><thead><tr><th>机构 / 姓名</th><th>独特未来技术判断</th><th>概率区间</th><th>证据分</th><th>可核验阈值</th><th>证据等级</th></tr></thead><tbody>${previewRows}</tbody></table>`, "utf8");

console.log(JSON.stringify({ output: OUTPUT_PATH, preview: PREVIEW_PATH, sheets: workbook.worksheets.map((sheet) => sheet.name), entities: entities.length, sources: sourceCount }, null, 2));
