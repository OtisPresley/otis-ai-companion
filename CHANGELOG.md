# Changelog

All notable changes to the Otis AI Companion integration are documented in this file.

> 📌 See also: [`ROADMAP.md`](./ROADMAP.md) for planned features and release targets.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-11-05

### Added & Enhanced
- **Conversation Agent Resolution Badge Continuity (`__init__.py`, `otis-companion-card.js`)**:
  - Restored and hardened the conversation agent resolution badge (`🧠 Thought for X.Xs (N steps) • ☁️/⚡ <Agent Name>`) across both LLM and grounded fast-path responses by emitting `agent_resolution` progress steps, preserving `"default"` session keys in `_create_response()` and `handle_chat()`, normalizing legacy `config_entry_id` agent preferences to active `conversation.*` entities, and extracting `resolved_agent` directly from `otis_ai.chat` service payloads on the frontend.
- **Clean Alias-Free YAML Generation & Indoor Lighting Filtering (`__init__.py`)**:
  - Added `_NoAliasSafeDumper` (`yaml.SafeDumper` subclass) to eliminate `&id001` / `*id001` YAML anchors and aliases in generated Home Assistant automations.
  - Filtered hardware indicator LEDs (`*_led`, `*_screen`) and exterior driveway/floodlight fixtures when synthesizing indoor room motion/occupancy lighting automations.
- **Full HACS Default Catalog Compliance Verified**:
  - Verified 100% non-blocking event-loop file I/O (dispatched via `hass.async_add_executor_job`), mandatory authentication and 100MB upload size cap on `OtisWalkthroughUploadView` (`/api/otis_ai/upload_walkthrough`), private storage of walkthrough videos and floor plan SVGs under `.storage/otis_ai/media` served via authenticated `OtisMediaView` (`/api/otis_ai/media/{filename}`), and zero raw user YAML writes (`configuration.yaml`, `automations.yaml`, `scripts.yaml`, `blueprints/`).

## [0.1.59] - 2026-11-05

### Fixed & Enhanced
- **Assist Co-Pilot Speed & Test Accuracy Optimization**:
  - Eliminated the 45-second RAG embedding timeout stall per query in `local_llm.py` (`async_get_embedding`) by skipping embedding requests against non-embedding chat models (`qwen2.5:3b`) unless a dedicated embedding model is configured, falling back immediately to deterministic/lexical retrieval.
  - Fixed `classify_and_score_agent()` and `async_get_prioritized_agents()` in `__init__.py` to resolve `conversation.*` entity IDs through the Entity Registry to their parent `ConfigEntry` and `ConfigSubentry`, deduplicating config entry IDs vs. entity IDs and properly classifying Groq (`domain="groq"`) and OpenRouter free tiers with compact prompts and responsive failover timeouts.
  - Added grounded live room status inspection, anti-hallucination entity registry verification (refusing to generate or offer deployment for non-existent entities and stripping hallucinated YAML blocks in `validate_and_upgrade_assistant_response`), grounded single-room occupancy/lighting automation synthesis, and ambiguous room clarification prompts.
- **Startup Gate (`hass.is_running` / `EVENT_HOMEASSISTANT_STARTED`)**:
  - Prevented `DiscoveryEngine.async_generate_proactive_suggestions` and `VisionPresenceManager` state-change listeners from generating recommendations or firing spatial migration intents until Home Assistant is fully started (`hass.is_running` is `True`).
- **Assist Co-Pilot Bottom Starting Scroll Position**:
  - Updated `OtisCompanionCard._render()` so `#chat-history` starts scrolled to the bottom on initial load and tab switches so the most recent results are visible first, while preserving relative scroll offset if the user scrolls up.
- **Standalone People/Pets/Guests Identity Training & Multi-Domain Recommendations**:
  - Decoupled identity training in `async_generate_proactive_suggestions` from `person.*` entities and Audio Follow-Me by merging all profiles from `rules_manager.get_person_profiles()`, `person.*` entities, and Home Assistant users, and added multi-domain recommendations for pet-immune occupancy/security (`identity_pet_immunity_guard_*`), personalized resident room comfort (`identity_resident_comfort_*`), guest hospitality (`identity_guest_hospitality_*`), and vision false-positive / unfamiliar-person deterrence (`identity_feedback_filter_*`, `identity_unknown_person_watchdog_*`).

## [0.1.58] - 2026-11-05

### Fixed & Enhanced
- **3D Floor Plan Save-to-Dashboard Synchronization & Dedicated Subview Polish**:
  - Fixed `#btn-save-3d-dashboard` on the Command Center Floor Plan tab by persisting `floorplan_view_mode`, `floorplan_3d`, `floorplan_azimuth`, `floorplan_pitch`, `floorplan_wall_height`, `floorplan_walls_enabled`, `floorplan_zone`, and `floorplan_scale` to `user_rules` (`rules_manager.py`) and `dashboard_manager.py`, applying saved rules directly on the `floorplan_control` view even when `localStorage` contains older values, and preserving toast notifications across Shadow DOM re-renders.
  - Hid the `💾 Save 3D to Dashboard` button on the dedicated **Floor Plan** dashboard view (`mode: "floorplan_control"`) while keeping it available on the main Command Center Floor Plan tab.
- **Assist Co-Pilot Chat Text Selection & Clipboard Copy**:
  - Enabled native text highlighting and copy (`user-select: text !important`) across `.chat-history`, `.chat-bubble`, markdown blocks, code blocks, and reasoning steps, stopping Lovelace pointer event capture from interfering with drag-to-select.
  - Updated `.prompt-copy-btn` to use `_copyToClipboard()` so prompt and response copying work reliably over both HTTPS and local HTTP connections.

## [0.1.57] - 2026-11-05

### Fixed & Enhanced
- **Identity Training Cards with Detection Snapshots, Live Camera Preview & Classification Buttons**:
  - Added `_resolve_room_training_media()` in `OtisDataCoordinator` and `_renderTrainingVerificationMedia()` in `otis-companion-card.js` to attach Frigate/NVR detection snapshots (`image.<room>_person`, `image.<room>_dog`, `image.<room>_cat`, `camera.<room>_snapshots_*`) and live room camera feeds (`camera.<room>`) directly onto `📍 Who is in the <Room>? Verify Identity for Training` cards, with click-to-enlarge `hass-more-info` support.
  - Added **🕵️ Unknown Person**, **🦊 Unknown Animal**, and **🚫 Not Person/Pet** classification buttons to all room identity verification cards and persisted non-household / false-positive classifications in `vision_training_feedback` (`rules_manager.py`) along with a 10-minute per-room verification cooldown (`recent_room_verifications`).
- **3D Floor Plan Near & Far Wall Click/Hover Fix**:
  - Fixed Chromium/WebKit 3D Z-buffer hit-testing on the far half (`Z < 0` under `rotateX` tilt) of the 3D floor plan by setting `transform-style: flat; pointer-events: none;` on `.floorplan-3d-stage` and `pointer-events: none;` on `.floorplan-3d-canvas`, preventing `.floorplan-3d-stage`'s `Z = 0` plane from intercepting hover and click events over far rooms and walls (`Backyard`, `Great Room`, `Mudroom`, `Garage`, upper suites).
  - Elevated `.floorplan-device-pin` to `translate3d(-50%, -50%, 14px)` above the `z_local = 0` SVG floor plane and linked `.room-group` `pointerenter`/`pointerleave` events to highlight the room's raised 3D glass walls (`.floorplan-3d-room-shell.is-hovered`).

## [0.1.56] - 2026-11-05

### Fixed & Enhanced
- **3D Floor Plan Lock Button & Real-Time Entity Pin State Coloring**:
  - Fixed `#btn-toggle-3d-lock` by separating its class (`btn-lock-pill`) from angle preset pills (`.btn-preset-pill[data-azimuth]`), preventing the `45° NE` preset listener from overriding the Lock/Unlock toggle, and persisted lock state across re-renders via `localStorage`.
  - Added real-time `_updateFloorplanPinStates()` synchronization inside `set hass()` and `_setupEventListeners()` so `<ha-state-icon>` pins dynamically update domain-specific active colors (`#f59e0b` for lights/switches, `#38bdf8` for media/climate, `#ef4444` for unlocked deadbolts/open covers, `#10b981` for active motion/occupancy) and glow filters immediately on state change.
- **Unrestricted Spatial Audio Follow-Me & Multi-Zone Source Selection**:
  - Removed all time-of-day gates from Audio Follow-Me and Movie Time (`movie_night`) migration in `vision_manager.py`, leaving **Quiet Hours** and **Party Mode** as the sole suppressants.
  - Excluded slow-cooldown Ecobee thermostat occupancy sensors (`*temp_occupancy`, `downstairs_occupancy`, `upstairs_occupancy`) from `is_mmwave` so `binary_sensor.study_temp_occupancy` no longer pins `occupied_areas[0]` to `study` for 30+ minutes after leaving the room.
  - Added Frigate/Reolink `*_person_occupancy` and `*_all_occupancy` camera sensors (`great_room`, `foyer`, `mudroom`, etc.) to spatial presence transition tracking, removed the premature `target_area in occupied_areas` abort in `audio_manager.py`, and prioritized active music sources (`"Server"`, `"Bridge"`, `"Spotify"`) over idle TTS inputs (`"Home Assistant"`).
