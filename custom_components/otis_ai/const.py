"""Constants for the Otis AI Companion integration."""

DOMAIN = "otis_ai"
INTEGRATION_VERSION = "1.11.19"

# Configuration Keys
CONF_CONVERSATION_AGENT = "conversation_agent"
CONF_SPATIAL_MAP_PATH = "spatial_map_path"
CONF_THEME_NAME = "theme_name"

# Default Values
DEFAULT_THEME_NAME = "ha_native"
DEFAULT_SPATIAL_MAP_PATH = "otis_ai_spatial_map.json"

# Service Names
SERVICE_GET_CAPABILITY_MAP = "get_capability_map"
SERVICE_GET_SUGGESTIONS = "get_suggestions"
SERVICE_APPLY_SUGGESTION = "apply_suggestion"
SERVICE_CHAT = "chat"
SERVICE_GET_SPATIAL_MAP = "get_spatial_map"
SERVICE_UPDATE_SPATIAL_MAP = "update_spatial_map"
SERVICE_GENERATE_FLOORPLAN = "generate_floorplan"
SERVICE_UPDATE_FLOORPLAN_LAYOUT = "update_floorplan_layout"
SERVICE_GENERATE_THEME = "generate_theme"
SERVICE_APPLY_THEME = "apply_theme"
SERVICE_LIST_THEMES = "list_themes"
SERVICE_DELETE_THEME = "delete_theme"
SERVICE_RUN_SENTINEL_WATCHDOG = "run_sentinel_watchdog"
SERVICE_REMEDIATE_ANOMALY = "remediate_anomaly"
SERVICE_GET_SENTINEL_TELEMETRY = "get_sentinel_telemetry"
SERVICE_IGNORE_SENTINEL_ALERT = "ignore_sentinel_alert"
SERVICE_CREATE_COMMAND_CENTER = "create_command_center"
SERVICE_SYNC_DASHBOARDS = "sync_dashboards"
SERVICE_EXECUTE_MACRO = "execute_macro"
SERVICE_ROLLBACK_MACRO = "rollback_macro"
SERVICE_LIST_MACROS = "list_macros"
SERVICE_AUDIO_HANDOFF = "audio_handoff"
SERVICE_MEDIA_FOLLOW_ME = "media_follow_me"
SERVICE_RELEASE_IDLE_SOURCES = "release_idle_sources"
SERVICE_NOTIFY_VOICE = "notify_voice"
SERVICE_GET_ENERGY_SUMMARY = "get_energy_summary"
SERVICE_LOAD_SHED = "load_shed"
SERVICE_RESTORE_SHED_LOADS = "restore_shed_loads"
SERVICE_GET_PRESENCE_STATES = "get_presence_states"
SERVICE_ANALYZE_CAMERA = "analyze_camera"
SERVICE_EVALUATE_CONTEXTUAL_ALERTS = "evaluate_contextual_alerts"
SERVICE_MINE_HABITS = "mine_habits"
SERVICE_GET_CIRCADIAN_CURVES = "get_circadian_curves"
SERVICE_AUDIT_HABIT_DEVIATIONS = "audit_habit_deviations"

# Autonomous Home Commissioning & Multi-Node Federation Services (Phase 10)
SERVICE_AUDIT_UNASSIGNED_ENTITIES = "audit_unassigned_entities"
SERVICE_AUTO_COMMISSION_ENTITIES = "auto_commission_entities"
SERVICE_REGISTER_FEDERATED_NODE = "register_federated_node"
SERVICE_REMOVE_FEDERATED_NODE = "remove_federated_node"
SERVICE_SYNC_FEDERATED_NODES = "sync_federated_nodes"
SERVICE_CALL_REMOTE_SERVICE = "call_remote_service"
SERVICE_GET_FEDERATION_STATUS = "get_federation_status"

# User Behavioral Rules & Onboarding Services (Roadmap Item 7)
SERVICE_GET_USER_RULES = "get_user_rules"
SERVICE_SET_USER_RULES = "set_user_rules"

# Voice Assist & Spatial Audio Ducking Services (Roadmap Item 9)
SERVICE_DUCK_MEDIA = "duck_media"
SERVICE_RESTORE_MEDIA = "restore_media"
SERVICE_GET_VOICE_ASSIST_STATUS = "get_voice_assist_status"

# Dashboard Constants
COMMAND_CENTER_DASHBOARD_ID = "command-center"
COMMAND_CENTER_DASHBOARD_URL_PATH = "command-center"
COMMAND_CENTER_DASHBOARD_TITLE = "Command Center"
COMMAND_CENTER_DASHBOARD_ICON = "mdi:view-dashboard"
