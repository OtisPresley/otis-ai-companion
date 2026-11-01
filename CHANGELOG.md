# Changelog

All notable changes to the Otis AI Companion integration are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.4] - 2026-10-31

### Added
- **Configurable Camera Stream Selection Strategy**:
  - Added `CONF_CAMERA_STREAM_STRATEGY` to OptionsFlow allowing user selection between:
    - `frigate`: Frigate Preferred (low-latency Frigate streams across rooms and studios, automatic fallback to Fluent/Sub for unmanaged cameras).
    - `fluent`: Direct Fluent/Sub (high-efficiency lightweight sub-streams across all cameras to minimize browser lag and network bandwidth).
    - `clear`: Direct Clear/HD (high-definition streams for crisp rendering).
  - Enhanced `stream_priority` and `get_canonical_camera_key` in `vision_manager.py` with integration platform awareness and stream deduplication across Frigate and native camera integrations (e.g. Reolink).
  - Synchronized stream selection across Vision Intelligence, Room Subviews, and Security Command Center dashboards.

## [0.1.3] - 2026-10-31

### Added
- **Local LLM & Offline Edge Inference Tier (Option C + Option A)**:
  - Added `local_llm.py` manager providing native connectivity to local inference engines (Ollama, vLLM, LocalAI, LM Studio) via native `/api/tags`, `/api/chat`, and OpenAI-compatible `/v1/chat/completions`.
  - Configurable in OptionsFlow with `local_llm_enabled`, `local_llm_url` (default: `http://10.0.12.228:11434`), `local_llm_model` (`qwen2.5:1.5b`), and optional API key.
  - Transparent Failover: Prioritizes zero-cloud local LLM execution for Assist Co-Pilot and conversation queries with sub-second health-checking. Automatically fails over to cloud LLM agents (Google Generative AI, OpenAI, etc.) with real-time UI reasoning event dispatches if the local node is offline or times out.
  - Dedicated diagnostic services: `otis_ai.test_local_llm` (endpoint latency and model catalog discovery) and `otis_ai.benchmark_local_llm` (throughput tokens/sec and reasoning benchmark).
  - Integrated local LLM diagnostic root-cause reasoning in `SentinelManager.async_diagnose_anomaly`.

### Fixed
- **Lovelace Frontend Element Registration**:
  - Resolved `SyntaxError: Identifier 'fileInput' has already been declared` in `otis-companion-card.js` by isolating and namespacing attachment and walkthrough file input variables (`chatFileInput` and `walkthroughFileInput`).
  - Restored full initialization and custom element definition (`otis-companion-card`) in Lovelace dashboards.

## [0.1.2] - 2026-10-31

### Added
- **Multimodal File & Image Attachments in Assist Co-Pilot**:
  - Direct file attachment paperclip button (`#chat-attach-btn`) and full drag-and-drop file upload support directly onto the chat input bar.
  - Interactive attachment preview tray above the input box with real-time image thumbnails, filename chips, and 1-click removal (`✕`).
  - Support for multiple image formats (`.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`) and diagnostic documents (`.yaml`, `.json`, `.txt`, `.csv`, `.log`) with a 10MB safety guard.
  - Inline bubble rendering of image previews and attached file chips for past and active conversation turns.
  - Backend integration in `otis_ai.chat`: automatic structured ingestion and code block injection for prompt analysis of configuration files, scripts, and logs.

## [0.1.1] - 2026-10-31

### Changed
- **Extended Assist Co-Pilot Timeout**:
  - Increased conversation timeout from 40s to 120s to allow complex reasoning chains, tool execution, and local LLM models (e.g. Ollama) sufficient processing time.
- **Header Actions & Navigation Elevation**:
  - Elevated Themes Studio and Household Rules chips to the top card header next to the Refresh button with unified `.icon-btn` styling and size.
  - Removed Themes and Rules from the subviews launchpad row, reflecting their system-wide scope.
- **Proactive Feed Ignored Count & Full Display**:
  - Synchronized the "Show Ignored" badge count with active suggestions in the feed.
  - Eliminated the `max_suggestions` (5) slice cap when viewing ignored suggestions, ensuring all ignored cards are visible when toggled.
- **Graceful Quota Exhaustion & Transparent Failover**:
  - Enhanced `is_provider_error()` to detect HTTP 429 and `resource_exhausted` quota limits across lengthy error strings.
  - Added real-time Lovelace reasoning event dispatches informing the user when transparent failover occurs due to provider rate or quota exhaustion.
  - Added structured, helpful explanations directing the user to configure fallback providers when all AI endpoints are exhausted.

## [0.1.0] - 2026-10-31

