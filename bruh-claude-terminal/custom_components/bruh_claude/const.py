"""Constants for the BRUH Claude integration."""

DOMAIN = "bruh_claude"

CONF_TIMEOUT = "timeout"
CONF_NAME = "name"
CONF_SYSTEM_PROMPT = "system_prompt"
CONF_MODEL = "model"
CONF_ENABLE_CONVERSATION = "enable_conversation"
CONF_ENABLE_SENSORS = "enable_sensors"
DEFAULT_TIMEOUT = 120
DEFAULT_NAME = "BRUH Claude"
DEFAULT_SYSTEM_PROMPT = ""
DEFAULT_MODEL = "default"

# Model choices shown in the config/options flow.
# Keys are passed to `claude -p --model <key>`.
# "default" means don't pass --model (use Claude Code's default).
AVAILABLE_MODELS = {
    "default": "Default",
    "sonnet": "Claude Sonnet (fast, balanced)",
    "opus": "Claude Opus (most capable)",
    "haiku": "Claude Haiku (fastest, cheapest)",
}

# Shared directory under /config for add-on <-> integration communication
SHARED_DIR = ".bruh_claude"
REQUESTS_DIR = "requests"
RESPONSES_DIR = "responses"
TASKS_DIR = "tasks"
TASK_RESULTS_DIR = "task_results"
