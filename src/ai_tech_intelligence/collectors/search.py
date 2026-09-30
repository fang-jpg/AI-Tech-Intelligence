from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from ..models import Candidate, SourceTier
from ..utils import canonicalize_url, parse_date
from .base import SourceAdapter


PROVIDER_ENV_KEYS = {
    "tavily": "TAVILY_API_KEY",
    "exa": "EXA_API_KEY",
    "serper": "SERPER_API_KEY",
    "bocha": "BOCHA_API_KEY",
    "bing": "BING_API_KEY",
    "serpapi": "SERPAPI_API_KEY",
}


def available_search_providers() -> list[str]:
    return [name for name, env_key in PROVIDER_ENV_KEYS.items() if os.getenv(env_key)]


@dataclass(slots=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    published_at: str | None = None


class SearchCollector(SourceAdapter):
    def __init__(self, provider: str = "auto", timeout: float = 30.0):
        available = available_search_providers()
        if provider == "auto":
            if not available:
                raise RuntimeError("未检测到搜索 API 密钥；请在 .env.txt 中配置至少一个搜索源")
            provider = available[0]
        if provider not in PROVIDER_ENV_KEYS:
            raise ValueError(f"不支持的搜索源: {provider}")
        api_key = os.getenv(PROVIDER_ENV_KEYS[provider], "")
        if not api_key:
            raise RuntimeError(f"缺少 {PROVIDER_ENV_KEYS[provider]}")
        self.provider = provider
        self.api_key = api_key
        self.client = httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "SearchCollector":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def discover(
        self,
        company: str,
        queries: list[str],
        max_results_per_query: int = 5,
    ) -> list[Candidate]:
        found: dict[str, Candidate] = {}
        for query in queries:
            for result in self._search(query, max_results_per_query):
                url = canonicalize_url(result.url)
                if not url or url in found:
                    continue
                found[url] = Candidate(
                    company=company,
                    source_id=f"search_{self.provider}",
                    source_name=f"{self.provider} discovery",
                    source_type="search_discovery",
                    url=url,
                    title=result.title,
                    published_at=result.published_at,
                    snippet=result.snippet,
                    tier_hint=SourceTier.D,
                    official_hint=False,
                    metadata={"query": query, "search_provider": self.provider},
                )
        return list(found.values())

    def _search(self, query: str, limit: int) -> list[SearchResult]:
        method = getattr(self, f"_search_{self.provider}")
        return method(query, limit)

    def _search_tavily(self, query: str, limit: int) -> list[SearchResult]:
        response = self.client.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"query": query, "max_results": limit, "search_depth": "advanced", "include_raw_content": False},
        )
        response.raise_for_status()
        return [
            SearchResult(str(item.get("url", "")), str(item.get("title", "")), str(item.get("content", "")), parse_date(item.get("published_date")))
            for item in response.json().get("results", [])
        ]

    def _search_exa(self, query: str, limit: int) -> list[SearchResult]:
        response = self.client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": self.api_key},
            json={"query": query, "numResults": limit, "type": "auto", "contents": {"highlights": {"maxCharacters": 800}}},
        )
        response.raise_for_status()
        output = []
        for item in response.json().get("results", []):
            highlights = item.get("highlights") or []
            output.append(SearchResult(str(item.get("url", "")), str(item.get("title", "")), " ".join(highlights), parse_date(item.get("publishedDate"))))
        return output

    def _search_serper(self, query: str, limit: int) -> list[SearchResult]:
        response = self.client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            json={"q": query, "num": limit},
        )
        response.raise_for_status()
        return [
            SearchResult(str(item.get("link", "")), str(item.get("title", "")), str(item.get("snippet", "")), parse_date(item.get("date")))
            for item in response.json().get("organic", [])[:limit]
        ]

    def _search_bocha(self, query: str, limit: int) -> list[SearchResult]:
        endpoint = os.getenv("BOCHA_SEARCH_ENDPOINT", "https://api.bochaai.com/v1/web-search")
        response = self.client.post(
            endpoint,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"query": query, "count": limit, "summary": True, "freshness": "noLimit"},
        )
        response.raise_for_status()
        values = response.json().get("data", {}).get("webPages", {}).get("value", [])
        return [
            SearchResult(str(item.get("url", "")), str(item.get("name", "")), str(item.get("summary") or item.get("snippet") or ""), parse_date(item.get("datePublished")))
            for item in values
        ]

    def _search_bing(self, query: str, limit: int) -> list[SearchResult]:
        endpoint = os.getenv("BING_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search")
        response = self.client.get(
            endpoint,
            headers={"Ocp-Apim-Subscription-Key": self.api_key},
            params={"q": query, "count": limit, "textDecorations": False, "textFormat": "Raw"},
        )
        response.raise_for_status()
        values = response.json().get("webPages", {}).get("value", [])
        return [SearchResult(str(item.get("url", "")), str(item.get("name", "")), str(item.get("snippet", "")), parse_date(item.get("dateLastCrawled"))) for item in values]

    def _search_serpapi(self, query: str, limit: int) -> list[SearchResult]:
        response = self.client.get(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "api_key": self.api_key, "num": limit},
        )
        response.raise_for_status()
        return [
            SearchResult(str(item.get("link", "")), str(item.get("title", "")), str(item.get("snippet", "")), parse_date(item.get("date")))
            for item in response.json().get("organic_results", [])[:limit]
        ]
