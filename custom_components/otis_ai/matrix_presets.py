"""Multi-Zone Audio Matrix Amplifier Presets and Agnostic Discovery Profiles.

Provides vendor-agnostic architecture and first-class presets for multi-room matrix amplifiers:
- Universal / Generic Multi-Zone Matrix Amplifiers
- Russound Multi-Zone Controllers (MCA-C3, MCA-C5, MCA-66, MCA-88, RIO, RNET, MBX)
- Monoprice 6-Zone Whole-Home Audio / Dayton Audio (DAX66)
- Snap One / Episode / Triad Multi-Zone Matrix Amplifiers
- Control4 Multi-Zone Matrix Amplifiers
- HTD Whole-Home Audio (Lync, MC-66, MCA-66)
- AudioControl / Anthem / Savant Matrix Directors
"""

from __future__ import annotations

from typing import Any

# Supported Multi-Zone Matrix Amplifier Presets
MATRIX_PRESETS: dict[str, dict[str, Any]] = {
    "universal": {
        "id": "universal",
        "name": "Universal Multi-Zone Matrix Amplifier",
        "vendor": "Universal / Standards-Based",
        "description": "Agnostic multi-zone matrix audio architecture with multi-room zone grouping, volume synchronization, and input routing.",
        "platforms": ["universal", "generic"],
        "entity_patterns": ["matrix_amp", "matrix", "multiroom", "audio_matrix", "zone_amp", "whole_house", "whole_home"],
        "default_sources": ["Stream 1", "Stream 2", "Media Player", "TV Audio", "Auxiliary"],
        "min_zones": 2,
    },
    "russound": {
        "id": "russound",
        "name": "Russound Multi-Zone Controller (MCA / RIO / RNET)",
        "vendor": "Russound",
        "description": "Russound MCA-C3, MCA-C5, MCA-66, MCA-88, and MBX series multi-zone controllers.",
        "platforms": ["russound_rio", "russound_rnet", "russound"],
        "entity_patterns": ["russound", "mca", "rio", "mbx", "rnet"],
        "default_sources": ["Source 1", "Source 2", "Source 3", "Source 4", "Streamer", "AirPlay"],
        "min_zones": 2,
    },
    "monoprice": {
        "id": "monoprice",
        "name": "Monoprice 6-Zone Whole-Home Audio",
        "vendor": "Monoprice / Dayton Audio",
        "description": "Monoprice 6-Zone Multi-Zone Amplifier (MPR-6ZHMA) and Dayton Audio DAX66 matrix controllers.",
        "platforms": ["monoprice", "daytonaudio", "dax66"],
        "entity_patterns": ["monoprice", "dayton", "dax66", "zone_1", "zone_2", "zone_3", "zone_4", "zone_5", "zone_6"],
        "default_sources": ["Source 1", "Source 2", "Source 3", "Source 4", "Source 5", "Source 6"],
        "min_zones": 2,
    },
    "snapone_episode": {
        "id": "snapone_episode",
        "name": "Snap One / Episode / Triad Matrix",
        "vendor": "Snap One / Episode",
        "description": "Episode Response DSP Multi-Zone Matrix Amplifiers and Triad AMS high-resolution audio matrix systems.",
        "platforms": ["snapone", "episode", "binary", "triad"],
        "entity_patterns": ["episode", "snapone", "triad", "binary"],
        "default_sources": ["Input 1", "Input 2", "Input 3", "Input 4", "Digital 1", "Media Bridge"],
        "min_zones": 2,
    },
    "control4": {
        "id": "control4",
        "name": "Control4 Multi-Zone Matrix Amplifier",
        "vendor": "Control4",
        "description": "Control4 4-zone, 8-zone, and 16-zone matrix amplifiers with input bridge routing.",
        "platforms": ["control4", "control4_mediaplayer"],
        "entity_patterns": ["control4", "matrix_amp", "c4_amp"],
        "default_sources": ["Bridge", "Streamer", "AirPlay", "Turntable", "TV Audio"],
        "min_zones": 2,
    },
    "htd": {
        "id": "htd",
        "name": "HTD Whole-Home Audio (Lync / MC-66)",
        "vendor": "Home Theater Direct",
        "description": "HTD Lync 6/12 and Mid-Level MC-66 / MCA-66 whole-house audio matrix controllers.",
        "platforms": ["htd", "htd_mc", "htd_lync"],
        "entity_patterns": ["htd", "lync", "mc66", "mca66"],
        "default_sources": ["Source 1", "Source 2", "Source 3", "Source 4", "Source 5", "Source 6"],
        "min_zones": 2,
    },
    "audiocontrol": {
        "id": "audiocontrol",
        "name": "AudioControl / Anthem Multi-Zone Director",
        "vendor": "AudioControl / Anthem",
        "description": "AudioControl Director series network DSP matrix amplifiers and Anthem multi-room matrix processors.",
        "platforms": ["audiocontrol", "anthemav", "savant"],
        "entity_patterns": ["audiocontrol", "director", "anthem", "savant"],
        "default_sources": ["Input 1", "Input 2", "Streamer", "AirPlay", "Optical 1"],
        "min_zones": 2,
    },
}

