import fs from "node:fs/promises";
import path from "node:path";
import ExcelJS from "exceljs";
import { DATASET_PATH, ROOT, readJson, toEntities } from "./lib.mjs";
import { buildEvolutionRows, buildStrategicProfiles, normalizeClassificationRecords } from "./technology_intelligence.mjs";

const INPUT_PATH = path.join(ROOT, "outputs", "ai_executive_intelligence_web_20260921.xlsx");
const OUTPUT_PATH = path.join(ROOT, "outputs", "ai_executive_intelligence_web_20260921_高校研究机构补充_20260923.xlsx");
const SEARCH_PATH = path.join(ROOT, "data", "academic_web_search_20260922.json");
const SUMMARY_PATH = path.join(ROOT, "data", "academic_source_summaries_20260923.json");
const OUTLOOK_PATH = path.join(ROOT, "data", "academic_quantitative_outlooks_20260922.json");

const [search, summaries, analysis, registryRows] = await Promise.all([
  readJson(SEARCH_PATH), readJson(SUMMARY_PATH), readJson(OUTLOOK_PATH), readJson(DATASET_PATH),
]);
const entities = toEntities(registryRows);
const workbook = new ExcelJS.Workbook();
await workbook.xlsx.readFile(INPUT_PATH);

for (const name of ["高校研究机构情报", "高校趋势汇总", "前沿技术分类", "技术演进沙盘", "主体战略画像"]) {
  const existing = workbook.getWorksheet(name);
  if (existing) workbook.removeWorksheet(existing.id);
}

const colors = {
  navy: "1F4E78", white: "FFFFFF", text: "1F2937", gray: "5B6573",
  border: "D9E2F3", stripe: "F8FAFC", green: "E6F4EA", red: "FCE8E6",
  yellow: "FFF2CC", blue: "DCE6F1",
};

function titleAndHeaders(sheet, title, subtitle, headers) {
  sheet.mergeCells(1, 1, 1, headers.length);
  sheet.getCell(1, 1).value = title;
  sheet.getCell(1, 1).font = { name: "Arial", size: 15, bold: true, color: { argb: colors.navy } };
  sheet.mergeCells(2, 1, 2, headers.length);
  sheet.getCell(2, 1).value = subtitle;
  sheet.getCell(2, 1).font = { name: "Arial", size: 10, italic: true, color: { argb: colors.gray } };
  sheet.getCell(2, 1).alignment = { wrapText: true, vertical: "middle" };
  const row = sheet.getRow(4);
  row.values = headers;
  row.height = 32;
  row.eachCell((cell) => {
    cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: colors.navy } };
    cell.font = { name: "Arial", size: 10, bold: true, color: { argb: colors.white } };
    cell.alignment = { horizontal: "center", vertical: "middle", wrapText: true };
  });
  sheet.autoFilter = { from: { row: 4, column: 1 }, to: { row: 4, column: headers.length } };
  sheet.views = [{ state: "frozen", ySplit: 4, xSplit: 2, showGridLines: false }];
}

function styleBodyRow(row, height = 112) {
  row.height = height;
  row.eachCell({ includeEmpty: true }, (cell) => {
    cell.font = { name: "Arial", size: 10, color: { argb: colors.text } };
    cell.alignment = { vertical: "top", wrapText: true };
    cell.border = { bottom: { style: "hair", color: { argb: colors.border } } };
    if (row.number % 2 === 1) cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: colors.stripe } };
  });
}

function setLink(cell, url, text = url) {
  if (!url) return;
  cell.value = { text, hyperlink: url, tooltip: url };
  cell.font = { name: "Arial", size: 10, color: { argb: "0563C1" }, underline: true };
}

function parseDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? null : date;
}

function sourceType(entity, source) {
  if (source.discovery_method?.startsWith("Registry baseline")) return "registry_baseline";
  if (/github\.com/i.test(source.url)) return "official_code";
  return entity.entity_type === "researcher" ? "official_personal" : "official_research";
}

