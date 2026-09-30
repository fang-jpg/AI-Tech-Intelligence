from __future__ import annotations

import io
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from ..models import Candidate, Source
from ..utils import canonicalize_url, compact_excerpt, normalize_text, parse_date
from .base import SourceAdapter


DEFAULT_USER_AGENT = "AI-Tech-Intelligence/0.1 (+local research pipeline)"


class WebFetcher:
    def __init__(self, timeout: float | None = None, delay_seconds: float | None = None):
        self.timeout = timeout or float(os.getenv("ATI_REQUEST_TIMEOUT", "30"))
        self.delay_seconds = delay_seconds if delay_seconds is not None else float(os.getenv("ATI_REQUEST_DELAY_SECONDS", "0.8"))
        self.client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": os.getenv("ATI_USER_AGENT", DEFAULT_USER_AGENT),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.5",
            },
        )
        self._last_request_at = 0.0

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "WebFetcher":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(self, url: str) -> httpx.Response:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        response = self.client.get(url)
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response

    def extract(self, url: str) -> dict[str, Any]:
        response = self.get(url)
        final_url = str(response.url)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type == "application/pdf" or final_url.lower().endswith(".pdf"):
            reader = PdfReader(io.BytesIO(response.content))
            page_texts = [(page.extract_text() or "") for page in reader.pages]
            text = normalize_text("\n\n".join(page_texts))
            title = ""
            if reader.metadata:
                title = str(reader.metadata.title or "")
            return {
                "url": final_url,
                "title": normalize_text(title) or final_url.rsplit("/", 1)[-1],
                "published_at": None,
                "text": text,
                "content_type": content_type or "application/pdf",
                "metadata": {"page_count": len(reader.pages)},
            }
        return self._extract_html(final_url, response.text, content_type)

    @staticmethod
    def _extract_html(url: str, html: str, content_type: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        json_ld_dates: list[str] = []
        for node in soup.select('script[type="application/ld+json"]'):
            try:
                value = json.loads(node.string or node.get_text() or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            queue = value if isinstance(value, list) else [value]
            for item in queue:
                if isinstance(item, dict) and item.get("datePublished"):
                    json_ld_dates.append(str(item["datePublished"]))
        for element in soup.select("script,style,noscript,svg,nav,footer,form,aside"):
            element.decompose()
        title = ""
        for selector, attribute in (
            ('meta[property="og:title"]', "content"),
            ('meta[name="twitter:title"]', "content"),
        ):
            node = soup.select_one(selector)
            if node and node.get(attribute):
                title = str(node.get(attribute))
                break
        if not title:
            h1 = soup.find("h1")
            title = h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(" ", strip=True) if soup.title else "")

        published_at = None
        date_selectors = (
            ('meta[property="article:published_time"]', "content"),
            ('meta[name="date"]', "content"),
            ('meta[name="publishdate"]', "content"),
            ('meta[itemprop="datePublished"]', "content"),
            ("time[datetime]", "datetime"),
        )
        for selector, attribute in date_selectors:
            node = soup.select_one(selector)
            if node and node.get(attribute):
                published_at = parse_date(str(node.get(attribute)))
                if published_at:
                    break
        if not published_at:
            published_at = next((parsed for value in json_ld_dates if (parsed := parse_date(value))), None)
        if not published_at:
            raw_match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html, flags=re.I)
            if raw_match:
                published_at = parse_date(raw_match.group(1))

        container = soup.find("article") or soup.find("main") or soup.body or soup
        blocks: list[str] = []
        for node in container.find_all(["h1", "h2", "h3", "p", "li", "blockquote"], recursive=True):
            value = normalize_text(node.get_text(" ", strip=True))
            if len(value) >= 2 and (not blocks or value != blocks[-1]):
                blocks.append(value)
        text = normalize_text("\n".join(blocks))
        if len(text) < 120:
            text = normalize_text(container.get_text("\n", strip=True))
        description = ""
        description_node = soup.select_one('meta[name="description"],meta[property="og:description"]')
        if description_node and description_node.get("content"):
            description = normalize_text(str(description_node.get("content")))
        return {
            "url": url,
            "title": normalize_text(title),
            "published_at": published_at,
            "text": text,
            "content_type": content_type or "text/html",
            "metadata": {"description": description},
        }