### Added
- **Zero-Hardcoding Spatial Intelligence & Interactive Floor Plan Studio**:
  - Dynamic discovery of Area, Device, and Entity registries generating a physical topological adjacency graph with Breadth-First Search (BFS) pathfinding.
  - Interactive SVG vector floor plan canvas viewer with visual Blueprint Editor (`mode: "floorplan_studio"`).
  - Dynamic SVG matrix transformations (`getScreenCTM()`), dual `ResizeObserver` responsive canvas scaling, and interactive drag-and-drop device pins.
  - Multimodal Video-to-Blueprint AI parser (`floorplan_parser.py`) converting narrated camera walkthroughs into vector SVG layouts.
- **Dynamic AI Themes Studio**:
  - Natural language theme generator synthesizing CSS custom properties with instant zero-profile-switching live activation.
  - Granular application scopes: Current User, Specific User (`frontend.user_data_<uid>`), and All Users (Global Profile Sync).
  - Web Speech voice input with real-time 5-bar animated audio waveform equalizer.
  - 7 curated master presets (Cyberpunk Neon, Midnight Slate, OLED Obsidian, Sunset Amber, Emerald Luxury, Nordic Frost, and High Contrast).
- **Otis Sentinel Watchdog & Self-Healing Engine**:
  - Continuous background telemetry monitoring battery depletion, short-cycling climate compressors, unmonitored garage doors, and offline integrations.
  - Atomic 1-click remediation operations for all identified system anomalies.
- **Lifestyle Macro Orchestrator & State Rollback**:
  - Multi-step lifestyle sequences (Movie Night, Goodnight, Party Mode, Lockdown, Welcome Home).
  - Atomic pre-flight state snapshotting with 1-click full state rollback (`undo`).
- **Voice Assist, Spatial Audio Ducking & Multi-Room Follow-Me**:
  - Assist conversation pipeline coordination with wake-word readiness.
  - Spatial audio ducking across active media players during announcements (`otis_ai.duck_media`, `otis_ai.restore_media`).
  - Whisper / quiet voice mode adhering to user quiet hours volume constraints.
  - Seamless presence-based multi-room audio follow-me routing and handoffs (`otis_ai.audio_handoff`).
- **Modular Multi-Zone Matrix Audio Architecture**:
  - Vendor-agnostic capability discovery and first-class hardware profiles for:
    - Universal / Standards-Based Multi-Zone Matrix Amplifiers
    - Russound Multi-Zone Controllers (MCA-C3, MCA-C5, MCA-66, MCA-88, RIO, RNET, MBX)
    - Monoprice 6-Zone Whole-Home Audio / Dayton Audio (DAX66)
    - Snap One / Episode Response DSP / Triad AMS Multi-Zone Matrix Amplifiers
    - Control4 4/8/16-Zone Matrix Amplifiers
    - HTD Whole-Home Audio (Lync 6/12, MC-66, MCA-66)
    - AudioControl Director / Anthem / Savant Multi-Zone DSP Systems
  - Proactive idle power guard monitoring amplifier output channels and powering down idle zones to conserve power.
  - Integrated Cinema and TV display scene coordination.
- **Predictive Energy & Dynamic Load Shedding**:
  - Time-of-Use (TOU) tariff awareness and tiered dynamic load shedding during grid peak hours.
  - Solar surplus charging optimization and battery/UPS storage telemetry monitoring.
- **Multi-Modal Vision & Room Presence Fusion**:
  - Multi-sensor room occupancy fusion combining mmWave radar, PIR, media playback, and micro-BLE beacons.
  - RTSP camera stream deduplication and Google Gemini Vision scene description.
- **Self-Supervised Habit Learning & Behavioral Modeling**:
  - Non-blocking SQLite recorder habit routine sequence mining.
  - Habit deviation detection (e.g. missed evening routines) with proactive reminders.
  - Dynamic circadian lighting and seasonal climate temperature curves.
- **Zero-Config Home Commissioning & Multi-Node Federation**:
  - Heuristic spatial assignment for unassigned entities and devices.
  - Multi-instance Home Assistant edge node synchronization with remote service dispatch.
- **User Behavioral Rules & Persona Management**:
  - Persistent assistant personality and etiquette configuration (`rules_manager.py`).
  - Customizable conversational tone, response verbosity, quiet hours volume limits, and autonomy safeguards.
  - Dynamic prompt injection into Assist conversation turns and interactive onboarding wizard.
- **Otis Companion Lovelace Dashboard Card**:
  - Unified frosted glassmorphism dashboard card (`custom:otis-companion-card`) featuring live multi-agent status, Proactive Feed with category pills and persistent dismissal storage, Assist Co-Pilot chat interface, Glance Strip, and interactive Capabilities Inspector.
  - Full-viewport floating modal dialog overlays with responsive auto-centering and scrollability.
