# Changelog

All notable changes to the Otis AI Companion integration are documented in this file.

## [1.9.1] - 2026-10-30

### Fixed & Improved
- **Assist Co-Pilot Chat Stability & State Persistence (`otis-companion-card.js`)**:
  - Resolved issue where entering a prompt immediately refreshed the card back to the Proactive Feed tab and wiped chat history.
  - Added strict `e.preventDefault()`, `e.stopPropagation()`, and `e.stopImmediatePropagation()` to `chatInput` keydown and `chatSend` click listeners to prevent event bubbling and accidental form submits.
  - Explicitly added `type="button"` to all 62 `<button>` elements in the card (including `#chat-send`, `#chat-mic`, `#btn-save-layout`, tabs, and prompt chips) to prevent default HTML `<button type="submit">` behavior from triggering parent form submissions or full-page reloads.
  - Added `sessionStorage` persistence for `_activeTab` (`otis_active_tab`) and `_chatMessages` (`otis_chat_messages`), ensuring active tab location and multi-turn conversational history persist seamlessly across card re-mounts and dashboard view updates.
  - Upgraded `_sendChatMessage` with dual-transport execution: first attempts native WebSocket `call_service` with `return_response: true` before falling back to `callService` and `conversation.process`, ensuring robust prompt execution and reliable response speech rendering.
  - Added `🗑️ Clear` chip button in Assist Co-Pilot header allowing users to reset conversational history on demand.
- **Floor Plan Canvas Editor Save In-Place (`otis-companion-card.js`)**:
  - Removed disruptive client-side `ll-rebuild` and `location-changed` event dispatches from `btnSaveLayout` and `btnDeleteRoom`, eliminating card destruction and unwanted tab resets to Proactive Feed when saving layout changes or deleting rooms.
  - Fixed `btnDeleteRoom` invocation to call `this._loadFloorplanSvg()` instead of the non-existent `this._fetchFloorplanSvg()`.

## [1.9.0] - 2026-10-29

### Added & Improved
- **Phase 5 Dynamic Macro Orchestrator & Multi-Step Assist Pipelines (`macro_manager.py`, `__init__.py`, `const.py`, `services.yaml`, `otis-companion-card.js`)**:
  - Expanded Assist Co-Pilot conversational execution into intelligent multi-step atomic sequences:
    - **Movie Night Mode**: Dims media/living room lights to 15%, selects TV/HDMI matrix source (e.g. 'Apple TV' or streamer), adjusts comfort climate to 68°F, sets soundbar/AVR volume to 45%, and closes window shades.
    - **Goodnight Routine**: Extinguishes common area lights, engages perimeter security deadbolts, closes garage doors, lowers climate to 66°F, powers off media players, and arms security alarm.
    - **Entertain & Party Mode**: Broadcasts matrix audio across multi-room zones, sets warm ambient scene lighting, and balances climate for social comfort.
    - **Away & Lockdown Mode**: Extinguishes non-essential lights, locks deadbolts, closes garage doors, shuts down media zones, and arms security to Away mode.
    - **Welcome Home Arrival**: Illuminates entryway and living pathway lighting, restores comfort climate, unlocks entryway deadbolt, and disarms security.
  - **Atomic Prior State Snapshotting & 1-Click Rollback (`async_rollback_macro`)**:
    - Captures an atomic state snapshot of all affected entities immediately prior to macro sequence execution.
    - Maintained ring-buffer execution history allowing users to say "undo", "rollback", or "revert", or call the `otis_ai.rollback_macro` service to restore every entity to its exact prior state (including light brightness/color, thermostat setpoint, media player source/volume, lock states, and cover positions).
  - **Pre-Flight Safety Checks & Step Confirmation**:
    - Guarded high-impact security actions (`lock.unlock`, `alarm_control_panel.alarm_disarm`, `cover.open_cover`).
    - Prompts the user with structured multi-step previews, safety warnings, and explicit confirmation requirements before running critical sequences.
  - **Assist Co-Pilot Frontend Integration (`otis-companion-card.js`)**:
    - Added quick macro action chips (`🎬 Movie Night`, `🌙 Goodnight`, `🥂 Party Mode`, `🛡️ Lockdown`, `↺ Undo`) to the Assist Co-Pilot tab.
    - Added interactive inline confirmation buttons (`✅ Confirm & Execute`, `✕ Cancel`, `↺ Rollback / Undo Macro`) directly inside Otis conversational chat bubbles for 1-click execution.
  - **Services Registered (`otis_ai`)**:
    - `otis_ai.execute_macro`: Executes built-in or custom multi-step macro sequences with confirmation guards and state snapshotting.
    - `otis_ai.rollback_macro`: Restores entities from recent macro executions.
    - `otis_ai.list_macros`: Lists available macro templates and execution history.

## [1.8.1] - 2026-10-29

### Fixed & Improved
- **Automatic Floor Plan & Command Center Synchronization (`floorplan_parser.py`, `dashboard_manager.py`, `__init__.py`, `otis-companion-card.js`)**:
  - Connected `_calculate_orthogonal_layout` and `_build_floorplan_view_cards` to `custom_layout` room and badge coordinates, ensuring the `picture-elements` card on `/command-center/floorplan` and `/otis-ai/floorplan` mirrors custom floor plan edits with exact visual alignment.
  - Parsed rendered `<rect>` coordinates from `www/otis_floorplan.svg` into layout calculations so all navigation hotspots, room icons, and intelligent dock controls align with real blueprint geometry.
  - Implemented merging for `custom_layout["rooms"]` and `custom_layout["badges"]` to persist all multi-room adjustments across sessions.
  - Added live dashboard bus event notifications (`lovelace_updated`, `otis_ai_floorplan_updated`) and client-side view refresh signals (`ll-rebuild`, `location-changed`) to immediately update views without manual page reloads.

## [1.8.0] - 2026-10-29

### Fixed
- **Floor Plan Text Tag Attribute Corruption (`floorplan_parser.py`, `otis-companion-card.js`)**:
  - Fixed SVG text label regex generation where attribute values (`x="..." y="..."`) were placed outside the opening tag (`<text class="room-header"> x="..." y="...">Room Name</text>`), causing browser SVG renderers to treat them as text content at coordinate (0, 0) and hiding room titles and subzones.
  - Implemented depth-aware room group parsing (`find_room_group_span`) to accurately match parent `<g class="room-group">` elements to their corresponding closing `</g>` tags without prematurely halting on child `<g class="entity-badge">` tags.
  - Added automated server-side and client-side sanitizers (`sanitize_corrupted_svg_text`) to detect and heal previously corrupted SVG text elements upon loading and saving.
  - Repositioned outdoor subzones (`▪ Deck & Grill`, `▪ Hot Tub`, `▪ Side Gate`) into Backyard boundary geometry when moved or resized.

### Added & Improved
- **Phase 4 Step 3 Magnetic Snapping & Alignment Guides (`otis-companion-card.js`)**:
  - Implemented dynamic magnetic wall snapping: when dragging or resizing rooms in Canvas Editor, edges snap magnetically within a 12px threshold to adjacent room walls (aligning left/right/top/bottom edges and abutments).
  - Added live dashed cyan SVG alignment guidelines (`.snap-guides-layer`) showing real-time wall alignment axes across the canvas.
- **Multi-Floor Level Switching Persistence (`otis-companion-card.js`)**:
  - Persisted the active floor zone (`All Floors`, `Ground & Outdoor`, `Upper Level`, `Outdoor Only`) in `localStorage` across page refreshes and editor toggles.
  - Added smart auto-switching: selecting any upper level or outdoor room in Canvas Editor automatically aligns the active floor zone to match that room's level.

