"""Multi-Node Federation & Edge Synchronization Manager for Otis AI Companion (Phase 10).

Enables cross-instance Home Assistant state synchronization, edge node orchestration,
latency monitoring, and remote service execution across satellite nodes (e.g. Guest House,
Workshop, Camper / Marine, Remote Outbuilding).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant

try:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
except ImportError:  # pragma: no cover
    def async_get_clientsession(hass: Any) -> Any:
        """Fallback client session getter for test environments."""
        import aiohttp
        return getattr(hass, "client_session", None) or aiohttp.ClientSession()

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "otis_ai_federation_nodes"
STORAGE_VERSION = 1


class FederationManager:
    """Manages multi-node Home Assistant federation and edge state synchronization."""

    def __init__(self, hass: HomeAssistant, storage_key: str = STORAGE_KEY) -> None:
        """Initialize the Federation Manager."""
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, storage_key)
        self._nodes: dict[str, dict[str, Any]] = {}
        self._cached_node_states: dict[str, dict[str, Any]] = {}
        self._loaded: bool = False

    async def async_load(self) -> None:
        """Load registered federated nodes from persistent store."""
        if self._loaded:
            return
        data = await self._store.async_load()
        if isinstance(data, dict) and "nodes" in data:
            self._nodes = data["nodes"]
        elif isinstance(data, list):
            self._nodes = {n.get("node_id", f"node_{i}"): n for i, n in enumerate(data) if isinstance(n, dict)}
        else:
            self._nodes = {}
        self._loaded = True
        _LOGGER.debug("Loaded %d federated edge nodes from storage", len(self._nodes))

    async def async_save(self) -> None:
        """Save federated node configurations to persistent store."""
        # Sanitize sensitive data or large states if needed, but keep core config
        storable_nodes: dict[str, Any] = {}
        for nid, node in self._nodes.items():
            storable_nodes[nid] = {
                "node_id": node.get("node_id", nid),
                "name": node.get("name", nid),
                "host": node.get("host", ""),
                "port": node.get("port", 8123),
                "ssl": bool(node.get("ssl", False)),
                "token": node.get("token", ""),
                "enabled": bool(node.get("enabled", True)),
                "status": node.get("status", "offline"),
                "latency_ms": node.get("latency_ms", 0.0),
                "remote_version": node.get("remote_version", "unknown"),
                "last_synced": node.get("last_synced"),
                "entities_count": node.get("entities_count", 0),
            }
        await self._store.async_save({"nodes": storable_nodes})

    def _build_url(self, node: dict[str, Any], path: str) -> str:
        """Construct full HTTP(S) URL for a remote node."""
        protocol = "https" if node.get("ssl") else "http"
        host = node.get("host", "").strip()
        port = node.get("port", 8123)
        clean_path = path.lstrip("/")
        return f"{protocol}://{host}:{port}/{clean_path}"

    def _build_headers(self, node: dict[str, Any]) -> dict[str, str]:
        """Build HTTP request headers including Bearer Token authentication."""
        token = node.get("token", "").strip()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Otis-AI-Companion-Federation/1.11.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def async_register_node(
        self,
        node_id: str,
        name: str,
        host: str,
        port: int = 8123,
        token: str = "",
        ssl: bool = False,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Register or update a remote Home Assistant instance node."""
        if not self._loaded:
            await self.async_load()

        if not node_id or not host:
            raise ValueError("node_id and host are required to register a federated node")

        node_data: dict[str, Any] = {
            "node_id": node_id,
            "name": name or node_id,
            "host": host,
            "port": int(port),
            "ssl": bool(ssl),
            "token": token,
            "enabled": bool(enabled),
            "status": "configured",
            "latency_ms": 0.0,
            "remote_version": "unknown",
            "last_synced": None,
            "entities_count": 0,
        }

        self._nodes[node_id] = node_data

        # Immediately test connectivity & query remote version
        try:
            await self.async_ping_node(node_id)
        except Exception as err:
            _LOGGER.debug("Immediate ping to newly registered node '%s' failed: %s", node_id, err)

        await self.async_save()
        return self._nodes[node_id]

    async def async_remove_node(self, node_id: str) -> bool:
        """Remove a federated node from the registry."""
        if not self._loaded:
            await self.async_load()

        if node_id in self._nodes:
            del self._nodes[node_id]
            self._cached_node_states.pop(node_id, None)
            await self.async_save()
            _LOGGER.info("Deregistered federated node '%s'", node_id)
            return True
        return False

    async def async_get_nodes(self) -> list[dict[str, Any]]:
        """Return all registered federated nodes."""
        if not self._loaded:
            await self.async_load()
        return list(self._nodes.values())

    async def async_ping_node(self, node_id: str) -> dict[str, Any]:
        """Ping a remote node to check online status, round-trip latency, and version."""
        if not self._loaded:
            await self.async_load()

        node = self._nodes.get(node_id)
        if not node:
            raise ValueError(f"Federated node '{node_id}' not found")

        url = self._build_url(node, "api/discovery_info")
        headers = self._build_headers(node)
        session = async_get_clientsession(self.hass)

        t_start = time.perf_counter()
        try:
            async with asyncio.timeout(5.0):
                async with session.get(url, headers=headers) as resp:
                    latency = round((time.perf_counter() - t_start) * 1000, 1)
                    if resp.status == 200:
                        payload = await resp.json()
                        node["status"] = "online"
                        node["latency_ms"] = latency
                        node["remote_version"] = payload.get("version", "unknown")
                        node["location_name"] = payload.get("location_name", node.get("name"))
                    elif resp.status in (401, 403):
                        node["status"] = "unauthorized"
                        node["latency_ms"] = latency
                    else:
                        node["status"] = f"http_{resp.status}"
                        node["latency_ms"] = latency
        except asyncio.TimeoutError:
            node["status"] = "timeout"
            node["latency_ms"] = -1.0
        except Exception as err:
            _LOGGER.debug("Ping failed for node '%s': %s", node_id, err)
            node["status"] = "unreachable"
            node["latency_ms"] = -1.0

        return {
            "node_id": node_id,
            "status": node["status"],
            "latency_ms": node["latency_ms"],
            "remote_version": node.get("remote_version", "unknown"),
        }

    async def async_sync_node(self, node_id: str) -> dict[str, Any]:
        """Synchronize all entity states from a remote federated node."""
        if not self._loaded:
            await self.async_load()

        node = self._nodes.get(node_id)
        if not node:
            raise ValueError(f"Federated node '{node_id}' not found")

        if not node.get("enabled", True):
            return {
                "node_id": node_id,
                "status": "disabled",
                "synced_count": 0,
                "error": "Node is disabled in configuration",
            }

        url = self._build_url(node, "api/states")
        headers = self._build_headers(node)
        session = async_get_clientsession(self.hass)

        t_start = time.perf_counter()
        try:
            async with asyncio.timeout(10.0):
                async with session.get(url, headers=headers) as resp:
                    latency = round((time.perf_counter() - t_start) * 1000, 1)
                    if resp.status == 200:
                        raw_states = await resp.json()
                        entity_states: dict[str, dict[str, Any]] = {}
                        for s in raw_states:
                            eid = s.get("entity_id")
                            if eid:
                                entity_states[eid] = {
                                    "state": s.get("state"),
                                    "attributes": s.get("attributes", {}),
                                    "last_updated": s.get("last_updated"),
                                    "last_changed": s.get("last_changed"),
                                }

                        self._cached_node_states[node_id] = entity_states
                        node["status"] = "online"
                        node["latency_ms"] = latency
                        node["last_synced"] = datetime.now(timezone.utc).isoformat()
                        node["entities_count"] = len(entity_states)
                        await self.async_save()

                        return {
                            "node_id": node_id,
                            "status": "online",
                            "synced_count": len(entity_states),
                            "latency_ms": latency,
                            "last_synced": node["last_synced"],
                        }
                    else:
                        node["status"] = f"http_{resp.status}"
                        return {
                            "node_id": node_id,
                            "status": node["status"],
                            "synced_count": 0,
                            "error": f"Remote node returned HTTP {resp.status}",
                        }
        except asyncio.TimeoutError:
            node["status"] = "timeout"
            return {"node_id": node_id, "status": "timeout", "synced_count": 0, "error": "Request timed out"}
        except Exception as err:
            _LOGGER.debug("Sync failed for node '%s': %s", node_id, err)
            node["status"] = "unreachable"
            return {"node_id": node_id, "status": "unreachable", "synced_count": 0, "error": str(err)}

    async def async_sync_all_nodes(self) -> dict[str, Any]:
        """Synchronize states from all registered and enabled federated nodes concurrently."""
        if not self._loaded:
            await self.async_load()

        enabled_nodes = [nid for nid, n in self._nodes.items() if n.get("enabled", True)]
        if not enabled_nodes:
            return {"synced_nodes": 0, "total_entities": 0, "results": {}}

        results = await asyncio.gather(
            *(self.async_sync_node(nid) for nid in enabled_nodes),
            return_exceptions=True,
        )

        res_dict: dict[str, Any] = {}
        total_ents = 0
        successful_nodes = 0

        for nid, res in zip(enabled_nodes, results):
            if isinstance(res, Exception):
                res_dict[nid] = {"status": "error", "error": str(res)}
            else:
                res_dict[nid] = res
                if res.get("status") == "online":
                    successful_nodes += 1
                    total_ents += res.get("synced_count", 0)

        return {
            "synced_nodes": successful_nodes,
            "total_nodes": len(enabled_nodes),
            "total_entities": total_ents,
            "results": res_dict,
        }

    async def async_call_remote_service(
        self,
        node_id: str,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatch a remote service execution to a federated edge node."""
        if not self._loaded:
            await self.async_load()

        node = self._nodes.get(node_id)
        if not node:
            raise ValueError(f"Federated node '{node_id}' not found")

        url = self._build_url(node, f"api/services/{domain}/{service}")
        headers = self._build_headers(node)
        session = async_get_clientsession(self.hass)
        payload = service_data or {}

        try:
            async with asyncio.timeout(10.0):
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        _LOGGER.info(
                            "Executed remote service '%s.%s' on node '%s'",
                            domain, service, node_id
                        )
                        return {
                            "success": True,
                            "node_id": node_id,
                            "domain": domain,
                            "service": service,
                            "response": data,
                        }
                    else:
                        text = await resp.text()
                        return {
                            "success": False,
                            "node_id": node_id,
                            "status": resp.status,
                            "error": f"Remote node returned HTTP {resp.status}: {text}",
                        }
        except Exception as err:
            _LOGGER.error("Failed to execute remote service on node '%s': %s", node_id, err)
            return {"success": False, "node_id": node_id, "error": str(err)}

    def get_federated_entities(self, node_id: str | None = None) -> dict[str, dict[str, Any]]:
        """Return cached federated entities, optionally namespaced by node_id."""
        result: dict[str, dict[str, Any]] = {}
        if node_id:
            states = self._cached_node_states.get(node_id, {})
            for eid, s in states.items():
                result[f"federated.{node_id}.{eid}"] = s
            return result

        for nid, states in self._cached_node_states.items():
            for eid, s in states.items():
                result[f"federated.{nid}.{eid}"] = s
        return result

    async def async_get_federation_summary(self) -> dict[str, Any]:
        """Return full multi-node federation topology, latency, and synchronization health."""
        if not self._loaded:
            await self.async_load()

        node_list = list(self._nodes.values())
        online_count = sum(1 for n in node_list if n.get("status") == "online")
        total_entities = sum(n.get("entities_count", 0) for n in node_list)
        latencies = [n.get("latency_ms", 0.0) for n in node_list if n.get("latency_ms", -1.0) > 0]
        avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0.0

        return {
            "total_nodes": len(node_list),
            "online_nodes": online_count,
            "offline_nodes": len(node_list) - online_count,
            "avg_latency_ms": avg_latency,
            "total_federated_entities": total_entities,
            "nodes": node_list,
        }
