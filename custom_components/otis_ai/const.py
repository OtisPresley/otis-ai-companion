"""Constants for the Otis AI Companion integration."""

DOMAIN = "otis_ai"
INTEGRATION_VERSION = "0.1.42"

# Configuration Keys
CONF_CONVERSATION_AGENT = "conversation_agent"
CONF_SPATIAL_MAP_PATH = "spatial_map_path"
CONF_THEME_NAME = "theme_name"
CONF_REASONING_TIMEOUT = "reasoning_timeout"
CONF_LOCAL_LLM_ENABLED = "local_llm_enabled"
CONF_LOCAL_LLM_URL = "local_llm_url"
CONF_LOCAL_LLM_MODEL = "local_llm_model"
CONF_LOCAL_VISION_MODEL = "local_vision_model"
CONF_LOCAL_LLM_API_KEY = "local_llm_api_key"
CONF_CAMERA_STREAM_STRATEGY = "camera_stream_strategy"

# Camera Stream Strategy Options (Agnostic stream classification)
CAMERA_STRATEGY_MANAGED_PROXY = "managed_proxy"
CAMERA_STRATEGY_HIGH_EFFICIENCY = "high_efficiency"
CAMERA_STRATEGY_HIGH_DEFINITION = "high_definition"
DEFAULT_CAMERA_STREAM_STRATEGY = CAMERA_STRATEGY_MANAGED_PROXY

# Backward compatibility aliases for legacy strategy keys
CAMERA_STRATEGY_ALIASES = {
    "frigate": CAMERA_STRATEGY_MANAGED_PROXY,
    "fluent": CAMERA_STRATEGY_HIGH_EFFICIENCY,
    "clear": CAMERA_STRATEGY_HIGH_DEFINITION,
}

# Default Values
DEFAULT_THEME_NAME = "ha_native"
DEFAULT_SPATIAL_MAP_PATH = "otis_ai_spatial_map.json"
DEFAULT_REASONING_TIMEOUT = 60
DEFAULT_LOCAL_LLM_URL = "http://10.0.12.228:11434"
DEFAULT_LOCAL_LLM_MODEL = "qwen2.5:3b"
DEFAULT_LOCAL_VISION_MODEL = "llama3.2-vision:latest"
DEFAULT_PERIMETER_ANOMALY_CONFIDENCE = 0.65
DEFAULT_INTRUDER_TRACK_TIMEOUT = 180

# Service Names
SERVICE_GET_CAPABILITY_MAP = "get_capability_map"
SERVICE_GET_SUGGESTIONS = "get_suggestions"
SERVICE_APPLY_SUGGESTION = "apply_suggestion"
SERVICE_CHAT = "chat"
SERVICE_GET_SPATIAL_MAP = "get_spatial_map"
SERVICE_UPDATE_SPATIAL_MAP = "update_spatial_map"
SERVICE_GENERATE_FLOORPLAN = "generate_floorplan"
SERVICE_UPDATE_FLOORPLAN_LAYOUT = "update_floorplan_layout"
SERVICE_PIN_FLOORPLAN_ENTITY = "pin_floorplan_entity"
SERVICE_UNPIN_FLOORPLAN_ENTITY = "unpin_floorplan_entity"
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
SERVICE_REGENERATE_DASHBOARDS = "regenerate_dashboards"
SERVICE_EXECUTE_MACRO = "execute_macro"
SERVICE_ROLLBACK_MACRO = "rollback_macro"
SERVICE_CANCEL_PRECONDITIONING = "cancel_preconditioning"
SERVICE_LIST_MACROS = "list_macros"
SERVICE_AUDIO_HANDOFF = "audio_handoff"
SERVICE_MEDIA_FOLLOW_ME = "media_follow_me"
SERVICE_RELEASE_IDLE_SOURCES = "release_idle_sources"
SERVICE_NOTIFY_VOICE = "notify_voice"
SERVICE_GET_ENERGY_SUMMARY = "get_energy_summary"
SERVICE_LOAD_SHED = "load_shed"
SERVICE_RESTORE_SHED_LOADS = "restore_shed_loads"
SERVICE_GET_PRESENCE_STATES = "get_presence_states"
SERVICE_FUSE_PRESENCE = "fuse_presence"
SERVICE_TRILATERATE_BLE = "trilaterate_ble"
SERVICE_ANALYZE_CAMERA = "analyze_camera"
SERVICE_AUDIT_PERIMETER = "audit_perimeter"
SERVICE_GET_INTRUDER_TRACKS = "get_intruder_tracks"
SERVICE_ANNOUNCE_VISUAL_ALERT = "announce_visual_alert"
SERVICE_TOGGLE_VOICE_ANNOUNCEMENTS = "toggle_voice_announcements"
SERVICE_CONFIRM_PERSON_IDENTITY = "confirm_person_identity"
CONF_VOICE_ANNOUNCEMENTS_ENABLED = "voice_announcements_enabled"
CONF_VOICE_FILTER_PASSERSBY = "voice_filter_passersby"
ATTR_MEDIA_SESSION_OWNER = "session_owner"
ATTR_MEDIA_SESSION_USER = "session_user_id"
SERVICE_EVALUATE_CONTEXTUAL_ALERTS = "evaluate_contextual_alerts"
SERVICE_MINE_HABITS = "mine_habits"
SERVICE_GET_CIRCADIAN_CURVES = "get_circadian_curves"
SERVICE_AUDIT_HABIT_DEVIATIONS = "audit_habit_deviations"