## [1.7.0] - 2026-10-29

### Added & Improved
- **Interactive 8-Point Canvas Editor & Whole-Room Dragging (`otis-companion-card.js`, `floorplan_parser.py`)**:
  - Implemented 8 distinct resize handles (`nw`, `n`, `ne`, `e`, `se`, `s`, `sw`, `w`) allowing direct width-only and height-only adjustments from any edge or corner.
  - Enabled direct room dragging (`type: "move"`): clicking and dragging anywhere inside a selected room smoothly repositions the entire room across the architectural canvas.
  - Synchronized all internal room contents live during drag and resize operations: architectural subzone labels (e.g. `▪ Deck & Grill`, `▪ Hot Tub`), entity badges, staircase cuts, and doorway thresholds move seamlessly with room boundaries.
  - Added strict plan frame clamping: room boundaries are strictly clamped within the blueprint outer border (`minX >= 40`, `maxX <= 1260`, `minY >= 30`, `maxY <= 1400`), preventing rooms from extending outside the blueprint into the canvas void.
- **Draggable Area Boundary Editor Box (`otis-companion-card.js`)**:
  - Made the Area Boundary Inspector card draggable: users can grab the header bar and move the dialog anywhere across the canvas so it never obstructs the room or section being configured.
- **Flicker-Free Handle Hover Styling (`otis-companion-card.js`)**:
  - Removed SVG CSS `transform: scale(1.4)` on `:hover` which caused rapid 60Hz flickering when hovering near handle boundaries; replaced with stable high-contrast fill and stroke styling.
- **Backend Layout Synchronization (`floorplan_parser.py`)**:
  - Enhanced `update_floorplan_layout` with boundary clamping and automated regex synchronization for `.subzone-pill` labels, `.entity-badge` groups, and `.stairs-step` elements.

## [1.6.9] - 2026-10-29

### Fixed
- **Canvas Editor Boundary Snap-Back Resolution (`otis-companion-card.js`)**:
  - Resolved snap-back bug where clicking "Update Boundary" in the Area Boundary Inspector caused the room to revert to its original position.
  - Eliminated disruptive full DOM `_render()` call on inspector update; boundary coordinates, SVG rect footprint, text label, and corner resize handles are now updated directly in place.
  - Added pending layout state persistence (`_dirtyRooms` and `_dirtyBadges` re-application) inside `_attachFloorplanListeners()`, guaranteeing modified room dimensions and repositioned pins persist visually across room selection changes until explicitly saved.

## [1.6.8] - 2026-10-29

### Added & Improved
- **Automatic Studio & Room Synchronization to Command Center (`dashboard_manager.py`, `__init__.py`, `const.py`, `otis-companion-card.js`)**:
  - Implemented automatic bi-directional inheritance: any customizations made to Studios (`media`, `security`, `climate`, `floorplan`) and Room subviews (`area_{slug}`) on the Otis AI dashboard are automatically synchronized to the Command Center dashboard (`/command-center`).
  - Added URL rewriting engine mapping `/otis-ai/` paths to `/command-center/` across all cards, navigation actions, and badges so non-admin users always stay within the Command Center dashboard context.
  - Command Center Home view (`home`) now automatically synchronizes its "Studios" grid and "Rooms" grid whenever rooms are added, deleted, or updated, while strictly preserving any custom cards added by the user.
  - Automatic synchronization runs whenever `update_floorplan_layout`, `generate_floorplan`, or discovery scans complete.
  - Registered `otis_ai.sync_dashboards` backend service and added a 1-click `🔄 Sync Command Center` launchpad chip to the companion card.
  - Dynamic dashboard path detection: companion card chips automatically route to `/command-center` when viewed inside Command Center.

## [1.6.7] - 2026-10-29

### Added & Improved
- **Floor Plan Canvas Room Deletion (`floorplan_parser.py`, `otis-companion-card.js`, `__init__.py`, `services.yaml`)**:
  - Added 1-click room deletion directly from the Area Boundary Inspector panel in the Floor Plan Canvas Editor.
  - Deleting an area immediately removes its SVG boundary `<g class="room-group" data-area-id="...">` element, purges it from metadata `custom_layout["rooms"]`, registers it in `deleted_rooms`, and triggers instant SVG live refresh.
  - Added `deleted_rooms` parameter to `otis_ai.update_floorplan_layout` service call and updated service schema.
  - Synchronized dashboard configuration regeneration upon floor plan update and room deletion.
- **Intelligent Controllable Device Selection for Interactive Floor Plan (`dashboard_manager.py`)**:
  - Implemented `_select_intelligent_room_controls` heuristic algorithm selecting up to 2–3 high-utility, domain-diverse devices per room for the interactive bottom dock.
  - Strict filtering out of low-utility clutter: robot vacuum sub-switches (e.g. `_customized_cleaning`, `_mop_`, `_clean_record`), sleep number / bed toggles (e.g. `_sleep_pause_mode`, `_super_sleep`), fridge/appliance sub-switches (`_ice_maker`, `_filter_reset`), and network/PoE infrastructure switches.
  - Domain-diverse allocation prioritizing room primary lighting, TV/media players (`media_player.*`), ceiling fans/exhaust fans (`fan.*` or bath fan switch), and environmental/security controls (`cover.*`, `lock.*`, `climate.*`).
  - Dynamic width-aware dock sizing: automatically limits controls to 2 for narrow rooms (< 155px width) and 3 for spacious rooms to ensure comfortable 46px icon dock spacing with zero edge clipping.
- **Clickable Room Names for Subview Navigation (`dashboard_manager.py`, `otis-companion-card.js`)**:
  - Placed an invisible, transparent interactive hotspot over room title vector text in Home Assistant's `picture-elements` card, routing directly to `/{dashboard_url}/area_{slug}` on click with pointer hover cursor and contextual tooltip.
  - Added room title click listeners (`.room-header`) in the Lovelace companion card SVG viewer to route instantly to the corresponding room controls.

## [1.6.6] - 2026-10-29

### Fixed & Improved
- **Floor Plan Element Layout & Overlap Resolution (`dashboard_manager.py`, `floorplan_parser.py`, `otis-companion-card.js`)**:
  - Replaced bulky `state-badge` climate widgets with native `state-icon` Material Design thermostat controls (`mdi:thermostat` with `#f97316` active heating color and tap `more-info`), eliminating oversized 70px badges and truncated entity names overflowing room borders.
  - Implemented an evenly spaced horizontal control dock along the bottom of each room (`rx + 30 + idx * 46`, `ry + rh - 24`), guaranteeing a generous 22px spacing buffer between adjacent lights, switches, and thermostat icons with zero wall collisions.
  - Positioned room navigation icons safely inset from right walls (`rx + rw - 32`) and below container banner titles (`ry + 38` for multi-room open spaces like Great Room and Master Suite), eliminating overlaps with architectural banner labels.
  - Set `.entity-badge { display: none; }` in blueprint SVG styling (and `display: inline !important;` in editor mode) to prevent static vector emoji circles from ghosting underneath native Lovelace controls.

## [1.6.5] - 2026-10-29

### Fixed
- **Blocking File I/O in Async Event Loop (`dashboard_manager.py`)**:
  - Resolved `homeassistant.util.loop` warning (`Detected blocking call to open with args ('/config/.storage/lovelace.otis_ai', 'r') inside the event loop`).
  - Wrapped `_merge_dashboard_config_preserving_user_views` inside `hass.async_add_executor_job` so synchronous storage file reading/parsing is delegated to the worker threadpool.

## [1.6.4] - 2026-10-29

