"""Multi-Node Federation & Edge Synchronization Manager for Otis AI Companion (Phase 10).

Enables cross-instance Home Assistant state synchronization, edge node orchestration,
latency monitoring, cluster health scoring, and remote service execution across satellite
nodes (e.g. Guest House, Workshop, Camper / Marine, Remote Outbuilding).
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

from .const import (
    CLUSTER_STATUS_DEGRADED,
    CLUSTER_STATUS_HEALTHY,
    CLUSTER_STATUS_IDLE,
    CLUSTER_STATUS_OFFLINE,
    FEDERATION_ROLE_SATELLITE,
    INTEGRATION_VERSION,
    SENSOR_FEDERATED_NODES,
    SENSOR_FEDERATION_CLUSTER,
)

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
        self._recent_remote_calls: list[dict[str, Any]] = []
        self._sync_task: asyncio.Task | None = None
        self._sync_interval_seconds: int = 300
        self._last_sync_timestamp: str | None = None
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
                "role": node.get("role", FEDERATION_ROLE_SATELLITE),
                "allowed_domains": node.get("allowed_domains"),
                "excluded_domains": node.get("excluded_domains"),
                "status": node.get("status", "offline"),
                "latency_ms": node.get("latency_ms", 0.0),
                "remote_version": node.get("remote_version", "unknown"),
                "location_name": node.get("location_name", node.get("name", nid)),
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
            "User-Agent": f"Otis-AI-Companion-Federation/{INTEGRATION_VERSION}",
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
        role: str = FEDERATION_ROLE_SATELLITE,
        allowed_domains: list[str] | None = None,
        excluded_domains: list[str] | None = None,
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
            "role": role or FEDERATION_ROLE_SATELLITE,
            "allowed_domains": allowed_domains,
            "excluded_domains": excluded_domains,
            "status": "configured",
            "latency_ms": 0.0,
            "remote_version": "unknown",
            "location_name": name or node_id,
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
        self.publish_telemetry()
        return self._nodes[node_id]

    async def async_remove_node(self, node_id: str) -> bool:
        """Remove a federated node from the registry."""
        if not self._loaded:
            await self.async_load()

        if node_id in self._nodes:
            del self._nodes[node_id]
            self._cached_node_states.pop(node_id, None)
            await self.async_save()
            self.publish_telemetry()
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

        self.publish_telemetry()
        return {
            "node_id": node_id,
            "status": node["status"],
            "latency_ms": node["latency_ms"],
            "remote_version": node.get("remote_version", "unknown"),
        }

    async def async_sync_node(self, node_id: str) -> dict[str, Any]:
        """Synchronize all entity states from a remote federated node with domain filtering."""
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

        allowed_domains = set(node.get("allowed_domains") or [])
        excluded_domains = set(node.get("excluded_domains") or [])

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
                            if not eid:
                                continue
                            domain = eid.split(".", 1)[0]
                            if allowed_domains and domain not in allowed_domains:
                                continue
                            if excluded_domains and domain in excluded_domains:
                                continue

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
                        self._last_sync_timestamp = node["last_synced"]
                        await self.async_save()
                        self.publish_telemetry()

                        return {
                            "node_id": node_id,
                            "status": "online",
                            "synced_count": len(entity_states),
                            "latency_ms": latency,
                            "last_synced": node["last_synced"],
                        }
                    else:
                        node["status"] = f"http_{resp.status}"
                        self.publish_telemetry()
                        return {
                            "node_id": node_id,
                            "status": node["status"],
                            "synced_count": 0,
                            "error": f"Remote node returned HTTP {resp.status}",
                        }
        except asyncio.TimeoutError:
            node["status"] = "timeout"
            self.publish_telemetry()
            return {"node_id": node_id, "status": "timeout", "synced_count": 0, "error": "Request timed out"}
        except Exception as err:
            _LOGGER.debug("Sync failed for node '%s': %s", node_id, err)
            node["status"] = "unreachable"
            self.publish_telemetry()
            return {"node_id": node_id, "status": "unreachable", "synced_count": 0, "error": str(err)}

    async def async_sync_all_nodes(self) -> dict[str, Any]:
        """Synchronize states from all registered and enabled federated nodes concurrently."""
        if not self._loaded:
            await self.async_load()

        enabled_nodes = [nid for nid, n in self._nodes.items() if n.get("enabled", True)]
        if not enabled_nodes:
            self.publish_telemetry()
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

        self._last_sync_timestamp = datetime.now(timezone.utc).isoformat()
        self.publish_telemetry()

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

        t_start = time.perf_counter()
        try:
            async with asyncio.timeout(10.0):
                async with session.post(url, headers=headers, json=payload) as resp:
                    duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
                    if resp.status == 200:
                        data = await resp.json()
                        _LOGGER.info(
                            "Executed remote service '%s.%s' on node '%s' (in %0.1fms)",
                            domain, service, node_id, duration_ms
                        )
                        self._record_call(node_id, domain, service, success=True, duration_ms=duration_ms)
                        self.publish_telemetry()
                        return {
                            "success": True,
                            "node_id": node_id,
                            "domain": domain,
                            "service": service,
                            "response": data,
                        }
                    else:
                        text = await resp.text()
                        err_msg = f"Remote node returned HTTP {resp.status}: {text}"
                        self._record_call(node_id, domain, service, success=False, duration_ms=duration_ms, error=err_msg)
                        self.publish_telemetry()
                        return {
                            "success": False,
                            "node_id": node_id,
                            "status": resp.status,
                            "error": err_msg,
                        }
        except Exception as err:
            duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
            _LOGGER.error("Failed to execute remote service on node '%s': %s", node_id, err)
            self._record_call(node_id, domain, service, success=False, duration_ms=duration_ms, error=str(err))
            self.publish_telemetry()
            return {"success": False, "node_id": node_id, "error": str(err)}

    async def async_forward_remote_command(
        self,
        entity_id: str,
        service: str,
        node_id: str | None = None,
        service_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Transparently forward a command to a remote federated entity.

        Accepts namespaced entities (federated.<node_id>.<domain>.<obj>) or standard
        domain.obj entities with explicit node_id parameter.
        """
        target_node = node_id
        target_entity = entity_id
        target_domain = ""

        if entity_id.startswith("federated."):
            parts = entity_id.split(".", 3)
            # federated.<node_id>.<domain>.<obj>
            if len(parts) >= 4:
                target_node = parts[1]
                target_domain = parts[2]
                target_entity = f"{parts[2]}.{parts[3]}"
            elif len(parts) == 3:
                target_node = parts[1]
                target_domain = parts[2].split(".", 1)[0]
                target_entity = parts[2]
        elif "." in entity_id:
            target_domain = entity_id.split(".", 1)[0]

        if not target_node:
            raise ValueError(f"Could not determine target federated node for entity '{entity_id}'")

        if not target_domain:
            target_domain = "homeassistant"

        payload = dict(service_data or {})
        if target_entity and "entity_id" not in payload:
            payload["entity_id"] = target_entity

        return await self.async_call_remote_service(
            node_id=target_node,
            domain=target_domain,
            service=service,
            service_data=payload,
        )

    async def async_broadcast_cluster_message(
        self,
        message: str,
        title: str = "Otis Cluster Notification",
        target_nodes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Broadcast an alert or notification across all online federated edge nodes."""
        if not self._loaded:
            await self.async_load()

        if target_nodes:
            candidate_ids = [nid for nid in target_nodes if nid in self._nodes]
        else:
            candidate_ids = [nid for nid, n in self._nodes.items() if n.get("enabled", True)]

        if not candidate_ids:
            return {"total_targeted": 0, "successful_nodes": [], "failed_nodes": []}

        notification_payload = {
            "title": title,
            "message": message,
        }

        async def _send_to_node(nid: str) -> tuple[str, bool, str]:
            res = await self.async_call_remote_service(
                node_id=nid,
                domain="persistent_notification",
                service="create",
                service_data=notification_payload,
            )
            return nid, res.get("success", False), res.get("error", "")

        results = await asyncio.gather(*(_send_to_node(nid) for nid in candidate_ids))

        successful = [nid for nid, success, _ in results if success]
        failed = [nid for nid, success, _ in results if not success]

        _LOGGER.info(
            "Broadcasted cluster notification to %d nodes (%d success, %d failed)",
            len(candidate_ids), len(successful), len(failed)
        )
        return {
            "total_targeted": len(candidate_ids),
            "successful_nodes": successful,
            "failed_nodes": failed,
        }

    def _record_call(
        self,
        node_id: str,
        domain: str,
        service: str,
        success: bool,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        """Record execution history for auditing and diagnostics."""
        entry = {
            "node_id": node_id,
            "domain": domain,
            "service": service,
            "success": success,
            "duration_ms": duration_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": error,
        }
        self._recent_remote_calls.insert(0, entry)
        if len(self._recent_remote_calls) > 20:
            self._recent_remote_calls = self._recent_remote_calls[:20]

    def calculate_cluster_health(self) -> dict[str, Any]:
        """Calculate overall multi-node federation cluster health score and status."""
        node_list = list(self._nodes.values())
        if not node_list:
            return {
                "health_score": 100,
                "status": CLUSTER_STATUS_IDLE,
                "total_nodes": 0,
                "online_nodes": 0,
                "offline_nodes": 0,
                "avg_latency_ms": 0.0,
            }

        enabled_nodes = [n for n in node_list if n.get("enabled", True)]
        if not enabled_nodes:
            return {
                "health_score": 100,
                "status": CLUSTER_STATUS_IDLE,
                "total_nodes": len(node_list),
                "online_nodes": 0,
                "offline_nodes": 0,
                "avg_latency_ms": 0.0,
            }

        node_scores: list[int] = []
        valid_latencies: list[float] = []
        online_count = 0

        for n in enabled_nodes:
            status = n.get("status", "offline")
            lat = n.get("latency_ms", -1.0)
            if status == "online" and lat >= 0:
                online_count += 1
                valid_latencies.append(lat)
                if lat < 50.0:
                    node_scores.append(100)
                elif lat < 150.0:
                    node_scores.append(85)
                elif lat < 300.0:
                    node_scores.append(70)
                elif lat < 500.0:
                    node_scores.append(50)
                else:
                    node_scores.append(30)
            else:
                node_scores.append(0)

        health_score = int(round(sum(node_scores) / len(node_scores)))
        avg_latency = round(sum(valid_latencies) / len(valid_latencies), 1) if valid_latencies else 0.0

        if online_count == len(enabled_nodes) and health_score >= 80:
            cluster_status = CLUSTER_STATUS_HEALTHY
        elif online_count > 0:
            cluster_status = CLUSTER_STATUS_DEGRADED
        else:
            cluster_status = CLUSTER_STATUS_OFFLINE

        return {
            "health_score": health_score,
            "status": cluster_status,
            "total_nodes": len(node_list),
            "online_nodes": online_count,
            "offline_nodes": len(enabled_nodes) - online_count,
            "avg_latency_ms": avg_latency,
        }

    def publish_telemetry(self) -> None:
        """Publish real-time telemetry to sensor.otis_federation_cluster and sensor.otis_federated_nodes."""
        if not hasattr(self.hass, "states") or not hasattr(self.hass.states, "async_set"):
            return

        health = self.calculate_cluster_health()
        cluster_status = health["status"]

        sanitized_nodes = []
        for n in self._nodes.values():
            node_copy = dict(n)
            if "token" in node_copy:
                node_copy["token"] = "***" if node_copy["token"] else ""
            sanitized_nodes.append(node_copy)

        total_entities = sum(n.get("entities_count", 0) for n in sanitized_nodes)

        attrs = {
            "friendly_name": "Otis Multi-Node Federation Cluster",
            "icon": "mdi:server-network",
            "health_score": health["health_score"],
            "total_nodes": health["total_nodes"],
            "online_nodes": health["online_nodes"],
            "offline_nodes": health["offline_nodes"],
            "avg_latency_ms": health["avg_latency_ms"],
            "total_federated_entities": total_entities,
            "cluster_mode": "distributed",
            "nodes": sanitized_nodes,
            "recent_remote_calls": list(self._recent_remote_calls[:10]),
            "last_sync_timestamp": self._last_sync_timestamp,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            from .sensor import async_update_entity_state
            async_update_entity_state(self.hass, SENSOR_FEDERATION_CLUSTER, cluster_status, attrs)
            async_update_entity_state(
                self.hass,
                SENSOR_FEDERATED_NODES,
                f"{health['online_nodes']}/{health['total_nodes']} Online",
                attrs,
            )
        except Exception:
            self.hass.states.async_set(SENSOR_FEDERATION_CLUSTER, cluster_status, attrs)
            self.hass.states.async_set(
                SENSOR_FEDERATED_NODES,
                f"{health['online_nodes']}/{health['total_nodes']} Online",
                attrs,
            )

    async def async_publish_telemetry(self) -> None:
        """Publish real-time telemetry (async interface)."""
        self.publish_telemetry()

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

        health = self.calculate_cluster_health()

        sanitized_nodes = []
        for n in self._nodes.values():
            node_copy = dict(n)
            if "token" in node_copy:
                node_copy["token"] = "***" if node_copy["token"] else ""
            sanitized_nodes.append(node_copy)

        total_entities = sum(n.get("entities_count", 0) for n in sanitized_nodes)

        return {
            "total_nodes": health["total_nodes"],
            "online_nodes": health["online_nodes"],
            "offline_nodes": health["offline_nodes"],
            "avg_latency_ms": health["avg_latency_ms"],
            "health_score": health["health_score"],
            "status": health["status"],
            "cluster_mode": "distributed",
            "total_federated_entities": total_entities,
            "nodes": sanitized_nodes,
            "recent_remote_calls": list(self._recent_remote_calls[:10]),
            "last_sync_timestamp": self._last_sync_timestamp,
        }

    async def async_start_background_sync(self, interval_seconds: int = 300) -> None:
        """Start non-blocking background periodic sync loop for federated edge nodes."""
        if self._sync_task and not self._sync_task.done():
            return
        self._sync_interval_seconds = interval_seconds

        async def _sync_loop() -> None:
            _LOGGER.info(
                "Starting Otis multi-node federation background sync loop (every %ds)",
                self._sync_interval_seconds,
            )
            while True:
                try:
                    await asyncio.sleep(self._sync_interval_seconds)
                    await self.async_sync_all_nodes()
                except asyncio.CancelledError:
                    _LOGGER.debug("Otis federation background sync loop cancelled")
                    break
                except Exception as err:
                    _LOGGER.warning("Error in Otis federation background sync loop: %s", err)

        try:
            loop = asyncio.get_running_loop()
            self._sync_task = loop.create_task(_sync_loop())
        except RuntimeError:
            self._sync_task = asyncio.create_task(_sync_loop())

    async def async_stop_background_sync(self) -> None:
        """Stop background synchronization loop gracefully."""
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except (asyncio.CancelledError, Exception):
                pass
            self._sync_task = None
            _LOGGER.debug("Stopped Otis federation background sync loop")
