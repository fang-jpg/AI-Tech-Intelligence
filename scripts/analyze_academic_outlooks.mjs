import path from "node:path";
import { DATASET_PATH, ROOT, clamp, evidenceScore, fetchJson, jaccard, loadEnv, readJson, toEntities, writeJson } from "./lib.mjs";

const SEARCH_PATH = path.join(ROOT, "data", "academic_web_search_20260922.json");
const OUTPUT_PATH = path.join(ROOT, "data", "academic_quantitative_outlooks_20260922.json");
const env = await loadEnv();
const entities = toEntities(await readJson(DATASET_PATH));
const search = await readJson(SEARCH_PATH);
const existing = await readJson(OUTPUT_PATH).catch(() => ({ generated_at: null, analysis_model: null, outlooks: {} }));
const apiKey = env.GENERAL_AI_REPORT_LLM_API_KEY;
const baseUrl = String(env.GENERAL_AI_REPORT_LLM_BASE_URL ?? "").replace(/\/$/, "");
const model = env.GENERAL_AI_REPORT_LLM_MODEL || "qwen3.7-plus";
if (!apiKey || !baseUrl) throw new Error("GENERAL_AI_REPORT_LLM_API_KEY and GENERAL_AI_REPORT_LLM_BASE_URL are required");
const endpoint = /\/chat\/completions$/i.test(baseUrl) ? baseUrl : `${baseUrl}/chat/completions`;

function parseJsonContent(content) {
  const value = Array.isArray(content) ? content.map((item) => item.text ?? "").join("") : String(content ?? "");
  const fenced = value.match(/```(?:json)?\s*([\s\S]*?)```/i)?.[1];
  const candidate = fenced ?? value.slice(value.indexOf("{"), value.lastIndexOf("}") + 1);
  return JSON.parse(candidate);
}

async function callLlm(messages, maxTokens = 10000) {
  const response = await fetchJson(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({ model, messages, temperature: 0.1, max_tokens: maxTokens, response_format: { type: "json_object" } }),
    signal: AbortSignal.timeout(Number(env.GENERAL_AI_REPORT_LLM_TIMEOUT || 240) * 1000),
  }, 3);
  return parseJsonContent(response.choices?.[0]?.message?.content);
}

function inputFor(entity) {
  const results = search.entities[entity.id]?.results ?? [];
  const baselineOnly = results.every((result) => result.discovery_method?.startsWith("Registry baseline"));
  return {
    entity_id: entity.id,
    name: entity.name,
    entity_type: entity.entity_type,
    description: entity.description,
    deterministic_evidence_score: baselineOnly ? 10 : evidenceScore(entity, results),
    evidence_status: baselineOnly ? "registry_baseline_only" : "current_official_search_evidence",
    sources: results.slice(0, 5).map((source) => ({
      title: source.title,
      url: source.url,
      excerpt: String(source.content ?? "").slice(0, 900),
      date: source.published_date ?? null,
      discovery_method: source.discovery_method,
    })),
  };
}

function fallback(entity) {
  const input = inputFor(entity);
  const source = input.sources[0];
  return {
    entity_id: entity.id,
    trend_hypothesis: input.evidence_status === "registry_baseline_only"
      ? `${entity.name} 暂无足够近期官方材料支持可量化的模型路线判断`
      : `${entity.name} 未来 6–18 个月更可能沿“${source.title}”所体现的具体研究方向继续产出`,
    evidence_chain: source ? [`官方线索：${source.title}`, `登记研究重点：${entity.description}`] : [`登记研究重点：${entity.description}`],
    why_now: "自动降级结论；需要人工阅读全文后复核。",
    horizon_months_low: 6,
    horizon_months_high: 18,
    probability_low_pct: input.evidence_status === "registry_baseline_only" ? 15 : 35,
    probability_high_pct: input.evidence_status === "registry_baseline_only" ? 40 : 60,
    maturity_stage_1_5: 1,
    leading_indicator: "未来官方论文、代码仓库或评测页面是否出现同方向连续更新",
    indicator_threshold: "12 个月内至少 2 个独立官方更新",
    expected_change_metric: null,
    expected_change_low_pct: null,
    expected_change_high_pct: null,
    counter_signals: ["缺少近期完整正文证据"],
    falsification_criteria: "12 个月内未出现同方向的第二个官方信号，或研究重心公开转向其他主题。",
    confidence_rationale: "证据仅来自搜索摘录或注册表，结论保持宽区间和低置信度。",
    evidence_level: input.evidence_status === "registry_baseline_only" ? "Insufficient" : "Speculative",
    evidence_urls: source ? [source.url] : [],
    analysis_method: "deterministic_fallback",
  };
}

