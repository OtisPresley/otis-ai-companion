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