### Fixed
- **Picture-Elements Floor Plan Configuration Errors (`dashboard_manager.py`, `test_core_rebuilt.py`)**:
  - Resolved Home Assistant frontend `Configuration error: Entity required` validation errors across all rooms on the Floor Plan subviews (`/otis-ai/floorplan` and `/command-center/floorplan`).
  - Home Assistant's native `picture-elements` card strictly requires an `entity` property on `type: state-label`. Replaced room navigation overlays with native `type: icon` elements using contextual room MDI icons (`_get_room_icon`) positioned in the upper right corner of each room (`rx + rw - 24`, `ry + 20`).
  - Room icons now cleanly display the room name as a hover tooltip and route directly to the room subview (`/{dashboard_url}/area_{slug}`) on tap without requiring dummy entities or triggering Lovelace card validation exceptions.
  - Updated test assertions in `tests/test_core_rebuilt.py` to validate room navigation elements under the compliant `type: icon` specification.

## [1.6.3] - 2026-10-29

### Fixed & Improved
- **Interactive Floor Plan Picture-Elements Rendering (`dashboard_manager.py`, `floorplan_parser.py`)**:
  - Floor Plan Studio subview (`/otis-ai/floorplan` and `/command-center/floorplan`) now reliably renders the generated vector floor plan image and interactive overlay elements.
  - Resolved `coordinator` reference bug in `DashboardManager` by directly connecting `FloorplanParser` to calculate orthogonal room layouts and canvas boundaries.
  - Appended dynamic version timestamp query parameter (`?v={mtime}`) to `/local/otis_floorplan.svg` to bypass browser static asset cache (which previously held cached 404s/broken images).
  - Ensured standalone floor plan SVG files generated by `FloorplanParser` include standard XML prologue (`<?xml version="1.0" encoding="UTF-8"?>`) required for error-free `<img>` rendering in Chromium and WebKit.
  - Dynamically builds clickable room navigation labels (navigating to `/{dashboard_url}/area_{slug}`), light toggles (`state-icon`), switch toggles (`state-icon`), and climate badges (`state-badge`).
- **Sentinel Alert Dismissal Persistence Across Navigation (`otis-companion-card.js`, `sentinel_manager.py`, `__init__.py`)**:
  - Muted/dismissed Sentinel alerts and recommendations now persist across view navigation and browser reloads via `localStorage` synchronization (`otis_dismissed_suggestions`).
  - Sentinel alert actions (`Ignore this alert` and `Ignore all alerts in this category`) immediately trigger proactive feed re-fetch and backend cache invalidation.
  - Enhanced `sentinel_manager.py` to index both raw anomaly IDs and entity IDs across alert prefixes (`sentinel_battery_critical_`, `sentinel_battery_low_`, `sentinel_node_offline_`, etc.) so ignored sensors stay permanently silenced even if battery percentage values fluctuate.
  - Fixed manager unpacking in `__init__.py` so `dashboard_manager` and `sentinel_manager` are properly routed in service handlers.
  - Prioritized Proactive Feed ordering to strictly render `CRITICAL` alerts ahead of `HIGH` alerts (`critical: 0 > high: 1 > medium: 2 > low: 3`).

### Added & Improved
- **Native Picture-Elements Floor Plan Studio & Control View (`dashboard_manager.py`)**:
  - Replaced `custom:otis-companion-card` on the Floor Plan subview (`/otis-ai/floorplan` and `/command-center/floorplan`) with a native Home Assistant **`picture-elements`** card.
  - Floor Plan Studio is now a true interactive visual control surface across the entire house layout:
    - Interactive `state-icon` for room lights with tap toggle (`#38bdf8` active glow).
    - Interactive `state-icon` for room outlets with tap toggle (`#a855f7` active glow).
    - Interactive `state-badge` for climate thermostats with tap more-info dialog.
    - Clickable styled room navigation labels that jump directly to each room's subview (`/command-center/area_<slug>`).
    - Zero admin controls or companion card clutter exposed to non-admin household users.
- **Permanent User Dashboard Customization Preservation (`dashboard_manager.py`)**:
  - Added `_merge_dashboard_config_preserving_user_views` to `DashboardManager`.
  - View 0 (`default_view` / `home`) containing the user's customized Otis AI Companion card settings, titles, and extra cards is 100% preserved across integration updates, service calls, and Home Assistant restarts.
  - Custom user subviews added outside the integration are also safely preserved.
- **Fixed `lovelace_dashboards` Startup Warning (`dashboard_manager.py`)**:
  - Safely reads and strips file contents before attempting `json.loads()`, resolving the `Could not parse lovelace_dashboards: Expecting value: line 1 column 1 (char 0)` startup log entry when the storage file is empty or whitespace.
- **Room & Studio View Intelligence & Clutter Elimination (`dashboard_manager.py`, `__init__.py`)**:
  - **Power & Outlets**: Excludes camera toggles (`detect`, `recording`, `snapshots`, `audio_detection`, `infrared`, `siren`, `email`, `ftp`, `push`, `review`), network & SNMP switch ports/firewall rules (`hades`, `snmp`, `switch-`, `port_`, `poe_`), pool equipment, and status LEDs (`*_led`, `ap_*_led`). Capped cleanly at max 8 genuine user outlets/switches.
  - **Cameras**: Excludes vacuum cleaner map entities (`Larry Poppins Current`, `Larry Poppins Saved Map`) from camera views. Multi-stream RTSP cameras (`_clear`, `_fluent`, `_recording`, `_snapshots_fluent`) are automatically grouped by physical camera and deduplicated to exactly 1 primary high-quality stream.
  - **Lighting**: Excludes status/indicator LEDs (`AP Entry LED`, `AP Back LED`, `Poolio LED`, `Foyer LED Indicator`) and ceiling fan speed controllers.
  - **Occupancy & Sensors**: Excludes AI object counters (`person_count`, `dog_count`, `all_count`, etc.) and disconnected network AP alerts. Displays primary motion, presence, and door/window contact sensors.
  - **Media & Audio**: Features a prominent `media-control` card for the primary active/playing media player (AVR, Shield TV, Apple TV) and compact 2-column tiles for secondary audio zones.
  - **Pool & Spa Controls**: Rooms with pool/spa hardware (e.g. Backyard) receive a dedicated, organized "Pool & Spa Controls" section.
  - **Contextual Room Icons**: Contextualizes room icons across the Home Command Center launchpad and navigation headers (`mdi:desk` for Office/Study, `mdi:theater` for Theater, `mdi:tree` for Backyard, `mdi:shower` for Bath, `mdi:sofa` for Great Room, `mdi:bed` for Master/Guest, `mdi:countertop` for Kitchen, `mdi:silverware-fork-knife` for Dining, `mdi:garage` for Garage, `mdi:dumbbell` for Gym, `mdi:washing-machine` for Laundry/Mudroom).

## [1.6.1] - 2026-10-29

### Added & Improved
- **Non-Admin User Command Center Dashboard (`dashboard_manager.py`)**:
  - Automatically generates and synchronizes `/command-center` with `require_admin: false`, making Studios and Room views accessible to family members and non-admin users.
  - Zero exposure to administrative features, AI conversation assistant, or blueprint editor.
  - Features home launcher tiles for Studios (Floor Plan, Media Studio, Security Center, Climate & Pool) and dynamic room navigation cards.
  - Registered service `otis_ai.create_command_center` to sync or regenerate on demand.
- **Interactive Floor Plan User Control Surface (`otis-companion-card.js`, `dashboard_manager.py`)**:
  - Re-architected `/otis-ai/floorplan` and `/command-center/floorplan` into a dedicated full-width **User Control View** (`mode: "floorplan_control"`).
  - Tapping light or switch markers toggles devices with instant visual feedback.
  - Tapping climate, media players, locks, or cameras triggers Home Assistant's native `hass-more-info` popup.
  - Tapping a room boundary opens an interactive Room Control drawer with quick-toggles for room devices and navigation to the room subview.
  - Hides walkthrough authoring banners and YAML export tools during control mode; Canvas Editor toggle is restricted exclusively to Admin/Owner accounts.
