from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import Registry
from .models import Analysis, Document
from .utils import normalized_for_match


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    aliases_json TEXT NOT NULL,
    official_domains_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL REFERENCES companies(id),
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    aliases_json TEXT NOT NULL,
    profile_url TEXT NOT NULL,
    UNIQUE(company_id, name)
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    tier TEXT NOT NULL,
    url TEXT NOT NULL,
    official INTEGER NOT NULL,
    config_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL REFERENCES companies(id),
    source_id TEXT,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    tier TEXT NOT NULL,
    official INTEGER NOT NULL,
    people_json TEXT NOT NULL,
    attribution_status TEXT NOT NULL,
    verification_reason TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_company_date ON documents(company_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL UNIQUE REFERENCES documents(id) ON DELETE CASCADE,
    core_points_json TEXT NOT NULL,
    technical_signals_json TEXT NOT NULL,
    attributed_statements_json TEXT NOT NULL,
    trend_summary TEXT NOT NULL,
    trend_directions_json TEXT NOT NULL,
    evidence_level TEXT NOT NULL,
    confidence REAL NOT NULL,
    time_window TEXT NOT NULL,
    model TEXT NOT NULL,
    grounding_passed INTEGER NOT NULL,
    analysis_method TEXT NOT NULL,
    analyzed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    stats_json TEXT NOT NULL,
    error TEXT
);
"""


class IntelligenceDB:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "IntelligenceDB":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def initialize(self, registry: Registry) -> None:
        self.connection.executescript(SCHEMA)
        now = datetime.now(timezone.utc).isoformat()
        with self.connection:
            for company in registry.companies.values():
                self.connection.execute(
                    """INSERT INTO companies(id,name,country,aliases_json,official_domains_json,updated_at)
                       VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                       name=excluded.name,country=excluded.country,aliases_json=excluded.aliases_json,
                       official_domains_json=excluded.official_domains_json,updated_at=excluded.updated_at""",
                    (company.id, company.name, company.country, json.dumps(company.aliases, ensure_ascii=False), json.dumps(company.official_domains), now),
                )
            for person in registry.people:
                self.connection.execute(
                    """INSERT INTO people(company_id,name,role,aliases_json,profile_url) VALUES(?,?,?,?,?)
                       ON CONFLICT(company_id,name) DO UPDATE SET role=excluded.role,
                       aliases_json=excluded.aliases_json,profile_url=excluded.profile_url""",
                    (person.company, person.name, person.role, json.dumps(person.aliases, ensure_ascii=False), person.profile_url),
                )
            for source in registry.sources:
                self.connection.execute(
                    """INSERT INTO sources(id,company_id,name,source_type,tier,url,official,config_json)
                       VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                       company_id=excluded.company_id,name=excluded.name,source_type=excluded.source_type,
                       tier=excluded.tier,url=excluded.url,official=excluded.official,config_json=excluded.config_json""",
                    (
                        source.id,
                        source.company,
                        source.name,
                        source.type,
                        str(source.tier),
                        source.url,
                        int(source.official),
                        json.dumps({"include_patterns": source.include_patterns}, ensure_ascii=False),
                    ),
                )

    def start_run(self) -> int:
        cursor = self.connection.execute(
            "INSERT INTO collection_runs(started_at,status,stats_json) VALUES(?,?,?)",
            (datetime.now(timezone.utc).isoformat(), "running", "{}"),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, stats: dict[str, Any], error: str | None = None) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE collection_runs SET finished_at=?,status=?,stats_json=?,error=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), status, json.dumps(stats, ensure_ascii=False), error, run_id),
            )

    def existing_urls(self, urls: Iterable[str]) -> set[str]:
        values = [url for url in urls if url]
        if not values:
            return set()
        found: set[str] = set()
        for start in range(0, len(values), 500):
            batch = values[start : start + 500]
            placeholders = ",".join("?" for _ in batch)
            rows = self.connection.execute(
                f"SELECT canonical_url FROM documents WHERE canonical_url IN ({placeholders})", batch
            ).fetchall()
            found.update(str(row["canonical_url"]) for row in rows)
        return found

    def upsert_document(self, document: Document) -> tuple[int, bool]:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection:
            row = self.connection.execute(
                "SELECT id,content_hash FROM documents WHERE canonical_url=?", (document.canonical_url,)
            ).fetchone()
            if row:
                self.connection.execute(
                    """UPDATE documents SET url=?,title=?,published_at=COALESCE(?,published_at),fetched_at=?,
                       text=?,content_hash=?,tier=?,official=?,people_json=?,attribution_status=?,
                       verification_reason=?,metadata_json=?,last_seen_at=? WHERE id=?""",
                    (
                        document.url,
                        document.title,
                        document.published_at,
                        document.fetched_at,
                        document.text,
                        document.content_hash,
                        str(document.tier),
                        int(document.official),
                        json.dumps(document.people, ensure_ascii=False),
                        document.attribution_status,
                        document.verification_reason,
                        json.dumps(document.metadata, ensure_ascii=False),
                        now,
                        row["id"],
                    ),
                )
                if row["content_hash"] != document.content_hash:
                    self.connection.execute("DELETE FROM analyses WHERE document_id=?", (row["id"],))
                return int(row["id"]), False
            duplicate = self.connection.execute(
                "SELECT id FROM documents WHERE company_id=? AND content_hash=? LIMIT 1",
                (document.company, document.content_hash),
            ).fetchone()
            if duplicate:
                self.connection.execute(
                    "UPDATE documents SET last_seen_at=? WHERE id=?", (now, duplicate["id"])
                )
                return int(duplicate["id"]), False
            cursor = self.connection.execute(
                """INSERT INTO documents(company_id,source_id,source_name,source_type,url,canonical_url,title,
                   published_at,fetched_at,text,content_hash,tier,official,people_json,attribution_status,
                   verification_reason,metadata_json,first_seen_at,last_seen_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    document.company,
                    document.source_id,
                    document.source_name,
                    document.source_type,
                    document.url,
                    document.canonical_url,
                    document.title,
                    document.published_at,
                    document.fetched_at,
                    document.text,
                    document.content_hash,
                    str(document.tier),
                    int(document.official),
                    json.dumps(document.people, ensure_ascii=False),
                    document.attribution_status,
                    document.verification_reason,
                    json.dumps(document.metadata, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid), True

    def documents_for_analysis(self, companies: list[str] | None = None, limit: int = 0) -> list[sqlite3.Row]:
        clauses = ["a.id IS NULL", "length(d.text) >= 120"]
        params: list[Any] = []
        if companies:
            clauses.append("d.company_id IN (%s)" % ",".join("?" for _ in companies))
            params.extend(companies)
        sql = """SELECT d.* FROM documents d LEFT JOIN analyses a ON a.document_id=d.id
                 WHERE %s ORDER BY COALESCE(d.published_at,d.fetched_at) DESC""" % " AND ".join(clauses)
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        return list(self.connection.execute(sql, params).fetchall())

    def recent_timeline(self, company: str, days: int = 365, limit: int = 30) -> list[dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        rows = self.connection.execute(
            """SELECT d.id,d.title,d.published_at,a.technical_signals_json,a.trend_summary,a.evidence_level
               FROM documents d JOIN analyses a ON a.document_id=d.id
               WHERE d.company_id=? AND COALESCE(d.published_at,substr(d.fetched_at,1,10))>=?
               ORDER BY COALESCE(d.published_at,d.fetched_at) DESC LIMIT ?""",
            (company, cutoff, limit),
        ).fetchall()
        return [
            {
                "document_id": row["id"],
                "title": row["title"],
                "published_at": row["published_at"],
                "technical_signals": json.loads(row["technical_signals_json"]),
                "trend_summary": row["trend_summary"],
                "evidence_level": row["evidence_level"],
            }
            for row in rows
        ]

    def save_analysis(self, analysis: Analysis) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO analyses(document_id,core_points_json,technical_signals_json,
                   attributed_statements_json,trend_summary,trend_directions_json,evidence_level,
                   confidence,time_window,model,grounding_passed,analysis_method,analyzed_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET
                   core_points_json=excluded.core_points_json,technical_signals_json=excluded.technical_signals_json,
                   attributed_statements_json=excluded.attributed_statements_json,trend_summary=excluded.trend_summary,
                   trend_directions_json=excluded.trend_directions_json,evidence_level=excluded.evidence_level,
                   confidence=excluded.confidence,time_window=excluded.time_window,model=excluded.model,
                   grounding_passed=excluded.grounding_passed,analysis_method=excluded.analysis_method,
                   analyzed_at=excluded.analyzed_at""",
                (
                    analysis.document_id,
                    json.dumps(analysis.core_points, ensure_ascii=False),
                    json.dumps(analysis.technical_signals, ensure_ascii=False),
                    json.dumps(analysis.attributed_statements, ensure_ascii=False),
                    analysis.trend_summary,
                    json.dumps(analysis.trend_directions, ensure_ascii=False),
                    str(analysis.evidence_level),
                    analysis.confidence,
                    analysis.time_window,
                    analysis.model,
                    int(analysis.grounding_passed),
                    analysis.analysis_method,
                    analysis.analyzed_at,
                ),
            )

    def sanitize_attributions(self, registry: Registry) -> dict[str, int]:
        """Keep only grounded statements that map to a tracked executive/technical leader."""
        rows = self.connection.execute(
            """SELECT d.id,d.company_id,d.text,d.people_json,a.attributed_statements_json
               FROM documents d JOIN analyses a ON a.document_id=d.id"""
        ).fetchall()
        stats = {"documents_checked": len(rows), "documents_changed": 0, "statements_before": 0, "statements_after": 0}
        with self.connection:
            for row in rows:
                try:
                    statements = json.loads(row["attributed_statements_json"] or "[]")
                    existing_people = json.loads(row["people_json"] or "[]")
                except json.JSONDecodeError:
                    statements, existing_people = [], []
                stats["statements_before"] += len(statements)
                text_match = normalized_for_match(str(row["text"]))
                company_people = registry.people_for(str(row["company_id"]))
                cleaned: list[dict[str, Any]] = []
                matched_people = {str(person.get("name", "")): person for person in existing_people}
                for statement in statements:
                    if not isinstance(statement, dict):
                        continue
                    speaker_match = normalized_for_match(str(statement.get("speaker", "")))
                    evidence_match = normalized_for_match(str(statement.get("evidence", "")))
                    if not speaker_match or not evidence_match or evidence_match not in text_match:
                        continue
                    matched = None
                    for person in company_people:
                        aliases = [person.name, *person.aliases]
                        if any(normalized_for_match(alias) and normalized_for_match(alias) in speaker_match for alias in aliases):
                            matched = person
                            break
                    if not matched:
                        continue
                    normalized_statement = dict(statement)
                    normalized_statement["speaker"] = matched.name
                    normalized_statement["role"] = matched.role
                    cleaned.append(normalized_statement)
                    matched_people[matched.name] = {"name": matched.name, "role": matched.role}
                stats["statements_after"] += len(cleaned)
                if cleaned != statements or list(matched_people.values()) != existing_people:
                    stats["documents_changed"] += 1
                    self.connection.execute(
                        "UPDATE analyses SET attributed_statements_json=? WHERE document_id=?",
                        (json.dumps(cleaned, ensure_ascii=False), row["id"]),
                    )
                    self.connection.execute(
                        "UPDATE documents SET people_json=?,attribution_status=? WHERE id=?",
                        (
                            json.dumps(list(matched_people.values()), ensure_ascii=False),
                            "verified_person_statement" if cleaned else ("named_person_mention" if matched_people else "official_editorial"),
                            row["id"],
                        ),
                    )
        return stats

    def report_rows(self, companies: list[str] | None = None, days: int | None = None) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        params: list[Any] = []
        if companies:
            clauses.append("d.company_id IN (%s)" % ",".join("?" for _ in companies))
            params.extend(companies)
        if days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
            clauses.append("COALESCE(d.published_at,substr(d.fetched_at,1,10))>=?")
            params.append(cutoff)
        rows = self.connection.execute(
            """SELECT d.*,c.name AS company_name,a.core_points_json,a.technical_signals_json,
               a.attributed_statements_json,a.trend_summary,a.trend_directions_json,a.evidence_level,
               a.confidence,a.time_window,a.model,a.grounding_passed,a.analysis_method,a.analyzed_at
               FROM documents d JOIN companies c ON c.id=d.company_id
               LEFT JOIN analyses a ON a.document_id=d.id WHERE %s
               ORDER BY c.name,COALESCE(d.published_at,d.fetched_at) DESC""" % " AND ".join(clauses),
            params,
        ).fetchall()
        output: list[dict[str, Any]] = []
        json_fields = {
            "people_json": [],
            "metadata_json": {},
            "core_points_json": [],
            "technical_signals_json": [],
            "attributed_statements_json": [],
            "trend_directions_json": [],
        }
        for row in rows:
            item = dict(row)
            for field, default in json_fields.items():
                raw = item.get(field)
                try:
                    item[field] = json.loads(raw) if raw else default
                except json.JSONDecodeError:
                    item[field] = default
            output.append(item)
        return output

    def stats(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in ("companies", "people", "sources", "documents", "analyses"):
            result[table] = int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return result