- **Room-Entry Identity Verification Cards & Training Progress UI**:
  - Added critical-priority room-entry verification cards (`📍 Who is in the <Room>? Verify Identity for Training`) with multi-choice resident/pet/guest candidate buttons for recently entered or active rooms (`Great Room`, `Mudroom`, `Foyer`, `Study`, etc.).
  - Added a live **Training Progress Summary Banner** in the `👥 People & Pets` feed view and enhanced the `Rules -> People & Pets` tab with visual sample progress bars (`samples/5`), confidence percentages, status badges (`🟢 Trained`, `🟡 Calibrating`, `🔵 Needs Samples`), verified rooms list, and 1-click `+ Verify Sample` buttons.
- **Paid-First Dynamic Agent Reordering, Free-Tier Audit & Continuous Self-Learning Engine**:
  - Implemented `classify_and_score_agent()` and dynamic `async_get_prioritized_agents()` ordering that inspects config entries and subentries to prioritize **Paid Cloud APIs first** (`anthropic`, `openai_conversation`, `extended_openai_conversation`, paid `open_router`), followed by healthy Standard Cloud and **Local LAN LLM (`Ollama` / `qwen2.5:3b`)**, while automatically demoting congested `google_generative_ai_conversation` (HTTP 429/503) and restricted Free Tiers (`groq` with `protect_free_tier` 6k–12k TPM limit and `openrouter/free`).
  - Added continuous self-learning (`async_learn_from_interaction()`) and `validate_and_upgrade_assistant_response()` to enforce modern Home Assistant (`triggers:`, `conditions:`, `actions:`, `action:`) syntax, ask the user for clarification when requests are ambiguous, detect hallucinated entity IDs, and automatically append learned rules/corrections to Custom Instructions.
  - Updated the **AI Multi-Agent Routing & Failover Guide** modal with clear Paid vs. Local vs. Restricted Free Tier guidance covering Anthropic Claude, OpenAI, OpenRouter, Google Gemini, xAI Grok, Local Ollama, and why Groq Free Tier is not recommended.

## [0.1.55] - 2026-11-05

### Fixed & Enhanced
- **3D Floor Plan Orbit Lock & Wall Click-Through**:
  - Added a **Lock button (`🔒 Locked` / `🔓 Unlocked`)** in the 3D Orbit & Pitch Controls box (`#btn-toggle-3d-lock`) that **starts locked by default**, preventing accidental 3D canvas rotation or movement while clicking entities and rooms.
  - Set `pointer-events: none !important;` on `.floorplan-3d-room-shell` and `.floorplan-3d-wall` so hover and click events pass directly through 3D walls to the underlying room polygons and device pins.
- **Smart EV Charging False Positive Suppression**:
  - Excluded phone/watch/tablet chargers, iBeacons, and non-EV battery entities from `has_ev` detection in `energy_manager.py`, and restricted the Smart EV Charging section on the Command Center card to render only when `arbitrage.has_ev` is true.
- **People & Pets Profile UI & Training Card Visibility**:
  - Removed the redundant delete icon button (`.btn-delete-profile`) from People & Pets profile cards in favor of the `🚫 Exclude / Do Not Track` dropdown option.
  - Added a `👥 People & Pets` (`presence`) filter chip in the Proactive Feed and elevated identity verification training cards (`confirm_person_identity`) to high priority.
- **Rules Wizard Default Tab & Cache Freshness**:
  - Set the Rules modal default tab to `🧙 Rules Wizard` (`wizard`) instead of `Persona & Tone`.
  - Injected live `user_rules` into `capability_map` responses even on cache hits so saved wizard text and ignored profiles never revert on refresh.
- **Energy Studio High-Draw Controllable Circuits**:
  - Replaced substring matching with strict token-level matching for `controllable_power_eids`, excluding indicator LEDs (`switch.hall_lamps_led`), virtual/auto-update switches (`switch.theater_auto_update_enabled`), and media/DND toggles.
- **Room Subview Camera Stream Selection**:
  - Expanded canonical camera groups across all system cameras in `_build_room_subview()` so rooms like `Garage` select the live Reolink substream (`camera.driveway_fluent`) instead of the non-live Frigate entity (`camera.driveway`).
- **Dashboard Regenerate Custom Card Preservation**:
  - Updated `force_regenerate=True` (`⚡ Regenerate` button) to preserve user-configured custom cards (`custom:control4-mediaplayer-card`, `custom:mini-media-player`, etc.) across both view `cards` and `sections`.
- **Assist Co-Pilot ULID Agent Routing & Prompt Grounding**:
  - Resolved Home Assistant config entry domain/title for ULID conversation agent IDs so OpenRouter (`free_models_router`) triggers fast local LLM (`qwen2.5:3b`) prioritization and Groq receives compact prompts.
  - Added strict prompt constraints forbidding CLI update commands (`cd /config`, `git pull`, `pip install`) and nonexistent `voice:` YAML blocks.

## [0.1.54] - 2026-11-05

### Fixed & Enhanced
- **Floor Plan 3D & 2D Wall Hover and Click Interaction**:
  - Restored interactive pointer events and hover states on `.floorplan-3d-wall` and `.floorplan-3d-room-shell` while keeping `.floorplan-walls-overlay` transparent.
  - Hovering over any 3D architectural wall now illuminates the room with bright cyan glow and clicking immediately opens the room's controls and device inspector.
  - Added strict `pointer-events: none !important;` to SVG frame borders (`.plan-frame`), blueprint grid textures, and container shells, preventing background geometry from intercepting clicks near perimeter walls.
  - Added `pointer-events: all;` and unified hover drop-shadow filters across all 2D room polygons (`.room-box`, `.room-rect`, `.room-polygon`).
- **Assist Co-Pilot Architectural Grounding**:
  - Injected strict Home Assistant architecture rules into Co-Pilot system prompts: hardware voice satellites connect via native ESPHome or Wyoming Protocol integrations under Settings → Voice Assistants (eliminating hallucinated "Assist Satellite" integration menus and onboarding steps).
  - Explicitly prohibited `platform: time_pattern` polling automations for quiet hours volume caps in favor of discrete `platform: time` triggers to protect the asyncio event loop.
  - Forbade instructing users to create `README.md` notes or markdown files in `/config`.

## [0.1.53] - 2026-11-05

### Fixed & Enhanced
- **Rules Wizard & Preference Persistence**:
  - Fixed pre-render DOM destruction: inputs are now harvested before setting saving flags or re-rendering, ensuring user-typed text edits save reliably.
  - Added continuous real-time input event synchronization across wizard fields (`#wiz-residents`, `#wiz-work`, `#wiz-sleep`, `#wiz-guest-code`).
  - Restricted available household members strictly to Home Assistant `person.*` entities, eliminating duplicate chips.
  - Removed disruptive unconditional `regenerate_dashboards` call on preference save.
- **People & Pets Recognition Management**:
  - Implemented persistent `ignored_persons` registry: deleted profiles are permanently excluded from recognition and will not re-appear on refresh.
  - Fixed profile deletion button to immediately prune local and server state.
- **Dashboard & Card Configuration Preservation**:
  - Enhanced `_merge_dashboard_config_preserving_user_views` across all views and subviews (`media`, `energy`, `security`, `climate`, `area_*`): all user card configurations, custom cards, ordering, and options are now strictly preserved when Otis updates or synchronizes dashboards.
- **Energy Arbitrage & EV Suppression**:
  - Omitted Smart EV Charging section from Command Center Capabilities card when no EV is integrated in the home.
  - Filtered out non-energy automations (lighting, UPS watchdogs, adaptive brightness) from Contextual Energy Arbitrage migration recommendations.
- **Sentinel False Positive Filter**:
  - Excluded `device_tracker.*` entities from BLE proxy offline audits, resolving spurious alerts for active Bluetooth proxies.
- **AI Assist Co-Pilot Cascade Optimization**:
  - Compacted conversation prompts for high-speed agents (Groq) to eliminate HTTP 413 Payload Too Large errors.
  - Re-ordered fallback cascade to engage local edge models (`qwen2.5:3b` on LAN) and fast cloud models ahead of slow public third-party free routers.

## [0.1.52] - 2026-11-05

### Added & Enhanced
- **Household Rules Wizard State Persistence**:
  - Added dedicated `wizard_state` storage schema to `BehavioralRulesManager`, permanently persisting all step answers (household residents, work-from-home routines, sleep preferences, guest codes, security thresholds) across reboots and dashboard refreshes.
  - Added automatic legacy recovery parsing from existing `custom_instructions` into structured `wizard_state`.
  - Added interactive multi-select chip selector for Primary Residents in Step 1, letting users toggle active household members directly from existing Home Assistant `person` entities and registered accounts.
- **People & Pets Recognition Management Studio**:
  - Added dedicated `👥 People & Pets` tab in the Rules modal, giving users full granular control over all vision-recognized profiles.
  - Provides per-profile classification selector (`👤 Primary Resident`, `🐾 Pet / Domestic Animal`, `👥 Guest / Visitor`, `🚫 Exclude / Do Not Track`), individual training toggle switches, and one-click profile removal (`🗑️ Remove`).
  - Added backend services `otis_ai.update_person_profile` and `otis_ai.remove_person_profile`.