- **Proactive Feed Priority Sorting Fix (`otis-companion-card.js`)**:
  - Fixed rank sorting to place `CRITICAL` priority alerts strictly ahead of `HIGH` priority items (`critical: 0, high: 1, medium: 2, low: 3`).
- **Eliminated False-Positive Diagnostic Setpoint Alerts (`sentinel_manager.py`)**:
  - Completely generic heuristic filter strictly checks domain `sensor`, ignores entities with `entity_category in ("config", "diagnostic")` in the entity registry, and excludes setpoint/threshold keywords (`setpoint`, `threshold`, `limit`, `target`, `alarm`, `warning_level`, `shutdown`).
  - Completely prevents configuration numbers (e.g., UPS Low battery setpoint) from being misclassified as low battery telemetry.
- **Actionable Sentinel Alerts & Alert Muting (`sentinel_manager.py`, `otis-companion-card.js`)**:
  - Replaced nonsensical "Apply with 1-Click" buttons on informational watchdog alerts with contextual options:
    - `Ignore this alert`: Mutes the specific anomaly ID.
    - `Ignore all low battery alerts` / `Ignore all offline node alerts`: Mutes the entire alert category across restarts.
  - Added preference persistence in `.storage/otis_ai_sentinel_prefs` using Home Assistant's `Store`.
  - Registered `otis_ai.ignore_sentinel_alert` service.
- **Per-User Theme Profile Storage & Service Fixes (`theme_manager.py`, `__init__.py`, `otis-companion-card.js`)**:
  - Changed all action services (`apply_theme`, `generate_theme`, `remediate_anomaly`, etc.) from `SupportsResponse.ONLY` to `SupportsResponse.OPTIONAL`, resolving the `"The action requires responses and must be called with return_response=True"` frontend toast error.
  - Directly syncs applied themes to the logged-in user's profile via Home Assistant WebSocket `frontend/set_user_data` (`key: "theme"`).
  - Added user scope selector in the Theme Studio modal ("Current User" vs "All Users"), allowing Admins to optionally sync themes across all household user profiles via `.storage/frontend.user_data_<uid>`.
  - Enforced input, select, and surface background contrast variables on all dynamically synthesized themes to prevent white-on-white dropdown text.

## [1.6.0] - 2026-10-29

### Added & Improved
- **Phase 4: Visual Floor Plan Boundary & Marker Adjuster Canvas Editor (`floorplan_parser.py`, `otis-companion-card.js`)**:
  - **Full-Width Floor Plan Studio View**: Redesigned `/otis-ai/floorplan` subview with dedicated studio mode (`mode: "floorplan_studio"`). Takes up 100% full width and full viewport height with an expansive vector canvas, dedicated studio header, and quick return navigation to `/otis-ai`.
  - **Interactive Canvas Editor Mode**:
    - Embedded `🛠️ Canvas Editor` toggle button into the floor plan toolbar.
    - Drag-and-drop repositioning for device pins and badges directly on `/local/otis_floorplan.svg` with 60fps live SVG coordinate updates via inverted CTM matrix transforms.
    - Added floating live coordinate HUD (`📐 Pointer: X, Y`) displaying mouse and drag coordinates.
  - **Visual Area Boundary Polygon & Footprint Editor**:
    - Click any room boundary to activate interactive corner resize handles (`nw`, `ne`, `se`, `sw`) to dynamically expand or contract room footprints on the architectural blueprint.
    - Built-in Boundary Inspector card allows 1-click binding of SVG polygons to Home Assistant `area_id`s from the registry, renaming rooms, and fine-tuning dimensions.
  - **Layout Persistence (`otis_ai.update_floorplan_layout`)**:
    - Registered `update_floorplan_layout` service persisting modified badge coordinates, room rectangles, and polygon boundaries directly back into SVG markup and metadata storage.
  - **Device Pin Placer**:
    - Added `➕ Add Pin` modal to drop unmapped sensors, lights, climates, and cameras directly onto the blueprint.
- **Dynamic Theme Improvements & Usability Fixes (`theme_manager.py`, `otis-companion-card.js`)**:
  - **Instant Live Theme Activation**: Fixed theme application so clicking "Generate & Apply" or "Apply Live" immediately updates the active browser session without having to visit the User Profile settings, dispatching native `settheme` CustomEvents directly to the Home Assistant DOM root.
  - **Resolved White-on-White Contrast Issues**: Audited and enhanced all curated presets (including `midnight_slate`, `cyberpunk`, `oled_black`, `sunset_amber`, `emerald_luxury`, and `high_contrast`) with complete MDC surface, input, and select variables (`card-background-color`, `mdc-theme-surface`, `input-fill-color`, `input-ink-color`, `input-dropdown-icon-color`, `mdc-select-fill-color`, `mdc-text-field-fill-color`).
  - **Modern HA `modes` Compatibility**: Serializes both top-level variables and `modes: { dark: ... }` / `modes: { light: ... }` dictionaries so Home Assistant natively renders all form fields, menus, and dropdowns in high-contrast dark mode.


### Added & Improved
- **Phase 3: Otis Sentinel (Proactive Anomaly Detection & Watchdog) (`sentinel_manager.py`)**:
  - Implemented continuous telemetry watchdog audit engine across:
    - **Climate Short-Cycling & Extreme Runaway Deltas**: Detects extreme divergence between target and ambient temperatures to avoid compressor stress.
    - **Battery Health & Depletion Watchdog**: Flags critical (< 10%) and low (< 20%) battery sensors before unexpected device drops.
    - **Security Perimeter Watchdog**: Detects locks left unsecured or garage doors left open for > 60 minutes.
    - **Failed Integration Detection**: Audits `config_entries` for `SETUP_ERROR` or `SETUP_RETRY` states.
    - **Offline Infrastructure Nodes**: Identifies unavailable network switches, cameras, and media bridges.
  - **1-Click Self-Healing Remediation**:
    - Auto-lock and auto-close unlatched perimeter gates/doors.
    - Live reload failed integration config entries without Home Assistant restarts.
    - Adjust runaway HVAC targets to safe operational deadbands.
    - Create persistent alert notifications for critical battery replacements.
  - **Services Registered**:
    - `otis_ai.run_sentinel_watchdog`: Triggers a comprehensive telemetry audit.
    - `otis_ai.remediate_anomaly`: Executes atomic self-healing action for any anomaly.
    - `otis_ai.get_sentinel_telemetry`: Returns active anomaly status and remediation logs.
  - **Conversational Intelligence**: Ask Otis *"Run sentinel audit"* or *"Check system anomalies"* for instant status.
- **Floor Plan Studio Subview Optimization (`dashboard_manager.py`, `floorplan_parser.py`)**:
  - Changed `/otis-ai/floorplan` subview to host `custom:otis-companion-card` with `default_tab: "floorplan"`, providing the full interactive vector floor plan studio with zone filters, room inspection drawer, and live glowing badges.
  - Changed root SVG markup from percentage dimensions to explicit `width="1300" height="{canvas_height}"` and added cache-busting version query parameters (`?v=...`) to avoid stale 31-day browser cache issues.

## [1.5.8] - 2026-10-29

