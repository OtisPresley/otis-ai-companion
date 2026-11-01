# Changelog

All notable changes to the Otis AI Companion integration are documented in this file.

> 📌 See also: [`ROADMAP.md`](./ROADMAP.md) for planned features and release targets.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.13] - 2026-11-01

### Fixed & Improved
- 📎 **Prevent Duplicate Clipboard Screenshot Attachments (`otis-companion-card.js`)**:
  - Eliminated redundant paste event listener on `#chat-input` that caused paste events inside the textarea to bubble up to `.chat-input-wrapper` and invoke `_handleClipboardPaste` twice.
  - Added `e.stopPropagation()` in `_handleClipboardPaste` when clipboard image attachments are processed.
  - Added deduplication safety in `_handleFilesSelected` to ensure identical file objects (same name, size, type, and payload) cannot be staged multiple times concurrently.
  - Bumped Companion Card version to v0.1.13.

---

## [0.1.12] - 2026-11-01

### Fixed & Improved
- 🤖 **Universal Automation Deployment Across All Conversation Agents (`__init__.py`, `automation_manager.py`)**:
  - Enforced strict autonomous deployment rules across all prioritized AI conversation agents (Gemini, OpenRouter, Groq, Ollama) and offline local LLMs. Models are strictly forbidden from telling users to manually edit `automations.yaml` or "do it yourself".
  - Mandated clean Home Assistant GUI Visual Automation Editor format (standalone dictionary with `alias:`, `description:`, `triggers:`/`trigger:`, `conditions:`/`condition:`, `actions:`/`action:`, `mode:` without leading dashes or `- id:`).
  - Built robust multi-format YAML extraction (`_extract_pending_items_from_speech`) supporting lists, unwrapped/wrapped dictionaries, modern plural keys (`triggers:`, `actions:`), and blueprints.
  - Added natural language deployment confirmation matching ("deploy", "apply", "create it", "install it", "yes please", "do it") and turn recovery from prior conversation history.
  - Implemented automatic speech sanitization stripping leaked manual file instructions before presentation to the user.
- 🚀 **1-Click Automation & Script Deployment Action Buttons (`otis-companion-card.js`)**:
  - Added dedicated `"🚀 Deploy & Enable Automation"` and `"🚀 Deploy & Enable Script"` action buttons to Assist Co-Pilot chat bubbles, providing instant 1-click deployment.
  - Bumped Companion Card version to v0.1.12.

---

## [0.1.11] - 2026-11-01

### Added & Improved
- 📰 **Official Home Assistant News Cards in Proactive Feed (`__init__.py`, `otis-companion-card.js`)**:
  - Implemented asynchronous live fetching and caching (6h TTL) of official Home Assistant releases and blog articles directly from `https://www.home-assistant.io/atom.xml`.
  - Added formatted news recommendation cards with article publication dates, clean summary snippets, and a dedicated `"📰 Read Full Article ↗"` action button opening the official post in a new tab.
  - Added a dedicated `"📰 Official News"` category filter pill in the Proactive Feed.
  - Fully integrated with persistent recommendation dismissal: dismissing a news card writes its unique ID to localStorage and backend rules storage, ensuring it never returns to the active feed unless explicitly restored.

---

## [0.1.10] - 2026-11-01

### Added & Improved
- 📋 **Seamless Clipboard Screenshot Paste (`otis-companion-card.js`)**:
  - Added direct clipboard image paste handler (`_handleClipboardPaste`) on the chat input textarea and container wrapper. Pasting screenshots with `Ctrl+V` automatically encodes the image and stages it into pending attachments without manual file dialogs or dragging.
- 🔄 **One-Click Turn Retry Button (`otis-companion-card.js`)**:
  - Added a `🔄 Retry` button to assistant response action bars in the Lovelace Companion Card. Allows immediately re-dispatching failed or interrupted turns with one click, preserving original prompt context and attachments.
- ⚡ **Instant Rule & Dashboard Style Synchronization (`__init__.py`, `otis-companion-card.js`)**:
  - Subscribed Lovelace card to the `"otis_ai_rules_updated"` Home Assistant bus event, ensuring prompt rules, visual styles, and dashboard behavior apply instantaneously in the background with zero page reload required.
- 🏗️ **Blueprint Automation Architecture & Logic Inspection (`automation_manager.py`, `__init__.py`)**:
  - Injected explicit architecture rules forbidding direct injection of `condition:` or `action:` blocks into `automations.yaml` for blueprint-backed automations (`use_blueprint:`).
  - Enhanced `AutomationManager.async_cross_reference` to automatically locate and read the underlying `/config/blueprints/automation/<path>` logic so Co-Pilot understands full execution flows.
  - Added proactive recommendations detecting malformed blueprint top-level injections.
