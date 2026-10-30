"""Constants for the Otis AI Companion integration."""

DOMAIN = "otis_ai"

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

# Dashboard Constants
COMMAND_CENTER_DASHBOARD_ID = "command-center"
COMMAND_CENTER_DASHBOARD_URL_PATH = "command-center"
COMMAND_CENTER_DASHBOARD_TITLE = "Command Center"
COMMAND_CENTER_DASHBOARD_ICON = "mdi:view-dashboard"

