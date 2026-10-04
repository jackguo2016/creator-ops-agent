from __future__ import annotations

import csv
import io
import math
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import date

from app.db import invalidate_campaign_results


REQUIRED_HEADERS = (
    "name",
    "platform",
    "handle",
    "country",
    "category",
    "followers",
    "engagement_rate",
    "estimated_fee",
    "currency",
    "language",
    "email",
    "source",
    "source_updated_at",
    "notes",
)


@dataclass(frozen=True)
class CreatorRow:
    row_number: int
    name: str
    platform: str
    handle: str
    normalized_handle: str
    country: str
    category: str
    followers: int
    engagement_rate: float
    estimated_fee: float
    currency: str
    language: str
    email: str
    source: str
    source_updated_at: date
    notes: str


@dataclass(frozen=True)
class ImportIssue:
    row_number: int
    code: str
    message: str


@dataclass
class ImportSummary:
    rows: list[CreatorRow] = field(default_factory=list)
    issues: list[ImportIssue] = field(default_factory=list)
    duplicate_count: int = 0

    @property
    def valid_count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True)
class CreatorFilters:
    country: str = ""
    platform: str = ""
    category: str = ""


def _text(row: dict[str, str | None], key: str) -> str:
    return (row.get(key) or "").strip()


def _issue(summary: ImportSummary, row_number: int, code: str, message: str) -> None:
    summary.issues.append(ImportIssue(row_number, code, message))


def _read_csv_rows(text: str):
    try:
        reader = csv.DictReader(io.StringIO(text))
        if tuple(reader.fieldnames or ()) != REQUIRED_HEADERS:
            raise ValueError("CSV 表头不符合模板")
        yield from reader
    except csv.Error as exc:
        raise ValueError("CSV 解析失败：单字段过长或文件结构无效") from exc