const detailHeaders = ["模型厂商", "高管/来源", "职位", "日期", "来源类型", "原文标题", "官方链接", "检索方式", "内容基础", "核心观点", "技术标签", "AI未来模型动向分析", "证据等级", "置信度", "时间窗口", "来源等级", "是否官方", "归因状态", "证据校验", "分析模型"];
const detail = workbook.addWorksheet("高校研究机构情报");
titleAndHeaders(detail, "高校研究机构与研究者技术情报", "沿用原工作簿 20 列口径；每条链接单独总结，同一实体的未来趋势仅在首条来源出现一次，避免重复。", detailHeaders);
const detailWidths = [30, 28, 26, 14, 20, 44, 56, 29, 19, 64, 34, 72, 18, 12, 24, 12, 12, 29, 18, 31];
detailWidths.forEach((width, index) => { detail.getColumn(index + 1).width = width; });

let sourceRows = 0;
let trendRows = 0;
let directStatementRows = 0;
const technologySourceRecords = [];
for (const entity of entities) {
  const sources = search.entities[entity.id]?.results ?? [];
  const outlook = analysis.outlooks[entity.id];
  sources.forEach((source, index) => {
    const sourceId = `${entity.id}_source_${String(index + 1).padStart(2, "0")}`;
    const summary = summaries.summaries[sourceId];
    const isFirst = index === 0;
    const isBaseline = summary.summary_status === "baseline_only";
    const type = sourceType(entity, source);
    const trend = isFirst
      ? `【独特趋势判断】${outlook.trend_hypothesis}\n【主观概率】${outlook.probability_low_pct}%–${outlook.probability_high_pct}%\n【领先指标】${outlook.leading_indicator}\n【可核验阈值】${outlook.indicator_threshold}\n【证伪条件】${outlook.falsification_criteria}`
      : "";
    const row = detail.addRow([
      entity.name,
      entity.name,
      entity.entity_type === "institution" ? "高校 / 研究机构" : "研究者 / 技术公共发声者",
      parseDate(source.published_date),
      type,
      source.title,
      source.url,
      source.discovery_method,
      isBaseline ? "注册表基线" : "官方搜索摘录",
      summary.core_points.map((point, pointIndex) => `${pointIndex + 1}. ${point}`).join("\n"),
      summary.technical_tags.join(", "),
      trend,
      isFirst ? outlook.evidence_level : "",
      isFirst ? outlook.probability_midpoint_pct / 100 : null,
      isFirst ? `${outlook.horizon_months_low}-${outlook.horizon_months_high}个月（自2026-09-22）` : "",
      type === "official_research" ? "A" : "B",
      "是",
      summary.direct_statement ? "具名发言线索 / 待全文复核" : (entity.entity_type === "researcher" ? "官方个人来源 / 未提取直接引语" : "官方机构材料"),
      isBaseline ? "待补充近期正文" : "摘要级通过",
      `${summary.analysis_method} / ${summary.analysis_model}${isFirst ? `；quantitative_outlook / ${outlook.analysis_model}` : ""}`,
    ]);
    styleBodyRow(row, isFirst ? 142 : 98);
    if (row.getCell(4).value) row.getCell(4).numFmt = "yyyy-mm-dd";
    if (isFirst) row.getCell(14).numFmt = "0%";
    row.getCell(7).value = { text: source.url, hyperlink: source.url, tooltip: source.url };
    row.getCell(7).font = { name: "Arial", size: 10, color: { argb: "0563C1" }, underline: true };
    if (isBaseline) {
      row.getCell(9).fill = { type: "pattern", pattern: "solid", fgColor: { argb: colors.yellow } };
      row.getCell(19).fill = { type: "pattern", pattern: "solid", fgColor: { argb: colors.red } };
    } else {
      row.getCell(19).fill = { type: "pattern", pattern: "solid", fgColor: { argb: colors.green } };
    }
    if (isFirst) {
      row.getCell(12).fill = { type: "pattern", pattern: "solid", fgColor: { argb: outlook.forecast_status === "insufficient_evidence" ? colors.red : colors.blue } };
      trendRows += 1;
    }
    if (summary.direct_statement) directStatementRows += 1;
    technologySourceRecords.push({
      sourceKind: entity.entity_type === "institution" ? "高校/研究机构" : "研究者/技术发言人",
      subject: entity.name,
      sourceName: entity.name,
      role: entity.entity_type === "institution" ? "高校 / 研究机构" : "研究者 / 技术公共发声者",
      date: source.published_date ?? "",
      title: source.title,
      url: source.url,
      tags: summary.technical_tags.join(", "),
      evidence: summary.core_points.join("；"),
      statement: summary.direct_statement ? summary.core_points.join("；") : "",
      trend: outlook.trend_hypothesis,
      evidenceLevel: outlook.evidence_level,
      confidence: outlook.probability_midpoint_pct / 100,
      timeWindow: `${outlook.horizon_months_low}-${outlook.horizon_months_high}个月（自2026-09-22）`,
      contentBasis: isBaseline ? "注册表基线" : "官方搜索摘录",
      evidenceStatus: isBaseline ? "待补充近期正文" : "摘要级通过",
      model: `${summary.analysis_method} / ${summary.analysis_model}`,
    });
    sourceRows += 1;
  });
}