- 🌡️ **Guest Mode Climate Comfort Recommendation (`__init__.py`)**:
  - Expanded proactive recommendations to check for `input_boolean.guest_mode` coordination with central upper floor climate (`climate.upstairs`), preventing uncomfortable economy setbacks when house guests are present.

---

## [0.1.9] - 2026-11-01

### Fixed & Improved
- 🛡️ **Model Scratchpad & Tool-Call Leak Sanitization (`__init__.py`)**:
  - Implemented `sanitize_model_speech()` to strip unrendered `<think>...</think>`, `</think>`, and `<tool_call>` blocks leaked by open/free models (e.g. DeepSeek-R1/V3 or Qwen on OpenRouter Free Router).
  - Enhanced `is_provider_error()` to detect raw DSML/tool call syntax (`<tool_call>`, `<|dsml|`, `_observation`, etc.). When a free router model emits broken tool call tokens instead of a valid conversational response, Otis treats it as a provider failure and transparently fails over down the cascade or to the local edge LLM (`qwen2.5:3b`).
- 🔄 **Updated Home Assistant Google Generative AI to `gemini-3.8-flash`**:
  - Migrated Home Assistant's primary `google_generative_ai_conversation` model from the deprecated `models/gemini-2.5-flash` (which began failing with HTTP 404 from Google) to `models/gemini-3.8-flash`.

---

## [0.1.8] - 2026-11-01

### Added & Improved
- 🌡️ **Grounding in Central Dual-Zone HVAC & Floor Levels (`__init__.py`)**:
  - Implemented floor level classification (`Upper Floor`, `Ground Floor`, `Outdoor`) for all areas.
  - Correctly recognized dual-zone space HVAC architecture: `climate.downstairs` (Ground Floor) and `climate.upstairs` (Upper Floor: Guest Room, Master, Gym, Study, Theater, Hallway).
  - Explicitly separated water/pool equipment (`climate.spa_thermostat`) from space heating/cooling.
  - Eliminated hallucinations of non-existent per-room climate entities (e.g. `climate.guest_room`), explicitly grounding Co-Pilot in the blueprint automations (`Climate: Thermostat Downstairs`, `Climate: Thermostat Upstairs`) driven by occupancy and sleep states.
- ⚡ **Automated Local LLM Verification & Option Switching (`services.yaml`, `__init__.py`)**:
  - Enhanced `otis_ai.pull_local_llm_model` with `test_after_pull` (default `true`) and `set_as_active` (default `true`).
  - Pulling an edge model now automatically benchmarks the model on the Ollama host, verifies readiness, updates `LocalLLMManager`, and updates integration options (`CONF_LOCAL_LLM_MODEL`) seamlessly without manual user intervention.
- 🔍 **Transparent AI Agent Attribution in Assist Co-Pilot (`__init__.py`, `otis-companion-card.js`)**:
  - Tracked and resolved the exact executing AI agent (Primary Cloud AI, Failover Agent, or Local Edge Ollama LLM).
  - Emitted real-time `agent_resolution` progress steps with friendly provider names and durations.
  - Updated Lovelace Companion Card to render an agent attribution pill in the thought trace header (`• ☁️ Google Generative AI` or `• ⚡ Local Edge (qwen2.5:3b)`) and highlighted resolution step in the expanded reasoning list.
- 📜 **Deepened Automation Cross-Referencing (`automation_manager.py`)**:
  - Increased cross-reference capacity to 8 matches and enhanced salient keyword indexing for guest mode, bedtime, and climate coordinators.

---

## [0.1.7] - 2026-11-01

### Added
- ⏱️ **Configurable Assist Co-Pilot Reasoning Timeout (`const.py`, `config_flow.py`, `__init__.py`, `otis-companion-card.js`)**:
  - Added user-configurable `reasoning_timeout` (range 10s - 300s, default 60s) in Integration Options Flow (*Settings ➔ Devices & Services ➔ Otis AI Companion ➔ Configure*).
  - Enforced timeout via `asyncio.wait_for` during conversation agent converse calls with transparent failover cascading on timeout.
  - Added reasoning timeout control into Companion Card's "Autonomy & Safety" settings and dynamically scaled card client timeout to match backend setting.
