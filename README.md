# Otis AI Companion: Home Assistant Custom Integration

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-41BDF5?logo=home-assistant&logoColor=white&style=flat)](https://www.home-assistant.io/)
[![HACS Badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://hacs.xyz)
[![HA installs](https://img.shields.io/badge/dynamic/json?url=https://analytics.home-assistant.io/custom_integrations.json&query=$.otis-ai-companion.total&label=Installs&color=41BDF5)](https://analytics.home-assistant.io/custom_integrations.json)
[![License: MIT](https://img.shields.io/badge/License-MIT-e0b416.svg)](https://github.com/OtisPresley/otis-ai-companion/blob/main/LICENSE)
[![hassfest](https://img.shields.io/github/actions/workflow/status/OtisPresley/otis-ai-companion/hassfest.yaml?branch=main&label=hassfest)](https://github.com/OtisPresley/otis-ai-companion/actions/workflows/hassfest.yaml)
[![HACS](https://img.shields.io/github/actions/workflow/status/OtisPresley/otis-ai-companion/hacs.yaml?branch=main&label=HACS)](https://github.com/OtisPresley/otis-ai-companion/actions/workflows/hacs.yaml)
[![CI](https://img.shields.io/github/actions/workflow/status/OtisPresley/otis-ai-companion/ci.yaml?branch=main&event=push)](https://github.com/OtisPresley/otis-ai-companion/actions/workflows/ci.yaml)

**Otis AI Companion** is an autonomous smart home co-pilot, spatial intelligence engine, and self-healing system administrator for **Home Assistant**.

It replaces fragile Jinja2 templates, hardcoded entity mappings, and rigid automations with a high-performance, asynchronous, local-first intelligence architecture:

---

## 📖 Table of Contents

- [✨ Core Highlights](#-core-highlights)
- [🏛️ Architectural Overview](#️-architectural-overview)
- [🗺️ Spatial Graph & Interactive Floor Plan](#️-spatial-graph--interactive-floor-plan)
- [📦 Installation](#-installation)
  - [HACS (Recommended)](#hacs-recommended)
  - [Manual Installation](#manual-installation)
- [📘 Documentation & Wiki](#-documentation--wiki)
- [⚡ Proactive Suggestions & 1-Click Operations](#-proactive-suggestions--1-click-operations)
- [🔊 Media Architecture & Dynamic Speaker Routing](#-media-architecture--dynamic-speaker-routing)
- [🏷️ Services Reference](#️-services-reference)
- [🎛️ Otis Companion Lovelace Card](#️-otis-companion-lovelace-card)
- [🧪 Testing & Validation](#-testing--validation)
- [🔧 Troubleshooting & Support](#-troubleshooting--support)
- [🛣️ Changelog & Project Links](#️-changelog--project-links)

---

## ✨ Core Highlights

- 🗺️ **Zero-Hardcoding Spatial Intelligence (Phase 1 & 4)**: Dynamically discovers Area, Device, and Entity registries. Maintains an in-memory physical topological adjacency graph with Breadth-First Search (BFS) pathfinding between rooms. Full visual canvas editor (`mode: "floorplan_studio"`) with drag-and-drop pin repositioning and interactive boundary resizing.
- 🎨 **Dynamic AI Themes Studio (Phase 2)**: Natural language theme generator synthesizing modern CSS variables with instant zero-profile-switching live activation and robust dark/light contrast.
- 🛡️ **Otis Sentinel Watchdog & Self-Healing (Phase 3)**: Continuous background telemetry watchdog monitoring battery depletion, short-cycling climate compressors, unattended garage doors, and failed integrations with 1-click atomic remediation.
- ⚡ **Dynamic Macro Orchestrator & Assist Pipelines (Phase 5)**: Multi-step atomic lifestyle macros (Movie Night, Goodnight, Party Mode, Lockdown) with prior state snapshotting, pre-flight safety gates, and 1-click state rollback.
- 🔊 **Voice Feedback & Dynamic Audio Follow-Me (Phase 6)**: Presence-based TTS notifications (`notify_router`) and seamless multi-room audio handoff across matrix amplifiers (e.g. Control4) with idle amplifier power guards.
- ⚡ **Energy & Predictive Load Orchestrator (Phase 7)**: TOU tariff awareness, solar surplus utilization, battery/UPS storage monitoring, and tiered dynamic load shedding during grid peak hours.
- 👁️ **Multi-Modal Vision & Presence Intelligence (Phase 8)**: Multi-sensor room occupancy fusion combining mmWave radar, PIR, media playback, and micro-BLE beacons; RTSP camera stream deduplication and Gemini Vision anomaly detection.
- 🔄 **Self-Supervised Habit Learning & Behavioral Modeling (Phase 9)**: Non-blocking SQLite recorder habit sequence mining, habit deviation guards (e.g. missed bedtime routine), and dynamic circadian lighting & seasonal temperature curves.
- 🌐 **Autonomous Home Commissioning & Multi-Node Federation (Phase 10)**: Zero-config heuristic spatial assignment for unassigned entities and multi-instance Home Assistant edge node synchronization with remote service orchestration.
- 💬 **Assist AI Co-Pilot with Real-Time Audio Streaming**: Interactive multi-turn chat co-pilot (`otis_ai.chat`) with direct Web Speech microphone input, 5-bar animated audio waveform visualizer, and instant Markdown live preview.

<div align="center">
  <img width="900" alt="image" src="https://github.com/user-attachments/assets/317266e6-1470-4d90-afa9-5f7f0432de53" />
</div>

---

## 🏛️ Architectural Overview

Otis AI Companion is structured into modular, asynchronous subsystems:

<p align="center">
  <img alt="Otis AI Architecture" src="https://raw.githubusercontent.com/wiki/OtisPresley/otis-ai-companion/images/system-architecture.png" width="850" />
</p>

---

## 🗺️ Spatial Graph & Interactive Floor Plan

Otis AI models your home as an undirected adjacency graph where rooms connect via doors, open transitions, hallways, and stairs:

<p align="center">
  <img alt="Spatial Adjacency Graph" src="https://raw.githubusercontent.com/wiki/OtisPresley/otis-ai-companion/images/spatial-adjacency-graph.png" width="850" />
</p>

### Multimodal Video Walkthrough
1. **Record**: Walk through your home with your smartphone, speaking room names as you cross thresholds.
2. **Upload**: Drag and drop `.mp4`, `.mov`, or `.webm` files directly into the Floor Plan upload modal.
3. **Synthesis**: Otis AI extracts container audio with FFmpeg, transcribes spoken room sequences with Gemini, calculates architectural footprints, and renders an interactive SVG floor plan with clickable light and switch badges.

---

## 📦 Installation

### HACS (Recommended)

1. In the Home Assistant UI, navigate to **HACS → Integrations**.
2. Click the three vertical dots in the top right corner and select **Custom Repositories**.
3. Under **Repository**, enter:
   ```text
   https://github.com/OtisPresley/otis-ai-companion
   ```
4. Set **Category** to **Integration** and click **Add**.
5. Find **Otis AI Companion** in the catalog and click **Download**.
6. **Restart Home Assistant**.
7. Navigate to **Settings → Devices & Services → Add Integration** and select **Otis AI Companion**.

---

### Manual Installation

1. Copy the contents of `custom_components/otis_ai` into your Home Assistant installation folder under `/config/custom_components/otis_ai`.
2. **Restart Home Assistant**:
   ```bash
   ha core restart
   ```
3. Go to **Settings → Devices & Services → Add Integration** and select **Otis AI Companion**.

---

## 📘 Documentation & Wiki

Exhaustive, step-by-step guides and architectural references are available in the **[GitHub Wiki](https://github.com/OtisPresley/otis-ai-companion/wiki)**:

- 🏠 **[Overview & Architecture](https://github.com/OtisPresley/otis-ai-companion/wiki/Home)** – Vision, subsystem breakdown, and capabilities summary.
- 📦 **[Installation & Prerequisites](https://github.com/OtisPresley/otis-ai-companion/wiki/Installation)** – Host setup, FFmpeg requirements, HACS onboarding, and verification.
- ⚙️ **[Integration Configuration](https://github.com/OtisPresley/otis-ai-companion/wiki/Integration-Configuration)** – Options flow, LLM provider failover cascade, backup detection, and sensitivity thresholds.
- 🗺️ **[Spatial Topology & Floor Plan](https://github.com/OtisPresley/otis-ai-companion/wiki/Spatial-and-Floorplan)** – Adjacency graphs, BFS pathfinding, video walkthrough recording guide, and SVG layout engine.
- 🔄 **[Automation & Habit Mining](https://github.com/OtisPresley/otis-ai-companion/wiki/Automation-and-Habit-Mining)** – Non-blocking SQLite mining, temporal sequence clustering, actuator safety gates, and scoped YAML repairs.
- 🔊 **[Media & Speaker Routing](https://github.com/OtisPresley/otis-ai-companion/wiki/Media-and-Speaker-Routing)** – Presence-based `notify_router`, VLC Telnet synchronization, and Control4 multi-zone matrix idle power guards.
- 🛡️ **[Diagnostics & System Health](https://github.com/OtisPresley/otis-ai-companion/wiki/Diagnostics-and-System-Health)** – Smart Home Maturity Score, pre-flight safety gates, orphan entity cleanup, and supervisor rollback.
- 🎛️ **[Lovelace Card Guide](https://github.com/OtisPresley/otis-ai-companion/wiki/Lovelace-Card)** – 6 theme presets (`ha_native` default), Web Speech microphone input, live markdown preview, and card-mod CSS custom properties.
- 🏷️ **[Services Reference](https://github.com/OtisPresley/otis-ai-companion/wiki/Services)** – Complete parameter specifications and YAML examples for all registered integration services.
- ❓ **[Troubleshooting & Diagnostic Workflows](https://github.com/OtisPresley/otis-ai-companion/wiki/Troubleshooting)** – Resolving walkthrough upload failures, audio playback delays, and database query optimizations.
- 📖 **[Frequently Asked Questions](https://github.com/OtisPresley/otis-ai-companion/wiki/FAQ)** – Privacy, local-first architecture, LLM token usage, and dashboard deletion.

---

## ⚡ Proactive Suggestions & 1-Click Operations

The background discovery engine continuously evaluates system state and delivers actionable suggestions:

* **Habit Routines**: Discovered recurring patterns ready to activate as native automations.
* **Orphan Entity Cleanup**: 1-click batch removal of obsolete entities from uninstalled integrations while protecting offline battery sensors.
* **Automation Upgrades**: Surgical repair of broken entity IDs, line-wrapped strings, and upgrades from `mode: single` to `mode: queued`.
* **Area Auto-Assignment**: Automatic inference and assignment of unassigned entities to physical rooms.

---

## 🔊 Media Architecture & Dynamic Speaker Routing

Otis AI routes audio intelligently based on live room occupancy:

```yaml
# Example: Presence-Aware Text-to-Speech via notify_router
action: script.notify_router
data:
  message: "Front gate motion detected."
  title: "Perimeter Alert"
  notify_router: true
  wait_for_idle: true
```

* **Targeted Audio**: Broadcasts only to rooms where motion or radar presence is currently active.
* **Idle Power Guard**: Monitors multi-zone matrix amplifiers (e.g. Control4) and powers down idle amplifier output zones when playback ceases.

---

## 🏷️ Services Reference

Otis AI Companion provides **41 registered services** structured by architectural subsystem:

### 1. AI Co-Pilot & Suggestion Engine
| Service Name | Description | Example Target |
| :--- | :--- | :--- |
| `otis_ai.chat` | Multi-turn conversational query with spatial context and LLM failover. | `text: "Turn off lights in vacant rooms"` |
| `otis_ai.get_capability_map` | Retrieve system maturity score, active entities, and suggestions. | `response_variable: capabilities` |
| `otis_ai.get_suggestions` | Retrieve active proactive recommendations feed. | `response_variable: suggestions` |
| `otis_ai.apply_suggestion` | Execute recommendation (YAML automation, script, or cleanup). | `data: { suggestion_id: "..." }` |

### 2. Spatial Topology & Floor Plan Studio
| Service Name | Description | Example Target |
| :--- | :--- | :--- |
| `otis_ai.get_spatial_map` | Retrieve room adjacency topology and connection types. | `response_variable: spatial_graph` |
| `otis_ai.update_spatial_map` | Connect or disconnect physical rooms. | `data: { area_1: "foyer", area_2: "study" }` |
| `otis_ai.generate_floorplan` | Synthesize an interactive vector SVG floor plan. | `data: { theme: "cyberpunk" }` |
| `otis_ai.update_floorplan_layout`| Update floor plan room bounds, dimensions, and device pin coordinates. | `data: { updates: [...] }` |

### 3. Dynamic Themes & Dashboard Studio
| Service Name | Description | Example Target |
| :--- | :--- | :--- |
| `otis_ai.generate_theme` | Synthesize custom CSS theme from natural language prompt. | `data: { prompt: "Deep space obsidian with neon cyan" }` |
| `otis_ai.apply_theme` | Apply theme globally or to a specific user profile. | `data: { theme_name: "cyberpunk" }` |
| `otis_ai.list_themes` | List all available built-in presets and user-created themes. | `response_variable: themes` |
| `otis_ai.delete_theme` | Remove a previously saved custom theme. | `data: { theme_name: "custom_theme" }` |
| `otis_ai.create_command_center`| Provision user Command Center and admin Otis AI dashboards. | `data: { mode: "command_center" }` |
| `otis_ai.sync_dashboards` | Resynchronize dashboard views and subviews with Home Assistant. | `data: { force_overwrite: false }` |

### 4. Otis Sentinel Watchdog & Self-Healing
| Service Name | Description | Example Target |
| :--- | :--- | :--- |
| `otis_ai.run_sentinel_watchdog`| Run full system diagnostic audit across climate, battery, security, and integrations. | `response_variable: anomalies` |
| `otis_ai.remediate_anomaly` | Execute 1-click self-healing remediation for a detected anomaly. | `data: { anomaly_id: "..." }` |
| `otis_ai.get_sentinel_telemetry`| Retrieve health score, active anomalies, and remediation history. | `response_variable: telemetry` |
| `otis_ai.ignore_sentinel_alert`| Mute a specific alert or category (e.g., low battery, offline node). | `data: { anomaly_id: "...", category: "battery" }` |

### 5. Dynamic Macro Orchestrator
| Service Name | Description | Example Target |
| :--- | :--- | :--- |
| `otis_ai.execute_macro` | Execute multi-step atomic macro with prior state snapshotting. | `data: { macro_name: "movie_night" }` |
| `otis_ai.rollback_macro` | Roll back most recent macro and restore entities to prior states. | `data: { macro_id: "..." }` |
| `otis_ai.list_macros` | List built-in macro templates and recent execution history. | `response_variable: macros` |

### 6. Voice Feedback & Multi-Room Audio Routing
| Service Name | Description | Example Target |
| :--- | :--- | :--- |
| `otis_ai.audio_handoff` | Transfer or follow media stream between source and target rooms. | `data: { source_area: "living_room", target_area: "patio" }` |
| `otis_ai.media_follow_me` | Follow user media playback as they move across rooms. | `data: { target_area: "kitchen" }` |
| `otis_ai.release_idle_sources` | Power down idle multi-zone amplifier channels and matrix streamers. | `data: { idle_threshold_minutes: 15 }` |
| `otis_ai.notify_voice` | Broadcast targeted presence-aware TTS announcement via `notify_router`. | `data: { message: "Front gate open", area_id: "office" }` |

### 7. Energy & Predictive Load Orchestrator
| Service Name | Description | Example Target |
| :--- | :--- | :--- |
| `otis_ai.get_energy_summary` | Discover power meters, solar surplus, battery state, and TOU tariff period. | `response_variable: energy_summary` |
| `otis_ai.load_shed` | Dynamically shed Tier 1 (EV, pool) or Tier 2 (climate, AV) electrical loads. | `data: { tier: 1 }` |
| `otis_ai.restore_shed_loads` | Restore previously shed appliances and HVAC setpoints. | `data: { tier: 1 }` |

### 8. Multi-Modal Vision & Presence Intelligence
| Service Name | Description | Example Target |
| :--- | :--- | :--- |
| `otis_ai.get_presence_states` | Return fused occupancy probabilities (mmWave + PIR + media + BLE) per room. | `response_variable: presence` |
| `otis_ai.analyze_camera` | Capture camera snapshot and analyze visual scene via Gemini Vision. | `data: { camera_entity_id: "camera.frontdoor" }` |
| `otis_ai.evaluate_contextual_alerts`| Evaluate perimeter security context and suspicious occupancy anomalies. | `response_variable: alerts` |

### 9. Self-Supervised Habit Learning & Behavioral Modeling
| Service Name | Description | Example Target |
| :--- | :--- | :--- |
| `otis_ai.mine_habits` | Mine SQLite recorder transitions for recurring routine proposals. | `data: { days: 14, min_occurrences: 3 }` |
| `otis_ai.get_circadian_curves` | Compute dynamic solar circadian lighting and seasonal climate curves. | `response_variable: curves` |
| `otis_ai.audit_habit_deviations`| Audit home state against behavioral baselines (e.g. Missed bedtime). | `response_variable: deviations` |

### 10. Autonomous Home Commissioning & Multi-Node Federation
| Service Name | Description | Example Target |
| :--- | :--- | :--- |
| `otis_ai.audit_unassigned_entities`| Audit unassigned entities and infer room mappings with confidence scores. | `response_variable: audit` |
| `otis_ai.auto_commission_entities`| 1-click batch assign eligible unassigned entities into their rooms. | `data: { min_confidence: 0.85 }` |
| `otis_ai.register_federated_node`| Register remote Home Assistant edge node with host, port, and token. | `data: { node_id: "guest_house", host: "10.0.12.247" }` |
| `otis_ai.remove_federated_node` | Unregister a remote federated node. | `data: { node_id: "guest_house" }` |
| `otis_ai.sync_federated_nodes` | Synchronize state machines from all registered satellite nodes. | `data: { node_id: "all" }` |
| `otis_ai.call_remote_service` | Execute a Home Assistant service call on a satellite edge node. | `data: { node_id: "guest_house", domain: "light", service: "turn_off" }` |
| `otis_ai.get_federation_status` | Retrieve connectivity, latency, entity counts, and version across nodes. | `response_variable: status` |

---

## 🎛️ Otis Companion Lovelace Card

The custom Lovelace card (`custom:otis-companion-card`) provides an interactive interface for dashboards:

```yaml
type: custom:otis-companion-card
theme_preset: ha_native
max_suggestions: 10
show_stats: true
show_suggestions: true
show_chat: true
```

### Features:
* **6 Theme Presets**: `ha_native` (Default, follows HA theme), `cyberpunk`, `midnight`, `emerald`, `sunset`, and `light_frost`.
* **Voice Speech Input**: Built-in microphone streaming with a 5-bar animated audio waveform equalizer.
* **Live Markdown Preview**: Auto-expanding live markdown preview above the chat input box.
* **Visual Card Editor**: Complete visual configuration via Home Assistant's dashboard editor.

---

## 🧪 Testing & Validation

Otis AI Companion includes a comprehensive test suite running against an asynchronous mock Home Assistant core:

```bash
python3 -m unittest discover tests
```

### Coverage (85/85 Passing):
- **Core Engine & Registries (`test_core_rebuilt.py`)**: Registry discovery, maturity scoring, BFS spatial pathfinding, floor plan rendering, themes, Sentinel watchdog, and atomic macros.
- **Vision & Presence Fusion (`test_vision_presence.py`)**: mmWave + PIR + media fusion, camera stream deduplication, and Gemini Vision anomaly detection.
- **Habit Learning & Behavioral Modeling (`test_habit_manager.py`)**: SQLite recorder mining, habit routine clustering, bedtime deviation guards, and circadian curves.
- **Autonomous Commissioning & Federation (`test_node_federation_commissioning.py`)**: Zero-config heuristic room mapping, satellite node sync, and remote service proxying.

---

## 🔧 Troubleshooting & Support

- **Walkthrough Upload**: Verify that `/usr/bin/ffmpeg` is installed and that the recorded video includes an audible audio track speaking room names clearly.
- **Microphone Permissions**: Browser voice speech recognition requires an HTTPS connection or `localhost`.
- **Lovelace Cache**: After updating, perform a hard reload (`Ctrl + F5` or `Cmd + Shift + R`) to bypass cached card resources.

---

## 🛣️ Changelog & Project Links

- 📦 **[Changelog](https://github.com/OtisPresley/otis-ai-companion/blob/main/CHANGELOG.md)**: Full release notes and historical upgrades.
- 🐞 **[Issues](https://github.com/OtisPresley/otis-ai-companion/issues)**: Report bugs or request enhancements.
- 📘 **[GitHub Wiki](https://github.com/OtisPresley/otis-ai-companion/wiki)**: Complete documentation.