### Added & Improved
- **Phase 2 Step 1: Dynamic Themes & Collaborative AI Styling (`theme_manager.py`)**:
  - Implemented `ThemeManager` allowing Otis to dynamically synthesize and persist Home Assistant themes to `/config/themes/otis_<theme_name>.yaml`.
  - Natural language prompt parsing: extracts custom hex codes, named colors, border radius (`16px`, `8px`, `0px`), glow effects, and light/dark modes.
  - Curated master presets: `cyberpunk` (neon cyan/magenta glow), `midnight_slate` (frosted glass & sky blue), `oled_black` (pitch black zero-emission), `sunset_amber` (warm wood/charcoal & gold), `emerald_luxury` (forest green & mint), `nordic_frost` (clean Scandinavian daylight), `high_contrast` (accessibility sharp high-contrast).
  - Registered services with live responses: `otis_ai.generate_theme`, `otis_ai.apply_theme`, `otis_ai.list_themes`, and `otis_ai.delete_theme`.
  - Automatic `frontend.reload_themes` service invocation upon theme creation and deletion for instant zero-restart loading.
  - Instant live activation via conversational chat requests (e.g. "Generate a cyberpunk neon theme", "Apply midnight slate theme").
- **Dynamic AI Theme Studio in Lovelace Card (`otis-companion-card.js`)**:
  - Added dedicated `🎨 Themes` launcher chip in the launchpad header.
  - Interactive Theme Studio modal with 1-click live theme activation, swatches preview, and AI generation prompt input.
- **Lovelace Launchpad Row Hierarchy Fix (`otis-companion-card.js`)**:
  - Restructured launchpad into two distinct visual flex rows: Studios on row 1, and dynamic Rooms on a dedicated new row below.
- **Vector Floor Plan Studio SVG XML Escaping (`floorplan_parser.py`)**:
  - Added XML entity escaping (`html.escape`) to room names, container banners, and sub-zone labels, resolving XML parsing errors that prevented the Floor Plan subview from rendering.
  - Exposed cached `lovelace_yaml` via `capability_map["floorplan"]` for picture-elements interactive toggles.

## [1.5.7] - 2026-10-29

### Added & Improved
- **Dynamic Area/Room Subviews (`dashboard_manager.py`)**:
  - Automatically identifies all registered Home Assistant areas containing active entities and generates dedicated subviews (`/otis-ai/area_<slug>`) with `subview: true` and native `←` back navigation.
  - Automatically categorizes devices in each room into native Lovelace cards:
    - **Lighting & Power**: Brightness slider tile cards for lights and toggle tile cards for switches/outlets.
    - **Media & Audio**: Volume slider tile cards for media players.
    - **Climate & Comfort**: Thermostat cards with HVAC modes, fan tiles, and environmental telemetry sensors.
    - **Access & Sensors**: Lock and cover command tile cards, live camera feeds, and occupancy/presence sensor lists.
- **Hub-and-Spoke Architecture for Standalone Dashboards**:
  - Upgraded pro dashboards (`media_studio`, `security_center`, `climate_energy`, and new `whole_home`) to feature a central navigation Hub linking to dedicated spoke subviews (`zones`, `streamers`, `cinema`, `cameras`, `access`, `sensors`, `hvac`, `pool`, `comfort`, `area_<slug>`).
  - Added whole-home multi-room hub proposal to gap analysis whenever 3 or more active areas exist.
- **Continuous Discovery Synchronization (`__init__.py`)**:
  - Wired `dashboard_manager.async_ensure_admin_companion_dashboard(cap_map)` into `DiscoveryEngine.async_build_capability_map()` to automatically keep companion dashboard subviews synchronized as devices and rooms are added or reassigned.
- **Card-Level Dynamic Room Launchpad Chips (`otis-companion-card.js`)**:
  - Added dynamic room launchpad chips to the companion card header for instant one-tap navigation to any room subview.

## [1.5.6] - 2026-10-29

### Added & Improved
- **Hub-and-Spoke Subview Dashboards (`dashboard_manager.py`)**:
  - Automatically provisions native subpages (`subview: true`) under `/otis-ai`:
    - `media` (`/otis-ai/media`): Dedicated matrix amplifier audio routing, upstream streamer bridges, and theater displays.
    - `security` (`/otis-ai/security`): Alarm panel, smart locks, garage doors, camera snapshots, and presence sensors.
    - `climate` (`/otis-ai/climate`): HVAC thermostats, ceiling fans, pool telemetry, and comfort controls.
    - `floorplan` (`/otis-ai/floorplan`): Full architectural vector floor plan studio view.
  - Subviews stay cleanly hidden from the top dashboard tab bar while providing Home Assistant's native header back arrow (`←`) for zero-reload drill-down navigation.
- **Card-Level Studio Launchpad (`otis-companion-card.js`)**:
  - Added interactive glassmorphic subview launchpad chips (`.subviews-launchpad`) on the companion card header, allowing instantaneous 1-click drill-down navigation directly into specialized domain subviews via native `hass-navigate`.

## [1.5.5] - 2026-10-28

### Fixed & Improved
- **HACS & Hassfest GitHub Action Compliance**:
  - Added required `"issue_tracker"` URL to `manifest.json` for HACS validation.
  - Added missing `"http"`, `"frontend"`, and `"lovelace"` component dependencies and after-dependencies to `manifest.json`.
  - Removed core-supplied `pyyaml` from `manifest.json` `requirements` to comply with Home Assistant integration guidelines.
  - Added `CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)` in `__init__.py` to satisfy Home Assistant configuration schema requirements.
  - Updated `codeowners` to `@OtisPresley`.
- **Automated CI Workflow**:
  - Created `.github/workflows/ci.yaml` running Ruff linting, Python compilation (`compileall`), and 32-suite unit tests on push and pull requests, matching the `snmp-network-manager` CI pipeline.
  - Configured `tests/` directory with `test_core_rebuilt.py` for automated test discovery.

### Fixed & Improved
- **Robust Markdown Parsing & Code Token Protection (`otis-companion-card.js`)**:
  - Rebuilt `_renderMarkdown()` with early inline code tokenization (`@@@OTIS_IC_*@@@`), preventing wildcards (e.g. `matrix amp1*`) and entity underscores (e.g. `alarm_control_panel`) inside backticks from triggering runaway italics or corrupting subsequent markdown syntax.
  - Added multiline reconnect logic for standalone `###` heading markers followed by numbered/titled sections (`###\n1. Heading` → `### 1. Heading`), and converted orphaned `###` markers and double dashes (`--`) into clean `<hr>` dividers.
  - Protected heading numbers from premature newline splitting, allowing `### 1. Title` to render cleanly as `<h3>1. Title</h3>`.
  - Added support for markdown tables, blockquotes, checklist task items (`- [ ]`, `- [x]`), and word-boundary safe bold/italic formatting.
  - Updated live chat input preview detection (`updateLivePreview`) to recognize all markdown elements (`#`, `-`, `*`, `+`, `1.`, `--`, `---`, ````, `>`, `|`) identically to the assistant chat bubble renderer.

## [1.5.3] - 2026-10-28

### Improved & Fixed
- **Multiline YAML String Repair (`automation_manager.py`)**:
  - Updated `async_improve_automation()` to match and replace line-wrapped strings across newlines within the target automation block (e.g., `'Loading\n        ...'` → `'Loading...'`).
- **Automatic & Third-Party Backup Detection (`__init__.py`)**:
  - Updated `_inspect_config_files_sync()` and `async_generate_proactive_suggestions()` to inspect `.storage/backup` (`automatic_backups_configured: true` or configured backup `agents`) and installed backup integrations (`pcloud_backup`, `google_drive_backup`, `samba_backup`, `auto_backup`, `onedrive`), suppressing duplicate nightly backup suggestions when backups are already configured.