- **Command Center Floor Plan Hover & Click-Through Fixes**:
  - Fixed 3D orbit pointer capture: disambiguates orbit drag from room clicks (`moveDist < 6px`), restoring instant room inspection popup triggers in 3D perspective.
  - Dynamically computes dashboard URL path prefix (`dashPrefix`), ensuring "Open Room Controls →" and room headers navigate reliably to `/{dashboard_url_path}/area_{slug}` on both the Command Center and custom dashboards.
  - Added explicit SVG room group hover glow (`var(--otis-primary)`) and pointer cursor rules in Shadow DOM.
- **Media Studio Valid MDI Icon**:
  - Replaced invalid MDI icon `mdi:music-note-sync` with valid `mdi:cast-connected` for `switch.otis_audio_follow` in both entities cards and Home Assistant state publication.
- **Contextual EV & Energy Studio Optimization**:
  - Added smart EV topology detection: automatically suppresses EV charging recommendations and EV-specific cards when no EV charger or vehicle is integrated in Home Assistant.
  - Fixed Command Center home view card preservation: added `"Active Rooms"` to core titles, preventing exponential card duplication on dashboard regenerations.

## [0.1.51] - 2026-11-05

### Added & Enhanced
- **Instant Floor Plan SVG Delivery**:
  - Embedded SVG XML directly into `cap_map["floorplan"]["svg"]` via non-blocking executor job, eliminating 401 signed URL parameter mismatches and guaranteeing instant floor plan rendering.
- **Media Studio Dynamic Lovelace Card Detection**:
  - Automatically discovers installed custom Lovelace cards (`custom:control4-mediaplayer-card`, `custom:mini-media-player`, `custom:universal-remote-card`, `custom:mushroom-media-player-card`) and configures specialized media player dashboards dynamically.
- **Proactive Feed Migration Recommendations**:
  - Analyzes existing legacy automations, scripts, and blueprints to propose native Otis coordinator upgrades (Multimodal Presence Fusion, TOU Contextual Energy Arbitrage) via safe non-destructive recommendations.
- **HA News Capability Adoption**:
  - Automatically parses official Home Assistant release feeds to identify newly introduced capabilities and generate one-click adoption suggestions.
- **Zero Hard-Coding Standards**:
  - Replaced residual user names and specific environment references with generic aliases and dynamic registry lookups across test suites and placeholders.

## [0.1.50] - 2026-11-05

### Fixed & Optimized
- **Floor Plan 3D/2D Wall Pass-Through**:
  - Added strict `pointer-events: none !important;` to `.floorplan-walls-overlay *`, `.floorplan-3d-wall`, and SVG door/window stroke geometries, allowing click-and-hover gestures to seamlessly reach underlying floor plans, rooms, and entity pins.
- **Sun Elevation Resolution & Solar Conditional Rendering**:
  - Fixed `sun_elevation` reporting `None` by evaluating `sun.sun` attributes (`elevation`, `azimuth`) and circadian time-of-day math fallbacks.
  - Dynamically detects presence of real solar systems; suppresses misleading zero-production solar panels in Energy Studio when no solar integration exists.
- **Perimeter Sentinel Entity Initialization**:
  - Added `publish_initial_perimeter_sentinel_state()` on startup, eliminating the "Entity Not Found: sensor.otis_perimeter_sentinel" warning on the Security Center view.
- **Rules Wizard Multi-Tab Input Persistence**:
  - Implemented comprehensive `_harvestAllInputs()` handler across all Rules Wizard tabs and footer save actions, preventing input loss on tab switching and persisting custom instructions directly.
- **Zero Hard-Coding Compliance**:
  - Removed hardcoded resident names, IP addresses, and specific entity IDs (`ups_theater`, `amy_s_office`, `10.0.12.228`) across `energy_manager.py`, `dashboard_manager.py`, `vision_manager.py`, `const.py`, and `otis-companion-card.js`.

## [0.1.49] - 2026-11-05

### Fixed
- **Signed Media URLs & Synchronous Floorplan Fetching**:
  - Enhanced capability map with temporary signed URLs (`async_sign_path`) for floor plan SVG assets, allowing seamless image loading across both authenticated card fetchers and standard dashboard image renderers.
  - Added synchronous `await` in `_fetchData` for initial floor plan SVG retrieval prior to render pass.
  - Added `_floorplanLoadFailed` guard to prevent render thrashing on network anomalies.

## [0.1.48] - 2026-11-05

### Fixed
- **OtisMediaView Response Formatting & Auto Floorplan Fetch**:
  - Fixed aiohttp `web.Response` `content_type` exception in `OtisMediaView` by setting `content_type="image/svg+xml"` (removing invalid charset string).
  - Enhanced Companion Card `_loadFloorplanSvg` with automatic fallback endpoint resolution (`/api/otis_ai/media/otis_floorplan.svg`) and response status logging.
  - Added self-healing floor plan loader trigger inside `_renderFloorplanTab` ensuring SVG immediately fetches upon tab display.

## [0.1.47] - 2026-11-05

### Fixed
- **Floor Plan Restoration & Media File Clean-Up**:
  - Ensured dynamic reload of floorplan metadata and SVG room bounds during capability map generation if not previously initialized.
  - Resolved floor plan metadata resolution for paths in private storage (`.storage/otis_ai/media/`).
  - Removed temporary migration code from integration startup.

## [0.1.46] - 2026-11-05

### Security & Compliance
- **HACS Default Catalog Compliance & Security Hardening**:
  - **Authenticated Walkthrough Uploads & Stream Limits**:
    - Removed `requires_auth = False` from `OtisWalkthroughUploadView` (`/api/otis_ai/upload_walkthrough`), enforcing native Home Assistant authentication across all video uploads.
    - Added strict 100MB (`MAX_UPLOAD_SIZE_BYTES`) payload stream and content-length cap, rejecting oversized requests with HTTP 413 Payload Too Large to prevent resource exhaustion.
    - Updated `otis-companion-card.js` to upload walkthroughs and poll processing status via authenticated `hass.fetchWithAuth(...)`.
  - **Private Media Isolation & Authenticated Media Endpoint**:
    - Moved walkthrough uploads and generated floor plan SVGs out of unauthenticated `/config/www` into private storage under `/config/.storage/otis_ai/media/`.
    - Added authenticated `OtisMediaView` (`/api/otis_ai/media/{filename}`) requiring active Home Assistant credentials, with strict directory traversal validation and MIME detection.
    - Updated dashboard manager, capability map, and Lovelace card to resolve floor plans via `/api/otis_ai/media/otis_floorplan.svg`.
  - **Eliminated Raw User YAML File Writes**:
    - Dropped all raw file writes to `configuration.yaml`, `automations.yaml`, `scripts.yaml`, and user blueprints under `/config/blueprints/`.
    - Integrated persistent Home Assistant `.storage` registries (`Store`) for integration-managed automations (`otis_ai_automations`), scripts (`otis_ai_scripts`), and blueprints (`otis_ai_blueprints`).
    - Upgraded `async_improve_automation` and `async_optimize_system_config` to present clean, GUI-ready YAML blocks for user review and 1-click clipboard copy into the Home Assistant UI.

## [0.1.45] - 2026-11-04

### Added & Improved
- **Post-Phase 10 Polish & Assist Co-Pilot Automation Parity**:
  - **Full Automation Parity Between Lovelace Card & Assist Co-Pilot**:
    - Connected proactive recommendations and vetted automation proposals to Assist Co-Pilot conversational flow (`OtisAIConversationAgent.async_process`).
    - Added natural language intent matching for proactive suggestions (e.g., "list recommendations", "show suggestions", "apply suggestion <id/index>", "dismiss suggestion <id/index>").
    - Synchronized automation creation so requesting automations conversationally applies the exact same vetted Home Assistant YAML triggers, conditions, and actions created when clicking "Apply" on the Command Center card.
    - Added high autonomy mode auto-apply: when `autonomy_level == "high"` or explicit "apply/deploy" is requested, automations are written and reloaded immediately; in balanced/strict mode, vetted YAML is presented with interactive confirmation prompts.
  - **Dynamic Behavioral Rules & Immediate Propagation**:
    - Added `reasoning_timeout` to `DEFAULT_RULES` and validation (10–300s), dynamically updating config entry options on `set_user_rules`.
    - Connected `rules_manager` to `MacroManager`: `inspect_safety` now dynamically honors user autonomy policies (`high`, `balanced`, `strict`), `require_lock_confirmation`, and `require_security_confirmation`.
    - Connected `rules_manager` to `MultiAgentOrchestrator`: multi-agent specialist sub-agents now ground their prompts in user personas, tone, quiet hours, and household instructions.
  - **Rules Modal UI & Controls**:
    - Added missing toggles in Lovelace `otis-companion-card.js` Rules Modal:
      - `voice_announcements_enabled`: Master proactive voice announcements switch.
      - `voice_filter_passersby`: Filter pedestrian sidewalk and street passerby movements.
      - `presence_room_cards`: Contextual room presence & activity cards toggle in Command Center.
    - Bumped Lovelace card version to v0.1.45.

## [0.1.44] - 2026-11-04

