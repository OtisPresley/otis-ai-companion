# 🛠️ Troubleshooting & Diagnostic Workflows

This guide covers common issues, debugging procedures, and diagnostic steps for **Otis AI Companion**.

---

## 🔍 Common Issues & Solutions

### 1. Video Walkthrough Upload Fails or Transcribes No Rooms
* **Symptom**: The upload finishes, but no room transitions are detected, or you see `FFmpeg failed to extract audio`.
* **Fix**:
  - Ensure the video contains an active audio track where room names are spoken out loud.
  - Verify that FFmpeg is available on your host system:
    ```bash
    which ffmpeg
    ```
  - Ensure the video file format is standard `.mp4`, `.mov`, or `.webm`.
  - Check that `/config/www/` exists and has write permissions for the Home Assistant process.

---

### 2. Lovelace Card Shows Blank or Cached Older Version
* **Symptom**: After updating Otis AI, the dashboard displays an older card layout or a `Custom element doesn't exist: otis-companion-card` warning.
* **Fix**:
  - Force reload your browser cache using `Ctrl + F5` (Windows/Linux) or `Cmd + Shift + R` (Mac).
  - Clear the Home Assistant mobile app frontend cache via **App Settings → Debugging → Reset frontend cache**.
  - Verify that the card resource is loaded at `/otis_ai_card/otis-companion-card.js`.

---

### 3. Voice Input Microphone Button Does Not Respond
* **Symptom**: Clicking the microphone icon does nothing or displays an error.
* **Fix**:
  - The **Web Speech API** requires a secure context (**HTTPS** or `localhost`). If accessing Home Assistant over unencrypted `http://`, browsers block microphone access.
  - Ensure your browser has granted microphone permission to your Home Assistant URL in browser site settings.

---

### 4. Audio Announcements Not Playing in Occupied Rooms
* **Symptom**: Text-to-speech calls via `notify_router` do not trigger speakers.
* **Fix**:
  - Verify that the target area contains at least one active, unmuted `media_player` entity.
  - Verify that room presence sensors (motion or mmWave) are reporting `on` state in Developer Tools → States.
  - Ensure your `vlc_telnet` or streaming players have finished previous audio queues.

---

### 5. SQLite Habit Mining Slow or Timing Out
* **Symptom**: System logs report database queries taking longer than 200ms.
* **Fix**:
  - Home Assistant's SQLite database may need defragmentation. Run an auto-purge or repack:
    ```yaml
    action: recorder.purge
    data:
      repack: true
      keep_days: 7
    ```
  - Ensure `commit_interval` in `configuration.yaml` is set to `30` or higher to batch disk writes:
    ```yaml
    recorder:
      commit_interval: 30
    ```

---

## 📋 Enabling Debug Logging

To capture detailed trace logs for Otis AI Companion, add the following to your `/config/configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.otis_ai: debug
```

<!-- IMAGE PLACEHOLDER: [Home Assistant System Logs viewer filtered by 'custom_components.otis_ai' showing clean diagnostic log output] -->

Reload logging or restart Home Assistant. You can view the live output in **Settings → System → Logs**.