- **Spatially Coherent & Actuator-Verified Habit Mining (`__init__.py`)**:
  - Updated `cluster_sequences_to_routines()` to require at least one controllable actuator domain (`light`, `switch`, `media_player`, `select`, `fan`, `cover`, `lock`, `climate`) and reject sensor-only sequences (`binary_sensor.*`) or cross-house/opposite-perimeter triggers (e.g., `backyard` → `frontdoor`).
- **Deletable Pro Dashboards & Strict Active Entity Filtering (`dashboard_manager.py`, `__init__.py`)**:
  - Filtered out disabled registry entities (`disabled_by is not None`) and `unknown`/`unavailable` entities from `DiscoveryEngine` and `DashboardManager` templates.
  - Synchronized dynamically created dashboards with Home Assistant's live `DashboardsCollection` (`lovelace/dashboards/list` storage collection) so they can be edited and deleted directly from `Settings > Dashboards`.

## [1.5.2] - 2026-10-28

### Improved & Fixed
- **Panel Mode Dashboard & System Theme Default (`dashboard_manager.py`, `otis-companion-card.js`, `const.py`)**:
  - Updated the Admin-only **Otis AI** Lovelace dashboard (`/otis-ai`) to render in full-width **Panel Mode** (`type: "panel"`, `panel: true`) so the co-pilot and floor plan have maximum screen real estate.
  - Changed the default theme preset across `otis-companion-card.js` and `dashboard_manager.py` to `ha_native` (follows the active Home Assistant / system theme automatically).
- **Safe Blueprint & Automation Upgrade Auditing (`__init__.py`, `automation_manager.py`)**:
  - Updated `_inspect_config_files_sync()` to structurally extract entity references while ignoring `use_blueprint.path`, `action`/`service` calls, `trigger`/`condition` types, and file paths/extensions.
  - Replaced broad sequence matching with single-token typo detection and scoped `async_improve_automation()` replacements strictly to the target automation block.

## [1.5.1] - 2026-10-28

### Improved
- **Zero Hardcoding & Universal Home Assistant Portability (`spatial_manager.py`, `floorplan_parser.py`, `__init__.py`)**:
  - Replaced all home-specific room slugs, personal names, and entity assumptions with generic, dynamic archetype resolution so the integration works out-of-the-box on any Home Assistant installation.
  - Updated `SpatialGraphManager._infer_default_connections()` and `FloorplanParser._place_zone_rooms()` to match generic room archetypes (`office`, `bedroom`, `guest`, `gym`, `laundry`, `study`, etc.) via prefix/suffix normalization in addition to exact area IDs.
  - Generalized `_inspect_config_files_sync()` to dynamically detect `input_select` whitespace/ellipsis option mismatches (`<Option> ...` vs `<Option>...`), infer broken entity replacements from active same-domain entities within the same automation, and detect `input_select` recorder event size filters generically.
  - Generalized open-concept zone sync and indoor-to-outdoor lighting transition recommendations to dynamically resolve living/kitchen and entry/outdoor areas from the active Home Assistant area registry and spatial graph.

## [1.5.0] - 2026-10-28

### Added
- **Automatic Admin-Only Companion Dashboard & Pro Dashboard Generator (`dashboard_manager.py` & `__init__.py`)**:
  - Automatically creates and registers the **"Otis AI"** Lovelace dashboard (`/otis-ai`, `require_admin: true`) on integration startup, strictly accessible by **Owner and Admin** roles.
  - Added `_analyze_dashboard_gaps_sync()` and `async_create_professional_dashboard()` (`action_type: "create_dashboard"`) to scan `.storage/lovelace*` and generate professional multi-card dashboards (`Whole-Home Matrix Audio & Cinema Studio`, `Security, Locks & Perimeter Command Center`, `Climate, Pool & Comfort Operations`).
- **Deep Existing Automation Analyzer & 1-Click Automation Upgrades (`__init__.py` & `automation_manager.py`)**:
  - Added `_inspect_config_files_sync()` to index `automations.yaml` and `scripts.yaml` (aliases, normalized names, and every referenced `entity_id`) so recommendations never overlap with existing automations or router scripts (`Media: Bridge On Off`, `script.media_router`, `Security: Alarm System`, `Lighting: Adaptive Inside/Outside Lights`, `Area: Theater Lights`, etc.).
  - Added `async_improve_automation()` (`action_type: "improve_automation"`) to repair broken/typo entity references (`matrix_amp_1_sstudy` → `matrix_amp_1_study`, `climate.spa_thermostat` → `climate.pentair_13_d9_20_pool_heat`), fix `input_select` `"Loading ..."` option mismatch warnings, and upgrade multi-trigger automations from default `mode: single` to `mode: queued`.
- **HA System Performance, Log Hygiene & New Version Capability Discovery (`__init__.py` & `automation_manager.py`)**:
  - Added `async_optimize_system_config()` (`action_type: "optimize_system_config"`) to batch SQLite writes (`commit_interval: 30` in `configuration.yaml`) and filter 32KB `recorder.db_schema` event size warnings.
  - Added native Home Assistant **Floor Registry** capability discovery and 1-click synchronization (`action_type: "sync_ha_floors"`).
  - Eliminated the HA 2027.9 `device_registry.devices` mapping deprecation warning.

## [1.4.0] - 2026-10-28

### Added
- **Multi-Zone Matrix Audio & Cinema Topology Engine (`__init__.py`)**:
  - Added `_discover_media_topology()` to automatically detect Control4 / multi-zone matrix amplifiers, shared input sources (`Bridge`, `Gym Bridge`, `Server`, `Home Assistant`), upstream input streamers, and Cinema/TV display zones.
  - Added proactive **Multi-Zone Matrix Audio Router & Idle Power Guard** coordinator package (`create_package`) and **Cinema Mode Lighting & Shade Coordinator** recommendation.
- **Unified Security, Presence & SleepNumber Bedtime Topology Engine (`__init__.py`)**:
  - Added `_discover_security_topology()` scanning Alarmo/alarm panels, smart locks, garage covers, sirens, cameras, tracked persons, and SleepNumber bed occupancy sensors.
  - Added cohesive **Unified Security, Presence & Bedtime Coordinator** recommendation combining departure away-arming, SleepNumber night-arming, arrival disarming, and intrusion siren/lighting activation.
- **Smart Home Maturity Score & 1-Click Area Auto-Assignment (`__init__.py` & `otis-companion-card.js`)**:
  - Added `_discover_system_maturity()` calculating a 0–100 Smart Home Maturity Score across 5 weighted dimensions (`Spatial`, `Hygiene`, `Automations`, `Security`, `Media`) with automatic area inference for unassigned devices and entities (`auto_assign_areas`).
  - Added **Whole-Home Adaptive Occupancy Lighting Coordinator**, **Automated Nightly Home Assistant Backup**, and **Ecosystem Advisors** (`advisor_guide` for Music Assistant & Alarmo).
  - Updated Lovelace Capabilities Inspector (`otis-companion-card.js`) to display the Smart Home Maturity Score progress bar, 5-dimension breakdown, and Media/Security Architecture summaries.
  - Added category filter pills (`All`, `Lighting`, `Media`, `Security`, `Cleanup`, `System`) and action-specific button labels in the Proactive Feed.

### Improved
- **Architecture Refactor, Performance Caching & Cross-Tab Sync (`spatial_manager.py`, `floorplan_parser.py`, `__init__.py`, `otis-companion-card.js`)**:
  - Extracted shared area lookup and entity classification utilities into `spatial_manager.py`, deduplicated `floorplan_parser.py`, parallelized startup initialization, and added TTL caching in `DiscoveryEngine` with O(1) suggestion lookup.

## [1.3.9] - 2026-10-28