# Autonomous Self-Healing Mesh Networking Services (Phase 6)
SERVICE_AUDIT_MESH_HEALTH = "audit_mesh_health"
SERVICE_HEAL_MESH_NODE = "heal_mesh_node"

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
SERVICE_DISMISS_RECOMMENDATION = "dismiss_recommendation"
SERVICE_RESTORE_RECOMMENDATION = "restore_recommendation"
SERVICE_RESET_DISMISSED_RECOMMENDATIONS = "reset_dismissed_recommendations"

# Voice Assist & Spatial Audio Ducking Services (Roadmap Item 9)
SERVICE_DUCK_MEDIA = "duck_media"
SERVICE_RESTORE_MEDIA = "restore_media"
SERVICE_GET_VOICE_ASSIST_STATUS = "get_voice_assist_status"
SERVICE_TEST_LOCAL_LLM = "test_local_llm"
SERVICE_BENCHMARK_LOCAL_LLM = "benchmark_local_llm"
SERVICE_PULL_LOCAL_LLM_MODEL = "pull_local_llm_model"
SERVICE_EXECUTE_TOOL_PLAN = "execute_tool_plan"

# Local LLM Embedding-Based RAG & Knowledge Store Services (Roadmap Item 1 / Phase 5 Step 3)
SERVICE_INDEX_DOCUMENT = "index_document"
SERVICE_QUERY_KNOWLEDGE = "query_knowledge_base"
SERVICE_INDEX_ENTITY_HISTORY = "index_entity_history"
SERVICE_CLEAR_KNOWLEDGE = "clear_knowledge_base"
SERVICE_SYNC_ENTITY_TELEMETRY = "sync_entity_telemetry"
SERVICE_INDEX_DEVICE_MANUAL = "index_device_manual"
SERVICE_TOGGLE_AUDIO_FOLLOW = "toggle_audio_follow"
CONF_AUDIO_FOLLOW_ENABLED = "audio_follow_enabled"

# Context-Aware Energy Arbitrage & Battery Scheduling (Phase 7)
SERVICE_OPTIMIZE_BATTERY_SCHEDULE = "optimize_battery_schedule"
SERVICE_GET_ENERGY_ARBITRAGE_PLAN = "get_energy_arbitrage_plan"
SERVICE_SCHEDULE_EV_CHARGING = "schedule_ev_charging"
SERVICE_EXECUTE_ENERGY_ARBITRAGE = "execute_energy_arbitrage"

# Spatial Audio Migration & Follow-Me (Phase 4 Step 3)
DEFAULT_AUDIO_MIGRATION_CONFIDENCE = 0.70
ATTR_AUDIO_FOLLOW_ACTIVE = "audio_follow_active"
ATTR_AUDIO_FOLLOW_SOURCE = "audio_follow_source"
ATTR_AUDIO_FOLLOW_TARGET = "audio_follow_target"
ATTR_AUDIO_FOLLOW_PLAYER = "audio_follow_player"
ATTR_AUDIO_FOLLOW_STATUS = "audio_follow_status"

# Dashboard Constants
COMMAND_CENTER_DASHBOARD_ID = "command-center"
COMMAND_CENTER_DASHBOARD_URL_PATH = "command-center"
COMMAND_CENTER_DASHBOARD_TITLE = "Command Center"
COMMAND_CENTER_DASHBOARD_ICON = "mdi:view-dashboard"
