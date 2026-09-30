import fs from "node:fs/promises";
import path from "node:path";
import { DATASET_PATH, ROOT, readJson, toEntities } from "./lib.mjs";

const rows = await readJson(DATASET_PATH);
const entities = toEntities(rows);
const quote = (value) => JSON.stringify(String(value), null, 0);

const companies = ["companies:"];
for (const entity of entities) {
  companies.push(
    `  ${entity.id}:`,
    `    name: ${quote(entity.name)}`,
    `    country: ${quote(entity.region === "国内" ? "CN" : "International")}`,
    `    entity_type: ${quote(entity.entity_type)}`,
    `    aliases: [${quote(entity.name)}]`,
    `    official_domains: [${entity.official_domains.map(quote).join(", ")}]`,
    `    query_topics: [${entity.query_topics.map(quote).join(", ")}]`,
    `    description: ${quote(entity.description)}`,
    "",
  );
}

const people = ["people:"];
for (const entity of entities.filter((item) => item.entity_type === "researcher")) {
  people.push(
    `  - company: ${entity.id}`,
    `    name: ${quote(entity.name)}`,
    `    role: ${quote("Researcher / technical public voice")}`,
    `    aliases: [${quote(entity.name)}]`,
    `    profile_url: ${quote(entity.homepage)}`,
    "",
  );
}

const sources = ["sources:"];
for (const entity of entities) {
  sources.push(
    `  ${entity.id}:`,
    `    - id: ${entity.id}_official`,
    `      name: ${quote(`${entity.name} Official ${entity.entity_type === "researcher" ? "Profile" : "Research"}`)}`,
    `      type: ${entity.entity_type === "researcher" ? "official_personal" : "official_research"}`,
    `      tier: ${entity.entity_type === "researcher" ? "B" : "A"}`,
    `      url: ${quote(entity.homepage)}`,
    "      official: true",
    "      single_page: true",
  );
  if (entity.github) {
    sources.push(
      `    - id: ${entity.id}_github`,
      `      name: ${quote(`${entity.name} Official GitHub`)}`,
      "      type: official_code",
      "      tier: B",
      `      url: ${quote(entity.github)}`,
      "      official: true",
      "      single_page: true",
    );
  }
  sources.push("");
}

await fs.mkdir(path.join(ROOT, "config"), { recursive: true });
await Promise.all([
  fs.writeFile(path.join(ROOT, "config", "companies.yaml"), `${companies.join("\n")}\n`, "utf8"),
  fs.writeFile(path.join(ROOT, "config", "people.yaml"), `${people.join("\n")}\n`, "utf8"),
  fs.writeFile(path.join(ROOT, "config", "sources.yaml"), `${sources.join("\n")}\n`, "utf8"),
]);

console.log(JSON.stringify({ entities: entities.length, institutions: entities.filter((x) => x.entity_type === "institution").length, researchers: entities.filter((x) => x.entity_type === "researcher").length }, null, 2));