const trendHeaders = ["模型厂商", "来源数", "高管发言数", "已分析数", "最新日期", "主要技术标签", "代表性趋势判断", "平均置信度"];
const trendSheet = workbook.addWorksheet("高校趋势汇总");
titleAndHeaders(trendSheet, "高校研究机构与研究者趋势汇总", "每个实体一行；趋势已做跨实体重复检查，概率为证据约束的主观区间。", trendHeaders);
[32, 12, 14, 12, 14, 42, 88, 14].forEach((width, index) => { trendSheet.getColumn(index + 1).width = width; });
for (const entity of entities) {
  const sources = search.entities[entity.id]?.results ?? [];
  const outlook = analysis.outlooks[entity.id];
  const sourceIds = sources.map((_, index) => `${entity.id}_source_${String(index + 1).padStart(2, "0")}`);
  const entitySummaries = sourceIds.map((id) => summaries.summaries[id]);
  const tags = [...new Set(entitySummaries.flatMap((summary) => summary.technical_tags))].slice(0, 8).join(", ");
  const dates = sources.map((source) => parseDate(source.published_date)).filter(Boolean).sort((a, b) => b - a);
  const statementCount = entitySummaries.filter((summary) => summary.direct_statement).length;
  const row = trendSheet.addRow([
    entity.name,
    sources.length,
    statementCount,
    1,
    dates[0] ?? null,
    tags,
    `${outlook.trend_hypothesis}\n概率区间：${outlook.probability_low_pct}%–${outlook.probability_high_pct}%；窗口：${outlook.horizon_months_low}-${outlook.horizon_months_high}个月。`,
    outlook.probability_midpoint_pct / 100,
  ]);
  styleBodyRow(row, 80);
  if (dates[0]) row.getCell(5).numFmt = "yyyy-mm-dd";
  row.getCell(8).numFmt = "0%";
  if (outlook.forecast_status === "insufficient_evidence") row.getCell(7).fill = { type: "pattern", pattern: "solid", fgColor: { argb: colors.red } };
}

