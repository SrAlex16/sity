from app.cortex.tool_schemas.actions import (
    CANCEL_PENDING_ACTION_TOOL,
    NO_ACTION_REQUIRED_TOOL,
)
from app.cortex.tool_schemas.file_agent import (
    APPLY_MULTI_FILE_UNIFIED_DIFF_PLAN_TOOL,
    APPLY_TEXT_PATCH_TOOL,
    APPLY_UNIFIED_DIFF_TOOL,
    FIND_LATEST_REVERSIBLE_FILE_CHANGE_TOOL,
    LIST_DIRECTORY_TOOL,
    LIST_FILE_CHANGES_TOOL,
    READ_FILE_TOOL,
    ROLLBACK_FILE_CHANGE_TOOL,
    ROLLBACK_LATEST_FILE_CHANGE_TOOL,
    WRITE_FILE_TOOL,
)
from app.cortex.tool_schemas.git import (
    GIT_PROPOSE_ACTION_TOOL,
    GIT_READ_BRANCHES_TOOL,
    GIT_READ_LOG_TOOL,
    GIT_READ_REMOTES_TOOL,
    GIT_READ_STATUS_TOOL,
)
from app.cortex.tool_schemas.google import (
    CALENDAR_CREATE_EVENT_TOOL,
    CALENDAR_DELETE_EVENT_TOOL,
    CALENDAR_EDIT_EVENT_TOOL,
    CALENDAR_LIST_EVENTS_TOOL,
    DRIVE_LIST_FOLDER_TOOL,
    DRIVE_SEARCH_TOOL,
    GMAIL_SEARCH_TOOL,
)
from app.cortex.tool_schemas.home_assistant import (
    HA_CALL_SERVICE_TOOL,
    HA_GET_STATE_TOOL,
    HA_LIST_ENTITIES_TOOL,
)
from app.cortex.tool_schemas.personality import UPDATE_PERSONALITY_SETTINGS_TOOL
from app.cortex.tool_schemas.senses import (
    CAPTURE_CAMERA_SNAPSHOT_TOOL,
    CLEAN_OLD_CAPTURES_TOOL,
    GET_CAPTURE_STORAGE_SUMMARY_TOOL,
    LIST_AUDIO_DEVICES_TOOL,
    LIST_CAMERA_DEVICES_TOOL,
    RECORD_AUDIO_SAMPLE_TOOL,
)
from app.cortex.tool_schemas.social import SOCIAL_RECALL_IMPRESSION_TOOL
from app.cortex.tool_schemas.spotify import (
    SPOTIFY_LIST_DEVICES_TOOL,
    SPOTIFY_LIST_PLAYLISTS_TOOL,
    SPOTIFY_NOW_PLAYING_TOOL,
    SPOTIFY_PAUSE_TOOL,
    SPOTIFY_PLAY_TOOL,
    SPOTIFY_PLAYLIST_TRACKS_TOOL,
    SPOTIFY_RECENTLY_PLAYED_TOOL,
    SPOTIFY_RESUME_PREVIOUS_TOOL,
    SPOTIFY_SET_VOLUME_TOOL,
    SPOTIFY_SKIP_TOOL,
)
from app.cortex.tool_schemas.system import (
    ADD_ALLOWED_SERVICE_TOOL,
    LIST_ALLOWED_DIRECTORY_TOOL,
    LIST_ALLOWED_SERVICES_TOOL,
    READ_DISK_USAGE_TOOL,
    READ_PROCESSES_TOOL,
    READ_SERVICE_STATUS_TOOL,
    READ_SYSTEM_STATUS_TOOL,
    REMOVE_ALLOWED_SERVICE_TOOL,
    RESTART_SERVICE_TOOL,
    START_SERVICE_TOOL,
    STOP_SERVICE_TOOL,
    SYSTEM_PROPOSE_ACTION_TOOL,
)
from app.cortex.tool_schemas.trace import (
    READ_OWN_TRACE_TOOL,
    READ_RECENT_DEBUG_EVENTS_TOOL,
    READ_TRACE_EVENTS_TOOL,
)
from app.cortex.tool_schemas.web import SEARCH_CONVERSATION_HISTORY_TOOL, WEB_SEARCH_TOOL

TOOL_BLOCKING_POLICIES: dict[str, str] = {
    # "immediate" — no tool execution; planner uses these to skip the tool loop
    "no_action_required": "immediate",
    "cancel_pending_action": "immediate",
    # "detachable" — can be moved to background if it exceeds the watchdog timeout
    "web_search": "detachable",
    # Everything else defaults to "blocking" (must finish before the AI responds)
}

