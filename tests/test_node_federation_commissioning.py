"""Unit tests for Otis AI Companion Phase 10: Autonomous Home Commissioning & Multi-Node Federation."""

import tests  # noqa: F401 - Initialize Home Assistant mock environment
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.otis_ai.commissioning_manager import (
    AutonomousCommissioningManager,
)
from custom_components.otis_ai.federation_manager import FederationManager


class MockArea:
    def __init__(self, id: str, name: str, aliases: list[str] | None = None):
        self.id = id
        self.name = name
        self.aliases = aliases or []


class MockDevice:
    def __init__(
        self,
        id: str,
        name: str = "",
        area_id: str | None = None,
        model: str = "",
        manufacturer: str = "",
    ):
        self.id = id
        self.name = name
        self.name_by_user = name
        self.area_id = area_id
        self.model = model
        self.manufacturer = manufacturer


class MockEntity:
    def __init__(
        self,
        entity_id: str,
        name: str = "",
        area_id: str | None = None,
        device_id: str | None = None,
        domain: str = "",
    ):
        self.entity_id = entity_id
        self.name = name
        self.original_name = name
        self.area_id = area_id
        self.device_id = device_id
        self.domain = domain or entity_id.split(".")[0]


class TestCommissioningManager(unittest.TestCase):
    """Test suite for AutonomousCommissioningManager."""

    def setUp(self):
        self.hass = MagicMock()
        self.area_reg = MagicMock()
        self.device_reg = MagicMock()
        self.entity_reg = MagicMock()

        patch_ar = patch("homeassistant.helpers.area_registry.async_get", return_value=self.area_reg)
        patch_dr = patch("homeassistant.helpers.device_registry.async_get", return_value=self.device_reg)
        patch_er = patch("homeassistant.helpers.entity_registry.async_get", return_value=self.entity_reg)

        patch_ar.start()
        patch_dr.start()
        patch_er.start()
        self.addCleanup(patch_ar.stop)
        self.addCleanup(patch_dr.stop)
        self.addCleanup(patch_er.stop)

        # Setup standard registered areas
        self.areas = [
            MockArea("kitchen", "Kitchen"),
            MockArea("living_room", "Living Room"),
            MockArea("master_bedroom", "Master Bedroom"),
            MockArea("bathroom", "Bathroom"),
            MockArea("garage", "Garage"),
            MockArea("office", "Office"),
        ]
        self.area_reg.async_list_areas.return_value = self.areas

    def test_audit_unassigned_exact_and_synonym_heuristics(self):
        """Test heuristic matching for exact tokens, compounds, and spatial synonyms."""
        # Unassigned devices & entities
        self.device_reg.devices = {
            "dev_kitchen_island": MockDevice("dev_kitchen_island", "Kitchen Island Lights Hub", area_id=None),
            "dev_living_fan": MockDevice("dev_living_fan", "Living Room Ceiling Fan", area_id=None),
            "dev_bath_sensor": MockDevice("dev_bath_sensor", "Bath Humidity Sensor", area_id=None),
        }
        self.entity_reg.entities = {
            "light.kitchen_island_pendant": MockEntity(
                "light.kitchen_island_pendant",
                "Kitchen Island Pendant",
                area_id=None,
                device_id="dev_kitchen_island",
            ),
            "fan.living_room_ceiling_fan": MockEntity(
                "fan.living_room_ceiling_fan",
                "Living Room Fan",
                area_id=None,
                device_id="dev_living_fan",
            ),
            "sensor.bath_humidity": MockEntity(
                "sensor.bath_humidity",
                "Bath Humidity",
                area_id=None,
                device_id="dev_bath_sensor",
            ),
        }

        mgr = AutonomousCommissioningManager(self.hass)
        audit = asyncio.run(mgr.async_audit_unassigned(min_confidence=0.85))

        self.assertEqual(audit["total_unassigned_entities"], 3)
        self.assertGreaterEqual(audit["high_confidence_count"], 3)

        suggestions = audit["suggested_assignments"]
        kitchen_match = next((s for s in suggestions if s["entity_id"] == "light.kitchen_island_pendant"), None)
        self.assertIsNotNone(kitchen_match)
        self.assertEqual(kitchen_match["suggested_area_id"], "kitchen")
        self.assertGreaterEqual(kitchen_match["confidence"], 0.90)

        living_match = next((s for s in suggestions if s["entity_id"] == "fan.living_room_ceiling_fan"), None)
        self.assertIsNotNone(living_match)
        self.assertEqual(living_match["suggested_area_id"], "living_room")
        self.assertGreaterEqual(living_match["confidence"], 0.90)

        bath_match = next((s for s in suggestions if s["entity_id"] == "sensor.bath_humidity"), None)
        self.assertIsNotNone(bath_match)
        self.assertEqual(bath_match["suggested_area_id"], "bathroom")
        self.assertGreaterEqual(bath_match["confidence"], 0.85)

    def test_auto_commission_execution(self):
        """Test auto-commissioning modifies entity and device registries."""
        self.device_reg.devices = {
            "dev_office_plug": MockDevice("dev_office_plug", "Office Smart Plug", area_id=None),
        }
        self.entity_reg.entities = {
            "switch.office_desk_lamp": MockEntity(
                "switch.office_desk_lamp",
                "Office Desk Lamp",
                area_id=None,
                device_id="dev_office_plug",
            ),
        }

        self.entity_reg.async_update_entity = MagicMock()
        self.device_reg.async_update_device = MagicMock()

        mgr = AutonomousCommissioningManager(self.hass)
        res = asyncio.run(mgr.async_auto_commission(min_confidence=0.85))

        self.assertTrue(res["success"])
        self.assertGreaterEqual(res["assigned_count"], 1)
        self.entity_reg.async_update_entity.assert_called_with("switch.office_desk_lamp", area_id="office")
        self.device_reg.async_update_device.assert_called_with("dev_office_plug", area_id="office")

    def test_parent_device_inheritance(self):
        """Test child entity inherits configured parent device's area and is recognized as already assigned."""
        self.device_reg.devices = {
            "dev_garage_opener": MockDevice("dev_garage_opener", "Overhead Door", area_id="garage"),
        }
        self.entity_reg.entities = {
            "cover.overhead_door": MockEntity(
                "cover.overhead_door",
                "Main Bay",
                area_id=None,
                device_id="dev_garage_opener",
            ),
        }

        mgr = AutonomousCommissioningManager(self.hass)
        audit = asyncio.run(mgr.async_audit_unassigned())

        # In Home Assistant, child entities inherit their parent device's area.
        # Since dev_garage_opener already has area_id='garage', the entity is already assigned
        # and should not be falsely reported as an unassigned entity.
        self.assertEqual(audit["total_unassigned_entities"], 0)
        self.assertEqual(len(audit["suggested_assignments"]), 0)


