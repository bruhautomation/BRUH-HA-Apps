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

# Shared directory under /config for add-on <-> integration communication
SHARED_DIR = ".bruh_claude"
REQUESTS_DIR = "requests"
RESPONSES_DIR = "responses"
TASKS_DIR = "tasks"
TASK_RESULTS_DIR = "task_results"
# Maps conversation_id -> Claude Code session uuid (written by the add-on's
# assist listener so follow-up turns resume the same Claude session).
SESSIONS_DIR = "sessions"