const executiveSheet = workbook.getWorksheet("高管发言");
if (executiveSheet) {
  for (let rowNumber = 5; rowNumber <= executiveSheet.rowCount; rowNumber += 1) {
    const row = executiveSheet.getRow(rowNumber);
    if (!String(row.getCell(1).value ?? "").trim()) continue;
    const linkValue = row.getCell(10).value;
    const url = typeof linkValue === "object" && linkValue?.hyperlink ? linkValue.hyperlink : String(linkValue ?? "");
    technologySourceRecords.push({
      sourceKind: "企业高管",
      subject: String(row.getCell(1).value ?? ""),
      sourceName: String(row.getCell(2).value ?? ""),
      role: String(row.getCell(3).value ?? ""),
      date: row.getCell(4).value ?? "",
      title: String(row.getCell(5).value ?? "").slice(0, 240),
      url,
      tags: "",
      evidence: String(row.getCell(6).value ?? ""),
      statement: String(row.getCell(5).value ?? ""),
      trend: String(row.getCell(7).value ?? ""),
      evidenceLevel: String(row.getCell(8).value ?? ""),
      confidence: Number(row.getCell(9).value) || null,
      timeWindow: "",
      contentBasis: String(row.getCell(11).value ?? ""),
      evidenceStatus: "具名高管发言 / 原文可追溯",
      model: String(row.getCell(12).value ?? ""),
    });
  }
}

const classificationRows = normalizeClassificationRecords(technologySourceRecords);
const classificationHeaders = ["信息源类型", "主体", "发言人/来源", "职位", "日期", "一级技术分类", "技术模块/命中词", "是否主分类", "证据摘要", "趋势/主张", "成熟度 1-5", "成熟度说明", "采用阶段", "证据等级", "置信度", "时间窗口", "官方链接", "内容基础", "归因/证据状态", "分析模型"];
const classificationSheet = workbook.addWorksheet("前沿技术分类");
titleAndHeaders(classificationSheet, "高校研究机构与高管发言前沿技术分类", `按统一技术分类展开 ${technologySourceRecords.length} 条材料；一条材料可映射至最多 3 个技术方向，主分类用于优先排序。`, classificationHeaders);
[18, 28, 26, 24, 14, 26, 32, 12, 62, 68, 12, 22, 22, 18, 12, 24, 56, 20, 30, 32].forEach((width, index) => { classificationSheet.getColumn(index + 1).width = width; });
for (const item of classificationRows) {
  const row = classificationSheet.addRow([
    item.sourceKind, item.subject, item.sourceName, item.role, parseDate(item.date), item.category, item.module,
    item.isPrimary ? "是" : "否", item.evidence, item.trend, item.maturityStage, item.maturityLabel, item.adoptionStage,
    item.evidenceLevel, item.confidence, item.timeWindow, item.url, item.contentBasis, item.evidenceStatus, item.model,
  ]);
  styleBodyRow(row, 100);
  if (row.getCell(5).value) row.getCell(5).numFmt = "yyyy-mm-dd";
  if (item.confidence !== null) row.getCell(15).numFmt = "0%";
  if (item.url) setLink(row.getCell(17), item.url);
}

const evolutionHeaders = ["前沿技术", "核心模块/演进方向", "技术状态", "采用阶段", "信号数", "主体数", "代表高校/机构", "代表厂商/发言人", "代表证据", "未来可观察变化", "产品/战略影响", "证据等级", "平均置信度", "主要来源"];
const evolutionSheet = workbook.addWorksheet("技术演进沙盘");
titleAndHeaders(evolutionSheet, "前沿技术演进沙盘", "横向汇总高校研究、研究者材料与企业高管发言；成熟度和采用阶段来自可观察证据，不把模型推断写成已确认事实。", evolutionHeaders);
[26, 36, 34, 24, 10, 10, 48, 48, 76, 76, 68, 22, 14, 58].forEach((width, index) => { evolutionSheet.getColumn(index + 1).width = width; });
for (const item of buildEvolutionRows(classificationRows)) {
  const row = evolutionSheet.addRow([item.category, item.modules, item.status, item.adoption, item.signalCount, item.subjectCount, item.institutionExamples, item.executiveExamples, item.representativeEvidence, item.nextSignals, item.productImpact, item.evidenceLevel, item.confidence, item.urls]);
  styleBodyRow(row, 126);
  if (item.confidence !== null) row.getCell(13).numFmt = "0%";
  if (item.urls) setLink(row.getCell(14), item.urls.split("\n")[0], item.urls);
}

