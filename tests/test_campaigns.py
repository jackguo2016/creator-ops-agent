import pytest


def test_demo_campaign_is_seeded_and_editable(client, db):
    row = db.execute("SELECT * FROM campaigns").fetchone()

    assert row["name"] == "LumaSip 美国创作者启动项目"

    response = client.post(
        f"/campaigns/{row['id']}",
        data={
            "brand": "LumaSip",
            "name": "LumaSip 秋季项目",
            "market": "US",
            "language": "English",
            "platforms": "TikTok,YouTube",
            "categories": "fitness,tech",
            "min_followers": "20000",
            "max_followers": "500000",
            "max_fee": "1200",
            "total_budget": "6000",
            "deadline": "2026-11-15",
            "deliverables": "1 short video; profile link for 7 days",
            "restrictions": "No medical claims; include #ad",
            "brief_text": "Launch a smart hydration bottle for active US consumers.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    saved = db.execute(
        "SELECT name, platforms_json FROM campaigns WHERE id = ?", (row["id"],)
    ).fetchone()
    assert saved["name"] == "LumaSip 秋季项目"
    assert saved["platforms_json"] == '["TikTok", "YouTube"]'


def test_campaign_page_returns_validation_errors_without_saving(client, db):
    campaign_id = db.execute("SELECT id FROM campaigns").fetchone()[0]

    response = client.post(
        f"/campaigns/{campaign_id}",
        data={
            "brand": "LumaSip",
            "name": "Invalid",
            "market": "US",
            "language": "English",
            "platforms": "TikTok",
            "categories": "fitness",
            "min_followers": "500000",
            "max_followers": "20000",
            "max_fee": "1200",
            "total_budget": "6000",
            "deadline": "2026-11-15",
            "deliverables": "1 video",
            "restrictions": "No medical claims",
            "brief_text": "Launch brief",
        },
    )

    assert response.status_code == 422
    assert "粉丝数上限不能低于下限" in response.text
    stored = db.execute(
        "SELECT max_followers FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()[0]
    assert stored == 500000


@pytest.mark.parametrize("path", ["/campaigns/999", "/campaigns/999/matches", "/campaigns/999/workflow"])
def test_missing_campaign_returns_not_found(client, path):
    response = client.get(path)

    assert response.status_code == 404


def test_budget_edit_on_web_blocks_old_draft_and_recalculates_matches(client, db, settings):
    from app.campaigns import DEMO_CAMPAIGN
    from app.creators import parse_creator_csv, upsert_creators
    from app.llm import LLMClient
    from app.matching import refresh_rule_matches
    from app.outreach import select_creator, create_outreach_draft
    from datetime import date
    from pathlib import Path

    upsert_creators(db, parse_creator_csv(Path("data/creators.csv").read_bytes(), date(2026, 10, 3)))
    refresh_rule_matches(db, 1)
    creator_id = db.execute("SELECT creator_id FROM matches WHERE eligible = 1 LIMIT 1").fetchone()[0]
    select_creator(db, 1, creator_id)
    draft_id = create_outreach_draft(db, 1, creator_id, LLMClient(settings, db))
    payload = DEMO_CAMPAIGN.model_dump(mode="json")
    payload.update(platforms=",".join(payload["platforms"]), categories=",".join(payload["categories"]), max_fee=100)

    saved = client.post("/campaigns/1", data=payload, follow_redirects=False)

    assert saved.status_code == 303
    assert client.post(f"/drafts/{draft_id}/approve").status_code == 400
    assert client.post(f"/campaigns/1/drafts/{creator_id}").status_code == 400
    matches_page = client.get("/campaigns/1/matches")
    assert matches_page.status_code == 200
    assert db.execute("SELECT eligible FROM matches WHERE creator_id = ?", (creator_id,)).fetchone()[0] == 0
    workflow = client.get("/campaigns/1/workflow")
    assert "已失效" in workflow.text


@pytest.mark.parametrize("field", ["max_fee", "total_budget"])
@pytest.mark.parametrize("value", ["inf", "nan", "-inf", "1e309"])
def test_campaign_rejects_nonfinite_budget_without_saving(client, db, field, value):
    from app.campaigns import DEMO_CAMPAIGN

    before = tuple(db.execute("SELECT max_fee, total_budget FROM campaigns WHERE id = 1").fetchone())
    payload = DEMO_CAMPAIGN.model_dump(mode="json")
    payload.update(platforms=",".join(payload["platforms"]), categories=",".join(payload["categories"]))
    payload[field] = value

    response = client.post("/campaigns/1", data=payload, follow_redirects=False)

    assert response.status_code == 422
    assert tuple(db.execute("SELECT max_fee, total_budget FROM campaigns WHERE id = 1").fetchone()) == before


@pytest.mark.parametrize("field", ["min_followers", "max_followers"])
def test_campaign_rejects_followers_outside_sqlite_integer_range(client, db, field):
    from app.campaigns import DEMO_CAMPAIGN

    payload = DEMO_CAMPAIGN.model_dump(mode="json")
    payload.update(platforms=",".join(payload["platforms"]), categories=",".join(payload["categories"]))
    payload[field] = str(2**63)
    if field == "min_followers":
        payload["max_followers"] = str(2**63)

    response = client.post("/campaigns/1", data=payload, follow_redirects=False)

    assert response.status_code == 422
    assert tuple(db.execute("SELECT min_followers, max_followers FROM campaigns WHERE id = 1").fetchone()) == (20000, 500000)