function normalizeOutlook(entity, raw) {
  const input = inputFor(entity);
  const allowedUrls = new Set(input.sources.map((source) => source.url));
  const score = input.deterministic_evidence_score;
  let low = clamp(Number(raw.probability_low_pct ?? 20), 0, 100);
  let high = clamp(Number(raw.probability_high_pct ?? 55), 0, 100);
  if (low > high) [low, high] = [high, low];
  if (high - low < 10) high = clamp(low + 10, 0, 100);
  if (score < 35) {
    low = Math.min(low, 25);
    high = Math.min(high, 55);
  }
  const changeMetric = raw.expected_change_metric == null ? null : String(raw.expected_change_metric);
  let changeLow = Number.isFinite(Number(raw.expected_change_low_pct)) ? Number(raw.expected_change_low_pct) : null;
  let changeHigh = Number.isFinite(Number(raw.expected_change_high_pct)) ? Number(raw.expected_change_high_pct) : null;
  if (!changeMetric) [changeLow, changeHigh] = [null, null];
  if (changeLow != null && changeHigh != null && changeLow > changeHigh) [changeLow, changeHigh] = [changeHigh, changeLow];
  return {
    entity_id: entity.id,
    entity_name: entity.name,
    entity_type: entity.entity_type,
    region: entity.region,
    trend_hypothesis: String(raw.trend_hypothesis ?? fallback(entity).trend_hypothesis),
    evidence_chain: Array.isArray(raw.evidence_chain) ? raw.evidence_chain.slice(0, 4).map(String) : [],
    why_now: String(raw.why_now ?? ""),
    horizon_months_low: clamp(Number(raw.horizon_months_low ?? 6), 1, 60),
    horizon_months_high: clamp(Number(raw.horizon_months_high ?? 18), 1, 60),
    probability_low_pct: low,
    probability_high_pct: high,
    probability_midpoint_pct: Math.round((low + high) / 2),
    maturity_stage_1_5: clamp(Math.round(Number(raw.maturity_stage_1_5 ?? 2)), 1, 5),
    leading_indicator: String(raw.leading_indicator ?? ""),
    indicator_threshold: String(raw.indicator_threshold ?? ""),
    expected_change_metric: changeMetric,
    expected_change_low_pct: changeLow,
    expected_change_high_pct: changeHigh,
    counter_signals: Array.isArray(raw.counter_signals) ? raw.counter_signals.slice(0, 3).map(String) : [],
    falsification_criteria: String(raw.falsification_criteria ?? ""),
    confidence_rationale: String(raw.confidence_rationale ?? ""),
    evidence_level: ["Explicit", "Strong inference", "Speculative", "Insufficient"].includes(raw.evidence_level) ? raw.evidence_level : "Speculative",
    evidence_score_0_100: score,
    evidence_status: input.evidence_status,
    evidence_urls: [...new Set((Array.isArray(raw.evidence_urls) ? raw.evidence_urls : []).filter((url) => allowedUrls.has(url)))].slice(0, 5),
    analysis_model: model,
    analysis_method: raw.analysis_method ?? "llm_quantitative_outlook",
  };
}

