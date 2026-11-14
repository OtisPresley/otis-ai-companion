"""Tests for Proactive Feed snapshot classification, ignore/dismiss isolation, and bounding boxes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.otis_ai.rules_manager import BehavioralRulesManager
from custom_components.otis_ai.vision_manager import VisionPresenceManager


class _FakeStore:
    def __init__(self, data=None):
        self.data = data

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = dict(data)


def _make_hass():
    hass = MagicMock()
    hass.data = {}
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.states = MagicMock()
    return hass


@pytest.mark.asyncio
async def test_confirm_person_identity_records_classified_snapshot_and_unignores():
    hass = _make_hass()
    rm = BehavioralRulesManager(hass)
    rm._store = _FakeStore(
        {
            "dismissed_recommendation_ids": ["verify_room_entry_backyard_abc123"],
            "classified_snapshots": [],
        }
    )
    await rm.async_load()

    res = await rm.async_confirm_person_identity(
        person_id="person.jamie",
        label="Jamie",
        confirmed=True,
        visual_features={
            "area": "backyard",
            "area_name": "Backyard",
            "snapshot_key": "abc123",
            "suggestion_id": "verify_room_entry_backyard_abc123",
        },
    )

    assert res["success"] is True
    assert "abc123" in rm.get_rules()["classified_snapshots"]
    assert "verify_room_entry_backyard_abc123" not in rm.get_dismissed_recommendations()


@pytest.mark.asyncio
async def test_confirm_person_identity_unknown_animal_records_classified_snapshot():
    hass = _make_hass()
    rm = BehavioralRulesManager(hass)
    rm._store = _FakeStore({"classified_snapshots": []})
    await rm.async_load()

    res = await rm.async_confirm_person_identity(
        person_id="unknown_animal",
        label="Unknown Animal",
        confirmed=True,
        visual_features={
            "area": "backyard",
            "snapshot_key": "cat_snap_99",
            "suggestion_id": "verify_room_entry_backyard_cat_snap_99",
        },
    )

    assert res["success"] is True
    assert "cat_snap_99" in rm.get_rules()["classified_snapshots"]


@pytest.mark.asyncio
async def test_vision_detect_snapshot_bbox_reads_attribute_and_caches():
    hass = _make_hass()
    hass.states.get = MagicMock(
        return_value=SimpleNamespace(
            entity_id="image.front_doorbell_fluent_dog",
            state="2026-11-13T15:24:00+00:00",
            attributes={"box_2d": [520, 210, 780, 410]},
        )
    )
    vm = VisionPresenceManager(hass)

    bbox = await vm.async_detect_snapshot_bbox(
        "image.front_doorbell_fluent_dog",
        detection_label="Dog",
        snapshot_key="snap_key_1",
    )

    assert bbox == {
        "ymin": 520,
        "xmin": 210,
        "ymax": 780,
        "xmax": 410,
        "label": "Dog",
    }

    # Second call should hit cache even if state disappears
    hass.states.get = MagicMock(return_value=None)
    cached = await vm.async_detect_snapshot_bbox(
        "image.front_doorbell_fluent_dog",
        detection_label="Dog",
        snapshot_key="snap_key_1",
    )
    assert cached == bbox
