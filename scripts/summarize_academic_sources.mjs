import path from "node:path";
import { DATASET_PATH, ROOT, fetchJson, jaccard, loadEnv, readJson, toEntities, writeJson } from "./lib.mjs";

const SEARCH_PATH = path.join(ROOT, "data", "academic_web_search_20260922.json");
const OUTPUT_PATH = path.join(ROOT, "data", "academic_source_summaries_20260923.json");
const env = await loadEnv();
const entities = toEntities(await readJson(DATASET_PATH));
const search = await readJson(SEARCH_PATH);
const existing = await readJson(OUTPUT_PATH).catch(() => ({ generated_at: null, analysis_model: null, summaries: {} }));
const apiKey = env.GENERAL_AI_REPORT_LLM_API_KEY;
const baseUrl = String(env.GENERAL_AI_REPORT_LLM_BASE_URL ?? "").replace(/\/$/, "");
const model = env.GENERAL_AI_REPORT_LLM_MODEL || "qwen3.7-plus";
if (!apiKey || !baseUrl) throw new Error("GENERAL_AI_REPORT_LLM_API_KEY and GENERAL_AI_REPORT_LLM_BASE_URL are required");
const endpoint = /\/chat\/completions$/i.test(baseUrl) ? baseUrl : `${baseUrl}/chat/completions`;

const sources = [];
for (const entity of entities) {
  const results = search.entities[entity.id]?.results ?? [];
  results.forEach((source, index) => sources.push({
    source_id: `${entity.id}_source_${String(index + 1).padStart(2, "0")}`,
    entity_id: entity.id,
    entity_name: entity.name,
    entity_type: entity.entity_type,
    entity_description: entity.description,
    title: source.title,
    url: source.url,
    excerpt: String(source.content ?? "").slice(0, 1000),
    date: source.published_date ?? null,
    discovery_method: source.discovery_method,
    content_basis: source.discovery_method?.startsWith("Registry baseline") ? "registry_baseline" : "official_search_excerpt",
  }));
}

function parseJsonContent(content) {
  const value = Array.isArray(content) ? content.map((item) => item.text ?? "").join("") : String(content ?? "");
  const fenced = value.match(/```(?:json)?\s*([\s\S]*?)```/i)?.[1];
  const candidate = fenced ?? value.slice(value.indexOf("{"), value.lastIndexOf("}") + 1);
  return JSON.parse(candidate);
}

async function callLlm(batch) {
  const response = await fetchJson(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model,
      temperature: 0.1,
      max_tokens: 12000,
      response_format: { type: "json_object" },
      messages: [
        {
          role: "system",
          content: `你是证据约束型 AI 技术情报编辑。只根据输入中的标题、官方搜索摘录和实体说明总结每个链接，不得补充外部事实，不得把团队材料冒充个人发言。\n\n要求：\n1. 每个来源输出 1-3 条简洁核心观点，每条都必须能由该来源摘录支撑。\n2. 同一实体的不同链接要突出各自独有内容，避免使用重复的通用总结。\n3. technical_tags 输出 1-6 个具体技术标签，不使用“人工智能”“技术创新”这类空泛标签。\n4. direct_statement 只有摘录中明确出现具名人物及其话语时才为 true；否则为 false。\n5. registry_baseline 只能总结登记说明，并标记 summary_status=baseline_only。\n\n返回严格 JSON：{"sources":[{"source_id":"...","core_points":["..."],"technical_tags":["..."],"direct_statement":false,"summary_status":"excerpt_grounded|baseline_only"}]}`,
        },
        { role: "user", content: JSON.stringify({ sources: batch }) },
      ],
    }),
    signal: AbortSignal.timeout(Number(env.GENERAL_AI_REPORT_LLM_TIMEOUT || 180) * 1000),
  }, 2);
  return parseJsonContent(response.choices?.[0]?.message?.content);
}

function keywordTags(text) {
  const rules = [
    ["Agent", /agent|智能体/i], ["Reasoning", /reason|推理/i], ["Multimodal", /multimodal|多模态|vision-language/i],
    ["Evaluation", /benchmark|evaluation|评测|基准/i], ["AI Safety", /safety|alignment|安全|对齐/i], ["Robotics", /robot|具身|机器人/i],
    ["World Model", /world model|世界模型/i], ["Open Source", /open.source|开源/i], ["Infrastructure", /serving|inference|compute|system|部署|推理系统/i],
    ["Data", /dataset|data|语料|数据/i], ["Foundation Model", /foundation model|large language model|LLM|大模型/i],
  ];
  return rules.filter(([, pattern]) => pattern.test(text)).map(([tag]) => tag).slice(0, 6);
}

