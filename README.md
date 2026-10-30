# Otis AI Companion: Home Assistant Custom Integration

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-41BDF5?logo=home-assistant&logoColor=white&style=flat)](https://www.home-assistant.io/)
[![HACS Badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://hacs.xyz)
[![HA installs](https://img.shields.io/badge/dynamic/json?url=https://analytics.home-assistant.io/custom_integrations.json&query=$.otis-ai-companion.total&label=Installs&color=41BDF5)](https://analytics.home-assistant.io/custom_integrations.json)
[![Version](https://img.shields.io/badge/version-1.9.2-blue.svg)](https://github.com/OtisPresley/otis-ai-companion/blob/main/CHANGELOG.md)
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

- 🗺️ **Zero-Hardcoding Spatial Intelligence**: Dynamically discovers Area, Device, and Entity registries. Maintains an in-memory physical topological adjacency graph with Breadth-First Search (BFS) pathfinding between rooms.
- 🎥 **Multimodal Walkthrough Video-to-FloorPlan**: Record smartphone video walkthroughs of your home; the integrated pipeline parses spoken room callouts, extracts container audio via FFmpeg, transcribes transitions using Gemini, and renders interactive, multi-floor vector SVG blueprints.
- 🔄 **Non-Blocking SQLite Habit Mining**: Executes high-speed, index-assisted queries against `home-assistant_v2.db` in under **50ms** via asynchronous background workers to uncover recurring lifestyle patterns and cluster them into 1-click routine proposals.
- 🛡️ **Actuator-Verified Safety Clustering**: Enforces strict safety rules on routine proposals—requiring controllable actuators (`light`, `switch`, `media_player`, `climate`, `cover`, `lock`) and rejecting opposite-perimeter false pairings.
- 🔊 **Dynamic Presence-Based Audio Routing**: Automatically directs TTS announcements (`notify_router`) and media streams to currently occupied rooms using real-time presence sensors, with smart fallbacks and idle power guards for multi-zone matrix amplifiers (e.g. Control4).
- 📊 **Smart Home Maturity Scoring**: Continuously audits your installation across 5 core dimensions (**Spatial**, **Hygiene**, **Automations**, **Security**, **Media**) with a 0–100 score and 1-click auto-assignment for unassigned devices.
- 📋 **Surgical YAML & Blueprint Repair**: Repairs broken entity typos, fixes wrapped multiline strings, corrects `input_select` whitespace mismatches, and upgrades automations from `mode: single` to `mode: queued` with scoped block protection.
- 🎛️ **Admin-Only Panel Mode Dashboard (`/otis-ai`)**: Automatically creates and synchronizes an Admin-only dashboard in full-width Panel Mode (`ha_native` theme default) with Home Assistant's live `DashboardsCollection`.
- 🧭 **Hub-and-Spoke Subview Architecture**: Generates specialized domain subviews (`subview: true`) for **Media Studio** (`/otis-ai/media`), **Security Center** (`/otis-ai/security`), **Climate & Pool** (`/otis-ai/climate`), and **Floor Plan Studio** (`/otis-ai/floorplan`) with native header back navigation (`←`) and card launchpad chips.
- 📐 **Interactive Canvas Editor & Visual Boundary Adjuster**: Floor Plan Studio provides full-width canvas editing (`mode: "floorplan_studio"`) with drag-and-drop device pin repositioning, interactive corner resize handles for room footprints, and 1-click binding to Home Assistant registered areas (`otis_ai.update_floorplan_layout`).
- 🎨 **Dynamic AI Themes with Instant Activation**: Natural language theme synthesizer with zero-profile-switching live activation and robust contrast variables across dark and light palettes.
- ⚡ **Dynamic Macro Orchestrator & Atomic Rollback**: Multi-step conversational pipelines (Movie Night, Goodnight Routine, Party Mode, Lockdown, Welcome Home) with automatic pre-flight safety checks and 1-click state rollback.
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

| Service Name | Description | Example Target |
| :--- | :--- | :--- |
| `otis_ai.chat` | Conversational query with spatial context and LLM failover. | `text: "Turn off lights in vacant rooms"` |
| `otis_ai.get_capability_map` | Retrieve system maturity score, active entities, and suggestions. | `response_variable: capabilities` |
| `otis_ai.get_suggestions` | Retrieve active proactive recommendations. | `response_variable: suggestions` |
| `otis_ai.apply_suggestion` | Execute a recommendation (YAML automation, script, or cleanup). | `data: { suggestion_id: "..." }` |
| `otis_ai.get_spatial_map` | Retrieve room adjacency topology and connection types. | `response_variable: spatial_graph` |
| `otis_ai.update_spatial_map` | Connect or disconnect physical rooms. | `data: { area_1: "foyer", area_2: "study" }` |
| `otis_ai.generate_floorplan` | Synthesize an interactive vector SVG floor plan. | `data: { theme: "cyberpunk" }` |
| `otis_ai.execute_macro` | Execute multi-step atomic macro with prior state snapshot. | `data: { macro_name: "movie_night" }` |
| `otis_ai.rollback_macro` | Roll back most recent macro and restore entities to prior states. | `data: { macro_id: "..." }` |
| `otis_ai.list_macros` | List built-in macro templates and recent execution history. | `response_variable: macros` |

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

Otis AI Companion includes a unit-testing suite running against an asynchronous mock Home Assistant core:

```bash
python3 -m pytest tools/test_core_rebuilt.py
```

### Coverage (32/32 Passing):
- DiscoveryEngine registry traversal, orphan filtering, and maturity score calculation.
- SpatialGraphManager adjacency topologies, BFS shortest path, and room transition updates.
- AutomationManager scoped multiline regex string repair and mode upgrades.
- DashboardManager in-memory `DashboardsCollection` synchronization and panel view mounting.
- Multi-agent failover cascade across Gemini, OpenAI, and local LLMs.
- Walkthrough audio extraction and SVG layout generation.

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