ALL_MATRIX_PLATFORMS: set[str] = {
    p for preset in MATRIX_PRESETS.values() for p in preset["platforms"]
}

ALL_MATRIX_PATTERNS: tuple[str, ...] = tuple(
    pat for preset in MATRIX_PRESETS.values() for pat in preset["entity_patterns"]
)

TV_CINEMA_TOKENS: tuple[str, ...] = (
    "tv",
    "television",
    "theater",
    "theatre",
    "cinema",
    "projector",
    "receiver",
    "avr",
    "soundbar",
    "bravia",
    "shield",
    "roku",
    "apple_tv",
    "firetv",
    "chromecast",
    "googletv",
    "display",
)


def is_matrix_entity(entity_id: str, platform: str = "") -> bool:
    """Check if an entity_id or platform belongs to a known or generic matrix amplifier."""
    eid = entity_id.lower()
    plat = platform.lower()
    if plat and plat in ALL_MATRIX_PLATFORMS:
        return True
    return any(pattern in eid for pattern in ALL_MATRIX_PATTERNS)


def is_tv_cinema_player(entity_id: str, attributes: dict[str, Any] | None = None) -> bool:
    """Identify if a media player is a TV, projector, home theater AVR, or streaming display."""
    attrs = attributes or {}
    dev_class = str(attrs.get("device_class", "")).lower()
    if dev_class in ("tv", "receiver"):
        return True
    eid = entity_id.lower()
    friendly = str(attrs.get("friendly_name", "")).lower()
    return any(tok in eid for tok in TV_CINEMA_TOKENS) or any(tok in friendly for tok in TV_CINEMA_TOKENS)


def identify_matrix_preset(
    active_integrations: list[Any],
    media_players: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Identify the best matching matrix preset based on active integrations and media player platforms."""
    integration_domains: set[str] = set()
    for item in active_integrations:
        if isinstance(item, dict):
            integration_domains.add(str(item.get("domain", "")).lower())
        else:
            integration_domains.add(str(item).lower())

    player_platforms: set[str] = set()
    if media_players:
        for mp in media_players:
            p = str(mp.get("platform", "")).lower()
            if p:
                player_platforms.add(p)

    combined_domains = integration_domains | player_platforms

    # Check vendor presets first (non-universal)
    for pid, preset in MATRIX_PRESETS.items():
        if pid == "universal":
            continue
        if any(p in combined_domains for p in preset["platforms"]):
            return preset

    # Check entity pattern heuristics
    if media_players:
        for pid, preset in MATRIX_PRESETS.items():
            if pid == "universal":
                continue
            for mp in media_players:
                eid = str(mp.get("entity_id", "")).lower()
                if any(pat in eid for pat in preset["entity_patterns"]):
                    return preset

    return MATRIX_PRESETS["universal"]


def get_matrix_presets_list() -> list[dict[str, Any]]:
    """Return all matrix presets formatted for API / Lovelace inspection."""
    return list(MATRIX_PRESETS.values())

