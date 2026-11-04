"""Unit tests for Otis AI Companion Phase 6: Autonomous Mesh Self-Healing & Topology Ingestion."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.otis_ai.mesh_manager import MeshManager, normalize_node_slug


class MockDevice:
    """Mock Home Assistant Device Entry."""

    def __init__(
        self,
        dev_id: str,
        name: str,
        identifiers: set,
        area_id: str | None = None,
    ):
        self.id = dev_id
        self.name = name
        self.name_by_user = None
        self.identifiers = identifiers
        self.area_id = area_id


class MockEntity:
    """Mock Home Assistant Entity Registry Entry."""

    def __init__(self, entity_id: str, device_id: str):
        self.entity_id = entity_id
        self.device_id = device_id


class MockState:
    """Mock Home Assistant State."""

    def __init__(self, state: str, attributes: dict | None = None):
        self.state = state
        self.attributes = attributes or {}


def test_normalize_node_slug():
    """Test slug normalization for mesh node IDs."""
    assert normalize_node_slug("zwave_js_3924280160-14") == "zwave_js_3924280160_14"
    assert normalize_node_slug("Front Porch Plug") == "front_porch_plug"
    assert normalize_node_slug(None) == ""


@pytest.mark.asyncio
async def test_audit_mesh_topology_empty():
    """Test mesh audit when no mesh devices exist."""
    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()

    with patch("homeassistant.helpers.device_registry.async_get", return_value=None), \
         patch("homeassistant.helpers.entity_registry.async_get", return_value=None):
        mm = MeshManager(hass)
        res = await mm.async_audit_mesh_topology()
        assert res["total_nodes"] == 0
        assert res["status"] == "no_mesh_detected"
        assert res["health_score"] == 100
        hass.states.async_set.assert_called_once()
        args = hass.states.async_set.call_args[0]
        assert args[0] == "sensor.otis_mesh_health"
        assert args[1] == "no_mesh_detected"


@pytest.mark.asyncio
async def test_audit_mesh_topology_zwave_js():
    """Test mesh audit detects alive and dead Z-Wave JS devices and calculates health score."""
    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()

    dev_alive = MockDevice(
        dev_id="dev_zwave_1",
        name="Living Room Dimmer",
        identifiers={("zwave_js", "3924280160-14")},
        area_id="living_room",
    )
    dev_dead = MockDevice(
        dev_id="dev_zwave_2",
        name="Front Porch Sconce",
        identifiers={("zwave_js", "3924280160-22")},
        area_id="front_porch",
    )

    ent_alive = MockEntity("light.living_room_dimmer", "dev_zwave_1")
    ent_dead = MockEntity("light.front_porch_sconce", "dev_zwave_2")

    mock_dev_reg = MagicMock()
    mock_dev_reg.devices = {"dev_zwave_1": dev_alive, "dev_zwave_2": dev_dead}

    mock_ent_reg = MagicMock()
    mock_ent_reg.entities = {
        "light.living_room_dimmer": ent_alive,
        "light.front_porch_sconce": ent_dead,
    }

    # States
    def mock_get_state(eid):
        if eid == "light.living_room_dimmer":
            return MockState("on")
        if eid == "light.front_porch_sconce":
            return MockState("unavailable")
        return None

    hass.states.get.side_effect = mock_get_state

    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg), \
         patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_ent_reg):
        mm = MeshManager(hass)
        res = await mm.async_audit_mesh_topology()

        assert res["total_nodes"] == 2
        assert res["dead_nodes_count"] == 1
        assert res["marginal_nodes_count"] == 0
        assert res["health_score"] == 80  # 100 - (1 * 20)
        assert res["status"] == "degraded"
        assert "zwave_js" in res["protocols"]
        assert res["dead_nodes"][0]["name"] == "Front Porch Sconce"


@pytest.mark.asyncio
async def test_audit_mesh_topology_zigbee_marginal_lqi():
    """Test Zigbee devices with poor link quality (LQI < 50) are classified as marginal."""
    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()

    dev_zha = MockDevice(
        dev_id="dev_zha_1",
        name="Basement Temperature Sensor",
        identifiers={("zha", "00:15:8d:00:01:23:45:67")},
        area_id="basement",
    )
    ent_zha = MockEntity("sensor.basement_temperature", "dev_zha_1")

    mock_dev_reg = MagicMock()
    mock_dev_reg.devices = {"dev_zha_1": dev_zha}

    mock_ent_reg = MagicMock()
    mock_ent_reg.entities = {"sensor.basement_temperature": ent_zha}

    # State with weak LQI (32 out of 255)
    hass.states.get.return_value = MockState("21.5", {"lqi": 32, "rssi": -88.0})

    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg), \
         patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_ent_reg):
        mm = MeshManager(hass)
        res = await mm.async_audit_mesh_topology()

        assert res["total_nodes"] == 1
        assert res["dead_nodes_count"] == 0
        assert res["marginal_nodes_count"] == 1
        assert res["health_score"] == 95  # 100 - 5
        assert res["status"] == "healthy"
        assert "zigbee" in res["protocols"]


@pytest.mark.asyncio
async def test_heal_mesh_node_zwave():
    """Test healing a Z-Wave node dispatches zwave_js.ping and zwave_js.heal_node."""
    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.has_service.side_effect = lambda domain, svc: svc in ("ping", "heal_node", "rebuild_routes")
    hass.services.async_call = AsyncMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()

    mm = MeshManager(hass)
    mm._mesh_nodes["zwave_js_14"] = {
        "id": "zwave_js_14",
        "node_id": "14",
        "device_id": "dev_14",
        "name": "Kitchen Pendant",
        "protocol": "zwave_js",
        "status": "dead",
    }

    # Execute healing
    with patch.object(mm, "async_audit_mesh_topology", new_callable=AsyncMock) as mock_audit:
        mock_audit.return_value = {"status": "healthy"}
        res = await mm.async_heal_mesh_node("zwave_js_14", force_rebuild=True)

        assert res["success"] is True
        assert res["node_id"] == "zwave_js_14"
        assert res["protocol"] == "zwave_js"
        assert len(res["actions_taken"]) >= 2

        # Check bus event
        assert hass.bus.async_fire.call_count == 1
        call_args = hass.bus.async_fire.call_args[0]
        assert call_args[0] == "otis_ai_mesh_node_healed"
        assert call_args[1]["node_id"] == "zwave_js_14"
        assert call_args[1]["protocol"] == "zwave_js"
        # Check healing history recorded
        assert len(mm.get_healing_history()) == 1


@pytest.mark.asyncio
async def test_heal_mesh_node_zigbee_and_mqtt():
    """Test healing ZHA and Zigbee2MQTT nodes dispatches correct protocol actions."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.has_service.side_effect = lambda domain, svc: (domain == "zha" and svc == "reconfigure_device") or (domain == "mqtt" and svc == "publish")
    hass.services.async_call = AsyncMock()
    hass.bus = MagicMock()

    mm = MeshManager(hass)
    mm._mesh_nodes["zha_123"] = {
        "id": "zha_123",
        "node_id": "123",
        "device_id": "dev_zha_123",
        "protocol": "zha",
    }
    mm._mesh_nodes["mqtt_456"] = {
        "id": "mqtt_456",
        "node_id": "456",
        "device_id": "dev_z2m_456",
        "protocol": "zigbee2mqtt",
    }

    with patch.object(mm, "async_audit_mesh_topology", new_callable=AsyncMock):
        # 1. ZHA healing
        res_zha = await mm.async_heal_mesh_node("zha_123")
        assert res_zha["success"] is True
        hass.services.async_call.assert_any_call(
            "zha",
            "reconfigure_device",
            {"device_id": "dev_zha_123"},
            blocking=True,
        )

        # 2. Zigbee2MQTT healing
        res_mqtt = await mm.async_heal_mesh_node("mqtt_456")
        assert res_mqtt["success"] is True
        hass.services.async_call.assert_any_call(
            "mqtt",
            "publish",
            {"topic": "zigbee2mqtt/bridge/request/device/heal", "payload": '{"id": "dev_z2m_456"}'},
            blocking=True,
        )


