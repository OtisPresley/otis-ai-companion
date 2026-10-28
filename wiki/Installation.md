# 📦 Installation & System Prerequisites

This guide covers everything required to deploy **Otis AI Companion** on your Home Assistant instance, from system dependencies and HACS setup to initial onboarding and post-install verification.

---

## 🛠️ System Prerequisites

Before installing the integration, ensure your Home Assistant host satisfies the following requirements:

### 1. Home Assistant Version
* **Minimum**: Home Assistant 2024.6.0 or newer.
* **Recommended**: Home Assistant 2025.11+ (supports modern Floor Registry, asynchronous storage collections, and native Assist pipeline APIs).

### 2. Host Capabilities
* **FFmpeg**: Required on the host system (`/usr/bin/ffmpeg`) for extracting audio tracks from video walkthrough files. FFmpeg is pre-installed in standard Home Assistant Operating System (HAOS) and Home Assistant Container environments.
* **SQLite Database**: Standard Home Assistant database (`home-assistant_v2.db`). The habit mining engine uses index-assisted, non-blocking queries directly against the recorder history.
* **Storage Space**: Minimum 10 GB free disk space recommended for safe updates, temporary walkthrough video processing, and automatic pre-flight backups.

### 3. Optional AI / LLM Integrations
Otis AI operates fully locally for spatial routing, habit clustering, and dashboard management. For multimodal walkthrough audio transcription and rich conversational co-pilot interactions, one of the following is recommended:
* **Google Generative AI (Gemini)** (Recommended for multimodal walkthrough parsing)
* **OpenAI Conversation**
* **Ollama / Local LLMs**

---

## 📥 Installation Methods

### Option A: HACS (Recommended)

Installing through the **Home Assistant Community Store (HACS)** guarantees automatic update checks and seamless version upgrades:

1. Open Home Assistant and navigate to **HACS → Integrations**.
2. Click the **three vertical dots** in the top right corner and select **Custom repositories**.
3. In the repository URL field, enter:
   ```text
   https://github.com/OtisPresley/otis-ai-companion
   ```
4. Set the **Category** dropdown to **Integration** and click **Add**.
5. Once added, search the HACS catalog for **Otis AI Companion** and click **Download**.

<!-- IMAGE PLACEHOLDER: [Searching for 'Otis AI Companion' in the HACS integrations store and clicking Download] -->

6. **Restart Home Assistant** to load the custom component files.

---

### Option B: Manual Installation

If you prefer installing directly over SSH, SFTP, or deployment scripts:

1. Download the latest release archive from [Releases](https://github.com/OtisPresley/otis-ai-companion/releases).
2. Copy the entire `custom_components/otis_ai` directory to your Home Assistant configuration directory:
   ```bash
   /config/custom_components/otis_ai/
   ```
3. Ensure file ownership and permissions match your Home Assistant process user:
   ```bash
   chown -R root:root /config/custom_components/otis_ai
   chmod -R 755 /config/custom_components/otis_ai
   ```
4. **Restart Home Assistant**:
   ```bash
   ha core restart
   ```

---

## ⚙️ Initial Onboarding Flow

Once Home Assistant has restarted:

1. Navigate to **Settings → Devices & Services**.
2. Click **Add Integration** in the bottom right corner.
3. Search for **Otis AI Companion** and select it.

<!-- IMAGE PLACEHOLDER: [Home Assistant Settings > Devices & Services > Add Integration dialog with Otis AI Companion selected] -->

4. The integration initiates its asynchronous discovery engine:
   * Discovers all configured Areas, Devices, and Entities.
   * Auto-infers the initial **Spatial Adjacency Graph**.
   * Mounts the Lovelace frontend card resource at `/otis_ai_card/otis-companion-card.js`.
   * Automatically creates the Admin-only **Otis AI** dashboard at `/otis-ai`.

<!-- IMAGE PLACEHOLDER: [Initial setup modal for Otis AI Companion prompting for Google Gemini API key and primary floorplan room list] -->

5. Click **Finish**.

> [!NOTE]
> **Admin-Only Security Gate**  
> The generated `/otis-ai` dashboard is registered with `require_admin: true`. Only users with the **Administrator** or **Owner** role can view this dashboard in the sidebar. Standard or guest users will not see the dashboard.

---

## 🧪 Post-Installation Verification

To verify that all components are functioning normally:

1. **Check the Sidebar**: Look for the **Otis AI** icon in your Home Assistant sidebar. Opening it will reveal the companion interface in full-width Panel Mode.

<!-- IMAGE PLACEHOLDER: [Home Assistant sidebar showing the newly mounted Otis AI icon leading to the /otis-ai full-width dashboard] -->

2. **Inspect Integration Diagnostics**:
   Go to **Developer Tools → Services** and run:
   ```yaml
   action: otis_ai.get_capability_map
   ```
   A comprehensive JSON capability payload including your active areas, entities, and proactive suggestions will return.
3. **Verify the Lovelace Card**:
   The frontend card script is automatically loaded. If you wish to add the card manually to any custom dashboard view, use the type `custom:otis-companion-card`.
