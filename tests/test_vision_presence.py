"""Unit tests for Otis AI Companion Phase 8: Multi-Modal Vision & Presence Intelligence."""

import asyncio
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.otis_ai.vision_manager import VisionPresenceManager


class MockArea:
    def __init__(self, area_id: str, name: str):
        self.id = area_id
        self.name = name


class MockEntityEntry:
    def __init__(self, entity_id: str, area_id: str | None = None):
        self.entity_id = entity_id
        self.area_id = area_id


class MockEntityState:
    def __init__(self, entity_id: str, state: str = "off", attributes: dict | None = None, last_changed: float | None = None):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}
        if last_changed:
            self.last_changed = datetime.fromtimestamp(last_changed, tz=timezone.utc)
        else:
            self.last_changed = datetime.now(tz=timezone.utc)


class TestVisionPresenceManager(unittest.TestCase):
    """Test suite for VisionPresenceManager."""

    def setUp(self):
        self.hass = MagicMock()
        self.hass.states = MagicMock()
        self.hass.bus = MagicMock()
        self.hass.bus.async_fire = MagicMock()
        self.hass.services = MagicMock()
        self.hass.services.async_call = AsyncMock()

    @patch("custom_components.otis_ai.vision_manager.ar.async_get")
    @patch("custom_components.otis_ai.vision_manager.er.async_get")
    def test_multi_sensor_occupancy_fusion(self, mock_er, mock_ar):
        """Test multi-sensor room occupancy fusion combining mmWave, PIR, media, and BLE."""
        area_reg = MagicMock()
        area_reg.async_list_areas.return_value = [
            MockArea("living_room", "Living Room"),
            MockArea("office", "Office"),
            MockArea("kitchen", "Kitchen"),
        ]
        mock_ar.return_value = area_reg

        ent_reg = MagicMock()
        ent_reg.entities = {
            "binary_sensor.living_room_mmwave": MockEntityEntry("binary_sensor.living_room_mmwave", "living_room"),
            "binary_sensor.office_pir_motion": MockEntityEntry("binary_sensor.office_pir_motion", "office"),
            "media_player.living_room_tv": MockEntityEntry("media_player.living_room_tv", "living_room"),
            "person.resident_1": MockEntityEntry("person.resident_1", "office"),
            "switch.kitchen_oven": MockEntityEntry("switch.kitchen_oven", "kitchen"),
            "device_tracker.kitchen_smart_plug": MockEntityEntry("device_tracker.kitchen_smart_plug", "kitchen"),
        }
        mock_er.return_value = ent_reg

        states = [
            MockEntityState("binary_sensor.living_room_mmwave", "on", {"device_class": "occupancy", "friendly_name": "Living Room Radar"}),
            MockEntityState("media_player.living_room_tv", "playing", {"friendly_name": "Living Room TV"}),
            MockEntityState("binary_sensor.office_pir_motion", "on", {"device_class": "motion", "friendly_name": "Office PIR"}),
            MockEntityState("person.resident_1", "office", {"friendly_name": "Alex"}),
            MockEntityState("switch.kitchen_oven", "off", {"friendly_name": "Kitchen Oven"}),
            MockEntityState("device_tracker.kitchen_smart_plug", "home", {"friendly_name": "Kitchen Plug Tracker"}),
        ]
        self.hass.states.async_all.return_value = states

        mgr = VisionPresenceManager(self.hass)
        res = asyncio.run(mgr.async_get_presence_states())

        self.assertIn("Living Room", res["occupied_areas"])
        self.assertIn("Office", res["occupied_areas"])
        self.assertIn("Kitchen", res["vacant_areas"])

        lr_room = res["rooms"]["living_room"]
        self.assertEqual(lr_room["status"], "occupied")
        self.assertGreaterEqual(lr_room["probability"], 0.90)
        self.assertTrue(lr_room["sensors"]["mmwave"]["active"])
        self.assertTrue(lr_room["sensors"]["media"]["playing"])

        off_room = res["rooms"]["office"]
        self.assertEqual(off_room["status"], "occupied")
        self.assertTrue(off_room["sensors"]["pir"]["active"])
        self.assertTrue(off_room["sensors"]["ble_beacon"]["active"])

        kit_room = res["rooms"]["kitchen"]
        self.assertEqual(kit_room["status"], "vacant")
        self.assertEqual(kit_room["probability"], 0.0)

    @patch("custom_components.otis_ai.vision_manager.ar.async_get")
    @patch("custom_components.otis_ai.vision_manager.er.async_get")
    def test_camera_discovery_and_snapshot_analysis(self, mock_er, mock_ar):
        """Test camera discovery and snapshot anomaly analysis."""
        area_reg = MagicMock()
        area_reg.async_list_areas.return_value = [MockArea("front_porch", "Front Porch")]
        mock_ar.return_value = area_reg

        ent_reg = MagicMock()
        ent_reg.entities = {
            "camera.doorbell": MockEntityEntry("camera.doorbell", "front_porch"),
            "camera.foyer_clear": MockEntityEntry("camera.foyer_clear", "foyer"),
            "camera.foyer_fluent": MockEntityEntry("camera.foyer_fluent", "foyer"),
            "camera.foyer_snapshots_fluent": MockEntityEntry("camera.foyer_snapshots_fluent", "foyer"),
            "camera.larry_poppins_saved_map": MockEntityEntry("camera.larry_poppins_saved_map", "living_room"),
        }
        mock_er.return_value = ent_reg

        states = [
            MockEntityState("camera.doorbell", "idle", {"friendly_name": "Front Doorbell Camera", "brand": "Reolink"}),
            MockEntityState("binary_sensor.doorbell_package", "on", {"friendly_name": "Doorbell Package"}),
            MockEntityState("camera.foyer_clear", "idle", {"friendly_name": "Clear"}),
            MockEntityState("camera.foyer_fluent", "idle", {"friendly_name": "Fluent"}),
            MockEntityState("camera.foyer_snapshots_fluent", "idle", {"friendly_name": "Snapshots fluent"}),
            MockEntityState("camera.larry_poppins_saved_map", "idle", {"friendly_name": "Larry Poppins Saved Map"}),
        ]
        self.hass.states.async_all.return_value = states
        self.hass.states.get.side_effect = lambda eid: next((s for s in states if s.entity_id == eid), None)

        mgr = VisionPresenceManager(self.hass)
        cams = asyncio.run(mgr.async_get_cameras())
        # Vacuum map excluded, Foyer multi-streams deduplicated to 1 (Fluent by default/fallback), Doorbell retained -> 2 total
        self.assertEqual(len(cams), 2)
        cam_eids = [c["entity_id"] for c in cams]
        self.assertIn("camera.doorbell", cam_eids)
        self.assertIn("camera.foyer_fluent", cam_eids)
        self.assertNotIn("camera.foyer_clear", cam_eids)
        self.assertNotIn("camera.larry_poppins_saved_map", cam_eids)
        self.assertTrue(cams[0]["is_doorbell"])

        analysis = asyncio.run(mgr.async_analyze_camera("camera.doorbell"))
        self.assertTrue(analysis["success"])
        audit = analysis["audit"]
        self.assertEqual(audit["status"], "attention_needed")
        self.assertIn("package", audit["detected_objects"])
        self.assertIn("Package delivery detected", audit["safety_assessment"])
        self.assertGreaterEqual(len(mgr.get_audit_history()), 1)

    @patch("custom_components.otis_ai.vision_manager.ar.async_get")
    @patch("custom_components.otis_ai.vision_manager.er.async_get")
    def test_contextual_presence_alerts(self, mock_er, mock_ar):
        """Test cross-domain contextual alerts (garage open while away, unattended heater in vacant room)."""
        area_reg = MagicMock()
        area_reg.async_list_areas.return_value = [
            MockArea("garage", "Garage"),
            MockArea("study", "Study"),
            MockArea("dining_room", "Dining Room"),
            MockArea("downstairs_bath", "Downstairs Bath"),
            MockArea("theater", "Theater"),
        ]
        mock_ar.return_value = area_reg

        ent_reg = MagicMock()
        ent_reg.entities = {
            "cover.garage_door": MockEntityEntry("cover.garage_door", "garage"),
            "switch.study_space_heater": MockEntityEntry("switch.study_space_heater", "study"),
            "lock.front_door": MockEntityEntry("lock.front_door", "front_porch"),
            "switch.theater_yamaha_enhancer": MockEntityEntry("switch.theater_yamaha_enhancer", "theater"),
            "switch.theater_led": MockEntityEntry("switch.theater_led", "theater"),
            "switch.theater_auto_update_enabled": MockEntityEntry("switch.theater_auto_update_enabled", "theater"),
        }
        mock_er.return_value = ent_reg

        # All residents away, garage door open, space heater left on in vacant study, theater switches on
        states = [
            MockEntityState("person.resident_1", "not_home", {"friendly_name": "Alex"}),
            MockEntityState("cover.garage_door", "open", {"device_class": "garage", "friendly_name": "Garage Door"}),
            MockEntityState("switch.study_space_heater", "on", {"friendly_name": "Study Space Heater"}),
            MockEntityState("switch.theater_yamaha_enhancer", "on", {"friendly_name": "Theater Yamaha Enhancer"}),
            MockEntityState("switch.theater_led", "on", {"friendly_name": "Theater LED"}),
            MockEntityState("switch.theater_auto_update_enabled", "on", {"friendly_name": "Theater Auto-update enabled"}),
            MockEntityState("lock.front_door", "unlocked", {"friendly_name": "Front Door Lock"}),
        ]
        self.hass.states.async_all.return_value = states

        mgr = VisionPresenceManager(self.hass)
        alerts = asyncio.run(mgr.async_evaluate_contextual_alerts())

        # Verify garage open while away alert
        garage_alert = next((a for a in alerts if "garage_open_away" in a["id"]), None)
        self.assertIsNotNone(garage_alert)
        self.assertEqual(garage_alert["priority"], "high")
        self.assertEqual(garage_alert["action_payload"]["service"], "cover.close_cover")

        # Verify unattended heater in vacant room alert
        heater_alert = next((a for a in alerts if "unattended" in a["id"]), None)
        self.assertIsNotNone(heater_alert)
        self.assertIn("Study", heater_alert["title"])
        self.assertEqual(heater_alert["action_payload"]["service"], "homeassistant.turn_off")

        # Verify Theater switches do NOT produce false positive appliance alerts in other rooms
        theater_alerts = [a for a in alerts if "theater" in a.get("id", "").lower() or "theater" in a.get("title", "").lower()]
        self.assertEqual(len(theater_alerts), 0, f"Unexpected theater false positive alerts: {theater_alerts}")

        # Verify no bogus unattended alerts in Dining Room or Downstairs Bath
        bogus_room_alerts = [a for a in alerts if "dining room" in a.get("title", "").lower() or "downstairs bath" in a.get("title", "").lower()]
        self.assertEqual(len(bogus_room_alerts), 0, f"Unexpected bogus alerts in vacant rooms: {bogus_room_alerts}")

        # Verify perimeter unlocked while away alert
        lock_alert = next((a for a in alerts if "unlocked" in a["id"]), None)
        self.assertIsNotNone(lock_alert)
        self.assertEqual(lock_alert["action_payload"]["service"], "lock.lock")

    def test_conversational_presence_and_camera_queries(self):
        """Test Assist conversational queries for presence and camera audits in OtisAIConversationAgent."""
        from custom_components.otis_ai import OtisAIConversationAgent

        entry = MagicMock()
        entry.options = {}
        entry.data = {}
        engine = MagicMock()
        manager = MagicMock()

        vision_manager = MagicMock()
        vision_manager.async_get_presence_states = AsyncMock(return_value={
            "occupied_areas": ["Living Room", "Office"],
            "likely_areas": [],
            "household_present": True,
        })
        vision_manager.async_get_cameras = AsyncMock(return_value=[
            {"entity_id": "camera.front_porch", "name": "Front Porch Camera", "is_doorbell": True}
        ])
        vision_manager.async_analyze_camera = AsyncMock(return_value={
            "success": True,
            "audit": {
                "name": "Front Porch Camera",
                "status": "normal",
                "summary": "Clear front walkway, no motion detected.",
                "safety_assessment": "Perimeter normal.",
                "detected_objects": [],
            }
        })

        agent = OtisAIConversationAgent(
            self.hass, entry, engine, manager, vision_manager=vision_manager
        )

        # 1. Presence question
        u1 = MagicMock()
        u1.text = "Who is in the house?"
        u1.conversation_id = "test_conv_pres"
        u1.create_response = MagicMock(return_value="mock_resp")
        asyncio.run(agent.async_process(u1))
        speech1 = u1.create_response.call_args[1]["speech"]
        self.assertIn("Living Room", speech1)
        self.assertIn("Office", speech1)

        # 2. Camera question
        u2 = MagicMock()
        u2.text = "Check security cameras"
        u2.conversation_id = "test_conv_pres"
        u2.create_response = MagicMock(return_value="mock_resp")
        asyncio.run(agent.async_process(u2))
        speech2 = u2.create_response.call_args[1]["speech"]
        self.assertIn("Front Porch Camera", speech2)
        self.assertIn("NORMAL", speech2)

    @patch("custom_components.otis_ai.vision_manager.ar.async_get")
    @patch("custom_components.otis_ai.vision_manager.er.async_get")
    def test_camera_stream_strategies(self, mock_er, mock_ar):
        """Test stream selection under Managed Proxy, High Efficiency, and High Definition strategies."""
        from custom_components.otis_ai.const import (
            DOMAIN,
            CONF_CAMERA_STREAM_STRATEGY,
            CAMERA_STRATEGY_MANAGED_PROXY,
            CAMERA_STRATEGY_HIGH_EFFICIENCY,
            CAMERA_STRATEGY_HIGH_DEFINITION,
        )

        area_reg = MagicMock()
        area_reg.async_list_areas.return_value = [MockArea("kitchen", "Kitchen")]
        mock_ar.return_value = area_reg

        ent_reg = MagicMock()
        ent_entry_proxy = MockEntityEntry("camera.kitchen_gateway", "kitchen")
        ent_entry_proxy.platform = "webrtc_proxy"
        ent_entry_fluent = MockEntityEntry("camera.kitchen_fluent", "kitchen")
        ent_entry_fluent.platform = "hardware_cam"
        ent_entry_clear = MockEntityEntry("camera.kitchen_clear", "kitchen")
        ent_entry_clear.platform = "hardware_cam"

        ent_reg.entities = {
            "camera.kitchen_gateway": ent_entry_proxy,
            "camera.kitchen_fluent": ent_entry_fluent,
            "camera.kitchen_clear": ent_entry_clear,
        }
        mock_er.return_value = ent_reg

        states = [
            MockEntityState("camera.kitchen_gateway", "idle", {"friendly_name": "Kitchen Gateway", "platform": "webrtc_proxy"}),
            MockEntityState("camera.kitchen_fluent", "idle", {"friendly_name": "Fluent", "platform": "hardware_cam"}),
            MockEntityState("camera.kitchen_clear", "idle", {"friendly_name": "Clear", "platform": "hardware_cam"}),
        ]
        self.hass.states.async_all.return_value = states

        # 1. Strategy = MANAGED_PROXY (Managed stream preferred)
        self.hass.data = {DOMAIN: {"entry_1": {"data": {CONF_CAMERA_STREAM_STRATEGY: CAMERA_STRATEGY_MANAGED_PROXY}}}}
        mgr_proxy = VisionPresenceManager(self.hass)
        cams_proxy = asyncio.run(mgr_proxy.async_get_cameras())
        self.assertEqual(len(cams_proxy), 1)
        self.assertEqual(cams_proxy[0]["entity_id"], "camera.kitchen_gateway")

        # 2. Strategy = HIGH_EFFICIENCY (Direct lightweight stream preferred)
        self.hass.data = {DOMAIN: {"entry_1": {"data": {CONF_CAMERA_STREAM_STRATEGY: CAMERA_STRATEGY_HIGH_EFFICIENCY}}}}
        mgr_fluent = VisionPresenceManager(self.hass)
        cams_fluent = asyncio.run(mgr_fluent.async_get_cameras())
        self.assertEqual(len(cams_fluent), 1)
        self.assertEqual(cams_fluent[0]["entity_id"], "camera.kitchen_fluent")

        # 3. Strategy = HIGH_DEFINITION (Direct HD stream preferred)
        self.hass.data = {DOMAIN: {"entry_1": {"data": {CONF_CAMERA_STREAM_STRATEGY: CAMERA_STRATEGY_HIGH_DEFINITION}}}}
        mgr_clear = VisionPresenceManager(self.hass)
        cams_clear = asyncio.run(mgr_clear.async_get_cameras())
        self.assertEqual(len(cams_clear), 1)
        self.assertEqual(cams_clear[0]["entity_id"], "camera.kitchen_clear")

        # 4. Legacy alias backwards compatibility ("frigate" -> MANAGED_PROXY)
        self.hass.data = {DOMAIN: {"entry_1": {"data": {CONF_CAMERA_STREAM_STRATEGY: "frigate"}}}}
        mgr_legacy = VisionPresenceManager(self.hass)
        cams_legacy = asyncio.run(mgr_legacy.async_get_cameras())
        self.assertEqual(cams_legacy[0]["entity_id"], "camera.kitchen_gateway")

    @patch("custom_components.otis_ai.vision_manager.ar.async_get")
    @patch("custom_components.otis_ai.vision_manager.er.async_get")
    def test_publish_fused_presence_and_tracking(self, mock_er, mock_ar):
        """Test publishing fused binary_sensor.otis_presence_<slug> entities and event listener tracking."""
        area_reg = MagicMock()
        area_reg.async_list_areas.return_value = [
            MockArea("living_room", "Living Room"),
            MockArea("kitchen", "Kitchen"),
        ]
        mock_ar.return_value = area_reg

        ent_reg = MagicMock()
        ent_reg.entities = {
            "binary_sensor.living_room_motion": MockEntityEntry("binary_sensor.living_room_motion", "living_room"),
            "light.kitchen_lights": MockEntityEntry("light.kitchen_lights", "kitchen"),
        }
        mock_er.return_value = ent_reg

        states = [
            MockEntityState("binary_sensor.living_room_motion", "on", {"device_class": "motion", "friendly_name": "LR Motion"}),
            MockEntityState("light.kitchen_lights", "off", {"friendly_name": "Kitchen Lights"}),
        ]
        self.hass.states.async_all.return_value = states
        published_states = {}

        def mock_async_set(entity_id, state, attributes=None):
            published_states[entity_id] = {"state": state, "attributes": attributes or {}}

        self.hass.states.async_set = mock_async_set

        mgr = VisionPresenceManager(self.hass)

        # 1. Test publishing fused presence states
        res = asyncio.run(mgr.async_publish_fused_presence_states())
        self.assertTrue(res["occupied_count"] >= 1)

        # Verify living room is published as "on"
        self.assertIn("binary_sensor.otis_presence_living_room", published_states)
        lr_state = published_states["binary_sensor.otis_presence_living_room"]
        self.assertEqual(lr_state["state"], "on")
        self.assertEqual(lr_state["attributes"]["device_class"], "occupancy")
        self.assertEqual(lr_state["attributes"]["area_id"], "living_room")

        # Verify kitchen is published as "off"
        self.assertIn("binary_sensor.otis_presence_kitchen", published_states)
        k_state = published_states["binary_sensor.otis_presence_kitchen"]
        self.assertEqual(k_state["state"], "off")

        # Verify global active household occupancy sensor
        self.assertIn("binary_sensor.otis_active_occupancy", published_states)
        self.assertEqual(published_states["binary_sensor.otis_active_occupancy"]["state"], "on")

        # 2. Test event tracking initialization
        mgr.async_start_presence_tracking()
        self.hass.bus.async_listen.assert_called_once()

        # Idempotent re-initialization
        mgr.async_start_presence_tracking()
        self.assertEqual(self.hass.bus.async_listen.call_count, 1)

    @patch("custom_components.otis_ai.vision_manager.ar.async_get")
    @patch("custom_components.otis_ai.vision_manager.er.async_get")
    def test_outdoor_suppression_and_sensorless_spatial_inference(self, mock_er, mock_ar):
        """Test outdoor false-positive suppression, sensorless room light/TV correlation, and sightline holds."""
        import time as _time
        from datetime import datetime, timezone

        now_ts = _time.time()
        recent_dt = datetime.fromtimestamp(now_ts - 30.0, tz=timezone.utc)
        old_dt = datetime.fromtimestamp(now_ts - 14400.0, tz=timezone.utc)  # 4 hours ago

        area_reg = MagicMock()
        area_reg.async_list_areas.return_value = [
            MockArea("hallway", "Hallway"),
            MockArea("study", "Study"),
            MockArea("dining_room", "Dining Room"),
            MockArea("backyard", "Backyard"),
        ]
        mock_ar.return_value = area_reg

        ent_reg = MagicMock()
        ent_reg.entities = {
            "binary_sensor.hallway_motion": MockEntityEntry("binary_sensor.hallway_motion", "hallway"),
            "light.study_lamp": MockEntityEntry("light.study_lamp", "study"),
            "light.dining_chandelier": MockEntityEntry("light.dining_chandelier", "dining_room"),
            "light.backyard_flood": MockEntityEntry("light.backyard_flood", "backyard"),
            "binary_sensor.backyard_motion": MockEntityEntry("binary_sensor.backyard_motion", "backyard"),
        }
        mock_er.return_value = ent_reg

        s_hall_motion = MockEntityState("binary_sensor.hallway_motion", "on", {"device_class": "motion"})
        s_study_light = MockEntityState("light.study_lamp", "on", {"friendly_name": "Study Lamp"})
        s_study_light.last_changed = recent_dt
        s_dining_light = MockEntityState("light.dining_chandelier", "on", {"friendly_name": "Dining Chandelier"})
        s_dining_light.last_changed = old_dt  # Forgotten static light
        s_backyard_light = MockEntityState("light.backyard_flood", "on", {"friendly_name": "Backyard Flood"})
        s_backyard_light.last_changed = recent_dt
        s_backyard_motion = MockEntityState("binary_sensor.backyard_motion", "on", {"device_class": "motion"})

        self.hass.states.async_all.return_value = [
            s_hall_motion,
            s_study_light,
            s_dining_light,
            s_backyard_light,
            s_backyard_motion,
        ]

        spatial_mock = MagicMock()
        spatial_mock.get_adjacent_areas.side_effect = lambda aid: ["hallway"] if aid in ("study", "dining_room") else []

        mgr = VisionPresenceManager(self.hass, spatial_manager=spatial_mock)
        res = asyncio.run(mgr.async_get_presence_states())

        # 1. Backyard is outdoor -> excluded from indoor occupied_areas / likely_areas
        self.assertTrue(res["rooms"]["backyard"]["is_outdoor"])
        self.assertNotIn("Backyard", res["occupied_areas"])
        self.assertNotIn("Backyard", res["likely_areas"])

        # 2. Study has no sensors, is adjacent to occupied Hallway, and light just turned on -> inferred likely_occupied
        self.assertTrue(res["rooms"]["study"]["is_sensorless"])
        self.assertTrue(res["rooms"]["study"]["spatial_entry_inferred"])
        self.assertEqual(res["rooms"]["study"]["inferred_from"], "hallway")
        self.assertEqual(res["rooms"]["study"]["status"], "likely_occupied")

        # 3. Dining Room has only a forgotten static light (4h old) -> remains vacant
        self.assertEqual(res["rooms"]["dining_room"]["status"], "vacant")
        self.assertFalse(res["rooms"]["dining_room"]["spatial_entry_inferred"])

        # 4. Camera sightline entry holds Dining Room even without fresh light, and exit clears it
        s_dining_light.state = "off"
        mgr._presence_cache_ts = 0.0
        mgr.record_camera_sightline_event("hallway", "dining_room", event_type="entry", subject="person")
        res_hold = asyncio.run(mgr.async_get_presence_states())
        self.assertEqual(res_hold["rooms"]["dining_room"]["status"], "likely_occupied")
        self.assertTrue(res_hold["rooms"]["dining_room"]["spatial_entry_inferred"])

        mgr._presence_cache_ts = 0.0
        mgr.record_camera_sightline_event("hallway", "dining_room", event_type="exit", subject="person")
        res_exit = asyncio.run(mgr.async_get_presence_states())
        self.assertEqual(res_exit["rooms"]["dining_room"]["status"], "vacant")

        # 5. Auto-derivation of indoor camera sightlines from floor plan / spatial graph
        s_hall_cam = MockEntityState("camera.hallway_cam", "idle", {"friendly_name": "Hallway Camera"})
        ent_reg.entities["camera.hallway_cam"] = MockEntityEntry("camera.hallway_cam", "hallway")
        self.hass.states.async_all.return_value = [
            s_hall_cam,
            s_hall_motion,
            s_study_light,
            s_dining_light,
            s_backyard_light,
            s_backyard_motion,
        ]
        spatial_mock.get_adjacent_areas.side_effect = (
            lambda aid: ["study", "dining_room", "backyard"] if aid == "hallway" else ["hallway"]
        )
        mgr._sightlines_synced_ts = 0.0
        mgr._presence_cache_ts = 0.0
        asyncio.run(mgr.async_get_presence_states())
        self.assertIn("hallway", mgr._auto_sightlines)
        self.assertIn("study", mgr._auto_sightlines["hallway"])
        self.assertIn("dining_room", mgr._auto_sightlines["hallway"])
        # Outdoor areas must be excluded from indoor camera sightlines
        self.assertNotIn("backyard", mgr._auto_sightlines["hallway"])
        # Because Study entered via Hallway camera sightline + fresh light, hold is auto-engaged
        self.assertIn("study", mgr._active_room_holds)


if __name__ == "__main__":
    unittest.main()