### Added
- **Phase 10: Multi-Node Federation and Distributed Cross-Instance Home Assistant Clustering**:
  - Implemented advanced multi-node clustering and edge state synchronization in `federation_manager.py`:
    - **Clustering & Node Roles**: Flexible node topology (`primary`, `satellite`, `outbuilding`, `mobile_marine`) connecting detached workshops, guest houses, RVs, and marine vessels.
    - **Automated Health Scoring & Latency Monitoring**: Continuous round-trip latency tracking, dynamic health scoring (0–100%), and status classification (`healthy`, `degraded`, `offline`, `idle`).
    - **Domain-Specific Filtering & Namespacing**: Granular entity synchronization with `allowed_domains` and `excluded_domains`, exposing remote entities as `federated.<node_id>.<domain>.<object_id>`.
    - **Transparent Remote Service Routing**: `otis_ai.forward_remote_command` transparently extracts node targets from namespaced entities and executes remote services.
    - **Cluster-Wide Emergency & Event Broadcasting**: `otis_ai.broadcast_cluster_message` dispatches urgent notifications and alerts across all active edge instances concurrently.
    - **Background Non-Blocking Sync Engine**: Periodic automated synchronization loop with graceful lifecycle start/stop in `__init__.py`.
  - **Real-Time Telemetry Sensors**:
    - `sensor.otis_federation_cluster`: Publishes cluster health score, online/offline edge node counts, average latency, and recent remote service call execution history.
    - `sensor.otis_federated_nodes`: Mirrors real-time cluster state and federated node catalog.
  - **Conversational Assist Capabilities**:
    - Expanded Otis AI conversation agent to process cluster health inquiries, edge node synchronization commands, and remote device execution.
  - Updated Lovelace `otis-companion-card.js` with Cluster Health scoring pill, latency indicators, and edge node synchronization controls.
  - Bumped integration and card version to v0.1.44.

## [0.1.43] - 2026-11-04

### Added
- **Phase 9: Multi-Agent Conversational Orchestration & Custom Localized Wake-Word Voice Satellites**:
  - Implemented `MultiAgentOrchestrator` in `agent_orchestrator.py` orchestrating 5 specialized sub-agent personas:
    - **Executive Butler (`executive`)**: Holistic butler, conversational coordinator, system oversight, and cross-domain collaborative synthesis.
    - **Sentinel Security (`sentinel`)**: Perimeter defense, intrusion kinematic tracking, camera vision analysis, deadbolt safety gates, and security audit enforcement.
    - **Energy Architect (`energy`)**: Solar PV forecasting, wholesale TOU tariff tracking, negative pricing co-optimization, EV charge scheduling, and peak load shedding.
    - **Spatial Media (`media_spatial`)**: Multi-zone audio matrix routing, spatial audio follow-me, dynamic volume ducking, and Bayesian presence fusion.
    - **Automation Engineer (`automator`)**: GUI-ready Home Assistant YAML generation (alias, description, triggers, conditions, actions, mode), routine sequencing, and habit validation.
  - **Dynamic Intent Classification & Multi-Agent Collaborative Synthesis**:
    - Automatic domain taxonomy classification mapping natural language queries to specialized agent personas.
    - Parallel multi-agent execution via `asyncio.gather` with cohesive executive synthesis and cross-domain action coordination.
  - **Custom Localized Wake-Word Voice Satellites**:
    - Discovery and mapping of `assist_satellite` and `wake_word` entities across spatial rooms and multi-room matrix audio zones.
    - Persistent per-satellite configuration of localized wake-words ("Hey Otis", "Computer", "Jarvis"), wake-word engines (`openwakeword`, `wyoming`, `micro_wake_word`), assigned agent personas, and preferred playback speakers.
    - **Spatial Acoustic Arbitration (Deduplication)**: Multi-satellite acoustic arbitration using RSSI, SNR, and presence fusion to select the authoritative satellite and suppress competing satellites during simultaneous wake triggers.
  - **Home Assistant Services**:
    - `otis_ai.orchestrate_multi_agent`: Route or collaboratively synthesize queries across agent personas.
    - `otis_ai.configure_voice_satellite`: Configure localized wake-word, area, persona, and speaker for an Assist satellite.
    - `otis_ai.arbitrate_satellite_audio`: Acoustically arbitrate multiple concurrent satellite triggers.
  - **Real-Time Telemetry Sensors**:
    - `sensor.otis_multi_agent_orchestrator`: Tracks active agent personas, routing metrics, and collaborative synthesis latency.
    - `sensor.otis_voice_satellites`: Tracks registered satellites, localized wake-words, and arbitration history.
  - Updated Lovelace `otis-companion-card.js` with Multi-Agent Specialists badges and Voice Satellite management view.
  - Fixed syntax error in `services.yaml` line 584 where unquoted YAML mapping characters caused loader failure.
  - Bumped integration and card version to v0.1.43.

## [0.1.42] - 2026-11-04

### Added
- **Phase 8: Advanced Multimodal Presence Fusion (BLE Trilateration, mmWave Micro-Motion, Thermal Imaging, and Acoustic Footprinting)**:
  - Implemented `PresenceFusionManager` in `presence_manager.py` integrating the 4 advanced spatial sensing pillars:
    - **BLE RSSI Trilateration & Distance Modeling**: Log-distance path loss propagation ($d = 10^{\frac{RSSI_0 - RSSI}{10 \cdot n}}$) and 2D/3D linearized least-squares trilateration across multi-anchor Bluetooth proxies with weighted centroid fallback and resident persona attribution.
    - **mmWave Micro-Motion & Static Target Sensing**: Stationary vs. moving target energy discrimination (LD2410, FP1/FP2, Screek), resolving micro-movements (breathing, chest displacement) while sitting still or asleep to permanently eliminate false-negative "vacant" states.
    - **Thermal Infrared Heat-Signature Discrimination**: Temperature delta evaluation ($\Delta T = T_{\text{target}} - T_{\text{ambient}}$) with human body surface temperature gating ($29.5^\circ\text{C} - 38.5^\circ\text{C}$), automatically discriminating and rejecting domestic pets and cold appliances/vacuums.
    - **Acoustic Footprinting**: Real-time ambient noise floor tracking, decibel spike evaluation, and voice/speech event detection with speech confidence bonuses.
  - **Dynamic Bayesian Sensor Fusion**:
    - Cross-validates modalities and discounts false positives (e.g. robot vacuums triggering PIR without human body heat or BLE, abandoned televisions without biological confirmation).
    - Introduced `micro_presence` state classification for resting/sleeping residents.
  - Implemented Home Assistant services `otis_ai.fuse_presence` and `otis_ai.trilaterate_ble`.
  - Implemented real-time telemetry publishing to `sensor.otis_fused_presence` reporting room-by-room breakdown, active modalities, coordinates, and attributed users.
  - Enhanced Assist conversational agent to answer spatial queries ("Where is everyone right now?", "Who is in the house?", "Multimodal presence") with rich room occupancy and micro-presence breakdowns.
  - Updated Lovelace `otis-companion-card.js` with Multimodal Presence Fusion view, `micro_presence` purple glowing badges, active modality pill tags (radar, thermal, BLE, sound), and user attribution.
  - Bumped integration and card version to v0.1.42.

## [0.1.41] - 2026-11-04

### Added
- **Phase 7: Contextual Energy Arbitrage with Time-Of-Use Tariffs, Solar Forecasting, and Smart EV/Battery Scheduling**:
  - Implemented dynamic tariff support in `EnergyManager` (`get_hourly_tariffs`), reading Nordpool, Amber, Tibber, and wholesale spot pricing sensors with negative pricing detection and standard TOU fallback.
  - Implemented contextual solar forecasting (`get_hourly_solar_forecast`), parsing Forecast.Solar and Solcast detailed hourly attribute tables with fallback to astronomical bell curves.
  - Implemented automated discovery of EVSE chargers (switches, amperage controllers, telemetry) and connected electric vehicles in `async_discover_energy_topology`.
  - Implemented `calculate_ev_charging_schedule` co-optimizing solar surplus utilization (curtailment avoidance) and lowest-cost off-peak grid windows prior to morning departure.
  - Implemented `otis_ai.schedule_ev_charging` and `otis_ai.execute_energy_arbitrage` services for automated dispatch of EV charger controls and battery modes.
  - Implemented real-time telemetry publishing to `sensor.otis_energy_arbitrage` with complete 24-hour horizon, EV charging metrics, and tariff details.
  - Added smart EV charging section, dispatch action triggers, and updated timeline indicators to Lovelace `otis-companion-card.js`.

### Fixed
- **Home Assistant 2026+ Deprecation Warning**:
  - Resolved `device_registry.devices` mapping usage deprecation in `mesh_manager.py:48`, iterating devices directly without `.values()` to guarantee seamless compatibility with HA 2026.10+ and 2027+.

## [0.1.40] - 2026-11-04

### Added
- **Phase 6: Autonomous Self-Healing Mesh Networking & Zigbee/Z-Wave Routing Optimizations**:
  - Implemented `MeshManager` in `mesh_manager.py` to audit mesh topology graphs across Z-Wave JS, Zigbee (ZHA & Zigbee2MQTT), and Thread/Matter ecosystems.
  - Added continuous neighbor table auditing, calculating Link Quality (LQI), signal strength (RSSI), round-trip time (RTT), and unified Mesh Health Score (0-100%).
  - Implemented `sensor.otis_mesh_health` reporting real-time mesh health status, dead node counts, marginal links, and healing telemetry.
  - Implemented `otis_ai.audit_mesh_health` service for on-demand non-blocking mesh audits.
  - Implemented `otis_ai.heal_mesh_node` service with protocol-tailored remediation (Z-Wave ping/heal_node/rebuild_routes, ZHA reconfigure, Zigbee2MQTT heal requests).
  - Added proactive mesh healing cards in Lovelace with quick-action `📡 Heal Mesh Node` chips.