const systemPrompt = `你是证据约束型 AI 技术情报分析师。只根据给定的官方搜索摘录和注册信息工作，不添加外部事实。为每个实体生成一条与其具体项目、论文、评测、代码或研究议程绑定的、可证伪且不与其他实体雷同的未来判断。\n\n量化规则：\n1. probability_low_pct/high_pct 是分析性主观区间，不是客观频率；必须解释依据。\n2. deterministic_evidence_score 原样保留，不由模型修改。\n3. 只有输入含明确数值基线时，expected_change_* 才能填写，否则必须为 null。\n4. evidence_status=registry_baseline_only 时，evidence_level 必须 Insufficient，概率上限不得超过 45。\n5. leading_indicator 必须可观察，indicator_threshold 必须含数字阈值或明确截止时间。\n6. falsification_criteria 必须说明什么结果会推翻判断。\n7. 不得把个人主页存在本身当作未来承诺。\n\n返回严格 JSON：{"entities":[{"entity_id":"...","trend_hypothesis":"...","evidence_chain":["..."],"why_now":"...","horizon_months_low":6,"horizon_months_high":18,"probability_low_pct":40,"probability_high_pct":65,"maturity_stage_1_5":2,"leading_indicator":"...","indicator_threshold":"...","expected_change_metric":null,"expected_change_low_pct":null,"expected_change_high_pct":null,"counter_signals":["..."],"falsification_criteria":"...","confidence_rationale":"...","evidence_level":"Explicit|Strong inference|Speculative|Insufficient","evidence_urls":["..."]}]}`;

const analyzedTopics = Object.values(existing.outlooks).map((item) => item.trend_hypothesis);
async function analyzeBatch(batch, batchNumber) {
  let rawEntities = [];
  try {
    const response = await callLlm([
      { role: "system", content: systemPrompt },
      { role: "user", content: JSON.stringify({ avoid_repeating_these_recent_hypotheses: analyzedTopics.slice(-20), entities: batch.map(inputFor) }) },
    ]);
    rawEntities = Array.isArray(response.entities) ? response.entities : [];
  } catch (error) {
    console.error(`LLM_BATCH_FALLBACK ${batchNumber}: ${error.message}`);
  }
  const values = [];
  for (const entity of batch) {
    const raw = rawEntities.find((item) => item.entity_id === entity.id) ?? fallback(entity);
    const normalized = normalizeOutlook(entity, raw);
    values.push([entity.id, normalized]);
  }
  return values;
}

const pending = entities.filter((entity) => !existing.outlooks[entity.id]);
const batches = [];
for (let index = 0; index < pending.length; index += 10) batches.push(pending.slice(index, index + 10));
for (let wave = 0; wave < batches.length; wave += 3) {
  const waveBatches = batches.slice(wave, wave + 3);
  const analyzed = await Promise.all(waveBatches.map((batch, offset) => analyzeBatch(batch, wave + offset + 1)));
  for (const values of analyzed) {
    for (const [id, normalized] of values) {
      existing.outlooks[id] = normalized;
      analyzedTopics.push(normalized.trend_hypothesis);
    }
  }
  existing.generated_at = new Date().toISOString();
  existing.analysis_model = model;
  await writeJson(OUTPUT_PATH, existing);
  console.log(`ANALYZE_PROGRESS ${Object.keys(existing.outlooks).length}/${entities.length}`);
}

function markSimilarity() {
  const values = Object.values(existing.outlooks);
  for (const outlook of values) {
    let max = 0;
    let nearest = "";
    for (const other of values) {
      if (other.entity_id === outlook.entity_id) continue;
      const score = jaccard(outlook.trend_hypothesis, other.trend_hypothesis);
      if (score > max) [max, nearest] = [score, other.entity_id];
    }
    outlook.max_similarity = Number(max.toFixed(3));
    outlook.nearest_entity_id = nearest;
    outlook.duplicate_review = max >= 0.62;
  }
  return values.filter((item) => item.duplicate_review);
}