function fallback(source) {
  const text = source.excerpt || source.entity_description || source.title;
  const sentences = text.split(/(?<=[。！？.!?])\s*/).filter(Boolean).slice(0, 2);
  return {
    source_id: source.source_id,
    core_points: sentences.length ? sentences : [text.slice(0, 400)],
    technical_tags: keywordTags(`${source.title} ${text}`),
    direct_statement: false,
    summary_status: source.content_basis === "registry_baseline" ? "baseline_only" : "excerpt_grounded",
    analysis_method: "deterministic_fallback",
  };
}

async function summarizeBatch(batch, batchNumber) {
  let responseSources = [];
  try {
    const response = await callLlm(batch);
    responseSources = Array.isArray(response.sources) ? response.sources : [];
  } catch (error) {
    console.error(`SUMMARY_BATCH_FALLBACK ${batchNumber}: ${error.message}`);
  }
  return batch.map((source) => {
    const raw = responseSources.find((item) => item.source_id === source.source_id) ?? fallback(source);
    const points = Array.isArray(raw.core_points) ? raw.core_points.map(String).filter(Boolean).slice(0, 3) : fallback(source).core_points;
    const tags = Array.isArray(raw.technical_tags) ? [...new Set(raw.technical_tags.map(String).filter(Boolean))].slice(0, 6) : fallback(source).technical_tags;
    return [source.source_id, {
      source_id: source.source_id,
      entity_id: source.entity_id,
      core_points: points,
      technical_tags: tags,
      direct_statement: Boolean(raw.direct_statement),
      summary_status: source.content_basis === "registry_baseline" ? "baseline_only" : "excerpt_grounded",
      analysis_model: model,
      analysis_method: raw.analysis_method ?? "llm_excerpt_summary",
    }];
  });
}

const retryFallback = process.env.ACADEMIC_RETRY_FALLBACK === "1";
const pending = sources.filter((source) => !existing.summaries[source.source_id] || (retryFallback && existing.summaries[source.source_id]?.analysis_method === "deterministic_fallback"));
const batches = [];
const batchSize = retryFallback ? Number(process.env.ACADEMIC_RETRY_BATCH_SIZE || 10) : 25;
const concurrency = retryFallback ? Math.min(5, Math.max(1, Number(process.env.ACADEMIC_RETRY_CONCURRENCY || 3))) : 4;
for (let index = 0; index < pending.length; index += batchSize) batches.push(pending.slice(index, index + batchSize));
for (let wave = 0; wave < batches.length; wave += concurrency) {
  const values = await Promise.all(batches.slice(wave, wave + concurrency).map((batch, offset) => summarizeBatch(batch, wave + offset + 1)));
  for (const batchValues of values) for (const [id, summary] of batchValues) existing.summaries[id] = summary;
  existing.generated_at = new Date().toISOString();
  existing.analysis_model = model;
  await writeJson(OUTPUT_PATH, existing);
  console.log(`SUMMARY_PROGRESS ${Object.keys(existing.summaries).length}/${sources.length}`);
}

let adjusted = 0;
for (const entity of entities) {
  const entitySources = sources.filter((source) => source.entity_id === entity.id);
  for (let left = 0; left < entitySources.length; left += 1) {
    for (let right = left + 1; right < entitySources.length; right += 1) {
      const a = existing.summaries[entitySources[left].source_id];
      const b = existing.summaries[entitySources[right].source_id];
      const similarity = jaccard(a.core_points.join(" "), b.core_points.join(" "));
      if (similarity >= 0.72) {
        b.core_points[0] = `${entitySources[right].title}：${b.core_points[0]}`;
        b.dedup_adjusted = true;
        adjusted += 1;
      }
    }
  }
}

const summaryValues = Object.values(existing.summaries);
existing.metrics = {
  sources: sources.length,
  summarized: summaryValues.length,
  llm_summaries: summaryValues.filter((item) => item.analysis_method === "llm_excerpt_summary").length,
  fallback_summaries: summaryValues.filter((item) => item.analysis_method === "deterministic_fallback").length,
  baseline_only: summaryValues.filter((item) => item.summary_status === "baseline_only").length,
  direct_statements: summaryValues.filter((item) => item.direct_statement).length,
  dedup_adjusted: adjusted,
  exact_duplicate_summaries: summaryValues.length - new Set(summaryValues.map((item) => item.core_points.join("\n"))).size,
};
await writeJson(OUTPUT_PATH, existing);
console.log(JSON.stringify({ output: OUTPUT_PATH, model, ...existing.metrics }, null, 2));