## [0.1.39] - 2026-11-04

### Added
- **Phase 5 Step 5: Proactive Voice Announcement Controls & Person Identification with Audio Follow Attribution**:
  - Implemented `switch.otis_voice_announcements` with persistent state in `BehavioralRulesManager` and dynamic service listener, enabling instant silencing of spoken notifications when desired.
  - Added benign passerby and delivery courier intelligent filtering in `VisionPresenceManager.async_dispatch_visual_alert_voice` to suppress frightening TTS alerts for postal, delivery, and sidewalk pedestrians while maintaining visual dashboard logs.
  - Implemented `confirm_person_identity` service and proactive training cards in Lovelace to allow residents to verify and calibrate person recognition with continuous confidence scoring.
  - Bound media playback sessions to the triggering user/person in `AudioHandoffManager` (`session_owner` tracking), preventing cross-user audio follow-me collisions in multi-occupant homes.
  - Placed Proactive Security Voice Announcements entities card on Security Command Center view in `DashboardManager`.

## [0.1.38] - 2026-11-04

### Added
- **Phase 5 Step 4: Proactive Voice Notifications & Conversational Summaries on High-Confidence Visual Alerts**:
  - Implemented `async_synthesize_visual_alert_summary` in `VisionPresenceManager` to convert camera detections, perimeter zone contexts, and spatial kinematics into persona-tailored conversational summaries (butler, concierge, minimalist, witty).
  - Integrated local LLM conversational generation with deterministic zero-cloud fallback templates.
  - Implemented `async_dispatch_visual_alert_voice` with automated spatial audio ducking via `AudioHandoffManager`, 45-second per-target anti-spam cooldown, and quiet-hours-aware volume attenuation / whisper mode.
  - Automatically triggers proactive voice announcements on high-confidence perimeter detections (`confidence >= 0.70`, security anomalies, or escalating intruder tracks).
  - Registered Home Assistant service `otis_ai.announce_visual_alert` for manual or external automation triggers (e.g. Frigate, UniFi Protect).
  - Published alert tracking metrics to `sensor.otis_perimeter_sentinel` (`last_voice_announcement`, `last_voice_announcement_ts`).
  - Added real-time voice alert status banner and `📢 Re-announce` button to the Lovelace card Vision tab.
  - Placed dedicated Autonomous Spatial Audio Follow-Me control card (`switch.otis_audio_follow`, `sensor.otis_spatial_migration`) directly on the generated Media Studio view across both Command Center and Admin Companion dashboards.

## [0.1.37] - 2026-11-04

### Added
- **Phase 5 Step 3: Local RAG Vector Memory Integration with Live Telemetry & Device Manual Embeddings**:
  - Enhanced `RAGKnowledgeManager` (`rag_manager.py`) with hybrid dense vector + lexical keyword retrieval and live Home Assistant telemetry integration.
  - Implemented `async_index_entity_telemetry` to extract real-time entity states, area assignments, device classes, and telemetry attributes (climate, power, battery, media, switches, locks, cameras, sensors) and generate semantic vector embeddings.
  - Added `format_entity_telemetry_chunk` with attribute filtering to prioritize key telemetry (`current_temperature`, `power`, `battery`, `hvac_action`, `volume_level`) while pruning internal noise.
  - Implemented `async_index_device_manual` for ingesting hardware manuals with manufacturer, model, and domain taxonomy tags.
  - Expanded seeded smart home knowledge base with manuals for Lutron Caseta dimmers, Shelly Plus relays, Control4 audio matrix amplifiers, UniFi PoE access points & switches, and Yale Assure Lock 2 deadbolts.
  - Added recency boost in `async_query_knowledge` to prioritize fresh entity telemetry alongside hardware guides and manuals.
  - Published real-time index metrics to `sensor.otis_knowledge_rag` (`total_chunks`, `total_documents`, `categories`).
  - Registered Home Assistant services: `otis_ai.sync_entity_telemetry`, `otis_ai.index_device_manual`, and `otis_ai.toggle_audio_follow`.
  - Added options flow toggle for `audio_follow_enabled` in Home Assistant integration configuration.
  - Surfaced prominent "Spatial Audio Follow-Me" toggle switch in the Lovelace card Settings modal under the Voice & Quiet Hours tab, along with a 1-click `🔇 Disable Follow` button on active preconditioning banners.
  - Added bidirectional state synchronization and event listeners for `switch.otis_audio_follow`.

## [0.1.36] - 2026-11-04

### Added
- **Phase 5 Step 2: Multi-Camera Spatial Triangulation & Unified Intruder Track History**:
  - Implemented real-time multi-camera spatial triangulation in `VisionPresenceManager.process_visual_detection()`.
  - Correlates continuous physical tracks across multiple camera viewpoints using spatial zone coordinates and topology adjacency graphs.
  - Computes dynamic target kinematics: velocity vector, heading angle (0–360°), cardinal heading direction, and predictive next-area estimation.
  - Maintains unified track lifecycle: active track correlation with 180s expiration timeout, chronological trajectory waypoints, threat level classification (`normal`, `suspicious`, `intruder`, `critical`), and plain-English narrative summaries.
  - Publishes real-time track telemetry to `sensor.otis_intruder_tracks` (`clear`, `monitoring`, `tracking`, `breach`) and integrates active track counts into `sensor.otis_perimeter_sentinel`.
  - Dispatches `otis_ai_intruder_track_created` and `otis_ai_intruder_track_updated` bus events.
  - Registered `otis_ai.get_intruder_tracks` service in Home Assistant Core.
  - Added user behavioral rule persistence for `"audio_follow_enabled"` and user toggle entity support (`input_boolean.otis_audio_follow`, `switch.otis_audio_follow`) for non-admin Command Center dashboard users.

## [0.1.35] - 2026-11-04

### Added
- **Phase 5 Step 1: Real-Time Camera Snapshot Analysis & Perimeter Anomaly Detection**:
  - Implemented multimodal vision inference in `LocalLLMManager` (`async_analyze_vision`) supporting both Ollama native `/api/chat` with raw base64 images and OpenAI-compatible `/v1/chat/completions` with structured image URLs.
  - Added robust structured JSON response parser (`_parse_vision_response`) with heuristic regex fallbacks to classify detected objects (`person`, `vehicle`, `package`, `animal`), perimeter zone (`driveway`, `porch`, `front_door`, `backyard`, `gate`), security anomaly flags, risk severity (`normal`, `low`, `medium`, `high`, `critical`), confidence scores, and recommended actions (`turn_on_floodlights`, `notify_security`, `log_delivery`).
  - Added automatic vision model discovery to detect installed vision models (`llama3.2-vision`, `llava`, `qwen2.5-vl`, `minicpm`) or default to `llama3.2-vision:latest`.
  - Upgraded `VisionPresenceManager.async_analyze_camera` to capture live camera frames via `homeassistant.components.camera.async_get_image` and route through `LocalLLMManager`, with graceful fallback to edge sensor telemetry.
  - Added real-time perimeter sentinel tracking updating `sensor.otis_perimeter_sentinel` and firing `otis_ai_perimeter_anomaly_detected` and `otis_ai_vision_analysis_completed` events.
  - Added `async_audit_perimeter` method and registered `otis_ai.audit_perimeter` service to run concurrent anomaly scans across all perimeter cameras.
  - Created module alias `local_llm_manager.py` ensuring full parity with roadmap specifications.

## [0.1.34] - 2026-11-04

### Added
- **Phase 4 Step 4: Proactive Assist Integration & Spatial Habit Mining**:
  - Implemented `async_mine_spatial_habits` in `BehavioralHabitManager` to cluster physical room-to-room transitions into proactive habit recommendations.
  - Surfaced spatial habit recommendations with 1-click macro automation in proactive suggestions.
  - Added natural language conversational Assist support for spatial habit queries ("What spatial migration habits have you observed?").
  - Extended live pre-conditioning & `🎵 Audio Follow` status banner across all major card views: Home tab, Vision & Presence tab, and Interactive Floor Plan 2D/3D views.

### Fixed
- Fixed CI action failure by adding evening and self-consumption discharge action constants to arbitrage schedule assertions.

## [0.1.33] - 2026-11-04

### Added
- **Phase 4 Step 3: Multi-Zone Audio Migration & Seamless Hand-Off**:
  - Wired `sensor.otis_spatial_migration` into `AudioHandoffManager` to autonomously trigger media follow-me routing across multi-zone matrix amplifiers and smart speakers during room-to-room transitions.
  - Added quiet hours integration to cap target room audio volumes to configured threshold when migrations occur during overnight periods.
  - Linked audio migration lifecycle with `MacroManager` watchdog and `cancel_preconditioning` service to turn off target players if migrations are aborted.
  - Finalized departed zone power-down upon confirmed physical occupancy in target destination.
  - Added live `🎵 Audio Follow` badge to pre-conditioning chip in `otis-companion-card.js`.
  - Refactored area matching into shared global utilities (`zone_matches_area`, `filter_zones_by_area`), eliminating code repetition and zeroing hard-coded identifiers.

## [0.1.32] - 2026-11-04