### Added
- **Architectural FloorPlan Blueprints & Unified Open-Concept `Great Room` (`floorplan_parser.py`)**:
  - Replaced floating grid boxes with contiguous architectural floorplan blueprints featuring proportional room footprints, shared walls, doorway cuts, staircase step markers (`Back Stairs UP ↗ / DN ↙`), and water-styled swimming pool basin.
  - Modeled `Great Room` as **one large unified open-concept room** containing the **Living Area**, **Kitchen Area** (`data-area-id="kitchen"`), and **Breakfast Nook** inside a single architectural shell.
  - Integrated **Outdoor & Perimeter** areas (`Frontyard` with wrap-around Driveway, `Backyard` with Deck/Grill/Hot Tub, and `Pool`) directly into the **Ground Floorplan**, while drawing the **Upper Level Floor Plan** (`Gym`, `Hallway`, `Theater`, `Amy's Office`, `Laundry Room`, `Guest Room`, `Master Bath`, and `Master`) separately.
- **Live Step-by-Step Walkthrough Progress (`__init__.py` & `otis-companion-card.js`)**:
  - Added live `GET /api/otis_ai/upload_walkthrough` progress polling and animated discovery badges (`Uploading videos` → `Analyzing videos` → `Discovered Frontyard` → `Discovered Foyer` → ... → `Done`).
  - Updated Floor Plan zone tabs (`All Floors`, `Ground & Outdoor`, `Upper Level`, `Outdoor Only`) to isolate and crop the SVG `viewBox` cleanly per floor plan.
- **Architectural Multi-Room Automation Recommendations (`__init__.py`)**:
  - Added *Great Room Open-Concept Zone Sync (Living • Kitchen • Nook)* and *Mudroom → Backyard Deck & Pool Evening Transition* proactive recommendations.

## [1.3.8] - 2026-10-28

### Added
- **Multi-Video Walkthrough Upload & Automatic Gemini Audio Transcription (`floorplan_parser.py`, `__init__.py`, `otis-companion-card.js`)**:
  - Updated the Walkthrough Upload Modal to support selecting or dragging **multiple video files at once** in a single upload batch.
  - Added `FloorplanParser.cleanup_previous_uploads()` so every new upload batch automatically deletes/overwrites previous walkthrough video and audio files in `/config/www/` to conserve Home Assistant disk space.
  - Added `FloorplanParser.async_analyze_walkthrough_audio()` using the configured Google Generative AI (Gemini) integration in Home Assistant to transcribe walkthrough audio tracks, extract spoken room order sequences, and infer room-to-room adjacency connections across all uploaded videos.
  - Automatically updates the `SpatialGraphManager` with newly discovered walkthrough transitions and persists `spoken_order` and `transcripts` in floorplan storage metadata.

### Fixed
- **SVG Floor Plan Multi-Zone Overlap Fix (`floorplan_parser.py`)**:
  - Fixed `_calculate_orthogonal_layout()` and `_render_svg_markup()` so `Upper Level & Suites` and `Outdoor & Perimeter` dynamically position below `Ground / Main Floor` instead of overlapping rows 1–3.
  - Added `data-zone` and `.room-group` attributes to SVG zones and room nodes so zone filter pills (`Main Floor`, `Upper Level`, `Outdoor`) and click-to-inspect room drawers work properly.

## [1.3.7] - 2026-10-28

### Fixed
- **Proactive Feed Priority Sorting (`__init__.py` & `otis-companion-card.js`)**:
  - Sorted proactive recommendation cards by priority (`high` → `medium` → `low`) in both `DiscoveryEngine.async_generate_proactive_suggestions()` and the Lovelace card renderer before slicing to `max_suggestions`.
  - Ensures high-priority recommendations (such as HVAC Energy Guard, Walkthrough Floor Plan generation, and critical orphan cleanups) always appear at the top of the Proactive Feed and are never pushed below medium/low cards.

## [1.3.6] - 2026-10-27

### Fixed
- **Floorplan & Lovelace YAML Export Fixes**:
  - Fixed `TypeError` in `otis_ai.generate_floorplan` service call where `FloorplanParser.async_generate_svg_floorplan()` received unexpected keyword arguments (`video_path`, `spoken_order`).
  - Added full support for `video_path`, `spoken_order`, `theme`, and `walkthrough_completed` in `async_generate_svg_floorplan`.
  - Added `has_walkthrough()` status check and persistent tracking in storage metadata (`walkthrough_completed`).
  - Proactive Feed now reliably surfaces the "Record Walkthrough for Vector Floor Plan" recommendation whenever a walkthrough video has not yet been processed, even if an initial layout preview exists.
  - Lovelace YAML button in the card toolbar is disabled with a descriptive tooltip when a walkthrough has not been completed, preventing premature export errors.
  - Added a walkthrough pending indicator banner on the Floor Plan tab linking directly to the mobile walkthrough upload modal.

## [1.3.5] - 2026-10-27

### Added
- **Phase 6: Multimodal Video-to-Floorplan SVG Parser (`floorplan_parser.py` & `__init__.py`)**:
  - Implemented `FloorplanParser` with multi-floor topological zone classification (`Main Floor`, `Upper Floor`, `Outdoor & Perimeter`).
  - Added native container audio extraction via `/usr/bin/ffmpeg` with zero external python dependencies.
  - Added speech callout regex parser matching room mentions in video walkthrough audio against Home Assistant registered areas.
  - Implemented multi-floor vector SVG layout engine with wall boundaries, doorways, room labels, and interactive entity badges.
  - Implemented procedural generation of Home Assistant `picture-elements` card YAML.
  - Registered `otis_ai.generate_floorplan` service and `/api/otis_ai/upload_walkthrough` HTTP endpoint.
  - Added proactive recommendation in the card feed when a floor plan does not exist, guiding the user to record/upload a walkthrough.
- **Interactive Floor Plan Card Tab & Walkthrough Modal (`otis-companion-card.js`)**:
  - Added dedicated "Floor Plan" navigation tab to the card.
  - Embedded responsive vector SVG floor plan viewer with zone filtering pills (`All Zones`, `Main Floor`, `Upper Level`, `Outdoor`).
  - Interactive SVG click handlers: toggle lights and switches directly by tapping badges, and inspect room details by clicking room boundaries.
  - Walkthrough Upload Modal with mobile recording guide, drag & drop video selector (`.mp4`, `.mov`, `.webm`), optional speech order override, and live progress indicator.
  - One-click "Copy Lovelace YAML" button to export the generated dashboard card.

## [1.3.4] - 2026-10-27

### Added
- **Phase 4: Spatial Adjacency Graph Engine (`spatial_manager.py` & `custom_components/otis_ai`)**:
  - Implemented `SpatialGraphManager` managing physical topological area adjacencies (which rooms connect to which) with persistent Home Assistant storage (`.storage/otis_ai_spatial_graph`).
  - Added intelligent auto-inference of topological default connections across home areas (Foyer, Hallway, Kitchen, Great Room, Master, Mudroom, Garage, etc.).
  - Added Breadth-First Search (BFS) pathfinding between any two connected areas in the home.
  - Registered dedicated services `otis_ai.get_spatial_map` and `otis_ai.update_spatial_map` for reading and dynamically connecting/disconnecting rooms.
- **Contextual Presence & Pathway Automations**:
  - `DiscoveryEngine` now generates proactive contextual pathway lighting recommendations when motion/presence in one room can illuminate transition lighting in an adjacent connected room after dark.
- **AI Co-Pilot Spatial Context Injection**:
  - Injected full area adjacency topology into the `OtisAIConversationAgent` system prompt, allowing Otis to understand room transitions and physical proximities in multi-turn chat.
