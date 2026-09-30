from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import Company, Person, Source, SourceTier


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env_file(path: Path, override: bool = False) -> dict[str, str]:
    """Load KEY=VALUE pairs without logging values or requiring python-dotenv."""
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not (key[0].isalpha() or key[0] == "_"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        loaded[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return loaded


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"配置文件顶层必须是映射: {path}")
    return data


@dataclass(slots=True)
class Registry:
    companies: dict[str, Company]
    people: list[Person]
    sources: list[Source]
    defaults: dict[str, Any]
    youtube: dict[str, Any]

    def selected_companies(self, values: list[str] | None) -> list[str]:
        if not values:
            return list(self.companies)
        unknown = sorted(set(values) - set(self.companies))
        if unknown:
            raise ValueError(f"未知厂商 ID: {', '.join(unknown)}")
        return values

    def people_for(self, company: str) -> list[Person]:
        return [person for person in self.people if person.company == company]

    def sources_for(self, company: str) -> list[Source]:
        return [source for source in self.sources if source.company == company]


def load_registry(config_dir: Path | None = None) -> Registry:
    config_dir = (config_dir or PROJECT_ROOT / "config").resolve()
    company_data = _read_yaml(config_dir / "companies.yaml")
    people_data = _read_yaml(config_dir / "people.yaml")
    source_data = _read_yaml(config_dir / "sources.yaml")

    companies: dict[str, Company] = {}
    for company_id, raw in company_data.get("companies", {}).items():
        companies[company_id] = Company(
            id=company_id,
            name=str(raw["name"]),
            country=str(raw.get("country", "")),
            aliases=[str(item) for item in raw.get("aliases", [])],
            official_domains=[str(item).lower() for item in raw.get("official_domains", [])],
            query_topics=[str(item) for item in raw.get("query_topics", [])],
            entity_type=str(raw.get("entity_type", "vendor")),
        )

    people: list[Person] = []
    for raw in people_data.get("people", []):
        company = str(raw["company"])
        if company not in companies:
            raise ValueError(f"people.yaml 引用了未知厂商: {company}")
        people.append(
            Person(
                company=company,
                name=str(raw["name"]),
                role=str(raw["role"]),
                aliases=[str(item) for item in raw.get("aliases", [raw["name"]])],
                profile_url=str(raw.get("profile_url", "")),
            )
        )

    sources: list[Source] = []
    seen_ids: set[str] = set()
    for company, company_sources in source_data.get("sources", {}).items():
        if company not in companies:
            raise ValueError(f"sources.yaml 引用了未知厂商: {company}")
        for raw in company_sources:
            source_id = str(raw["id"])
            if source_id in seen_ids:
                raise ValueError(f"source id 重复: {source_id}")
            seen_ids.add(source_id)
            sources.append(
                Source(
                    id=source_id,
                    company=company,
                    name=str(raw["name"]),
                    type=str(raw["type"]),
                    tier=SourceTier(str(raw.get("tier", "A"))),
                    url=str(raw["url"]),
                    include_patterns=[str(item) for item in raw.get("include_patterns", [])],
                    official=bool(raw.get("official", True)),
                    single_page=bool(raw.get("single_page", False)),
                )
            )

    return Registry(
        companies=companies,
        people=people,
        sources=sources,
        defaults=dict(source_data.get("defaults", {})),
        youtube=dict(source_data.get("youtube", {})),
    )
