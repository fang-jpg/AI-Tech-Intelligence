from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from html import unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from dateutil import parser as date_parser


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
    "ref",
    "source",
}


def canonicalize_url(url: str, base_url: str | None = None) -> str:
    absolute = urljoin(base_url or "", url.strip())
    parts = urlsplit(absolute)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    host = (parts.hostname or "").lower()
    if parts.port and parts.port not in {80, 443}:
        host = f"{host}:{parts.port}"
    clean_path = re.sub(r"/{2,}", "/", parts.path or "/")
    if clean_path != "/":
        clean_path = clean_path.rstrip("/")
    query = urlencode(
        sorted((key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in TRACKING_PARAMS)
    )
    return urlunsplit((parts.scheme.lower(), host, clean_path, query, ""))


def url_domain(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def domain_matches(url: str, allowed_domains: list[str]) -> bool:
    host = url_domain(url)
    return any(host == domain.removeprefix("www.") or host.endswith("." + domain.removeprefix("www.")) for domain in allowed_domains)


def normalize_text(text: str) -> str:
    text = unescape(text or "").replace("\u00a0", " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalized_for_match(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").casefold())


def sha256_text(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = date_parser.parse(value, fuzzy=True)
    except (ValueError, TypeError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.date().isoformat()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_json_object(text: str) -> dict:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(stripped[start : end + 1])
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def compact_excerpt(text: str, max_chars: int = 240) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "…"