- **Lovelace Capabilities Inspector (`otis-companion-card.js`)**:
  - Added dedicated Spatial Adjacency Graph inspection section under the Capabilities tab displaying all active physical room connection pairs.

## [1.3.3] - 2026-10-27

### Added
- **Real-Time Markdown Live Preview for Chat Input (`otis-companion-card.js`)**:
  - Added an auto-expanding live Markdown preview container (`.chat-live-preview`) directly above the chat input bar.
  - Automatically activates when markdown syntax is typed (such as `#` headings, `- ` / `* ` / `1. ` lists, `**bold**`, `*italic*`, ```code blocks```, blockquotes, horizontal rules, and links).
  - Renders instant visual feedback of headers, bullet points, and code formatting before sending the message.
  - Includes a quick-dismiss button (`✕`) for closing the preview on demand.
  - Preserves input draft state across dashboard re-renders and card updates (`_draftChatText`).
  - Improved user chat bubble typography for nested headings across all theme presets.

## [1.3.2] - 2026-10-27

### Added
- **Full Markdown Rendering in Assist Chat (`otis-companion-card.js`)**:
  - Implemented client-side Markdown rendering engine (`_renderMarkdown`) formatting headings (`#` to `####`), bold/italic (`**`, `*`, `__`, `_`), inline code, fenced code blocks with language tags, horizontal rules, bulleted lists, numbered lists, and hyperlinks (`[text](url)`).
  - Preprocessing filters that dynamically reformat compressed LLM outputs (e.g. inline `###` headings and `*` bullet points) into structured, readable multi-section layouts.
- **Auto-Expanding Multi-Line Chat Input (`otis-companion-card.js`)**:
  - Converted the chat input from a single-line input to an auto-growing multi-line textarea supporting up to 140px vertical expansion.
  - Added modern conversational keyboard ergonomics: press `Enter` to submit, and `Shift + Enter` to insert a newline.
  - Multi-line markdown formatting is automatically preserved and rendered in user chat bubbles as well.

### Changed
- **Lengthened Chat History Viewport (`otis-companion-card.js`)**:
  - Lengthened the chat viewport height to `min-height: 420px; max-height: 560px` to match the tall proactive feed view, allowing users to view full automation proposals, scripts, and audits without squished scrollbars.

## [1.3.1] - 2026-10-27

### Fixed
- **Assist Co-Pilot Chat Tab Conversation Routing (`otis-companion-card.js` & `custom_components/otis_ai`)**:
  - Resolved conversation failure where quick prompt buttons and chat input defaulted to Home Assistant's built-in local intent engine (`conversation.home_assistant`) with "Sorry, I couldn't understand that".
  - Introduced dedicated `otis_ai.chat` service for zero-friction direct chat communication with active spatial capability context and transparent LLM cascade.
  - Added dynamic `conversation_agent_id` resolution in `get_capability_map` and frontend card fallback cascades.
  - Implemented multi-turn conversation session tracking (`conversation_id`) ensuring interactive wizard confirmations (such as "yes" / "apply" automation proposals) persist across exchanges.

### Added
- **Real-Time Voice Audio Waveform Equalizer (`otis-companion-card.js`)**:
  - Dynamic 5-bar animated frequency waveform visualizer (`.voice-equalizer`) with glowing coral/neon accents during active microphone speech capture.
  - Enhanced listening feedback in the chat input container with real-time audio transcription streaming.

## [1.3.0] - 2026-10-27

### Added
- **Voice Input & Direct Microphone Speech Recognition (`otis-companion-card.js`)**:
  - Integrated direct microphone voice input button using Web Speech API (`SpeechRecognition` / `webkitSpeechRecognition`).
  - Real-time speech streaming into the Assist input box with pulsing glowing recording indicator animation.
  - Automatic prompt dispatch upon sentence completion with graceful fallback and error handling.

### Fixed
- **Orphan Detection Safeguards (`DiscoveryEngine`)**:
  - Suppressed orphan discovery during Home Assistant startup until `hass.is_running` is fully confirmed.
  - Protected installed integrations from orphan pruning: entities tied to existing `config_entry_id`s (even if offline, in setup retry, or disconnected) are strictly preserved and never flagged as orphans.
  - Removed `restored` state attribute as an orphan trigger to protect sleeping, battery, and disconnected devices.

## [1.2.0] - 2026-10-27

### Added
- **Theme Presets & Lovelace Theme Integration (`otis-companion-card.js`)**:
  - Implemented 6 curated theme presets: `cyberpunk` (Default Cyberpunk Neon), `midnight` (Deep Obsidian & Cobalt Navy), `emerald` (Matrix Forest & Cyber Mint), `sunset` (Velvet Twilight & Coral Amber), `light_frost` (Crisp Pearl White Frosted Glass), and `ha_native` (Seamless 100% Home Assistant Theme sync).
  - Native `card-mod` architecture: Root container rendered as `<ha-card>` with comprehensive `--otis-*` and standard `--ha-card-*` CSS custom properties, allowing direct YAML styling overrides via `lovelace-card-mod`.
  - Full-featured visual card editor (`OtisCompanionCardEditor`) with interactive dropdowns for theme preset selection, toggles for stats/suggestions/chat, and max suggestion count controls.
- **Historical Sensor Trend Analysis & Habit Routine Mining**:
  - Direct SQLite read-only index-assisted pattern mining against Home Assistant's `home-assistant_v2.db` via `async_mine_historical_habits`.
  - Temporal sequence clustering algorithm (`cluster_sequences_to_routines`) mining recurring multi-day trigger-action lifestyle patterns (e.g. morning routines, workout sequences, evening bedtime habits).
  - Automatically translates recurring habit patterns into 1-click executable proactive automation recommendations with confidence ratings.

## [1.1.0] - 2026-10-27

### Added
- **Phase 4 Lovelace UI Card (`otis-companion-card.js`)**:
  - Interactive glassmorphic dashboard card matching Otis brand aesthetics (Sky Cyan & Lavender Purple neon accents, frosted glass blur, responsive design).
  - Live AI status indicator with primary agent and failover cascade health chip.
  - Interactive proactive suggestions feed with priority tags, category icons, and 1-click execution (`otis_ai.apply_suggestion`).
  - Integrated Assist Co-Pilot Chat directly inside the card for conversational automation management, quick prompt chips, and instant YAML confirmation wizards.
  - Collapsible Home Capability Inspector (areas, active control entities, automations, and orphan warnings).
  - Visual card editor (`getConfigElement()`, `getStubConfig()`) for Lovelace dashboard builder support.
- **Proactive Suggestions Engine (`DiscoveryEngine`)**:
  - Automated detection of orphaned entities from deleted integrations with batch cleanup payloads.
  - Area motion + light discovery proposing occupancy-based lighting automations.
  - Climate HVAC energy guard proposals linked to open door/window contact sensors.
  - Security & evening bedtime routine suggestions.
  - AI failover redundancy warning when only 1 agent is active.
- **New Services**:
  - `otis_ai.get_suggestions`: Retrieve structured proactive suggestions list.
  - `otis_ai.apply_suggestion`: 1-click execution to write and reload proposed automations, scripts, or orphan cleanup.
- **Frontend Static Path Registration**: Automatically mounts `/otis_ai_card` static route for Lovelace card resources.

## [1.0.0] - 2026-10-27

### Added
- Complete core rebuild featuring `DiscoveryEngine`, `AutomationManager`, and `OtisAIConversationAgent`.
- Multi-agent failover engine with automatic recovery across Google Generative AI, OpenAI, and Ollama.
- Assist YAML intent generation pipeline with session memory and verbal confirmation wizard.
- Comprehensive unit test suite with 100% test pass rate.
- Home Assistant brand assets (8 standard light & dark icons and logos).