### Added
- **Phase 4 Step 2: Contextual Pre-Conditioning State Engine & Macro Integration**:
  - Wired `sensor.otis_spatial_migration` into `MacroManager` to trigger soft pre-conditioning actions:
    - **Theater Room Pre-Cooling**: Automatically pre-cools theater comfort climate setpoint by -1°F upon migration intent detection (`movie_night`).
    - **Master Bedroom Nighttime Pre-Arming**: Triggers staged dim ambient illumination (10%) and pre-arms white noise machine / media player (`sleep_bedtime`).
  - **10-Minute Auto-Rollback Watchdog**: Monitors physical presence in the target destination. If the target area is not occupied within 10 minutes, cleanly executes `async_rollback_macro`, restoring all pre-migration setpoints and lighting.
  - **Companion Card Pre-Conditioning Chip**: Added real-time status banner chip (e.g. `🎬 Theater Pre-Cooling in progress [Cancel]`) with 1-click manual rollback.
  - Registered `otis_ai.cancel_preconditioning` service in Core and updated `services.yaml`.

## [0.1.31] - 2026-11-04

### Fixed
- **Interactive Floor Plan View Streamlining (`mode: floorplan_control`)**:
  - Completely stripped studio header (Back button, Interactive Floor Plan title/subtitle, Edit Blueprint, Themes, Rules, and Refresh buttons) from the Interactive Floor Plan view.
  - Hidden "Edit Floor Plan" (`btn-toggle-editor`) button from the toolbar in `floorplan_control` mode, confining blueprint editing strictly to the Floor Plan tab of the Otis AI Companion card.
  - Cleaned toolbar to present exclusively the view mode pills (2D, 3D), zone pills (All Floors, Ground & Outdoor, Upper Level, Outdoor Only), and floating 3D Orbit & Pitch Controls HUD.
- **3D Raised Glass Wall Alignment & Letterbox Scaling**:
  - Locked `#floorplan-canvas` aspect-ratio dynamically to the active zone's SVG viewBox (`1300 / 713` for main, `1300 / 488` for upper, `1300 / 1250` for all).
  - Stripped hardcoded `width` and `height` attributes from loaded SVG markup and eliminated `max-height` letterbox clamping, guaranteeing a 1:1 pixel match between the 3D walls overlay and the underlying 2D floorplan.

## [0.1.30] - 2026-11-04

### Fixed
- **Illuminated 3D Glass Walls Visibility & Styling**:
  - Upgraded 3D raised room walls to high-visibility architectural illuminated glass with vibrant 3px neon top rails (`#38bdf8`, `box-shadow: 0 0 14px #38bdf8`), 2px solid vertical corner posts, and frosted cyan gradient facets that pop distinctly in isometric 3D space.
  - Excluded outdoor perimeters (`frontyard`, `backyard`, `pool`) from raised room wall generation so vast exterior yards no longer mask indoor rooms.
  - Fixed floor zone switching bug in Companion Card: clicking "Ground & Outdoor", "Upper Level", or "Outdoor Only" now immediately recalculates SVG viewBox coordinates and calls `updateWallPositions()` and `updatePinPositions()`.
- **Save 3D to Dashboard Service Execution**:
  - Fixed `handle_regenerate_dashboards` in `__init__.py` which previously passed invalid `ServiceCall` arguments causing `force=False` and skipping dashboard regeneration. Implemented internal helper `_async_sync_dashboards_internal(force=True)`.
  - Added support in Companion Card `setConfig` for `mode: "floorplan_control"` and initialized `floorplan_azimuth`, `floorplan_pitch`, `floorplan_wall_height`, and `floorplan_walls_enabled` directly from card configuration and persisted behavioral rules.

## [0.1.29] - 2026-11-04

### Fixed
- **3D Raised Transparent Walls True Extrusion**:
  - Corrected inverted rotation angle signs on all 4 walls (North: $+90^\circ$, South: $-90^\circ$, West: $-90^\circ$, East: $+90^\circ$) which previously rotated into negative Z space (downwards behind the floorplan). All walls now stand upwards into positive Z space ($+36\text{px} \dots +50\text{px}$) with vibrant neon top rims.
  - Removed canvas transform `perspective(1200px)` which flattened child 3D contexts; enabled true 3D spatial hierarchy via stage `preserve-3d`.
- **Save 3D to Dashboard Persistence**:
  - Added `floorplan_3d`, `floorplan_view_mode`, `floorplan_azimuth`, `floorplan_pitch`, `floorplan_wall_height`, and `floorplan_walls_enabled` to `DEFAULT_RULES` in `BehavioralRulesManager`.
  - Updated `dashboard_manager.py` to cleanly rebuild the `/otis-ai/floorplan` and `/command-center/floorplan` views with `custom:otis-companion-card` in 3D mode upon user save.

## [0.1.28] - 2026-11-04

### Added
- **Phase 4 Step 1: Spatial Migration Flow Engine & Contextual Macro Pre-Conditioning**:
  - Implemented `record_area_transition`, `get_transition_history`, and `async_detect_migration_intent` in `VisionPresenceManager`.
  - Added 4 lifestyle migration intent classifiers (Evening Movie Migration to Theater, Night Bedtime Sleep to Master, Morning Awakening to Kitchen, Daytime Focus to Study/Office).
  - Published real-time spatial migration sensor `sensor.otis_spatial_migration` with pre-conditioning hypotheses (`armed` / `idle`), confidence scores, and suggested macro actions.
- **3D Raised Transparent Wall Rendering & Dashboard Sync**:
  - Eliminated CSS 3D context-flattening bug caused by `filter: drop-shadow` on the 3D canvas and `backdrop-filter` on walls.
  - Enhanced extruded glass walls with rich semi-transparent cyan styling, neon glowing top rims, and bidirectional `backface-visibility`.
  - Added `💾 Save 3D to Dashboard` button in 3D HUD to persist default camera angles and sync the 3D interactive view to the Home Assistant "Interactive Floor Plan" dashboard view.

## [0.1.27] - 2026-11-04

### Fixed
- **Lovelace Frontend Card Syntax & Registration**:
  - Eliminated trailing dangling pin-position lines in `otis-companion-card.js` that caused browser JavaScript parser `SyntaxError` and triggered `Custom element doesn't exist: otis-companion-card`.
  - Added automated ES2022+ QuickJS JavaScript evaluation test (`test_card_javascript_syntax_validity`) to prevent JavaScript syntax regressions.
- **GitHub Actions CI Workflow**:
  - Resolved `ModuleNotFoundError: No module named 'pytest'` and unit test discovery failures by configuring `pytest`, `pytest-asyncio`, and `quickjs` dependencies and running `pytest tests`.

## [0.1.26] - 2026-11-04

### Added
- **Raised Transparent 3D Glass Walls & Architectural Extrusion**:
  - **Dynamic CSS 3D Room Shell Extrusion**:
    - Extrudes vertical frosted glass walls along room perimeters (North, South, East, West) standing up in physical 3D space (`transform: rotateX/Y`) with neon-capped top wall rims.
    - Low perimeter architectural railing/glass for outdoor zones (patio, deck, pool) vs full-height interior glass partitions.
    - Context-aware presence illumination: occupied rooms illuminate their transparent 3D glass walls with a vibrant emerald green glow in real time.
    - HUD wall controls: dedicated `🏢 3D Walls` toggle pill and wall height stepping adjustment controls ($\pm 4\text{px}$) with persistent settings in `localStorage`.
  - Bumped Lovelace Companion Card to `v0.1.26`.

## [0.1.25] - 2026-11-04

### Added
- **Interactive Floorplan 3D Orbit & Pitch Controls (Roadmap Phase 3)**:
  - **Dynamic 3D Camera Orbit & Pitch Projection Engine**:
    - Interactive 3D perspective projection onto the floorplan canvas with smooth orbit azimuth ($0^\circ \dots 360^\circ$) and pitch incline ($30^\circ \dots 75^\circ$).
    - Zero-drift SVG device pin coordinate locking: pins are mapped via exact viewBox relative percentage vectors inside the 3D-transformed canvas, preventing subpixel offset or drift during high-speed rotation and tilt.
    - Automatic 3D pin billboarding: pin badges and state icons counter-rotate on GPU hardware acceleration to remain upright and oriented toward the viewer across all azimuth and pitch angles.
    - Smooth gesture & pointer controls: intuitive click-and-drag orbit and pitch manipulation on the canvas with pointer capture, plus mouse wheel and pinch-to-zoom scaling ($0.6\times \dots 1.8\times$).
    - Floating Frosted Glass 3D HUD: real-time live azimuth/pitch readout, dual continuous range sliders, single-step angle nudges ($\pm 15^\circ$ azimuth, $\pm 5^\circ$ pitch), 8 cardinal/isometric preset pills (`0° N`, `45° NE`, `90° E`, `135° SE`, `180° S`, `225° SW`, `270° W`, `315° NW`), one-click default reset, and collapsibility toggle.
    - Persistent Camera State: stores and restores custom azimuth, pitch, scale, and active view mode across browser reloads via `localStorage`.
    - Intelligent Canvas Editor Integration: automatically drops into 2D orthogonal grid when entering edit mode for room boundary adjustments, restoring the user's active 3D orbit camera on exit.
  - Bumped Lovelace Companion Card to `v0.1.25`.

## [0.1.24] - 2026-11-04