- 🌡️ **Discovery & Architecture Grounding for Climate & HVAC (`__init__.py`)**:
  - Added `DiscoveryEngine._discover_climate_topology()` to index all `climate.*` entities, mapping them to areas, current temperatures, target setpoints, HVAC modes, and zone relationships.
  - Integrated `climate_topology` directly into the Assist Co-Pilot system prompt and capability map.
- 👁️ **Multi-Modal Vision, Presence & Occupancy Grounding (`__init__.py`)**:
  - Grounded Assist Co-Pilot prompt with live household status, person locations, occupied rooms (fusing mmWave radar, PIR, media playback), vacant rooms, and perimeter security cameras.
- 🗺️ **Comprehensive Area & Room Topology Breakdown (`__init__.py` & `spatial_manager.py`)**:
  - Grounded Assist prompt with complete per-area breakdowns displaying exact room names, door/open adjacency connections, assigned or inherited thermostat coverage, lights, audio, and sensors.
  - Enhanced spatial manager with topological synonyms (`guest_room` ↔ `guest_bedroom`, `guest_suite`, etc.) and fallback connectivity heuristics to ensure 100% graph connectivity for all registered rooms.
- ⚡ **Enhanced Local Edge Model Capabilities (`local_llm.py` & `services.yaml`)**:
  - Pulled and verified `qwen2.5:3b` edge model on Ollama host (`10.0.12.228:11434`), delivering ~15 tokens/sec local smart home reasoning.
  - Added `async_pull_model` and `async_list_models` to `LocalLLMManager`.
  - Registered service `otis_ai.pull_local_llm_model` to allow pulling local edge models directly from Home Assistant.
  - Enhanced `otis_ai.benchmark_local_llm` service with custom `model` parameter.

---

## [0.1.6] - 2026-11-01

### Added
- 🧙‍♂️ **Interactive Household Rules Wizard (`otis-companion-card.js`)**: Built an interactive 5-step wizard tab into the Otis Companion Card:
  - Step 1 (Household & Habits): Guides resident names, work-from-home rooms/hours, and bedtime routines.
  - Step 2 (Guest Mode & Entertaining): Guides guest door lock codes (`4411`), delayed night lighting turn-off (`00:00:00`), guest climate comfort, and holiday lighting sync.
  - Step 3 (Security & Perimeter): Manages deadbolt verbal confirmation guards, security alarm safeguards, garage door alert thresholds, and perimeter camera monitoring.
  - Step 4 (Audio & Media): Coordinates multi-zone matrix audio routing, voice assist spatial ducking, and quiet hours spoken volume caps.
  - Step 5 (Review & Auto-Synthesize): Live markdown preview with 1-click **"Apply to Custom Instructions & Save"** and direct textarea handoff.
- 🔍 **Real YAML Automation & Script Cross-Referencing (`automation_manager.py` & `__init__.py`)**: Added `AutomationManager.async_cross_reference()`. When entities or topics like `input_boolean.guest_mode` are referenced in conversation, Otis dynamically extracts matching real configurations from `automations.yaml` and `scripts.yaml` (e.g., "Security: Manage Guest Lock Code", "Lighting: Adaptive Inside Lights", "Lighting: Lights Off at Bed") and injects them directly into the prompt context to eliminate hallucinations.

### Fixed & Improved
- 🧠 **Multi-Turn Conversation Amnesia (`__init__.py`)**:
  - Implemented unified `_record_turn` across cloud providers and local inference failovers to prevent context drops.
  - Resolved session overwrite bug where detecting proposed YAML blocks previously cleared `session_data["history"]`.
  - Expanded conversation context history window to 10 entries for deep conversational continuity.
- ⚡ **Agent Priority & Transparent Offline Failover (`__init__.py`)**:
  - Configured prioritized AI agents (Gemini 2.5 Flash, OpenRouter) to execute first as primary intelligence.
  - Local LLM now operates as dedicated offline edge failover, smoothly engaging when cloud services encounter rate limits or network downtime.
- 🌐 **Options Dialog Human-Readable Translations (`strings.json` & `translations/en.json`)**: Added user-friendly localized labels for `local_llm_enabled`, `local_llm_url`, `local_llm_model`, and `camera_stream_strategy`.
- 🚀 **Local LLM Performance & Context Optimization (`local_llm.py`)**: Added `keep_alive: "15m"` to keep models in GPU VRAM and expanded Ollama context window to 8192 tokens (`num_ctx: 8192`).
- 🔄 **Dynamic Options Listener Update (`__init__.py`)**: Updates to Local LLM URL or model now take effect immediately without requiring a Home Assistant restart.