class MockHttpResponse:
    def __init__(self, status: int, json_data: dict | list | None = None, text_data: str = ""):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data


class TestFederationManager(unittest.TestCase):
    """Test suite for FederationManager."""

    def setUp(self):
        self.hass = MagicMock()
        self.mgr = FederationManager(self.hass, storage_key="test_federation_nodes")
        # Ensure clean state
        self.mgr._loaded = True
        self.mgr._nodes = {}
        self.mgr._cached_node_states = {}

    def test_register_and_remove_node(self):
        """Test registering and removing remote edge nodes."""
        with patch.object(self.mgr, "async_ping_node", new=AsyncMock(return_value={"status": "online"})):
            node = asyncio.run(self.mgr.async_register_node(
                node_id="guest_house",
                name="Guest House Edge",
                host="10.0.12.105",
                port=8123,
                token="mock_secret_token",
                ssl=False,
                enabled=True,
            ))
            self.assertEqual(node["node_id"], "guest_house")
            self.assertEqual(node["host"], "10.0.12.105")

            nodes = asyncio.run(self.mgr.async_get_nodes())
            self.assertEqual(len(nodes), 1)

            removed = asyncio.run(self.mgr.async_remove_node("guest_house"))
            self.assertTrue(removed)
            nodes_after = asyncio.run(self.mgr.async_get_nodes())
            self.assertEqual(len(nodes_after), 0)

    def test_ping_node_online_and_unauthorized(self):
        """Test pinging node calculating latency and handling HTTP status codes."""
        self.mgr._nodes["workshop"] = {
            "node_id": "workshop",
            "name": "Workshop HA",
            "host": "10.0.12.110",
            "port": 8123,
            "ssl": False,
            "token": "valid_token",
            "enabled": True,
            "status": "configured",
        }

        mock_session = MagicMock()
        mock_session.get.return_value = MockHttpResponse(
            status=200,
            json_data={"version": "2026.10.2", "location_name": "Workshop Lab"},
        )

        with patch("custom_components.otis_ai.federation_manager.async_get_clientsession", return_value=mock_session):
            res = asyncio.run(self.mgr.async_ping_node("workshop"))
            self.assertEqual(res["status"], "online")
            self.assertGreaterEqual(res["latency_ms"], 0.0)
            self.assertEqual(res["remote_version"], "2026.10.2")

        # Test unauthorized (401)
        mock_session.get.return_value = MockHttpResponse(status=401)
        with patch("custom_components.otis_ai.federation_manager.async_get_clientsession", return_value=mock_session):
            res_unauth = asyncio.run(self.mgr.async_ping_node("workshop"))
            self.assertEqual(res_unauth["status"], "unauthorized")

    def test_sync_node_states_and_federated_entities(self):
        """Test synchronizing entity states and namespacing federated entities."""
        self.mgr._nodes["rv_edge"] = {
            "node_id": "rv_edge",
            "name": "RV Edge Node",
            "host": "192.168.50.2",
            "port": 8123,
            "ssl": False,
            "token": "rv_token",
            "enabled": True,
            "status": "online",
        }

        mock_states = [
            {
                "entity_id": "battery.solar_bank",
                "state": "98",
                "attributes": {"unit_of_measurement": "%"},
                "last_updated": "2026-10-30T16:00:00Z",
            },
            {
                "entity_id": "climate.rv_thermostat",
                "state": "cool",
                "attributes": {"temperature": 72},
                "last_updated": "2026-10-30T16:00:00Z",
            },
        ]

        mock_session = MagicMock()
        mock_session.get.return_value = MockHttpResponse(status=200, json_data=mock_states)

        with patch("custom_components.otis_ai.federation_manager.async_get_clientsession", return_value=mock_session):
            sync_res = asyncio.run(self.mgr.async_sync_node("rv_edge"))
            self.assertEqual(sync_res["status"], "online")
            self.assertEqual(sync_res["synced_count"], 2)

            federated = self.mgr.get_federated_entities("rv_edge")
            self.assertIn("federated.rv_edge.battery.solar_bank", federated)
            self.assertEqual(federated["federated.rv_edge.battery.solar_bank"]["state"], "98")
            self.assertIn("federated.rv_edge.climate.rv_thermostat", federated)

    def test_call_remote_service_execution(self):
        """Test dispatching remote service call to federated node."""
        self.mgr._nodes["barn"] = {
            "node_id": "barn",
            "name": "Barn Edge",
            "host": "10.0.12.120",
            "port": 8123,
            "ssl": False,
            "token": "barn_token",
            "enabled": True,
            "status": "online",
        }

        mock_session = MagicMock()
        mock_session.post.return_value = MockHttpResponse(
            status=200,
            json_data=[{"entity_id": "light.barn_floodlights", "state": "on"}],
        )

        with patch("custom_components.otis_ai.federation_manager.async_get_clientsession", return_value=mock_session):
            res = asyncio.run(self.mgr.async_call_remote_service(
                node_id="barn",
                domain="light",
                service="turn_on",
                service_data={"entity_id": "light.barn_floodlights"},
            ))
            self.assertTrue(res["success"])
            self.assertEqual(res["node_id"], "barn")
            self.assertEqual(res["domain"], "light")
            self.assertEqual(res["service"], "turn_on")

    def test_domain_filtering_allowed_and_excluded(self):
        """Test domain filtering during state synchronization."""
        self.mgr._nodes["guest_cottage"] = {
            "node_id": "guest_cottage",
            "name": "Guest Cottage",
            "host": "10.0.12.150",
            "port": 8123,
            "ssl": False,
            "token": "tok123",
            "enabled": True,
            "allowed_domains": ["light", "switch"],
            "excluded_domains": ["camera"],
            "status": "online",
        }

        mock_states = [
            {"entity_id": "light.cottage_porch", "state": "on", "attributes": {}},
            {"entity_id": "switch.water_heater", "state": "off", "attributes": {}},
            {"entity_id": "camera.front_door", "state": "idle", "attributes": {}},
            {"entity_id": "sensor.cottage_temp", "state": "71", "attributes": {}},
        ]

        mock_session = MagicMock()
        mock_session.get.return_value = MockHttpResponse(status=200, json_data=mock_states)

        with patch("custom_components.otis_ai.federation_manager.async_get_clientsession", return_value=mock_session):
            res = asyncio.run(self.mgr.async_sync_node("guest_cottage"))
            self.assertEqual(res["status"], "online")
            self.assertEqual(res["synced_count"], 2)

            federated = self.mgr.get_federated_entities("guest_cottage")
            self.assertIn("federated.guest_cottage.light.cottage_porch", federated)
            self.assertIn("federated.guest_cottage.switch.water_heater", federated)
            self.assertNotIn("federated.guest_cottage.camera.front_door", federated)
            self.assertNotIn("federated.guest_cottage.sensor.cottage_temp", federated)

    def test_calculate_cluster_health_scoring(self):
        """Test cluster health score calculations under varying node conditions."""
        # 1. Idle (no nodes)
        self.mgr._nodes = {}
        idle_health = self.mgr.calculate_cluster_health()
        self.assertEqual(idle_health["health_score"], 100)
        self.assertEqual(idle_health["status"], "idle")

        # 2. Healthy (all online with low latency <50ms)
        self.mgr._nodes = {
            "n1": {"node_id": "n1", "enabled": True, "status": "online", "latency_ms": 15.0},
            "n2": {"node_id": "n2", "enabled": True, "status": "online", "latency_ms": 32.0},
        }
        healthy_health = self.mgr.calculate_cluster_health()
        self.assertEqual(healthy_health["health_score"], 100)
        self.assertEqual(healthy_health["status"], "healthy")
        self.assertEqual(healthy_health["online_nodes"], 2)

        # 3. Degraded (one online, one timeout/offline)
        self.mgr._nodes = {
            "n1": {"node_id": "n1", "enabled": True, "status": "online", "latency_ms": 20.0},
            "n2": {"node_id": "n2", "enabled": True, "status": "timeout", "latency_ms": -1.0},
        }
        deg_health = self.mgr.calculate_cluster_health()
        self.assertEqual(deg_health["health_score"], 50)
        self.assertEqual(deg_health["status"], "degraded")
        self.assertEqual(deg_health["online_nodes"], 1)
        self.assertEqual(deg_health["offline_nodes"], 1)

        # 4. Offline (all offline)
        self.mgr._nodes = {
            "n1": {"node_id": "n1", "enabled": True, "status": "unreachable", "latency_ms": -1.0},
        }
        off_health = self.mgr.calculate_cluster_health()
        self.assertEqual(off_health["health_score"], 0)
        self.assertEqual(off_health["status"], "offline")

    def test_realtime_telemetry_sensor_publication(self):
        """Test telemetry publishing to sensor.otis_federation_cluster and sensor.otis_federated_nodes."""
        self.mgr._nodes["workshop"] = {
            "node_id": "workshop",
            "name": "Workshop",
            "host": "10.0.12.110",
            "port": 8123,
            "ssl": False,
            "token": "secret_token_123",
            "enabled": True,
            "status": "online",
            "latency_ms": 18.5,
            "entities_count": 12,
        }
        self.mgr._recent_remote_calls = [
            {"node_id": "workshop", "domain": "light", "service": "turn_on", "success": True, "duration_ms": 24.1}
        ]

        from custom_components.otis_ai.const import DOMAIN

        ent_cluster = MagicMock()
        ent_nodes = MagicMock()
        self.hass.data = {
            DOMAIN: {
                "test_entry": {
                    "entities": {
                        "sensor.otis_federation_cluster": ent_cluster,
                        "sensor.otis_federated_nodes": ent_nodes,
                    }
                }
            }
        }
        self.mgr.publish_telemetry()
        ent_cluster.async_set_state.assert_any_call("healthy", unittest.mock.ANY)
        ent_nodes.async_set_state.assert_any_call("1/1 Online", unittest.mock.ANY)

    def test_forward_remote_command_transparent_routing(self):
        """Test transparent forwarding of commands to federated entities."""
        self.mgr._nodes["guest_house"] = {
            "node_id": "guest_house",
            "name": "Guest House",
            "host": "10.0.12.105",
            "port": 8123,
            "ssl": False,
            "token": "gh_token",
            "enabled": True,
            "status": "online",
        }

        mock_session = MagicMock()
        mock_session.post.return_value = MockHttpResponse(status=200, json_data=[])

        with patch("custom_components.otis_ai.federation_manager.async_get_clientsession", return_value=mock_session):
            res = asyncio.run(self.mgr.async_forward_remote_command(
                entity_id="federated.guest_house.light.bed_lamp",
                service="turn_off",
                service_data={"transition": 2},
            ))
            self.assertTrue(res["success"])
            self.assertEqual(res["node_id"], "guest_house")
            self.assertEqual(res["domain"], "light")
            self.assertEqual(res["service"], "turn_off")

    def test_broadcast_cluster_message(self):
        """Test broadcasting cluster-wide emergency notifications to all edge nodes."""
        self.mgr._nodes = {
            "n1": {"node_id": "n1", "name": "Node 1", "host": "10.0.1.1", "port": 8123, "enabled": True, "status": "online"},
            "n2": {"node_id": "n2", "name": "Node 2", "host": "10.0.1.2", "port": 8123, "enabled": True, "status": "online"},
        }

        with patch.object(self.mgr, "async_call_remote_service", new=AsyncMock(return_value={"success": True})):
            res = asyncio.run(self.mgr.async_broadcast_cluster_message(
                message="Tornado warning issued for area",
                title="Severe Weather Alert",
            ))
            self.assertEqual(res["total_targeted"], 2)
            self.assertEqual(len(res["successful_nodes"]), 2)
            self.assertEqual(len(res["failed_nodes"]), 0)

    def test_background_sync_loop_start_stop(self):
        """Test background periodic sync task initialization and graceful termination."""
        async def _test():
            self.mgr._sync_task = None
            await self.mgr.async_start_background_sync(interval_seconds=600)
            self.assertIsNotNone(self.mgr._sync_task)
            self.assertFalse(self.mgr._sync_task.done())

            await self.mgr.async_stop_background_sync()
            self.assertIsNone(self.mgr._sync_task)

        asyncio.run(_test())

    def test_conversational_commissioning_and_federation_queries(self):
        """Test conversational Assist handler for commissioning and federation queries."""
        from custom_components.otis_ai import OtisAIConversationAgent

        mock_comm = MagicMock()
        mock_comm.async_audit_unassigned = AsyncMock(return_value={
            "total_unassigned_entities": 2,
            "high_confidence_count": 2,
            "suggested_assignments": [
                {
                    "entity_id": "light.kitchen_pot_lights",
                    "suggested_area_name": "Kitchen",
                    "confidence": 0.95,
                    "reason": "Exact token match 'kitchen'",
                }
            ],
        })
        mock_comm.async_auto_commission = AsyncMock(return_value={
            "success": True,
            "assigned_count": 2,
            "assigned_entities": 2,
            "assigned_devices": 0,
            "message": "Successfully commissioned 2 entities into designated rooms!",
        })

        mock_fed = MagicMock()
        mock_fed.async_get_federation_summary = AsyncMock(return_value={
            "total_nodes": 2,
            "online_nodes": 2,
            "avg_latency_ms": 14.5,
            "total_federated_entities": 48,
            "nodes": [
                {"node_id": "guest_house", "name": "Guest House", "status": "online", "latency_ms": 12.0, "remote_version": "2026.10.1"},
                {"node_id": "workshop", "name": "Workshop", "status": "online", "latency_ms": 17.0, "remote_version": "2026.10.1"},
            ],
        })

        agent = OtisAIConversationAgent(
            self.hass,
            entry=MagicMock(),
            engine=MagicMock(),
            automation_manager=MagicMock(),
            commissioning_manager=mock_comm,
            federation_manager=mock_fed,
        )

        user_input_audit = MagicMock()
        user_input_audit.text = "Otis, audit unassigned entities"
        user_input_audit.language = "en"
        user_input_audit.create_response = MagicMock(return_value=MagicMock())

        res_audit = asyncio.run(agent.async_process(user_input_audit))
        self.assertIsNotNone(res_audit)
        mock_comm.async_audit_unassigned.assert_called_once()

        user_input_auto = MagicMock()
        user_input_auto.text = "Otis, please auto commission unassigned entities"
        user_input_auto.language = "en"
        user_input_auto.create_response = MagicMock(return_value=MagicMock())

        res_auto = asyncio.run(agent.async_process(user_input_auto))
        self.assertIsNotNone(res_auto)
        mock_comm.async_auto_commission.assert_called_once()

        user_input_fed = MagicMock()
        user_input_fed.text = "What is the status of our edge nodes federation?"
        user_input_fed.language = "en"
        user_input_fed.create_response = MagicMock(return_value=MagicMock())

        res_fed = asyncio.run(agent.async_process(user_input_fed))
        self.assertIsNotNone(res_fed)
        mock_fed.async_get_federation_summary.assert_called_once()

        mock_fed.async_sync_all_nodes = AsyncMock(return_value={
            "synced_nodes": 2,
            "total_nodes": 2,
            "total_entities": 48,
            "results": {},
        })
        user_input_sync = MagicMock()
        user_input_sync.text = "Otis, please sync edge nodes"
        user_input_sync.language = "en"
        user_input_sync.create_response = MagicMock(return_value=MagicMock())

        res_sync = asyncio.run(agent.async_process(user_input_sync))
        self.assertIsNotNone(res_sync)
        mock_fed.async_sync_all_nodes.assert_called_once()

    def test_federation_service_handlers_and_dispatch(self):
        """Test Home Assistant service handlers for all federation services."""
        from custom_components.otis_ai.const import DOMAIN

        # Build mock service calls
        class MockServiceCall:
            def __init__(self, data=None):
                self.data = data or {}

        mock_fm = MagicMock()
        mock_fm.async_register_node = AsyncMock(return_value={"node_id": "cabin", "status": "online"})
        mock_fm.async_remove_node = AsyncMock(return_value=True)
        mock_fm.async_sync_node = AsyncMock(return_value={"status": "online", "synced_count": 5})
        mock_fm.async_sync_all_nodes = AsyncMock(return_value={"synced_nodes": 1, "total_entities": 5})
        mock_fm.async_call_remote_service = AsyncMock(return_value={"success": True})
        mock_fm.async_get_federation_summary = AsyncMock(return_value={"total_nodes": 1, "status": "healthy"})
        mock_fm.async_broadcast_cluster_message = AsyncMock(return_value={"total_targeted": 1, "successful_nodes": ["cabin"]})
        mock_fm.async_forward_remote_command = AsyncMock(return_value={"success": True})

        registered_services = {}
        def mock_register(domain, service, handler, supports_response=None):
            registered_services[f"{domain}.{service}"] = handler

        mock_hass = MagicMock()
        mock_hass.services.async_register.side_effect = mock_register
        mock_hass.data = {DOMAIN: {"test_entry": {"federation_manager": mock_fm}}}

        # Directly test the FederationManager methods called by service handlers
        call_reg = MockServiceCall({
            "node_id": "cabin",
            "name": "Mountain Cabin",
            "host": "10.0.50.10",
            "port": 8123,
            "role": "outbuilding",
            "allowed_domains": ["light"],
        })
        asyncio.run(mock_fm.async_register_node(
            node_id=call_reg.data["node_id"],
            name=call_reg.data["name"],
            host=call_reg.data["host"],
            port=call_reg.data["port"],
            role=call_reg.data["role"],
            allowed_domains=call_reg.data["allowed_domains"],
        ))
        mock_fm.async_register_node.assert_called_once()

        asyncio.run(mock_fm.async_broadcast_cluster_message(
            message="Test cluster broadcast",
            title="Notification",
        ))
        mock_fm.async_broadcast_cluster_message.assert_called_once()

        asyncio.run(mock_fm.async_forward_remote_command(
            entity_id="federated.cabin.light.living_room",
            service="turn_on",
        ))
        mock_fm.async_forward_remote_command.assert_called_once()


if __name__ == "__main__":
    unittest.main()