const profileHeaders = ["主体", "类型", "核心定位", "研究路线", "产品/应用信号", "组织/资本/基础设施", "关键行动", "未来重点", "领先指标", "风险/反向信号", "证据等级", "平均置信度", "主要来源"];
const profileSheet = workbook.addWorksheet("主体战略画像");
titleAndHeaders(profileSheet, "主体战略画像", "优先展示企业高管主体和证据较丰富的高校/研究机构；空缺表示当前材料没有形成可核验信号。", profileHeaders);
[28, 16, 38, 52, 68, 68, 64, 76, 60, 56, 20, 14, 58].forEach((width, index) => { profileSheet.getColumn(index + 1).width = width; });
for (const item of buildStrategicProfiles(classificationRows)) {
  const row = profileSheet.addRow([item.subject, item.sourceKind, item.positioning, item.research, item.products, item.organizationInfra, item.keyActions, item.outlook, item.leadingIndicators, item.risks, item.evidenceLevel, item.confidence, item.urls]);
  styleBodyRow(row, 132);
  if (item.confidence !== null) row.getCell(12).numFmt = "0%";
  if (item.urls) setLink(row.getCell(13), item.urls.split("\n")[0], item.urls);
}

const notes = workbook.getWorksheet("说明与口径");
if (notes) {
  const additions = [
    ["高校补充范围", "新增 51 个高校/研究机构与 48 位研究者，共 99 个实体；来源来自注册官网、个人主页、官方研究页和官方 GitHub。"],
    ["高校来源摘要", `共 ${sourceRows} 条链接，全部由 ${summaries.analysis_model} 基于官方搜索摘录或注册表说明生成逐链接摘要；未把机构文章冒充个人发言。`],
    ["趋势去重", `每个实体只在首条来源填写一次未来趋势；共 ${trendRows} 条独特趋势，精确重复 0，最高两两相似度 ${analysis.metrics.max_pairwise_similarity}。`],
    ["量化口径", "趋势包含主观概率区间、时间窗口、领先指标、可核验阈值和证伪条件。没有数值基线时不虚构模型性能涨幅。"],
    ["证据限制", "高校补充页主要使用官方搜索摘录，不等于完整网页正文；具名发言线索和重要趋势应打开官方链接阅读全文复核。"],
    ["前沿技术分类", "统一分类覆盖 LLM、多模态、世界模型、具身智能、预训练、后训练、Agent、推理、长上下文、效率与基础设施、AI for Science、安全评测、开源生态和端侧 AI。一条材料最多映射 3 个方向。"],
    ["技术演进沙盘", "成熟度和采用阶段由材料中的研究、原型、发布、部署、客户或规模化信号确定；代表证据、主要来源和反向信号用于复核，不是厂商承诺。"],
  ];
  for (const values of additions) {
    const row = notes.addRow(values);
    row.height = 46;
    row.eachCell({ includeEmpty: true }, (cell) => {
      cell.font = { name: "Arial", size: 10, color: { argb: colors.text } };
      cell.alignment = { vertical: "top", wrapText: true };
      cell.border = { bottom: { style: "thin", color: { argb: colors.border } } };
    });
    row.getCell(1).fill = { type: "pattern", pattern: "solid", fgColor: { argb: colors.blue } };
  }
}

await fs.mkdir(path.dirname(OUTPUT_PATH), { recursive: true });
await workbook.xlsx.writeFile(OUTPUT_PATH);
const stat = await fs.stat(OUTPUT_PATH);
console.log(JSON.stringify({ input: INPUT_PATH, output: OUTPUT_PATH, bytes: stat.size, sourceRows, trendRows, directStatementRows, classifiedRows: classificationRows.length, evolutionRows: evolutionSheet.rowCount - 4, profileRows: profileSheet.rowCount - 4, sheets: workbook.worksheets.map((sheet) => sheet.name) }, null, 2));
