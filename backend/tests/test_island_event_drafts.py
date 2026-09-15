from __future__ import annotations

import json
from pathlib import Path

from app.islands import get_islands


ALLOWED_ACTIONS = {
    "approach",
    "observe",
    "respond",
    "cooperate",
    "avoid",
    "leave",
}
ALLOWED_END_CONDITIONS = {
    "both_completed_turn",
    "one_left",
    "max_turns_reached",
}


def load_draft() -> dict:
    path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "authored"
        / "island_events.draft.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_event_review_covers_every_island_and_records_exclusion():
    draft = load_draft()
    assert draft["authored_status"] == "approved_with_exclusions"
    assert draft["target_fixture_version"] == "v2"
    assert draft["approved_on"] == "2026-09-15"
    assert draft["excluded_event_ids"] == ["ai-borrowed-voice"]
    assert {island["island_id"] for island in draft["islands"]} == set(
        get_islands().ids
    )


def test_each_island_has_three_bounded_events_and_all_basic_actions():
    event_ids: set[str] = set()
    for island in load_draft()["islands"]:
        assert island["scene"].strip()
        assert len(island["events"]) == 3
        assert [event["act"] for event in island["events"]] == [1, 2, 3]
        for event in island["events"]:
            assert event["event_id"] not in event_ids
            event_ids.add(event["event_id"])
            assert set(event["available_actions"]) == ALLOWED_ACTIONS
            assert 2 <= event["max_turns"] <= 5
            assert set(event["end_conditions"]) == ALLOWED_END_CONDITIONS
            assert 1 <= event["material_limit"] <= 3
            assert event["dilemma"].strip()
            assert event["return_question"].endswith("？")


def test_published_fixture_contains_only_approved_events():
    draft = load_draft()
    excluded = set(draft["excluded_event_ids"])
    expected = {
        event["event_id"]
        for island in draft["islands"]
        for event in island["events"]
        if event["event_id"] not in excluded
    }
    published = {
        event["event_id"]
        for island in get_islands().islands
        for event in island.events
    }
    assert published == expected
