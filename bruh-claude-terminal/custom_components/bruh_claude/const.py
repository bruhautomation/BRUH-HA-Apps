"""Constants for the BRUH Claude integration."""

DOMAIN = "bruh_claude"

CONF_TIMEOUT = "timeout"
CONF_NAME = "name"
CONF_SYSTEM_PROMPT = "system_prompt"
CONF_MODEL = "model"
CONF_ENABLE_CONVERSATION = "enable_conversation"
CONF_ENABLE_SENSORS = "enable_sensors"
DEFAULT_TIMEOUT = 120
# Automation tasks legitimately run longer than conversations (multi-step
# config edits). Must stay >= the add-on listener's BRUH_AUTOMATION_TIMEOUT
# default (300s) or results land after the bridge stops waiting.
DEFAULT_TASK_TIMEOUT = 300
DEFAULT_NAME = "BRUH Claude"
DEFAULT_SYSTEM_PROMPT = ""
# Haiku keeps voice interactions snappy; device control rarely needs a
# bigger model. Users can pick another model per agent in the options flow.
DEFAULT_MODEL = "haiku"

# Model choices shown in the config/options flow.
# Keys are passed to `claude -p --model <key>`.
# "default" means don't pass --model (use Claude Code's default).
AVAILABLE_MODELS = {
    "default": "Default (whatever the terminal uses)",
    "sonnet": "Claude Sonnet (balanced)",
    "opus": "Claude Opus (most capable, slowest)",
    "haiku": "Claude Haiku (fastest — recommended for voice)",
}

# Config entries come in two flavors: conversation agents (the default and
# the only kind that existed before 3.0) and insight jobs.
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_AGENT = "agent"
ENTRY_TYPE_INSIGHT = "insight"

# Insight job configuration
CONF_INSIGHT_TEMPLATE = "insight_template"
CONF_INSIGHT_PROMPT = "insight_prompt"
CONF_INSIGHT_INTERVAL = "interval_minutes"
CONF_INSIGHT_DAILY_AT = "daily_at"
DEFAULT_INSIGHT_TIMEOUT = 300

# Event fired on the HA bus when an insight job finishes
EVENT_INSIGHT_COMPLETE = "bruh_claude_insight_complete"
# Dispatcher signal (entry_id appended) for pushing results to the sensor
SIGNAL_INSIGHT_UPDATE = "bruh_claude_insight_update_{}"

# Shared directory under /config for add-on <-> integration communication
SHARED_DIR = ".bruh_claude"
REQUESTS_DIR = "requests"
RESPONSES_DIR = "responses"
TASKS_DIR = "tasks"
TASK_RESULTS_DIR = "task_results"
# Maps conversation_id -> Claude Code session uuid (written by the add-on's
# assist listener so follow-up turns resume the same Claude session).
SESSIONS_DIR = "sessions"
# Persisted insight results (survive HA restarts)
INSIGHTS_DIR = "insights"

# Internal HTTP API published by the add-on's worker pool (fast mode).
# Endpoint + token are exchanged over the shared /config volume; the
# integration falls back to file IPC whenever HTTP is unavailable.
API_ENDPOINT_FILENAME = "api_endpoint.json"
API_TOKEN_FILENAME = "api_token"
POOL_STATUS_FILENAME = "cache/pool_status.json"
