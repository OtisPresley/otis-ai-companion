# 🤖 Otis AI Companion Documentation

Welcome to the comprehensive user guide and reference manual for **Otis AI Companion**—an autonomous smart home co-pilot, spatial intelligence engine, and self-healing system administrator for **Home Assistant**.

This wiki is your complete documentation for:
- 🧠 The **Otis AI Home Assistant Integration** (`custom_components/otis_ai`)
- 🎛️ The custom **Otis Companion Lovelace Card** (`otis-companion-card.js`)
- 🗺️ The **Spatial Adjacency Graph & Vector Floor Plan Engine**
- 🔄 The **Habit Mining & Autonomous Automation Engine**
- 🔊 The **Presence-Aware Audio & Speaker Routing Architecture**

---

## ✨ Core Highlights

Otis AI Companion replaces fragile Jinja2 templates, hardcoded entity mappings, and rigid automations with a local-first, proactive intelligence engine:

* 🗺️ **Zero-Hardcoding Spatial Graph**: Discovers all areas, devices, and entities dynamically. Maintains a physical topological adjacency graph with Breadth-First Search (BFS) pathfinding between rooms.
* 🎥 **Walkthrough Video-to-Vector Floor Plan**: Upload mobile video walkthroughs of your home; the integrated multimodal pipeline parses spoken room callouts, transcribes audio via Gemini, calculates architectural layouts, and generates interactive SVG floor plans and Lovelace `picture-elements` YAML.
* 🔄 **SQLite Habit Mining & Routine Discovery**: Executes non-blocking historical queries against `home-assistant_v2.db` to uncover recurring lifestyle patterns (morning routines, gym transitions, bedtime habits) and proposes 1-click executable automations.
* 🛡️ **Actuator-Verified Safety Clustering**: Enforces strict safety rules on routine proposals—requiring controllable actuators (`light`, `switch`, `media_player`, `climate`, `cover`) and rejecting senseless cross-house or opposite-perimeter pairings.
* 🔊 **Contextual Audio & Speaker Routing**: Dynamically directs text-to-speech announcements (`notify_router`) and media playback to currently occupied rooms using real-time presence, with smart fallback and matrix amplifier power management.
* 📊 **Smart Home Maturity Scoring & 1-Click Repair**: Continuously audits your setup across 5 key dimensions (**Spatial**, **Hygiene**, **Automations**, **Security**, **Media**), identifying orphaned entities, broken entity typos, and unassigned devices.
* 📋 **Scoped Automation Repair**: Uses multiline regular expressions to safely fix broken YAML strings, line breaks, and mismatched `input_select` options while protecting vital triggers, conditions, and actions.
* 🎛️ **Admin-Only Co-Pilot Dashboard & Panel Mode**: Automatically creates the `/otis-ai` dashboard in full-width Panel Mode (`ha_native` theme default), synchronizing with Home Assistant's live `DashboardsCollection` so generated views can be edited or deleted cleanly.
* 💬 **Assist AI Co-Pilot with Real-Time Audio Streaming**: Interactive multi-turn chat co-pilot (`otis_ai.chat`) with direct Web Speech microphone input, 5-bar animated audio waveform visualizer, and instant Markdown live preview.

---

## 🧱 Architectural Overview

Otis AI Companion is architected as an asynchronous, non-blocking pipeline divided into specialized managers:

```
+-------------------------------------------------------------------------+
|                       HOME ASSISTANT CORE ENGINE                        |
+-------------------------------------------------------------------------+
       │                             │                             │
       ▼                             ▼                             ▼
+─────────────────+         +─────────────────+         +─────────────────+
| DiscoveryEngine |         | SpatialGraph    |         | Automation      |
| • Area/Device/  |         | • Physical area |         |   Manager       |
|   Entity scan   |         |   adjacencies   |         | • SQLite mining |
| • Orphan detect |         | • BFS routing   |         | • YAML repairs  |
| • Maturity score|         | • Walkthroughs  |         | • Mode upgrades |
+─────────────────+         +─────────────────+         +─────────────────+
       │                             │                             │
       └─────────────────────────────┼─────────────────────────────┘
                                     ▼
                   +───────────────────────────────────+
                   | DashboardManager & Frontend Card  |
                   | • Panel Mode Admin UI (/otis-ai)  |
                   | • 6 Theme Presets (ha_native)     |
                   | • Interactive SVG Floor Plan      |
                   | • Assist Co-Pilot with Live Mic   |
                   +───────────────────────────────────+
```

---

## 🧭 Subsystem Summary

| Subsystem | Primary Python Module | Key Responsibilities |
| :--- | :--- | :--- |
| **Discovery & Maturity** | `__init__.py` (`DiscoveryEngine`) | Scans registries, calculates 0–100 maturity score, detects orphans, filters disabled/unavailable entities. |
| **Spatial Graph & Floorplan** | `spatial_manager.py`, `floorplan_parser.py` | Maps physical room adjacencies, processes video walkthroughs, renders interactive SVG floor plans. |
| **Automation & Habit Mining** | `automation_manager.py`, `__init__.py` | Mines `home-assistant_v2.db` without table locks, clusters temporal routines, repairs multiline YAML typos. |
| **Dashboard Management** | `dashboard_manager.py` | Syncs in-memory `DashboardsCollection`, generates domain command centers, mounts `/otis-ai`. |
| **Media & Audio Routing** | `__init__.py`, `scripts.yaml` | Manages presence-aware TTS announcements, VLC Telnet queues, Control4 matrix amplifier power state. |
| **Frontend Lovelace Card** | `frontend/otis-companion-card.js` | Glassmorphic UI, voice recording visualizer, Markdown live preview, visual card editor. |

---

## 🚀 Quick Navigation

- **Get Started**: Follow the [Installation & Prerequisites](Installation) guide.
- **Configure Providers**: Learn about LLM and system options in [Integration Configuration](Integration-Configuration).
- **Create Your Floor Plan**: Record a walkthrough video using the [Spatial Topology & Floor Plan](Spatial-and-Floorplan) guide.
- **Understand Habit Mining**: Explore routine discovery in [Automation & Habit Mining](Automation-and-Habit-Mining).
- **Master the Card**: Customize themes and visual properties in the [Otis Companion Lovelace Card](Lovelace-Card) guide.
- **Automate with Services**: Integrate Otis into scripts with the complete [Services Reference](Services).