@pytest.mark.asyncio
async def test_proactive_mesh_healing_suggestion_card():
    """Verify DiscoveryEngine surfaces high-priority proactive healing card when dead mesh nodes exist."""
    from custom_components.otis_ai import DiscoveryEngine

    hass = MagicMock()
    mm = MeshManager(hass)
    mm.async_audit_mesh_topology = AsyncMock(return_value={
        "dead_nodes": [
            {
                "id": "zwave_js_3924280160-22",
                "node_id": "22",
                "name": "Front Porch Sconce",
                "protocol": "zwave_js",
                "status": "dead",
            }
        ],
        "health_score": 80,
    })

    engine = DiscoveryEngine(hass, mesh_manager=mm)
    with patch.object(engine, "_discover_media_topology", return_value={}), \
         patch.object(engine, "_discover_security_topology", return_value={}), \
         patch.object(engine, "_discover_system_maturity", return_value={"breakdown": {}, "gaps": {}}), \
         patch.object(engine, "_inspect_config_files_sync", return_value={"automated_entities": set(), "norm_names": set()}), \
         patch.object(engine, "async_fetch_ha_official_news", new_callable=AsyncMock, return_value=[]):
        suggestions = await engine.async_generate_proactive_suggestions({"entities": []})

        heal_cards = [s for s in suggestions if s.get("action_type") == "heal_mesh_node"]
        assert len(heal_cards) == 1
        assert "Front Porch Sconce" in heal_cards[0]["title"]
        assert heal_cards[0]["priority"] == "high"
        assert heal_cards[0]["action_payload"]["node_id"] == "zwave_js_3924280160-22"
