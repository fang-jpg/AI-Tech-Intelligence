import fs from "node:fs/promises";
import path from "node:path";
import { ROOT } from "./lib.mjs";

export const technologyTaxonomy = JSON.parse(
  await fs.readFile(path.join(ROOT, "config", "technology_taxonomy.json"), "utf8"),
);

const maturityLabels = {
  1: "早期研究",
  2: "多项研究/原型",
  3: "可复现实验/持续项目",
  4: "产品化/规模采用",
  5: "成熟基础设施/标准生态",
};

export function classifyText(parts, maxCategories = 3) {
  const text = parts.map((value) => String(value ?? "")).join("\n").toLowerCase();
  return technologyTaxonomy
    .map((category, order) => {
      const matchedKeywords = [];
      let score = 0;
      for (const keyword of category.keywords) {
        const normalized = String(keyword).toLowerCase();
        let start = 0;
        let count = 0;
        while ((start = text.indexOf(normalized, start)) >= 0) {
          count += 1;
          start += Math.max(1, normalized.length);
        }
        if (count) {
          matchedKeywords.push(keyword);
          score += Math.min(count, 3);
        }
      }
      return { ...category, order, score, matched_keywords: matchedKeywords };
    })
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || a.order - b.order)
    .slice(0, maxCategories);
}

export function inferMaturity(record) {
  const text = [record.title, record.trend, record.statement, record.sourceType, record.evidence]
    .map((value) => String(value ?? ""))
    .join(" ")
    .toLowerCase();
  const confidence = Number(record.confidence) || 0;
  let stage = 1;
  if ((record.categories?.length ?? 0) >= 2) stage = 2;
  if (/benchmark|评测|prototype|原型|demo|演示|release|发布|open weight|开放权重|持续项目/i.test(text)) stage = Math.max(stage, 3);
  if (/production|deployed|deployment|commercial|产品|客户|用户|收入|api|maas|规模化|量产|上线/i.test(text)) stage = Math.max(stage, 4);
  if (/standardized|standardisation|standardization|行业标准|标准化|广泛采用|widely adopted/i.test(text) && confidence >= 0.8) stage = 5;
  if (confidence > 0 && confidence < 0.45) stage = Math.min(stage, 2);
  return { stage, label: maturityLabels[stage] };
}

export function adoptionStage(record, maturity = inferMaturity(record).stage) {
  const text = [record.title, record.trend, record.statement, record.evidence].join(" ").toLowerCase();
  if (maturity >= 4 && /commercial|客户|用户|收入|production|规模化|量产|上线|api|maas/i.test(text)) return "规模应用";
  if (maturity >= 3) return "工程验证/产品导入";
  if (maturity >= 2) return "研究原型";
  return "研究探索";
}

export function normalizeClassificationRecords(sourceRecords) {
  const output = [];
  for (const record of sourceRecords) {
    const categories = classifyText(
      [record.title, record.tags, record.evidence, record.trend, record.statement],
      3,
    );
    const effective = categories.length
      ? categories
      : [{
        id: "other",
        name: "其他前沿技术与应用",
        module_terms: ["应用与交叉方向"],
        product_focus: "当前证据未稳定映射到既定技术分类，建议人工复核后再纳入技术路线比较。",
        score: 1,
        matched_keywords: [],
      }];
    const normalized = { ...record, categories: effective };
    const maturity = inferMaturity(normalized);
    for (let index = 0; index < effective.length; index += 1) {
      const category = effective[index];
      output.push({
        ...record,
        categoryId: category.id,
        category: category.name,
        categoryOrder: category.order ?? 999,
        isPrimary: index === 0,
        matchedKeywords: category.matched_keywords,
        module: category.matched_keywords.slice(0, 4).join("、") || category.module_terms.slice(0, 3).join("、"),
        maturityStage: maturity.stage,
        maturityLabel: maturity.label,
        adoptionStage: adoptionStage(normalized, maturity.stage),
        productFocus: category.product_focus,
      });
    }
  }
  return output;
}

function topValues(values, limit = 5) {
  const counts = new Map();
  for (const value of values.filter(Boolean)) counts.set(value, (counts.get(value) ?? 0) + 1);
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0]), "zh-CN"))
    .slice(0, limit)
    .map(([value]) => value);
}

function evidenceRank(row) {
  return (row.sourceKind === "企业高管" ? 3 : 0) + Number(row.confidence || 0) * 2 + Number(row.maturityStage || 0) / 5;
}

export function buildEvolutionRows(classificationRows) {
  const rows = [];
  for (const category of [...technologyTaxonomy, { id: "other", name: "其他前沿技术与应用", product_focus: "建议人工复核并补充分类规则。" }]) {
    const items = classificationRows.filter((item) => item.categoryId === category.id);
    if (!items.length) continue;
    const ranked = [...items].sort((a, b) => evidenceRank(b) - evidenceRank(a));
    const institutions = [...new Set(items.filter((item) => item.sourceKind !== "企业高管").map((item) => item.subject))];
    const executives = [...new Set(items.filter((item) => item.sourceKind === "企业高管").map((item) => `${item.subject}/${item.sourceName}`))];
    const averageMaturity = items.reduce((sum, item) => sum + item.maturityStage, 0) / items.length;
    const maxMaturity = Math.max(...items.map((item) => item.maturityStage));
    const confidenceValues = items
      .map((item) => item.confidence)
      .filter((value) => value !== null && value !== "" && Number.isFinite(Number(value)))
      .map(Number);
    const averageConfidence = confidenceValues.length
      ? confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length
      : null;
    const strongest = ranked.slice(0, 3);
    const adoption = topValues(items.map((item) => item.adoptionStage), 2).join(" / ");
    const evidenceLevel = topValues(items.map((item) => item.evidenceLevel), 2).join(" / ") || "待复核";
    rows.push({
      category: category.name,
      modules: topValues(items.flatMap((item) => String(item.module ?? "").split("、")), 5).join("、"),
      status: `${maturityLabels[Math.max(1, Math.min(5, Math.round(averageMaturity)))]}；最高信号达到“${maturityLabels[maxMaturity]}”`,
      adoption,
      signalCount: items.length,
      subjectCount: new Set(items.map((item) => item.subject)).size,
      institutionExamples: institutions.slice(0, 6).join("、") || "—",
      executiveExamples: executives.slice(0, 6).join("、") || "—",
      representativeEvidence: strongest.map((item) => `${item.subject}：${String(item.evidence || item.statement || item.title).slice(0, 180)}`).join("\n"),
      nextSignals: strongest.map((item) => item.trend).filter(Boolean).slice(0, 2).join("\n") || "关注正式论文、模型/数据集发布、产品上线或基础设施扩容等可核验信号。",
      productImpact: category.product_focus,
      evidenceLevel,
      confidence: averageConfidence,
      urls: [...new Set(strongest.map((item) => item.url).filter(Boolean))].join("\n"),
    });
  }
  return rows;
}

