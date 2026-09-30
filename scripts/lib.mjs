import fs from "node:fs/promises";
import path from "node:path";

export const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(?:([A-Za-z]:))/, "$1")), "..");
export const DATASET_PATH = path.join(ROOT, ".artifact-runtime", "academic_source_rows.json");

export async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

export async function writeJson(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

export async function loadEnv(filePath = path.join(ROOT, ".env.txt")) {
  const text = await fs.readFile(filePath, "utf8");
  const values = {};
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const index = line.indexOf("=");
    if (index < 1) continue;
    const key = line.slice(0, index).trim();
    let value = line.slice(index + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    values[key] = value;
  }
  return values;
}

export function toEntities(rows) {
  return rows.slice(1).map((row, index) => {
    const [name, regionType, homepage, github, description] = row.map((value) => String(value ?? "").trim());
    const isPerson = regionType.includes("个人");
    const region = regionType.includes("国内") ? "国内" : "国外";
    return {
      id: `academic_${String(index + 1).padStart(3, "0")}`,
      name,
      region,
      entity_type: isPerson ? "researcher" : "institution",
      homepage,
      github: ["—", "-", ""].includes(github) ? "" : github,
      description,
      official_domains: unique([hostname(homepage), hostname(github)].filter(Boolean)),
      query_topics: ["foundation model", "large language model", "agent", "reasoning", "multimodal", "AI safety", "evaluation", "open source"],
    };
  });
}

export function hostname(url) {
  try {
    return new URL(url).hostname.toLowerCase().replace(/^www\./, "");
  } catch {
    return "";
  }
}

export function normalizeUrl(value) {
  try {
    const url = new URL(value);
    url.hash = "";
    for (const key of [...url.searchParams.keys()]) {
      if (/^(utm_|gclid|fbclid|ref$)/i.test(key)) url.searchParams.delete(key);
    }
    return url.toString().replace(/\/$/, "");
  } catch {
    return String(value ?? "").trim();
  }
}

export function isOfficialUrl(url, entity) {
  const candidate = hostname(url);
  if (!candidate) return false;
  if (entity.official_domains.some((domain) => candidate === domain || candidate.endsWith(`.${domain}`))) {
    if (candidate === "github.com" && entity.github) {
      return normalizeUrl(url).toLowerCase().startsWith(normalizeUrl(entity.github).toLowerCase());
    }
    if (candidate === "x.com" && entity.homepage) {
      return normalizeUrl(url).toLowerCase().startsWith(normalizeUrl(entity.homepage).toLowerCase());
    }
    return true;
  }
  return false;
}

export function unique(values) {
  return [...new Set(values)];
}

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function fetchJson(url, options, attempts = 3) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, options);
      const body = await response.text();
      if (!response.ok) throw new Error(`${response.status} ${body.slice(0, 500)}`);
      return JSON.parse(body);
    } catch (error) {
      lastError = error;
      if (attempt < attempts) await sleep(600 * 2 ** (attempt - 1));
    }
  }
  throw lastError;
}

export function extractYear(text) {
  const years = [...String(text ?? "").matchAll(/\b(20(?:2[4-9]|3\d))\b/g)].map((match) => Number(match[1]));
  return years.length ? Math.max(...years) : null;
}

export function evidenceScore(entity, sources) {
  if (!sources.length) return 10;
  const currentYear = 2026;
  let score = 22;
  score += Math.min(30, sources.length * 10);
  score += Math.min(20, sources.filter((source) => isOfficialUrl(source.url, entity)).length * 7);
  const recent = sources.filter((source) => {
    const year = extractYear(`${source.title} ${source.content}`);
    return year && year >= currentYear - 1;
  }).length;
  score += Math.min(18, recent * 7);
  if (sources.some((source) => /paper|research|model|benchmark|agent|reason|multimodal|大模型|模型|智能体|评测/i.test(`${source.title} ${source.content}`))) score += 10;
  return clamp(score, 0, 90);
}

export function jaccard(a, b) {
  const tokenize = (text) => {
    const value = String(text).toLowerCase();
    const tokens = value.match(/[a-z0-9]+/g) ?? [];
    const chinese = (value.match(/[\u4e00-\u9fff]/g) ?? []).join("");
    for (let index = 0; index < chinese.length - 1; index += 1) tokens.push(chinese.slice(index, index + 2));
    return new Set(tokens);
  };
  const aa = tokenize(a);
  const bb = tokenize(b);
  const intersection = [...aa].filter((token) => bb.has(token)).length;
  const union = new Set([...aa, ...bb]).size;
  return union ? intersection / union : 0;
}