let duplicates = markSimilarity();
for (let start = 0; start < duplicates.length; start += 6) {
  const batch = duplicates.slice(start, start + 6);
  try {
    const response = await callLlm([
      { role: "system", content: "你是技术情报去重编辑。根据每个实体自己的证据，将重复的趋势判断改写为由独有项目/方法/研究资产锚定的可证伪判断。不得增加输入之外的事实。返回 JSON：{\"entities\":[{\"entity_id\":\"...\",\"trend_hypothesis\":\"...\",\"why_now\":\"...\",\"leading_indicator\":\"...\",\"indicator_threshold\":\"...\",\"falsification_criteria\":\"...\"}]}" },
      { role: "user", content: JSON.stringify({ avoid_hypotheses: Object.values(existing.outlooks).map((item) => item.trend_hypothesis), entities: batch.map((item) => ({ ...inputFor(entities.find((entity) => entity.id === item.entity_id)), current: item })) }) },
    ], 4500);
    for (const replacement of response.entities ?? []) {
      const target = existing.outlooks[replacement.entity_id];
      if (!target) continue;
      for (const key of ["trend_hypothesis", "why_now", "leading_indicator", "indicator_threshold", "falsification_criteria"]) {
        if (replacement[key]) target[key] = String(replacement[key]);
      }
      target.dedup_rewritten = true;
    }
  } catch (error) {
    console.error(`DEDUP_REWRITE_SKIPPED ${error.message}`);
  }
}

duplicates = markSimilarity();
for (const outlook of Object.values(existing.outlooks)) {
  const entity = entities.find((item) => item.id === outlook.entity_id);
  const input = inputFor(entity);
  outlook.as_of_date = "2026-09-22";
  outlook.evidence_score_0_100 = input.deterministic_evidence_score;
  outlook.indicator_threshold_original = outlook.indicator_threshold_original ?? outlook.indicator_threshold;
  let cleanedThreshold = String(outlook.indicator_threshold_original ?? "")
    .replace(/(?:在|截至)?\s*202[0-6]\s*年?\s*(?:(?:Q[1-4])|(?:第[一二三四]季度)|(?:上半年|下半年)|(?:\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?))(?:\s*(?:前|之前|底前|以内|内))?/gi, "预测窗口内")
    .replace(/^预测窗口内\s*[，,:：]?\s*/, "");
  if (/202[0-6]/.test(cleanedThreshold)) cleanedThreshold = "公开至少1篇同方向论文、技术报告或代码更新";
  outlook.indicator_threshold = `自2026-09-22起${outlook.horizon_months_high}个月内：${cleanedThreshold || "出现至少一个可公开核验的官方进展信号"}`;
  outlook.forecast_status = outlook.evidence_status === "registry_baseline_only" ? "insufficient_evidence" : "evidence_backed_outlook";
  if (outlook.evidence_status === "registry_baseline_only") {
    outlook.evidence_level = "Insufficient";
    outlook.probability_low_pct = Math.min(outlook.probability_low_pct, 25);
    outlook.probability_high_pct = Math.min(outlook.probability_high_pct, 45);
    outlook.probability_midpoint_pct = Math.round((outlook.probability_low_pct + outlook.probability_high_pct) / 2);
  } else if (outlook.evidence_score_0_100 < 50) {
    outlook.probability_high_pct = Math.min(outlook.probability_high_pct, 60);
    outlook.probability_midpoint_pct = Math.round((outlook.probability_low_pct + outlook.probability_high_pct) / 2);
  }
  if (!outlook.evidence_urls.length && input.sources[0]?.url) outlook.evidence_urls = [input.sources[0].url];
}
existing.metrics = {
  entities: entities.length,
  analyzed: Object.keys(existing.outlooks).length,
  current_evidence_entities: Object.values(existing.outlooks).filter((item) => item.evidence_status === "current_official_search_evidence").length,
  insufficient_evidence_entities: Object.values(existing.outlooks).filter((item) => item.evidence_status === "registry_baseline_only").length,
  duplicate_review_count: duplicates.length,
  max_pairwise_similarity: Math.max(...Object.values(existing.outlooks).map((item) => item.max_similarity)),
};
existing.generated_at = new Date().toISOString();
await writeJson(OUTPUT_PATH, existing);
console.log(JSON.stringify({ output: OUTPUT_PATH, model, ...existing.metrics }, null, 2));
