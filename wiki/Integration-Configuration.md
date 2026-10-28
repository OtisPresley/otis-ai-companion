# ⚙️ Integration Configuration & Options Reference

This guide details all configuration settings, Options Flow parameters, AI failover cascades, and runtime heuristics available in **Otis AI Companion**.

---

## 🧭 Accessing the Options Flow

All integration options are managed dynamically via Home Assistant's UI without editing YAML configuration files.

To open the Options Flow:
1. Navigate to **Settings → Devices & Services**.
2. Locate the **Otis AI Companion** card.
3. Click the **Configure** button.

<!-- IMAGE PLACEHOLDER: [Otis AI Companion Options dialog showing primary and secondary AI conversation agent dropdowns, LLM context window slider, and habit confidence thresholds] -->

---

## 🧠 AI Provider & Conversation Cascade

Otis AI integrates directly with Home Assistant's native `assist_pipeline` and `conversation` framework while offering autonomous multi-agent failover:

<p align="center">
  <img alt="AI Model Fallback Pipeline" src="https://raw.githubusercontent.com/wiki/OtisPresley/otis-ai-companion/images/ai-fallback-pipeline.png" width="850" />
</p>

### Configuration Parameters:
* **Primary Conversation Agent**: Select the primary agent (e.g. `conversation.google_generative_ai`). This agent is used for conversational intent parsing, walkthrough audio transcription, and habit routine synthesis.
* **Fallback Cascade**: Select secondary and tertiary fallback conversation agents. If the primary provider encounters a network timeout, quota exceeded, or service interruption, Otis AI automatically re-routes the prompt to the secondary agent transparently.
* **Multi-Turn Context Window**: Number of conversation turns remembered in the interactive co-pilot session (default: `10`).

---

## 💾 Backup Detection & System Protection

Otis AI actively monitors system backup health to avoid redundant recommendations and protect the instance prior to upgrades:

* **Automatic Detection**:
  - Checks `.storage/backup` for `automatic_backups_configured: true` or active backup `agents`.
  - Scans installed integrations for verified backup providers (`pcloud_backup`, `google_drive_backup`, `samba_backup`, `auto_backup`, `onedrive`).
* **Suppression Rule**: If an active automated backup system is detected, the proactive suggestion for "Configure Nightly Backups" is automatically suppressed to eliminate UI noise.
* **Pre-Flight Health Gate**:
  - Before applying system updates or structural automations, Otis AI verifies that disk free space exceeds **10 GB** and validates that no uncommitted SQLite locks or corrupted database tables exist in `home-assistant_v2.db`.

---

## 🔄 Habit Mining & Discovery Thresholds

The background habit mining engine scans historical binary sensor and state transitions to propose smart routines:

* **Analysis Window**: Time span queried from recorder history (default: `14 days`).
* **Minimum Confidence Threshold**: Minimum recurring pattern frequency before surfacing a proposal in the Proactive Feed (default: `80%`).
* **Actuator Verification**: Enforces that any routine must include at least one controllable actuator (`light`, `switch`, `media_player`, `climate`, `cover`, `lock`, `fan`). Sensor-only sequences (e.g., motion sensor triggering another motion sensor) are rejected.
* **Perimeter Coherence Gate**: Rejects cross-house or opposite-perimeter pairings (e.g., motion at `backyard` triggering an action on `frontdoor`) to ensure proposed automations represent genuine physical habits.

---

## 🏛️ Floor Registry & Area Sync

* **Floor Registry Discovery**: Discovers native Home Assistant floors registered under `core.floor_registry`.
* **Sync HA Floors (`action_type: "sync_ha_floors"`)**: Automatically maps detected areas to their registered floors, ensuring the multi-floor SVG generator and spatial graph reflect your home's physical layout.
* **Area Archetype Normalization**: Uses regex token matching to normalize room slugs (e.g. `amy_s_office` → archetype `office`, `living_room_rear` → archetype `living`) so standard spatial rules apply regardless of naming quirks.

---

## 🧹 Entity Filtering & Hygiene

To maintain a responsive dashboard and prevent registry bloat:

* **Active Entity Gate**: Disabled entities (`disabled_by is not None`), `unknown` entities, and `unavailable` devices are excluded from dashboard templates and proactive recommendations.
* **Orphan Protection**:
  - Entities belonging to installed, active config entries (`config_entry_id`) are protected from orphan pruning, even if temporarily offline or in a setup retry state.
  - Prevents accidental deletion of sleeping Zigbee/Z-Wave devices or battery sensors with long polling intervals.
