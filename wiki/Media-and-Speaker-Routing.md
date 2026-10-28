# 🔊 Media Architecture & Dynamic Speaker Routing

Otis AI Companion features a presence-aware audio routing engine and a multi-zone matrix audio coordinator that eliminates blasting announcements into empty rooms while providing intelligent power management for multi-room amplifiers.

---

## 🎯 Contextual Presence-Based Speaker Routing

Standard Home Assistant TTS broadcasts announcements across all media players simultaneously or targets hardcoded speaker entities.

Otis AI replaces this with **Dynamic Presence-Based Audio Routing** (`notify_router`):

```
                        [ Notification Event ]
                       (e.g., Doorbell / Alert)
                                  │
                                  ▼
                     [ Dynamic Presence Engine ]
                     Scans active room occupancy:
                     • Area Motion Sensors
                     • mmWave Radar Presence
                     • Bed Occupancy Sensors
                                  │
             ┌────────────────────┴────────────────────┐
             ▼ Occupied Rooms Found                    ▼ Vacant / Away
  [ Targeted Speaker Routing ]              [ Default Announcement Zone ]
  Routes audio ONLY to active               Routes to central living
  media players in occupied areas.          zones or designated speakers.
```

### Key Engineering Enhancements:
1. **Defensive Boolean Handling**:
   Prevents Jinja2 template errors by enforcing explicit defaults for audio flags (e.g. `{{ notify_router | default(true) }}`).
2. **VLC Telnet Stream Synchronization**:
   When communicating with hardware players utilizing `vlc_telnet` or streaming endpoints, Otis AI enforces an active playback-wait gate:
   - Polls the player state until audio has completely finished playing (`idle` or `paused`).
   - Prevents abrupt cutoff of notification audio and avoids overlapping concurrent audio alerts.

---

## 🎛️ Multi-Zone Matrix Audio & Control4 Topology

For homes equipped with multi-zone matrix audio systems (such as Control4 8-Zone / 16-Zone amplifiers or Dayton/Monoprice matrix units):

### 1. Matrix Topology Discovery
Otis AI's `_discover_media_topology()` automatically indexes:
* All physical amplifier zone outputs (e.g. `matrix_amp_1_kitchen`, `matrix_amp_1_patio`, `matrix_amp_1_study`).
* Shared audio sources (`Bridge`, `Gym Bridge`, `Home Assistant`, `Server`).
* Upstream streaming devices (Apple AirPlay, Spotify Connect, Wiim, Bluesound).

### 2. Proactive Idle Power Guard
Multi-zone matrix amplifiers draw significant idle power when zones remain unmuted or active without an audio signal:
* Monitors zone output states and stream playback flags.
* When playback stops for a configurable timeout (e.g., 10 minutes), Otis AI powers down the amplifier zone to conserve energy and reduce heat in AV racks.

### 3. Cinema & Media Room Coordination
Automatically discovers Cinema and TV display zones, proposing integrated scene coordination:
* **Playback Active**: Automatically dims ambient room lighting to 15%, lowers motorized shades, and routes audio to surround-sound receivers.
* **Playback Paused**: Ramps lighting smoothly to 50% for intermission.
* **Playback Stopped**: Restores standard room lighting and engages the matrix idle power guard.

---

## 🎶 Music Assistant & Media Ecosystem Integration

Otis AI integrates seamlessly with **Music Assistant (MASS)** and native media players:
* Detects paired Music Assistant player providers.
* Advises on grouping strategies to avoid multicast network saturation.
* Automatically syncs input sources and volume normalization across grouped zones.