def parse_creator_csv(data: bytes, today: date) -> ImportSummary:
    summary = ImportSummary()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV 必须使用 UTF-8 编码") from exc

    seen: set[tuple[str, str]] = set()
    for row_number, raw in enumerate(_read_csv_rows(text), start=2):
        platform = _text(raw, "platform").title()
        handle = _text(raw, "handle")
        normalized_handle = handle.lstrip("@").lower()
        required = {
            "platform": platform,
            "handle": normalized_handle,
            "country": _text(raw, "country"),
            "estimated_fee": _text(raw, "estimated_fee"),
            "source_updated_at": _text(raw, "source_updated_at"),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            code = "missing_handle" if "handle" in missing else "missing_required"
            _issue(summary, row_number, code, f"缺少必填字段：{', '.join(missing)}")
            continue
        try:
            followers = int(_text(raw, "followers"))
            engagement_rate = float(_text(raw, "engagement_rate"))
            estimated_fee = float(_text(raw, "estimated_fee"))
            updated_at = date.fromisoformat(_text(raw, "source_updated_at"))
        except (TypeError, ValueError):
            _issue(summary, row_number, "invalid_value", "数值或日期格式无效")
            continue
        if not all(math.isfinite(value) for value in (engagement_rate, estimated_fee)) or min(followers, engagement_rate, estimated_fee) < 0:
            _issue(summary, row_number, "invalid_value", "数值必须是有限的非负数")
            continue
        if followers > 2**63 - 1:
            _issue(summary, row_number, "invalid_value", "粉丝数超出数据库整数范围")
            continue
        if (today - updated_at).days > 365:
            _issue(summary, row_number, "stale_quote", "报价更新时间超过 365 天")
            continue

        key = (platform.lower(), normalized_handle)
        if key in seen:
            summary.duplicate_count += 1
        seen.add(key)
        summary.rows.append(
            CreatorRow(
                row_number=row_number,
                name=_text(raw, "name"),
                platform=platform,
                handle=handle if handle.startswith("@") else f"@{handle}",
                normalized_handle=normalized_handle,
                country=_text(raw, "country").upper(),
                category=_text(raw, "category").lower(),
                followers=followers,
                engagement_rate=engagement_rate,
                estimated_fee=estimated_fee,
                currency=_text(raw, "currency").upper(),
                language=_text(raw, "language"),
                email=_text(raw, "email"),
                source=_text(raw, "source"),
                source_updated_at=updated_at,
                notes=_text(raw, "notes"),
            )
        )
    return summary


def _merge_duplicate_rows(rows: list[CreatorRow]) -> CreatorRow:
    ordered = sorted(rows, key=lambda row: row.source_updated_at, reverse=True)
    primary = ordered[0]

    def newest_nonempty(field_name: str) -> str:
        for row in ordered:
            value = getattr(row, field_name)
            if value:
                return str(value)
        return ""

    return CreatorRow(
        row_number=primary.row_number,
        name=newest_nonempty("name"),
        platform=primary.platform,
        handle=primary.handle,
        normalized_handle=primary.normalized_handle,
        country=newest_nonempty("country"),
        category=newest_nonempty("category"),
        followers=primary.followers,
        engagement_rate=primary.engagement_rate,
        estimated_fee=primary.estimated_fee,
        currency=newest_nonempty("currency"),
        language=newest_nonempty("language"),
        email=newest_nonempty("email"),
        source=newest_nonempty("source"),
        source_updated_at=primary.source_updated_at,
        notes=newest_nonempty("notes"),
    )


def upsert_creators(
    connection: sqlite3.Connection, summary: ImportSummary
) -> ImportSummary:
    grouped: dict[tuple[str, str], list[CreatorRow]] = {}
    for row in summary.rows:
        grouped.setdefault((row.platform, row.normalized_handle), []).append(row)

    affected_campaigns: set[int] = set()
    for rows in grouped.values():
        creator = _merge_duplicate_rows(rows)
        existing = connection.execute(
            "SELECT * FROM creators WHERE platform = ? AND normalized_handle = ?",
            (creator.platform, creator.normalized_handle),
        ).fetchone()
        defaults = {"name": creator.normalized_handle, "currency": "USD", "language": "English", "source": "upload", "email": "", "notes": ""}
        creator = replace(creator, **{
            name: getattr(creator, name) or (existing[name] if existing else default)
            for name, default in defaults.items()
        })
        fields = ("name", "platform", "handle", "normalized_handle", "country", "category", "followers", "engagement_rate", "estimated_fee", "currency", "language", "email", "source", "source_updated_at", "notes")
        values = tuple(
            creator.source_updated_at.isoformat() if name == "source_updated_at" else getattr(creator, name)
            for name in fields
        )
        changed = existing is not None and any(existing[name] != value for name, value in zip(fields, values))
        cursor = connection.execute(
            """
            INSERT INTO creators (
                name, platform, handle, normalized_handle, country, category,
                followers, engagement_rate, estimated_fee, currency, language,
                email, source, source_updated_at, notes, data_quality_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'valid')
            ON CONFLICT(platform, normalized_handle) DO UPDATE SET
                name = excluded.name,
                handle = excluded.handle,
                country = excluded.country,
                category = excluded.category,
                followers = excluded.followers,
                engagement_rate = excluded.engagement_rate,
                estimated_fee = excluded.estimated_fee,
                currency = excluded.currency,
                language = excluded.language,
                email = CASE WHEN excluded.email != '' THEN excluded.email ELSE creators.email END,
                source = excluded.source,
                source_updated_at = excluded.source_updated_at,
                notes = CASE WHEN excluded.notes != '' THEN excluded.notes ELSE creators.notes END,
                data_quality_status = 'valid',
                updated_at = CURRENT_TIMESTAMP
            WHERE excluded.source_updated_at >= creators.source_updated_at
            """,
            values,
        )
        if changed and cursor.rowcount:
            affected_campaigns.update(row[0] for row in connection.execute(
                "SELECT DISTINCT campaign_id FROM matches WHERE creator_id = ?", (existing["id"],)
            ))
    for campaign_id in affected_campaigns:
        invalidate_campaign_results(connection, campaign_id)
    connection.commit()
    return summary


def list_creators(
    connection: sqlite3.Connection, filters: CreatorFilters = CreatorFilters()
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[str] = []
    for column, value in (
        ("country", filters.country.upper()),
        ("platform", filters.platform.title()),
        ("category", filters.category.lower()),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return connection.execute(
        f"SELECT * FROM creators {where} ORDER BY followers DESC", params
    ).fetchall()
