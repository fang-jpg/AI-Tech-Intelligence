from __future__ import annotations

from datetime import datetime, timezone

from ..config import Registry


def build_search_queries(registry: Registry, company_id: str, max_queries: int = 4) -> list[str]:
    company = registry.companies[company_id]
    people = registry.people_for(company_id)
    topic = " OR ".join(f'"{value}"' for value in company.query_topics[:4])
    aliases = " OR ".join(f'"{value}"' for value in company.aliases[:3])
    current_year = datetime.now(timezone.utc).year
    queries: list[str] = []
    if company.official_domains:
        queries.append(f"site:{company.official_domains[0]} ({aliases}) ({topic}) {current_year}")
    for person in people[: max(1, max_queries - 1)]:
        queries.append(f'"{person.name}" ({topic}) (interview OR keynote OR blog OR 演讲 OR 采访) {current_year}')
    return queries[:max_queries]