---

## [0.1.5] - 2026-10-31

### Improved
- 📹 **Vendor-Agnostic Camera Stream Strategy Architecture (`vision_manager.py` & `const.py`)**: Fully decoupled camera stream selection from specific integration names. Implemented agnostic architectural strategies:
  - 🌐 `managed_proxy`: Managed Proxy / Gateway Preferred (adaptive fallback to high-efficiency sub-streams for unmanaged cameras).
  - ⚡ `high_efficiency`: High-Efficiency Sub-Stream (`sub`, `fluent`, `low`, `balanced`, `secondary`, `preview`).
  - 🖥️ `high_definition`: High-Definition Main Stream (`main`, `clear`, `high`, `primary`, `hd`).
- 🧹 **Generic Robot Vacuum Map Camera Filtering (`vision_manager.py` & `dashboard_manager.py`)**: Completely eliminated hard-coded vacuum integration platforms in favor of generic entity registry device-domain association (`domain == "vacuum"`), device-class verification (`device_class == "map"`), and standard navigation keywords.
- 🔄 **Backward-Compatibility Normalization**: Transparently maps legacy config keys (`frigate`, `fluent`, `clear`) to the new agnostic tier definitions.

---

## [0.1.4] - 2026-10-31

### Added
- 🎛️ **Configurable Camera Stream Selection Strategy (`config_flow.py`)**: Added `camera_stream_strategy` to Options Flow enabling user-selectable stream prioritization across all rooms, studios, and dashboards.
- 📐 **Stream Key Deduplication (`vision_manager.py`)**: Enhanced `get_canonical_camera_key` to strip repetitive device prefix strings and normalize gateway/proxy/WebRTC channel endpoints.

---

## [0.1.3] - 2026-10-31

### Added
- 🧠 **Local LLM & Offline Edge Inference Tier (`local_llm.py`)**: Added native connectivity to local inference engines (Ollama, vLLM, LocalAI, LM Studio) via native `/api/tags`, `/api/chat`, and OpenAI-compatible `/v1/chat/completions` endpoints.
- ⚡ **Sub-Second Transparent Edge-to-Cloud Failover**: Prioritizes zero-cloud local LLM execution for Assist Co-Pilot and conversation queries with sub-second health-checking. Automatically fails over to cloud LLM agents with real-time UI reasoning event dispatches if the local node is offline or times out.
- 🔍 **Dedicated Local LLM Diagnostics & Benchmarks**: Added `otis_ai.test_local_llm` (endpoint latency and model catalog discovery) and `otis_ai.benchmark_local_llm` (throughput tokens/sec and reasoning benchmark).
- 🛡️ **Sentinel Offline Root-Cause Reasoning**: Integrated local LLM diagnostic root-cause reasoning in `SentinelManager.async_diagnose_anomaly`.

### Fixed
- 🐛 **Lovelace Frontend Element Registration**: Resolved `SyntaxError: Identifier 'fileInput' has already been declared` in `otis-companion-card.js` by isolating and namespacing attachment and walkthrough file input variables (`chatFileInput` and `walkthroughFileInput`).

---

## [0.1.2] - 2026-10-31

