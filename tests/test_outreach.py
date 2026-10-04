from datetime import date
from pathlib import Path

import pytest

from app.campaigns import DEMO_CAMPAIGN, update_campaign
from app.creators import parse_creator_csv, upsert_creators
from app.llm import LLMClient
from app.matching import refresh_rule_matches
from app.outreach import (
    approve_draft,
    create_outreach_draft,
    rank_eligible_matches,
    select_creator,
    list_selected_creators,
)


def _seed_matches(db) -> int:
    campaign_id = db.execute("SELECT id FROM campaigns").fetchone()[0]
    summary = parse_creator_csv(Path("data/creators.csv").read_bytes(), date(2026, 10, 2))
    upsert_creators(db, summary)
    refresh_rule_matches(db, campaign_id)
    return campaign_id


def test_only_eligible_creators_are_ranked(db, settings):
    campaign_id = _seed_matches(db)
    llm = LLMClient(settings, db)

    count = rank_eligible_matches(db, campaign_id, llm)

    eligible = db.execute(
        "SELECT COUNT(*) FROM matches WHERE campaign_id = ? AND eligible = 1",
        (campaign_id,),
    ).fetchone()[0]
    ranked = db.execute(
        "SELECT COUNT(*) FROM matches WHERE campaign_id = ? AND llm_score IS NOT NULL",
        (campaign_id,),
    ).fetchone()[0]
    assert count == eligible == ranked
    assert eligible > 0


def test_draft_requires_explicit_approval(db, settings):
    campaign_id = _seed_matches(db)
    creator_id = db.execute(
        "SELECT creator_id FROM matches WHERE campaign_id = ? AND eligible = 1 LIMIT 1",
        (campaign_id,),
    ).fetchone()[0]
    select_creator(db, campaign_id, creator_id)

    draft_id = create_outreach_draft(
        db, campaign_id, creator_id, LLMClient(settings, db)
    )

    pending = db.execute(
        "SELECT status, approved_at FROM drafts WHERE id = ?", (draft_id,)
    ).fetchone()
    assert pending["status"] == "pending"
    assert pending["approved_at"] is None

    approve_draft(db, draft_id)
    approved = db.execute(
        "SELECT status, approved_at FROM drafts WHERE id = ?", (draft_id,)
    ).fetchone()
    assert approved["status"] == "approved"
    assert approved["approved_at"] is not None


def _selected_draft(db, settings):
    campaign_id = _seed_matches(db)
    creator_id = db.execute(
        "SELECT creator_id FROM matches WHERE eligible = 1 LIMIT 1"
    ).fetchone()[0]
    select_creator(db, campaign_id, creator_id)
    draft_id = create_outreach_draft(db, campaign_id, creator_id, LLMClient(settings, db))
    return campaign_id, creator_id, draft_id


def test_campaign_change_invalidates_matches_and_old_draft(db, settings):
    campaign_id, creator_id, draft_id = _selected_draft(db, settings)

    update_campaign(db, campaign_id, DEMO_CAMPAIGN.model_copy(update={"max_fee": 100}))

    match = db.execute(
        "SELECT * FROM matches WHERE campaign_id = ? AND creator_id = ?",
        (campaign_id, creator_id),
    ).fetchone()
    assert match["selected"] == 0
    assert match["rule_score"] is None
    assert db.execute("SELECT status FROM drafts WHERE id = ?", (draft_id,)).fetchone()[0] == "stale"
    with pytest.raises(ValueError):
        select_creator(db, campaign_id, creator_id)
    with pytest.raises(ValueError):
        create_outreach_draft(db, campaign_id, creator_id, LLMClient(settings, db))
    with pytest.raises(ValueError):
        approve_draft(db, draft_id)
    assert db.execute("SELECT COUNT(*) FROM drafts WHERE id = ?", (draft_id,)).fetchone()[0] == 1


def test_selection_rechecks_current_budget_even_with_legacy_cached_match(db, settings):
    campaign_id = _seed_matches(db)
    creator_id = db.execute("SELECT creator_id FROM matches WHERE eligible = 1 LIMIT 1").fetchone()[0]
    db.execute("UPDATE campaigns SET max_fee = 100 WHERE id = ?", (campaign_id,))
    db.commit()

    with pytest.raises(ValueError):
        select_creator(db, campaign_id, creator_id)


def test_draft_and_approval_recheck_current_budget(db, settings):
    campaign_id, creator_id, draft_id = _selected_draft(db, settings)
    db.execute("UPDATE campaigns SET max_fee = 100 WHERE id = ?", (campaign_id,))
    db.commit()

    with pytest.raises(ValueError):
        create_outreach_draft(db, campaign_id, creator_id, LLMClient(settings, db))
    with pytest.raises(ValueError):
        approve_draft(db, draft_id)


def test_refilter_removes_excluded_creator_from_selected_workflow(db, settings):
    campaign_id, creator_id, draft_id = _selected_draft(db, settings)
    db.execute("UPDATE campaigns SET max_fee = 100 WHERE id = ?", (campaign_id,))
    db.commit()

    refresh_rule_matches(db, campaign_id)

    assert list_selected_creators(db, campaign_id) == []
    with pytest.raises(ValueError):
        approve_draft(db, draft_id)


def test_saving_unchanged_campaign_preserves_selection_and_pending_draft(db, settings):
    campaign_id, creator_id, draft_id = _selected_draft(db, settings)

    update_campaign(db, campaign_id, DEMO_CAMPAIGN)

    assert db.execute("SELECT selected FROM matches WHERE creator_id = ?", (creator_id,)).fetchone()[0] == 1
    assert db.execute("SELECT status FROM drafts WHERE id = ?", (draft_id,)).fetchone()[0] == "pending"


def test_brief_change_during_generation_cannot_create_pending_old_draft(db, settings):
    from app.models import OutreachDraftResult

    campaign_id = _seed_matches(db)
    creator_id = db.execute("SELECT creator_id FROM matches WHERE eligible = 1 LIMIT 1").fetchone()[0]
    select_creator(db, campaign_id, creator_id)

    class UpdatingModel:
        def generate_outreach(self, campaign, creator, knowledge):
            update_campaign(db, campaign_id, DEMO_CAMPAIGN.model_copy(update={"brand": "ChangedBrand"}))
            return OutreachDraftResult(subject="Old LumaSip subject", body="Old campaign", brief="Old brief")

    with pytest.raises(ValueError):
        create_outreach_draft(db, campaign_id, creator_id, UpdatingModel())
    assert db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0


def test_brief_change_during_ranking_cannot_save_old_explanation(db, settings):
    from app.models import MatchExplanation

    campaign_id = _seed_matches(db)

    class UpdatingModel:
        def rank_creator(self, campaign, creator, knowledge):
            update_campaign(db, campaign_id, DEMO_CAMPAIGN.model_copy(update={"brand": "ChangedBrand"}))
            return MatchExplanation(score=99, recommendation="Old explanation", reasons=["old"], evidence=["项目 Brief"], risks=[])

    with pytest.raises(ValueError):
        rank_eligible_matches(db, campaign_id, UpdatingModel())
    assert db.execute("SELECT COUNT(*) FROM matches WHERE llm_score IS NOT NULL").fetchone()[0] == 0
