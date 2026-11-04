"""Otis AI Companion: Multi-Agent Conversational Orchestration & Voice Satellites (Phase 9).

Orchestrates specialized sub-agent personas (Executive, Sentinel, Energy, Media/Spatial, Automator)
with dynamic intent routing, collaborative synthesis, and custom localized wake-word voice satellites
with spatial acoustic arbitration.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "otis_ai_voice_satellites"
STORAGE_VERSION = 1

# Specialized Agent Personas
AGENT_EXECUTIVE = "executive"
AGENT_SENTINEL = "sentinel"
AGENT_ENERGY = "energy"
AGENT_MEDIA_SPATIAL = "media_spatial"
AGENT_AUTOMATOR = "automator"

ALL_AGENTS = [
    AGENT_EXECUTIVE,
    AGENT_SENTINEL,
    AGENT_ENERGY,
    AGENT_MEDIA_SPATIAL,
    AGENT_AUTOMATOR,
]

# Collaboration Modes
COLLAB_MODE_AUTO = "auto"
COLLAB_MODE_SINGLE = "single"
COLLAB_MODE_SYNTHESIS = "collaborative_synthesis"
COLLAB_MODE_DEBATE = "debate"

# Satellite Acoustic Arbitration Modes
ARBITRATION_SPATIAL_PROXIMITY = "spatial_proximity"
ARBITRATION_SIGNAL_TO_NOISE = "signal_to_noise"
ARBITRATION_PRESENCE_FUSED = "presence_fused"

DEFAULT_DEDUPLICATION_WINDOW_S = 1.5
DEFAULT_WAKE_WORD = "Hey Otis"

AGENT_SPECIFICATIONS: dict[str, dict[str, Any]] = {
    AGENT_EXECUTIVE: {
        "name": "Otis Executive Coordinator",
        "role": "Holistic butler, conversational coordinator & general home oversight",
        "domains": {"general", "weather", "calendar", "overview", "status", "summary"},
        "system_prompt": (
            "You are the Executive Butler & Coordinator of Otis AI Companion. "
            "Coordinate whole-home operations, synthesize specialist insights, and deliver polished, "
            "actionable, and contextually grounded guidance."
        ),
        "priority": 1,
    },
    AGENT_SENTINEL: {
        "name": "Sentinel Security Specialist",
        "role": "Perimeter defense, visual intrusion tracking, access control & lock safety",
        "domains": {"alarm_control_panel", "lock", "camera", "binary_sensor", "siren", "security"},
        "system_prompt": (
            "You are the Sentinel Security Specialist of Otis AI Companion. "
            "Analyze perimeter defenses, gate/door locks, camera feeds, intrusion kinematics, "
            "and enforce rigorous household safety policies."
        ),
        "priority": 2,
    },
    AGENT_ENERGY: {
        "name": "Energy & Resource Architect",
        "role": "Solar PV, battery arbitrage, dynamic TOU tariffs, EV charging & load shedding",
        "domains": {"sensor", "switch", "energy", "solar", "battery", "tariff", "ev"},
        "system_prompt": (
            "You are the Energy & Resource Architect of Otis AI Companion. "
            "Co-optimize solar production, battery state-of-charge, wholesale electricity prices, "
            "smart EV charging dispatch, and load-shedding during peak periods."
        ),
        "priority": 3,
    },
    AGENT_MEDIA_SPATIAL: {
        "name": "Spatial Media & Presence Maestro",
        "role": "Multi-zone audio matrix, spatial audio follow-me, speaker handoff & presence fusion",
        "domains": {"media_player", "sound", "presence", "ble", "acoustic", "zone"},
        "system_prompt": (
            "You are the Spatial Media & Presence Maestro of Otis AI Companion. "
            "Manage multi-room audio matrices, seamless follow-me playback transitions, "
            "acoustic volume ducking, and Bayesian presence fusion across rooms."
        ),
        "priority": 4,
    },
    AGENT_AUTOMATOR: {
        "name": "Automation & Blueprint Engineer",
        "role": "GUI-ready Home Assistant YAML automations, habit mining & sequence verification",
        "domains": {"automation", "script", "scene", "blueprint", "routine", "yaml"},
        "system_prompt": (
            "You are the Automation & Blueprint Engineer of Otis AI Companion. "
            "Design flawless Home Assistant automations in GUI YAML format (clean top-level dict "
            "with alias, description, triggers, conditions, actions, mode), optimize routines, "
            "and eliminate automations conflicts."
        ),
        "priority": 5,
    },
}

INTENT_KEYWORD_TAXONOMY: dict[str, list[str]] = {
    AGENT_SENTINEL: [
        "security", "perimeter", "lock", "locked", "unlock", "camera", "intruder", "guard",
        "patrol", "siren", "alarm", "armed", "disarmed", "sentinel", "door", "window",
        "gate", "deadbolt", "motion alert", "visual alert", "tamper",
    ],
    AGENT_ENERGY: [
        "solar", "battery", "energy", "power", "grid", "tariff", "tou", "pricing",
        "negative price", "ev", "charging", "charger", "peak", "off-peak", "kilowatt",
        "kwh", "watts", "solar forecast", "arbitrage", "load shed",
    ],
    AGENT_MEDIA_SPATIAL: [
        "audio", "music", "play", "track", "volume", "sound", "speaker", "matrix",
        "amplifier", "follow me", "spatial", "zone", "room audio", "ducking",
        "quiet hours", "presence", "trilaterate", "acoustic",
    ],
    AGENT_AUTOMATOR: [
        "automation", "automate", "script", "routine", "blueprint", "yaml", "trigger",
        "action", "condition", "habit", "deploy automation", "create automation",
    ],
    AGENT_EXECUTIVE: [
        "status", "summary", "overview", "hello", "hi", "hey", "good morning", "good night",
        "help", "weather", "calendar", "schedule", "what's up", "house status", "system status",
    ],
}


class MultiAgentOrchestrator:
    """Orchestrates multi-agent conversations, specialized personas, and voice satellites."""

    def __init__(
        self,
        hass: HomeAssistant,
        local_llm_manager: Any = None,
        spatial_manager: Any = None,
        presence_fusion_manager: Any = None,
        audio_manager: Any = None,
        sentinel_manager: Any = None,
        energy_manager: Any = None,
        habit_manager: Any = None,
        storage_key: str = STORAGE_KEY,
    ) -> None:
        """Initialize the Multi-Agent Orchestrator."""
        self.hass = hass
        self.local_llm_manager = local_llm_manager
        self.spatial_manager = spatial_manager
        self.presence_fusion_manager = presence_fusion_manager
        self.audio_manager = audio_manager
        self.sentinel_manager = sentinel_manager
        self.energy_manager = energy_manager
        self.habit_manager = habit_manager

        self._store = Store(hass, STORAGE_VERSION, storage_key)
        self._satellite_configs: dict[str, dict[str, Any]] = {}

        self._metrics = {
            "total_requests": 0,
            "single_agent_routes": 0,
            "multi_agent_collaborations": 0,
            "delegated_actions_count": 0,
            "total_latency_ms": 0.0,
            "average_latency_ms": 0.0,
        }
        self._last_routing: dict[str, Any] = {}
        self._last_arbitration: dict[str, Any] = {}
        self._initialized = False

    async def async_load(self) -> None:
        """Load stored satellite configurations."""
        try:
            stored = await self._store.async_load()
            if stored and isinstance(stored, dict):
                self._satellite_configs = stored.get("satellites", {})
                _LOGGER.debug(
                    "Loaded %d stored voice satellite configurations",
                    len(self._satellite_configs),
                )
        except Exception as err:
            _LOGGER.warning("Could not load voice satellite configurations: %s", err)
            self._satellite_configs = {}
        self._initialized = True
        await self.async_publish_telemetry()

    async def async_save(self) -> None:
        """Save satellite configurations to persistent store."""
        try:
            await self._store.async_save({"satellites": self._satellite_configs})
        except Exception as err:
            _LOGGER.error("Failed to save voice satellite configurations: %s", err)

    def classify_intent(self, text: str) -> list[str]:
        """Classify user natural language prompt into one or more specialist agent personas."""
        clean = (text or "").strip().lower()
        if not clean:
            return [AGENT_EXECUTIVE]

        scores: dict[str, int] = {agent: 0 for agent in ALL_AGENTS}

        for agent_id, keywords in INTENT_KEYWORD_TAXONOMY.items():
            for kw in keywords:
                if " " in kw:
                    if kw in clean:
                        scores[agent_id] += 3
                else:
                    words = set(clean.split())
                    if kw in words or any(w.startswith(kw) for w in words):
                        scores[agent_id] += 1

        # Check for multi-domain queries
        matched = [agent for agent, score in scores.items() if score > 0]
        if not matched:
            return [AGENT_EXECUTIVE]

        # Sort matching agents by score descending, then by priority
        matched.sort(
            key=lambda a: (scores[a], -AGENT_SPECIFICATIONS[a]["priority"]),
            reverse=True,
        )

        top_agent = matched[0]
        top_score = scores[top_agent]

        if top_agent == AGENT_EXECUTIVE and (len(matched) == 1 or top_score > scores[matched[1]]):
            return [AGENT_EXECUTIVE]

        specialists = [a for a in matched if a != AGENT_EXECUTIVE]
        if specialists:
            return specialists

        return [AGENT_EXECUTIVE]

    async def async_orchestrate(
        self,
        prompt: str,
        conversation_id: str | None = None,
        requested_agents: list[str] | None = None,
        mode: str = COLLAB_MODE_AUTO,
        context: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Orchestrate conversational multi-agent routing and collaborative synthesis."""
        start_time = time.monotonic()
        clean_prompt = (prompt or "").strip()

        # 1. Determine target agent personas
        if requested_agents:
            selected_agents = [a for a in requested_agents if a in ALL_AGENTS]
            if not selected_agents:
                selected_agents = [AGENT_EXECUTIVE]
        elif mode == COLLAB_MODE_SINGLE:
            classified = self.classify_intent(clean_prompt)
            selected_agents = [classified[0]]
        else:
            selected_agents = self.classify_intent(clean_prompt)

        is_collaboration = len(selected_agents) > 1 and mode != COLLAB_MODE_SINGLE

        # 2. Gather agent contributions
        agent_responses: dict[str, Any] = {}
        executed_actions: list[dict[str, Any]] = []

        if not is_collaboration:
            agent_id = selected_agents[0]
            resp = await self._async_invoke_specialist(
                agent_id=agent_id,
                prompt=clean_prompt,
                conversation_id=conversation_id,
                context=context,
                timeout=timeout,
            )
            agent_responses[agent_id] = resp
            synthesized_speech = resp.get("response", "")
            executed_actions.extend(resp.get("actions", []))
            self._metrics["single_agent_routes"] += 1
        else:
            # Multi-agent collaborative synthesis
            tasks = [
                self._async_invoke_specialist(
                    agent_id=a,
                    prompt=clean_prompt,
                    conversation_id=conversation_id,
                    context=context,
                    timeout=timeout,
                )
                for a in selected_agents
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for a, res in zip(selected_agents, results, strict=False):
                if isinstance(res, Exception):
                    _LOGGER.warning("Specialist agent %s encountered error: %s", a, res)
                    agent_responses[a] = {"error": str(res), "response": f"Specialist {a} was unavailable."}
                else:
                    agent_responses[a] = res
                    executed_actions.extend(res.get("actions", []))

            # Synthesize cohesive response
            synthesized_speech = self._synthesize_multi_agent_responses(
                prompt=clean_prompt,
                agent_responses=agent_responses,
            )
            self._metrics["multi_agent_collaborations"] += 1

        duration_ms = (time.monotonic() - start_time) * 1000.0
        self._metrics["total_requests"] += 1
        self._metrics["total_latency_ms"] += duration_ms
        self._metrics["average_latency_ms"] = round(
            self._metrics["total_latency_ms"] / self._metrics["total_requests"], 2
        )
        self._metrics["delegated_actions_count"] += len(executed_actions)

        primary_agent = selected_agents[0]
        self._last_routing = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": clean_prompt[:120],
            "selected_agents": selected_agents,
            "primary_agent": primary_agent,
            "mode": "collaboration" if is_collaboration else "single",
            "latency_ms": round(duration_ms, 2),
            "executed_actions_count": len(executed_actions),
        }

        await self.async_publish_telemetry()

        return {
            "success": True,
            "query": clean_prompt,
            "selected_agents": selected_agents,
            "primary_agent": primary_agent,
            "is_collaboration": is_collaboration,
            "agent_responses": agent_responses,
            "synthesized_response": synthesized_speech,
            "executed_actions": executed_actions,
            "latency_ms": round(duration_ms, 2),
        }

    async def _async_invoke_specialist(
        self,
        agent_id: str,
        prompt: str,
        conversation_id: str | None,
        context: dict[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        """Invoke an individual specialist persona with localized domain grounding."""
        spec = AGENT_SPECIFICATIONS.get(agent_id, AGENT_SPECIFICATIONS[AGENT_EXECUTIVE])
        actions: list[dict[str, Any]] = []

        # Domain-specific telemetries and actions
        domain_insights = []

        if agent_id == AGENT_SENTINEL:
            if self.sentinel_manager:
                try:
                    perim = await self.sentinel_manager.async_audit_perimeter()
                    unlocked = perim.get("unlocked_doors", [])
                    if unlocked:
                        domain_insights.append(f"Perimeter: {len(unlocked)} unsecured lock(s) identified ({', '.join(unlocked)}).")
                    else:
                        domain_insights.append("Perimeter: All exterior entryways and deadbolts are secured.")
                except Exception as err:
                    _LOGGER.debug("Sentinel audit context notice: %s", err)

        elif agent_id == AGENT_ENERGY:
            if self.energy_manager:
                try:
                    topo = self.energy_manager.discover_energy_topology()
                    solar_w = topo.get("current_solar_power_w", 0.0)
                    batt_soc = topo.get("battery_average_soc", 100.0)
                    domain_insights.append(f"Energy: Solar generation is {int(solar_w)}W with battery reserve at {batt_soc:.0f}%.")
                except Exception as err:
                    _LOGGER.debug("Energy topology context notice: %s", err)

        elif agent_id == AGENT_MEDIA_SPATIAL:
            if self.presence_fusion_manager:
                try:
                    summary = self.presence_fusion_manager.get_presence_summary()
                    occ = summary.get("occupied_areas", [])
                    if occ:
                        domain_insights.append(f"Spatial: Active presence detected in {', '.join(occ)}.")
                except Exception as err:
                    _LOGGER.debug("Presence summary context notice: %s", err)

        # Generate response using local LLM if available, otherwise domain-grounded synthesis
        if self.local_llm_manager and getattr(self.local_llm_manager, "model", None):
            try:
                system_prompt = (
                    f"{spec['system_prompt']} "
                    f"Relevant telemetry: {' '.join(domain_insights)} "
                    "Respond concisely and actionably in 1-2 sentences."
                )
                res = await self.local_llm_manager.async_generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    timeout=min(timeout, 15.0),
                )
                if res.get("success") and res.get("response"):
                    return {
                        "agent": agent_id,
                        "name": spec["name"],
                        "response": res["response"].strip(),
                        "insights": domain_insights,
                        "actions": actions,
                    }
            except Exception as llm_err:
                _LOGGER.debug("Local LLM specialist generation notice: %s", llm_err)

        # Fallback domain-grounded synthesis
        telemetry_str = f" ({' '.join(domain_insights)})" if domain_insights else ""
        text_response = f"{spec['name']}: Acknowledged request regarding '{prompt}'{telemetry_str}."

        return {
            "agent": agent_id,
            "name": spec["name"],
            "response": text_response,
            "insights": domain_insights,
            "actions": actions,
        }

    def _synthesize_multi_agent_responses(
        self,
        prompt: str,
        agent_responses: dict[str, dict[str, Any]],
    ) -> str:
        """Synthesize multiple specialist agent contributions into a cohesive executive response."""
        parts: list[str] = [f"**Otis Multi-Agent Synthesis** for '{prompt}':\n"]

        for agent_id, resp in agent_responses.items():
            name = resp.get("name") or AGENT_SPECIFICATIONS.get(agent_id, {}).get("name", agent_id)
            speech = resp.get("response", "").strip()
            if speech:
                parts.append(f"• **{name}**: {speech}")

        return "\n".join(parts)

    # -------------------------------------------------------------------------
    # Voice Satellites & Localized Wake-Word Management
    # -------------------------------------------------------------------------

    def get_discovered_satellites(self) -> list[dict[str, Any]]:
        """Discover live assist_satellite entities and blend with persistent configuration."""
        results: list[dict[str, Any]] = []
        live_satellites = self.hass.states.async_all("assist_satellite")

        for state in live_satellites:
            eid = state.entity_id
            cfg = self._satellite_configs.get(eid, {})
            attrs = state.attributes or {}

            area_id = cfg.get("area_id") or attrs.get("area_id")
            if not area_id and self.spatial_manager:
                area_id = self.spatial_manager.get_entity_area(eid)

            results.append({
                "entity_id": eid,
                "name": attrs.get("friendly_name", eid),
                "state": state.state,
                "area_id": area_id or "unassigned",
                "assigned_agent": cfg.get("assigned_agent", AGENT_EXECUTIVE),
                "wake_word": cfg.get("wake_word", DEFAULT_WAKE_WORD),
                "wake_word_engine": cfg.get("wake_word_engine", "openwakeword"),
                "preferred_speaker": cfg.get("preferred_speaker", ""),
                "custom_pipeline": cfg.get("custom_pipeline"),
                "last_triggered": cfg.get("last_triggered"),
            })

        # Also include any stored satellites that are currently offline
        for eid, cfg in self._satellite_configs.items():
            if not any(r["entity_id"] == eid for r in results):
                results.append({
                    "entity_id": eid,
                    "name": cfg.get("name", eid),
                    "state": "unavailable",
                    "area_id": cfg.get("area_id", "unassigned"),
                    "assigned_agent": cfg.get("assigned_agent", AGENT_EXECUTIVE),
                    "wake_word": cfg.get("wake_word", DEFAULT_WAKE_WORD),
                    "wake_word_engine": cfg.get("wake_word_engine", "openwakeword"),
                    "preferred_speaker": cfg.get("preferred_speaker", ""),
                    "custom_pipeline": cfg.get("custom_pipeline"),
                    "last_triggered": cfg.get("last_triggered"),
                })

        return results

    async def async_configure_satellite(
        self,
        satellite_id: str,
        area_id: str | None = None,
        assigned_agent: str | None = None,
        wake_word: str | None = None,
        wake_word_engine: str | None = None,
        preferred_speaker: str | None = None,
        custom_pipeline: str | None = None,
    ) -> dict[str, Any]:
        """Configure localized wake-word, area, persona, and output speaker for a voice satellite."""
        norm_id = satellite_id.strip()
        if not norm_id.startswith("assist_satellite.") and "." not in norm_id:
            norm_id = f"assist_satellite.{norm_id}"

        cfg = self._satellite_configs.setdefault(norm_id, {})
        if area_id is not None:
            cfg["area_id"] = area_id.strip()
        if assigned_agent is not None:
            cfg["assigned_agent"] = assigned_agent.strip() if assigned_agent in ALL_AGENTS else AGENT_EXECUTIVE
        if wake_word is not None:
            cfg["wake_word"] = wake_word.strip()
        if wake_word_engine is not None:
            cfg["wake_word_engine"] = wake_word_engine.strip()
        if preferred_speaker is not None:
            cfg["preferred_speaker"] = preferred_speaker.strip()
        if custom_pipeline is not None:
            cfg["custom_pipeline"] = custom_pipeline.strip()

        cfg["updated_at"] = datetime.now(timezone.utc).isoformat()

        await self.async_save()
        await self.async_publish_telemetry()

        return {
            "success": True,
            "satellite_id": norm_id,
            "config": cfg,
        }

    def arbitrate_satellite_audio(
        self,
        candidate_satellites: list[dict[str, Any]],
        utterance: str | None = None,
        window_s: float = DEFAULT_DEDUPLICATION_WINDOW_S,
    ) -> dict[str, Any]:
        """Acoustically arbitrate multiple concurrent satellite wake triggers using RSSI, SNR and presence."""
        if not candidate_satellites:
            return {
                "success": False,
                "error": "No candidate satellites provided for acoustic arbitration",
            }

        if len(candidate_satellites) == 1:
            sat = candidate_satellites[0]
            winner_id = sat.get("satellite_id") or sat.get("entity_id", "assist_satellite.unknown")
            return {
                "success": True,
                "winning_satellite_id": winner_id,
                "winning_area_id": sat.get("area_id", "unassigned"),
                "confidence": 1.0,
                "suppressed_satellites": [],
                "routing_decision": "Single satellite trigger; no acoustic contention.",
            }

        # Filter candidates within deduplication window
        now_ts = time.time()
        valid_candidates = []
        for c in candidate_satellites:
            ts = float(c.get("timestamp", now_ts))
            if abs(now_ts - ts) <= (window_s * 2):
                valid_candidates.append(c)

        if not valid_candidates:
            valid_candidates = candidate_satellites

        # Score each candidate:
        # Score = (normalized_rssi * 0.40) + (normalized_snr * 0.35) + (presence_bonus * 0.25)
        scored_candidates = []
        for c in valid_candidates:
            sat_id = c.get("satellite_id") or c.get("entity_id", "assist_satellite.unknown")
            area_id = c.get("area_id", "")

            # Look up configured area if missing
            if not area_id and sat_id in self._satellite_configs:
                area_id = self._satellite_configs[sat_id].get("area_id", "")

            # Normalize RSSI (-95 dBm to -35 dBm -> 0.0 to 1.0)
            raw_rssi = float(c.get("rssi", -70.0))
            rssi_norm = max(0.0, min(1.0, (raw_rssi - (-95.0)) / ((-35.0) - (-95.0))))

            # Normalize SNR (0 dB to 30 dB -> 0.0 to 1.0)
            raw_snr = float(c.get("snr", 15.0))
            snr_norm = max(0.0, min(1.0, raw_snr / 30.0))

            # Presence bonus
            presence_bonus = 0.0
            if area_id:
                # Check fused presence state
                area_slug = area_id.replace(" ", "_").lower()
                st = self.hass.states.get(f"binary_sensor.otis_presence_{area_slug}")
                if st and st.state == "on":
                    presence_bonus = 1.0
                elif self.presence_fusion_manager:
                    summary = self.presence_fusion_manager.get_presence_summary()
                    if area_id in summary.get("occupied_areas", []):
                        presence_bonus = 1.0

            total_score = (rssi_norm * 0.40) + (snr_norm * 0.35) + (presence_bonus * 0.25)
            scored_candidates.append({
                "satellite_id": sat_id,
                "area_id": area_id,
                "rssi": raw_rssi,
                "snr": raw_snr,
                "presence_bonus": presence_bonus,
                "score": round(total_score, 4),
            })

        scored_candidates.sort(key=lambda x: x["score"], reverse=True)
        winner = scored_candidates[0]
        suppressed = [c["satellite_id"] for c in scored_candidates[1:]]

        decision = (
            f"Authoritative satellite {winner['satellite_id']} selected in area '{winner['area_id'] or 'unknown'}' "
            f"(score: {winner['score']}, RSSI: {winner['rssi']} dBm, SNR: {winner['snr']} dB). "
            f"Suppressed {len(suppressed)} competing satellite(s)."
        )

        self._last_arbitration = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "winning_satellite_id": winner["satellite_id"],
            "winning_area_id": winner["area_id"],
            "confidence": winner["score"],
            "suppressed_satellites": suppressed,
            "utterance": (utterance or "")[:60],
            "candidates_count": len(scored_candidates),
        }

        # Update last_triggered on winner
        if winner["satellite_id"] in self._satellite_configs:
            self._satellite_configs[winner["satellite_id"]]["last_triggered"] = datetime.now(timezone.utc).isoformat()
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.async_save())
            except RuntimeError:
                pass

        self.publish_telemetry()

        return {
            "success": True,
            "winning_satellite_id": winner["satellite_id"],
            "winning_area_id": winner["area_id"],
            "confidence": winner["score"],
            "suppressed_satellites": suppressed,
            "scored_candidates": scored_candidates,
            "routing_decision": decision,
        }

    # -------------------------------------------------------------------------
    # Telemetry Publication
    # -------------------------------------------------------------------------

    def publish_telemetry(self) -> None:
        """Publish real-time telemetry to sensor.otis_multi_agent_orchestrator and sensor.otis_voice_satellites."""
        # 1. sensor.otis_multi_agent_orchestrator
        orch_state = "active" if self._metrics["total_requests"] > 0 else "idle"
        orch_attrs = {
            "friendly_name": "Otis Multi-Agent Orchestrator",
            "icon": "mdi:account-supervisor-circle",
            "active_agents": ALL_AGENTS,
            "primary_coordinator": AGENT_EXECUTIVE,
            "agent_specifications": AGENT_SPECIFICATIONS,
            "metrics": self._metrics,
            "last_routing": self._last_routing,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.hass.states.async_set("sensor.otis_multi_agent_orchestrator", orch_state, orch_attrs)

        # 2. sensor.otis_voice_satellites
        sats = self.get_discovered_satellites()
        sat_state = f"{len(sats)} Satellites"
        sat_attrs = {
            "friendly_name": "Otis Voice Satellites",
            "icon": "mdi:satellite-uplink",
            "total_satellites": len(sats),
            "satellites": sats,
            "arbitration_mode": ARBITRATION_PRESENCE_FUSED,
            "deduplication_window_s": DEFAULT_DEDUPLICATION_WINDOW_S,
            "last_arbitration": self._last_arbitration,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.hass.states.async_set("sensor.otis_voice_satellites", sat_state, sat_attrs)

    async def async_publish_telemetry(self) -> None:
        """Publish real-time telemetry (async interface)."""
        self.publish_telemetry()
