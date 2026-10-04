from datetime import date

import pytest

from app.creators import parse_creator_csv, upsert_creators


CSV_PAYLOAD = b"""name,platform,handle,country,category,followers,engagement_rate,estimated_fee,currency,language,email,source,source_updated_at,notes
Maya Lee,TikTok,@mayamoves,US,fitness,85000,4.8,900,USD,English,maya@example.test,demo,2026-09-20,Strong video hooks
Maya New,TikTok,mayamoves,US,fitness,91000,5.0,950,USD,English,,demo,2026-09-25,Updated quote
No Handle,TikTok,,US,fitness,20000,3.2,400,USD,English,nobody@example.test,demo,2026-09-20,
Old Quote,YouTube,@oldquote,US,tech,40000,3.9,700,USD,English,old@example.test,demo,2025-01-01,
"""


def test_csv_reports_duplicate_missing_and_stale_rows(db):
    summary = parse_creator_csv(CSV_PAYLOAD, date(2026, 10, 2))

    assert summary.valid_count == 2
    assert summary.duplicate_count == 1
    assert {issue.code for issue in summary.issues} == {
        "missing_handle",
        "stale_quote",
    }

    upsert_creators(db, summary)
    creator = db.execute(
        "SELECT * FROM creators WHERE normalized_handle = 'mayamoves'"
    ).fetchone()
    assert creator["name"] == "Maya New"
    assert creator["email"] == "maya@example.test"


def test_upload_rejects_non_csv_file(client):
    response = client.post(
        "/creators/import",
        files={"file": ("creators.txt", CSV_PAYLOAD, "text/plain")},
    )

    assert response.status_code == 400
    assert "只接受 CSV 文件" in response.text


@pytest.mark.parametrize("field", ["engagement_rate", "estimated_fee"])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_csv_rejects_nonfinite_numbers(field, value, client):
    header = CSV_PAYLOAD.decode().splitlines()[0]
    row = dict(zip(header.split(","), CSV_PAYLOAD.decode().splitlines()[1].split(",")))
    row[field] = value
    payload = (header + "\n" + ",".join(row[column] for column in header.split(",")) + "\n").encode()

    summary = parse_creator_csv(payload, date(2026, 10, 3))

    assert summary.valid_count == 0
    assert summary.issues[0].code == "invalid_value"
    response = client.post("/creators/import", files={"file": ("creators.csv", payload, "text/csv")})
    assert response.status_code == 200


def test_duplicate_blank_fields_preserve_newest_nonempty_values(db):
    header = CSV_PAYLOAD.decode().splitlines()[0]
    payload = (header + "\n"
        "Actual Name,TikTok,@merge,US,fitness,85000,4.8,900,EUR,French,,demo,2026-09-20,\n"
        ",TikTok,@merge,US,fitness,91000,5.0,950,,,,demo,2026-09-25,\n").encode()

    upsert_creators(db, parse_creator_csv(payload, date(2026, 10, 3)))

    creator = db.execute("SELECT name,currency,language FROM creators WHERE normalized_handle = 'merge'").fetchone()
    assert tuple(creator) == ("Actual Name", "EUR", "French")


def test_new_quote_import_invalidates_old_selection_and_draft(db, settings):
    from app.llm import LLMClient
    from app.matching import refresh_rule_matches
    from app.outreach import select_creator, create_outreach_draft, approve_draft

    upsert_creators(db, parse_creator_csv(CSV_PAYLOAD, date(2026, 10, 3)))
    refresh_rule_matches(db, 1)
    creator_id = db.execute("SELECT id FROM creators WHERE normalized_handle = 'mayamoves'").fetchone()[0]
    select_creator(db, 1, creator_id)
    draft_id = create_outreach_draft(db, 1, creator_id, LLMClient(settings, db))
    payload = CSV_PAYLOAD.replace(b"5.0,950,", b"5.0,2500,")

    upsert_creators(db, parse_creator_csv(payload, date(2026, 10, 3)))

    assert db.execute("SELECT selected FROM matches WHERE creator_id = ?", (creator_id,)).fetchone()[0] == 0
    with pytest.raises(ValueError):
        approve_draft(db, draft_id)


def test_reimporting_same_data_does_not_invalidate_draft(db, settings):
    from app.llm import LLMClient
    from app.matching import refresh_rule_matches
    from app.outreach import select_creator, create_outreach_draft

    upsert_creators(db, parse_creator_csv(CSV_PAYLOAD, date(2026, 10, 3)))
    refresh_rule_matches(db, 1)
    creator_id = db.execute("SELECT id FROM creators WHERE normalized_handle = 'mayamoves'").fetchone()[0]
    select_creator(db, 1, creator_id)
    draft_id = create_outreach_draft(db, 1, creator_id, LLMClient(settings, db))

    upsert_creators(db, parse_creator_csv(CSV_PAYLOAD, date(2026, 10, 3)))

    assert db.execute("SELECT status FROM drafts WHERE id = ?", (draft_id,)).fetchone()[0] == "pending"


@pytest.mark.parametrize("followers,valid_count", [(2**63 - 1, 1), (2**63, 0)])
def test_csv_followers_respect_sqlite_integer_range(followers, valid_count, client, db):
    header = CSV_PAYLOAD.decode().splitlines()[0]
    row = dict(zip(header.split(","), CSV_PAYLOAD.decode().splitlines()[1].split(",")))
    row.update(followers=str(followers), source_updated_at=date.today().isoformat())
    payload = (header + "\n" + ",".join(row[column] for column in header.split(",")) + "\n").encode()

    summary = parse_creator_csv(payload, date.today())

    assert summary.valid_count == valid_count
    if not valid_count:
        assert summary.issues[0].code == "invalid_value"
    response = client.post("/creators/import", files={"file": ("creators.csv", payload, "text/csv")})
    assert response.status_code == 200
    assert db.execute("SELECT COUNT(*) FROM creators").fetchone()[0] == valid_count


def test_csv_oversized_field_is_reported_as_bad_input(client, db):
    header = CSV_PAYLOAD.decode().splitlines()[0]
    row = dict(zip(header.split(","), CSV_PAYLOAD.decode().splitlines()[1].split(",")))
    row.update(notes="x" * 140000, source_updated_at=date.today().isoformat())
    payload = (header + "\n" + ",".join(row[column] for column in header.split(",")) + "\n").encode()

    with pytest.raises(ValueError, match="CSV"):
        parse_creator_csv(payload, date.today())
    response = client.post("/creators/import", files={"file": ("creators.csv", payload, "text/csv")})
    assert response.status_code == 400
    assert db.execute("SELECT COUNT(*) FROM creators").fetchone()[0] == 0