### Added
- **Context-Aware Energy Arbitrage & Battery Scheduling (Roadmap Phase 2)**:
  - **Dynamic 24-Hour Battery Arbitrage Simulation Engine (`EnergyManager`)**:
    - Generates hourly battery charge/discharge target schedules based on solar forecast curves, residential diurnal consumption profiles, and grid TOU (Time-Of-Use) electricity rates.
    - Four operating strategies: `auto` (adaptive TOU shave & solar absorption), `peak_arbitrage` (aggressive peak discharge during 2:00 PM – 7:00 PM), `self_consumption` (zero grid dependency), and `backup_reserve` (100% emergency outage preservation).
    - Simulates battery State of Charge (SoC %), net solar surplus/deficit, grid power flow, and computes exact projected daily cost savings ($) and peak kW shaved.
  - **New Registered Services**:
    - `otis_ai.optimize_battery_schedule`: Configure mode, battery capacity, reserve floor, and custom forecast/load parameters to generate and set active arbitrage schedules.
    - `otis_ai.get_energy_arbitrage_plan`: Query live battery SoC, solar forecasts, and household load to return active recommendations and 24-hour timeline.
  - **Autonomous Local LLM Tool Calling (`DEFAULT_OTIS_TOOLS`)**:
    - Exposed JSON Schema specifications for `optimize_battery_schedule` and `get_energy_arbitrage_plan` allowing local Ollama and OpenAI-compatible models to optimize energy storage autonomously during multi-step reasoning.
  - **Conversational Assist Intent Routing**:
    - Added natural language intent recognition (*"What is my energy arbitrage plan?"*, *"Optimize battery for storm outage backup"*, *"Show battery schedule"*) returning structured summaries with current power flow and 6-hour upcoming previews.
  - **Lovelace Companion Card Energy Arbitrage Widget & Timeline Strip**:
    - Added real-time battery status tile to the Capabilities & Architecture tab in `otis-companion-card.js` with live SoC %, flow direction indicators (📥 Charging / 📤 Discharging / ⏸️ Holding), mode switcher pills (`Auto`, `Peak Shave`, `Solar Soak`, `Backup`), interactive 24-hour hourly tariff/schedule strip, and 1-click re-optimization trigger.
  - Bumped Lovelace Companion Card to `v0.1.24`.

## [0.1.23] - 2026-11-03