BASE_TOOLSET: list[dict] = [
    # Minimal conversational toolset. No file tools here.
    # FILE_AGENT_TOOLSET is added structurally by toolset_selector:
    #   - explicit tool name detected from schemas/registry
    #   - file path detected by message_mentions_file_path
    WEB_SEARCH_TOOL,
    SEARCH_CONVERSATION_HISTORY_TOOL,
    NO_ACTION_REQUIRED_TOOL,
    # Google tools always available — keyword detection was too fragile.
    # Coste extra mínimo gracias al cache_control existente en tools.
    GMAIL_SEARCH_TOOL,
    CALENDAR_LIST_EVENTS_TOOL,
    CALENDAR_CREATE_EVENT_TOOL,
    CALENDAR_EDIT_EVENT_TOOL,
    CALENDAR_DELETE_EVENT_TOOL,
    DRIVE_SEARCH_TOOL,
    DRIVE_LIST_FOLDER_TOOL,
    # Home Assistant tools always available — same reason as Google.
    HA_LIST_ENTITIES_TOOL,
    HA_GET_STATE_TOOL,
    HA_CALL_SERVICE_TOOL,
    # Spotify tools always available — same reason as Google.
    SPOTIFY_NOW_PLAYING_TOOL,
    SPOTIFY_RECENTLY_PLAYED_TOOL,
    SPOTIFY_LIST_DEVICES_TOOL,
    SPOTIFY_PLAY_TOOL,
    SPOTIFY_PAUSE_TOOL,
    SPOTIFY_SKIP_TOOL,
    SPOTIFY_SET_VOLUME_TOOL,
    SPOTIFY_RESUME_PREVIOUS_TOOL,
    SPOTIFY_LIST_PLAYLISTS_TOOL,
    SPOTIFY_PLAYLIST_TRACKS_TOOL,
    # Social memory — impression of third-party users (user: sessions only, checked in handler).
    SOCIAL_RECALL_IMPRESSION_TOOL,
]

ALL_TOOLS = [
    WEB_SEARCH_TOOL,
    UPDATE_PERSONALITY_SETTINGS_TOOL,
    READ_OWN_TRACE_TOOL,
    READ_RECENT_DEBUG_EVENTS_TOOL,
    READ_TRACE_EVENTS_TOOL,
    READ_SYSTEM_STATUS_TOOL,
    READ_DISK_USAGE_TOOL,
    READ_PROCESSES_TOOL,
    READ_SERVICE_STATUS_TOOL,
    LIST_ALLOWED_DIRECTORY_TOOL,
    GIT_READ_STATUS_TOOL,
    GIT_READ_LOG_TOOL,
    GIT_READ_BRANCHES_TOOL,
    GIT_READ_REMOTES_TOOL,
    GIT_PROPOSE_ACTION_TOOL,
    RESTART_SERVICE_TOOL,
    START_SERVICE_TOOL,
    STOP_SERVICE_TOOL,
    SYSTEM_PROPOSE_ACTION_TOOL,
    ADD_ALLOWED_SERVICE_TOOL,
    REMOVE_ALLOWED_SERVICE_TOOL,
    LIST_ALLOWED_SERVICES_TOOL,
    LIST_CAMERA_DEVICES_TOOL,
    LIST_AUDIO_DEVICES_TOOL,
    CAPTURE_CAMERA_SNAPSHOT_TOOL,
    RECORD_AUDIO_SAMPLE_TOOL,
    GET_CAPTURE_STORAGE_SUMMARY_TOOL,
    CLEAN_OLD_CAPTURES_TOOL,
    READ_FILE_TOOL,
    LIST_DIRECTORY_TOOL,
    WRITE_FILE_TOOL,
    APPLY_TEXT_PATCH_TOOL,
    LIST_FILE_CHANGES_TOOL,
    APPLY_UNIFIED_DIFF_TOOL,
    APPLY_MULTI_FILE_UNIFIED_DIFF_PLAN_TOOL,
    FIND_LATEST_REVERSIBLE_FILE_CHANGE_TOOL,
    ROLLBACK_LATEST_FILE_CHANGE_TOOL,
    ROLLBACK_FILE_CHANGE_TOOL,
    CANCEL_PENDING_ACTION_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

TOOLS = ALL_TOOLS


TOOL_RISK_POLICY: dict[str, str] = {
    "list_camera_devices": "read",
    "list_audio_devices": "read",
    "capture_camera_snapshot": "sensitive_direct",
    "record_audio_sample": "sensitive_direct",
    "git_fetch": "safe_confirm",
    "git_pull": "critical_confirm",
    "git_push": "critical_confirm",
    "git_commit": "critical_confirm",
    "git_create_branch": "critical_confirm",
    "git_checkout_branch": "critical_confirm",
    "system_restart_service": "safe_confirm",
    "system_start_service": "safe_confirm",
    "system_stop_service": "safe_confirm",
    "system_config_update": "critical_confirm",
}