class OfficialWebCollector(SourceAdapter):
    def __init__(self, fetcher: WebFetcher):
        self.fetcher = fetcher

    def discover(self, source: Source, limit: int = 25) -> list[Candidate]:
        if source.single_page:
            return [
                Candidate(
                    company=source.company,
                    source_id=source.id,
                    source_name=source.name,
                    source_type=source.type,
                    url=source.url,
                    tier_hint=source.tier,
                    official_hint=source.official,
                    metadata={"discovered_from": source.url, "single_page": True},
                )
            ]
        try:
            response = self.fetcher.get(source.url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {401, 403, 429}:
                raise
            parts = urlsplit(source.url)
            sitemap_url = f"{parts.scheme}://{parts.netloc}/sitemap.xml"
            response = self.fetcher.get(sitemap_url)
        content_type = response.headers.get("content-type", "").lower()
        text = response.text
        if "xml" in content_type or text.lstrip().startswith("<?xml") or "<rss" in text[:500].lower():
            links = list(self._links_from_xml(text, str(response.url)))
        else:
            links = list(self._links_from_html(text, str(response.url)))
        links.sort(key=lambda item: item[2] or "0000-00-00", reverse=True)
        unique: dict[str, tuple[str, str | None]] = {}
        for url, title, published_at in links:
            canonical = canonicalize_url(url, str(response.url))
            if not canonical or canonical == canonicalize_url(source.url):
                continue
            if source.include_patterns and not any(pattern in canonical for pattern in source.include_patterns):
                continue
            unique.setdefault(canonical, (title, published_at))
            if len(unique) >= limit:
                break
        if source.type == "official_event" and canonicalize_url(source.url) not in unique:
            unique[canonicalize_url(source.url)] = (source.name, None)
        return [
            Candidate(
                company=source.company,
                source_id=source.id,
                source_name=source.name,
                source_type=source.type,
                url=url,
                title=title,
                published_at=published_at,
                tier_hint=source.tier,
                official_hint=source.official,
                metadata={"discovered_from": source.url},
            )
            for url, (title, published_at) in unique.items()
        ]

    @staticmethod
    def _links_from_html(html: str, base_url: str) -> Iterable[tuple[str, str, str | None]]:
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", "")).strip()
            if not href or href.startswith(("#", "mailto:", "javascript:")):
                continue
            title = normalize_text(anchor.get_text(" ", strip=True))
            parent = anchor.find_parent(["article", "li", "div"])
            date_value = None
            if parent:
                time_node = parent.find("time")
                if time_node:
                    date_value = parse_date(str(time_node.get("datetime") or time_node.get_text(" ", strip=True)))
            yield canonicalize_url(href, base_url), title, date_value

    @staticmethod
    def _links_from_xml(xml_text: str, base_url: str) -> Iterable[tuple[str, str, str | None]]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return
        for item in root.iter():
            local_name = item.tag.rsplit("}", 1)[-1].lower()
            if local_name not in {"item", "entry", "url"}:
                continue
            values: dict[str, str] = {}
            for child in item.iter():
                child_name = child.tag.rsplit("}", 1)[-1].lower()
                if child.text and child_name in {"loc", "link", "title", "pubdate", "published", "updated", "lastmod"}:
                    values[child_name] = child.text.strip()
                if child_name == "link" and child.attrib.get("href"):
                    values["link"] = child.attrib["href"]
            url = values.get("loc") or values.get("link")
            if url:
                date_value = values.get("pubdate") or values.get("published") or values.get("updated") or values.get("lastmod")
                yield canonicalize_url(url, base_url), values.get("title", ""), parse_date(date_value)