### Fixed
- **Home Assistant Event Loop Non-Blocking I/O Conformance (HACS Review #13059)**:
  - Offloaded all synchronous filesystem I/O operations from async routines to the Home Assistant executor pool via `hass.async_add_executor_job` across all modules:
    - `OtisWalkthroughUploadView.post`: Offloaded directory creation with `partial(os.makedirs, upload_dir, exist_ok=True)` and replaced blocking `os.path.getsize` with stream chunk byte counters.
    - `AutomationManager.async_cross_reference`: Extracted blueprint file inspection and Home Assistant log scan into executor helper functions to avoid blocking on `open()` and `os.path.exists()`.
    - `ThemeManager.async_generate_and_save_theme` & `async_list_otis_themes`: Ensured directory creation and existence checks run strictly inside thread executor jobs.
    - `FloorplanParser`: Replaced event-loop blocking `os.path.exists()`, `os.path.isdir()`, and `open()` calls in walkthrough processing, audio extraction, audio concatenation, and layout updating with executor jobs.
  - Bumped Lovelace Companion Card to `v0.1.23`.

## [0.1.22] - 2026-11-03

### Added
- **Local LLM Embedding-Based RAG for Smart Home Manuals & Historical Events (Roadmap Item 1)**:
  - **Persistent Local Knowledge Store (`RAGKnowledgeManager`)**: Fully zero-cloud vector knowledge base persisted across Home Assistant restarts in `.storage/otis_ai_knowledge_store`.
  - **Hybrid Dense + Lexical Retrieval**: Combines cosine similarity from dense vector embeddings (via Ollama `/api/embed`, legacy `/api/embeddings`, or OpenAI `/v1/embeddings`) with deterministic subword fallback hash vectors and sparse token overlap (BM25/Jaccard), ensuring search functions even if local neural models are offline or loading.
  - **Automatic Text Chunking**: Semantic document chunking engine splitting user manuals, Markdown guides, and hardware notes by paragraphs and sentence boundaries with configurable overlap.
  - **Smart Home Historical Event Indexing**: Transforms entity state transitions, Sentinel watchdog remediation logs, and automation anomaly events into searchable historical context.
  - **New Registered Services**:
    - `otis_ai.index_document`: Ingest device manuals, troubleshooting guides, or notes with custom metadata and category filtering.
    - `otis_ai.query_knowledge_base`: Semantic vector retrieval returning ranked knowledge snippets with relevance scores.
    - `otis_ai.index_entity_history`: Ingest recent state history or anomaly logs for specific entities.
    - `otis_ai.clear_knowledge_base`: Prune or wipe knowledge entries by category, document ID, or full reset.
  - **Default Smart Home Manual Pre-Seeding**: Automatically seeds essential architectural references (Otis AI core services, TP-Link/Shelly/Inovelli smart switch Wi-Fi reset procedures, Zigbee/Z-Wave mesh healing topology rules) when store is initialized.
  - **Assist Co-Pilot Prompt RAG Injection**: Automatically searches the local knowledge base on user queries and injects relevant device documentation into the system prompt context before reasoning.
  - **Autonomous Tool Calling Integration**: Added `query_knowledge_base` to `DEFAULT_OTIS_TOOLS` for autonomous local LLM retrieval during multi-step reasoning.
- Bumped Lovelace Companion Card to `v0.1.22`.

## [0.1.21] - 2026-11-02

### Added
- **Advanced Local LLM Structured Tool Calling & Autonomous Planning (Roadmap Phase 3)**:
  - **Standard JSON Schema Tool Suite**: Defined native JSON schema definitions in `local_llm.py` for core Otis AI services:
    - `pin_floorplan_entity`: Pin entity badges to 2D blueprint or 3D isometric layers.
    - `unpin_floorplan_entity`: Remove badges from the floorplan.
    - `run_sentinel_watchdog`: Run proactive anomaly auditing and self-healing.
    - `turn_off_stuck_actuator`: Shut down stuck or runaway devices.
    - `restart_ble_proxy`: Self-heal stalled Bluetooth / ESPHome proxies.
    - `heal_mesh_node`: Ping and refresh unresponsive Zigbee/Z-Wave nodes.
    - `regenerate_dashboards`: Trigger dynamic Modern Sections or Classic Grid updates.
    - `analyze_camera`: Perform vision inspection on camera streams.
    - `execute_macro`: Execute predefined smart home routines.
    - `call_ha_service`: Generic dispatch for any Home Assistant service call.
  - **Ollama v0.3+ & OpenAI Function Calling Support**: Native integration with Ollama `/api/chat` `tools` parameter and OpenAI-compatible `/v1/chat/completions` `tools` spec.
  - **Resilient Multi-Format Fallback Extraction**: Robust parsing for smaller local models (e.g. `qwen2.5:1.5b`, `llama3.2:1b`, `phi-3`) supporting:
    - `<tool_call>{"name": ..., "arguments": ...}</tool_call>` XML tags.
    - Markdown ````json { "tool": ..., "parameters": ... } ```` blocks.
    - Inline invocation syntax `[TOOL_CALL: name(args)]`.
  - **Multi-Step Offline Autonomous Planning Engine (`async_chat_with_tools`)**: Multi-turn reasoning loop executing planned tools against Home Assistant services and re-prompting the LLM with execution observations.
  - **New Registered Service `otis_ai.execute_tool_plan`**: Execute explicit tool plans or natural language autonomous tool calling requests directly from automations, Lovelace, or scripts.
  - **Assist Co-Pilot Failover Integration**: Transparently invokes `async_chat_with_tools` during offline/local LLM failover, empowering local models to take physical actions autonomously.
- Bumped Lovelace Companion Card to `v0.1.21`.

## [0.1.20] - 2026-11-02

### Added
- **Contextual Presence-Based Room Cards & Dynamic Elevation (Roadmap Phase 2)**:
  - **Dynamic "Active Rooms" Section in Command Center**: Elevates active, occupied rooms to the top of the Command Center dashboard (`/command-center`) in Modern Sections and Classic Grid views.
  - **Fused Presence Entity Publishing**: `VisionPresenceManager` automatically computes Bayesian multi-sensor occupancy fusion (mmWave radar, PIR motion decay, media playback, BLE room beacons, and person entities) and publishes native Home Assistant entities:
    - `binary_sensor.otis_presence_<slug>`: Real-time room occupancy (device class `occupancy`, probability, confidence percentage, and active sensor breakdown).
    - `binary_sensor.otis_active_occupancy`: Whole-home active occupancy indicator.
  - **Real-Time State Change Tracking**: Event listener on `EVENT_STATE_CHANGED` for motion, presence, and media player entities automatically recalculates and publishes room presence with intelligent debouncing.
  - **Intelligent Conditional Room Cards**: Renders high-utility quick-control tiles (primary lights with brightness sliders, climate setpoints, media players, fans) and direct navigation buttons within `type: conditional` cards.
  - **Zero-Clutter Collapsing**: The Active Rooms section and its conditional heading automatically collapse to 0 height when rooms are vacant, cleanly keeping the dashboard focused and uncluttered.
  - **Floor Plan Live Presence Badges**: The Companion Card room inspector displays real-time occupancy status (`🟢 Active (N%)` vs `⚪ Vacant`) based on fused presence.
- Bumped Lovelace Companion Card to `v0.1.20`.

## [0.1.19] - 2026-11-01

### Added
- **Multi-Floor 3D Isometric View & Architectural Layering (Roadmap Phase 1)**:
  - **Pseudo-3D Isometric Layout Projection**: Computes 2.5D axonometric projection ($30^\circ$ pitch) mapping orthogonal room boundaries into isometric screen coordinates in `FloorplanParser`.
  - **Multi-Floor Vertical Stacking & Structural Risers**: Renders Ground Floor & Outdoor slab at baseline ($z = 0$) and Upper Level suspended directly above ($z = +320\text{px}$), visually linked by vertical structural corner guide pillars and an isometric staircase riser between Mudroom and Gym.
  - **3D Depth Facets & Slabs**: Renders South-facing and East-facing extruded slab depth facets ($T = 12\text{px}$) for physical architectural slab thickness, ambient drop shadows, and glowing accent wall strokes.
  - **Dual-Layer & Standalone SVG Synthesis**: Automatically compiles dual-mode `otis_floorplan.svg` (embedding `<g id="view-mode-2d">` and `<g id="view-mode-3d">`) and standalone `otis_floorplan_3d.svg` (viewBox `0 0 1300 1080`, 3D active by default) during floorplan generation.
  - **Lovelace Companion Card 2D / 3D Switcher**: Added `📐 2D` and `🧊 3D` view mode pills to the floorplan toolbar with instant toggle and `localStorage` persistence.
  - **Real-Time 3D Pin Projection**: Projecting entity pins and status badges onto isometric room coordinates using SVG coordinate transform matrices (`createSVGPoint().matrixTransform(ctm)`).
  - **Zone & Floor Filtering in 3D**: Full support for "All Floors" (stacked cutaway), "Ground & Outdoor", "Upper Level", and "Outdoor Only" with adaptive isometric viewBox framing.
- Bumped Lovelace Companion Card to `v0.1.19`.

## [0.1.18] - 2026-11-01

### Added
- **Advanced Sentinel Watchdog Actions & Proactive Self-Healing (Roadmap Item 3)**:
  - **Unresponsive BLE Proxies & Bluetooth Adapters**: Detects offline or disconnected ESPHome BLE proxies, Shelly Bluetooth gateways, and Bluetooth dongles. Automatically identifies matching hardware restart buttons (`button.<node>_restart`) or config entries and executes 1-click self-healing restart (`restart_ble_proxy`).
  - **Runaway & Stuck Actuators**: Detects runaway lights, bathroom exhaust fans, and non-critical switches left ON continuously for excessive durations (> 90m for fans, > 120m for lights) while strictly excluding critical infrastructure (servers, UPS, refrigerators, PoE switches, network hardware). Offers 1-click `turn_off_stuck_actuator` auto-off remediation.
  - **Zigbee & Z-Wave Mesh Routing Health**: Audits mesh health for dead or unresponsive Zigbee and Z-Wave routing nodes (`is_failed`, `node_status: dead`, offline mains routers) with 1-click self-healing ping/heal actions (`heal_mesh_node`).
  - **Enhanced Low Battery Notifications**: Proactive reminders with persistent notifications detailing device name, area, and battery level (`notify_battery_replacement`).
  - **Auto-Remediate Scan Pipeline**: Added `auto_remediate: boolean` parameter to `otis_ai.run_sentinel_watchdog` (`async_scan_all_anomalies(auto_remediate=True)`) to automatically self-heal safe anomalies (runaway lights/fans, failed integrations, dead mesh nodes, unresponsive BLE proxies) during scheduled watchdog audits.
  - **Conversational Assist Intents**: Intercepts natural language voice/text requests (*"Remediate anomalies"*, *"Heal network"*, *"Auto heal system"*, *"Audit system anomalies"*, *"Check smart home health"*) to trigger watchdog audits and auto-remediations with conversational summaries.
- Bumped Lovelace Companion Card to `v0.1.18`.

## [0.1.17] - 2026-11-01

### Added
- **Floorplan Interactive Pinning & Conversational Assist (Roadmap Item 2)**:
  - **Conversational Floorplan Pinning**: Assist Co-Pilot dynamically parses natural language commands to pin or reposition devices onto the 2D floorplan (e.g. *"Pin dining chandelier to dining room on the floorplan"*, *"Pin light.patio at 450, 320"*, *"Unpin light.patio from floorplan"*), computing room centers and anti-stacking offsets automatically.
  - **Native Home Assistant Services**: Registered `otis_ai.pin_floorplan_entity` and `otis_ai.unpin_floorplan_entity` with full schema in `services.yaml` and Lovelace event notifications (`lovelace_updated`, `otis_ai_floorplan_updated`).
  - **Spatially Aware Drag-and-Drop Drop-In**: Dropping newly discovered entities via the Floor Plan tab's Add Marker modal calculates the entity's registered room bounding polygon and automatically centers the pin in that room rather than an arbitrary default coordinate.
- Bumped total registered native services to 55.
- Bumped Lovelace Companion Card to `v0.1.17`.

## [0.1.16] - 2026-11-01

### Added
- **Modern Sections Studio & Room Ergonomics**:
  - **HVAC Dual-Setpoints in Climate Studio & Room Views**: Thermostats in Modern Sections render interactive `tile` cards with dual-setpoint `target-temperature` controls (+/- increment steppers for heat & cool thresholds) and `climate-hvac-modes` chips, eliminating bulky stacked circular dials.
  - **Separation of HVAC & Pool Heating**: Dedicated "HVAC Thermostats & Dual-Setpoints" section and separated "Pool & Spa Water Temperature" section for clean domain-specific organization.
  - **Balanced 2-Column Perimeter Video Wall**: Live camera feeds in Security Studio and Room views now incorporate `layout_options: { grid_columns: 2, grid_rows: auto }` and `column_span: 2`, displaying a balanced 2x2 or 2x3 grid across desktop and tablet without vertical feed stretching.
  - **Header Section Consolidation**: Consolidated navigation buttons and descriptive subtitles into a single unified Header section, preventing empty column allocation in 3-column desktop layouts.
  - **Section Heading Deduplication**: Automatically stripped redundant internal card titles when converted to modern section heading cards to eliminate duplicate headers on entities cards.
- Bumped Lovelace Companion Card to `v0.1.16`.

## [0.1.15] - 2026-11-01

### Fixed & Improved
- 📱 **Immediate Household Rules & Layout Pipeline Execution (`dashboard_manager.py`, `__init__.py`, `const.py`, `services.yaml`)**:
  - Implemented full pipeline execution for **Select Dashboard Layout** (`modern_sections` vs `classic_grid`), **Navigation Button Style** (`sleek_buttons` vs `standard_grid`), and **Schedule & Calendar Display** (`listDay` vs `month`/`dayGridMonth`) across the Command Center, all Studios (Media, Security, Climate & Pool, Energy, Floor Plan), and Room subviews.
  - Added native responsive `sections` conversion (`_convert_cards_to_sections`, `_build_studio_view`) for Studios and Rooms when modern sections layout is selected, while cleanly purging `type: "sections"` and `sections` blocks when classic card grid is chosen.
  - Resolved stale dashboard cache inheritance in `_merge_dashboard_config_preserving_user_views` by supporting `force_regenerate=True` and instantly firing `lovelace_updated` bus events for both `otis-ai` and `command-center`.
- ⚡ **1-Click Dashboard & Studio Regeneration (`dashboard_manager.py`, `__init__.py`, `otis-companion-card.js`)**:
  - Registered native `otis_ai.regenerate_dashboards` service and enhanced `otis_ai.sync_dashboards` with `force: true` / `regenerate: true`.
  - Added dedicated `⚡ Regenerate Now` control in the Companion Card Rules modal under Dashboard & Layout and quick-action `⚡ Regenerate` in the Subview Launchpad.
  - Added voice/chat intent handling allowing users to say "regenerate dashboards" / "rebuild command center" to trigger clean regeneration of all studios, rooms, and command center views.
  - Bumped Companion Card version to v0.1.15.

---

## [0.1.14] - 2026-11-01

### Fixed & Improved
- 📐 **Direct Blueprint Inspection, Editing & 1-Click Deployment (`automation_manager.py`, `__init__.py`, `otis-companion-card.js`)**:
  - Added `async_write_blueprint` and `async_reload_blueprints` in `AutomationManager` giving Otis AI full filesystem access to update `/config/blueprints/automation/<path>`.
  - Added blueprint YAML extraction (`type: "blueprint"`) and staging in `_extract_pending_items_from_speech`.
  - Added 1-click `🚀 Deploy & Update Blueprint` action button in the Companion Card with autonomous confirmation handling.
  - Enhanced system prompt across all model tiers explicitly noting full authority to update blueprints directly (preventing failover models from refusing to edit blueprints or attempting to unlink them into standalone automations).
  - Grounded security prompt: explicitly noted perimeter locks (`lock.front_door`, `lock.back_door`, `lock.garage_door`) are WiFi Schlage Encode deadbolts running on native `schlage` integration (never Z-Wave).
  - Bumped Companion Card version to v0.1.14.

---

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