function positioning(topCategories) {
  const ids = new Set(topCategories.map((item) => item.categoryId));
  if (ids.has("llm") && ids.has("agent") && ids.has("efficiency_infra")) return "基础模型、Agent与基础设施协同推进";
  if (ids.has("multimodal") && ids.has("agent")) return "多模态能力向任务执行与产品工作流延伸";
  if (ids.has("embodied") || ids.has("world_model")) return "以物理世界建模和交互为主要前沿方向";
  if (ids.has("safety_eval")) return "以评测、安全与治理研究形成技术影响力";
  return `重点围绕${topCategories.slice(0, 3).map((item) => item.category).join("、")}形成技术组合`;
}

export function buildStrategicProfiles(classificationRows, maxAcademic = 18) {
  const bySubject = new Map();
  for (const row of classificationRows.filter((item) => item.isPrimary)) {
    if (!bySubject.has(row.subject)) bySubject.set(row.subject, []);
    bySubject.get(row.subject).push(row);
  }
  const subjects = [...bySubject.entries()].map(([subject, items]) => ({
    subject,
    items,
    sourceKind: items.some((item) => item.sourceKind === "企业高管") ? "企业/高管" : "高校/研究机构",
    score: new Set(items.map((item) => item.url).filter(Boolean)).size + items.reduce((sum, item) => sum + Number(item.confidence || 0), 0),
  }));
  const companies = subjects.filter((item) => item.sourceKind === "企业/高管");
  const academics = subjects.filter((item) => item.sourceKind !== "企业/高管").sort((a, b) => b.score - a.score).slice(0, maxAcademic);
  return [...companies, ...academics]
    .sort((a, b) => (a.sourceKind === "企业/高管" ? 0 : 1) - (b.sourceKind === "企业/高管" ? 0 : 1) || b.score - a.score)
    .map(({ subject, items, sourceKind }) => {
      const categoryCounts = new Map();
      for (const item of items) categoryCounts.set(item.categoryId, (categoryCounts.get(item.categoryId) ?? 0) + 1);
      const topCategories = [...categoryCounts.entries()]
        .map(([id, count]) => ({ ...items.find((item) => item.categoryId === id), count }))
        .sort((a, b) => b.count - a.count)
        .slice(0, 4);
      const ranked = [...items].sort((a, b) => evidenceRank(b) - evidenceRank(a));
      const productItems = ranked.filter((item) => /产品|应用|平台|服务|用户|客户|api|app|部署|上线|commercial|product/i.test(`${item.title} ${item.evidence} ${item.statement}`));
      const infraItems = ranked.filter((item) => /资本|投资|组织|部门|芯片|算力|服务器|数据中心|基础设施|cloud|gpu|xpu|training center/i.test(`${item.title} ${item.evidence} ${item.statement}`));
      const confidenceValues = items
        .map((item) => item.confidence)
        .filter((value) => value !== null && value !== "" && Number.isFinite(Number(value)))
        .map(Number);
      return {
        subject,
        sourceKind,
        positioning: positioning(topCategories),
        research: topCategories.map((item) => `${item.category}（${item.module}）`).join("\n"),
        products: (productItems.length ? productItems : ranked).slice(0, 2).map((item) => String(item.evidence || item.statement || item.title).slice(0, 220)).join("\n"),
        organizationInfra: infraItems.slice(0, 2).map((item) => String(item.evidence || item.statement || item.title).slice(0, 220)).join("\n") || "现有材料未形成可核验的组织、资本或基础设施动作信号。",
        keyActions: ranked.slice(0, 3).map((item) => `${item.date || "日期待核验"}：${item.title}`).join("\n"),
        outlook: ranked.map((item) => item.trend).find(Boolean) || "现有材料不足以形成主体级趋势判断。",
        leadingIndicators: `未来更新时重点核验：${topCategories.slice(0, 3).map((item) => item.category).join("、")}方向的正式发布、公开评测或产品落地。`,
        risks: ranked.some((item) => /待复核|未通过|摘要级|baseline|基线/i.test(`${item.evidenceStatus} ${item.contentBasis}`)) ? "部分证据为搜索摘录或待全文复核；结论需随原文与后续发布更新。" : "若后续正式发布、产品采用或评测结果未延续当前信号，应下调判断。",
        evidenceLevel: topValues(items.map((item) => item.evidenceLevel), 2).join(" / ") || "待复核",
        confidence: confidenceValues.length ? confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length : null,
        urls: [...new Set(ranked.map((item) => item.url).filter(Boolean))].slice(0, 4).join("\n"),
      };
    });
}