### Added
- 📎 **Multimodal File & Image Attachments in Assist Co-Pilot**: Direct file attachment paperclip button (`#chat-attach-btn`) and full drag-and-drop file upload support directly onto the chat input bar.
- 🖼️ **Interactive Attachment Preview Tray**: Live image thumbnails, filename chips, and 1-click removal (`✕`) above the input box with a 10MB safety guard for `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, `.yaml`, `.json`, `.txt`, `.csv`, and `.log`.
- 💬 **Inline Rich Bubble Rendering**: Past and active conversation turns render full image previews and clickable attached diagnostic file chips.
- 🤖 **Structured Prompt Attachment Ingestion**: Backend ingestion in `otis_ai.chat` automatically extracts and formats attached configurations and logs for AI analysis.

---

## [0.1.1] - 2026-10-31

### Changed
- ⏱️ **Extended Assist Co-Pilot Timeout**: Increased conversation timeout from 40s to 120s to accommodate deep reasoning chains and local LLM execution.
- 🎛️ **Header Actions & Navigation Elevation**: Elevated Themes Studio and Household Rules chips to the top card header next to the Refresh button with unified `.icon-btn` styling and size.
- 👁️ **Proactive Feed Ignored Count & Full Display**: Synchronized the "Show Ignored" badge count with active suggestions and eliminated slice caps when viewing ignored suggestions.
- 🛡️ **Graceful Quota Exhaustion & Transparent Failover**: Enhanced `is_provider_error()` to detect HTTP 429 and `resource_exhausted` quota limits across lengthy error strings with real-time Lovelace reasoning dispatches.

---

## [0.1.0] - 2026-10-31

### Added
- 📐 **Zero-Hardcoding Spatial Intelligence & Interactive Floor Plan Studio**:
  - Dynamic discovery of Area, Device, and Entity registries generating a physical topological adjacency graph with Breadth-First Search (BFS) pathfinding.
  - Interactive SVG vector floor plan canvas viewer with visual Blueprint Editor (`mode: "floorplan_studio"`).
  - Dynamic SVG matrix transformations (`getScreenCTM()`), dual `ResizeObserver` responsive canvas scaling, and interactive drag-and-drop device pins.
  - Multimodal Video-to-Blueprint AI parser (`floorplan_parser.py`) converting narrated camera walkthroughs into vector SVG layouts.
- 🎨 **Dynamic AI Themes Studio**:
  - Natural language theme generator synthesizing CSS custom properties with instant zero-profile-switching live activation.
  - Granular application scopes: Current User, Specific User (`frontend.user_data_<uid>`), and All Users (Global Profile Sync).
  - Web Speech voice input with real-time 5-bar animated audio waveform equalizer.
  - 7 curated master presets (Cyberpunk Neon, Midnight Slate, OLED Obsidian, Sunset Amber, Emerald Luxury, Nordic Frost, and High Contrast).
- 🛡️ **Otis Sentinel Watchdog & Self-Healing Engine**:
  - Continuous background telemetry monitoring battery depletion, short-cycling climate compressors, unmonitored garage doors, and offline integrations.
  - Atomic 1-click remediation operations for all identified system anomalies.
- 🚀 **Lifestyle Macro Orchestrator & State Rollback**:
  - Multi-step lifestyle sequences (Movie Night, Goodnight, Party Mode, Lockdown, Welcome Home).
  - Atomic pre-flight state snapshotting with 1-click full state rollback (`undo`).
- 🎙️ **Voice Assist, Spatial Audio Ducking & Multi-Room Follow-Me**:
  - Assist conversation pipeline coordination with wake-word readiness.
  - Spatial audio ducking across active media players during announcements (`otis_ai.duck_media`, `otis_ai.restore_media`).
  - Whisper / quiet voice mode adhering to user quiet hours volume constraints.
  - Seamless presence-based multi-room audio follow-me routing and handoffs (`otis_ai.audio_handoff`).
- 🎵 **Modular Multi-Zone Matrix Audio Architecture**:
  - Vendor-agnostic capability discovery and first-class hardware profiles across Universal, Russound, Monoprice/Dayton, Snap One/Episode, Control4, HTD, and AudioControl/Anthem controllers.
  - Proactive idle power guard monitoring amplifier output channels and powering down idle zones to conserve power.
  - Integrated Cinema and TV display scene coordination.
- ⚡ **Predictive Energy & Dynamic Load Shedding**:
  - Time-of-Use (TOU) tariff awareness and tiered dynamic load shedding during grid peak hours.
  - Solar surplus charging optimization and battery/UPS storage telemetry monitoring.
- 👁️ **Multi-Modal Vision & Room Presence Fusion**:
  - Multi-sensor room occupancy fusion combining mmWave radar, PIR, media playback, and micro-BLE beacons.
  - RTSP camera stream deduplication and Google Gemini Vision scene description.
- 📊 **Self-Supervised Habit Learning & Behavioral Modeling**:
  - Non-blocking SQLite recorder habit routine sequence mining.
  - Habit deviation detection with proactive reminders and dynamic circadian curves.
- 🌐 **Zero-Config Home Commissioning & Multi-Node Federation**:
  - Heuristic spatial assignment for unassigned entities and devices.
  - Multi-instance Home Assistant edge node synchronization with remote service dispatch.
- 👤 **User Behavioral Rules & Persona Management**:
  - Persistent assistant personality and etiquette configuration (`rules_manager.py`).
  - Customizable conversational tone, response verbosity, quiet hours volume limits, and autonomy safeguards.
- 🎴 **Otis Companion Lovelace Dashboard Card**:
  - Unified frosted glassmorphism dashboard card (`custom:otis-companion-card`) featuring live multi-agent status, Proactive Feed, Assist Co-Pilot chat, Glance Strip, and interactive Capabilities Inspector.
  - Full-viewport floating modal dialog overlays with responsive auto-centering and scrollability.
