# 🎛️ Otis Companion Lovelace Card

The **Otis Companion Lovelace Card** (`otis-companion-card.js`) is an interactive dashboard interface featuring frosted glassmorphism, responsive navigation tabs, real-time voice speech streaming, and vector SVG floor plan inspection.

---

## 🎨 Theme Presets & Styling

The card features 6 curated theme presets designed for different dashboard aesthetics:

| Theme Preset | Description | Visual Character |
| :--- | :--- | :--- |
| **`ha_native`** *(Default)* | Follows your active Home Assistant theme. | Seamlessly blends with light/dark system themes without jarring contrast. |
| **`cyberpunk`** | High-contrast dark cyberpunk aesthetic. | Glowing Cyan (`#00f0ff`) and Neon Purple (`#bf00ff`) accents on deep obsidian. |
| **`midnight`** | Deep navy and cobalt glass. | Muted cobalt blue (`#38bdf8`) with rich midnight navy frosted glass blur. |
| **`emerald`** | Matrix cyber forest. | Emerald green (`#10b981`) and cyber mint accents on dark charcoal. |
| **`sunset`** | Twilight amber and coral glow. | Warm amber (`#f59e0b`) and coral pink (`#f43f5e`) gradients. |
| **`light_frost`** | Crisp pearl white frosted glass. | Elegant frosted white glass with high readability for daytime wall tablets. |

---

## 🖥️ Full-Width Panel Mode Dashboard (`/otis-ai`)

When installed, Otis AI automatically generates a dedicated dashboard configured in **Panel Mode**:

```yaml
# Admin-only Panel Mode Dashboard definition
title: Otis AI
url: otis-ai
icon: mdi:robot-happy
require_admin: true
views:
  - title: Otis AI Companion
    path: companion
    panel: true
    type: panel
    theme_preset: ha_native
    cards:
      - type: custom:otis-companion-card
        theme_preset: ha_native
        max_suggestions: 10
        show_stats: true
        show_suggestions: true
        show_chat: true
```

> [!NOTE]
> In Panel Mode (`panel: true`), the card expands to fill 100% of the screen height and width without standard card margins, giving the interactive floor plan and chat view maximum screen real estate.

---

## 🧭 Interactive Tabs & Navigation

```
+──────────────────────────────────────────────────────────────────────────+
|  [ 🏠 Status ]  [ ⚡ Suggestions ]  [ 💬 Chat ]  [ 🗺️ Floor Plan ]  [ ⚙️ ]  |
+──────────────────────────────────────────────────────────────────────────+
```

### 1. 🏠 Status & Maturity Tab
* **Smart Home Maturity Progress Bar**: Real-time score (0–100) with drill-down metrics across Spatial, Hygiene, Automations, Security, and Media.
* **System Vital Statistics**: Active areas, controllable actuators, active automations, and orphan alerts.
* **AI Provider Health Chip**: Live connection status to primary and secondary LLM agents.

### 2. ⚡ Proactive Suggestions Feed
* **Category Filter Pills**: Filter recommendations by `All`, `Lighting`, `Media`, `Security`, `Cleanup`, or `System`.
* **Priority Sorting**: Sorted dynamically with `High` priority cards pinned to the top.
* **1-Click Actions**: Execute recommendations with a single click via `otis_ai.apply_suggestion`.

### 3. 💬 Assist Co-Pilot Chat
* **Direct Web Speech Voice Input**: Tap the microphone button to stream voice directly from your browser.
* **5-Bar Audio Waveform Visualizer**: Real-time animated equalizer bars respond to microphone audio input.
* **Auto-Expanding Input Box**: Textarea expands vertically (up to 140px) as you type. Use `Enter` to send and `Shift + Enter` for new lines.
* **Live Markdown Preview**: A responsive live preview pane (`.chat-live-preview`) renders headings, lists, bold text, and code blocks before you send your message.
* **Multi-Turn Memory**: Maintains conversation context across multiple turns for interactive wizards.

### 4. 🗺️ Interactive SVG Floor Plan
* **Multi-Floor Zone Pills**: Toggle between `All Floors`, `Ground & Outdoor`, `Upper Level`, and `Outdoor Only`.
* **Interactive Device Badges**: Click any light or switch badge in the floor plan to toggle the physical entity immediately.
* **Room Inspection Drawers**: Click room boundaries to view all devices, climate sensors, and states for that area.
* **Walkthrough Modal**: Drag-and-drop video upload to re-transcribe or re-generate floor plans.

---

## 🎨 Card-Mod CSS Variables

For custom styling via `lovelace-card-mod`, the card exposes CSS custom variables:

```yaml
type: custom:otis-companion-card
card_mod:
  style: |
    ha-card {
      --otis-bg-primary: rgba(15, 23, 42, 0.95);
      --otis-accent-cyan: #00f0ff;
      --otis-accent-purple: #c084fc;
      --otis-glass-blur: 24px;
      --otis-border-radius: 16px;
    }
```
