# 🔄 Automation Engine & Continuous Habit Mining

Otis AI Companion replaces hardcoded scripts and trial-and-error automation writing with an autonomous **continuous habit mining** engine and a safety-gated **YAML repair** system.

---

## 🧠 Non-Blocking SQLite Habit Mining

Home Assistant's recorder stores every state change in SQLite (`home-assistant_v2.db`). In large smart homes, this file often exceeds 5–10 GB. Reading this database synchronously would freeze Home Assistant's event loop and cause watchdog crashes.

Otis AI solves this by executing read-only, index-assisted queries inside an asynchronous executor job (`hass.async_add_executor_job`):
* Queries complete in under **50 milliseconds**.
* Extracts transition timestamps and entity states across a rolling 14-day analysis window.
* Groupings are filtered by domain (`binary_sensor`, `light`, `switch`, `media_player`, `climate`, `lock`).

---

## ⏱️ Temporal Sequence Clustering

Once state transitions are collected, the clustering algorithm identifies recurring multi-step user habits:

<p align="center">
  <img alt="Habit Mining and Synthesis Flow" src="https://raw.githubusercontent.com/wiki/OtisPresley/otis-ai-companion/images/habit-mining-pipeline.png" width="850" />
</p>

### Safety & Integrity Gates:
1. **Controllable Actuator Requirement**:
   To prevent frivolous automations, every proposed routine **must** include at least one controllable actuator (`light`, `switch`, `media_player`, `climate`, `cover`, `lock`, `fan`, `select`). Sequences consisting entirely of sensor state changes (e.g., motion sensor A followed by motion sensor B) are rejected.
2. **Opposite-Perimeter Rejection**:
   Sensors on opposing exterior perimeters (e.g., `backyard` motion followed by `frontdoor` lock) are rejected from automatic clustering to avoid false correlations caused by environmental noise (wind, wildlife, delivery trucks).

---

## 🛠️ Scoped Multiline YAML Repair

When upgrading or repairing existing automations, `automation_manager.py` enforces surgical precision:

<p align="center">
  <img alt="YAML Repair Block Scoping" src="https://raw.githubusercontent.com/wiki/OtisPresley/otis-ai-companion/images/yaml-repair-scoping.png" width="850" />
</p>

### 1. Scoped Target Block Replacement
All replacements in `async_improve_automation()` are bound strictly between the target automation's `- id:` marker and the subsequent automation's start. This guarantees that repairs to one automation never inadvertently modify another.

### 2. Multiline String Normalization
Home Assistant's YAML dumper frequently breaks long strings across indented lines:
```yaml
# Before: Broken multi-line wrapping
state: 'Loading
        ...'

# After: Repaired single string
state: 'Loading...'
```
Otis AI utilizes multiline regular expressions with whitespace collapsing to find and fix wrapped strings automatically.

### 3. Protected Structure Keywords
Lines defining Home Assistant core workflow syntax are strictly protected and never altered:
- `path:` (Blueprint paths)
- `action:` and `service:` (Service invocations)
- `trigger:` and `platform:` (Trigger definitions)
- `condition:` (Evaluation blocks)

### 4. Single-to-Queued Mode Upgrades
Automations with multiple triggers configured in default `mode: single` risk dropping execution if two events occur simultaneously (e.g. two motion sensors tripping within milliseconds). Otis AI identifies multi-trigger automations and upgrades them safely to `mode: queued` with `max: 10`.

---

## ⚡ 1-Click Execution via Proactive Suggestions

<!-- IMAGE PLACEHOLDER: [Proactive Suggestions Feed in the Lovelace card displaying a newly mined 'Morning Routine' habit card with priority badge, trigger summary, and 1-click 'Apply' button] -->

All discovered routines, entity typo fixes, and automation repairs appear as interactive cards in the **Proactive Suggestions Feed**:
* Each card shows the exact rationale, affected entities, and a one-click **Apply** button.
* When clicked, Home Assistant invokes `otis_ai.apply_suggestion`.
* The YAML file is updated atomically, a timestamped pre-flight backup is stored, and the Home Assistant automation engine reloads the file dynamically with zero downtime.
