import path from "node:path";
import { DATASET_PATH, ROOT, fetchJson, isOfficialUrl, loadEnv, normalizeUrl, readJson, toEntities, unique, writeJson } from "./lib.mjs";

const OUTPUT = path.join(ROOT, "data", "academic_web_search_20260922.json");
const SEED = path.join(ROOT, "data", "chatgpt_web_seed_20260922.json");
const env = await loadEnv();
const entities = toEntities(await readJson(DATASET_PATH));
const seed = await readJson(SEED);
const existing = await readJson(OUTPUT).catch(() => ({ generated_at: null, entities: {} }));
const limit = Number(process.env.MAX_ENTITIES || entities.length);
const targetEntities = entities.slice(0, limit);

if (!env.TAVILY_API_KEY && !env.SERPER_API_KEY) {
  throw new Error("TAVILY_API_KEY or SERPER_API_KEY is required in .env.txt");
}

const techPattern = /foundation model|language model|large model|LLM|agent|reasoning|multimodal|benchmark|evaluation|safety|alignment|robot|world model|大模型|语言模型|智能体|推理|多模态|评测|对齐|具身|世界模型/i;

function buildQuery(entity) {
  const siteTerms = [entity.homepage, entity.github]
    .filter(Boolean)
    .map((url) => {
      try {
        const parsed = new URL(url);
        const prefix = parsed.hostname === "github.com" ? `${parsed.hostname}${parsed.pathname.replace(/\/$/, "")}` : parsed.hostname;
        return `site:${prefix}`;
      } catch {
        return "";
      }
    })
    .filter(Boolean);
  const sites = siteTerms.length ? `(${siteTerms.join(" OR ")})` : "";
  return `"${entity.name}" ${sites} ("foundation model" OR "large language model" OR agent OR reasoning OR multimodal OR benchmark OR "AI safety" OR 大模型 OR 智能体 OR 多模态 OR 评测) (2025 OR 2026)`;
}

async function tavilySearch(entity, query) {
  if (!env.TAVILY_API_KEY) return [];
  const response = await fetchJson("https://api.tavily.com/search", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      api_key: env.TAVILY_API_KEY,
      query,
      topic: "general",
      search_depth: "basic",
      max_results: 6,
      include_answer: false,
      include_raw_content: false,
      include_domains: entity.official_domains,
    }),
  }, 2);
  return (response.results ?? []).map((result) => ({
    title: String(result.title ?? ""),
    url: String(result.url ?? ""),
    content: String(result.content ?? ""),
    score: Number(result.score ?? 0),
    published_date: result.published_date ?? null,
    discovery_method: "Tavily official-domain search",
  }));
}

async function serperSearch(entity, query) {
  if (!env.SERPER_API_KEY) return [];
  const response = await fetchJson("https://google.serper.dev/search", {
    method: "POST",
    headers: { "content-type": "application/json", "X-API-KEY": env.SERPER_API_KEY },
    body: JSON.stringify({ q: query, num: 10 }),
  }, 2);
  return [...(response.organic ?? []), ...(response.news ?? [])].map((result) => ({
    title: String(result.title ?? ""),
    url: String(result.link ?? ""),
    content: String(result.snippet ?? ""),
    score: 0.5,
    published_date: result.date ?? null,
    discovery_method: "Serper fallback official-domain search",
  }));
}

async function searchEntity(entity) {
  const query = buildQuery(entity);
  let results = [];
  let errors = [];
  try {
    results = await tavilySearch(entity, query);
  } catch (error) {
    errors.push(`Tavily: ${error.message}`);
  }
  const hasOfficialTechnicalResult = () => results.some((result) => isOfficialUrl(result.url, entity) && techPattern.test(`${result.title} ${result.content}`));
  if (!hasOfficialTechnicalResult()) {
    try {
      results = [...results, ...await serperSearch(entity, query)];
    } catch (error) {
      errors.push(`Serper: ${error.message}`);
    }
  }
  const seeded = seed.filter((item) => item.entity_id === entity.id);
  const normalized = [...seeded, ...results]
    .filter((result) => result.url && isOfficialUrl(result.url, entity))
    .filter((result) => seeded.includes(result) || techPattern.test(`${result.title} ${result.content}`))
    .map((result) => ({ ...result, url: normalizeUrl(result.url) }));
  const deduped = [];
  const seen = new Set();
  for (const result of normalized.sort((a, b) => Number(b.score ?? 1) - Number(a.score ?? 1))) {
    const key = result.url.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      deduped.push(result);
    }
  }
  if (!deduped.length) {
    deduped.push({
      title: `${entity.name} official source`,
      url: normalizeUrl(entity.homepage),
      content: entity.description,
      score: 0,
      published_date: null,
      discovery_method: "Registry baseline; no current technical result found",
    });
  }
  return { query, results: deduped.slice(0, 5), errors };
}

let completed = 0;
for (let start = 0; start < targetEntities.length; start += 4) {
  const batch = targetEntities.slice(start, start + 4);
  const values = await Promise.all(batch.map(async (entity) => {
    const cached = existing.entities[entity.id];
    const onlyBaseline = cached?.results?.length && cached.results.every((result) => result.discovery_method?.startsWith("Registry baseline"));
    if (cached?.results?.length && !onlyBaseline) return [entity.id, cached];
    return [entity.id, await searchEntity(entity)];
  }));
  for (const [id, value] of values) existing.entities[id] = value;
  completed += batch.length;
  existing.generated_at = new Date().toISOString();
  existing.coverage = {
    requested_entities: targetEntities.length,
    completed_entities: Object.keys(existing.entities).filter((id) => targetEntities.some((entity) => entity.id === id)).length,
    discovery_methods: unique(Object.values(existing.entities).flatMap((item) => item.results ?? []).map((item) => item.discovery_method)),
  };
  await writeJson(OUTPUT, existing);
  console.log(`COLLECT_PROGRESS ${Math.min(completed, targetEntities.length)}/${targetEntities.length}`);
}

console.log(JSON.stringify({ output: OUTPUT, ...existing.coverage }, null, 2));
