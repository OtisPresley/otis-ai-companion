"""Unit tests for Phase 5 Step 1: Real-time Camera Snapshot Analysis and Perimeter Anomaly Detection."""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.otis_ai.const import (
    DEFAULT_LOCAL_VISION_MODEL,
    DOMAIN,
    SERVICE_AUDIT_PERIMETER,
    SERVICE_GET_INTRUDER_TRACKS,
)
from custom_components.otis_ai.local_llm import (
    LocalLLMManager,
    normalize_image_base64,
)
from custom_components.otis_ai.local_llm_manager import (
    LocalLLMManager as ReexportedLocalLLMManager,
)
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
    def __init__(self, entity_id: str, state: str = "off", attributes: dict | None = None):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}


class TestPerimeterVisionAnalysis(unittest.TestCase):
    """Test suite for Phase 5 Step 1 Perimeter Vision & Anomaly Detection."""

    def setUp(self):
        self.hass = MagicMock()
        self.hass.states = MagicMock()
        self.hass.bus = MagicMock()
        self.hass.bus.async_fire = MagicMock()
        self.hass.services = MagicMock()
        self.hass.services.async_call = AsyncMock()

    def test_reexported_module_parity(self):
        """Test that local_llm_manager re-exports LocalLLMManager seamlessly."""
        self.assertIs(LocalLLMManager, ReexportedLocalLLMManager)

    def test_normalize_image_base64(self):
        """Test normalization of raw base64 and data URI strings."""
        raw = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        data_uri = f"data:image/png;base64,{raw}"

        b64_from_raw, uri_from_raw = normalize_image_base64(raw)
        self.assertEqual(b64_from_raw, raw)
        self.assertEqual(uri_from_raw, f"data:image/jpeg;base64,{raw}")

        b64_from_uri, uri_from_uri = normalize_image_base64(data_uri)
        self.assertEqual(b64_from_uri, raw)
        self.assertEqual(uri_from_uri, data_uri)

    def test_analyze_vision_no_image(self):
        """Test analyze_vision returns error when no image data is passed."""
        llm = LocalLLMManager(self.hass)
        res = asyncio.run(llm.async_analyze_vision())
        self.assertFalse(res["success"])
        self.assertIn("No image data provided", res["error"])

    def test_analyze_vision_ollama_structured_json(self):
        """Test multimodal vision analysis with Ollama returning valid JSON."""
        llm = LocalLLMManager(self.hass, url="http://10.0.12.228:11434", model="llama3.2-vision:latest")

        vision_json = {
            "detected_objects": ["person", "vehicle"],
            "perimeter_zone": "driveway",
            "anomaly_detected": True,
            "anomaly_type": "loitering",
            "severity": "high",
            "confidence": 0.92,
            "summary": "Unknown individual loitering next to vehicle in driveway.",
            "recommended_action": "turn_on_floodlights",
        }

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "message": {"content": json.dumps(vision_json)},
            "eval_count": 80,
            "prompt_eval_count": 150,
            "eval_duration": 1_000_000_000,
        })

        mock_session = MagicMock()
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)

        fake_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        with patch("custom_components.otis_ai.local_llm.async_get_clientsession", return_value=mock_session):
            res = asyncio.run(llm.async_analyze_vision(image_base64=fake_b64))

            self.assertTrue(res["success"])
            self.assertEqual(res["perimeter_zone"], "driveway")
            self.assertTrue(res["anomaly_detected"])
            self.assertEqual(res["anomaly_type"], "loitering")
            self.assertEqual(res["severity"], "high")
            self.assertEqual(res["confidence"], 0.92)
            self.assertEqual(res["recommended_action"], "turn_on_floodlights")
            self.assertIn("person", res["detected_objects"])
            self.assertIn("vehicle", res["detected_objects"])

    def test_analyze_vision_heuristic_fallback(self):
        """Test parsing of unstructured free-text responses from local vision models."""
        llm = LocalLLMManager(self.hass)

        raw_text = "I observe an intruder attempting a break-in at the backyard gate. Motion is suspicious."
        parsed = llm._parse_vision_response(raw_text)

        self.assertTrue(parsed["anomaly_detected"])
        self.assertEqual(parsed["anomaly_type"], "perimeter_breach")
        self.assertEqual(parsed["severity"], "critical")
        self.assertEqual(parsed["perimeter_zone"], "backyard")
        self.assertEqual(parsed["recommended_action"], "notify_security")

    def test_vision_model_auto_selection(self):
        """Test auto-discovery and selection of installed vision model when standard model is configured."""
        llm = LocalLLMManager(self.hass, model="qwen2.5:3b")

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "models": [{"name": "qwen2.5:3b"}, {"name": "llama3.2-vision:11b"}]
        })

        mock_session = MagicMock()
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("custom_components.otis_ai.local_llm.async_get_clientsession", return_value=mock_session):
            with patch.object(llm, "async_generate", new_callable=AsyncMock) as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "response": '{"detected_objects": ["package"], "anomaly_detected": false, "severity": "normal"}',
                    "model": "llama3.2-vision:11b",
                }
                res = asyncio.run(llm.async_analyze_vision(image_base64="fake_b64"))
                self.assertTrue(res["success"])
                # Should have picked llama3.2-vision:11b from installed models
                mock_gen.assert_called_once()
                self.assertEqual(mock_gen.call_args[1]["model"], "llama3.2-vision:11b")

    def test_vision_manager_analyze_camera_with_llm(self):
        """Test VisionPresenceManager invoking LocalLLMManager for camera snapshot analysis."""
        llm = MagicMock()
        llm.async_analyze_vision = AsyncMock(return_value={
            "success": True,
            "model": DEFAULT_LOCAL_VISION_MODEL,
            "detected_objects": ["person"],
            "perimeter_zone": "front_door",
            "anomaly_detected": True,
            "anomaly_type": "prowler",
            "severity": "high",
            "confidence": 0.88,
            "summary": "Prowler identified near front entrance late at night.",
            "recommended_action": "turn_on_floodlights",
        })

        vm = VisionPresenceManager(self.hass, local_llm_manager=llm)

        cam_state = MockEntityState("camera.front_door", "idle", {"friendly_name": "Front Door Camera"})
        self.hass.states.get.return_value = cam_state

        mock_img = MagicMock()
        mock_img.content = b"fake_jpeg_bytes"
        mock_img.content_type = "image/jpeg"

        mock_camera_mod = MagicMock()
        mock_camera_mod.async_get_image = AsyncMock(return_value=mock_img)

        with patch.dict("sys.modules", {"homeassistant.components.camera": mock_camera_mod}):
            res = asyncio.run(vm.async_analyze_camera("camera.front_door"))

            self.assertTrue(res["success"])
            audit = res["audit"]
            self.assertEqual(audit["status"], "anomaly")
            self.assertTrue(audit["anomaly_detected"])
            self.assertEqual(audit["severity"], "high")
            self.assertEqual(audit["confidence"], 0.88)
            self.assertTrue(audit["llm_used"])
            self.assertEqual(audit["llm_model"], DEFAULT_LOCAL_VISION_MODEL)

            # Check that bus events were fired
            self.hass.bus.async_fire.assert_any_call("otis_ai_perimeter_anomaly_detected", audit)
            self.hass.bus.async_fire.assert_any_call("otis_ai_vision_analysis_completed", audit)

            # Check sensor.otis_perimeter_sentinel was updated to warning/critical
            self.hass.states.async_set.assert_called()
            sentinel_call = [
                c for c in self.hass.states.async_set.call_args_list
                if c[0][0] == "sensor.otis_perimeter_sentinel"
            ]
            self.assertTrue(len(sentinel_call) > 0)
            self.assertEqual(sentinel_call[-1][0][1], "warning")
            self.assertEqual(sentinel_call[-1][0][2]["latest_camera"], "camera.front_door")

    def test_vision_manager_fallback_when_llm_fails(self):
        """Test graceful fallback to sensor telemetry if Local LLM throws exception."""
        llm = MagicMock()
        llm.async_analyze_vision = AsyncMock(side_effect=Exception("Connection refused to Ollama"))

        vm = VisionPresenceManager(self.hass, local_llm_manager=llm)

        cam_state = MockEntityState("camera.driveway", "idle", {"friendly_name": "Driveway Camera"})
        sensor_state = MockEntityState("binary_sensor.driveway_vehicle", "on", {"friendly_name": "Driveway Vehicle"})

        self.hass.states.get.return_value = cam_state
        self.hass.states.async_all.return_value = [cam_state, sensor_state]

        mock_img = MagicMock()
        mock_img.content = b"fake_jpeg_bytes"

        mock_camera_mod = MagicMock()
        mock_camera_mod.async_get_image = AsyncMock(return_value=mock_img)

        with patch.dict("sys.modules", {"homeassistant.components.camera": mock_camera_mod}):
            res = asyncio.run(vm.async_analyze_camera("camera.driveway"))

            self.assertTrue(res["success"])
            audit = res["audit"]
            self.assertFalse(audit["llm_used"])
            self.assertIn("vehicle", audit["detected_objects"])
            self.assertEqual(audit["status"], "motion_detected")

    @patch("custom_components.otis_ai.vision_manager.ar.async_get")
    @patch("custom_components.otis_ai.vision_manager.er.async_get")
    def test_audit_perimeter_concurrent_scan(self, mock_er, mock_ar):
        """Test async_audit_perimeter scanning multiple perimeter cameras concurrently."""
        area_reg = MagicMock()
        area_reg.async_list_areas.return_value = [
            MockArea("driveway_area", "Driveway"),
            MockArea("porch_area", "Front Porch"),
        ]
        mock_ar.return_value = area_reg

        ent_reg = MagicMock()
        ent_reg.entities = {
            "camera.driveway_cam": MockEntityEntry("camera.driveway_cam", "driveway_area"),
            "camera.porch_cam": MockEntityEntry("camera.porch_cam", "porch_area"),
        }
        mock_er.return_value = ent_reg

        states = [
            MockEntityState("camera.driveway_cam", "idle", {"friendly_name": "Driveway Camera"}),
            MockEntityState("camera.porch_cam", "idle", {"friendly_name": "Porch Camera"}),
        ]
        self.hass.states.async_all.return_value = states
        self.hass.states.get.side_effect = lambda eid: next((s for s in states if s.entity_id == eid), None)

        vm = VisionPresenceManager(self.hass)

        # Mock async_analyze_camera on vm
        async def mock_analyze(cam_id, prompt=None, context=None, model=None):
            is_driveway = "driveway" in cam_id
            return {
                "success": True,
                "audit": {
                    "camera": cam_id,
                    "anomaly_detected": is_driveway,
                    "severity": "high" if is_driveway else "normal",
                    "detected_objects": ["person"] if is_driveway else [],
                },
            }

        with patch.object(vm, "async_analyze_camera", side_effect=mock_analyze):
            report = asyncio.run(vm.async_audit_perimeter())

            self.assertTrue(report["success"])
            self.assertEqual(report["total_cameras_scanned"], 2)
            self.assertEqual(report["anomalies_detected"], 1)
            self.assertEqual(len(report["anomalies"]), 1)
            self.assertEqual(report["anomalies"][0]["camera"], "camera.driveway_cam")

    def test_service_constants_defined(self):
        """Test service constants are properly defined."""
        self.assertEqual(DOMAIN, "otis_ai")
        self.assertEqual(SERVICE_AUDIT_PERIMETER, "audit_perimeter")
        self.assertEqual(SERVICE_GET_INTRUDER_TRACKS, "get_intruder_tracks")

    def test_multicamera_spatial_triangulation_and_kinematics(self):
        """Test multi-camera correlation, kinematics calculation, and next-area prediction."""
        mock_spatial = MagicMock()
        mock_spatial.get_adjacent_areas.side_effect = lambda a: {
            "driveway": ["front_porch", "garage"],
            "front_porch": ["front_door", "driveway", "foyer"],
            "front_door": ["foyer", "front_porch"],
        }.get(a, [])

        vm = VisionPresenceManager(self.hass, spatial_manager=mock_spatial)

        # 1. Detection at Camera 1 (driveway)
        audit_1 = {
            "id": "audit_1",
            "camera": "camera.driveway",
            "name": "Driveway Camera",
            "timestamp": "2026-11-04T15:00:00",
            "detected_objects": ["person"],
            "perimeter_zone": "driveway",
            "anomaly_detected": True,
            "anomaly_type": "loitering",
            "severity": "medium",
            "confidence": 0.90,
        }
        track_1 = vm.process_visual_detection(audit_1)
        self.assertIsNotNone(track_1)
        self.assertEqual(track_1["status"], "active")
        self.assertEqual(track_1["threat_level"], "suspicious")
        self.assertEqual(len(track_1["trajectory"]), 1)
        self.assertEqual(track_1["cameras_involved"], ["camera.driveway"])
        self.hass.bus.async_fire.assert_any_call("otis_ai_intruder_track_created", track_1)

        # 2. Correlated detection at Camera 2 (front porch) 15 seconds later
        audit_2 = {
            "id": "audit_2",
            "camera": "camera.front_porch",
            "name": "Front Porch Camera",
            "timestamp": "2026-11-04T15:00:15",
            "detected_objects": ["person"],
            "perimeter_zone": "doorstep",
            "anomaly_detected": True,
            "anomaly_type": "prowler",
            "severity": "high",
            "confidence": 0.95,
        }
        track_2 = vm.process_visual_detection(audit_2)
        self.assertIsNotNone(track_2)
        # Should correlate into same track ID
        self.assertEqual(track_2["track_id"], track_1["track_id"])
        self.assertEqual(len(track_2["trajectory"]), 2)
        self.assertEqual(track_2["cameras_involved"], ["camera.driveway", "camera.front_porch"])
        self.assertEqual(track_2["threat_level"], "intruder")  # Escalated from suspicious to intruder
        self.assertGreater(track_2["velocity"]["speed"], 0.0)
        self.assertIn("NE", track_2["velocity"]["heading_dir"])
        self.assertIn("front_porch", track_2["current_area"])
        self.hass.bus.async_fire.assert_any_call("otis_ai_intruder_track_updated", track_2)

        # Check sensor.otis_intruder_tracks state published as "tracking"
        sentinel_calls = [
            c for c in self.hass.states.async_set.call_args_list
            if c[0][0] == "sensor.otis_intruder_tracks"
        ]
        self.assertTrue(len(sentinel_calls) > 0)
        self.assertEqual(sentinel_calls[-1][0][1], "tracking")
        self.assertEqual(sentinel_calls[-1][0][2]["active_tracks_count"], 1)

    def test_intruder_track_timeout_expiration(self):
        """Test track transitions from active to departed after timeout."""
        vm = VisionPresenceManager(self.hass)

        audit = {
            "camera": "camera.backyard_gate",
            "detected_objects": ["person"],
            "perimeter_zone": "gate",
            "severity": "critical",
            "anomaly_detected": True,
            "anomaly_type": "perimeter_breach",
        }
        track = vm.process_visual_detection(audit)
        self.assertEqual(track["threat_level"], "critical")
        self.assertEqual(track["status"], "active")

        # Age the track artificially past 180 seconds
        track["last_seen_ts"] = track["last_seen_ts"] - 200

        # Trigger cleanup
        tracks_res = vm.get_intruder_tracks()
        # Active tracks should exclude aged track once next detection processes or status checked
        vm.process_visual_detection({
            "camera": "camera.driveway",
            "detected_objects": ["vehicle"],
            "severity": "normal",
        })
        self.assertEqual(track["status"], "departed")

    def test_audio_follow_disabled_by_user_rules_and_entity_toggle(self):
        """Test Audio Follow can be disabled by rules manager and entity toggle for Command Center users."""
        from custom_components.otis_ai.audio_manager import AudioHandoffManager

        rules_mgr = MagicMock()
        rules_mgr.get_rules.return_value = {"audio_follow_enabled": False}

        audio_mgr = AudioHandoffManager(self.hass, rules_manager=rules_mgr)

        intent = {
            "source_area": "living_room",
            "target_area": "kitchen",
            "confidence": 0.85,
        }

        # 1. Disabled via rules_manager
        res1 = asyncio.run(audio_mgr.async_process_spatial_audio_migration(intent))
        self.assertIsNone(res1)

        # 2. Enabled in rules_manager, but disabled via Command Center toggle entity
        rules_mgr.get_rules.return_value = {"audio_follow_enabled": True}
        toggle_state = MockEntityState("input_boolean.otis_audio_follow", "off")
        self.hass.states.get.side_effect = lambda eid: toggle_state if eid == "input_boolean.otis_audio_follow" else None

        res2 = asyncio.run(audio_mgr.async_process_spatial_audio_migration(intent))
        self.assertIsNone(res2)

    def test_synthesize_visual_alert_summary_personas(self) -> None:
        """Verify conversational summary generation tailored to household personas and kinematics."""
        vm = VisionPresenceManager(self.hass)
        mock_audio = MagicMock()
        mock_rules = MagicMock()
        mock_audio.rules_manager = mock_rules
        vm.audio_manager = mock_audio

        audit_entry = {
            "camera": "camera.driveway",
            "camera_name": "Driveway Camera",
            "perimeter_zone": "driveway",
            "detected_objects": ["person"],
            "severity": "critical",
            "confidence": 0.95,
            "summary": "Unknown individual walking up the driveway",
        }
        track = {
            "track_id": "trk_test_1",
            "cardinal_heading": "North-East",
            "velocity": 1.5,
            "predicted_next_area": "front_porch",
            "threat_level": "critical",
        }

        # Butler persona
        mock_rules.get_rules.return_value = {"persona": "butler", "tone": "formal"}
        summary_butler = asyncio.run(vm.async_synthesize_visual_alert_summary(audit_entry, track=track))
        self.assertIn("Security alert", summary_butler)
        self.assertIn("driveway", summary_butler.lower())
        self.assertIn("north-east", summary_butler.lower())

        # Minimalist persona
        mock_rules.get_rules.return_value = {"persona": "minimalist", "tone": "concise"}
        summary_mini = asyncio.run(vm.async_synthesize_visual_alert_summary(audit_entry, track=track))
        self.assertTrue(summary_mini.startswith("Alert:"))
        self.assertIn("Person", summary_mini)

        # Concierge persona
        mock_rules.get_rules.return_value = {"persona": "concierge", "tone": "friendly"}
        summary_concierge = asyncio.run(vm.async_synthesize_visual_alert_summary(audit_entry, track=track))
        self.assertIn("Otis detected person", summary_concierge)

    def test_dispatch_visual_alert_voice_with_ducking_and_cooldown(self) -> None:
        """Verify proactive voice dispatch with spatial ducking, occupancy targeting, and anti-spam cooldown."""
        vm = VisionPresenceManager(self.hass)
        mock_audio = MagicMock()
        mock_rules = MagicMock()
        mock_rules.get_rules.return_value = {"preferred_speaker": "living_room"}
        mock_audio.rules_manager = mock_rules
        mock_audio.is_quiet_hours_active.return_value = (False, 25, "living_room")
        mock_audio.async_notify_voice = AsyncMock(return_value={"success": True})
        vm.audio_manager = mock_audio

        audit_entry = {
            "camera": "camera.front_porch",
            "perimeter_zone": "front_porch",
            "detected_objects": ["person"],
            "severity": "high",
            "confidence": 0.92,
        }

        # 1. First dispatch succeeds
        res1 = asyncio.run(vm.async_dispatch_visual_alert_voice(audit_entry))
        self.assertTrue(res1["dispatched"])
        mock_audio.async_notify_voice.assert_called_once()

        # 2. Immediate second dispatch is suppressed by 45s cooldown
        res2 = asyncio.run(vm.async_dispatch_visual_alert_voice(audit_entry))
        self.assertFalse(res2["dispatched"])
        self.assertEqual(res2["reason"], "cooldown_active")

        # 3. Force bypasses cooldown
        res3 = asyncio.run(vm.async_dispatch_visual_alert_voice(audit_entry, force=True))
        self.assertTrue(res3["dispatched"])

    def test_media_studio_view_contains_audio_follow_switch(self) -> None:
        """Verify Media Studio view automatically includes Autonomous Spatial Audio Follow-Me switch card."""
        from custom_components.otis_ai.dashboard_manager import DashboardManager

        dm = DashboardManager(self.hass)
        media_cards = dm._build_media_view_cards(None)

        # Ensure an entities card with switch.otis_audio_follow is generated
        follow_cards = [
            c for c in media_cards
            if c.get("type") == "entities" and any(
                e.get("entity") == "switch.otis_audio_follow" for e in c.get("entities", [])
            )
        ]
        self.assertEqual(len(follow_cards), 1)
        self.assertEqual(follow_cards[0]["title"], "Autonomous Spatial Audio Follow-Me")

    def test_voice_announcements_switch_and_suppression(self) -> None:
        """Verify voice alerts are completely silenced when switch.otis_voice_announcements or rules are disabled."""
        vm = VisionPresenceManager(self.hass)
        mock_audio = MagicMock()
        mock_rules = MagicMock()
        mock_rules.get_rules.return_value = {
            "voice_announcements_enabled": False,
            "preferred_speaker": "living_room",
        }
        mock_audio.rules_manager = mock_rules
        mock_audio.is_quiet_hours_active.return_value = (False, 25, "living_room")
        mock_audio.async_notify_voice = AsyncMock(return_value={"success": True})
        vm.audio_manager = mock_audio

        audit_entry = {
            "camera": "camera.front_porch",
            "perimeter_zone": "front_porch",
            "detected_objects": ["person"],
            "severity": "high",
            "confidence": 0.95,
        }

        # Suppressed by rules toggle
        res = asyncio.run(vm.async_dispatch_visual_alert_voice(audit_entry))
        self.assertFalse(res["dispatched"])
        self.assertEqual(res["reason"], "voice_announcements_disabled")
        mock_audio.async_notify_voice.assert_not_called()

        # Suppressed by entity state off
        mock_rules.get_rules.return_value = {"voice_announcements_enabled": True}
        mock_switch = MagicMock()
        mock_switch.state = "off"
        self.hass.states.get.return_value = mock_switch

        res2 = asyncio.run(vm.async_dispatch_visual_alert_voice(audit_entry))
        self.assertFalse(res2["dispatched"])
        self.assertEqual(res2["reason"], "voice_announcements_disabled")

    def test_benign_passerby_and_delivery_filtering(self) -> None:
        """Verify delivery couriers and sidewalk passersby do not trigger scary intruder voice announcements."""
        vm = VisionPresenceManager(self.hass)
        mock_audio = MagicMock()
        mock_rules = MagicMock()
        mock_rules.get_rules.return_value = {
            "voice_announcements_enabled": True,
            "voice_filter_passersby": True,
            "preferred_speaker": "living_room",
        }
        mock_audio.rules_manager = mock_rules
        mock_audio.is_quiet_hours_active.return_value = (False, 25, "living_room")
        mock_audio.async_notify_voice = AsyncMock(return_value={"success": True})
        vm.audio_manager = mock_audio
        self.hass.states.get.return_value = None

        # Delivery courier alert
        delivery_entry = {
            "camera": "camera.front_porch",
            "perimeter_zone": "front_porch",
            "detected_objects": ["person", "package"],
            "summary": "Amazon delivery driver dropped off a package at front porch",
            "severity": "low",
            "confidence": 0.88,
        }
        res = asyncio.run(vm.async_dispatch_visual_alert_voice(delivery_entry))
        self.assertFalse(res["dispatched"])
        self.assertEqual(res["reason"], "suppressed_benign_passerby")

        # Pedestrian walking on sidewalk
        pedestrian_entry = {
            "camera": "camera.driveway",
            "perimeter_zone": "driveway",
            "detected_objects": ["person"],
            "summary": "Pedestrian walking past on sidewalk",
            "severity": "low",
            "confidence": 0.85,
        }
        res2 = asyncio.run(vm.async_dispatch_visual_alert_voice(pedestrian_entry))
        self.assertFalse(res2["dispatched"])
        self.assertEqual(res2["reason"], "suppressed_benign_passerby")

    def test_security_view_contains_voice_announcements_switch(self) -> None:
        """Verify Security Center subview includes Proactive Security Voice Announcements control card."""
        from custom_components.otis_ai.dashboard_manager import DashboardManager

        dm = DashboardManager(self.hass)
        sec_cards = dm._build_security_view_cards(None)

        voice_cards = [
            c for c in sec_cards
            if c.get("type") == "entities" and any(
                e.get("entity") == "switch.otis_voice_announcements" for e in c.get("entities", [])
            )
        ]
        self.assertEqual(len(voice_cards), 1)
        self.assertEqual(voice_cards[0]["title"], "Proactive Security Voice Announcements")

    def test_audio_follow_person_attribution_mismatch_and_match(self) -> None:
        """Verify audio follow-me binds playback to initiator and prevents migration for other household members."""
        from custom_components.otis_ai.audio_manager import AudioHandoffManager

        hass = MagicMock()
        hass.states = MagicMock()
        hass.states.get.return_value = None
        am = AudioHandoffManager(hass)

        # Mock active zones
        am.async_get_active_media_zones = AsyncMock(return_value={
            "matrix_zones": [
                {"entity_id": "media_player.living_room", "area_id": "living_room", "state": "playing", "volume_level": 0.4},
                {"entity_id": "media_player.kitchen", "area_id": "kitchen", "state": "idle", "volume_level": 0.3},
            ],
            "other_players": [],
            "tv_cinema_players": [],
        })
        am.async_audio_handoff = AsyncMock(return_value={"success": True, "target_player": "media_player.kitchen"})

        # Record media playback session owned by "person.resident_primary"
        am.record_media_session_owner(
            player_entity_id="media_player.living_room",
            person_id="person.resident_primary",
            area_id="living_room",
        )

        # 1. Other family member ("person.alex") moves from living room to kitchen -> Migration skipped!
        intent_other = {
            "intent": "room_migration",
            "source_area": "living_room",
            "target_area": "kitchen",
            "confidence": 0.85,
            "person_id": "person.alex",
        }
        res_other = asyncio.run(am.async_process_spatial_audio_migration(intent_other))
        self.assertIsNotNone(res_other)
        self.assertFalse(res_other["migrated"])
        self.assertEqual(res_other["reason"], "user_mismatch")
        am.async_audio_handoff.assert_not_called()

        # 2. Owner ("person.resident_primary") moves from living room to kitchen -> Audio follows!
        intent_owner = {
            "intent": "room_migration",
            "source_area": "living_room",
            "target_area": "kitchen",
            "confidence": 0.85,
            "person_id": "person.resident_primary",
        }
        res_owner = asyncio.run(am.async_process_spatial_audio_migration(intent_owner))
        self.assertIsNotNone(res_owner)
        self.assertEqual(res_owner["status"], "following")
        am.async_audio_handoff.assert_called_once()
        # Session owner transferred to target player
        self.assertEqual(
            am.get_media_session_owner("media_player.kitchen")["person_id"],
            "person.resident_primary",
        )

    def test_confirm_person_identity_profile_calibration(self) -> None:
        """Verify confirm_person_identity calibrates confidence scores and training samples."""
        from custom_components.otis_ai.rules_manager import BehavioralRulesManager

        hass = MagicMock()
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value={})
        mock_store.async_save = AsyncMock(return_value=None)

        with patch("custom_components.otis_ai.rules_manager.Store", return_value=mock_store):
            rm = BehavioralRulesManager(hass)
            # 1. Positive confirmation
            res1 = asyncio.run(rm.async_confirm_person_identity(
                person_id="person.resident_primary",
                track_id="trk_001",
                label="Jordan",
                confirmed=True,
            ))
            self.assertTrue(res1["success"])
            prof1 = res1["profile"]
            self.assertEqual(prof1["samples"], 1)
            self.assertEqual(prof1["confidence"], 0.60)
            self.assertIn("trk_001", prof1["tracks"])

            # 2. Second positive confirmation boosts confidence further
            res2 = asyncio.run(rm.async_confirm_person_identity(
                person_id="person.resident_primary",
                track_id="trk_002",
                confirmed=True,
            ))
            self.assertEqual(res2["profile"]["samples"], 2)
            self.assertEqual(res2["profile"]["confidence"], 0.70)
            self.assertEqual(len(res2["profile"]["tracks"]), 2)
